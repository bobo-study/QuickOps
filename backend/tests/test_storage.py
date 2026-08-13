from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from quickops.storage import QuickOpsStorage, StorageError
from sqlalchemy import inspect


@pytest.fixture
def storage(tmp_path):
    return QuickOpsStorage(tmp_path / "quickops-test.db")


def test_sessions_messages_are_persistent_ordered_and_cascade(storage, tmp_path):
    created = storage.create_session("s-1", host_id="local", user_id="operator")
    assert created["title"] == "新会话"

    storage.append_message(
        "s-1", role="user", content="检查 nginx", metadata={"source": "composer"}
    )
    storage.append_message(
        "s-1", role="tool", content="active", message_type="manual", metadata={"exit": 0}
    )
    messages = storage.list_messages("s-1")
    assert [item["content"] for item in messages] == ["检查 nginx", "active"]
    assert messages[0]["metadata"] == {"source": "composer"}

    reopened = QuickOpsStorage(tmp_path / "quickops-test.db")
    assert reopened.get_session("s-1")["host_id"] == "local"
    assert len(reopened.list_messages("s-1")) == 2
    assert reopened.delete_session("s-1") is True
    assert reopened.list_messages("s-1") == []


def test_session_listing_tracks_activity_and_rejects_unknown_updates(storage):
    storage.create_session("older", host_id="local", user_id="operator")
    storage.create_session("newer", host_id="local", user_id="operator")
    storage.append_message("older", role="user", content="make this recent")

    assert [row["id"] for row in storage.list_sessions(user_id="operator")] == [
        "older",
        "newer",
    ]
    updated = storage.update_session("older", title="CPU 排查", permission_mode="approval")
    assert updated["title"] == "CPU 排查"
    assert updated["permission_mode"] == "approval"
    with pytest.raises(StorageError):
        storage.update_session("older", user_id="attacker")


def test_model_configs_hide_secrets_and_keep_a_single_default(storage):
    secret = "test-secret-that-must-not-leak"
    public = storage.save_model_config(
        "siliconflow",
        name="DeepSeek",
        provider="SiliconFlow",
        model_id="deepseek-ai/example",
        base_url="https://example.invalid/v1",
        api_key=secret,
        is_default=True,
    )
    assert public["has_api_key"] is True
    assert "api_key" not in public
    assert secret not in repr(public)
    assert secret not in repr(storage.list_model_configs())

    credentials = storage.get_model_credentials("siliconflow")
    assert credentials == {
        "model_id": "deepseek-ai/example",
        "base_url": "https://example.invalid/v1",
        "api_key": secret,
        "provider": "SiliconFlow",
        "thinking_mode": "auto",
        "max_context_k": 128,
    }
    # Metadata-only updates preserve a configured credential.
    storage.save_model_config(
        "siliconflow",
        name="DeepSeek renamed",
        provider="SiliconFlow",
        model_id="deepseek-ai/example",
        base_url="https://example.invalid/v1",
        api_key=None,
        is_default=False,
    )
    assert storage.get_model_credentials("siliconflow")["api_key"] == secret

    storage.save_model_config(
        "local",
        name="Local",
        provider="Local",
        model_id="local/model",
        base_url="http://127.0.0.1:8000/v1",
        api_key="local-token",
        is_default=True,
    )
    defaults = [item["id"] for item in storage.list_model_configs() if item["is_default"]]
    assert defaults == ["local"]


def test_settings_round_trip_structured_json(storage):
    payload = {"theme": "dark", "limits": [1, 2], "enabled": True}
    storage.set_setting("ui.preferences", payload)
    assert storage.get_setting("ui.preferences") == payload
    assert storage.list_settings() == {"ui.preferences": payload}
    assert storage.delete_setting("ui.preferences") is True
    assert storage.get_setting("ui.preferences", "missing") == "missing"


