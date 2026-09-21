from __future__ import annotations

import asyncio
import ipaddress
import json
import mimetypes
import platform
import re
import shutil
import socket
import subprocess
import urllib.error
import urllib.request
import uuid
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from agno.tools import Toolkit

from quickops.host_adapter import HostAdapter
from quickops.storage import QuickOpsStorage, StorageError


class AssetDocumentError(ValueError):
    pass


class AssetDocumentStore:
    """Per-service blob storage plus bounded local text extraction for lexical retrieval."""

    max_file_bytes = 25 * 1024 * 1024
    _safe_id = re.compile(r"^[0-9a-f]{32}$")

    def __init__(self, root: Path, storage: QuickOpsStorage):
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.storage = storage

    def _service_dir(self, service_id: str) -> Path:
        if not self._safe_id.fullmatch(service_id):
            raise AssetDocumentError("无效的服务资产标识")
        directory = (self.root / service_id).resolve()
        if directory.parent != self.root:
            raise AssetDocumentError("无效的文档库目录")
        return directory

    @staticmethod
    def _extract_text(path: Path, mime_type: str) -> str:
        suffix = path.suffix.casefold()
        # Agno owns document-format parsing when its reader and optional dependency are
        # available. The narrow fallbacks below keep offline text/config ingestion usable.
        try:
            from agno.knowledge.reader.reader_factory import ReaderFactory

            reader = ReaderFactory.get_reader_for_extension(suffix or mime_type)
            reader.chunk = False
            documents = reader.read(path, name=path.stem)
            extracted = "\n\n".join(str(document.content or "") for document in documents)
            if extracted.strip():
                return extracted[:2_000_000]
        except (ImportError, OSError, ValueError, TypeError):
            pass
        if mime_type.startswith("text/") or suffix in {
            ".md",
            ".txt",
            ".log",
            ".csv",
            ".json",
            ".yaml",
            ".yml",
            ".xml",
            ".ini",
            ".conf",
            ".properties",
            ".sql",
            ".sh",
            ".py",
            ".js",
            ".ts",
        }:
            return path.read_text(encoding="utf-8", errors="replace")[:2_000_000]
        if suffix == ".docx":
            try:
                with zipfile.ZipFile(path) as archive:
                    root = ET.fromstring(archive.read("word/document.xml"))
                return "\n".join(text for text in root.itertext() if text.strip())[:2_000_000]
            except (OSError, KeyError, zipfile.BadZipFile, ET.ParseError):
                return ""
        if suffix == ".pdf":
            try:
                from pypdf import PdfReader

                return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)[
                    :2_000_000
                ]
            except (ImportError, OSError, ValueError):
                return ""
        return ""

    def save_bytes(
        self,
        service_id: str,
        *,
        filename: str,
        content: bytes,
        content_type: str | None = None,
        description: str = "",
        source_session_id: str | None = None,
    ) -> dict[str, Any]:
        if not content:
            raise AssetDocumentError("不能上传空文件")
        if len(content) > self.max_file_bytes:
            raise AssetDocumentError("单个文档不能超过 25 MB")
        name = Path(filename or "document").name.strip()[:255] or "document"
        mime_type = (
            (content_type or "").split(";", 1)[0].strip()
            or mimetypes.guess_type(name)[0]
            or "application/octet-stream"
        )
        document_id = uuid.uuid4().hex
        directory = self._service_dir(service_id)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{document_id}{Path(name).suffix[:20]}"
        path.write_bytes(content)
        try:
            return self.storage.create_asset_document(
                service_id,
                name=name,
                mime_type=mime_type,
                size=len(content),
                path=str(path),
                extracted_text=self._extract_text(path, mime_type),
                description=description,
                source_session_id=source_session_id,
            )
        except Exception:
            path.unlink(missing_ok=True)
            raise

    def import_path(
        self,
        service_id: str,
        source: Path,
        *,
        filename: str,
        content_type: str,
        source_session_id: str,
    ) -> dict[str, Any]:
        return self.save_bytes(
            service_id,
            filename=filename,
            content=source.read_bytes(),
            content_type=content_type,
            source_session_id=source_session_id,
        )

    def resolve(self, document_id: str) -> dict[str, Any]:
        document = self.storage.get_asset_document(document_id, public=False)
        if document is None:
            raise AssetDocumentError("文档不存在")
        path = Path(document["path"]).resolve()
        if path.parent != self._service_dir(document["service_id"]) or not path.is_file():
            raise AssetDocumentError("文档文件不可用")
        return document

    def delete(self, document_id: str) -> bool:
        try:
            document = self.resolve(document_id)
        except AssetDocumentError:
            return False
        self.storage.delete_asset_document(document_id)
        Path(document["path"]).unlink(missing_ok=True)
        return True

    def delete_service(self, service_id: str) -> None:
        directory = self._service_dir(service_id)
        if directory.is_dir():
            shutil.rmtree(directory)


