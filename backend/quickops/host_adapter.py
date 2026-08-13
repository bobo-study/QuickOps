from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from quickops.domain import HostSignal, HostSummary


class HostNotAllowedError(ValueError):
    pass


class CommandNotAllowedError(ValueError):
    pass


class HostAdapter(Protocol):
    def list_hosts(self) -> list[HostSummary]: ...

    def system_status(self, host_id: str) -> str: ...

    def process_list(self, host_id: str, process_name: str) -> str: ...

    def journal_search(self, host_id: str, unit: str, minutes: int) -> str: ...

    def gpu_status(self, host_id: str) -> str: ...

    def run_readonly_command(self, host_id: str, command: str) -> tuple[str, int]: ...


@dataclass(frozen=True)
class DemoHostAdapter:
    """Deterministic adapter for the first safe vertical slice.

    The Harness Agent already speaks the final HostAdapter contract. Replacing this adapter with
    an SSH/agent transport does not change Agno tools or the product API.
    """

    allowed_hosts: tuple[str, ...]

    def _check_host(self, host_id: str) -> None:
        if host_id not in self.allowed_hosts:
            raise HostNotAllowedError(f"Host is outside this QuickOps workspace: {host_id}")

    def list_hosts(self) -> list[HostSummary]:
        hosts: list[HostSummary] = []
        if "prod-web-03" in self.allowed_hosts:
            hosts.append(
                HostSummary(
                    id="prod-web-03",
                    ip="192.0.2.23",
                    environment="生产环境",
                    role="Web 节点",
                    tags=["web", "nginx", "prod"],
                    online=True,
                    signals=HostSignal(
                        cpu_percent=92,
                        load_1m=2.41,
                        memory_percent=86,
                        disk_percent=63,
                        network_out_kbps=78,
                        network_in_kbps=112,
                    ),
                )
            )
        return hosts

    def system_status(self, host_id: str) -> str:
        self._check_host(host_id)
        return (
            "host: prod-web-03  kernel: 5.15.0-101-generic  uptime: 15d 02:11\n"
            "load avg: 2.41, 2.18, 1.95  cpu usage: 92% user, 6% system, 2% iowait\n"
            "mem: 15.6G total, 2.1G free  swap: 2.0G total, 2.0G free"
        )

    def process_list(self, host_id: str, process_name: str) -> str:
        self._check_host(host_id)
        if process_name.lower() != "nginx":
            return f"No processes found for {process_name!r}"
        return (
            "PID    USER    %CPU  %MEM  RSS   VSZ   STAT  COMMAND\n"
            "27154  nginx   87.3  1.2   118m  284m  R     nginx: worker process\n"
            "27148  nginx   1.1   0.9   92m   221m  S     nginx: worker process\n"
            "27146  nginx   0.9   0.8   88m   218m  S     nginx: worker process\n"
            "26931  nginx   0.6   0.7   76m   198m  S     nginx: master process"
        )

    def journal_search(self, host_id: str, unit: str, minutes: int) -> str:
        self._check_host(host_id)
        if unit != "nginx.service":
            return f"No recent priority>=3 entries for {unit}"
        bounded_minutes = min(max(minutes, 1), 60)
        return (
            f'Search: unit={unit} priority>=3 since="{bounded_minutes} min ago"\n'
            "10:07:12 nginx[27154]: upstream timed out while reading response header\n"
            "10:08:21 nginx[27154]: upstream response is buffered to a temporary file\n"
            "10:08:47 nginx[27154]: connect() failed (111: Connection refused)\n"
            "total: 28 entries"
        )

    def run_readonly_command(self, host_id: str, command: str) -> tuple[str, int]:
        self._check_host(host_id)
        normalized = " ".join(command.strip().split())
        handlers = {
            "systemctl status nginx": (
                "● nginx.service - A high performance web server\n"
                "   Loaded: loaded (/lib/systemd/system/nginx.service; enabled)\n"
                "   Active: active (running) since Thu 2026-07-31 08:12:09 CST",
                0,
            ),
            "uptime": ("10:15:03 up 15 days, 2:11, 1 user, load average: 2.41, 2.18, 1.95", 0),
        }
        if normalized not in handlers:
            raise CommandNotAllowedError(
                "Command is not in the read-only allowlist for this vertical slice"
            )
        return handlers[normalized]

    def gpu_status(self, host_id: str) -> str:
        self._check_host(host_id)
        return "No GPU telemetry is available in the demo adapter"
