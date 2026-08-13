from __future__ import annotations

import ctypes
import os
import platform
import re
import shlex
import shutil
import socket
import subprocess
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from quickops.domain import HostSignal, HostSummary
from quickops.host_adapter import CommandNotAllowedError, HostNotAllowedError

MAX_OUTPUT_CHARS = 48_000
DEFAULT_TIMEOUT_SECONDS = 5


def _platform_slug(system_name: str | None = None) -> str:
    return {
        "darwin": "macos",
        "linux": "linux",
        "windows": "windows",
    }.get((system_name or platform.system()).casefold(), "host")


LOCAL_HOST_ID = f"local-{_platform_slug()}"
CommandRunner = Callable[[Sequence[str], int], tuple[str, int]]


def _subprocess_runner(argv: Sequence[str], timeout: int) -> tuple[str, int]:
    """Run adapter-owned argv without a shell on every supported platform."""
    env = os.environ.copy()
    env.update({"LANG": "C", "LC_ALL": "C"})
    try:
        completed = subprocess.run(
            list(argv),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            shell=False,
            env=env,
        )
    except subprocess.TimeoutExpired:
        return f"Command timed out after {timeout}s", 124
    except (OSError, ValueError) as exc:
        return f"Command unavailable: {type(exc).__name__}", 126
    output = completed.stdout
    if completed.stderr:
        output = f"{output}\n{completed.stderr}" if output else completed.stderr
    return _truncate(output.strip()), completed.returncode


def _truncate(value: str, limit: int = MAX_OUTPUT_CHARS) -> str:
    if len(value) <= limit:
        return value
    omitted = len(value) - limit
    return f"{value[:limit]}\n… output truncated ({omitted} characters omitted)"


