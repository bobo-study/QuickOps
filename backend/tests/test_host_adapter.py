import pytest
from quickops.host_adapter import CommandNotAllowedError, DemoHostAdapter, HostNotAllowedError


@pytest.fixture
def adapter() -> DemoHostAdapter:
    return DemoHostAdapter(("prod-web-03",))


def test_inventory_is_scoped_to_allowed_hosts(adapter: DemoHostAdapter) -> None:
    hosts = adapter.list_hosts()
    assert [host.id for host in hosts] == ["prod-web-03"]
    assert hosts[0].signals.cpu_percent == 92


def test_rejects_host_outside_workspace(adapter: DemoHostAdapter) -> None:
    with pytest.raises(HostNotAllowedError):
        adapter.system_status("prod-db-01")


def test_manual_command_allowlist(adapter: DemoHostAdapter) -> None:
    output, exit_code = adapter.run_readonly_command("prod-web-03", "systemctl   status nginx")
    assert exit_code == 0
    assert "Active: active (running)" in output

    with pytest.raises(CommandNotAllowedError):
        adapter.run_readonly_command("prod-web-03", "systemctl restart nginx")


def test_nginx_journal_evidence_is_available(adapter: DemoHostAdapter) -> None:
    output = adapter.journal_search("prod-web-03", "nginx.service", 10)
    assert "upstream timed out" in output
    assert "connect() failed" in output


def test_demo_gpu_status_is_readonly_evidence(adapter: DemoHostAdapter) -> None:
    assert "GPU telemetry" in adapter.gpu_status("prod-web-03")
