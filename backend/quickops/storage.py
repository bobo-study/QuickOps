from __future__ import annotations

import hashlib
import re
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column


def _now() -> datetime:
    return datetime.now(UTC)


def _id() -> str:
    return uuid.uuid4().hex


class Base(DeclarativeBase):
    pass


class SessionRow(Base):
    __tablename__ = "quickops_sessions"

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    host_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    user_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    permission_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="approval")
    model_config_id: Mapped[str | None] = mapped_column(
        ForeignKey("quickops_model_configs.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_activity_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (
        CheckConstraint(
            "permission_mode IN ('readonly','approval','delegated_approval','full_access')",
            name="ck_quickops_sessions_permission_mode",
        ),
        Index("ix_quickops_sessions_user_activity", "user_id", "last_activity_at"),
    )


class MessageRow(Base):
    __tablename__ = "quickops_messages"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("quickops_sessions.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    message_type: Mapped[str] = mapped_column(String(20), nullable=False, default="chat")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (
        CheckConstraint(
            "role IN ('user','assistant','system','tool')", name="ck_quickops_messages_role"
        ),
        CheckConstraint(
            "message_type IN ('chat','manual','tool','system')",
            name="ck_quickops_messages_type",
        ),
        Index("ix_quickops_messages_session_created", "session_id", "created_at"),
    )


class ModelConfigRow(Base):
    __tablename__ = "quickops_model_configs"

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    provider: Mapped[str] = mapped_column(String(100), nullable=False)
    model_id: Mapped[str] = mapped_column(String(300), nullable=False)
    base_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    thinking_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="auto")
    max_context_k: Mapped[int] = mapped_column(Integer, nullable=False, default=128)
    supports_vision: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (
        Index("ix_quickops_models_provider_enabled", "provider", "enabled"),
        Index("ix_quickops_models_default", "is_default"),
    )


class AppSettingRow(Base):
    __tablename__ = "quickops_app_settings"

    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    value_json: Mapped[Any] = mapped_column(JSON, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class CommandApprovalRow(Base):
    __tablename__ = "quickops_command_approvals"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("quickops_sessions.id", ondelete="CASCADE"), nullable=False
    )
    host_id: Mapped[str] = mapped_column(String(200), nullable=False)
    command: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    requested_by: Mapped[str] = mapped_column(String(200), nullable=False)
    decided_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','approved','rejected','expired','executed')",
            name="ck_quickops_approvals_status",
        ),
        Index("ix_quickops_approvals_session_status", "session_id", "status"),
        Index("ix_quickops_approvals_status_expiry", "status", "expires_at"),
    )


class AuditEventRow(Base):
    __tablename__ = "quickops_audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    actor: Mapped[str] = mapped_column(String(200), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(500), nullable=False)
    target: Mapped[str | None] = mapped_column(String(500), nullable=True)
    outcome: Mapped[str] = mapped_column(String(30), nullable=False)
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (
        Index("ix_quickops_audit_session_created", "session_id", "created_at"),
        Index("ix_quickops_audit_type_created", "event_type", "created_at"),
    )


class AgentRunRow(Base):
    __tablename__ = "quickops_agent_runs"

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("quickops_sessions.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="queued")
    input_text: Mapped[str] = mapped_column(Text, nullable=False)
    output_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','running','paused','completed','failed','cancelled')",
            name="ck_quickops_agent_runs_status",
        ),
        Index("ix_quickops_runs_session_created", "session_id", "created_at"),
        Index("ix_quickops_runs_session_status", "session_id", "status"),
    )


class AgentRunEventRow(Base):
    __tablename__ = "quickops_agent_run_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("quickops_agent_runs.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (
        UniqueConstraint("run_id", "sequence", name="uq_quickops_run_event_sequence"),
        Index("ix_quickops_run_events_run_sequence", "run_id", "sequence"),
    )


