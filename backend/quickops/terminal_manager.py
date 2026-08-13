from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from quickops.execution import (
    CommandExecutionError,
    PersistentManualTerminal,
    TerminalCommandResult,
)


class TerminalStorage(Protocol):
    def save_terminal_session(self, session_id: str, **values: Any) -> dict[str, Any]: ...

    def close_terminal_session(self, session_id: str) -> bool: ...


@dataclass
class _ManagedTerminal:
    terminal: PersistentManualTerminal
    created_monotonic: float
    last_active_monotonic: float
    active_requests: int = 0


class ManualTerminalManager:
    """Own persistent operator terminals keyed by QuickOps session id.

    The registry lock only guards lifecycle changes. A terminal has its own command lock, so
    different QuickOps sessions execute concurrently while commands in one terminal stay ordered.
    Idle processes are reaped by a daemon and every lifecycle transition can be projected into the
    application database without storing a stale process as if it survived a server restart.
    """

    def __init__(
        self,
        *,
        cwd: Path,
        storage: TerminalStorage | None = None,
        idle_timeout_seconds: int = 30 * 60,
        command_timeout_seconds: int = 120,
        max_output_bytes: int = 1024 * 1024,
        system_name: str | None = None,
        shell: str | None = None,
        start_reaper: bool = True,
    ) -> None:
        if idle_timeout_seconds <= 0:
            raise ValueError("idle_timeout_seconds must be positive")
        self.cwd = cwd.expanduser().resolve()
        self.storage = storage
        self.idle_timeout_seconds = idle_timeout_seconds
        self.command_timeout_seconds = command_timeout_seconds
        self.max_output_bytes = max_output_bytes
        self.system_name = system_name
        self.shell = shell
        self._lock = threading.RLock()
        self._terminals: dict[str, _ManagedTerminal] = {}
        self._stopped = threading.Event()
        self._reaper: threading.Thread | None = None
        if start_reaper:
            self._reaper = threading.Thread(
                target=self._reap_loop, name="quickops-terminal-reaper", daemon=True
            )
            self._reaper.start()

    def execute(self, session_id: str, command: str) -> TerminalCommandResult:
        session_id = session_id.strip()
        if not session_id:
            raise CommandExecutionError("缺少终端会话 ID")
        with self._lock:
            managed = self._get_or_create(session_id)
            managed.active_requests += 1
        try:
            result = managed.terminal.execute(command)
        finally:
            with self._lock:
                managed.active_requests -= 1
                managed.last_active_monotonic = time.monotonic()
        if result.terminal_alive:
            self._save(session_id, managed, status="active", cwd=result.cwd)
        else:
            self._discard(session_id, expected=managed, status="closed")
        return result

    def get_status(self, session_id: str) -> dict[str, Any]:
        self.reap_idle()
        with self._lock:
            managed = self._terminals.get(session_id)
            if managed is None or not managed.terminal.alive:
                # A closed terminal's next shell starts here. Exposing the real configured
                # account home lets the UI show an accurate prompt before the first command.
                return {
                    "session_id": session_id,
                    "status": "closed",
                    "alive": False,
                    "cwd": str(self.cwd),
                }
            idle_seconds = max(0, int(time.monotonic() - managed.last_active_monotonic))
            return {
                "session_id": session_id,
                "status": "active",
                "alive": True,
                "cwd": str(managed.terminal.cwd),
                "shell": managed.terminal.shell,
                "pid": managed.terminal.pid,
                "busy": managed.active_requests > 0,
                "idle_seconds": idle_seconds,
                "idle_timeout_seconds": self.idle_timeout_seconds,
            }

    def open(self, session_id: str) -> dict[str, Any]:
        """Ensure a terminal exists without executing an operator command."""
        self._get_or_create(session_id)
        return self.get_status(session_id)

    def restart(self, session_id: str) -> dict[str, Any]:
        """Explicitly replace a terminal with a clean native shell."""
        self.close(session_id)
        return self.open(session_id)

    def close(self, session_id: str) -> bool:
        with self._lock:
            managed = self._terminals.pop(session_id, None)
        if managed is None:
            return False
        managed.terminal.close()
        if self.storage is not None:
            self.storage.close_terminal_session(session_id)
        return True

    def close_all(self) -> None:
        self._stopped.set()
        with self._lock:
            session_ids = tuple(self._terminals)
        for session_id in session_ids:
            self.close(session_id)

    def reap_idle(self) -> list[str]:
        now = time.monotonic()
        with self._lock:
            expired = [
                session_id
                for session_id, managed in self._terminals.items()
                if managed.active_requests == 0
                and now - managed.last_active_monotonic >= self.idle_timeout_seconds
            ]
        for session_id in expired:
            self.close(session_id)
        return expired

    def _get_or_create(self, session_id: str) -> _ManagedTerminal:
        self.reap_idle()
        with self._lock:
            managed = self._terminals.get(session_id)
            if managed is not None and managed.terminal.alive:
                return managed
            terminal = PersistentManualTerminal(
                cwd=self.cwd,
                timeout_seconds=self.command_timeout_seconds,
                max_output_bytes=self.max_output_bytes,
                system_name=self.system_name,
                shell=self.shell,
            )
            now = time.monotonic()
            managed = _ManagedTerminal(terminal, now, now)
            self._terminals[session_id] = managed
            self._save(session_id, managed, status="active", cwd=str(terminal.cwd))
            return managed

    def _discard(
        self, session_id: str, *, expected: _ManagedTerminal, status: str
    ) -> None:
        with self._lock:
            if self._terminals.get(session_id) is expected:
                self._terminals.pop(session_id, None)
        if self.storage is not None:
            self.storage.save_terminal_session(
                session_id,
                platform=expected.terminal.system_name,
                shell=expected.terminal.shell,
                cwd=str(expected.terminal.cwd),
                status=status,
            )

    def _save(
        self, session_id: str, managed: _ManagedTerminal, *, status: str, cwd: str
    ) -> None:
        if self.storage is not None:
            self.storage.save_terminal_session(
                session_id,
                platform=managed.terminal.system_name,
                shell=managed.terminal.shell,
                cwd=cwd,
                status=status,
            )

    def _reap_loop(self) -> None:
        interval = max(1.0, min(30.0, self.idle_timeout_seconds / 2))
        while not self._stopped.wait(interval):
            self.reap_idle()


def default_terminal_manager(
    workspace: Path, *, storage: TerminalStorage | None = None
) -> ManualTerminalManager:
    return ManualTerminalManager(cwd=workspace, storage=storage)