class AssetKnowledgeToolkit(Toolkit):
    """Read and maintain the currently mounted service's isolated operational memory."""

    def __init__(
        self,
        storage: QuickOpsStorage,
        service_id: str,
        *,
        allow_record: bool = True,
        document_store: AssetDocumentStore | None = None,
    ):
        self.storage = storage
        self.service_id = service_id
        self.document_store = document_store
        tools = [
            self.get_mounted_service_status,
            self.search_service_knowledge,
            self.list_recent_service_events,
            self.read_service_document,
        ]
        if allow_record:
            tools.extend(
                [
                    self.record_service_event,
                    self.update_service_event,
                    self.delete_service_event,
                    self.list_service_documents,
                    self.update_service_document,
                ]
            )
            if document_store is not None:
                tools.append(self.delete_service_document)
        super().__init__(
            name="quickops_asset_knowledge",
            tools=tools,
            instructions=(
                "This toolkit is the isolated long-term memory and document library for the "
                "service asset mounted to this QuickOps conversation. Search it when prior "
                "incidents, maintenance decisions, runbooks, topology, deployment or configuration "
                "may affect the answer. Never search or mix another asset. Treat event recording "
                "as part of finishing operational work: after a verified incident, root-cause "
                "finding, deployment, configuration change, restart, recovery, durable workaround "
                "or operator decision, call record_service_event once with the evidence, action, "
                "result and remaining risk. Do not record routine observations, unverified "
                "hypotheses, conversational filler, credentials or other secrets."
            ),
            add_instructions=True,
        )

    def get_mounted_service_status(self) -> str:
        """Read the mounted service identity and latest automated health observation."""
        return json.dumps(
            self.storage.get_asset_service(self.service_id), ensure_ascii=False, default=str
        )

    def search_service_knowledge(self, query: str, limit: int = 8) -> str:
        """Search this service's events and document text using isolated lexical retrieval."""
        return json.dumps(
            self.storage.search_asset_knowledge(self.service_id, query, limit=limit),
            ensure_ascii=False,
            default=str,
        )

    def list_recent_service_events(self, limit: int = 20) -> str:
        """List recent monitoring, incident and maintenance events for this service."""
        return json.dumps(
            self.storage.list_asset_events(self.service_id, limit=limit),
            ensure_ascii=False,
            default=str,
        )

    def read_service_document(self, document_id: str) -> str:
        """Read extracted text from one document that belongs to the mounted service."""
        document = self.storage.get_asset_document(document_id, public=False)
        if not document or document["service_id"] != self.service_id:
            raise StorageError("Document does not belong to the mounted service")
        return json.dumps(
            {
                "id": document["id"],
                "name": document["name"],
                "description": document["description"],
                "content": document["extracted_text"],
            },
            ensure_ascii=False,
        )

    def record_service_event(
        self,
        title: str,
        content: str,
        severity: str = "info",
        category: str = "maintenance",
    ) -> str:
        """Persist a verified operational outcome or decision in this service's history."""
        event = self.storage.create_asset_event(
            self.service_id,
            title=title,
            content=content,
            severity=severity,
            category=category,
            source="agent",
        )
        return json.dumps(event, ensure_ascii=False, default=str)

    def update_service_event(
        self,
        event_id: str,
        title: str | None = None,
        content: str | None = None,
        severity: str | None = None,
        category: str | None = None,
    ) -> str:
        """Correct an existing event that belongs to the mounted service."""
        event = self.storage.get_asset_event(event_id)
        if not event or event["service_id"] != self.service_id:
            raise StorageError("运维事件不属于当前挂载的服务资产")
        changes = {
            key: value
            for key, value in {
                "title": title,
                "content": content,
                "severity": severity,
                "category": category,
            }.items()
            if value is not None
        }
        if not changes:
            raise StorageError("至少提供一个要修改的事件字段")
        updated = self.storage.update_asset_event(event_id, **changes)
        return json.dumps(updated, ensure_ascii=False, default=str)

    def delete_service_event(self, event_id: str) -> str:
        """Delete one incorrect event from the mounted service's history."""
        event = self.storage.get_asset_event(event_id)
        if not event or event["service_id"] != self.service_id:
            raise StorageError("运维事件不属于当前挂载的服务资产")
        return json.dumps({"deleted": self.storage.delete_asset_event(event_id)})

    def list_service_documents(self) -> str:
        """List documents archived in the mounted service's isolated library."""
        return json.dumps(
            self.storage.list_asset_documents(self.service_id),
            ensure_ascii=False,
            default=str,
        )

    def update_service_document(
        self,
        document_id: str,
        name: str | None = None,
        description: str | None = None,
    ) -> str:
        """Rename or revise the description of a mounted-service document."""
        document = self.storage.get_asset_document(document_id, public=False)
        if not document or document["service_id"] != self.service_id:
            raise StorageError("文档不属于当前挂载的服务资产")
        changes = {
            key: value
            for key, value in {"name": name, "description": description}.items()
            if value is not None
        }
        if not changes:
            raise StorageError("至少提供一个要修改的文档字段")
        updated = self.storage.update_asset_document(document_id, **changes)
        return json.dumps(updated, ensure_ascii=False, default=str)

    def delete_service_document(self, document_id: str) -> str:
        """Delete one document from the mounted service's isolated library."""
        document = self.storage.get_asset_document(document_id, public=False)
        if not document or document["service_id"] != self.service_id:
            raise StorageError("文档不属于当前挂载的服务资产")
        assert self.document_store is not None
        return json.dumps({"deleted": self.document_store.delete(document_id)})