class SessionBranchRow(Base):
    __tablename__ = "quickops_session_branches"

    child_session_id: Mapped[str] = mapped_column(
        ForeignKey("quickops_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    parent_session_id: Mapped[str] = mapped_column(
        ForeignKey("quickops_sessions.id", ondelete="CASCADE"), nullable=False
    )
    through_message_id: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (Index("ix_quickops_branches_parent", "parent_session_id"),)


class TerminalSessionRow(Base):
    __tablename__ = "quickops_terminal_sessions"

    session_id: Mapped[str] = mapped_column(
        ForeignKey("quickops_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    platform: Mapped[str] = mapped_column(String(40), nullable=False)
    shell: Mapped[str] = mapped_column(String(1000), nullable=False)
    cwd: Mapped[str] = mapped_column(String(2000), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    last_active_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status IN ('active','closed')", name="ck_quickops_terminal_sessions_status"
        ),
        Index("ix_quickops_terminal_status_activity", "status", "last_active_at"),
    )


class AssetServiceRow(Base):
    __tablename__ = "quickops_asset_services"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    host_id: Mapped[str] = mapped_column(String(200), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    probe_type: Mapped[str] = mapped_column(String(24), nullable=False, default="process")
    probe_target: Mapped[str] = mapped_column(String(1000), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    interval_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    guard_mode: Mapped[str] = mapped_column(String(24), nullable=False, default="diagnose")
    guard_policy: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="unknown")
    status_detail: Mapped[str] = mapped_column(Text, nullable=False, default="等待首次探测")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (
        CheckConstraint(
            "probe_type IN ('process','system_service','http','tcp')",
            name="ck_quickops_asset_services_probe_type",
        ),
        CheckConstraint(
            "status IN ('unknown','healthy','degraded','down')",
            name="ck_quickops_asset_services_status",
        ),
        Index("ix_quickops_asset_services_host_name", "host_id", "name"),
        Index("ix_quickops_asset_services_due", "enabled", "last_checked_at"),
    )


class AssetEventRow(Base):
    __tablename__ = "quickops_asset_events"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    service_id: Mapped[str] = mapped_column(
        ForeignKey("quickops_asset_services.id", ondelete="CASCADE"), nullable=False
    )
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    category: Mapped[str] = mapped_column(String(40), nullable=False, default="maintenance")
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="operator")
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (
        CheckConstraint(
            "severity IN ('info','warning','critical')",
            name="ck_quickops_asset_events_severity",
        ),
        CheckConstraint(
            "source IN ('system','agent','operator')",
            name="ck_quickops_asset_events_source",
        ),
        Index("ix_quickops_asset_events_service_created", "service_id", "created_at"),
    )


class AssetDocumentRow(Base):
    __tablename__ = "quickops_asset_documents"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    service_id: Mapped[str] = mapped_column(
        ForeignKey("quickops_asset_services.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(200), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    path: Mapped[str] = mapped_column(String(2000), nullable=False)
    extracted_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_session_id: Mapped[str | None] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (
        Index("ix_quickops_asset_documents_service_created", "service_id", "created_at"),
    )


class SessionAssetMountRow(Base):
    __tablename__ = "quickops_session_asset_mounts"

    session_id: Mapped[str] = mapped_column(
        ForeignKey("quickops_sessions.id", ondelete="CASCADE"), primary_key=True
    )
    service_id: Mapped[str] = mapped_column(
        ForeignKey("quickops_asset_services.id", ondelete="CASCADE"), nullable=False
    )
    mounted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)

    __table_args__ = (Index("ix_quickops_session_asset_service", "service_id"),)


class StorageError(ValueError):
    """Raised when a storage request violates a QuickOps invariant."""


class QuickOpsStorage:
    """Application persistence alongside Agno's own runtime/session database.

    SQLAlchemy binds every value as a parameter. Model secrets are omitted from all public
    projections; callers must use ``get_model_credentials`` at the server-only model boundary.
    """

    def __init__(self, db_file: str | Path):
        path = Path(db_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(f"sqlite:///{path}", future=True)
        event.listen(self.engine, "connect", self._configure_sqlite)
        Base.metadata.create_all(self.engine)
        self._migrate_agent_run_status_constraint()
        # ``create_all`` intentionally does not mutate existing tables. Keep local prototype
        # databases forward-compatible without discarding configured credentials.
        with self.engine.begin() as connection:
            columns = {
                row[1]
                for row in connection.exec_driver_sql(
                    "PRAGMA table_info(quickops_model_configs)"
                ).fetchall()
            }
            if "thinking_mode" not in columns:
                connection.exec_driver_sql(
                    "ALTER TABLE quickops_model_configs "
                    "ADD COLUMN thinking_mode VARCHAR(16) NOT NULL DEFAULT 'auto'"
                )
            if "max_context_k" not in columns:
                connection.exec_driver_sql(
                    "ALTER TABLE quickops_model_configs "
                    "ADD COLUMN max_context_k INTEGER NOT NULL DEFAULT 128"
                )
            if "supports_vision" not in columns:
                connection.exec_driver_sql(
                    "ALTER TABLE quickops_model_configs "
                    "ADD COLUMN supports_vision BOOLEAN NOT NULL DEFAULT 0"
                )
            asset_columns = {
                row[1]
                for row in connection.exec_driver_sql(
                    "PRAGMA table_info(quickops_asset_services)"
                ).fetchall()
            }
            if "guard_mode" not in asset_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE quickops_asset_services "
                    "ADD COLUMN guard_mode VARCHAR(24) NOT NULL DEFAULT 'diagnose'"
                )
            if "guard_policy" not in asset_columns:
                connection.exec_driver_sql(
                    "ALTER TABLE quickops_asset_services "
                    "ADD COLUMN guard_policy TEXT NOT NULL DEFAULT ''"
                )
        # Provider credentials may live in this database; keep the file owner-only by default.
        path.chmod(0o600)

    def _migrate_agent_run_status_constraint(self) -> None:
        """Add ``paused`` to an existing SQLite CHECK constraint without losing runs/events.

        SQLite cannot alter a CHECK constraint in place. Early QuickOps databases allowed only
        queued/running/completed/failed/cancelled, so Agno's RunPaused event failed exactly when
        an HITL approval was required. Rebuild only this table, keeping its primary/foreign keys
        and indexes stable. The migration is idempotent and runs before the store is served.
        """
        with self.engine.connect() as connection:
            table_sql = connection.exec_driver_sql(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='quickops_agent_runs'"
            ).scalar_one_or_none()
        if not table_sql or "'paused'" in table_sql:
            return

        # PRAGMA foreign_keys cannot be changed inside a transaction, hence the short-lived raw
        # connection. Event rows keep referencing the same final table name throughout.
        raw = self.engine.raw_connection()
        try:
            cursor = raw.cursor()
            cursor.execute("PRAGMA foreign_keys=OFF")
            cursor.execute("BEGIN IMMEDIATE")
            cursor.execute("DROP TABLE IF EXISTS quickops_agent_runs_migrating")
            cursor.execute(
                """
                CREATE TABLE quickops_agent_runs_migrating (
                    id VARCHAR(200) NOT NULL PRIMARY KEY,
                    session_id VARCHAR(200) NOT NULL,
                    user_id VARCHAR(200) NOT NULL,
                    status VARCHAR(24) NOT NULL,
                    input_text TEXT NOT NULL,
                    output_text TEXT NOT NULL,
                    error TEXT,
                    created_at DATETIME NOT NULL,
                    started_at DATETIME,
                    completed_at DATETIME,
                    CONSTRAINT ck_quickops_agent_runs_status CHECK
                      (status IN ('queued','running','paused','completed','failed','cancelled')),
                    FOREIGN KEY(session_id) REFERENCES quickops_sessions (id) ON DELETE CASCADE
                )
                """
            )
            cursor.execute(
                """
                INSERT INTO quickops_agent_runs_migrating
                  (id, session_id, user_id, status, input_text, output_text, error,
                   created_at, started_at, completed_at)
                SELECT id, session_id, user_id, status, input_text, output_text, error,
                       created_at, started_at, completed_at
                FROM quickops_agent_runs
                """
            )
            cursor.execute("DROP TABLE quickops_agent_runs")
            cursor.execute(
                "ALTER TABLE quickops_agent_runs_migrating RENAME TO quickops_agent_runs"
            )
            cursor.execute(
                "CREATE INDEX ix_quickops_runs_session_created "
                "ON quickops_agent_runs (session_id, created_at)"
            )
            cursor.execute(
                "CREATE INDEX ix_quickops_runs_session_status "
                "ON quickops_agent_runs (session_id, status)"
            )
            raw.commit()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()
        except Exception:
            raw.rollback()
            raise
        finally:
            raw.close()

    @staticmethod
    def _configure_sqlite(dbapi_connection: Any, _connection_record: Any) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

    @staticmethod
    def _required(value: str, field: str, maximum: int) -> str:
        value = value.strip()
        if not value or len(value) > maximum:
            raise StorageError(f"{field} must contain 1-{maximum} characters")
        return value

    @staticmethod
    def _session_dict(row: SessionRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "title": row.title,
            "host_id": row.host_id,
            "user_id": row.user_id,
            "permission_mode": row.permission_mode,
            "model_config_id": row.model_config_id,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
            "last_activity_at": row.last_activity_at,
        }

    @staticmethod
    def _message_dict(row: MessageRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "session_id": row.session_id,
            "role": row.role,
            "message_type": row.message_type,
            "content": row.content,
            "metadata": row.metadata_json,
            "created_at": row.created_at,
        }

    @staticmethod
    def _model_dict(row: ModelConfigRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "name": row.name,
            "provider": row.provider,
            "model_id": row.model_id,
            "base_url": row.base_url,
            "has_api_key": bool(row.api_key),
            "thinking_mode": row.thinking_mode,
            "max_context_k": row.max_context_k,
            "supports_vision": row.supports_vision,
            "is_default": row.is_default,
            "enabled": row.enabled,
            "can_delete": False,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }

    @staticmethod
    def _approval_dict(row: CommandApprovalRow) -> dict[str, Any]:
        return {column.name: getattr(row, column.name) for column in row.__table__.columns}

    @staticmethod
    def _audit_dict(row: AuditEventRow) -> dict[str, Any]:
        result = {column.name: getattr(row, column.name) for column in row.__table__.columns}
        result["details"] = result.pop("details_json")
        return result

    @staticmethod
    def _run_dict(row: AgentRunRow) -> dict[str, Any]:
        return {column.name: getattr(row, column.name) for column in row.__table__.columns}

    @staticmethod
    def _run_event_dict(row: AgentRunEventRow) -> dict[str, Any]:
        return {
            "id": row.id,
            "run_id": row.run_id,
            "sequence": row.sequence,
            "event_type": row.event_type,
            "payload": row.payload_json,
            "created_at": row.created_at,
        }

    @staticmethod
    def _terminal_dict(row: TerminalSessionRow) -> dict[str, Any]:
        return {column.name: getattr(row, column.name) for column in row.__table__.columns}

    @staticmethod
    def _asset_service_dict(row: AssetServiceRow) -> dict[str, Any]:
        return {column.name: getattr(row, column.name) for column in row.__table__.columns}

    @staticmethod
    def _asset_event_dict(row: AssetEventRow) -> dict[str, Any]:
        result = {column.name: getattr(row, column.name) for column in row.__table__.columns}
        result["metadata"] = result.pop("metadata_json")
        return result

    @staticmethod
    def _asset_document_dict(row: AssetDocumentRow, *, public: bool = True) -> dict[str, Any]:
        result = {column.name: getattr(row, column.name) for column in row.__table__.columns}
        if public:
            result.pop("path", None)
            result.pop("extracted_text", None)
        return result

    def create_session(
        self,
        session_id: str,
        *,
        title: str = "新会话",
        host_id: str,
        user_id: str = "operator",
        permission_mode: str = "approval",
        model_config_id: str | None = None,
    ) -> dict[str, Any]:
        row = SessionRow(
            id=self._required(session_id, "session_id", 200),
            title=self._required(title, "title", 200),
            host_id=self._required(host_id, "host_id", 200),
            user_id=self._required(user_id, "user_id", 200),
            permission_mode=permission_mode,
            model_config_id=model_config_id,
        )
        with Session(self.engine) as db:
            db.add(row)
            db.commit()
            db.refresh(row)
            return self._session_dict(row)

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        with Session(self.engine) as db:
            row = db.get(SessionRow, session_id)
            return self._session_dict(row) if row else None

    def list_sessions(self, *, user_id: str, limit: int = 50) -> list[dict[str, Any]]:
        limit = min(max(limit, 1), 200)
        with Session(self.engine) as db:
            rows = db.scalars(
                select(SessionRow)
                .where(SessionRow.user_id == user_id)
                .order_by(SessionRow.last_activity_at.desc())
                .limit(limit)
            ).all()
            return [self._session_dict(row) for row in rows]

    def update_session(self, session_id: str, **changes: Any) -> dict[str, Any] | None:
        allowed = {"title", "host_id", "permission_mode", "model_config_id"}
        unknown = changes.keys() - allowed
        if unknown:
            raise StorageError(f"Unsupported session fields: {', '.join(sorted(unknown))}")
        with Session(self.engine) as db:
            row = db.get(SessionRow, session_id)
            if not row:
                return None
            for key, value in changes.items():
                if key in {"title", "host_id"}:
                    value = self._required(value, key, 200)
                setattr(row, key, value)
            row.updated_at = row.last_activity_at = _now()
            db.commit()
            db.refresh(row)
            return self._session_dict(row)

    def delete_session(self, session_id: str) -> bool:
        with Session(self.engine) as db:
            row = db.get(SessionRow, session_id)
            if not row:
                return False
            db.delete(row)
            db.commit()
            return True

    def save_terminal_session(
        self,
        session_id: str,
        *,
        platform: str,
        shell: str,
        cwd: str,
        status: str = "active",
    ) -> dict[str, Any]:
        """Persist terminal lifecycle metadata, never the process or its environment."""
        if status not in {"active", "closed"}:
            raise StorageError("Unsupported terminal status")
        values = {
            "platform": self._required(platform, "platform", 40),
            "shell": self._required(shell, "shell", 1000),
            "cwd": self._required(cwd, "cwd", 2000),
        }
        with Session(self.engine) as db:
            if db.get(SessionRow, session_id) is None:
                raise StorageError("Session does not exist")
            row = db.get(TerminalSessionRow, session_id)
            if row is None:
                row = TerminalSessionRow(session_id=session_id, **values)
                db.add(row)
            else:
                for key, value in values.items():
                    setattr(row, key, value)
            now = _now()
            row.status = status
            row.last_active_at = now
            row.closed_at = now if status == "closed" else None
            db.commit()
            db.refresh(row)
            return self._terminal_dict(row)

    def get_terminal_session(self, session_id: str) -> dict[str, Any] | None:
        with Session(self.engine) as db:
            row = db.get(TerminalSessionRow, session_id)
            return self._terminal_dict(row) if row else None

    def close_terminal_session(self, session_id: str) -> bool:
        with Session(self.engine) as db:
            row = db.get(TerminalSessionRow, session_id)
            if row is None:
                return False
            now = _now()
            row.status = "closed"
            row.last_active_at = now
            row.closed_at = now
            db.commit()
            return True

    def create_asset_service(
        self,
        *,
        host_id: str,
        name: str,
        probe_type: str,
        probe_target: str,
        description: str = "",
        interval_seconds: int = 60,
        enabled: bool = True,
        guard_mode: str = "diagnose",
        guard_policy: str = "",
    ) -> dict[str, Any]:
        if probe_type not in {"process", "system_service", "http", "tcp"}:
            raise StorageError("Unsupported asset probe type")
        interval_seconds = min(max(int(interval_seconds), 15), 86_400)
        if guard_mode not in {"diagnose", "safe_repair"}:
            raise StorageError("Unsupported asset guard mode")
        row = AssetServiceRow(
            host_id=self._required(host_id, "host_id", 200),
            name=self._required(name, "name", 200),
            description=description.strip()[:20_000],
            probe_type=probe_type,
            probe_target=self._required(probe_target, "probe_target", 1000),
            interval_seconds=interval_seconds,
            enabled=bool(enabled),
            guard_mode=guard_mode,
            guard_policy=guard_policy.strip()[:20_000],
        )
        with Session(self.engine) as db:
            db.add(row)
            db.commit()
            db.refresh(row)
            return self._asset_service_dict(row)

    def get_asset_service(self, service_id: str) -> dict[str, Any] | None:
        with Session(self.engine) as db:
            row = db.get(AssetServiceRow, service_id)
            return self._asset_service_dict(row) if row else None

    def list_asset_services(self, host_id: str | None = None) -> list[dict[str, Any]]:
        query = select(AssetServiceRow)
        if host_id:
            query = query.where(AssetServiceRow.host_id == host_id)
        query = query.order_by(AssetServiceRow.name.asc())
        with Session(self.engine) as db:
            return [self._asset_service_dict(row) for row in db.scalars(query).all()]

    def update_asset_service(self, service_id: str, **changes: Any) -> dict[str, Any] | None:
        allowed = {
            "name",
            "description",
            "probe_type",
            "probe_target",
            "interval_seconds",
            "enabled",
            "guard_mode",
            "guard_policy",
            "status",
            "status_detail",
            "last_checked_at",
        }
        unknown = changes.keys() - allowed
        if unknown:
            raise StorageError(f"Unsupported asset fields: {', '.join(sorted(unknown))}")
        with Session(self.engine) as db:
            row = db.get(AssetServiceRow, service_id)
            if row is None:
                return None
            for key, value in changes.items():
                if key == "name":
                    value = self._required(str(value), key, 200)
                elif key == "probe_target":
                    value = self._required(str(value), key, 1000)
                elif key == "probe_type" and value not in {
                    "process",
                    "system_service",
                    "http",
                    "tcp",
                }:
                    raise StorageError("Unsupported asset probe type")
                elif key == "status" and value not in {"unknown", "healthy", "degraded", "down"}:
                    raise StorageError("Unsupported asset status")
                elif key == "guard_mode" and value not in {"diagnose", "safe_repair"}:
                    raise StorageError("Unsupported asset guard mode")
                elif key == "interval_seconds":
                    value = min(max(int(value), 15), 86_400)
                elif key in {"description", "status_detail", "guard_policy"}:
                    value = str(value).strip()[:50_000]
                setattr(row, key, value)
            row.updated_at = _now()
            db.commit()
            db.refresh(row)
            return self._asset_service_dict(row)

    def delete_asset_service(self, service_id: str) -> bool:
        with Session(self.engine) as db:
            row = db.get(AssetServiceRow, service_id)
            if row is None:
                return False
            db.delete(row)
            db.commit()
            return True

    def mount_session_asset(self, session_id: str, service_id: str | None) -> dict[str, Any] | None:
        with Session(self.engine) as db:
            if db.get(SessionRow, session_id) is None:
                raise StorageError("Session does not exist")
            row = db.get(SessionAssetMountRow, session_id)
            if service_id is None:
                if row:
                    db.delete(row)
                    db.commit()
                return None
            if db.get(AssetServiceRow, service_id) is None:
                raise StorageError("Asset service does not exist")
            if row is None:
                row = SessionAssetMountRow(session_id=session_id, service_id=service_id)
                db.add(row)
            else:
                row.service_id = service_id
                row.mounted_at = _now()
            db.commit()
            service = db.get(AssetServiceRow, service_id)
            return self._asset_service_dict(service)

    def get_session_asset(self, session_id: str) -> dict[str, Any] | None:
        with Session(self.engine) as db:
            mount = db.get(SessionAssetMountRow, session_id)
            if mount is None:
                return None
            service = db.get(AssetServiceRow, mount.service_id)
            return self._asset_service_dict(service) if service else None

    def create_asset_event(
        self,
        service_id: str,
        *,
        title: str,
        content: str,
        severity: str = "info",
        category: str = "maintenance",
        source: str = "operator",
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if severity not in {"info", "warning", "critical"}:
            raise StorageError("Unsupported event severity")
        if source not in {"system", "agent", "operator"}:
            raise StorageError("Unsupported event source")
        row = AssetEventRow(
            service_id=service_id,
            title=self._required(title, "title", 300),
            content=self._required(content, "content", 200_000),
            severity=severity,
            category=self._required(category, "category", 40),
            source=source,
            metadata_json=dict(metadata or {}),
        )
        with Session(self.engine) as db:
            if db.get(AssetServiceRow, service_id) is None:
                raise StorageError("Asset service does not exist")
            db.add(row)
            db.commit()
            db.refresh(row)
            return self._asset_event_dict(row)

    def list_asset_events(self, service_id: str, *, limit: int = 200) -> list[dict[str, Any]]:
        query = (
            select(AssetEventRow)
            .where(AssetEventRow.service_id == service_id)
            .order_by(AssetEventRow.created_at.desc())
            .limit(min(max(limit, 1), 1000))
        )
        with Session(self.engine) as db:
            return [self._asset_event_dict(row) for row in db.scalars(query).all()]

    def get_asset_event(self, event_id: str) -> dict[str, Any] | None:
        with Session(self.engine) as db:
            row = db.get(AssetEventRow, event_id)
            return self._asset_event_dict(row) if row else None

    def update_asset_event(self, event_id: str, **changes: Any) -> dict[str, Any] | None:
        allowed = {"title", "content", "severity", "category"}
        if changes.keys() - allowed:
            raise StorageError("Unsupported event fields")
        with Session(self.engine) as db:
            row = db.get(AssetEventRow, event_id)
            if row is None:
                return None
            for key, value in changes.items():
                if key == "severity" and value not in {"info", "warning", "critical"}:
                    raise StorageError("Unsupported event severity")
                maximum = 300 if key == "title" else 200_000 if key == "content" else 40
                setattr(row, key, self._required(str(value), key, maximum))
            row.updated_at = _now()
            db.commit()
            db.refresh(row)
            return self._asset_event_dict(row)

    def delete_asset_event(self, event_id: str) -> bool:
        with Session(self.engine) as db:
            row = db.get(AssetEventRow, event_id)
            if row is None:
                return False
            db.delete(row)
            db.commit()
            return True

    def create_asset_document(
        self,
        service_id: str,
        *,
        name: str,
        mime_type: str,
        size: int,
        path: str,
        extracted_text: str = "",
        description: str = "",
        source_session_id: str | None = None,
    ) -> dict[str, Any]:
        row = AssetDocumentRow(
            service_id=service_id,
            name=self._required(name, "name", 255),
            mime_type=self._required(mime_type, "mime_type", 200),
            size=max(0, int(size)),
            path=self._required(path, "path", 2000),
            extracted_text=extracted_text[:2_000_000],
            description=description.strip()[:20_000],
            source_session_id=source_session_id,
        )
        with Session(self.engine) as db:
            if db.get(AssetServiceRow, service_id) is None:
                raise StorageError("Asset service does not exist")
            db.add(row)
            db.commit()
            db.refresh(row)
            return self._asset_document_dict(row)

    def get_asset_document(self, document_id: str, *, public: bool = True) -> dict[str, Any] | None:
        with Session(self.engine) as db:
            row = db.get(AssetDocumentRow, document_id)
            return self._asset_document_dict(row, public=public) if row else None

    def list_asset_documents(self, service_id: str) -> list[dict[str, Any]]:
        query = (
            select(AssetDocumentRow)
            .where(AssetDocumentRow.service_id == service_id)
            .order_by(AssetDocumentRow.created_at.desc())
        )
        with Session(self.engine) as db:
            return [self._asset_document_dict(row) for row in db.scalars(query).all()]

    def update_asset_document(self, document_id: str, **changes: Any) -> dict[str, Any] | None:
        allowed = {"name", "description", "extracted_text"}
        if changes.keys() - allowed:
            raise StorageError("Unsupported document fields")
        with Session(self.engine) as db:
            row = db.get(AssetDocumentRow, document_id)
            if row is None:
                return None
            for key, value in changes.items():
                maximum = 255 if key == "name" else 2_000_000
                setattr(row, key, self._required(str(value), key, maximum))
            row.updated_at = _now()
            db.commit()
            db.refresh(row)
            return self._asset_document_dict(row)

    def delete_asset_document(self, document_id: str) -> dict[str, Any] | None:
        with Session(self.engine) as db:
            row = db.get(AssetDocumentRow, document_id)
            if row is None:
                return None
            result = self._asset_document_dict(row, public=False)
            db.delete(row)
            db.commit()
            return result

    def search_asset_knowledge(
        self, service_id: str, query: str, *, limit: int = 8
    ) -> list[dict[str, Any]]:
        """Per-asset lexical retrieval with deterministic scoring and no embedding model."""
        normalized = query.casefold()
        latin_terms = re.findall(r"[a-z0-9_./:@-]+", normalized)
        cjk_terms: list[str] = []
        for span in re.findall(r"[\u3400-\u9fff]+", normalized):
            cjk_terms.append(span)
            if len(span) > 2:
                cjk_terms.extend(span[index : index + 2] for index in range(len(span) - 1))
        terms = list(dict.fromkeys([*latin_terms, *cjk_terms]))[:40]
        if not terms:
            return []
        candidates: list[dict[str, Any]] = []
        with Session(self.engine) as db:
            events = db.scalars(
                select(AssetEventRow).where(AssetEventRow.service_id == service_id)
            ).all()
            for row in events:
                event_item = self._asset_event_dict(row)
                title = row.title.casefold()
                content = row.content.casefold()
                score = sum(3 * title.count(term) + content.count(term) for term in terms)
                if score:
                    candidates.append({"kind": "event", "score": score, **event_item})
            documents = db.scalars(
                select(AssetDocumentRow).where(AssetDocumentRow.service_id == service_id)
            ).all()
            for row in documents:
                heading = f"{row.name}\n{row.description}".casefold()
                content = row.extracted_text
                content_haystack = content.casefold()
                score = sum(
                    3 * heading.count(term) + content_haystack.count(term) for term in terms
                )
                if score:
                    first = min(
                        (content_haystack.find(term) for term in terms if term in content_haystack),
                        default=0,
                    )
                    start = max(0, first - 240)
                    candidates.append(
                        {
                            "kind": "document",
                            "score": score,
                            "id": row.id,
                            "name": row.name,
                            "description": row.description,
                            "excerpt": content[start : start + 1200],
                            "created_at": row.created_at,
                        }
                    )
        candidates.sort(
            key=lambda item: (item["score"], item.get("created_at") or _now()), reverse=True
        )
        return candidates[: min(max(limit, 1), 30)]

    def append_message(
        self,
        session_id: str,
        *,
        role: str,
        content: str,
        message_type: str = "chat",
        metadata: Mapping[str, Any] | None = None,
        created_at: datetime | None = None,
    ) -> dict[str, Any]:
        if role not in {"user", "assistant", "system", "tool"}:
            raise StorageError("Unsupported message role")
        if message_type not in {"chat", "manual", "tool", "system"}:
            raise StorageError("Unsupported message type")
        if not content or len(content) > 2_000_000:
            raise StorageError("content must contain 1-2000000 characters")
        with Session(self.engine) as db:
            parent = db.get(SessionRow, session_id)
            if not parent:
                raise StorageError("Session does not exist")
            row = MessageRow(
                session_id=session_id,
                role=role,
                content=content,
                message_type=message_type,
                metadata_json=dict(metadata or {}),
                created_at=created_at or _now(),
            )
            parent.updated_at = parent.last_activity_at = _now()
            db.add(row)
            db.commit()
            db.refresh(row)
            return self._message_dict(row)

    def update_message(
        self,
        message_id: str,
        *,
        content: str,
        metadata: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Replace one durable message body while preserving its timeline position."""
        if not content or len(content) > 2_000_000:
            raise StorageError("content must contain 1-2000000 characters")
        with Session(self.engine) as db:
            row = db.get(MessageRow, message_id)
            if row is None:
                raise StorageError("Message does not exist")
            parent = db.get(SessionRow, row.session_id)
            row.content = content
            row.metadata_json = dict(metadata)
            if parent is not None:
                parent.updated_at = parent.last_activity_at = _now()
            db.commit()
            db.refresh(row)
            return self._message_dict(row)

    def list_messages(
        self,
        session_id: str,
        *,
        limit: int | None = None,
        include_superseded: bool = False,
    ) -> list[dict[str, Any]]:
        query = (
            select(MessageRow)
            .where(MessageRow.session_id == session_id)
            .order_by(MessageRow.created_at.asc(), MessageRow.id.asc())
        )
        if limit is not None:
            # When callers explicitly request a bound, return the newest N messages in their
            # original chronological order. The old ascending LIMIT accidentally returned the
            # oldest N messages and hid current activity in long sessions.
            bounded = min(max(limit, 1), 100_000)
            query = (
                select(MessageRow)
                .where(MessageRow.session_id == session_id)
                .order_by(MessageRow.created_at.desc(), MessageRow.id.desc())
                .limit(bounded)
            )
        with Session(self.engine) as db:
            rows = db.scalars(query).all()
            if limit is not None:
                rows.reverse()
            messages = [self._message_dict(row) for row in rows]
            if include_superseded:
                return messages
            return [
                message
                for message in messages
                if not message["metadata"].get("superseded_by_revision")
            ]

    def count_messages(self, session_id: str, *, role: str | None = None) -> int:
        from sqlalchemy import func

        query = select(func.count(MessageRow.id)).where(MessageRow.session_id == session_id)
        if role is not None:
            query = query.where(MessageRow.role == role)
        with Session(self.engine) as db:
            return int(db.scalar(query) or 0)

    def branch_session(
        self,
        parent_session_id: str,
        through_message_id: str,
        *,
        child_session_id: str,
        title: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a session and copy history through one message, inclusively."""
        child_session_id = self._required(child_session_id, "child_session_id", 200)
        with Session(self.engine) as db:
            parent = db.get(SessionRow, parent_session_id)
            boundary = db.get(MessageRow, through_message_id)
            if parent is None:
                raise StorageError("Parent session does not exist")
            if boundary is None or boundary.session_id != parent_session_id:
                raise StorageError("Branch message does not belong to the parent session")
            if db.get(SessionRow, child_session_id):
                raise StorageError("Child session already exists")

            if title is None:
                child_titles = db.scalars(
                    select(SessionRow.title)
                    .join(
                        SessionBranchRow,
                        SessionBranchRow.child_session_id == SessionRow.id,
                    )
                    .where(SessionBranchRow.parent_session_id == parent_session_id)
                ).all()
                used_titles = set(child_titles)
                branch_number = 1
                suffix = f"（{branch_number}）"
                candidate = f"{parent.title[: 200 - len(suffix)]}{suffix}"
                while candidate in used_titles:
                    branch_number += 1
                    suffix = f"（{branch_number}）"
                    candidate = f"{parent.title[: 200 - len(suffix)]}{suffix}"
                title = candidate

            child = SessionRow(
                id=child_session_id,
                title=self._required(title, "title", 200),
                host_id=parent.host_id,
                user_id=user_id or parent.user_id,
                permission_mode=parent.permission_mode,
                model_config_id=parent.model_config_id,
            )
            db.add(child)
            source_messages = db.scalars(
                select(MessageRow)
                .where(
                    MessageRow.session_id == parent_session_id,
                    (MessageRow.created_at < boundary.created_at)
                    | (
                        (MessageRow.created_at == boundary.created_at)
                        & (MessageRow.id <= boundary.id)
                    ),
                )
                .order_by(MessageRow.created_at.asc(), MessageRow.id.asc())
            ).all()
            for source in source_messages:
                metadata = dict(source.metadata_json or {})
                metadata["branched_from_message_id"] = source.id
                db.add(
                    MessageRow(
                        session_id=child_session_id,
                        role=source.role,
                        message_type=source.message_type,
                        content=source.content,
                        metadata_json=metadata,
                        created_at=source.created_at,
                    )
                )
            db.add(
                SessionBranchRow(
                    child_session_id=child_session_id,
                    parent_session_id=parent_session_id,
                    through_message_id=through_message_id,
                )
            )
            parent_mount = db.get(SessionAssetMountRow, parent_session_id)
            if parent_mount:
                db.add(
                    SessionAssetMountRow(
                        session_id=child_session_id,
                        service_id=parent_mount.service_id,
                    )
                )
            db.commit()
            db.refresh(child)
            result = self._session_dict(child)
            result["branch"] = {
                "parent_session_id": parent_session_id,
                "through_message_id": through_message_id,
                "message_count": len(source_messages),
            }
            return result

    def revise_session_from_message(
        self,
        session_id: str,
        message_id: str,
    ) -> dict[str, Any]:
        """Hide the latest AI turn in-place while retaining it for reports and audit.

        The replacement is appended through the normal run endpoint. Superseded rows are never
        deleted: the interactive transcript filters them, while report export can request the
        complete revision history.
        """
        with Session(self.engine) as db:
            parent = db.get(SessionRow, session_id)
            target = db.get(MessageRow, message_id)
            if parent is None:
                raise StorageError("Session does not exist")
            if target is None or target.session_id != session_id:
                raise StorageError("Revision message does not belong to the parent session")
            latest_user = db.scalar(
                select(MessageRow)
                .where(
                    MessageRow.session_id == session_id,
                    MessageRow.role == "user",
                )
                .order_by(MessageRow.created_at.desc(), MessageRow.id.desc())
                .limit(1)
            )
            if latest_user is None or latest_user.id != target.id:
                raise StorageError("Only the latest user message can be revised")
            if (target.metadata_json or {}).get("source") != "ai_composer":
                raise StorageError("Only an AI composer message can be revised")
            superseded = db.scalars(
                select(MessageRow)
                .where(
                    MessageRow.session_id == session_id,
                    (MessageRow.created_at > target.created_at)
                    | ((MessageRow.created_at == target.created_at) & (MessageRow.id >= target.id)),
                )
                .order_by(MessageRow.created_at.asc(), MessageRow.id.asc())
            ).all()
            revision_id = str(uuid.uuid4())
            revised_at = _now().isoformat()
            for row in superseded:
                metadata = dict(row.metadata_json or {})
                metadata["superseded_by_revision"] = revision_id
                metadata["superseded_at"] = revised_at
                metadata["revision_target_message_id"] = target.id
                row.metadata_json = metadata
            parent.updated_at = parent.last_activity_at = _now()
            db.commit()
            db.refresh(parent)
            result = self._session_dict(parent)
            result["revision"] = {
                "revised_message_id": target.id,
                "revision_id": revision_id,
                "superseded_message_count": len(superseded),
            }
            return result

    def create_run(
        self,
        run_id: str,
        *,
        session_id: str,
        user_id: str,
        input_text: str,
    ) -> dict[str, Any]:
        if not input_text or len(input_text) > 2_000_000:
            raise StorageError("input_text must contain 1-2000000 characters")
        row = AgentRunRow(
            id=self._required(run_id, "run_id", 200),
            session_id=session_id,
            user_id=self._required(user_id, "user_id", 200),
            input_text=input_text,
        )
        with Session(self.engine) as db:
            if not db.get(SessionRow, session_id):
                raise StorageError("Session does not exist")
            db.add(row)
            db.commit()
            db.refresh(row)
            return self._run_dict(row)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with Session(self.engine) as db:
            row = db.get(AgentRunRow, run_id)
            return self._run_dict(row) if row else None

    def list_runs(
        self, *, session_id: str, active_only: bool = False, limit: int = 100
    ) -> list[dict[str, Any]]:
        query = select(AgentRunRow).where(AgentRunRow.session_id == session_id)
        if active_only:
            query = query.where(AgentRunRow.status.in_(("queued", "running", "paused")))
        query = query.order_by(AgentRunRow.created_at.desc()).limit(min(max(limit, 1), 500))
        with Session(self.engine) as db:
            return [self._run_dict(row) for row in db.scalars(query).all()]

    def update_run(
        self,
        run_id: str,
        *,
        status: str,
        output_text: str = "",
        error: str | None = None,
    ) -> dict[str, Any]:
        if status not in {"queued", "running", "paused", "completed", "failed", "cancelled"}:
            raise StorageError("Unsupported run status")
        with Session(self.engine) as db:
            row = db.get(AgentRunRow, run_id)
            if row is None:
                raise StorageError("Run does not exist")
            row.status = status
            row.output_text = output_text
            row.error = error
            if status == "running" and row.started_at is None:
                row.started_at = _now()
            if status in {"completed", "failed", "cancelled"}:
                row.completed_at = _now()
            db.commit()
            db.refresh(row)
            return self._run_dict(row)

    def append_run_event(
        self, run_id: str, *, event_type: str, payload: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        event_type = self._required(event_type, "event_type", 80)
        with Session(self.engine) as db:
            if not db.get(AgentRunRow, run_id):
                raise StorageError("Run does not exist")
            last = db.scalar(
                select(AgentRunEventRow.sequence)
                .where(AgentRunEventRow.run_id == run_id)
                .order_by(AgentRunEventRow.sequence.desc())
                .limit(1)
            )
            row = AgentRunEventRow(
                run_id=run_id,
                sequence=int(last or 0) + 1,
                event_type=event_type,
                payload_json=dict(payload or {}),
            )
            db.add(row)
            db.commit()
            db.refresh(row)
            return self._run_event_dict(row)

    def list_run_events(
        self, run_id: str, *, after_sequence: int = 0, limit: int = 1000
    ) -> list[dict[str, Any]]:
        query = (
            select(AgentRunEventRow)
            .where(
                AgentRunEventRow.run_id == run_id,
                AgentRunEventRow.sequence > max(after_sequence, 0),
            )
            .order_by(AgentRunEventRow.sequence.asc())
            .limit(min(max(limit, 1), 5000))
        )
        with Session(self.engine) as db:
            return [self._run_event_dict(row) for row in db.scalars(query).all()]

    def save_model_config(
        self,
        config_id: str,
        *,
        name: str,
        provider: str,
        model_id: str,
        base_url: str,
        api_key: str | None = None,
        thinking_mode: str = "auto",
        max_context_k: int = 128,
        supports_vision: bool = False,
        is_default: bool = False,
        enabled: bool = True,
    ) -> dict[str, Any]:
        values = {
            "name": self._required(name, "name", 200),
            "provider": self._required(provider, "provider", 100),
            "model_id": self._required(model_id, "model_id", 300),
            "base_url": self._required(base_url, "base_url", 1000),
        }
        if thinking_mode not in {"auto", "on", "off"}:
            raise StorageError("thinking_mode must be auto, on, or off")
        if not 8 <= int(max_context_k) <= 4096:
            raise StorageError("max_context_k must be between 8 and 4096")
        config_id = self._required(config_id, "config_id", 100)
        with Session(self.engine) as db:
            row = db.get(ModelConfigRow, config_id)
            if row is None:
                row = ModelConfigRow(id=config_id, **values)
                db.add(row)
            else:
                for key, value in values.items():
                    setattr(row, key, value)
            # None preserves an existing secret during metadata-only updates.
            if api_key is not None:
                row.api_key = api_key.strip() or None
            row.is_default = is_default
            row.enabled = enabled
            row.thinking_mode = thinking_mode
            row.max_context_k = int(max_context_k)
            row.supports_vision = bool(supports_vision)
            row.updated_at = _now()
            if is_default:
                for other in db.scalars(
                    select(ModelConfigRow).where(ModelConfigRow.id != config_id)
                ):
                    other.is_default = False
            db.commit()
            db.refresh(row)
            return self._model_dict(row)

    def get_model_config(self, config_id: str) -> dict[str, Any] | None:
        with Session(self.engine) as db:
            row = db.get(ModelConfigRow, config_id)
            return self._model_dict(row) if row else None

    def list_model_configs(self, *, enabled_only: bool = False) -> list[dict[str, Any]]:
        query = select(ModelConfigRow)
        if enabled_only:
            query = query.where(ModelConfigRow.enabled.is_(True))
        query = query.order_by(ModelConfigRow.is_default.desc(), ModelConfigRow.name.asc())
        with Session(self.engine) as db:
            return [self._model_dict(row) for row in db.scalars(query).all()]

    def get_model_credentials(self, config_id: str) -> dict[str, Any] | None:
        """Server-only secret projection; never expose this return value via an API DTO."""
        with Session(self.engine) as db:
            row = db.get(ModelConfigRow, config_id)
            if not row or not row.enabled or not row.api_key:
                return None
            return {
                "model_id": row.model_id,
                "base_url": row.base_url,
                "api_key": row.api_key,
                "provider": row.provider,
                "thinking_mode": row.thinking_mode,
                "max_context_k": row.max_context_k,
                "supports_vision": row.supports_vision,
            }

    def delete_model_config(self, config_id: str) -> bool:
        with Session(self.engine) as db:
            row = db.get(ModelConfigRow, config_id)
            if not row:
                return False
            db.delete(row)
            db.commit()
            return True

    def set_setting(self, key: str, value: Any) -> dict[str, Any]:
        key = self._required(key, "key", 200)
        with Session(self.engine) as db:
            row = db.get(AppSettingRow, key)
            if row is None:
                row = AppSettingRow(key=key, value_json=value)
                db.add(row)
            else:
                row.value_json = value
                row.updated_at = _now()
            db.commit()
            db.refresh(row)
            return {"key": row.key, "value": row.value_json, "updated_at": row.updated_at}

    def get_setting(self, key: str, default: Any = None) -> Any:
        with Session(self.engine) as db:
            row = db.get(AppSettingRow, key)
            return row.value_json if row else default

    def list_settings(self) -> dict[str, Any]:
        with Session(self.engine) as db:
            return {
                row.key: row.value_json
                for row in db.scalars(select(AppSettingRow).order_by(AppSettingRow.key)).all()
            }

    def delete_setting(self, key: str) -> bool:
        with Session(self.engine) as db:
            row = db.get(AppSettingRow, key)
            if not row:
                return False
            db.delete(row)
            db.commit()
            return True

    def create_approval(
        self,
        *,
        session_id: str,
        host_id: str,
        command: str,
        requested_by: str,
        expires_at: datetime | None = None,
    ) -> dict[str, Any]:
        if not command or len(command) > 20_000:
            raise StorageError("command must contain 1-20000 characters")
        row = CommandApprovalRow(
            session_id=session_id,
            host_id=self._required(host_id, "host_id", 200),
            command=command,
            requested_by=self._required(requested_by, "requested_by", 200),
            expires_at=expires_at,
        )
        with Session(self.engine) as db:
            if not db.get(SessionRow, session_id):
                raise StorageError("Session does not exist")
            db.add(row)
            db.commit()
            db.refresh(row)
            return self._approval_dict(row)

    def get_approval(self, approval_id: str) -> dict[str, Any] | None:
        with Session(self.engine) as db:
            row = db.get(CommandApprovalRow, approval_id)
            return self._approval_dict(row) if row else None

    def list_approvals(
        self, *, session_id: str | None = None, status: str | None = None, limit: int = 100
    ) -> list[dict[str, Any]]:
        query = select(CommandApprovalRow)
        if session_id is not None:
            query = query.where(CommandApprovalRow.session_id == session_id)
        if status is not None:
            query = query.where(CommandApprovalRow.status == status)
        query = query.order_by(CommandApprovalRow.requested_at.desc()).limit(
            min(max(limit, 1), 500)
        )
        with Session(self.engine) as db:
            return [self._approval_dict(row) for row in db.scalars(query).all()]

    def decide_approval(
        self, approval_id: str, *, decision: str, decided_by: str, reason: str | None = None
    ) -> dict[str, Any]:
        if decision not in {"approved", "rejected"}:
            raise StorageError("Decision must be approved or rejected")
        with Session(self.engine) as db:
            row = db.get(CommandApprovalRow, approval_id)
            if not row:
                raise StorageError("Approval does not exist")
            if row.status != "pending":
                raise StorageError("Only pending approvals can be decided")
            if row.expires_at and row.expires_at.replace(tzinfo=UTC) <= _now():
                row.status = "expired"
                db.commit()
                raise StorageError("Approval has expired")
            row.status = decision
            row.decided_by = self._required(decided_by, "decided_by", 200)
            row.reason = reason
            row.decided_at = _now()
            db.commit()
            db.refresh(row)
            return self._approval_dict(row)

    def mark_approval_executed(self, approval_id: str) -> dict[str, Any]:
        with Session(self.engine) as db:
            row = db.get(CommandApprovalRow, approval_id)
            if not row:
                raise StorageError("Approval does not exist")
            if row.status != "approved":
                raise StorageError("Only approved commands can be marked executed")
            row.status = "executed"
            row.executed_at = _now()
            db.commit()
            db.refresh(row)
            return self._approval_dict(row)

    def append_audit_event(
        self,
        *,
        actor: str,
        event_type: str,
        action: str,
        outcome: str,
        session_id: str | None = None,
        target: str | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_action = self._required(action, "action", 20_000)
        if len(normalized_action) > 500:
            # The full command/tool payload remains in details_json.  Keep the indexed
            # display column bounded without allowing observability to fail an otherwise
            # successful Agent tool call.
            digest = hashlib.sha256(normalized_action.encode("utf-8")).hexdigest()[:12]
            suffix = f" … [sha256:{digest}]"
            normalized_action = normalized_action[: 500 - len(suffix)].rstrip() + suffix
        row = AuditEventRow(
            actor=self._required(actor, "actor", 200),
            event_type=self._required(event_type, "event_type", 100),
            action=normalized_action,
            outcome=self._required(outcome, "outcome", 30),
            session_id=session_id,
            target=target,
            details_json=dict(details or {}),
        )
        with Session(self.engine) as db:
            db.add(row)
            db.commit()
            db.refresh(row)
            return self._audit_dict(row)

    def list_audit_events(
        self,
        *,
        session_id: str | None = None,
        event_type: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        query = select(AuditEventRow)
        if session_id is not None:
            query = query.where(AuditEventRow.session_id == session_id)
        if event_type is not None:
            query = query.where(AuditEventRow.event_type == event_type)
        query = query.order_by(AuditEventRow.created_at.desc()).limit(min(max(limit, 1), 1000))
        with Session(self.engine) as db:
            return [self._audit_dict(row) for row in db.scalars(query).all()]
