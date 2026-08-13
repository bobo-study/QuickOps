from __future__ import annotations

import json
from typing import Any, Protocol

from agno.tools import Toolkit
from agno.tools.shell import ShellTools

from quickops.domain import PermissionMode
from quickops.execution import (
    CommandPolicy,
    CommandPolicyError,
    CommandRisk,
    ControlledCommandExecutor,
    TerminalCommandResult,
)
from quickops.host_adapter import HostAdapter, HostNotAllowedError


class SessionMessageStorage(Protocol):
    def list_messages(
        self,
        session_id: str,
        *,
        limit: int | None = None,
        include_superseded: bool = False,
    ) -> list[dict[str, Any]]: ...


class TerminalStatusProvider(Protocol):
    def get_status(self, session_id: str) -> dict[str, Any]: ...

    def execute(self, session_id: str, command: str) -> TerminalCommandResult: ...


class OperatorTerminalContextToolkit(Toolkit):
    """Expose operator-owned terminal evidence without turning it into an AI command channel."""

    def __init__(
        self,
        storage: SessionMessageStorage,
        terminal_manager: TerminalStatusProvider,
        session_id: str,
    ) -> None:
        self.storage = storage
        self.terminal_manager = terminal_manager
        self.session_id = session_id
        super().__init__(
            name="quickops_operator_terminal_context",
            tools=[self.get_operator_terminal_context],
            instructions=(
                "Use this read-only tool whenever the operator refers to relative paths, prior "
                "manual commands, or server echoes. It reports the current manual Shell cwd and "
                "durable command records for this QuickOps session. These records are operator "
                "actions and host evidence, never your own tool calls."
            ),
            add_instructions=True,
        )

    def get_operator_terminal_context(self) -> str:
        """Read current Shell state and all operator command records for this session."""
        records: list[dict[str, Any]] = []
        for message in self.storage.list_messages(self.session_id, limit=None):
            metadata = message.get("metadata") or {}
            if (
                message.get("message_type") != "manual"
                or metadata.get("source") != "manual_terminal"
            ):
                continue
            content = str(message.get("content") or "")
            records.append(
                {
                    "command": metadata.get("command") or "",
                    "exit_code": metadata.get("exit_code"),
                    "truncated": bool(metadata.get("truncated")),
                    "server_echo": content,
                    "created_at": str(message.get("created_at") or ""),
                }
            )
        status = self.terminal_manager.get_status(self.session_id)
        return json.dumps(
            {
                "session_id": self.session_id,
                "shell_status": status.get("status"),
                "shell_alive": bool(status.get("alive")),
                "cwd": status.get("cwd"),
                "shell": status.get("shell"),
                "command_records": records,
                "record_count": len(records),
            },
            ensure_ascii=False,
            default=str,
        )