class HostAssetCatalogToolkit(Toolkit):
    """Small, always-present catalog for the asset services on a bound host."""

    def __init__(
        self,
        storage: QuickOpsStorage,
        host_id: str,
        session_id: str,
        *,
        monitor: AssetMonitor | None = None,
        document_store: AssetDocumentStore | None = None,
    ):
        self.storage = storage
        self.host_id = host_id
        self.session_id = session_id
        self.monitor = monitor
        self.document_store = document_store
        super().__init__(
            name="quickops_host_assets",
            tools=[
                self.list_host_assets,
                self.get_host_asset,
                self.create_host_asset,
                self.update_host_asset,
                self.delete_host_asset,
                self.mount_host_asset_to_current_session,
                self.unmount_host_asset_from_current_session,
                self.check_host_asset_now,
            ],
            instructions=(
                "This is the current target host's service-asset catalog. Use list_host_assets "
                "before saying no service asset exists or asking the user to rediscover it. "
                "The service definitions are a first-class QuickOps control surface: inspect, "
                "create, update, delete, mount, unmount and run an immediate read-only probe when "
                "the user's intent calls for it. These operations change QuickOps asset metadata, "
                "not host services. Never create a duplicate merely to change an existing asset; "
                "call update_host_asset. A conversation can use a service's isolated events and "
                "documents only after that service is mounted."
            ),
            add_instructions=True,
        )

    def list_host_assets(self) -> str:
        """List every service asset and latest health state for this conversation's target host."""
        return json.dumps(
            self.storage.list_asset_services(self.host_id), ensure_ascii=False, default=str
        )

    def _get_current_host_asset(self, service_id: str) -> dict[str, Any]:
        asset = self.storage.get_asset_service(service_id)
        if asset is None or asset["host_id"] != self.host_id:
            raise StorageError("该服务资产不属于当前目标主机")
        return asset

    def get_host_asset(self, service_id: str) -> str:
        """Read one service asset's complete definition and latest probe state."""
        return json.dumps(
            self._get_current_host_asset(service_id), ensure_ascii=False, default=str
        )

    def create_host_asset(
        self,
        name: str,
        probe_type: str,
        probe_target: str,
        description: str = "",
        interval_seconds: int = 60,
        mount_to_current_session: bool = True,
    ) -> str:
        """Create a requested service asset for this host and optionally mount it."""
        normalized_name = name.strip()
        normalized_target = probe_target.strip()
        if not normalized_name or not normalized_target:
            raise StorageError("创建主机资产需要明确的服务名称和探测目标")
        existing = next(
            (
                item
                for item in self.storage.list_asset_services(self.host_id)
                if item["name"] == normalized_name
                and item["probe_type"] == probe_type
                and item["probe_target"] == normalized_target
            ),
            None,
        )
        asset = existing or self.storage.create_asset_service(
            host_id=self.host_id,
            name=normalized_name,
            description=description,
            probe_type=probe_type,
            probe_target=normalized_target,
            interval_seconds=interval_seconds,
            enabled=True,
        )
        if mount_to_current_session:
            self.storage.mount_session_asset(self.session_id, asset["id"])
        return json.dumps(
            {
                "asset": asset,
                "created": existing is None,
                "mounted_to_current_session": bool(mount_to_current_session),
                "note": "自动监控将在下一轮调度中执行首次只读探测。",
            },
            ensure_ascii=False,
            default=str,
        )

    def mount_host_asset_to_current_session(self, service_id: str) -> str:
        """Mount a same-host asset so its events and documents become available."""
        asset = self.storage.get_asset_service(service_id)
        if asset is None or asset["host_id"] != self.host_id:
            raise StorageError("该服务资产不属于当前目标主机")
        self.storage.mount_session_asset(self.session_id, service_id)
        return json.dumps(asset, ensure_ascii=False, default=str)

    def update_host_asset(
        self,
        service_id: str,
        name: str | None = None,
        description: str | None = None,
        probe_type: str | None = None,
        probe_target: str | None = None,
        interval_seconds: int | None = None,
        enabled: bool | None = None,
    ) -> str:
        """Update an existing service asset instead of creating a duplicate."""
        self._get_current_host_asset(service_id)
        changes = {
            key: value
            for key, value in {
                "name": name,
                "description": description,
                "probe_type": probe_type,
                "probe_target": probe_target,
                "interval_seconds": interval_seconds,
                "enabled": enabled,
            }.items()
            if value is not None
        }
        if not changes:
            raise StorageError("至少提供一个要修改的主机资产字段")
        if "probe_type" in changes or "probe_target" in changes:
            changes.update(status="unknown", status_detail="", last_checked_at=None)
        updated = self.storage.update_asset_service(service_id, **changes)
        return json.dumps(updated, ensure_ascii=False, default=str)

    def delete_host_asset(self, service_id: str, expected_name: str) -> str:
        """Delete an asset and its isolated history/documents after exact-name confirmation."""
        asset = self._get_current_host_asset(service_id)
        if expected_name.strip() != asset["name"]:
            raise StorageError("expected_name 与服务资产名称不一致，未执行删除")
        if self.document_store is not None:
            self.document_store.delete_service(service_id)
        deleted = self.storage.delete_asset_service(service_id)
        return json.dumps({"deleted": deleted, "service_id": service_id}, ensure_ascii=False)

    def unmount_host_asset_from_current_session(self) -> str:
        """Unmount the current service asset without deleting any asset data."""
        self.storage.mount_session_asset(self.session_id, None)
        return json.dumps({"mounted": False, "session_id": self.session_id}, ensure_ascii=False)

    async def check_host_asset_now(self, service_id: str) -> str:
        """Run the configured read-only health probe immediately and return the fresh state."""
        self._get_current_host_asset(service_id)
        if self.monitor is None:
            raise StorageError("资产探测器当前不可用")
        updated = await self.monitor.check_service(service_id)
        return json.dumps(updated, ensure_ascii=False, default=str)


