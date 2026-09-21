from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Any

from agno.agent import Agent
from agno.media import File as AgnoFile
from agno.media import Image as AgnoImage
from agno.os import AgentOS
from agno.tools.file import FileTools
from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from quickops.assets import (
    AssetDocumentError,
    AssetDocumentStore,
    AssetKnowledgeToolkit,
    AssetMonitor,
    HostAssetCatalogToolkit,
)
from quickops.attachments import AttachmentError, SessionAttachmentStore
from quickops.auth import AuthManager, LoginRateLimitedError
from quickops.domain import (
    AgentRunRequest,
    AgentRunResponse,
    AssetEventRequest,
    AssetServiceRequest,
    BootstrapResponse,
    LoginRequest,
    ManualCommandRequest,
    ManualCommandResponse,
    ModelConfigRequest,
    PermissionMode,
    SessionAssetMountRequest,
    SessionBranchRequest,
    SessionCreateRequest,
    SessionReviseRequest,
    SessionUpdateRequest,
)
from quickops.execution import CommandExecutionError, CommandPolicy, CommandRisk, default_executor
from quickops.host_adapter import HostAdapter, HostNotAllowedError
from quickops.reports import ReportArtifactError, ReportArtifactStore, ReportToolkit
from quickops.run_manager import BackgroundRunManager, _friendly_run_error, _message_segments
from quickops.runtime import AGENT_ID, build_runtime
from quickops.settings import Settings
from quickops.storage import QuickOpsStorage, StorageError
from quickops.terminal_manager import default_terminal_manager
from quickops.title_generator import AgnoSessionTitleGenerator, fallback_title
from quickops.tool_registry import TOOLKIT_SPECS, toolkit_catalog
from quickops.toolkit import (
    AutonomousSafeOperationsToolkit,
    OperatorTerminalContextToolkit,
    SharedSessionOperationsToolkit,
)

LOGGER = logging.getLogger(__name__)

DEFAULT_MODEL_CONFIG_ID = "siliconflow-deepseek-v4-flash"
ENABLED_PERMISSION_MODES = [
    PermissionMode.READONLY,
    PermissionMode.APPROVAL,
    PermissionMode.DELEGATED_APPROVAL,
    PermissionMode.FULL_ACCESS,
]


def _public_message(message: dict[str, Any]) -> dict[str, Any]:
    metadata = message.get("metadata") or {}
    content = message["content"]
    if message["role"] == "user" and metadata.get("source") == "ai_composer":
        # Old builds could persist a trailing newline/space from IME or textarea state. Keep the
        # durable row intact for audit/export, but never turn that transport artifact into bubble
        # height after reload. Manual Shell input remains byte-for-byte untouched.
        content = content.strip()
    return {
        "id": message["id"],
        "session_id": message["session_id"],
        "role": message["role"],
        "kind": metadata.get("kind", message["message_type"]),
        "message_type": message["message_type"],
        "content": content,
        "status": metadata.get("status"),
        "tools": metadata.get("tools", []),
        "created_at": message["created_at"],
        "metadata": metadata,
    }


