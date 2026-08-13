from pathlib import Path

from quickops.domain import PermissionMode
from quickops.settings import Settings
from quickops.tool_registry import build_enabled_toolkits, toolkit_catalog


def test_optional_agno_toolkits_are_disabled_by_default(tmp_path: Path) -> None:
    settings = Settings(_env_file=None, quickops_db_file=tmp_path / "quickops.db")

    result = build_enabled_toolkits(
        settings.enabled_toolkits,
        configs=settings.toolkit_config,
        workspace_root=tmp_path,
        permission_mode=PermissionMode.APPROVAL,
    )

    assert settings.enabled_toolkits == ()
    assert result.tools == []
    assert all(not report.enabled for report in result.reports)


def test_catalog_keeps_session_configured_databases_enableable() -> None:
    catalog = {item["id"]: item for item in toolkit_catalog()}

    assert catalog["coding"]["default_enabled"] is False
    assert catalog["database.sql"]["available"] is True
    assert catalog["database.sql"]["unavailable_reason"] is None
    assert catalog["database.postgres"]["config_requirements"] == (
        "db_name",
        "host",
        "user",
        "password",
    )


def test_readonly_coding_toolkit_does_not_expose_mutation(tmp_path: Path) -> None:
    result = build_enabled_toolkits(
        ["coding"],
        configs={},
        workspace_root=tmp_path,
        permission_mode=PermissionMode.READONLY,
    )

    assert len(result.tools) == 1
    assert set(result.tools[0].functions) == {"read_file", "grep", "find", "ls"}


def test_approval_marks_coding_mutations_for_agno_confirmation(tmp_path: Path) -> None:
    result = build_enabled_toolkits(
        ["coding"],
        configs={},
        workspace_root=tmp_path,
        permission_mode=PermissionMode.APPROVAL,
    )

    toolkit = result.tools[0]
    assert set(toolkit.requires_confirmation_tools) == {
        "edit_file",
        "write_file",
        "run_shell",
    }
    assert toolkit.functions["edit_file"].requires_confirmation is True


def test_unconfigured_database_uses_session_connection_tool(tmp_path: Path) -> None:
    result = build_enabled_toolkits(
        ["database.sql", "does-not-exist"],
        configs={},
        workspace_root=tmp_path,
        permission_mode=PermissionMode.FULL_ACCESS,
    )

    assert len(result.tools) == 1
    assert set(result.tools[0].functions) == {"query_sql"}
    failures = {report.id: report.reason for report in result.reports if report.enabled}
    assert failures["database.sql"] is None
    assert failures["does-not-exist"] == "未知工具箱"


def test_database_connection_parameters_are_reused_within_session(tmp_path: Path) -> None:
    configs = {"database.sql": {}}
    first = build_enabled_toolkits(
        ["database.sql"],
        configs=configs,
        workspace_root=tmp_path,
        permission_mode=PermissionMode.APPROVAL,
    ).tools[0]
    db_url = f"sqlite:///{tmp_path / 'session.db'}"
    assert "1" in first.query_sql("select 1 as value", db_url=db_url)
    assert configs["database.sql"]["db_url"] == db_url

    second = build_enabled_toolkits(
        ["database.sql"],
        configs=configs,
        workspace_root=tmp_path,
        permission_mode=PermissionMode.APPROVAL,
    ).tools[0]
    assert "2" in second.query_sql("select 2 as value")