class AssetMonitor:
    """Low-cost monitor with one read-only Agent investigation per unhealthy transition."""

    def __init__(
        self,
        storage: QuickOpsStorage,
        adapter: HostAdapter,
        *,
        on_anomaly: Callable[[dict[str, Any], dict[str, Any]], Awaitable[None]] | None = None,
    ):
        self.storage = storage
        self.adapter = adapter
        self.on_anomaly = on_anomaly
        self._stop = asyncio.Event()
        self._triage_tasks: set[asyncio.Task[None]] = set()

    @staticmethod
    def _validate_http_target(target: str) -> None:
        parsed = urlsplit(target)
        if parsed.scheme.casefold() not in {"http", "https"} or not parsed.hostname:
            raise ValueError("HTTP 探测地址必须是完整的 http(s) URL")
        if parsed.username or parsed.password:
            raise ValueError("HTTP 探测地址不能包含凭据")
        try:
            addresses = {
                item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or 80)
            }
        except socket.gaierror as error:
            raise ValueError("HTTP 探测地址无法解析") from error
        for value in addresses:
            address = ipaddress.ip_address(value)
            if address.is_link_local or address.is_multicast or address.is_unspecified:
                raise ValueError("HTTP 探测禁止访问链路本地、组播或未指定地址")

    @staticmethod
    def _native_service_probe(target: str) -> tuple[str, str]:
        if not re.fullmatch(r"[\w@.:-]{1,200}", target):
            return "unknown", "服务标识包含不支持的字符"
        system = platform.system().casefold()
        if system == "linux":
            argv = ["systemctl", "is-active", target]
        elif system == "darwin":
            argv = ["launchctl", "print", target]
        elif system == "windows":
            argv = ["sc.exe", "query", target]
        else:
            return "unknown", "当前系统不支持服务管理器探测"
        try:
            result = subprocess.run(argv, capture_output=True, text=True, timeout=8, check=False)
        except (OSError, subprocess.TimeoutExpired) as error:
            return "unknown", f"探测命令不可用：{type(error).__name__}"
        detail = (result.stdout or result.stderr).strip()[:4000]
        if system == "windows":
            healthy = result.returncode == 0 and "RUNNING" in detail.upper()
        else:
            healthy = result.returncode == 0
        return ("healthy" if healthy else "down"), detail or f"exit={result.returncode}"

    def check(self, service: dict[str, Any]) -> tuple[str, str]:
        kind, target = service["probe_type"], service["probe_target"]
        if kind == "process":
            output = self.adapter.process_list(service["host_id"], target)
            healthy = not output.startswith("No processes found")
            return ("healthy" if healthy else "down"), output[:4000]
        if kind == "system_service":
            return self._native_service_probe(target)
        if kind == "http":
            try:
                self._validate_http_target(target)
            except ValueError as error:
                return "unknown", str(error)
            request = urllib.request.Request(
                target, method="GET", headers={"User-Agent": "QuickOps-Monitor/1"}
            )
            try:
                with urllib.request.urlopen(request, timeout=8) as response:
                    self._validate_http_target(response.geturl())
                    code = int(response.status)
                return ("healthy" if code < 400 else "degraded"), f"HTTP {code}"
            except urllib.error.HTTPError as error:
                return ("degraded" if error.code < 500 else "down"), f"HTTP {error.code}"
            except (urllib.error.URLError, TimeoutError, ValueError) as error:
                return "down", f"HTTP 探测失败：{type(error).__name__}"
        if kind == "tcp":
            host, separator, port = target.rpartition(":")
            if not separator or not host or not port.isdigit():
                return "unknown", "TCP 探测目标应为 host:port"
            try:
                with socket.create_connection((host, int(port)), timeout=5):
                    return "healthy", f"TCP {target} 可连接"
            except (OSError, ValueError) as error:
                return "down", f"TCP {target} 不可连接：{type(error).__name__}"
        return "unknown", "未知探测类型"

    def _record_transition(
        self, service: dict[str, Any], status: str, detail: str
    ) -> dict[str, Any] | None:
        previous = service["status"]
        now = datetime.now(UTC)
        self.storage.update_asset_service(
            service["id"], status=status, status_detail=detail, last_checked_at=now
        )
        if status == previous or (previous == "unknown" and status == "healthy"):
            return None
        if status in {"down", "degraded"}:
            evidence = [f"自动探测：{detail}"]
            try:
                evidence.append(
                    "主机状态：\n" + self.adapter.system_status(service["host_id"])[:8000]
                )
                if service["probe_type"] in {"process", "system_service"}:
                    evidence.append(
                        "相关进程：\n"
                        + self.adapter.process_list(service["host_id"], service["probe_target"])[
                            :8000
                        ]
                    )
            except Exception as error:
                evidence.append(f"自动只读排查未完整执行：{type(error).__name__}")
            return self.storage.create_asset_event(
                service["id"],
                title=f"检测到服务{('异常' if status == 'degraded' else '不可用')}",
                content="\n\n".join(evidence),
                severity="critical" if status == "down" else "warning",
                category="automatic_investigation",
                source="system",
                metadata={"previous_status": previous, "current_status": status},
            )
        elif status == "healthy":
            return self.storage.create_asset_event(
                service["id"],
                title="服务已恢复",
                content=f"自动探测确认服务恢复正常。\n\n{detail}",
                severity="info",
                category="recovery",
                source="system",
                metadata={"previous_status": previous, "current_status": status},
            )
        return None

    def _schedule_anomaly_investigation(
        self, service: dict[str, Any], trigger_event: dict[str, Any]
    ) -> None:
        if self.on_anomaly is None:
            return
        task = asyncio.create_task(self.on_anomaly(service, trigger_event))
        self._triage_tasks.add(task)
        task.add_done_callback(self._triage_tasks.discard)
        task.add_done_callback(
            lambda completed: completed.exception() if not completed.cancelled() else None
        )

    async def check_service(self, service_id: str) -> dict[str, Any]:
        service = self.storage.get_asset_service(service_id)
        if service is None:
            raise StorageError("Asset service does not exist")
        status, detail = await asyncio.to_thread(self.check, service)
        transition = self._record_transition(service, status, detail)
        updated = self.storage.get_asset_service(service_id) or service
        if transition and status in {"down", "degraded"}:
            self._schedule_anomaly_investigation(updated, transition)
        return updated

    async def run(self) -> None:
        while not self._stop.is_set():
            now = datetime.now(UTC)
            for service in self.storage.list_asset_services():
                checked = service.get("last_checked_at")
                if not service["enabled"]:
                    continue
                if (
                    checked
                    and checked.replace(tzinfo=UTC) + timedelta(seconds=service["interval_seconds"])
                    > now
                ):
                    continue
                try:
                    await self.check_service(service["id"])
                except Exception:
                    continue
            with suppress(TimeoutError):
                await asyncio.wait_for(self._stop.wait(), timeout=5)

    def stop(self) -> None:
        self._stop.set()
        for task in tuple(self._triage_tasks):
            task.cancel()
