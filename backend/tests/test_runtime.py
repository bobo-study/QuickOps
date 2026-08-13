from pathlib import Path

from quickops.domain import PermissionMode
from quickops.host_adapter import DemoHostAdapter
from quickops.runtime import build_runtime
from quickops.settings import Settings


def test_runtime_keeps_provider_cache_prefix_stable(tmp_path: Path) -> None:
    agent, _, _ = build_runtime(
        Settings(
            quickops_db_file=tmp_path / "runtime.db",
            quickops_target_host_id="demo",
            quickops_target_host_name="demo-host",
            quickops_target_host_ip="192.0.2.10",
            quickops_target_host_platform="Linux",
            quickops_workspace_root=tmp_path,
        ),
        DemoHostAdapter(("demo",)),
    )

    assert agent.add_datetime_to_context is False
    assert "terminal_cwd=" not in str(agent.additional_context)


def test_summary_model_uses_portable_json_object_output(tmp_path: Path) -> None:
    agent, _, _ = build_runtime(
        Settings(quickops_db_file=tmp_path / "runtime.db"),
        DemoHostAdapter(("demo",)),
    )

    summary_model = agent.session_summary_manager.model
    assert summary_model.supports_native_structured_outputs is False
    assert summary_model.supports_json_schema_outputs is False
    assert summary_model.extra_body == {"enable_thinking": False}


def test_runtime_declares_fresh_enabled_toolbox_as_authoritative(tmp_path: Path) -> None:
    disabled, _, _ = build_runtime(
        Settings(quickops_db_file=tmp_path / "runtime.db", quickops_workspace_root=tmp_path),
        DemoHostAdapter(("demo",)),
        permission_mode=PermissionMode.APPROVAL,
    )
    enabled, _, _ = build_runtime(
        Settings(
            quickops_db_file=tmp_path / "runtime.db",
            quickops_workspace_root=tmp_path,
            enabled_toolkits=("coding",),
        ),
        DemoHostAdapter(("demo",)),
        permission_mode=PermissionMode.APPROVAL,
    )

    assert "当前没有启用可调用的扩展工具" in str(disabled.additional_context)
    assert "刚启用的工具在当前既有会话的下一次运行立即生效" in str(
        enabled.additional_context
    )
    assert "edit_file" in str(enabled.additional_context)
    assert any("edit_file" in getattr(tool, "functions", {}) for tool in enabled.tools)
