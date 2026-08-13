from __future__ import annotations

import contextlib
import os
import platform
import queue
import secrets
import shlex
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class CommandRisk(StrEnum):
    READONLY = "readonly"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    PROHIBITED = "prohibited"


class CommandPolicyError(ValueError):
    pass


class CommandExecutionError(RuntimeError):
    pass


@dataclass(frozen=True)
class CommandDecision:
    command: str
    argv: tuple[str, ...]
    risk: CommandRisk
    reason: str


@dataclass(frozen=True)
class CommandResult:
    output: str
    exit_code: int
    truncated: bool


@dataclass(frozen=True)
class TerminalCommandResult(CommandResult):
    """Result returned by a long-lived operator terminal."""

    cwd: str
    terminal_alive: bool = True


class CommandPolicy:
    """Classify argv by observable impact; only malformed control syntax is rejected outright."""

    _readonly_commands = {
        "date",
        "cat",
        "column",
        "cut",
        "diff",
        "df",
        "dirname",
        "du",
        "echo",
        "env",
        "file",
        "find",
        "free",
        "grep",
        "hostname",
        "id",
        "ifconfig",
        "ip",
        "journalctl",
        "less",
        "lsof",
        "more",
        "ls",
        "lsblk",
        "netstat",
        "nvidia-smi",
        "nslookup",
        "pgrep",
        "ping",
        "ps",
        "printf",
        "pwd",
        "readlink",
        "realpath",
        "rg",
        "route",
        "sort",
        "stat",
        "sw_vers",
        "sysctl",
        "tail",
        "head",
        "top",
        "tr",
        "tree",
        "uname",
        "uniq",
        "uptime",
        "vm_stat",
        "wc",
        "where",
        "which",
        "whoami",
    }
    _low_risk_commands = {"alias", "export", "mkdir", "touch", "unalias", "unset"}
    _high_risk_commands = {
        "chflags",
        "killall",
        "pkill",
        "rmdir",
        "shred",
        "truncate",
        "unlink",
    }
    _critical_commands = {
        "dd",
        "diskutil",
        "halt",
        "mkfs",
        "poweroff",
        "reboot",
        "shutdown",
    }
    _control_tokens = {";", "&&", "||", "|", "&", ">", ">>", "<", "<<", "<<<"}
    _dangerous_find_options = {"-delete", "-exec", "-execdir", "-ok", "-okdir"}

    def __init__(self, allowed_write_roots: tuple[Path, ...]) -> None:
        self.allowed_write_roots = tuple(
            path.expanduser().resolve() for path in allowed_write_roots
        )

    def classify(self, command: str) -> CommandDecision:
        raw = command.strip()
        if not raw:
            raise CommandPolicyError("命令不能为空")
        try:
            parsed = shlex.split(raw, posix=True)
        except ValueError as error:
            raise CommandPolicyError(f"无法解析命令：{error}") from error
        return self.classify_argv(parsed, display_command=raw)

    def classify_argv(
        self, argv: list[str] | tuple[str, ...], *, display_command: str | None = None
    ) -> CommandDecision:
        if not argv or not all(isinstance(item, str) and item for item in argv):
            raise CommandPolicyError("命令参数必须是非空字符串数组")
        command = display_command or shlex.join(argv)
        if any(item in self._control_tokens or "\n" in item or "\r" in item for item in argv):
            return self._prohibited(command, "复合 Shell 控制符必须作为完整命令单独审批")
        executable = Path(argv[0]).name.casefold()
        if executable.endswith(".exe"):
            executable = executable[:-4]
        args = list(argv[1:])
        risk, reason = self._classify_operation(executable, args)
        return CommandDecision(command, tuple(argv), risk, reason)

    def _classify_operation(self, executable: str, args: list[str]) -> tuple[CommandRisk, str]:
        if executable in self._readonly_commands:
            if executable == "find" and any(arg in self._dangerous_find_options for arg in args):
                risk = (
                    CommandRisk.HIGH
                    if "-delete" in args
                    else CommandRisk.MEDIUM
                )
                return risk, "find 包含执行或删除动作"
            if executable == "sysctl" and any("=" in arg or arg == "-w" for arg in args):
                return CommandRisk.HIGH, "修改内核参数"
            if executable == "env" and any(
                "=" in arg or not arg.startswith("-") for arg in args
            ):
                return CommandRisk.MEDIUM, "修改环境或通过 env 执行子命令"
            if executable == "ip" and any(
                arg in {"add", "delete", "del", "set", "replace", "flush"} for arg in args
            ):
                return CommandRisk.HIGH, "修改网络接口、地址或路由"
            if executable == "route" and args and args[0] not in {"get", "show", "list", "-n"}:
                return CommandRisk.HIGH, "修改系统路由"
            if (
                executable == "ifconfig"
                and len([arg for arg in args if not arg.startswith("-")]) > 1
            ):
                return CommandRisk.HIGH, "修改网络接口配置"
            return CommandRisk.READONLY, "只读观察，不改变主机状态"

        if executable == "cd":
            return CommandRisk.READONLY, "仅改变当前会话目录"
        if executable == "sed":
            return (
                (CommandRisk.MEDIUM, "原地编辑文件")
                if any(arg == "-i" or arg.startswith("-i") for arg in args)
                else (CommandRisk.READONLY, "只读文本转换")
            )
        if executable == "rm":
            recursive = any(
                arg in {"-r", "-R", "--recursive"}
                or (arg.startswith("-") and "r" in arg.casefold()[1:])
                for arg in args
            )
            return (
                (CommandRisk.CRITICAL, "递归删除文件或目录")
                if recursive
                else (CommandRisk.HIGH, "删除文件")
            )
        if executable in self._high_risk_commands:
            return CommandRisk.HIGH, "删除、截断或强制改变现有资源"
        if executable in self._critical_commands:
            return CommandRisk.CRITICAL, "可能破坏磁盘、文件系统或主机可用性"
        if executable in {"chmod", "chown"}:
            recursive = any(arg in {"-R", "--recursive"} for arg in args)
            return (
                CommandRisk.HIGH if recursive else CommandRisk.MEDIUM,
                "递归修改权限或所有权" if recursive else "修改权限或所有权",
            )
        if executable in {"kill", "taskkill"}:
            force = any(arg in {"-9", "-KILL", "/F"} for arg in args)
            return (
                CommandRisk.HIGH if force else CommandRisk.MEDIUM,
                "强制终止进程" if force else "向进程发送信号",
            )
        if executable == "systemctl":
            action = next((arg for arg in args if not arg.startswith("-")), "")
            if action in {"status", "show", "is-active", "is-enabled", "list-units"}:
                return CommandRisk.READONLY, "读取服务状态"
            if action in {"stop", "disable", "mask"}:
                return CommandRisk.HIGH, "停止或禁用系统服务"
            return CommandRisk.MEDIUM, "修改系统服务状态"
        if executable == "docker":
            action = next((arg for arg in args if not arg.startswith("-")), "")
            if action in {"ps", "images", "inspect", "logs", "stats", "version", "info"}:
                return CommandRisk.READONLY, "读取容器状态"
            if action in {"container", "image", "network", "volume"}:
                nested = next(
                    (arg for arg in args[1:] if not arg.startswith("-")), ""
                )
                if nested in {"ls", "inspect", "logs", "stats", "top"}:
                    return CommandRisk.READONLY, "读取 Docker 资源状态"
                if nested in {"rm", "prune"}:
                    return CommandRisk.HIGH, "删除 Docker 资源"
            if action == "compose":
                nested = next(
                    (arg for arg in args[1:] if not arg.startswith("-")), ""
                )
                if nested in {"ps", "logs", "config", "images", "top", "version"}:
                    return CommandRisk.READONLY, "读取 Compose 项目状态"
                if nested in {"down", "rm", "kill"}:
                    return CommandRisk.HIGH, "停止或删除 Compose 资源"
            if action in {"rm", "rmi", "prune"} or "prune" in args:
                risk = CommandRisk.CRITICAL if "prune" in args else CommandRisk.HIGH
                return risk, "删除容器、镜像或批量清理资源"
            return CommandRisk.MEDIUM, "改变容器运行或镜像状态"
        if executable in {"kubectl", "oc"}:
            action = next((arg for arg in args if not arg.startswith("-")), "")
            if action in {"get", "describe", "logs", "top", "explain", "api-resources"}:
                return CommandRisk.READONLY, "读取集群状态"
            if action == "config" and any(
                item in {"current-context", "get-contexts", "view"} for item in args
            ):
                return CommandRisk.READONLY, "读取集群客户端配置"
            if action == "delete":
                return CommandRisk.HIGH, "删除集群资源"
            return CommandRisk.MEDIUM, "修改集群资源"
        if executable == "git":
            action = next((arg for arg in args if not arg.startswith("-")), "")
            if action in {"status", "diff", "log", "show", "rev-parse", "tag"}:
                return CommandRisk.READONLY, "读取版本库状态"
            if action == "branch" and not any(
                arg in {"-d", "-D", "-m", "-M", "--delete", "--move"} for arg in args
            ):
                return CommandRisk.READONLY, "读取本地分支"
            if action == "remote" and not any(
                arg in {"add", "remove", "rename", "set-url", "prune"} for arg in args
            ):
                return CommandRisk.READONLY, "读取远端配置"
            if action == "fetch":
                return CommandRisk.LOW, "更新远端引用，不改工作区文件"
            if action in {"clean", "reset"} and any(
                arg in {"-f", "--force", "--hard"} for arg in args
            ):
                return CommandRisk.HIGH, "强制清理或重置版本库"
            if action == "push" and any("force" in arg for arg in args):
                return CommandRisk.HIGH, "强制推送远端历史"
            return CommandRisk.MEDIUM, "修改版本库或工作区状态"
        if executable in {"apt", "apt-get", "dnf", "yum", "brew", "pip", "npm"}:
            readonly_actions = {
                "check",
                "info",
                "list",
                "outdated",
                "search",
                "show",
                "view",
                "why",
            }
            if readonly_actions.intersection(args):
                return CommandRisk.READONLY, "读取软件包状态"
            destructive = {"remove", "uninstall", "purge", "autoremove"}
            return (
                (CommandRisk.HIGH, "卸载软件包或依赖")
                if destructive.intersection(args)
                else (CommandRisk.MEDIUM, "安装或更新软件包")
            )
        if executable in self._low_risk_commands:
            if executable in {"mkdir", "touch"} and not self._targets_within_roots(args):
                return CommandRisk.MEDIUM, "在常用工作区之外创建资源"
            return CommandRisk.LOW, "局部、可恢复的低风险操作"
        if executable in {"cp", "ln", "mv", "rsync", "scp", "tee"}:
            return CommandRisk.MEDIUM, "创建、覆盖或移动文件"
        if executable in {"curl", "wget", "nc", "ssh"}:
            return CommandRisk.MEDIUM, "发起网络连接或传输数据"
        if executable == "mount" and not args:
            return CommandRisk.READONLY, "读取挂载状态"
        if executable == "launchctl" and args and args[0] in {"list", "print"}:
            return CommandRisk.READONLY, "读取服务状态"
        if executable in {"mount", "umount", "launchctl"}:
            return CommandRisk.HIGH, "改变系统级资源或服务状态"
        if executable in {"sudo", "su"}:
            if "rm" in args and any("r" in arg for arg in args if arg.startswith("-")):
                return CommandRisk.CRITICAL, "提权执行递归删除"
            return CommandRisk.HIGH, "提升或切换操作系统权限"
        if executable in {"bash", "sh", "zsh", "python", "python3", "node", "perl", "ruby"}:
            return CommandRisk.MEDIUM, "执行脚本或解释器代码"
        return CommandRisk.MEDIUM, "未命中专用规则，按中风险变更进入审批"

    def _prohibited(self, command: str, reason: str) -> CommandDecision:
        return CommandDecision(command, (), CommandRisk.PROHIBITED, reason)

    def _targets_within_roots(self, args: list[str]) -> bool:
        targets = [arg for arg in args if not arg.startswith("-")]
        if not targets:
            return False
        for target in targets:
            path = Path(target).expanduser()
            if not path.is_absolute():
                continue
            resolved = path.resolve(strict=False)
            if not any(
                resolved == root or resolved.is_relative_to(root)
                for root in self.allowed_write_roots
            ):
                return False
        return True


