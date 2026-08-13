from __future__ import annotations

from collections import namedtuple
from collections.abc import Sequence
from types import SimpleNamespace

import pytest
from quickops.host_adapter import CommandNotAllowedError, HostNotAllowedError
from quickops.local_host_adapter import (
    LocalHostAdapter,
    LocalMacOSHostAdapter,
    _subprocess_runner,
)


class FakeRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], int]] = []
        self.network_calls = 0

    def __call__(self, argv: Sequence[str], timeout: int) -> tuple[str, int]:
        args = tuple(argv)
        self.calls.append((args, timeout))
        fixtures = {
            ("/usr/bin/top", "-l", "1", "-n", "0"): (
                "Load Avg: 1.2, 1.1, 1.0\nCPU usage: 10% user, 5% sys, 85% idle\n"
                "PhysMem: 8G used, 8G unused.",
                0,
            ),
            ("/usr/sbin/sysctl", "-n", "hw.memsize"): ("17179869184", 0),
            ("/usr/bin/vm_stat",): (
                "Mach Virtual Memory Statistics: (page size of 16384 bytes)\n"
                "Pages free: 100000.\nPages active: 400000.\n"
                "Pages speculative: 10000.\nPages wired down: 200000.\n"
                "Pages occupied by compressor: 50000.",
                0,
            ),
            ("/usr/sbin/ipconfig", "getifaddr", "en0"): ("192.0.2.20", 0),
            ("/usr/bin/uptime",): ("10:00 up 2 days, load averages: 1.2 1.1 1.0", 0),
            ("/bin/df", "-h", "/"): ("Filesystem Size Used Avail Capacity Mounted on", 0),
            ("/bin/ps", "aux"): ("USER PID COMMAND\nme 1 launchd", 0),
            ("/bin/ps", "-axo", "pid=,user=,%cpu=,%mem=,rss=,vsz=,stat=,comm=", "-r"): (
                "12 me 10.0 1.0 100 200 R nginx worker\n13 me 1.0 0.2 50 100 S python api",
                0,
            ),
        }
        if args == ("/usr/sbin/netstat", "-ibn"):
            self.network_calls += 1
            bump = self.network_calls * 1024
            return (
                "Name Mtu Network Address Ipkts Ierrs Ibytes Opkts Oerrs Obytes Coll\n"
                f"en0 1500 Link aa 1 0 {1000 + bump} 2 0 {2000 + bump} 0",
                0,
            )
        if args[:2] == ("/usr/bin/log", "show"):
            return "nginx: test log entry", 0
        return fixtures.get(args, ("", 1))