def create_app(
    settings: Settings | None = None,
    *,
    host_adapter: HostAdapter | None = None,
    agent_factory: Callable[
        [Settings, HostAdapter | None], tuple[Agent, HostAdapter, object]
    ] = build_runtime,
) -> FastAPI:
    resolved_settings = settings or Settings()
    agent, adapter, database = agent_factory(resolved_settings, host_adapter)
    storage = QuickOpsStorage(resolved_settings.quickops_db_file)
    # Audit events are durable records. Remove the retired retention preference left by older
    # builds; no background task prunes quickops_audit_events.
    storage.delete_setting("audit_retention_days")
    attachment_store = SessionAttachmentStore(
        resolved_settings.quickops_db_file.parent / "attachments"
    )
    asset_document_store = AssetDocumentStore(
        resolved_settings.quickops_db_file.parent / "asset-documents", storage
    )
    report_store = ReportArtifactStore(resolved_settings.quickops_db_file.parent / "reports")
    terminal_manager = default_terminal_manager(
        resolved_settings.quickops_workspace_root, storage=storage
    )
    ai_command_policy = CommandPolicy((resolved_settings.quickops_workspace_root,))

    def auto_confirm_safe_requirement(requirement: dict[str, Any], session_id: str) -> bool:
        tool = requirement.get("tool_execution") or {}
        name = str(tool.get("tool_name") or "")
        if name not in {
            "execute_change_command",
            "execute_elevated_command",
            "exec_change_in_container",
            "exec_elevated_in_container",
        }:
            return False
        tool_args = tool.get("tool_args") or {}
        args = tool_args.get("args") if isinstance(tool_args, dict) else None
        if not isinstance(args, list) or not args or not all(isinstance(arg, str) for arg in args):
            return False
        if args[0] == "cd":
            return len(args) == 2
        try:
            risk = ai_command_policy.classify_argv(args).risk
            requirement["risk"] = risk.value
            session = storage.get_session(session_id) or {}
            mode = session.get("permission_mode")
            if mode == PermissionMode.DELEGATED_APPROVAL.value:
                return risk in {CommandRisk.READONLY, CommandRisk.LOW, CommandRisk.MEDIUM}
            return risk == CommandRisk.READONLY
        except (ValueError, TypeError):
            return False

    run_manager = BackgroundRunManager(
        storage, auto_confirm_requirement=auto_confirm_safe_requirement
    )
    auth_manager = AuthManager(
        username=resolved_settings.quickops_auth_username,
        password=resolved_settings.quickops_auth_password,
        ttl_seconds=resolved_settings.quickops_auth_session_ttl_hours * 60 * 60,
    )
    session_database_configs: dict[str, dict[str, dict[str, Any]]] = {}

    if not storage.list_model_configs():
        storage.save_model_config(
            DEFAULT_MODEL_CONFIG_ID,
            name=resolved_settings.model_id.rsplit("/", 1)[-1],
            provider="SiliconFlow",
            model_id=resolved_settings.model_id,
            base_url=resolved_settings.model_base_url,
            api_key=resolved_settings.siliconflow_api_key,
            thinking_mode=resolved_settings.thinking_mode,
            max_context_k=max(1, resolved_settings.max_context_tokens // 1000),
            is_default=True,
        )

    async def investigate_asset_anomaly(
        service: dict[str, Any], trigger_event: dict[str, Any]
    ) -> None:
        """Run one policy-bounded Xiaowei investigation for a health transition."""
        model = next(
            (item for item in storage.list_model_configs(enabled_only=True) if item["is_default"]),
            None,
        )
        credentials = storage.get_model_credentials(model["id"]) if model else None
        if not credentials:
            storage.create_asset_event(
                service["id"],
                title="小维自动排查未启动",
                content="探针已记录异常，但当前没有可用的默认模型凭据。可从该事件创建正式会话继续处理。",
                severity="warning",
                category="automatic_agent_investigation_failed",
                source="system",
                metadata={"trigger_event_id": trigger_event["id"], "follow_up_available": True},
            )
            return
        target_host = next(
            (host for host in adapter.list_hosts() if host.id == service["host_id"]), None
        )
        if target_host is None:
            return
        try:
            runtime_settings = resolved_settings.model_copy(
                update={
                    "model_id": credentials["model_id"],
                    "model_base_url": credentials["base_url"],
                    "siliconflow_api_key": credentials["api_key"],
                    "model_provider": credentials["provider"],
                    "thinking_mode": credentials["thinking_mode"],
                    "max_context_tokens": credentials["max_context_k"] * 1000,
                    "quickops_target_host_id": target_host.id,
                    "quickops_target_host_name": target_host.name,
                    "quickops_target_host_ip": target_host.ip,
                    "quickops_target_host_platform": target_host.platform,
                    # Background monitoring is observation-only. Optional toolkits are omitted
                    # so a user toggle can never expand this unattended run into mutation.
                    "enabled_toolkits": (),
                }
            )
            guard_mode = service.get("guard_mode") or "diagnose"
            command_toolkit = None
            if guard_mode == "safe_repair":
                command_toolkit = AutonomousSafeOperationsToolkit(
                    default_executor(resolved_settings.quickops_workspace_root)
                )
            triage_agent, _, _ = agent_factory(
                runtime_settings,
                adapter,
                permission_mode=PermissionMode.READONLY,
                command_toolkit=command_toolkit,
            )
            triage_agent.add_tool(AssetKnowledgeToolkit(storage, service["id"], allow_record=False))
            triage_agent.quickops_runtime_context += (
                "\n<automatic_asset_triage>\n"
                f"service_id={service['id']}\nservice_name={service['name']}\n"
                f"probe={service['probe_type']}:{service['probe_target']}\n"
                f"trigger_event_id={trigger_event['id']}\n"
                f"guard_mode={guard_mode}\n"
                "<operator_guard_policy>\n"
                f"{service.get('guard_policy') or '未配置额外守护策略。'}\n"
                "</operator_guard_policy>\n"
                + (
                    "这是后台异常触发的只读排查。只收集最少必要证据，禁止任何修复、重启、"
                    "写文件或配置变更。输出证据、可能原因、置信度和建议人工决策项。\n"
                    if guard_mode == "diagnose"
                    else "这是用户明确启用的安全修复守护。先只读取证；仅在守护策略明确授权、"
                    "根因证据充分且操作被服务端判定为非高风险时执行最小可恢复修复，随后验证。"
                    "高风险/严重风险操作一律不得执行，并应留给正式会话决策。\n"
                )
                + "</automatic_asset_triage>"
            )
            result = await asyncio.wait_for(
                triage_agent.arun(
                    "服务探针刚刚发现异常，请严格按该资产的守护模式和守护策略完成一次初步处置。",
                    session_id=f"asset-triage-{service['id']}",
                    user_id="quickops-monitor",
                    stream=False,
                ),
                timeout=180,
            )
            content = str(getattr(result, "content", "") or "").strip()
            storage.create_asset_event(
                service["id"],
                title=(
                    "小维已完成自动只读排查"
                    if guard_mode == "diagnose"
                    else "小维已完成自动守护处置"
                ),
                content=content or "小维未返回可展示的排查结论，请创建正式会话继续处理。",
                severity=trigger_event["severity"],
                category="automatic_agent_investigation",
                source="agent",
                metadata={
                    "trigger_event_id": trigger_event["id"],
                    "investigation_mode": guard_mode,
                    "follow_up_available": True,
                },
            )
        except Exception as error:
            storage.create_asset_event(
                service["id"],
                title="小维自动排查未完成",
                content=f"自动守护未完成：{type(error).__name__}。探针原始证据仍已保留，可创建正式会话继续处理。",
                severity="warning",
                category="automatic_agent_investigation_failed",
                source="system",
                metadata={"trigger_event_id": trigger_event["id"], "follow_up_available": True},
            )

    asset_monitor = AssetMonitor(storage, adapter, on_anomaly=investigate_asset_anomaly)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        monitor_task = asyncio.create_task(asset_monitor.run())
        try:
            yield
        finally:
            asset_monitor.stop()
            monitor_task.cancel()
            await asyncio.gather(monitor_task, return_exceptions=True)
            terminal_manager.close_all()
            session_database_configs.clear()
            auth_manager.close()

    base_app = FastAPI(title="QuickOps Harness API", version="0.0.2", lifespan=lifespan)

    public_paths = {
        "/api/quickops/health",
        "/api/quickops/auth/status",
        "/api/quickops/auth/login",
        "/api/quickops/auth/logout",
    }

    def request_auth_token(request: Request) -> str | None:
        authorization = request.headers.get("authorization", "")
        scheme, _, bearer = authorization.partition(" ")
        if scheme.casefold() == "bearer" and bearer.strip():
            return bearer.strip()
        return request.cookies.get(auth_manager.cookie_name)

    @base_app.middleware("http")
    async def require_login(request: Request, call_next: Callable) -> Response:
        path = request.url.path
        is_public_ui = path == "/" or path.startswith("/assets/")
        if path not in public_paths and not is_public_ui:
            token = request_auth_token(request)
            session = auth_manager.authenticate(token)
            if session is None:
                return JSONResponse(
                    status_code=401,
                    content={"detail": "请先登录 QuickOps"},
                    headers={"Cache-Control": "no-store"},
                )
            request.state.auth_user = session.username
        response = await call_next(request)
        response.headers.setdefault("Cache-Control", "no-store")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    def get_host_ids() -> set[str]:
        return {host.id for host in adapter.list_hosts()}

    def ensure_session(
        session_id: str,
        *,
        host_id: str,
        user_id: str = "operator",
        title: str = "新会话",
    ) -> dict[str, Any]:
        session = storage.get_session(session_id)
        if session:
            if session["host_id"] != host_id:
                raise HTTPException(status_code=409, detail="会话目标主机与请求不一致")
            return session
        if host_id not in get_host_ids():
            raise HTTPException(status_code=403, detail="目标主机不在 QuickOps 工作区")
        default_model = next(
            (
                model
                for model in storage.list_model_configs(enabled_only=True)
                if model["is_default"]
            ),
            None,
        )
        return storage.create_session(
            session_id,
            title=title,
            host_id=host_id,
            user_id=user_id,
            model_config_id=default_model["id"] if default_model else None,
        )

    def session_with_asset(session: dict[str, Any]) -> dict[str, Any]:
        return {**session, "asset_service": storage.get_session_asset(session["id"])}

    def selected_model(session: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
        models = storage.list_model_configs(enabled_only=True)
        model = next((item for item in models if item["id"] == session["model_config_id"]), None)
        model = model or next((item for item in models if item["is_default"]), None)
        if model is None:
            raise HTTPException(status_code=503, detail="没有启用的模型配置")
        return model, storage.get_model_credentials(model["id"])

    @base_app.get("/api/quickops/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "agent_id": AGENT_ID}

    @base_app.get("/api/quickops/auth/status")
    async def auth_status(request: Request) -> dict[str, Any]:
        session = auth_manager.authenticate(request_auth_token(request))
        return {
            "configured": auth_manager.configured,
            "authenticated": session is not None,
            "username": session.username if session else None,
        }

    @base_app.post("/api/quickops/auth/login")
    async def login(payload: LoginRequest, request: Request, response: Response) -> dict[str, Any]:
        if not auth_manager.configured:
            raise HTTPException(
                status_code=503,
                detail=(
                    "服务端尚未配置登录凭据，请设置 QUICKOPS_AUTH_USERNAME 和 "
                    "QUICKOPS_AUTH_PASSWORD 后重启 QuickOps"
                ),
            )
        client_key = request.client.host if request.client else "unknown"
        try:
            token = auth_manager.login(payload.username, payload.password, client_key)
        except LoginRateLimitedError as error:
            raise HTTPException(status_code=429, detail=str(error)) from error
        if token is None:
            raise HTTPException(status_code=401, detail="账号或密码错误")
        response.set_cookie(
            key=auth_manager.cookie_name,
            value=token,
            max_age=auth_manager.ttl_seconds,
            httponly=True,
            secure=request.url.scheme == "https",
            # Lax keeps the cookie unavailable to scripts and blocks cross-site
            # subrequests, while still surviving ordinary intranet links/bookmarks.
            samesite="lax",
            path="/",
        )
        # The bearer token is a compatibility fallback for browser containers that reject
        # cookies on an intranet HTTP origin. The UI keeps it in sessionStorage only.
        return {
            "authenticated": True,
            "username": payload.username,
            "access_token": token,
            "token_type": "bearer",
            "expires_in": auth_manager.ttl_seconds,
        }

    @base_app.post("/api/quickops/auth/logout", status_code=204)
    async def logout(request: Request, response: Response) -> Response:
        auth_manager.logout(request_auth_token(request))
        response.delete_cookie(auth_manager.cookie_name, path="/", samesite="lax")
        response.status_code = 204
        return response

    @base_app.get("/api/quickops/bootstrap", response_model=BootstrapResponse)
    async def bootstrap() -> BootstrapResponse:
        models = storage.list_model_configs(enabled_only=True)
        default_model = next((model for model in models if model["is_default"]), None)
        configured = bool(default_model and default_model["has_api_key"])
        return BootstrapResponse(
            agent_id=AGENT_ID,
            model_id=default_model["model_id"] if default_model else "",
            model_provider=default_model["provider"] if default_model else "",
            model_configured=configured,
            permission_mode=PermissionMode.APPROVAL,
            permission_modes_enabled=ENABLED_PERMISSION_MODES,
            hosts=adapter.list_hosts(),
        )

    @base_app.get("/api/quickops/sessions")
    async def list_sessions(user_id: str = "operator") -> dict[str, Any]:
        return {
            "sessions": [
                session_with_asset(item) for item in storage.list_sessions(user_id=user_id)
            ]
        }

    @base_app.post("/api/quickops/sessions", status_code=201)
    async def create_session(payload: SessionCreateRequest) -> dict[str, Any]:
        hosts = adapter.list_hosts()
        host_id = payload.host_id or (hosts[0].id if hosts else "")
        if host_id not in {host.id for host in hosts}:
            raise HTTPException(status_code=403, detail="目标主机不在 QuickOps 工作区")
        session_id = payload.id or payload.session_id or f"quickops-{uuid.uuid4()}"
        default_model = next(
            (
                model
                for model in storage.list_model_configs(enabled_only=True)
                if model["is_default"]
            ),
            None,
        )
        try:
            session = storage.create_session(
                session_id,
                title=payload.title,
                host_id=host_id,
                user_id=payload.user_id,
                permission_mode=payload.permission_mode,
                model_config_id=payload.model_config_id
                or (default_model["id"] if default_model else None),
            )
        except StorageError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        # A QuickOps conversation owns one persistent operator shell from the moment the
        # conversation is created. AI and manual modes are merely two interaction surfaces for
        # that same shell; entering manual mode must not be what establishes the connection.
        terminal = terminal_manager.open(session_id)
        session = {
            **session,
            "terminal_status": "connected" if terminal["alive"] else "closed",
            "terminal": {
                **terminal,
                "terminal_id": session_id,
                "terminal_alive": terminal["alive"],
            },
        }
        return {"session": session_with_asset(session)}

    @base_app.get("/api/quickops/sessions/{session_id}/messages")
    async def list_messages(session_id: str) -> dict[str, Any]:
        if not storage.get_session(session_id):
            raise HTTPException(status_code=404, detail="会话不存在")
        stored_messages = storage.list_messages(session_id)
        represented_runs = {
            (item.get("metadata") or {}).get("run_id") for item in stored_messages
        }
        # Repair runs produced by older builds that persisted provider failures but not the
        # corresponding assistant turn. This restores the partial execution chain on first read.
        for failed_run in reversed(storage.list_runs(session_id=session_id, limit=500)):
            if failed_run["status"] != "failed" or failed_run["id"] in represented_runs:
                continue
            partial = str(failed_run.get("output_text") or "").rstrip()
            friendly = _friendly_run_error(RuntimeError(failed_run.get("error") or "运行失败"))
            content = f"{partial}\n\n> ⚠️ {friendly}" if partial else f"> ⚠️ {friendly}"
            segments = _message_segments(storage.list_run_events(failed_run["id"]), partial)
            segments.append({"type": "text", "content": f"\n\n> ⚠️ {friendly}"})
            storage.append_message(
                session_id,
                role="assistant",
                content=content,
                metadata={
                    "kind": "chat",
                    "status": "failed",
                    "run_id": failed_run["id"],
                    "segments": segments,
                },
                created_at=failed_run.get("completed_at") or failed_run["created_at"],
            )
        messages = [_public_message(item) for item in storage.list_messages(session_id)]
        return {"messages": messages}

    @base_app.put("/api/quickops/sessions/{session_id}/asset")
    async def mount_session_asset(
        session_id: str, payload: SessionAssetMountRequest
    ) -> dict[str, Any]:
        try:
            asset = storage.mount_session_asset(session_id, payload.service_id)
        except StorageError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        session = storage.get_session(session_id)
        return {"asset_service": asset, "session": session_with_asset(session)}

    @base_app.post("/api/quickops/sessions/{session_id}/attachments", status_code=201)
    async def upload_session_attachment(
        session_id: str, upload: Annotated[UploadFile, File()]
    ) -> dict[str, Any]:
        if storage.get_session(session_id) is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        content = await upload.read(attachment_store.max_file_bytes + 1)
        try:
            attachment = attachment_store.save(
                session_id,
                filename=upload.filename,
                content_type=upload.content_type,
                content=content,
            )
        except AttachmentError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        asset_document = None
        mounted_asset = storage.get_session_asset(session_id)
        if mounted_asset:
            resolved = attachment_store.resolve(session_id, attachment["id"])
            try:
                asset_document = asset_document_store.import_path(
                    mounted_asset["id"],
                    Path(resolved["path"]),
                    filename=resolved["name"],
                    content_type=resolved["mime_type"],
                    source_session_id=session_id,
                )
            except (AssetDocumentError, StorageError) as error:
                # The chat attachment remains usable even if knowledge indexing fails.
                storage.create_asset_event(
                    mounted_asset["id"],
                    title="会话附件归档失败",
                    content=f"文件 {resolved['name']} 未能进入文档库：{error}",
                    severity="warning",
                    category="document_ingest",
                    source="system",
                )
        return {"attachment": attachment, "asset_document": asset_document}

    @base_app.delete(
        "/api/quickops/sessions/{session_id}/attachments/{attachment_id}",
        status_code=204,
    )
    async def delete_session_attachment(session_id: str, attachment_id: str) -> None:
        if not attachment_store.delete(session_id, attachment_id):
            raise HTTPException(status_code=404, detail="附件不存在")

    @base_app.get("/api/quickops/sessions/{session_id}/attachments/{attachment_id}/preview")
    async def preview_session_attachment(session_id: str, attachment_id: str) -> FileResponse:
        if storage.get_session(session_id) is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        try:
            attachment = attachment_store.resolve(session_id, attachment_id)
        except AttachmentError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        mime_type = str(attachment["mime_type"])
        if not mime_type.startswith("image/") or mime_type == "image/svg+xml":
            raise HTTPException(status_code=415, detail="该附件不支持图片预览")
        return FileResponse(
            attachment["path"],
            media_type=mime_type,
            headers={"Content-Disposition": "inline"},
        )

    @base_app.get("/api/quickops/sessions/{session_id}/report-messages")
    async def list_report_messages(session_id: str) -> dict[str, Any]:
        if not storage.get_session(session_id):
            raise HTTPException(status_code=404, detail="会话不存在")
        messages = [
            _public_message(item)
            for item in storage.list_messages(session_id, include_superseded=True)
        ]
        return {"messages": messages}

    @base_app.get("/api/quickops/sessions/{session_id}/reports/{report_id}")
    async def download_session_report(session_id: str, report_id: str) -> FileResponse:
        if not storage.get_session(session_id):
            raise HTTPException(status_code=404, detail="会话不存在")
        try:
            report = report_store.resolve(session_id, report_id)
        except ReportArtifactError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return FileResponse(
            report["path"],
            media_type=report["mime_type"],
            filename=f"quickops-report-{report_id[:8]}.{report['format']}",
        )

    @base_app.patch("/api/quickops/sessions/{session_id}")
    async def update_session(session_id: str, payload: SessionUpdateRequest) -> dict[str, Any]:
        changes = payload.model_dump(exclude_none=True)
        if "host_id" in changes and changes["host_id"] not in get_host_ids():
            raise HTTPException(status_code=403, detail="目标主机不在 QuickOps 工作区")
        try:
            session = storage.update_session(session_id, **changes)
        except StorageError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if session is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        return {"session": session_with_asset(session)}

    @base_app.delete("/api/quickops/sessions/{session_id}", status_code=204)
    async def delete_session(session_id: str) -> Response:
        terminal_manager.close(session_id)
        session_database_configs.pop(session_id, None)
        if not storage.delete_session(session_id):
            raise HTTPException(status_code=404, detail="会话不存在")
        attachment_store.delete_session(session_id)
        report_store.delete_session(session_id)
        return Response(status_code=204)

    @base_app.get("/api/quickops/models")
    async def list_models() -> dict[str, Any]:
        return {"models": storage.list_model_configs()}

    @base_app.post("/api/quickops/models", status_code=201)
    async def create_model(payload: ModelConfigRequest) -> dict[str, Any]:
        config_id = payload.id or f"model-{uuid.uuid4().hex[:12]}"
        return {"model": storage.save_model_config(config_id, **payload.model_dump(exclude={"id"}))}

    @base_app.patch("/api/quickops/models/{config_id}")
    async def update_model(config_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        current = storage.get_model_config(config_id)
        if current is None:
            raise HTTPException(status_code=404, detail="模型配置不存在")
        merged = {
            "name": payload.get("name", current["name"]),
            "provider": payload.get("provider", current["provider"]),
            "model_id": payload.get("model_id", current["model_id"]),
            "base_url": payload.get("base_url", current["base_url"]),
            "api_key": payload.get("api_key") or None,
            "is_default": payload.get("is_default", current["is_default"]),
            "enabled": payload.get("enabled", current["enabled"]),
            "thinking_mode": payload.get("thinking_mode", current["thinking_mode"]),
            "max_context_k": payload.get("max_context_k", current["max_context_k"]),
            "supports_vision": payload.get("supports_vision", current["supports_vision"]),
        }
        return {"model": storage.save_model_config(config_id, **merged)}

    @base_app.delete("/api/quickops/models/{config_id}", status_code=204)
    async def delete_model(config_id: str) -> Response:
        model = storage.get_model_config(config_id)
        if model is None:
            raise HTTPException(status_code=404, detail="模型配置不存在")
        raise HTTPException(status_code=409, detail="已配置模型不可删除，可停用或修改配置")

    @base_app.get("/api/quickops/settings")
    async def list_settings() -> dict[str, Any]:
        return {"settings": storage.list_settings()}

    @base_app.put("/api/quickops/settings/{key}")
    async def set_setting(key: str, payload: dict[str, Any]) -> dict[str, Any]:
        if key == "audit_retention_days":
            raise HTTPException(status_code=410, detail="审计记录长期保存，不支持自动清理")
        if key == "toolkit_config":
            raise HTTPException(
                status_code=403,
                detail="工具凭据只能通过服务端受限配置提供",
            )
        if key == "agent_toolbox_enabled":
            value = payload.get("value")
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise HTTPException(status_code=422, detail="工具箱配置必须是工具 ID 列表")
            known = {spec.id for spec in TOOLKIT_SPECS}
            unknown = sorted(set(value).difference(known))
            if unknown:
                raise HTTPException(status_code=422, detail=f"未知工具：{', '.join(unknown)}")
        return {"setting": storage.set_setting(key, payload.get("value"))}

    @base_app.get("/api/quickops/toolbox")
    async def get_toolbox() -> dict[str, Any]:
        enabled = set(storage.get_setting("agent_toolbox_enabled", []))
        categories = {
            "development": "开发与编码",
            "infrastructure": "基础设施",
            "filesystem": "文件与工作区",
            "web": "网页与检索",
            "database": "数据库",
        }
        tools = []
        for item in toolkit_catalog(resolved_settings.toolkit_config):
            tools.append(
                {
                    "id": item["id"],
                    "name": item["name"],
                    "category": categories.get(item["category"], item["category"]),
                    "description": item["description"]
                    + (
                        " 连接参数由小维在实际调用时向用户索取，并在当前会话内临时复用。"
                        if item["category"] == "database" and item["id"] != "database.duckdb"
                        else ""
                    ),
                    "available": item["available"],
                    "enabled": item["id"] in enabled,
                    "unavailable_reason": item["unavailable_reason"],
                    "usage_tier": item.get("usage_tier", "specialized"),
                }
            )
        return {"tools": tools}

    @base_app.get("/api/quickops/assets/services")
    async def list_asset_services(host_id: str | None = None) -> dict[str, Any]:
        if host_id and host_id not in get_host_ids():
            raise HTTPException(status_code=403, detail="目标主机不在 QuickOps 工作区")
        return {"services": storage.list_asset_services(host_id)}

    @base_app.post("/api/quickops/assets/services", status_code=201)
    async def create_asset_service(payload: AssetServiceRequest) -> dict[str, Any]:
        hosts = adapter.list_hosts()
        if not hosts:
            raise HTTPException(status_code=409, detail="当前没有可管理的目标主机")
        try:
            service = storage.create_asset_service(host_id=hosts[0].id, **payload.model_dump())
        except StorageError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {"service": service}

    @base_app.patch("/api/quickops/assets/services/{service_id}")
    async def update_asset_service(service_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            service = storage.update_asset_service(service_id, **payload)
        except StorageError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if service is None:
            raise HTTPException(status_code=404, detail="服务资产不存在")
        return {"service": service}

    @base_app.delete("/api/quickops/assets/services/{service_id}", status_code=204)
    async def delete_asset_service(service_id: str) -> Response:
        if storage.get_asset_service(service_id) is None:
            raise HTTPException(status_code=404, detail="服务资产不存在")
        asset_document_store.delete_service(service_id)
        storage.delete_asset_service(service_id)
        return Response(status_code=204)

    @base_app.post("/api/quickops/assets/services/{service_id}/check")
    async def check_asset_service(service_id: str) -> dict[str, Any]:
        try:
            service = await asset_monitor.check_service(service_id)
        except StorageError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return {"service": service}

    @base_app.get("/api/quickops/assets/services/{service_id}/events")
    async def list_asset_events(service_id: str) -> dict[str, Any]:
        if storage.get_asset_service(service_id) is None:
            raise HTTPException(status_code=404, detail="服务资产不存在")
        return {"events": storage.list_asset_events(service_id)}

    @base_app.post("/api/quickops/assets/services/{service_id}/events", status_code=201)
    async def create_asset_event(service_id: str, payload: AssetEventRequest) -> dict[str, Any]:
        try:
            event = storage.create_asset_event(
                service_id, **payload.model_dump(), source="operator"
            )
        except StorageError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {"event": event}

    @base_app.patch("/api/quickops/assets/events/{event_id}")
    async def update_asset_event(event_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            item = storage.update_asset_event(event_id, **payload)
        except StorageError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if item is None:
            raise HTTPException(status_code=404, detail="运维事件不存在")
        return {"event": item}

    @base_app.delete("/api/quickops/assets/events/{event_id}", status_code=204)
    async def delete_asset_event(event_id: str) -> Response:
        if not storage.delete_asset_event(event_id):
            raise HTTPException(status_code=404, detail="运维事件不存在")
        return Response(status_code=204)

    @base_app.post("/api/quickops/assets/events/{event_id}/session", status_code=201)
    async def create_session_from_asset_event(event_id: str) -> dict[str, Any]:
        event = storage.get_asset_event(event_id)
        if event is None:
            raise HTTPException(status_code=404, detail="运维事件不存在")
        service = storage.get_asset_service(event["service_id"])
        if service is None:
            raise HTTPException(status_code=404, detail="服务资产不存在")
        default_model = next(
            (item for item in storage.list_model_configs(enabled_only=True) if item["is_default"]),
            None,
        )
        session_id = f"quickops-{uuid.uuid4()}"
        title = f"{service['name']}：{event['title']}"[:200]
        session = storage.create_session(
            session_id,
            title=title,
            host_id=service["host_id"],
            user_id="operator",
            permission_mode=PermissionMode.APPROVAL,
            model_config_id=default_model["id"] if default_model else None,
        )
        storage.mount_session_asset(session_id, service["id"])
        storage.append_message(
            session_id,
            role="assistant",
            content=(
                f"已从“{service['name']}”的运维事件创建排查会话。\n\n"
                f"## {event['title']}\n\n{event['content']}"
            ),
            metadata={
                "kind": "runtime",
                "source": "asset_event",
                "asset_event_id": event["id"],
                "asset_service_id": service["id"],
            },
        )
        terminal = terminal_manager.open(session_id)
        enriched = {
            **session,
            "terminal_status": "connected" if terminal["alive"] else "closed",
            "terminal": {
                **terminal,
                "terminal_id": session_id,
                "terminal_alive": terminal["alive"],
            },
        }
        return {"session": session_with_asset(enriched)}

    @base_app.get("/api/quickops/assets/services/{service_id}/documents")
    async def list_asset_documents(service_id: str) -> dict[str, Any]:
        if storage.get_asset_service(service_id) is None:
            raise HTTPException(status_code=404, detail="服务资产不存在")
        return {"documents": storage.list_asset_documents(service_id)}

    @base_app.post("/api/quickops/assets/services/{service_id}/documents", status_code=201)
    async def upload_asset_document(
        service_id: str, upload: Annotated[UploadFile, File()]
    ) -> dict[str, Any]:
        if storage.get_asset_service(service_id) is None:
            raise HTTPException(status_code=404, detail="服务资产不存在")
        content = await upload.read(asset_document_store.max_file_bytes + 1)
        try:
            document = asset_document_store.save_bytes(
                service_id,
                filename=upload.filename or "document",
                content=content,
                content_type=upload.content_type,
            )
        except (AssetDocumentError, StorageError) as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {"document": document}

    @base_app.patch("/api/quickops/assets/documents/{document_id}")
    async def update_asset_document(document_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            document = storage.update_asset_document(document_id, **payload)
        except StorageError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if document is None:
            raise HTTPException(status_code=404, detail="文档不存在")
        return {"document": document}

    @base_app.get("/api/quickops/assets/documents/{document_id}/download")
    async def download_asset_document(document_id: str) -> FileResponse:
        try:
            document = asset_document_store.resolve(document_id)
        except AssetDocumentError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return FileResponse(
            document["path"], media_type=document["mime_type"], filename=document["name"]
        )

    @base_app.get("/api/quickops/assets/documents/{document_id}/preview")
    async def preview_asset_document(document_id: str) -> dict[str, Any]:
        """Return inert preview data; active document markup is never served inline."""
        try:
            document = asset_document_store.resolve(document_id)
        except AssetDocumentError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        mime_type = str(document["mime_type"])
        if mime_type.startswith("image/") and mime_type != "image/svg+xml":
            kind = "image"
        elif mime_type == "application/pdf":
            kind = "pdf"
        else:
            kind = "text"
        return {
            "preview": {
                "id": document["id"],
                "name": document["name"],
                "mime_type": mime_type,
                "kind": kind,
                "content": document.get("extracted_text", "") if kind == "text" else "",
            }
        }

    @base_app.delete("/api/quickops/assets/documents/{document_id}", status_code=204)
    async def delete_asset_document(document_id: str) -> Response:
        if not asset_document_store.delete(document_id):
            raise HTTPException(status_code=404, detail="文档不存在")
        return Response(status_code=204)

    async def generate_title(
        session_id: str, first_message: str, credentials: dict[str, Any]
    ) -> None:
        try:
            generator = AgnoSessionTitleGenerator(
                model_id=credentials["model_id"],
                base_url=credentials["base_url"],
                api_key=credentials["api_key"],
                provider=credentials["provider"],
            )
            session = storage.get_session(session_id)
            if session and session["title"] == "新会话":
                title = await generator.generate(first_message)
                storage.update_session(session_id, title=title)
        except Exception:
            # A naming failure must never fail or cancel the operator's actual work.
            LOGGER.exception(
                "Session title generation failed for %s; using local fallback", session_id
            )
            session = storage.get_session(session_id)
            if session and session["title"] == "新会话":
                storage.update_session(session_id, title=fallback_title(first_message))

    @base_app.post("/api/quickops/runs", response_model=AgentRunResponse, status_code=202)
    async def run_agent(payload: AgentRunRequest) -> AgentRunResponse:
        try:
            adapter.system_status(payload.host_id)
        except HostNotAllowedError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error
        session = ensure_session(
            payload.session_id,
            host_id=payload.host_id,
            user_id=payload.user_id,
            title="新会话",
        )
        if payload.model_config_id and payload.model_config_id != session.get("model_config_id"):
            available_model_ids = {
                item["id"] for item in storage.list_model_configs(enabled_only=True)
            }
            if payload.model_config_id not in available_model_ids:
                raise HTTPException(status_code=422, detail="所选模型不存在或已停用")
            session = storage.update_session(
                payload.session_id, model_config_id=payload.model_config_id
            ) or session
        target_host = next(host for host in adapter.list_hosts() if host.id == payload.host_id)
        is_first_message = storage.count_messages(payload.session_id, role="user") == 0
        try:
            resolved_attachments = [
                attachment_store.resolve(payload.session_id, attachment_id)
                for attachment_id in payload.attachment_ids
            ]
        except AttachmentError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        public_attachments = [
            attachment_store.public(attachment) for attachment in resolved_attachments
        ]
        _, credentials = selected_model(session)
        if not credentials:
            raise HTTPException(status_code=503, detail="当前模型尚未配置服务端凭据")
        image_attachments = [
            attachment
            for attachment in resolved_attachments
            if str(attachment.get("mime_type", "")).startswith("image/")
        ]
        if image_attachments and not credentials.get("supports_vision", False):
            raise HTTPException(
                status_code=422,
                detail="当前模型未启用图像理解能力，请在模型配置中开启多模态",
            )
        user_message = storage.append_message(
            payload.session_id,
            role="user",
            content=payload.message.strip(),
            metadata={
                "kind": "chat",
                "source": "ai_composer",
                "attachments": public_attachments,
            },
        )
        session_toolkit_config = session_database_configs.setdefault(payload.session_id, {})
        for spec in TOOLKIT_SPECS:
            if spec.category != "database":
                continue
            session_toolkit_config.setdefault(
                spec.id, dict(resolved_settings.toolkit_config.get(spec.id, {}))
            )
        runtime_settings = resolved_settings.model_copy(
            update={
                "model_id": credentials["model_id"],
                "model_base_url": credentials["base_url"],
                "siliconflow_api_key": credentials["api_key"],
                "model_provider": credentials["provider"],
                "thinking_mode": credentials["thinking_mode"],
                "max_context_tokens": credentials["max_context_k"] * 1000,
                # AI tools start from the operator terminal's current directory snapshot. They
                # remain separate, permission-governed processes and never inherit hidden shell
                # variables or mutate the operator-owned Shell behind the user's back.
                "quickops_workspace_root": Path(
                    terminal_manager.get_status(payload.session_id).get("cwd")
                    or resolved_settings.quickops_workspace_root
                ),
                "quickops_target_host_id": target_host.id,
                "quickops_target_host_name": target_host.name,
                "quickops_target_host_ip": target_host.ip,
                "quickops_target_host_platform": target_host.platform,
                "enabled_toolkits": tuple(storage.get_setting("agent_toolbox_enabled", [])),
                "toolkit_config": {
                    **resolved_settings.toolkit_config,
                    **session_toolkit_config,
                },
            }
        )
        permission_mode = PermissionMode(session["permission_mode"])
        shared_command_toolkit = SharedSessionOperationsToolkit(
            terminal_manager,
            payload.session_id,
            ai_command_policy,
            permission_mode,
        )
        runtime_agent, _, _ = agent_factory(
            runtime_settings,
            adapter,
            permission_mode=permission_mode,
            command_toolkit=shared_command_toolkit,
        )
        runtime_agent.add_tool(
            OperatorTerminalContextToolkit(storage, terminal_manager, payload.session_id)
        )
        runtime_agent.add_tool(ReportToolkit(report_store, payload.session_id))
        runtime_agent.add_tool(
            HostAssetCatalogToolkit(
                storage,
                target_host.id,
                payload.session_id,
                monitor=asset_monitor,
                document_store=asset_document_store,
            )
        )
        runtime_agent.quickops_runtime_context += (
            "\n<host_asset_catalog>\n"
            "当前受管目标主机拥有独立的服务资产目录。使用 quickops_host_assets 可列出当前主机的"
                "服务资产及健康状态，并可按用户意图查询、创建、修改、删除、挂载和立即探测。修改"
                "已有资产必须使用 update_host_asset，不要创建重复资产。不要要求用户提供 host_id，"
                "也不要在未查询目录前声称不存在资产。资产的历史事件和文档仅在挂载后通过"
            "quickops_asset_knowledge 使用。\n"
            "</host_asset_catalog>"
        )
        mounted_asset = storage.get_session_asset(payload.session_id)
        if mounted_asset:
            runtime_agent.add_tool(
                AssetKnowledgeToolkit(
                    storage,
                    mounted_asset["id"],
                    document_store=asset_document_store,
                )
            )
            runtime_agent.quickops_runtime_context += (
                "\n<mounted_service_asset>\n"
                f"service_id={mounted_asset['id']}\n"
                f"service_name={mounted_asset['name']}\n"
                f"probe={mounted_asset['probe_type']}:{mounted_asset['probe_target']}\n"
                f"latest_status={mounted_asset['status']}\n"
                "该服务资产已明确挂载到本会话。遇到历史故障、维护决策、运行手册、部署或"
                "配置问题时，主动使用 quickops_asset_knowledge 检索该资产隔离的事件与文档；"
                "不要要求用户再次说明服务身份，也不要检索其他资产。完成已验证的故障处置、"
                "根因定位、发布、配置变更、重启、恢复、长期绕行方案或关键决策后，必须调用 "
                "record_service_event 将证据、操作、结果和遗留风险写入该资产事件；不要记录"
                "闲聊、例行观察、未证实推测或任何密钥。\n"
                "</mounted_service_asset>"
            )
        agent_message = payload.message
        agno_files: list[AgnoFile] | None = None
        agno_images: list[AgnoImage] | None = None
        if resolved_attachments:
            attachment_dir = Path(resolved_attachments[0]["path"]).parent
            runtime_agent.add_tool(
                FileTools(
                    base_dir=attachment_dir,
                    enable_save_file=False,
                    enable_delete_file=False,
                    enable_replace_file_chunk=False,
                    enable_search_files=False,
                    expose_base_directory=False,
                )
            )
            attachment_lines = [
                f"- 用户文件名：{attachment['name']}；读取路径：{Path(attachment['path']).name}"
                for attachment in resolved_attachments
            ]
            agent_message = (
                f"{payload.message}\n\n"
                "<uploaded_files>\n"
                "用户已在当前会话上传以下文件。它们是本轮输入的一部分，不是目标主机原有文件。"
                "图片由已配置的多模态模型直接理解；其他文件请使用 Agno 的 "
                "read_file/read_file_chunk 工具读取文本内容后再回答，"
                "不要声称看不到附件。\n" + "\n".join(attachment_lines) + "\n</uploaded_files>"
            )
            provider = credentials["provider"].strip().casefold()
            base_url = credentials["base_url"].strip().casefold()
            non_image_attachments = [
                attachment
                for attachment in resolved_attachments
                if attachment not in image_attachments
            ]
            if provider == "openai" and "api.openai.com" in base_url and non_image_attachments:
                agno_files = [
                    AgnoFile(
                        filepath=attachment["path"],
                        filename=attachment["name"],
                        name=attachment["name"],
                        mime_type=attachment["mime_type"],
                        size=attachment["size"],
                    )
                    for attachment in non_image_attachments
                ]
            if image_attachments:
                agno_images = [
                    AgnoImage(
                        filepath=attachment["path"],
                        mime_type=attachment["mime_type"],
                        alt_text=attachment["name"],
                    )
                    for attachment in image_attachments
                ]
        run = run_manager.start(
            runtime_agent,
            message=agent_message,
            session_id=payload.session_id,
            user_id=payload.user_id,
            files=agno_files,
            images=agno_images,
        )
        if is_first_message:
            asyncio.create_task(generate_title(payload.session_id, payload.message, credentials))
        return AgentRunResponse(
            run_id=run["id"],
            session_id=payload.session_id,
            user_message_id=user_message["id"],
            status=run["status"],
            content="",
            tools=[],
        )

    @base_app.get("/api/quickops/runs/{run_id}")
    async def get_run(run_id: str) -> dict[str, Any]:
        run = storage.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="运行不存在")
        return {"run": run}

    @base_app.get("/api/quickops/sessions/{session_id}/active-runs")
    async def list_active_runs(session_id: str) -> dict[str, Any]:
        if storage.get_session(session_id) is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        runs = storage.list_runs(session_id=session_id, active_only=True)
        for run in runs:
            # A long streaming response can easily exceed the default 1,000
            # persisted deltas.  Reconnect decisions need the latest pause or
            # continuation boundary, so read the storage layer's full bounded
            # allowance instead of silently inspecting only the oldest events.
            events = storage.list_run_events(run["id"], limit=5_000)
            pause = next(
                (event for event in reversed(events) if event["event_type"] == "run.paused"),
                None,
            )
            boundary = next(
                (
                    event
                    for event in reversed(events)
                    if event["event_type"] == "continuation.started"
                ),
                None,
            )
            if pause is not None and (pause.get("payload") or {}).get("message_id"):
                run["stream_message_id"] = pause["payload"]["message_id"]
            if run["status"] == "paused" and pause is not None:
                # Replay the pause itself so the browser can reconstruct the latest choice/HITL
                # card. A feedback pause already has a durable assistant boundary, so none of
                # the older deltas need to be replayed.
                has_durable_boundary = bool((pause.get("payload") or {}).get("message_id"))
                run["resume_after_sequence"] = pause["sequence"] - 1 if has_durable_boundary else 0
            elif boundary is not None:
                # Compatibility for runs created by older builds, where feedback answers
                # started a separate continuation boundary.
                run["resume_after_sequence"] = boundary["sequence"]
            elif pause is not None and (pause.get("payload") or {}).get("message_id"):
                # Current feedback continuations update the same durable assistant message and
                # no longer create a continuation boundary. Replay only events after the pause.
                run["resume_after_sequence"] = pause["sequence"]
            else:
                run["resume_after_sequence"] = 0
        return {"runs": runs}

    @base_app.get("/api/quickops/runs/{run_id}/events")
    async def stream_run_events(run_id: str, after: int = 0) -> StreamingResponse:
        if storage.get_run(run_id) is None:
            raise HTTPException(status_code=404, detail="运行不存在")

        async def event_stream():
            async for stored_event in run_manager.subscribe(run_id, after_sequence=after):
                wire_event = {
                    "sequence": stored_event["sequence"],
                    "event": stored_event["event_type"],
                    "run_id": run_id,
                    "session_id": storage.get_run(run_id)["session_id"],
                    "payload": stored_event["payload"],
                    "created_at": stored_event["created_at"],
                }
                data = json.dumps(jsonable_encoder(wire_event), ensure_ascii=False)
                yield f"id: {stored_event['sequence']}\nevent: message\ndata: {data}\n\n"

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @base_app.post("/api/quickops/runs/{run_id}/confirm", status_code=202)
    async def confirm_run(run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        approved = payload.get("approved")
        if not isinstance(approved, bool):
            raise HTTPException(status_code=422, detail="approved 必须是布尔值")
        try:
            run = await run_manager.resolve_confirmation(
                run_id,
                approved=approved,
                note=payload.get("note"),
                requirement_id=payload.get("requirement_id"),
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="运行不存在") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return {"run": run}

    @base_app.post("/api/quickops/runs/{run_id}/feedback", status_code=202)
    async def answer_run_feedback(run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        selections = payload.get("selections")
        if not isinstance(selections, dict) or not selections:
            raise HTTPException(status_code=422, detail="selections 必须是非空对象")
        normalized: dict[str, list[str]] = {}
        for question, values in selections.items():
            if not isinstance(question, str) or not isinstance(values, list):
                raise HTTPException(status_code=422, detail="每个问题的答案必须是字符串数组")
            normalized[question] = [str(value) for value in values]
        try:
            run = await run_manager.resolve_user_feedback(
                run_id,
                selections=normalized,
                requirement_id=payload.get("requirement_id"),
            )
        except KeyError as error:
            raise HTTPException(status_code=404, detail="运行不存在") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return {"run": run}

    @base_app.post("/api/quickops/runs/{run_id}/cancel", status_code=202)
    async def cancel_run(run_id: str) -> dict[str, Any]:
        try:
            run = await run_manager.cancel(run_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail="运行不存在") from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return {"run": run}

    @base_app.post("/api/quickops/sessions/{session_id}/branch", status_code=201)
    async def branch_session(session_id: str, payload: SessionBranchRequest) -> dict[str, Any]:
        try:
            session = storage.branch_session(
                session_id,
                payload.through_message_id,
                child_session_id=f"quickops-{uuid.uuid4()}",
                user_id=payload.user_id,
            )
        except StorageError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {"session": session_with_asset(session)}

    @base_app.post("/api/quickops/sessions/{session_id}/revise", status_code=201)
    async def revise_session(session_id: str, payload: SessionReviseRequest) -> dict[str, Any]:
        try:
            session = storage.revise_session_from_message(session_id, payload.message_id)
        except StorageError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        return {"session": session_with_asset(session)}

    @base_app.post("/api/quickops/manual-commands")
    async def run_manual_command(payload: ManualCommandRequest) -> ManualCommandResponse:
        session = ensure_session(
            payload.session_id,
            host_id=payload.host_id,
            user_id=payload.user_id,
            title="新会话",
        )
        is_first_message = storage.count_messages(payload.session_id, role="user") == 0
        user_message = storage.append_message(
            payload.session_id,
            role="user",
            content=payload.command,
            metadata={"kind": "chat", "source": "manual_composer"},
        )
        try:
            result = terminal_manager.execute(payload.session_id, payload.command)
        except CommandExecutionError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        server_message = storage.append_message(
            payload.session_id,
            role="tool",
            message_type="manual",
            content=f"$ {payload.command}\n{result.output}\n\n[exit {result.exit_code}]",
            metadata={
                "kind": "manual",
                "command": payload.command,
                "exit_code": result.exit_code,
                "truncated": result.truncated,
                "source": "manual_terminal",
            },
        )
        if is_first_message:
            _, credentials = selected_model(session)
            if credentials:
                asyncio.create_task(
                    generate_title(payload.session_id, payload.command, credentials)
                )
        return ManualCommandResponse(
            host_id=payload.host_id,
            command=payload.command,
            output=result.output,
            exit_code=result.exit_code,
            truncated=result.truncated,
            terminal_id=payload.session_id,
            terminal_alive=result.terminal_alive,
            shell=terminal_manager.get_status(payload.session_id).get("shell", ""),
            cwd=result.cwd,
            user_message_id=user_message["id"],
            message_id=server_message["id"],
            created_at=server_message["created_at"].isoformat(),
        )

    @base_app.get("/api/quickops/sessions/{session_id}/terminal")
    async def terminal_status(session_id: str) -> dict[str, Any]:
        if storage.get_session(session_id) is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        # Reading a conversation's terminal state also restores a shell that was reclaimed by
        # the transport idle bound or lost during an API restart. From the operator's point of
        # view, entering a conversation therefore always means its terminal is connected.
        status = terminal_manager.open(session_id)
        return {**status, "terminal_id": session_id, "terminal_alive": status["alive"]}

    @base_app.post("/api/quickops/sessions/{session_id}/terminal/restart")
    async def restart_terminal(session_id: str) -> dict[str, Any]:
        if storage.get_session(session_id) is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        status = terminal_manager.restart(session_id)
        return {**status, "terminal_id": session_id, "terminal_alive": status["alive"]}

    @base_app.post("/api/quickops/sessions/{session_id}/terminal/close")
    async def close_terminal(session_id: str) -> dict[str, Any]:
        if storage.get_session(session_id) is None:
            raise HTTPException(status_code=404, detail="会话不存在")
        terminal_manager.close(session_id)
        status = terminal_manager.get_status(session_id)
        return {**status, "terminal_id": session_id, "terminal_alive": False}

    @base_app.post("/api/quickops/approvals/{approval_id}/approve")
    async def deprecated_approve_command(approval_id: str) -> None:
        raise HTTPException(
            status_code=410,
            detail=(
                "旧版手动命令审批已停用；AI 命令审批请使用运行确认接口 "
                f"(legacy approval: {approval_id})"
            ),
        )

    @base_app.post("/api/quickops/approvals/{approval_id}/reject")
    async def deprecated_reject_command(approval_id: str) -> None:
        raise HTTPException(
            status_code=410,
            detail=(
                "旧版手动命令审批已停用；AI 命令审批请使用运行确认接口 "
                f"(legacy approval: {approval_id})"
            ),
        )

    @base_app.get("/api/quickops/audit-events")
    async def list_audit_events(session_id: str | None = None) -> dict[str, Any]:
        return {"events": storage.list_audit_events(session_id=session_id)}

    app = AgentOS(
        id="quickops-agent-os",
        name="QuickOps AgentOS",
        description="Agno runtime for the QuickOps Harness Agent",
        version="0.0.2",
        agents=[agent],
        db=database,
        base_app=base_app,
        cors_allowed_origins=[
            "http://localhost:4173",
            "http://127.0.0.1:4173",
            "http://localhost:4174",
            "http://127.0.0.1:4174",
        ],
        tracing=True,
        telemetry=False,
    ).get_app()

    static_dir = resolved_settings.quickops_static_dir
    if static_dir is not None:
        static_root = static_dir.expanduser().resolve()
        index_file = static_root / "index.html"
        assets_dir = static_root / "assets"
        if not index_file.is_file() or not assets_dir.is_dir():
            raise RuntimeError(
                f"QUICKOPS_STATIC_DIR does not contain a built QuickOps UI: {static_root}"
            )
        app.mount("/assets", StaticFiles(directory=assets_dir), name="quickops-assets")

        # AgentOS exposes its own informational GET /. In an appliance-style deployment the
        # product UI owns that route, while AgentOS APIs remain available under their API paths.
        app.router.routes[:] = [
            route
            for route in app.router.routes
            if not (
                getattr(route, "path", None) == "/"
                and "GET" in (getattr(route, "methods", None) or set())
            )
        ]

        @app.get("/", include_in_schema=False)
        async def quickops_index() -> FileResponse:
            return FileResponse(index_file, headers={"Cache-Control": "no-store"})

        # AgentOS installs delegated routers that also answer GET /. Place the two UI routes
        # immediately before those delegated routers so / and /assets resolve to the product,
        # without moving them ahead of QuickOps' concrete API routes.
        ui_route_names = {"quickops-assets", "quickops_index"}
        ui_routes = [
            route for route in app.router.routes if getattr(route, "name", None) in ui_route_names
        ]
        other_routes = [
            route
            for route in app.router.routes
            if getattr(route, "name", None) not in ui_route_names
        ]
        delegated_index = next(
            (
                index
                for index, route in enumerate(other_routes)
                if type(route).__name__ == "_IncludedRouter"
            ),
            len(other_routes),
        )
        app.router.routes[:] = (
            other_routes[:delegated_index] + ui_routes + other_routes[delegated_index:]
        )

    return app


app = create_app()