class ControlledCommandExecutor:
    def __init__(
        self,
        policy: CommandPolicy,
        *,
        cwd: Path,
        timeout_seconds: int = 10,
        max_output_bytes: int = 64 * 1024,
    ) -> None:
        self.policy = policy
        self.cwd = cwd.resolve()
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes

    def execute(self, decision: CommandDecision) -> CommandResult:
        if decision.risk == CommandRisk.PROHIBITED or not decision.argv:
            raise CommandPolicyError(decision.reason)
        safe_path = "/usr/bin:/bin:/usr/sbin:/sbin:/opt/homebrew/bin"
        executable = shutil.which(decision.argv[0], path=safe_path)
        if executable is None:
            raise CommandExecutionError(f"命令不可用：{decision.argv[0]}")
        argv = (executable, *decision.argv[1:])
        env = {"PATH": safe_path, "LANG": "C", "LC_ALL": "C"}
        try:
            completed = subprocess.run(
                argv,
                cwd=self.cwd,
                env=env,
                capture_output=True,
                text=False,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as error:
            raise CommandExecutionError(
                f"命令执行超过 {self.timeout_seconds} 秒，已终止"
            ) from error
        payload = completed.stdout + completed.stderr
        truncated = len(payload) > self.max_output_bytes
        if truncated:
            payload = payload[: self.max_output_bytes] + b"\n...[output truncated by QuickOps]"
        return CommandResult(
            output=payload.decode("utf-8", errors="replace"),
            exit_code=completed.returncode,
            truncated=truncated,
        )


class ManualCommandExecutor:
    """Forward an operator-entered command to their native shell.

    This executor is intentionally separate from ``CommandPolicy`` and
    ``ControlledCommandExecutor``. It models the product's manual-terminal mode, where QuickOps
    is a transport for a command explicitly entered by the operator. AI tool calls must never use
    this class. A timeout and output ceiling protect the service process, but do not alter shell
    semantics such as pipes, redirection, variables, or command chaining.
    """

    def __init__(
        self,
        *,
        cwd: Path,
        timeout_seconds: int = 120,
        max_output_bytes: int = 1024 * 1024,
        system_name: str | None = None,
        shell: str | None = None,
    ) -> None:
        self.cwd = cwd.resolve()
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes
        self.system_name = (system_name or platform.system()).casefold()
        self.shell = shell or self._native_shell()

    def execute(self, command: str) -> CommandResult:
        if not command.strip():
            raise CommandExecutionError("命令不能为空")
        argv = self._shell_argv(command)
        try:
            completed = subprocess.run(
                argv,
                cwd=self.cwd,
                env=os.environ.copy(),
                capture_output=True,
                text=False,
                timeout=self.timeout_seconds,
                check=False,
                shell=False,
            )
            payload = completed.stdout + completed.stderr
            exit_code = completed.returncode
        except subprocess.TimeoutExpired as error:
            stdout = error.stdout or b""
            stderr = error.stderr or b""
            if isinstance(stdout, str):
                stdout = stdout.encode()
            if isinstance(stderr, str):
                stderr = stderr.encode()
            payload = (
                stdout + stderr + (f"\n命令执行超过 {self.timeout_seconds} 秒，已终止".encode())
            )
            exit_code = 124
        except (OSError, ValueError) as error:
            raise CommandExecutionError(f"无法启动本机终端：{type(error).__name__}") from error
        truncated = len(payload) > self.max_output_bytes
        if truncated:
            payload = payload[: self.max_output_bytes] + b"\n...[output truncated by QuickOps]"
        return CommandResult(
            output=payload.decode("utf-8", errors="replace"),
            exit_code=exit_code,
            truncated=truncated,
        )

    def _native_shell(self) -> str:
        if self.system_name == "windows":
            return os.environ.get("COMSPEC") or shutil.which("pwsh") or "cmd.exe"
        configured = os.environ.get("SHELL")
        if configured and Path(configured).is_absolute() and Path(configured).is_file():
            return configured
        for candidate in ("/bin/zsh", "/bin/bash", "/bin/sh"):
            if Path(candidate).is_file():
                return candidate
        raise CommandExecutionError("找不到可用的本机 Shell")

    def _shell_argv(self, command: str) -> tuple[str, ...]:
        if self.system_name == "windows":
            shell_name = Path(self.shell).name.casefold()
            if shell_name in {"pwsh", "pwsh.exe", "powershell", "powershell.exe"}:
                return (
                    self.shell,
                    "-NoLogo",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    command,
                )
            return self.shell, "/D", "/S", "/C", command
        return self.shell, "-lc", command


class PersistentManualTerminal:
    """One long-lived native shell used only by the operator terminal.

    The process keeps shell-native state (cwd, environment, variables and functions) between
    commands. It deliberately bypasses the AI command policy: callers must never expose this
    class as an Agent tool. stdout and stderr are merged so their relative order matches a
    terminal more closely and a reader thread keeps the implementation portable to Windows,
    where pipe file descriptors cannot be used with ``select``.
    """

    _QUEUE_EOF = object()

    def __init__(
        self,
        *,
        cwd: Path,
        timeout_seconds: int = 120,
        max_output_bytes: int = 1024 * 1024,
        system_name: str | None = None,
        shell: str | None = None,
    ) -> None:
        self.cwd = cwd.expanduser().resolve()
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes
        self.system_name = (system_name or platform.system()).casefold()
        self.shell = shell or self._native_shell()
        self._lock = threading.Lock()
        self._output: queue.Queue[bytes | object] = queue.Queue()
        self._carryover = bytearray()
        self._closed = False
        self._process = self._start_process()
        self._reader = threading.Thread(
            target=self._read_output,
            name=f"quickops-terminal-{self._process.pid}",
            daemon=True,
        )
        self._reader.start()

    @property
    def pid(self) -> int | None:
        return None if self._closed else self._process.pid

    @property
    def alive(self) -> bool:
        return not self._closed and self._process.poll() is None

    def execute(self, command: str) -> TerminalCommandResult:
        if not command.strip():
            raise CommandExecutionError("命令不能为空")
        with self._lock:
            if not self.alive:
                raise CommandExecutionError("终端会话已结束")
            token = secrets.token_hex(16)
            sentinel = f"__QUICKOPS_DONE_{token}__"
            payload = self._command_payload(command, sentinel)
            try:
                assert self._process.stdin is not None
                self._process.stdin.write(payload.encode("utf-8"))
                self._process.stdin.flush()
            except (BrokenPipeError, OSError) as error:
                self._close_unlocked()
                raise CommandExecutionError("终端会话已意外结束") from error
            return self._collect_until(sentinel)

    def close(self) -> None:
        with self._lock:
            self._close_unlocked()

    def _close_unlocked(self) -> None:
        if self._closed:
            return
        self._closed = True
        process = self._process
        if process.poll() is None:
            try:
                if process.stdin is not None:
                    process.stdin.close()
                process.terminate()
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                process.kill()
                with contextlib.suppress(OSError, subprocess.TimeoutExpired):
                    process.wait(timeout=2)

    def _start_process(self) -> subprocess.Popen[bytes]:
        if self.system_name == "windows":
            shell_name = Path(self.shell).name.casefold()
            if shell_name in {"pwsh", "pwsh.exe", "powershell", "powershell.exe"}:
                argv = (self.shell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", "-")
            else:
                argv = (self.shell, "/D", "/Q")
        else:
            argv = (self.shell, "-s")
        try:
            return subprocess.Popen(
                argv,
                cwd=self.cwd,
                env=os.environ.copy(),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                shell=False,
                bufsize=0,
            )
        except (OSError, ValueError) as error:
            raise CommandExecutionError(f"无法启动本机终端：{type(error).__name__}") from error

    def _read_output(self) -> None:
        assert self._process.stdout is not None
        try:
            while chunk := self._process.stdout.read(4096):
                self._output.put(chunk)
        finally:
            self._output.put(self._QUEUE_EOF)

    def _command_payload(self, command: str, sentinel: str) -> str:
        if self.system_name == "windows":
            shell_name = Path(self.shell).name.casefold()
            if shell_name in {"pwsh", "pwsh.exe", "powershell", "powershell.exe"}:
                return (
                    f"{command}\n$__qo_status=$LASTEXITCODE; if ($null -eq $__qo_status) "
                    f"{{$__qo_status=0}}; Write-Output \"{sentinel}:$__qo_status:$PWD\"\n"
                )
            return f"{command}\necho {sentinel}:%errorlevel%:%CD%\n"
        # The marker is a shell command, so exports, cd, functions and other shell state from the
        # operator command remain in this exact process for the next request.
        return (
            f"{command}\n__qo_status=$?\n"
            f"printf '{sentinel}:%s:%s\\n' \"$__qo_status\" \"$PWD\"\n"
        )

    def _collect_until(self, sentinel: str) -> TerminalCommandResult:
        deadline = time.monotonic() + self.timeout_seconds
        collected = bytearray()
        scanning = self._carryover
        self._carryover = bytearray()
        truncated = False
        marker = sentinel.encode()
        while True:
            marker_index = scanning.find(marker)
            if marker_index >= 0:
                truncated = (
                    self._append_bounded(collected, scanning[:marker_index]) or truncated
                )
                marker_payload = scanning[marker_index:]
                newline_index = marker_payload.find(b"\n")
                if newline_index < 0:
                    # The marker itself was found but its status/cwd suffix spans pipe chunks.
                    remaining = deadline - time.monotonic()
                    if remaining > 0:
                        try:
                            continuation = self._output.get(timeout=remaining)
                        except queue.Empty:
                            continuation = self._QUEUE_EOF
                        if isinstance(continuation, bytes):
                            scanning = marker_payload + continuation
                            continue
                    self._close_unlocked()
                    return TerminalCommandResult(
                        collected.decode("utf-8", errors="replace"),
                        124,
                        truncated,
                        str(self.cwd),
                        False,
                    )
                marker_line = marker_payload[:newline_index].decode(
                    "utf-8", errors="replace"
                )
                self._carryover.extend(marker_payload[newline_index + 1 :])
                try:
                    _prefix, status_text, current_cwd = marker_line.split(":", 2)
                    exit_code = int(status_text)
                    if current_cwd:
                        self.cwd = Path(current_cwd)
                except (ValueError, TypeError):
                    exit_code = 1
                    current_cwd = str(self.cwd)
                if truncated:
                    # This transport notice intentionally sits outside the payload byte ceiling.
                    collected.extend(b"\n...[output truncated by QuickOps]")
                return TerminalCommandResult(
                    collected.decode("utf-8", errors="replace"),
                    exit_code,
                    truncated,
                    current_cwd,
                    True,
                )

            # Retain only the short suffix that could be the start of a split marker. This keeps
            # no-newline output bounded rather than making ``readline`` allocate without limit.
            safe_length = max(0, len(scanning) - len(marker) + 1)
            if safe_length:
                truncated = (
                    self._append_bounded(collected, scanning[:safe_length]) or truncated
                )
                del scanning[:safe_length]
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                self._close_unlocked()
                suffix = f"\n命令执行超过 {self.timeout_seconds} 秒，终端会话已关闭".encode()
                truncated = self._append_bounded(collected, scanning) or truncated
                self._append_bounded(collected, suffix)
                return TerminalCommandResult(
                    collected.decode("utf-8", errors="replace"),
                    124,
                    truncated,
                    str(self.cwd),
                    False,
                )
            try:
                chunk = self._output.get(timeout=remaining)
            except queue.Empty:
                continue
            if chunk is self._QUEUE_EOF:
                self._closed = True
                truncated = self._append_bounded(collected, scanning) or truncated
                code = self._process.poll()
                return TerminalCommandResult(
                    collected.decode("utf-8", errors="replace"),
                    code if code is not None else 1,
                    truncated,
                    str(self.cwd),
                    False,
                )
            assert isinstance(chunk, bytes)
            scanning.extend(chunk)

    def _append_bounded(self, target: bytearray, chunk: bytes) -> bool:
        available = max(self.max_output_bytes - len(target), 0)
        target.extend(chunk[:available])
        return len(chunk) > available

    def _native_shell(self) -> str:
        if self.system_name == "windows":
            return shutil.which("pwsh") or os.environ.get("COMSPEC") or "cmd.exe"
        configured = os.environ.get("SHELL")
        if configured and Path(configured).is_absolute() and Path(configured).is_file():
            return configured
        for candidate in ("/bin/zsh", "/bin/bash", "/bin/sh"):
            if Path(candidate).is_file():
                return candidate
        raise CommandExecutionError("找不到可用的本机 Shell")


def default_executor(workspace: Path) -> ControlledCommandExecutor:
    workspace = workspace.resolve()
    policy = CommandPolicy((workspace,))
    return ControlledCommandExecutor(policy, cwd=workspace)


def default_manual_executor(workspace: Path) -> ManualCommandExecutor:
    return ManualCommandExecutor(cwd=workspace)