def test_inventory_uses_live_local_observations(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = FakeRunner()
    times = iter((10.0, 11.0))
    adapter = LocalMacOSHostAdapter(runner=runner, clock=lambda: next(times))
    monkeypatch.setattr("quickops.local_host_adapter.os.getloadavg", lambda: (1.25, 1.0, 0.5))
    DiskUsage = namedtuple("DiskUsage", "total used free")
    monkeypatch.setattr(
        "quickops.local_host_adapter.shutil.disk_usage", lambda _path: DiskUsage(1000, 400, 600)
    )

    first = adapter.list_hosts()[0]
    second = adapter.list_hosts()[0]
    assert first.id == "local-macos"
    assert first.name
    assert first.source == "local"
    assert first.is_local is True
    assert first.ip == "192.0.2.20"
    assert first.signals.cpu_percent == 15
    assert first.signals.load_1m == 1.25
    assert first.signals.disk_percent == 40
    assert first.signals.network_in_kbps == 0
    assert second.signals.network_in_kbps == 1
    assert second.signals.network_out_kbps == 1


def test_process_filter_is_in_memory_and_bounded() -> None:
    runner = FakeRunner()
    adapter = LocalMacOSHostAdapter(runner=runner)
    output = adapter.process_list("local-macos", "nginx")
    assert "nginx worker" in output
    assert "python api" not in output
    ps_call = next(call for call in runner.calls if call[0][0] == "/bin/ps")
    assert "nginx" not in ps_call[0]

    with pytest.raises(CommandNotAllowedError):
        adapter.process_list("local-macos", "nginx; rm -rf /")


def test_log_search_is_allowlisted_and_time_bounded() -> None:
    runner = FakeRunner()
    adapter = LocalMacOSHostAdapter(runner=runner)
    assert "test log" in adapter.journal_search("local-macos", "nginx.service", 500)
    log_call = next(call for call in runner.calls if call[0][:2] == ("/usr/bin/log", "show"))
    assert "60m" in log_call[0]
    assert log_call[1] == 12
    with pytest.raises(CommandNotAllowedError):
        adapter.journal_search("local-macos", "../../private", 10)


def test_manual_commands_are_exact_allowlist_entries() -> None:
    runner = FakeRunner()
    adapter = LocalMacOSHostAdapter(runner=runner)
    output, code = adapter.run_readonly_command("local-macos", "df -h /")
    assert code == 0
    assert "Filesystem" in output
    assert runner.calls[-1][0] == ("/bin/df", "-h", "/")

    for command in ("rm -rf /", "echo hello", "ps aux | cat", "uname -a; id"):
        with pytest.raises(CommandNotAllowedError):
            adapter.run_readonly_command("local-macos", command)


def test_wrong_host_fails_closed() -> None:
    adapter = LocalMacOSHostAdapter(runner=FakeRunner())
    with pytest.raises(HostNotAllowedError):
        adapter.system_status("prod-web-03")


def test_process_output_redacts_common_secret_shapes() -> None:
    def runner(_argv: Sequence[str], _timeout: int) -> tuple[str, int]:
        return "12 me 1 1 1 1 S worker --api-key=sk-abcdefghijklmnop", 0

    adapter = LocalMacOSHostAdapter(runner=runner)
    output = adapter.process_list("local-macos")
    assert "abcdefghijklmnop" not in output
    assert "[REDACTED]" in output


def test_subprocess_runner_never_invokes_a_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(argv: list[str], **kwargs: object) -> SimpleNamespace:
        captured["argv"] = argv
        captured.update(kwargs)
        return SimpleNamespace(stdout="ok", stderr="", returncode=0)

    monkeypatch.setattr("quickops.local_host_adapter.subprocess.run", fake_run)
    output, code = _subprocess_runner(("/usr/bin/uptime",), 3)
    assert (output, code) == ("ok", 0)
    assert captured["argv"] == ["/usr/bin/uptime"]
    assert captured["shell"] is False
    assert captured["timeout"] == 3


def test_linux_adapter_uses_linux_diagnostics() -> None:
    calls: list[tuple[str, ...]] = []

    def runner(argv: Sequence[str], _timeout: int) -> tuple[str, int]:
        calls.append(tuple(argv))
        return "linux metric", 0

    adapter = LocalHostAdapter(system_name="Linux", runner=runner)
    output = adapter.system_status("local-linux")

    assert "os:" in output
    assert ("/usr/bin/uptime",) in calls
    assert ("/usr/bin/free", "-h") in calls
    assert ("/bin/df", "-h", "/") in calls


def test_gpu_status_uses_bounded_nvidia_queries(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, ...]] = []

    def runner(argv: Sequence[str], _timeout: int) -> tuple[str, int]:
        calls.append(tuple(argv))
        if "--query-gpu" in argv[1]:
            return "0, RTX 3090, GPU-1, 24576, 1024, 23552, 10, 42", 0
        return "GPU-1, 123, python, 512", 0

    monkeypatch.setattr("quickops.local_host_adapter.shutil.which", lambda _: "/usr/bin/nvidia-smi")
    adapter = LocalHostAdapter(system_name="Linux", runner=runner)
    output = adapter.gpu_status("local-linux")

    assert "RTX 3090" in output
    assert "python" in output
    assert len(calls) == 2


def test_windows_adapter_uses_powershell_diagnostics() -> None:
    calls: list[tuple[str, ...]] = []

    def runner(argv: Sequence[str], _timeout: int) -> tuple[str, int]:
        calls.append(tuple(argv))
        return "windows metric", 0

    adapter = LocalHostAdapter(system_name="Windows", runner=runner)
    output = adapter.system_status("local-windows")

    assert "os:" in output
    assert len(calls) == 2
    assert all("-NoProfile" in argv for argv in calls)
    assert all("-Command" in argv for argv in calls)


def test_linux_network_parser_excludes_loopback() -> None:
    output = (
        "Inter-| Receive | Transmit\n face |bytes |bytes\n"
        " lo: 100 0 0 0 0 0 0 0 200 0 0 0 0 0 0 0\n"
        " eth0: 1024 0 0 0 0 0 0 0 2048 0 0 0 0 0 0 0"
    )
    assert LocalHostAdapter._parse_linux_network_bytes(output) == (1024, 2048)
