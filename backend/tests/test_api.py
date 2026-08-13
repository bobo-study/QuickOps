import shlex
from pathlib import Path

from fastapi.testclient import TestClient
from quickops.api import create_app
from quickops.settings import Settings


def build_client(tmp_path: Path) -> TestClient:
    settings = Settings(
        _env_file=None,
        siliconflow_api_key=None,
        quickops_db_file=tmp_path / "quickops-test.db",
        quickops_allowed_hosts=("prod-web-03",),
        quickops_workspace_root=tmp_path,
        quickops_auth_username="operator",
        quickops_auth_password="correct-horse-battery-staple",
    )
    client = TestClient(create_app(settings))
    response = client.post(
        "/api/quickops/auth/login",
        json={"username": "operator", "password": "correct-horse-battery-staple"},
    )
    assert response.status_code == 200
    return client


def test_login_is_required_and_logout_invalidates_session(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        quickops_db_file=tmp_path / "auth.db",
        quickops_workspace_root=tmp_path,
        quickops_auth_username="operator",
        quickops_auth_password="server-only-password",
    )
    with TestClient(create_app(settings)) as client:
        assert client.get("/api/quickops/health").status_code == 200
        assert client.get("/api/quickops/bootstrap").status_code == 401
        assert client.get("/api/quickops/auth/status").json()["authenticated"] is False
        assert client.post(
            "/api/quickops/auth/login",
            json={"username": "operator", "password": "wrong"},
        ).status_code == 401
        logged_in = client.post(
            "/api/quickops/auth/login",
            json={"username": "operator", "password": "server-only-password"},
        )
        assert logged_in.status_code == 200
        assert logged_in.cookies.get("quickops_session")
        cookie_header = logged_in.headers["set-cookie"]
        assert "HttpOnly" in cookie_header
        assert "SameSite=lax" in cookie_header
        assert "Path=/" in cookie_header
        assert "Secure" not in cookie_header
        bearer = logged_in.json()["access_token"]
        client.cookies.clear()
        authorization = {"Authorization": f"Bearer {bearer}"}
        assert client.get("/api/quickops/auth/status", headers=authorization).json()[
            "authenticated"
        ] is True
        assert client.get("/api/quickops/bootstrap", headers=authorization).status_code == 200
        assert client.post("/api/quickops/auth/logout", headers=authorization).status_code == 204
        assert client.get("/api/quickops/bootstrap", headers=authorization).status_code == 401

        # Cookie auth remains the preferred path and can be established again.
        logged_in = client.post(
            "/api/quickops/auth/login",
            json={"username": "operator", "password": "server-only-password"},
        )
        assert logged_in.status_code == 200
        assert client.get("/api/quickops/bootstrap").status_code == 200
        assert client.post("/api/quickops/auth/logout").status_code == 204
        assert client.get("/api/quickops/bootstrap").status_code == 401


def test_missing_login_environment_fails_closed(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        quickops_db_file=tmp_path / "unconfigured-auth.db",
        quickops_workspace_root=tmp_path,
    )
    with TestClient(create_app(settings)) as client:
        status = client.get("/api/quickops/auth/status").json()
        login = client.post(
            "/api/quickops/auth/login",
            json={"username": "operator", "password": "anything"},
        )
        assert status == {"configured": False, "authenticated": False, "username": None}
        assert login.status_code == 503
        assert client.get("/api/quickops/sessions").status_code == 401


def test_api_can_serve_offline_ui_without_nginx(tmp_path: Path) -> None:
    static_dir = tmp_path / "client"
    assets_dir = static_dir / "assets"
    assets_dir.mkdir(parents=True)
    (static_dir / "index.html").write_text(
        '<!doctype html><script type="module" src="/assets/app.js"></script>',
        encoding="utf-8",
    )
    (assets_dir / "app.js").write_text("window.quickops = true;", encoding="utf-8")
    settings = Settings(
        _env_file=None,
        quickops_db_file=tmp_path / "static.db",
        quickops_workspace_root=tmp_path,
        quickops_static_dir=static_dir,
        quickops_auth_username="operator",
        quickops_auth_password="server-only-password",
    )

    with TestClient(create_app(settings)) as client:
        index = client.get("/")
        asset = client.get("/assets/app.js")

        assert index.status_code == 200
        assert "/assets/app.js" in index.text
        assert index.headers["cache-control"] == "no-store"
        assert asset.status_code == 200
        assert asset.text == "window.quickops = true;"
        assert client.get("/api/quickops/bootstrap").status_code == 401


