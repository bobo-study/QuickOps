from pathlib import Path

import pytest
from quickops.domain import PermissionMode
from quickops.execution import CommandPolicy, CommandPolicyError, default_executor
from quickops.storage import QuickOpsStorage
from quickops.terminal_manager import ManualTerminalManager
from quickops.toolkit import (
    ManagedOperationsToolkit,
    OperatorTerminalContextToolkit,
    SharedSessionOperationsToolkit,
)


class FakeTerminalStatus:
    def __init__(self, cwd: Path) -> None:
        self.cwd = cwd

    def get_status(self, session_id: str) -> dict[str, object]:
        return {
            "session_id": session_id,
            "status": "active",
            "alive": True,
            "cwd": str(self.cwd),
            "shell": "/bin/zsh",
        }


class FakeMessageStorage:
    def list_messages(self, _session_id: str, **_kwargs: object) -> list[dict[str, object]]:
        return [
            {
                "message_type": "chat",
                "role": "user",
                "content": "不要混入普通消息",
                "metadata": {"source": "ai_composer"},
            },
            {
                "message_type": "manual",
                "role": "tool",
                "content": "$ cd dify/docker/volumes\n\n[exit 0]",
                "created_at": "2026-08-12T12:00:00",
                "metadata": {
                    "source": "manual_terminal",
                    "command": "cd dify/docker/volumes",
                    "exit_code": 0,
                    "truncated": False,
                },
            },
        ]


def toolkit(tmp_path: Path, mode: PermissionMode) -> ManagedOperationsToolkit:
    return ManagedOperationsToolkit(default_executor(tmp_path), mode)


def test_readonly_exposes_no_command_tool(tmp_path: Path) -> None:
    managed = toolkit(tmp_path, PermissionMode.READONLY)
    assert managed.functions == {}


def test_approval_delegates_confirmation_to_agno(tmp_path: Path) -> None:
    managed = toolkit(tmp_path, PermissionMode.APPROVAL)
    assert set(managed.functions) == {
        "execute_readonly_command",
        "execute_change_command",
    }
    assert managed.requires_confirmation_tools == ["execute_change_command"]
    assert "[exit 0]" in managed.execute_readonly_command(["pwd"])
    with pytest.raises(CommandPolicyError):
        managed.execute_readonly_command(["touch", str(tmp_path / "not-created")])
    changed = tmp_path / "approved-change"
    managed.execute_change_command(["touch", str(changed)])
    assert changed.exists()


def test_delegated_mode_separates_safe_and_elevated_commands(tmp_path: Path) -> None:
    managed = toolkit(tmp_path, PermissionMode.DELEGATED_APPROVAL)
    assert set(managed.functions) == {"execute_safe_command", "execute_elevated_command"}
    assert managed.requires_confirmation_tools == ["execute_elevated_command"]
    assert "[exit 0]" in managed.execute_safe_command(["pwd"])
    managed.execute_safe_command(["touch", str(tmp_path / "low-risk-created")])
    assert (tmp_path / "low-risk-created").exists()
    with pytest.raises(CommandPolicyError):
        managed.execute_safe_command(["rm", str(tmp_path / "low-risk-created")])


def test_full_access_has_no_confirmation_but_keeps_command_policy(tmp_path: Path) -> None:
    managed = toolkit(tmp_path, PermissionMode.FULL_ACCESS)
    assert managed.requires_confirmation_tools == []
    with pytest.raises(CommandPolicyError):
        managed.execute_command(["rm", "-rf", str(tmp_path)])


def test_operator_terminal_context_is_structured_session_evidence(tmp_path: Path) -> None:
    context = OperatorTerminalContextToolkit(
        FakeMessageStorage(), FakeTerminalStatus(tmp_path), "session-1"
    ).get_operator_terminal_context()

    assert f'"cwd": "{tmp_path}"' in context
    assert '"command": "cd dify/docker/volumes"' in context
    assert '"command_records"' in context
    assert "不要混入普通消息" not in context


def test_ai_and_operator_commands_share_one_persistent_shell(tmp_path: Path) -> None:
    storage = QuickOpsStorage(tmp_path / "shared-shell.db")
    storage.create_session("session-1", host_id="local", user_id="operator")
    terminal_manager = ManualTerminalManager(
        cwd=tmp_path,
        storage=storage,
        shell="/bin/sh",
        system_name="linux",
        start_reaper=False,
    )
    work = tmp_path / "work"
    work.mkdir()
    try:
        terminal_manager.execute(
            "session-1", "cd work && export QUICKOPS_SHARED_SHELL=operator"
        )
        ai_tools = SharedSessionOperationsToolkit(
            terminal_manager,
            "session-1",
            CommandPolicy((tmp_path,)),
            PermissionMode.FULL_ACCESS,
        )

        ai_result = ai_tools.execute_command('printf "%s|%s" "$PWD" "$QUICKOPS_SHARED_SHELL"')
        ai_tools.change_directory(str(tmp_path))
        operator_result = terminal_manager.execute("session-1", "pwd")

        assert f"{work}|operator" in ai_result
        assert operator_result.output.strip() == str(tmp_path)
    finally:
        terminal_manager.close_all()