def _redact_secrets(value: str) -> str:
    patterns = (
        (r"\bsk-[A-Za-z0-9_-]{12,}\b", "sk-[REDACTED]"),
        (
            r"(?i)\b(api[_-]?key|access[_-]?token|secret|password)\b(\s*[=:]\s*|\s+)([^\s]+)",
            r"\1\2[REDACTED]",
        ),
        (r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{12,}=*", "Bearer [REDACTED]"),
    )
    for pattern, replacement in patterns:
        value = re.sub(pattern, replacement, value)
    return value


class LocalHostAdapter:
    """Real, read-only observations for the machine running QuickOps.

    OS-specific commands are owned by the adapter and are always argv-only. User text is used
    solely for bounded in-memory filtering or an exact read-only command lookup.
    """

    def __init__(
        self,
        host_id: str | None = None,
        runner: CommandRunner | None = None,
        clock: Callable[[], float] = time.monotonic,
        system_name: str | None = None,
    ) -> None:
        self.system_name = (system_name or platform.system()).casefold()
        self.platform_slug = _platform_slug(self.system_name)
        self.host_id = host_id or f"local-{self.platform_slug}"
        self._runner = runner or _subprocess_runner
        self._uses_default_runner = runner is None
        self._clock = clock
        self._last_network_sample: tuple[float, int, int] | None = None

    def _check_host(self, host_id: str) -> None:
        if host_id != self.host_id:
            raise HostNotAllowedError(f"Host is outside this QuickOps workspace: {host_id}")

    def _run(self, argv: Sequence[str], timeout: int = DEFAULT_TIMEOUT_SECONDS) -> tuple[str, int]:
        output, code = self._runner(tuple(argv), timeout)
        return _truncate(_redact_secrets(output)), code

    def list_hosts(self) -> list[HostSummary]:
        if self.system_name == "windows":
            disk_root = Path(f"{os.environ.get('SYSTEMDRIVE', 'C:')}\\")
        else:
            disk_root = Path("/")
        disk = shutil.disk_usage(disk_root)
        network_out_kbps, network_in_kbps = self._network_rates()
        hostname = socket.gethostname().removesuffix(".local") or self.host_id
        return [
            HostSummary(
                id=self.host_id,
                name=hostname,
                ip=self._local_ip(),
                environment=os.environ.get("QUICKOPS_HOST_ENVIRONMENT", "本机环境"),
                role=os.environ.get("QUICKOPS_HOST_ROLE", "QuickOps 服务节点"),
                platform=platform.system(),
                tags=["local", self.platform_slug, platform.machine().lower()],
                online=True,
                source="local",
                is_local=True,
                signals=HostSignal(
                    cpu_percent=self._cpu_percent(),
                    load_1m=self._load_1m(),
                    memory_percent=self._memory_percent(),
                    disk_percent=round((disk.used / disk.total) * 100) if disk.total else 0,
                    network_out_kbps=network_out_kbps,
                    network_in_kbps=network_in_kbps,
                ),
            )
        ]

    def system_status(self, host_id: str) -> str:
        self._check_host(host_id)
        header = (
            f"host: {socket.gethostname()}  os: {platform.system()} {platform.release()}\n"
            f"kernel: {platform.version()}  architecture: {platform.machine()}"
        )
        if self.system_name == "darwin":
            uptime, _ = self._run(("/usr/bin/uptime",))
            top, _ = self._run(("/usr/bin/top", "-l", "1", "-n", "0"), timeout=8)
            memory, _ = self._run(("/usr/bin/vm_stat",))
            disk, _ = self._run(("/bin/df", "-h", "/"))
            details = [
                uptime,
                *(
                    line
                    for line in top.splitlines()
                    if line.startswith(("CPU usage:", "PhysMem:", "Load Avg:"))
                ),
                self._vm_summary(memory),
                disk,
            ]
        elif self.system_name == "linux":
            uptime, _ = self._run(("/usr/bin/uptime",))
            memory, _ = self._run(("/usr/bin/free", "-h"))
            disk, _ = self._run(("/bin/df", "-h", "/"))
            details = [uptime, memory, disk]
        elif self.system_name == "windows":
            script = (
                "$os=Get-CimInstance Win32_OperatingSystem;"
                "$cpu=Get-CimInstance Win32_Processor|Measure-Object LoadPercentage -Average;"
                "[pscustomobject]@{LastBoot=$os.LastBootUpTime;FreeMemoryKB=$os.FreePhysicalMemory;"
                "TotalMemoryKB=$os.TotalVisibleMemorySize;CpuPercent=$cpu.Average}|Format-List"
            )
            status, _ = self._run(self._powershell(script), timeout=10)
            disk, _ = self._run(
                self._powershell("Get-Volume|Format-Table DriveLetter,Size,SizeRemaining")
            )
            details = [status, disk]
        else:
            details = ["Detailed system metrics are unavailable on this operating system"]
        return _truncate("\n".join((header, *(item for item in details if item))))

    def process_list(self, host_id: str, process_name: str = "") -> str:
        self._check_host(host_id)
        query = process_name.strip().casefold()
        if len(query) > 80 or (query and not re.fullmatch(r"[\w .:+/@-]+", query)):
            raise CommandNotAllowedError("Process filter contains unsupported characters")
        if self.system_name == "windows":
            argv = self._powershell(
                "Get-Process|Sort-Object CPU -Descending|"
                "Select-Object -First 100 Id,ProcessName,CPU,WorkingSet64|Format-Table -AutoSize"
            )
        else:
            ps = (
                "/bin/ps"
                if Path("/bin/ps").exists() or self.system_name == "darwin"
                else "/usr/bin/ps"
            )
            argv = (ps, "-axo", "pid=,user=,%cpu=,%mem=,rss=,vsz=,stat=,comm=", "-r")
        output, code = self._run(argv, timeout=8)
        if code != 0:
            return output or "Process list unavailable"
        rows = output.splitlines()
        if query:
            rows = [row for row in rows if query in row.casefold()]
        rows = rows[:100]
        if not rows:
            return f"No processes found for {process_name!r}"
        header = "PID USER %CPU %MEM RSS(KB) VSZ(KB) STAT COMMAND"
        return _truncate("\n".join((header, *rows)))

    def journal_search(self, host_id: str, unit: str, minutes: int) -> str:
        self._check_host(host_id)
        process_by_unit = {
            "nginx": "nginx",
            "nginx.service": "nginx",
            "quickops": "QuickOps",
            "quickops.service": "QuickOps",
        }
        process = process_by_unit.get(unit.strip().casefold())
        if process is None:
            raise CommandNotAllowedError("Log source is not in the read-only allowlist")
        bounded_minutes = min(max(int(minutes), 1), 60)
        if self.system_name == "darwin":
            argv = (
                "/usr/bin/log",
                "show",
                "--last",
                f"{bounded_minutes}m",
                "--style",
                "compact",
                "--predicate",
                f'process == "{process}"',
            )
        elif self.system_name == "linux":
            argv = (
                "/usr/bin/journalctl",
                "--no-pager",
                "-u",
                unit,
                "--since",
                f"{bounded_minutes} min ago",
            )
        elif self.system_name == "windows":
            script = (
                f"Get-WinEvent -FilterHashtable @{{LogName='Application';"
                f"StartTime=(Get-Date).AddMinutes(-{bounded_minutes})}} -MaxEvents 200|"
                f"Where-Object {{$_.ProviderName -like '*{process}*'}}|"
                "Format-List TimeCreated,Message"
            )
            argv = self._powershell(script)
        else:
            return f"Log search unavailable for {unit}"
        output, code = self._run(argv, timeout=12)
        if code != 0:
            return output or f"Log search unavailable for {unit}"
        return output or f"No recent entries for {unit}"

    def gpu_status(self, host_id: str) -> str:
        """Return real NVIDIA GPU memory/utilization and active compute processes."""
        self._check_host(host_id)
        executable = shutil.which("nvidia-smi")
        if executable is None:
            return "NVIDIA GPU telemetry unavailable: nvidia-smi is not installed"
        gpu_output, gpu_code = self._run(
            (
                executable,
                "--query-gpu=index,name,uuid,memory.total,memory.used,memory.free,"
                "utilization.gpu,temperature.gpu",
                "--format=csv,noheader,nounits",
            ),
            timeout=10,
        )
        if gpu_code != 0:
            return gpu_output or "nvidia-smi failed to read GPU telemetry"
        process_output, process_code = self._run(
            (
                executable,
                "--query-compute-apps=gpu_uuid,pid,process_name,used_gpu_memory",
                "--format=csv,noheader,nounits",
            ),
            timeout=10,
        )
        processes = (
            process_output if process_code == 0 and process_output else "No compute processes"
        )
        return _truncate(
            "GPU fields: index, name, uuid, memory.total MiB, memory.used MiB, "
            "memory.free MiB, utilization %, temperature C\n"
            f"{gpu_output}\n\nCompute processes: gpu_uuid, pid, name, used_memory MiB\n"
            f"{processes}"
        )

    def run_readonly_command(self, host_id: str, command: str) -> tuple[str, int]:
        self._check_host(host_id)
        try:
            tokens = tuple(shlex.split(command.strip(), posix=self.system_name != "windows"))
        except ValueError as exc:
            raise CommandNotAllowedError("Command could not be parsed safely") from exc
        if self.system_name == "darwin":
            allowlist = {
                ("uptime",): ("/usr/bin/uptime",),
                ("uname", "-a"): ("/usr/bin/uname", "-a"),
                ("sw_vers",): ("/usr/bin/sw_vers",),
                ("whoami",): ("/usr/bin/whoami",),
                ("pwd",): ("/bin/pwd",),
                ("df", "-h", "/"): ("/bin/df", "-h", "/"),
                ("ps", "aux"): ("/bin/ps", "aux"),
            }
        elif self.system_name == "linux":
            allowlist = {
                ("uptime",): ("/usr/bin/uptime",),
                ("uname", "-a"): ("/usr/bin/uname", "-a"),
                ("whoami",): ("/usr/bin/whoami",),
                ("pwd",): ("/bin/pwd",),
                ("df", "-h", "/"): ("/bin/df", "-h", "/"),
                ("ps", "aux"): ("/bin/ps", "aux"),
            }
        elif self.system_name == "windows":
            allowlist = {
                ("whoami",): ("whoami.exe",),
                ("hostname",): ("hostname.exe",),
                ("systeminfo",): ("systeminfo.exe",),
                ("tasklist",): ("tasklist.exe",),
            }
        else:
            allowlist = {}
        argv = allowlist.get(tokens)
        if argv is None:
            raise CommandNotAllowedError("Command is not in the local read-only allowlist")
        return self._run(argv, timeout=8)

    def _cpu_percent(self) -> int:
        if self.system_name == "darwin":
            output, code = self._run(("/usr/bin/top", "-l", "1", "-n", "0"), timeout=8)
            match = re.search(r"([\d.]+)%\s*idle", output, re.IGNORECASE) if code == 0 else None
            if match:
                return min(max(round(100 - float(match.group(1))), 0), 100)
            return self._darwin_cpu_percent()
        if self.system_name == "linux":
            try:
                first = self._read_linux_cpu()
                time.sleep(0.1)
                second = self._read_linux_cpu()
                total = sum(second) - sum(first)
                idle = (second[3] + second[4]) - (first[3] + first[4])
                return min(max(round(100 * (total - idle) / total), 0), 100) if total else 0
            except (OSError, ValueError, IndexError):
                return 0
        if self.system_name == "windows":
            output, code = self._run(
                self._powershell(
                    "(Get-CimInstance Win32_Processor|"
                    "Measure-Object LoadPercentage -Average).Average"
                )
            )
            try:
                return min(max(round(float(output)), 0), 100) if code == 0 else 0
            except ValueError:
                return 0
        return 0

    @staticmethod
    def _read_linux_cpu() -> tuple[int, ...]:
        values = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0].split()[1:]
        return tuple(int(value) for value in values)

    @staticmethod
    def _darwin_cpu_percent() -> int:
        """Sample Mach CPU ticks when `top` is unavailable in a restricted service."""
        try:
            library = ctypes.CDLL("/usr/lib/libSystem.B.dylib")

            def sample() -> tuple[int, ...]:
                ticks = (ctypes.c_uint * 4)()
                count = ctypes.c_uint(4)
                result = library.host_statistics(
                    library.mach_host_self(), 3, ctypes.byref(ticks), ctypes.byref(count)
                )
                if result != 0:
                    raise OSError("host_statistics failed")
                return tuple(ticks)

            first = sample()
            time.sleep(0.1)
            second = sample()
            delta = tuple((second[index] - first[index]) % (2**32) for index in range(4))
            total = sum(delta)
            return min(max(round((total - delta[2]) / total * 100), 0), 100) if total else 0
        except (AttributeError, OSError, ValueError):
            return 0

    def _load_1m(self) -> float:
        try:
            return round(os.getloadavg()[0], 2)
        except (AttributeError, OSError):
            return 0.0

    def _memory_percent(self) -> int:
        if self.system_name == "darwin":
            total_output, total_code = self._run(("/usr/sbin/sysctl", "-n", "hw.memsize"))
            vm_output, vm_code = self._run(("/usr/bin/vm_stat",))
            try:
                if total_code == 0:
                    total = int(total_output.strip())
                elif self._uses_default_runner:
                    total = os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE")
                else:
                    total = 0
            except (OSError, ValueError):
                total = 0
            page_match = re.search(r"page size of (\d+) bytes", vm_output)
            if not page_match or total <= 0:
                return 0
            pages = {
                key.strip().casefold(): int(value)
                for key, value in re.findall(r"^Pages ([^:]+):\s+(\d+)\.", vm_output, re.MULTILINE)
            }
            used = sum(
                pages.get(key, 0)
                for key in ("active", "wired down", "occupied by compressor", "speculative")
            )
            return min(max(round(used * int(page_match.group(1)) / total * 100), 0), 100)
        if self.system_name == "linux":
            try:
                info = {
                    key.rstrip(":"): int(value.split()[0])
                    for key, value in (
                        line.split(maxsplit=1)
                        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines()
                    )
                }
                return round((1 - info["MemAvailable"] / info["MemTotal"]) * 100)
            except (OSError, ValueError, KeyError):
                return 0
        if self.system_name == "windows":
            script = (
                "$o=Get-CimInstance Win32_OperatingSystem;"
                "[math]::Round((1-$o.FreePhysicalMemory/$o.TotalVisibleMemorySize)*100)"
            )
            output, code = self._run(self._powershell(script))
            try:
                return min(max(round(float(output)), 0), 100) if code == 0 else 0
            except ValueError:
                return 0
        return 0

    @staticmethod
    def _vm_summary(vm_output: str) -> str:
        lines = [line for line in vm_output.splitlines() if line.startswith("Pages ")]
        return "vm_stat: " + ("; ".join(lines[:6]) if lines else "unavailable")

    def _local_ip(self) -> str:
        # Ask the kernel which source address it would use for the default route. UDP connect
        # sends no packet and avoids Ubuntu hostname mappings that resolve to loopback.
        if self._uses_default_runner:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as route_socket:
                    route_socket.connect(("192.0.2.1", 9))
                    routed_ip = route_socket.getsockname()[0]
                if routed_ip and not routed_ip.startswith("127."):
                    return routed_ip
            except OSError:
                pass
            try:
                addresses = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
                candidates = [
                    item[4][0] for item in addresses if not item[4][0].startswith("127.")
                ]
                if candidates:
                    return candidates[0]
            except OSError:
                pass
        if self.system_name == "darwin":
            for interface in ("en0", "en1"):
                output, code = self._run(("/usr/sbin/ipconfig", "getifaddr", interface))
                if code == 0 and re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", output.strip()):
                    return output.strip()
            output, code = self._run(("/sbin/ifconfig",))
            if code == 0:
                match = re.search(r"\binet (?!127\.)(\d{1,3}(?:\.\d{1,3}){3})", output)
                if match:
                    return match.group(1)
        return "127.0.0.1"

    def _network_rates(self) -> tuple[int, int]:
        if self.system_name == "darwin":
            output, code = self._run(("/usr/sbin/netstat", "-ibn"))
            received, sent = self._parse_macos_network_bytes(output) if code == 0 else (0, 0)
        elif self.system_name == "linux":
            try:
                received, sent = self._parse_linux_network_bytes(
                    Path("/proc/net/dev").read_text(encoding="utf-8")
                )
            except OSError:
                received, sent = 0, 0
        elif self.system_name == "windows":
            script = (
                "$s=Get-NetAdapterStatistics|Measure-Object ReceivedBytes,SentBytes -Sum;"
                "$s[0].Sum;$s[1].Sum"
            )
            output, code = self._run(self._powershell(script))
            try:
                received, sent = (
                    (int(value) for value in output.splitlines()[:2]) if code == 0 else (0, 0)
                )
            except ValueError:
                received, sent = 0, 0
        else:
            received, sent = 0, 0
        now = self._clock()
        previous = self._last_network_sample
        self._last_network_sample = (now, received, sent)
        if previous is None or now <= previous[0]:
            return 0, 0
        elapsed = now - previous[0]
        return round(max(sent - previous[2], 0) / elapsed / 1024), round(
            max(received - previous[1], 0) / elapsed / 1024
        )

    @staticmethod
    def _parse_macos_network_bytes(output: str) -> tuple[int, int]:
        lines = output.splitlines()
        header: list[str] | None = None
        totals: dict[str, tuple[int, int]] = {}
        for line in lines:
            columns = line.split()
            if "Ibytes" in columns and "Obytes" in columns:
                header = columns
                continue
            if not header or len(columns) < len(header):
                continue
            try:
                interface = columns[header.index("Name")]
                if interface.startswith("lo"):
                    continue
                ibytes, obytes = (
                    int(columns[header.index("Ibytes")]),
                    int(columns[header.index("Obytes")]),
                )
            except (ValueError, IndexError):
                continue
            previous = totals.get(interface, (0, 0))
            totals[interface] = max(previous[0], ibytes), max(previous[1], obytes)
        return sum(value[0] for value in totals.values()), sum(
            value[1] for value in totals.values()
        )

    @staticmethod
    def _parse_linux_network_bytes(output: str) -> tuple[int, int]:
        received = sent = 0
        for line in output.splitlines()[2:]:
            if ":" not in line:
                continue
            interface, values = line.split(":", 1)
            if interface.strip() == "lo":
                continue
            columns = values.split()
            if len(columns) >= 9:
                received += int(columns[0])
                sent += int(columns[8])
        return received, sent

    @staticmethod
    def _powershell(script: str) -> tuple[str, ...]:
        executable = shutil.which("pwsh") or shutil.which("powershell") or "powershell.exe"
        return executable, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", script


# Compatibility name used by the existing runtime. It now dispatches by the actual OS.
LocalMacOSHostAdapter = LocalHostAdapter