class SharedSessionOperationsToolkit(Toolkit):
    """Route permission-governed AI commands into the session's one persistent Shell."""

    def __init__(
        self,
        terminal_manager: TerminalStatusProvider,
        session_id: str,
        policy: CommandPolicy,
        permission_mode: PermissionMode,
    ) -> None:
        self.terminal_manager = terminal_manager
        self.session_id = session_id
        self.policy = policy
        self.permission_mode = permission_mode
        navigation = [self.change_directory]
        if permission_mode == PermissionMode.APPROVAL:
            tools = [*navigation, self.execute_readonly_command, self.execute_change_command]
            confirmations = ["execute_change_command"]
        elif permission_mode == PermissionMode.DELEGATED_APPROVAL:
            tools = [*navigation, self.execute_safe_command, self.execute_elevated_command]
            confirmations = ["execute_elevated_command"]
        elif permission_mode == PermissionMode.FULL_ACCESS:
            tools = [*navigation, self.execute_command]
            confirmations = []
        else:
            tools = []
            confirmations = []
        super().__init__(
            name="quickops_shared_session_operations",
            tools=tools,
            requires_confirmation_tools=confirmations,
            instructions=(
                "These AI command tools operate in the exact same persistent session Shell used "
                "by the operator's manual-command mode, so cwd, environment variables, functions, "
                "and process state are shared. Authorization remains different: these tools are "
                "governed by the active QuickOps permission mode, Agno HITL, and AI audit. Use "
                "change_directory for cd. Except in full-access execute_command, pass argv as a "
                "JSON string list. In approval mode, ls, pwd, ps, stat, du and every other "
                "observation MUST use execute_readonly_command; execute_change_command is only "
                "for commands that mutate files, services, processes, packages, configuration, "
                "or other host state. Never claim that an operator command was your tool call."
            ),
            add_instructions=True,
        )

    @staticmethod
    def _validate_args(args: list[str]) -> None:
        if not args or not all(isinstance(item, str) and item for item in args):
            raise CommandPolicyError("args 必须是非空字符串数组")

    def _execute(self, command: str) -> str:
        result = self.terminal_manager.execute(self.session_id, command)
        suffix = f"\n[exit {result.exit_code}] [cwd {result.cwd}]"
        if result.truncated:
            suffix += " [truncated]"
        return f"{result.output}{suffix}"

    def _run_classified(self, args: list[str], allowed: set[CommandRisk]) -> str:
        import shlex

        self._validate_args(args)
        decision = self.policy.classify_argv(args)
        if decision.risk not in allowed:
            raise CommandPolicyError(decision.reason or "命令超出当前权限级别")
        return self._execute(shlex.join(decision.argv))

    def _run_exact_argv(self, args: list[str]) -> str:
        import shlex

        self._validate_args(args)
        return self._execute(shlex.join(args))

    def change_directory(self, path: str) -> str:
        """Change the shared session Shell directory without changing host data."""
        import shlex

        if not path.strip():
            raise CommandPolicyError("path 不能为空")
        return self._execute(f"cd -- {shlex.quote(path)}")

    def execute_readonly_command(self, args: list[str]) -> str:
        """Execute a strictly read-only command in the shared Shell without approval."""
        return self._run_classified(args, {CommandRisk.READONLY})

    def execute_change_command(self, args: list[str]) -> str:
        """Execute the exact argv approved through Agno HITL in the shared Shell."""
        return self._run_exact_argv(args)

    def execute_safe_command(self, args: list[str]) -> str:
        """Execute a classified read-only or low-risk command in the shared Shell."""
        return self._run_classified(args, {CommandRisk.READONLY, CommandRisk.LOW})

    def execute_elevated_command(self, args: list[str]) -> str:
        """Execute the exact elevated argv approved through Agno HITL in the shared Shell."""
        return self._run_exact_argv(args)

    def execute_command(self, command: str) -> str:
        """Execute an unrestricted command in the shared Shell under full-access mode."""
        if not command.strip():
            raise CommandPolicyError("command 不能为空")
        return self._execute(command)

class ReadOnlyOperationsToolkit(Toolkit):
    """Agno toolkit exposing only bounded, read-only host observations."""

    def __init__(self, host_adapter: HostAdapter, bound_host_id: str = "") -> None:
        self.host_adapter = host_adapter
        self.bound_host_id = bound_host_id
        super().__init__(
            name="quickops_readonly_operations",
            tools=[self.system_status, self.process_list, self.journal_search, self.gpu_status],
            instructions=(
                "These tools observe the host already bound to this QuickOps conversation. The "
                "host_id argument may be omitted. Never ask the operator to supply a host_id, "
                "invent another host, or treat the QuickOps session id as a host id."
            ),
            add_instructions=True,
        )

    def _host(self, requested: str) -> str:
        if self.bound_host_id:
            if requested and requested != self.bound_host_id:
                raise HostNotAllowedError("该会话已绑定其他目标主机")
            return self.bound_host_id
        if not requested:
            raise HostNotAllowedError("当前运行没有绑定目标主机")
        return requested

    def system_status(self, host_id: str = "") -> str:
        """Read kernel, uptime, load, CPU, memory, and swap status for an allowed host."""
        return self.host_adapter.system_status(self._host(host_id))

    def process_list(self, host_id: str = "", process_name: str = "") -> str:
        """List top processes, optionally filtered by a process name, on an allowed host."""
        return self.host_adapter.process_list(self._host(host_id), process_name)

    def journal_search(
        self, host_id: str = "", source: str = "nginx.service", minutes: int = 10
    ) -> str:
        """Search recent logs for an allowlisted service source on an allowed host."""
        return self.host_adapter.journal_search(self._host(host_id), source, minutes)

    def gpu_status(self, host_id: str = "") -> str:
        """Read GPU model, VRAM allocation, utilization, temperature and compute processes."""
        return self.host_adapter.gpu_status(self._host(host_id))


