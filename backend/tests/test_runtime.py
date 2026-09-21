from pathlib import Path
from types import SimpleNamespace

import pytest
from agno.exceptions import ModelProviderError
from agno.models.message import Message
from quickops.domain import PermissionMode
from quickops.host_adapter import DemoHostAdapter
from quickops.runtime import QuickOpsCompressionManager, _enrich_empty_provider_error, build_runtime
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
    assert agent.additional_context is None
    assert "terminal_cwd=" not in agent.quickops_runtime_context
    assert "host_id=demo" in agent.quickops_runtime_context
    assert agent.num_history_runs is None
    assert agent.add_session_summary_to_context is False
    assert agent.tool_call_limit == 32
    assert agent.compression_manager.compress_token_limit == 70_400
    assert agent.compression_manager.source_char_limit == 44_800
    assert agent.compression_manager.compressed_char_limit == 16_000
    assert agent.quickops_context_compaction_tokens == 115_200
    assert any(getattr(tool, "name", "") == "user_feedback_tools" for tool in agent.tools)


def test_empty_provider_error_recovers_http_status_and_safe_code() -> None:
    class ProviderCause(RuntimeError):
        pass

    cause = ProviderCause("upstream rejected request")
    cause.response = SimpleNamespace(
        status_code=429,
        json=lambda: {"error": {"code": 50602}},
    )
    error = ModelProviderError(
        message="Unknown model error",
        status_code=429,
        model_name="test",
        model_id="test-model",
    )
    error.__cause__ = cause

    enriched = _enrich_empty_provider_error(error)

    assert enriched.status_code == 429
    assert "HTTP 429" in str(enriched)
    assert "50602" in str(enriched)


@pytest.mark.asyncio
async def test_oversized_tool_result_is_bounded_when_model_compression_fails(
    monkeypatch,
) -> None:
    class FailingCompressionModel:
        async def aresponse(self, **_kwargs):
            raise ModelProviderError(message="compression context overflow", status_code=400)

    failing_model = FailingCompressionModel()
    monkeypatch.setattr("agno.compression.manager.get_model", lambda _model: failing_model)
    manager = QuickOpsCompressionManager(
        model=failing_model,
        compress_tool_results=True,
        compress_token_limit=1_000_000,
    )
    manager.configure_context_budget(200_000)
    message = Message(role="tool", tool_name="get_container_logs", content="x" * 100_000)

    assert await manager.ashould_compress([message], model=None) is True
    compressed = await manager._acompress_tool_result(message)

    assert compressed is not None
    assert manager.source_char_limit == 70_000
    assert manager.compressed_char_limit == 24_000
    assert len(compressed) <= manager.compressed_char_limit
    assert "QuickOps omitted" in compressed
    assert len(str(message.content)) == 100_000


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

    assert "enabled=none" in disabled.quickops_runtime_context
    assert "刚启用的工具在当前既有会话的下一次运行立即生效" in str(enabled.quickops_runtime_context)
    assert "coding_tools" in enabled.quickops_runtime_context
    assert "edit_file" not in enabled.quickops_runtime_context
    assert any("edit_file" in getattr(tool, "functions", {}) for tool in enabled.tools)
