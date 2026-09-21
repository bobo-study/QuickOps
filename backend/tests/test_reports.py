import json
from pathlib import Path

from fastapi.testclient import TestClient
from quickops.api import create_app
from quickops.local_host_adapter import LocalHostAdapter
from quickops.reports import ReportArtifactStore, ReportToolkit
from quickops.settings import Settings


def test_report_toolkit_creates_downloadable_formats(tmp_path: Path) -> None:
    store = ReportArtifactStore(tmp_path / "reports")
    toolkit = ReportToolkit(store, "session-1")

    for file_format in ("md", "txt", "html", "json", "docx", "pdf"):
        result = json.loads(
            toolkit.create_report("Nginx 诊断", "## 结论\n\n- 服务正常", file_format)
        )
        assert result["download_url"]
        report_id = result["report_id"]
        artifact = store.resolve("session-1", report_id)
        assert artifact["format"] == file_format
        assert Path(artifact["path"]).stat().st_size > 0


def test_report_download_is_authenticated_and_session_scoped(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        quickops_db_file=tmp_path / "quickops.db",
        quickops_workspace_root=tmp_path,
        quickops_auth_username="operator",
        quickops_auth_password="test-password",
    )
    store = ReportArtifactStore(tmp_path / "reports")
    with TestClient(
        create_app(settings, host_adapter=LocalHostAdapter(system_name="darwin"))
    ) as client:
        client.post(
            "/api/quickops/auth/login",
            json={"username": "operator", "password": "test-password"},
        )
        first = client.post(
            "/api/quickops/sessions", json={"title": "first", "host_id": "local-macos"}
        ).json()["session"]
        second = client.post(
            "/api/quickops/sessions", json={"title": "second", "host_id": "local-macos"}
        ).json()["session"]
        artifact = store.create(
            first["id"], title="测试报告", content="完整内容", file_format="docx"
        )

        ok = client.get(f"/api/quickops/sessions/{first['id']}/reports/{artifact['id']}")
        wrong_session = client.get(
            f"/api/quickops/sessions/{second['id']}/reports/{artifact['id']}"
        )
        client.cookies.clear()
        unauthenticated = client.get(
            f"/api/quickops/sessions/{first['id']}/reports/{artifact['id']}"
        )

    assert ok.status_code == 200
    assert ok.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument")
    assert wrong_session.status_code == 404
    assert unauthenticated.status_code == 401
