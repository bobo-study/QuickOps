from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from dataclasses import dataclass


@dataclass(frozen=True)
class AuthSession:
    username: str
    expires_at: float


class LoginRateLimitedError(RuntimeError):
    pass


class AuthManager:
    """Process-local login sessions backed by HttpOnly cookies.

    Restarting QuickOps intentionally invalidates every token. Credentials are never persisted in
    the application database and comparisons use constant-time digests.
    """

    cookie_name = "quickops_session"

    def __init__(
        self,
        *,
        username: str | None,
        password: str | None,
        ttl_seconds: int,
        max_failures: int = 5,
        lockout_seconds: int = 60,
    ) -> None:
        self.username = username.strip() if username else None
        self._password_digest = self._digest(password) if password else None
        self.ttl_seconds = ttl_seconds
        self.max_failures = max_failures
        self.lockout_seconds = lockout_seconds
        self._sessions: dict[str, AuthSession] = {}
        self._failures: dict[str, tuple[int, float]] = {}
        self._lock = threading.RLock()

    @property
    def configured(self) -> bool:
        return bool(self.username and self._password_digest)

    def login(self, username: str, password: str, client_key: str) -> str | None:
        now = time.time()
        with self._lock:
            failures, blocked_until = self._failures.get(client_key, (0, 0.0))
            if blocked_until > now:
                raise LoginRateLimitedError("登录尝试过于频繁，请稍后再试")

        username_ok = bool(self.username) and hmac.compare_digest(username, self.username or "")
        password_ok = bool(self._password_digest) and hmac.compare_digest(
            self._digest(password), self._password_digest or ""
        )
        if not (username_ok and password_ok):
            with self._lock:
                failures += 1
                blocked_until = now + self.lockout_seconds if failures >= self.max_failures else 0
                self._failures[client_key] = (failures, blocked_until)
            return None

        token = secrets.token_urlsafe(48)
        with self._lock:
            self._failures.pop(client_key, None)
            self._sessions[token] = AuthSession(self.username or username, now + self.ttl_seconds)
            self._reap(now)
        return token

    def authenticate(self, token: str | None) -> AuthSession | None:
        if not token:
            return None
        now = time.time()
        with self._lock:
            session = self._sessions.get(token)
            if session is None:
                return None
            if session.expires_at <= now:
                self._sessions.pop(token, None)
                return None
            return session

    def logout(self, token: str | None) -> None:
        if not token:
            return
        with self._lock:
            self._sessions.pop(token, None)

    def close(self) -> None:
        with self._lock:
            self._sessions.clear()
            self._failures.clear()

    def _reap(self, now: float) -> None:
        expired = [token for token, session in self._sessions.items() if session.expires_at <= now]
        for token in expired:
            self._sessions.pop(token, None)

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()
