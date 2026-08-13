from __future__ import annotations

import time
from pathlib import Path
from threading import Thread

from quickops.storage import QuickOpsStorage
from quickops.terminal_manager import ManualTerminalManager


def manager(tmp_path: Path, **kwargs: object) -> ManualTerminalManager:
    storage = QuickOpsStorage(tmp_path / "quickops.db")
    storage.create_session("session-1", host_id="local", user_id="operator")
    return ManualTerminalManager(
        cwd=tmp_path,
        storage=storage,
        shell="/bin/sh",
        system_name="linux",
        start_reaper=False,
        **kwargs,
    )


def test_terminal_preserves_cwd_environment_and_shell_state(tmp_path: Path) -> None:
    terminal_manager = manager(tmp_path)
    (tmp_path / "work").mkdir()
    try:
        initial = terminal_manager.get_status("session-1")
        changed = terminal_manager.execute(
            "session-1", "cd work && export QUICKOPS_TERMINAL=kept && qo_value=stateful"
        )
        observed = terminal_manager.execute(
            "session-1", 'printf "%s|%s|%s" "$PWD" "$QUICKOPS_TERMINAL" "$qo_value"'
        )

        assert initial["cwd"] == str(tmp_path)
        assert changed.exit_code == 0
        assert changed.cwd == str(tmp_path / "work")
        assert observed.output == f"{tmp_path / 'work'}|kept|stateful"
        assert observed.cwd == str(tmp_path / "work")
        assert observed.terminal_alive is True
        status = terminal_manager.get_status("session-1")
        assert status["alive"] is True
        assert status["cwd"] == str(tmp_path / "work")
    finally:
        terminal_manager.close_all()


def test_different_quickops_sessions_have_isolated_shell_state(tmp_path: Path) -> None:
    storage = QuickOpsStorage(tmp_path / "quickops.db")
    storage.create_session("one", host_id="local", user_id="operator")
    storage.create_session("two", host_id="local", user_id="operator")
    terminal_manager = ManualTerminalManager(
        cwd=tmp_path,
        storage=storage,
        shell="/bin/sh",
        system_name="linux",
        start_reaper=False,
    )
    try:
        terminal_manager.execute("one", "export QUICKOPS_ISOLATED=one")
        one = terminal_manager.execute("one", 'printf %s "$QUICKOPS_ISOLATED"')
        two = terminal_manager.execute("two", 'printf %s "${QUICKOPS_ISOLATED-unset}"')
        assert one.output == "one"
        assert two.output == "unset"
        assert one.terminal_alive and two.terminal_alive
    finally:
        terminal_manager.close_all()


def test_idle_terminal_is_reaped_and_can_start_fresh(tmp_path: Path) -> None:
    terminal_manager = manager(tmp_path, idle_timeout_seconds=0.03)
    try:
        first = terminal_manager.execute("session-1", "export QUICKOPS_EPHEMERAL=old")
        assert first.terminal_alive
        time.sleep(0.04)
        assert terminal_manager.reap_idle() == ["session-1"]
        assert terminal_manager.get_status("session-1")["alive"] is False

        restarted = terminal_manager.execute(
            "session-1", 'printf %s "${QUICKOPS_EPHEMERAL-unset}"'
        )
        assert restarted.output == "unset"
    finally:
        terminal_manager.close_all()


def test_idle_reaper_never_closes_a_running_command(tmp_path: Path) -> None:
    terminal_manager = manager(tmp_path, idle_timeout_seconds=0.02)
    results = []
    worker = Thread(
        target=lambda: results.append(
            terminal_manager.execute("session-1", "sleep 0.08; printf finished")
        )
    )
    try:
        worker.start()
        time.sleep(0.04)
        assert terminal_manager.get_status("session-1")["busy"] is True
        assert terminal_manager.reap_idle() == []
        worker.join(timeout=1)
        assert results[0].output == "finished"
        assert results[0].terminal_alive is True
    finally:
        terminal_manager.close_all()


def test_explicit_close_updates_storage(tmp_path: Path) -> None:
    storage = QuickOpsStorage(tmp_path / "quickops.db")
    storage.create_session("session-1", host_id="local", user_id="operator")
    terminal_manager = ManualTerminalManager(
        cwd=tmp_path,
        storage=storage,
        shell="/bin/sh",
        system_name="linux",
        start_reaper=False,
    )
    terminal_manager.execute("session-1", "pwd")

    assert storage.get_terminal_session("session-1")["status"] == "active"
    assert terminal_manager.close("session-1") is True
    assert terminal_manager.close("session-1") is False
    assert storage.get_terminal_session("session-1")["status"] == "closed"


def test_restart_replaces_shell_and_clears_ephemeral_state(tmp_path: Path) -> None:
    terminal_manager = manager(tmp_path)
    try:
        terminal_manager.execute("session-1", "export QUICKOPS_RESTART=old")
        before = terminal_manager.get_status("session-1")
        restarted = terminal_manager.restart("session-1")
        observed = terminal_manager.execute(
            "session-1", 'printf %s "${QUICKOPS_RESTART-unset}"'
        )
        assert restarted["alive"] is True
        assert restarted["pid"] != before["pid"]
        assert observed.output == "unset"
    finally:
        terminal_manager.close_all()


def test_output_limit_does_not_desynchronize_next_command(tmp_path: Path) -> None:
    terminal_manager = manager(tmp_path, max_output_bytes=4)
    try:
        # More than one reader chunk without a newline verifies bounded streaming and split-marker
        # handling rather than relying on an unbounded ``readline`` allocation.
        large = terminal_manager.execute("session-1", "printf %05000d 0")
        following = terminal_manager.execute("session-1", "printf ok")
        assert large.truncated is True
        assert large.output.startswith("0000")
        assert following.output == "ok"
        assert following.exit_code == 0
    finally:
        terminal_manager.close_all()