def test_health_and_bootstrap(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        assert client.get("/api/quickops/health").json() == {
            "status": "ok",
            "agent_id": "quickops-harness",
        }
        payload = client.get("/api/quickops/bootstrap").json()

    assert payload["model_id"] == "deepseek-ai/DeepSeek-V4-Flash"
    assert payload["model_configured"] is False
    assert payload["permission_mode"] == "approval"
    assert payload["hosts"][0]["id"] == "local-macos"
    assert payload["hosts"][0]["is_local"] is True
    assert payload["permission_modes_enabled"] == [
        "readonly",
        "approval",
        "delegated_approval",
        "full_access",
    ]


def test_run_requires_server_side_model_credential(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        response = client.post(
            "/api/quickops/runs",
            json={
                "message": "排查 nginx CPU",
                "host_id": "local-macos",
                "session_id": "session-1",
            },
        )
    assert response.status_code == 503
    assert "凭据" in response.json()["detail"]


def test_manual_command_forwards_native_shell_without_ai_policy(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        allowed = client.post(
            "/api/quickops/manual-commands",
            json={
                "host_id": "local-macos",
                "command": "uptime",
                "session_id": "session-1",
            },
        )
        piped = client.post(
            "/api/quickops/manual-commands",
            json={
                "host_id": "local-macos",
                "command": "printf 'quickops\\n' | tr a-z A-Z",
                "session_id": "session-1",
            },
        )
        audit_events = client.get("/api/quickops/audit-events").json()["events"]

    assert allowed.status_code == 200
    assert allowed.json()["exit_code"] == 0
    assert allowed.json()["user_message_id"]
    assert allowed.json()["message_id"]
    assert allowed.json()["user_message_id"] != allowed.json()["message_id"]
    assert piped.status_code == 200
    assert "QUICKOPS" in piped.json()["output"]
    assert audit_events == []


def test_session_attachment_upload_is_durable_and_session_scoped(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        first = client.post(
            "/api/quickops/sessions", json={"title": "files", "host_id": "local-macos"}
        ).json()["session"]
        second = client.post(
            "/api/quickops/sessions", json={"title": "other", "host_id": "local-macos"}
        ).json()["session"]
        uploaded = client.post(
            f"/api/quickops/sessions/{first['id']}/attachments",
            files={"upload": ("nginx.log", b"upstream timed out\n", "text/plain")},
        )

        assert uploaded.status_code == 201
        attachment = uploaded.json()["attachment"]
        assert attachment["name"] == "nginx.log"
        assert attachment["size"] == len(b"upstream timed out\n")
        assert "path" not in attachment
        assert (
            client.delete(
                f"/api/quickops/sessions/{second['id']}/attachments/{attachment['id']}"
            ).status_code
            == 404
        )
        assert (
            client.delete(
                f"/api/quickops/sessions/{first['id']}/attachments/{attachment['id']}"
            ).status_code
            == 204
        )
        uploaded_again = client.post(
            f"/api/quickops/sessions/{first['id']}/attachments",
            files={"upload": ("again.txt", b"cleanup", "text/plain")},
        )
        assert uploaded_again.status_code == 201
        attachment_dir = tmp_path / "attachments" / first["id"]
        assert attachment_dir.is_dir()
        assert client.delete(f"/api/quickops/sessions/{first['id']}").status_code == 204
        assert not attachment_dir.exists()


def test_manual_terminal_keeps_state_until_restart_or_close(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        session = client.post(
            "/api/quickops/sessions", json={"title": "terminal", "host_id": "local-macos"}
        ).json()["session"]
        session_id = session["id"]
        initial = client.get(f"/api/quickops/sessions/{session_id}/terminal").json()
        prepared = client.post(
            "/api/quickops/manual-commands",
            json={
                "host_id": "local-macos",
                "session_id": session_id,
                "command": (
                    f"cd {shlex.quote(str(tmp_path))} && export QUICKOPS_API_TERMINAL=kept"
                ),
            },
        )
        observed = client.post(
            "/api/quickops/manual-commands",
            json={
                "host_id": "local-macos",
                "session_id": session_id,
                "command": 'printf "%s|%s" "$PWD" "$QUICKOPS_API_TERMINAL"',
            },
        )
        status = client.get(f"/api/quickops/sessions/{session_id}/terminal").json()
        restarted = client.post(
            f"/api/quickops/sessions/{session_id}/terminal/restart"
        ).json()
        reset_value = client.post(
            "/api/quickops/manual-commands",
            json={
                "host_id": "local-macos",
                "session_id": session_id,
                "command": 'printf %s "${QUICKOPS_API_TERMINAL-unset}"',
            },
        )
        closed = client.post(
            f"/api/quickops/sessions/{session_id}/terminal/close"
        ).json()

    assert prepared.status_code == 200
    assert initial["terminal_alive"] is True
    assert initial["status"] == "active"
    assert initial["cwd"] == str(tmp_path)
    assert observed.json()["output"] == f"{tmp_path}|kept"
    assert observed.json()["cwd"] == str(tmp_path)
    assert status["terminal_alive"] is True
    assert restarted["terminal_alive"] is True
    assert reset_value.json()["output"] == "unset"
    assert closed["terminal_alive"] is False
    assert closed["cwd"] == str(tmp_path)


def test_entering_a_conversation_restores_its_terminal(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        session = client.post(
            "/api/quickops/sessions", json={"title": "terminal", "host_id": "local-macos"}
        ).json()["session"]
        session_id = session["id"]

        assert session["terminal"]["terminal_alive"] is True
        assert session["terminal_status"] == "connected"

        client.post(f"/api/quickops/sessions/{session_id}/terminal/close")
        restored = client.get(
            f"/api/quickops/sessions/{session_id}/terminal"
        ).json()

    assert restored["terminal_alive"] is True
    assert restored["status"] == "active"


def test_configured_models_are_not_deletable_and_store_thinking_mode(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        created = client.post(
            "/api/quickops/models",
            json={
                "name": "Local SGLang",
                "provider": "SGLang",
                "model_id": "Qwen/Qwen3-32B",
                "base_url": "http://127.0.0.1:30000/v1",
                "api_key": "local-key",
                "thinking_mode": "off",
                "max_context_k": 256,
            },
        )
        model = created.json()["model"]
        deleted = client.delete(f"/api/quickops/models/{model['id']}")

    assert model["thinking_mode"] == "off"
    assert model["max_context_k"] == 256
    assert model["can_delete"] is False
    assert deleted.status_code == 409


def test_new_session_appears_and_manual_output_is_persisted(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        created = client.post(
            "/api/quickops/sessions",
            json={"title": "新会话", "host_id": "local-macos"},
        )
        session_id = created.json()["session"]["id"]
        executed = client.post(
            "/api/quickops/manual-commands",
            json={"host_id": "local-macos", "command": "uptime", "session_id": session_id},
        )
        sessions = client.get("/api/quickops/sessions").json()["sessions"]
        messages = client.get(
            f"/api/quickops/sessions/{session_id}/messages"
        ).json()["messages"]

    assert created.status_code == 201
    assert executed.status_code == 200
    assert sessions[0]["id"] == session_id
    # No test credential is configured, so the independent title model cannot run here.
    assert sessions[0]["title"] == "新会话"
    assert [message["role"] for message in messages] == ["user", "tool"]
    assert messages[1]["kind"] == "manual"


def test_manual_mutation_executes_without_ai_approval_or_audit(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        created = client.post(
            "/api/quickops/sessions",
            json={
                "title": "审批测试",
                "host_id": "local-macos",
                "permission_mode": "approval",
            },
        ).json()["session"]
        requested = client.post(
            "/api/quickops/manual-commands",
            json={
                "host_id": "local-macos",
                "command": f"touch {tmp_path / 'manual-created.txt'}",
                "session_id": created["id"],
            },
        )
        events = client.get(
            f"/api/quickops/audit-events?session_id={created['id']}"
        ).json()["events"]
        messages = client.get(
            f"/api/quickops/sessions/{created['id']}/messages"
        ).json()["messages"]

    assert requested.status_code == 200
    assert (tmp_path / "manual-created.txt").exists()
    assert events == []
    assert [message["role"] for message in messages] == ["user", "tool"]


def test_model_api_never_returns_secret(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        created = client.post(
            "/api/quickops/models",
            json={
                "name": "Test Model",
                "provider": "OpenAI compatible",
                "model_id": "test/model",
                "base_url": "https://example.invalid/v1",
                "api_key": "super-secret-value",
            },
        )
        listed = client.get("/api/quickops/models")

    assert created.status_code == 201
    assert created.json()["model"]["has_api_key"] is True
    assert "super-secret-value" not in created.text
    assert "super-secret-value" not in listed.text


def test_toolbox_defaults_off_and_persists_only_known_tool_ids(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        initial = client.get("/api/quickops/toolbox")
        saved = client.put(
            "/api/quickops/settings/agent_toolbox_enabled",
            json={"value": ["coding", "database.duckdb"]},
        )
        updated = client.get("/api/quickops/toolbox")
        unknown = client.put(
            "/api/quickops/settings/agent_toolbox_enabled",
            json={"value": ["not-an-agno-tool"]},
        )

    assert initial.status_code == 200
    assert all(tool["enabled"] is False for tool in initial.json()["tools"])
    assert saved.status_code == 200
    enabled = {tool["id"] for tool in updated.json()["tools"] if tool["enabled"]}
    assert enabled == {"coding", "database.duckdb"}
    assert unknown.status_code == 422


def test_general_settings_api_rejects_toolkit_secrets(tmp_path: Path) -> None:
    with build_client(tmp_path) as client:
        response = client.put(
            "/api/quickops/settings/toolkit_config",
            json={"value": {"database.postgres": {"password": "must-not-store"}}},
        )
        settings = client.get("/api/quickops/settings")

    assert response.status_code == 403
    assert "must-not-store" not in settings.text


def test_audit_retention_setting_is_retired_and_removed(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        quickops_db_file=tmp_path / "audit-retention.db",
        quickops_workspace_root=tmp_path,
        quickops_auth_username="operator",
        quickops_auth_password="server-only-password",
    )
    from quickops.storage import QuickOpsStorage

    QuickOpsStorage(settings.quickops_db_file).set_setting("audit_retention_days", 90)
    with TestClient(create_app(settings)) as client:
        client.post(
            "/api/quickops/auth/login",
            json={"username": "operator", "password": "server-only-password"},
        )
        listed = client.get("/api/quickops/settings")
        update = client.put(
            "/api/quickops/settings/audit_retention_days", json={"value": 30}
        )

    assert "audit_retention_days" not in listed.json()["settings"]
    assert update.status_code == 410
