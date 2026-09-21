from __future__ import annotations

import asyncio
import json
from pathlib import Path

from quickops.assets import (
    AssetDocumentStore,
    AssetKnowledgeToolkit,
    AssetMonitor,
    HostAssetCatalogToolkit,
)
from quickops.storage import QuickOpsStorage


class FakeHostAdapter:
    def __init__(self, *, processes: str):
        self.processes = processes

    def process_list(self, host_id: str, query: str = "") -> str:
        assert host_id == "local"
        return self.processes

    def system_status(self, host_id: str) -> str:
        assert host_id == "local"
        return "cpu=12% memory=48%"


def test_document_store_extracts_text_and_toolkit_searches_only_mounted_asset(
    tmp_path: Path,
) -> None:
    storage = QuickOpsStorage(tmp_path / "quickops.db")
    first = storage.create_asset_service(
        host_id="local", name="订单服务", probe_type="process", probe_target="orders"
    )
    second = storage.create_asset_service(
        host_id="local", name="支付服务", probe_type="process", probe_target="payments"
    )
    documents = AssetDocumentStore(tmp_path / "documents", storage)
    saved = documents.save_bytes(
        first["id"],
        filename="runbook.md",
        content="订单连接池恢复：检查 max_connections".encode(),
        content_type="text/markdown",
    )
    storage.create_asset_event(second["id"], title="支付故障", content="订单连接池不应串库")

    toolkit = AssetKnowledgeToolkit(storage, first["id"])
    results = json.loads(toolkit.search_service_knowledge("之前订单服务的连接池怎么恢复"))

    assert saved["name"] == "runbook.md"
    assert results and {item["kind"] for item in results} == {"document"}
    assert "max_connections" in toolkit.read_service_document(saved["id"])


def test_asset_guard_policy_is_durable_and_validated(tmp_path: Path) -> None:
    storage = QuickOpsStorage(tmp_path / "quickops.db")
    service = storage.create_asset_service(
        host_id="local",
        name="OCR API",
        probe_type="http",
        probe_target="http://127.0.0.1:8080/health",
        guard_mode="safe_repair",
        guard_policy="仅允许重启单个 OCR 容器并立即复测。",
    )

    assert service["guard_mode"] == "safe_repair"
    assert "OCR 容器" in storage.get_asset_service(service["id"])["guard_policy"]
    updated = storage.update_asset_service(service["id"], guard_mode="diagnose")
    assert updated["guard_mode"] == "diagnose"


def test_monitor_records_only_real_status_transitions(tmp_path: Path) -> None:
    storage = QuickOpsStorage(tmp_path / "quickops.db")
    service = storage.create_asset_service(
        host_id="local", name="nginx", probe_type="process", probe_target="nginx"
    )
    adapter = FakeHostAdapter(processes="No processes found matching nginx")
    monitor = AssetMonitor(storage, adapter)  # type: ignore[arg-type]

    first = asyncio.run(monitor.check_service(service["id"]))
    asyncio.run(monitor.check_service(service["id"]))
    adapter.processes = "123 root nginx: master process"
    recovered = asyncio.run(monitor.check_service(service["id"]))
    events = storage.list_asset_events(service["id"])

    assert first["status"] == "down"
    assert recovered["status"] == "healthy"
    assert [item["category"] for item in events] == [
        "recovery",
        "automatic_investigation",
    ]


def test_monitor_schedules_agent_investigation_once_per_unhealthy_transition(
    tmp_path: Path,
) -> None:
    storage = QuickOpsStorage(tmp_path / "quickops.db")
    service = storage.create_asset_service(
        host_id="local", name="nginx", probe_type="process", probe_target="nginx"
    )
    adapter = FakeHostAdapter(processes="No processes found matching nginx")
    observed: list[tuple[str, str]] = []

    async def investigate(asset: dict[str, object], event: dict[str, object]) -> None:
        observed.append((str(asset["id"]), str(event["category"])))
        storage.create_asset_event(
            str(asset["id"]),
            title="小维已完成自动只读排查",
            content="证据：nginx 进程不存在；建议创建正式会话决定是否恢复。",
            severity="critical",
            category="automatic_agent_investigation",
            source="agent",
            metadata={"trigger_event_id": event["id"], "follow_up_available": True},
        )

    async def scenario() -> None:
        monitor = AssetMonitor(storage, adapter, on_anomaly=investigate)  # type: ignore[arg-type]
        await monitor.check_service(service["id"])
        await asyncio.sleep(0)
        await monitor.check_service(service["id"])
        await asyncio.sleep(0)

    asyncio.run(scenario())
    assert observed == [(service["id"], "automatic_investigation")]
    events = storage.list_asset_events(service["id"])
    assert [item["category"] for item in events] == [
        "automatic_agent_investigation",
        "automatic_investigation",
    ]
    assert events[0]["source"] == "agent"
    assert events[0]["metadata"]["follow_up_available"] is True