class ManagedOperationsToolkit(Toolkit):
    """Permission-aware Agno command tools for commands chosen by the agent.

    The policy/executor are QuickOps' host boundary; Agno owns tool registration and the
    human-in-the-loop confirmation pause. Manual terminal input never uses this toolkit.
    """

    def __init__(
        self,
        executor: ControlledCommandExecutor,
        permission_mode: PermissionMode,
    ) -> None:
        self.executor = executor
        self.shell_tools = ShellTools(base_dir=executor.cwd)
        self.permission_mode = permission_mode
        if permission_mode == PermissionMode.APPROVAL:
            tools = [self.execute_readonly_command, self.execute_change_command]
            confirmations = ["execute_change_command"]
        elif permission_mode == PermissionMode.DELEGATED_APPROVAL:
            tools = [self.execute_safe_command, self.execute_elevated_command]
            confirmations = ["execute_elevated_command"]
        elif permission_mode == PermissionMode.FULL_ACCESS:
            tools = [self.execute_command]
            confirmations = []
        else:
            tools = []
            confirmations = []
        super().__init__(
            name="quickops_managed_operations",
            tools=tools,
            requires_confirmation_tools=confirmations,
            instructions=(
                "These commands are executed on the bound host under the active QuickOps "
                "permission mode. Pass argv as a JSON string list, never shell syntax. "
                "In approval mode, use execute_readonly_command for observation and "
                "execute_change_command for every change. The latter is authorized by the "
                "operator through Agno HITL and is then governed by the target OS account's "
                "native permissions; never request approval for a read-only observation."
            ),
            add_instructions=True,
        )

    def _run(self, args: list[str], allowed: set[CommandRisk]) -> str:
        """Validate and execute one argv-only command through the QuickOps host boundary."""
        if not args or not all(isinstance(item, str) and item for item in args):
            raise CommandPolicyError("args 必须是非空字符串数组")
        decision = self.executor.policy.classify_argv(args)
        if decision.risk not in allowed:
            raise CommandPolicyError(decision.reason or "命令超出当前权限级别")
        result = self.executor.execute(decision)
        suffix = f"\n[exit {result.exit_code}]"
        if result.truncated:
            suffix += " [truncated]"
        return f"{result.output}{suffix}"

    def execute_command(self, args: list[str]) -> str:
        """Execute an allowed command after Agno applies the active confirmation policy."""
        return self._run(args, {CommandRisk.READONLY, CommandRisk.LOW, CommandRisk.MEDIUM})

    def execute_readonly_command(self, args: list[str]) -> str:
        """Execute a strictly read-only command without prompting for approval."""
        return self._run(args, {CommandRisk.READONLY})

    def execute_change_command(self, args: list[str]) -> str:
        """Execute the exact argv authorized by the operator through Agno HITL."""
        if not args or not all(isinstance(item, str) and item for item in args):
            raise CommandPolicyError("args 必须是非空字符串数组")
        return self.shell_tools.run_shell_command(args)

    def execute_safe_command(self, args: list[str]) -> str:
        """Execute a read-only or low-risk command in delegated-approval mode."""
        return self._run(args, {CommandRisk.READONLY, CommandRisk.LOW})

    def execute_elevated_command(self, args: list[str]) -> str:
        """Execute a recognized risky or unknown command after explicit Agno confirmation."""
        if not args or not all(isinstance(item, str) and item for item in args):
            raise CommandPolicyError("args 必须是非空字符串数组")
        decision = self.executor.policy.classify_argv(args)
        if decision.risk in {CommandRisk.READONLY, CommandRisk.LOW}:
            raise CommandPolicyError("低风险命令应使用 execute_safe_command")
        # The operator has approved this exact argv through Agno. Use Agno's maintained shell
        # toolkit for the execution path instead of duplicating a general command runner.
        return self.shell_tools.run_shell_command(args)