def test_approval_state_machine_and_audit(storage):
    storage.create_session("s-approval", host_id="local", user_id="operator")
    approval = storage.create_approval(
        session_id="s-approval",
        host_id="local",
        command="systemctl restart nginx",
        requested_by="agent",
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    assert approval["status"] == "pending"

    decided = storage.decide_approval(
        approval["id"], decision="approved", decided_by="operator", reason="已确认"
    )
    assert decided["status"] == "approved"
    with pytest.raises(StorageError):
        storage.decide_approval(approval["id"], decision="rejected", decided_by="operator")
    assert storage.mark_approval_executed(approval["id"])["status"] == "executed"

    event = storage.append_audit_event(
        session_id="s-approval",
        actor="operator",
        event_type="command.executed",
        action="execute approved command",
        target="local",
        outcome="success",
        details={"approval_id": approval["id"], "exit_code": 0},
    )
    assert event["details"]["exit_code"] == 0
    assert storage.list_audit_events(session_id="s-approval")[0]["id"] == event["id"]


def test_expired_approval_cannot_be_approved(storage):
    storage.create_session("expired", host_id="local", user_id="operator")
    approval = storage.create_approval(
        session_id="expired",
        host_id="local",
        command="uptime",
        requested_by="agent",
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )
    with pytest.raises(StorageError, match="expired"):
        storage.decide_approval(approval["id"], decision="approved", decided_by="operator")
    assert storage.get_approval(approval["id"])["status"] == "expired"


def test_expected_query_indexes_exist(storage):
    indexes = {
        index["name"]
        for table in (
            "quickops_sessions",
            "quickops_messages",
            "quickops_model_configs",
            "quickops_command_approvals",
            "quickops_audit_events",
        )
        for index in inspect(storage.engine).get_indexes(table)
    }
    assert {
        "ix_quickops_sessions_user_activity",
        "ix_quickops_messages_session_created",
        "ix_quickops_models_provider_enabled",
        "ix_quickops_approvals_session_status",
        "ix_quickops_audit_session_created",
    } <= indexes


def test_branch_session_copies_history_through_selected_message(storage):
    storage.create_session(
        "parent", host_id="local", user_id="operator", permission_mode="approval"
    )
    first = storage.append_message("parent", role="user", content="检查 nginx")
    second = storage.append_message("parent", role="assistant", content="正在检查")
    storage.append_message("parent", role="assistant", content="不应进入分支")

    child = storage.branch_session(
        "parent", second["id"], child_session_id="child", title="检查 nginx · 分支"
    )

    assert child["permission_mode"] == "approval"
    assert child["branch"]["parent_session_id"] == "parent"
    copied = storage.list_messages("child")
    assert [item["content"] for item in copied] == ["检查 nginx", "正在检查"]
    assert copied[0]["metadata"]["branched_from_message_id"] == first["id"]


def test_revise_session_hides_old_turn_but_retains_report_history(storage):
    storage.create_session("parent", host_id="local", user_id="operator")
    storage.append_message(
        "parent",
        role="user",
        content="第一问",
        metadata={"source": "ai_composer"},
    )
    storage.append_message("parent", role="assistant", content="第一答")
    revised = storage.append_message(
        "parent",
        role="user",
        content="这句要修改",
        metadata={"source": "ai_composer"},
    )
    storage.append_message("parent", role="assistant", content="原回答要保留在父会话")

    session = storage.revise_session_from_message("parent", revised["id"])

    assert session["id"] == "parent"
    assert session["revision"]["revised_message_id"] == revised["id"]
    visible = storage.list_messages("parent")
    assert [message["content"] for message in visible] == ["第一问", "第一答"]
    report = storage.list_messages("parent", include_superseded=True)
    assert [message["content"] for message in report] == [
        "第一问",
        "第一答",
        "这句要修改",
        "原回答要保留在父会话",
    ]
    assert report[-1]["metadata"]["superseded_by_revision"]


def test_revise_session_rejects_non_latest_or_manual_user_message(storage):
    storage.create_session("parent", host_id="local", user_id="operator")
    old = storage.append_message(
        "parent", role="user", content="old", metadata={"source": "ai_composer"}
    )
    manual = storage.append_message(
        "parent", role="user", content="pwd", metadata={"source": "manual_composer"}
    )

    with pytest.raises(Exception, match="latest user"):
        storage.revise_session_from_message("parent", old["id"])
    with pytest.raises(Exception, match="AI composer"):
        storage.revise_session_from_message("parent", manual["id"])


def test_run_and_event_storage_is_durable_and_replayable(storage, tmp_path):
    storage.create_session("run-session", host_id="local", user_id="operator")
    storage.create_run("run-1", session_id="run-session", user_id="operator", input_text="查看负载")
    storage.update_run("run-1", status="running")
    first = storage.append_run_event("run-1", event_type="run.started")
    storage.append_run_event("run-1", event_type="content.delta", payload={"delta": "正常"})
    storage.update_run("run-1", status="completed", output_text="正常")

    reopened = QuickOpsStorage(tmp_path / "quickops-test.db")
    assert reopened.get_run("run-1")["output_text"] == "正常"
    replay = reopened.list_run_events("run-1", after_sequence=first["sequence"])
    assert [(event["event_type"], event["payload"]) for event in replay] == [
        ("content.delta", {"delta": "正常"})
    ]


def test_existing_run_table_is_migrated_to_allow_paused_without_losing_events(tmp_path):
    db_file = tmp_path / "legacy-runs.db"
    storage = QuickOpsStorage(db_file)
    storage.create_session("s1", host_id="local", user_id="operator")
    storage.create_run("r1", session_id="s1", user_id="operator", input_text="修改配置")
    storage.append_run_event("r1", event_type="run.started")

    # Reproduce the constraint shipped by the earlier prototype.
    raw = storage.engine.raw_connection()
    cursor = raw.cursor()
    cursor.execute("PRAGMA foreign_keys=OFF")
    cursor.execute("BEGIN IMMEDIATE")
    cursor.execute(
        """
        CREATE TABLE quickops_agent_runs_legacy (
            id VARCHAR(200) NOT NULL PRIMARY KEY,
            session_id VARCHAR(200) NOT NULL,
            user_id VARCHAR(200) NOT NULL,
            status VARCHAR(24) NOT NULL,
            input_text TEXT NOT NULL,
            output_text TEXT NOT NULL,
            error TEXT,
            created_at DATETIME NOT NULL,
            started_at DATETIME,
            completed_at DATETIME,
            CONSTRAINT ck_quickops_agent_runs_status CHECK
              (status IN ('queued','running','completed','failed','cancelled')),
            FOREIGN KEY(session_id) REFERENCES quickops_sessions (id) ON DELETE CASCADE
        )
        """
    )
    cursor.execute(
        "INSERT INTO quickops_agent_runs_legacy SELECT * FROM quickops_agent_runs"
    )
    cursor.execute("DROP TABLE quickops_agent_runs")
    cursor.execute("ALTER TABLE quickops_agent_runs_legacy RENAME TO quickops_agent_runs")
    raw.commit()
    cursor.close()
    raw.close()
    storage.engine.dispose()

    migrated = QuickOpsStorage(db_file)
    migrated.update_run("r1", status="paused", output_text="等待审批")

    assert migrated.get_run("r1")["status"] == "paused"
    assert migrated.list_run_events("r1")[0]["event_type"] == "run.started"
    table_sql = migrated.engine.connect().exec_driver_sql(
        "SELECT sql FROM sqlite_master WHERE name='quickops_agent_runs'"
    ).scalar_one()
    assert "'paused'" in table_sql