def test_agent_asset_catalog_lists_creates_and_mounts_only_current_host(tmp_path: Path) -> None:
    storage = QuickOpsStorage(tmp_path / "quickops.db")
    storage.create_session("catalog-session", host_id="local", user_id="operator")
    storage.create_asset_service(
        host_id="other-host", name="other", probe_type="tcp", probe_target="127.0.0.1:9"
    )
    catalog = HostAssetCatalogToolkit(storage, "local", "catalog-session")

    created = json.loads(
        catalog.create_host_asset(
            name="ocr-api",
            probe_type="http",
            probe_target="http://127.0.0.1:8080/health",
            description="OCR service",
        )
    )

    assert created["created"] is True
    assert created["mounted_to_current_session"] is True
    assert storage.get_session_asset("catalog-session")["id"] == created["asset"]["id"]
    assert [item["name"] for item in json.loads(catalog.list_host_assets())] == ["ocr-api"]
    assert (
        json.loads(
            catalog.create_host_asset(
                name="ocr-api",
                probe_type="http",
                probe_target="http://127.0.0.1:8080/health",
            )
        )["created"]
        is False
    )


def test_agent_asset_catalog_can_update_probe_check_unmount_and_delete(tmp_path: Path) -> None:
    storage = QuickOpsStorage(tmp_path / "quickops.db")
    storage.create_session("catalog-session", host_id="local", user_id="operator")
    documents = AssetDocumentStore(tmp_path / "documents", storage)
    adapter = FakeHostAdapter(processes="123 root jenkins")
    monitor = AssetMonitor(storage, adapter)  # type: ignore[arg-type]
    catalog = HostAssetCatalogToolkit(
        storage,
        "local",
        "catalog-session",
        monitor=monitor,
        document_store=documents,
    )
    created = json.loads(
        catalog.create_host_asset(
            name="Jenkins",
            probe_type="http",
            probe_target="http://127.0.0.1:9090/",
        )
    )["asset"]

    updated = json.loads(
        catalog.update_host_asset(
            created["id"],
            probe_type="process",
            probe_target="jenkins",
            interval_seconds=30,
        )
    )
    checked = json.loads(asyncio.run(catalog.check_host_asset_now(created["id"])))
    unmounted = json.loads(catalog.unmount_host_asset_from_current_session())
    deleted = json.loads(catalog.delete_host_asset(created["id"], expected_name="Jenkins"))

    assert updated["probe_target"] == "jenkins"
    assert updated["status"] == "unknown"
    assert checked["status"] == "healthy"
    assert unmounted["mounted"] is False
    assert storage.get_session_asset("catalog-session") is None
    assert deleted["deleted"] is True
    assert storage.get_asset_service(created["id"]) is None


def test_mounted_asset_toolkit_controls_event_and_document_metadata(tmp_path: Path) -> None:
    storage = QuickOpsStorage(tmp_path / "quickops.db")
    service = storage.create_asset_service(
        host_id="local", name="OCR", probe_type="process", probe_target="ocr"
    )
    documents = AssetDocumentStore(tmp_path / "documents", storage)
    document = documents.save_bytes(
        service["id"],
        filename="runbook.md",
        content=b"restart steps",
        content_type="text/markdown",
    )
    toolkit = AssetKnowledgeToolkit(storage, service["id"], document_store=documents)
    event = json.loads(toolkit.record_service_event("部署", "版本 v2 已验证"))

    updated_event = json.loads(toolkit.update_service_event(event["id"], title="部署完成"))
    updated_document = json.loads(
        toolkit.update_service_document(document["id"], description="OCR recovery runbook")
    )

    assert updated_event["title"] == "部署完成"
    assert updated_document["description"] == "OCR recovery runbook"
    assert json.loads(toolkit.list_service_documents())[0]["id"] == document["id"]
    assert json.loads(toolkit.delete_service_event(event["id"]))["deleted"] is True
    assert json.loads(toolkit.delete_service_document(document["id"]))["deleted"] is True
