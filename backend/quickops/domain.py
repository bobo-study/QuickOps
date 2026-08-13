from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class PermissionMode(StrEnum):
    READONLY = "readonly"
    APPROVAL = "approval"
    DELEGATED_APPROVAL = "delegated_approval"
    FULL_ACCESS = "full_access"


class ThinkingMode(StrEnum):
    """Provider-neutral reasoning mode stored with a model configuration."""

    OFF = "off"
    ON = "on"
    AUTO = "auto"


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=1, max_length=2000)


class HostSignal(BaseModel):
    cpu_percent: int = Field(ge=0, le=100)
    load_1m: float = Field(ge=0)
    memory_percent: int = Field(ge=0, le=100)
    disk_percent: int = Field(ge=0, le=100)
    network_out_kbps: int = Field(ge=0)
    network_in_kbps: int = Field(ge=0)


class HostSummary(BaseModel):
    id: str
    name: str | None = None
    ip: str
    environment: str
    role: str
    platform: str | None = None
    tags: list[str]
    online: bool
    source: str = "managed"
    is_local: bool = False
    signals: HostSignal


class BootstrapResponse(BaseModel):
    agent_id: str
    model_id: str
    model_provider: str
    model_configured: bool
    permission_mode: PermissionMode
    permission_modes_enabled: list[PermissionMode] = Field(default_factory=list)
    hosts: list[HostSummary]


class ManualCommandRequest(BaseModel):
    host_id: str
    command: str = Field(min_length=1, max_length=20_000)
    session_id: str = Field(min_length=1, max_length=200)
    user_id: str = Field(default="operator", min_length=1, max_length=200)


class ManualCommandResponse(BaseModel):
    host_id: str
    command: str
    output: str
    exit_code: int
    truncated: bool = False
    terminal_id: str
    terminal_alive: bool = True
    shell: str
    cwd: str
    user_message_id: str
    message_id: str
    created_at: str


class AgentRunRequest(BaseModel):
    message: str = Field(min_length=1, max_length=20_000)
    host_id: str
    session_id: str = Field(min_length=1, max_length=200)
    user_id: str = Field(default="operator", min_length=1, max_length=200)
    attachment_ids: list[str] = Field(default_factory=list, max_length=10)


class AgentRunResponse(BaseModel):
    run_id: str
    session_id: str
    user_message_id: str
    status: str
    content: str = ""
    tools: list[dict[str, object]] = Field(default_factory=list)


class SessionCreateRequest(BaseModel):
    id: str | None = Field(default=None, max_length=200)
    session_id: str | None = Field(default=None, max_length=200)
    title: str = Field(default="新会话", min_length=1, max_length=200)
    host_id: str
    user_id: str = Field(default="operator", min_length=1, max_length=200)
    permission_mode: PermissionMode = PermissionMode.APPROVAL
    model_config_id: str | None = None


class SessionReviseRequest(BaseModel):
    message_id: str = Field(min_length=1, max_length=200)
    user_id: str = Field(default="operator", min_length=1, max_length=200)


class SessionUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    host_id: str | None = None
    permission_mode: PermissionMode | None = None
    model_config_id: str | None = None


class ModelConfigRequest(BaseModel):
    id: str | None = Field(default=None, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    provider: str = Field(min_length=1, max_length=100)
    model_id: str = Field(min_length=1, max_length=300)
    base_url: str = Field(min_length=1, max_length=1000)
    api_key: str | None = Field(default=None, max_length=2000)
    thinking_mode: ThinkingMode = ThinkingMode.AUTO
    max_context_k: int = Field(default=128, ge=8, le=4096)
    is_default: bool = False
    enabled: bool = True


class ApprovalDecisionRequest(BaseModel):
    user_id: str = Field(default="operator", min_length=1, max_length=200)
    reason: str | None = Field(default=None, max_length=1000)


class SessionBranchRequest(BaseModel):
    through_message_id: str = Field(min_length=1, max_length=64)
    user_id: str = Field(default="operator", min_length=1, max_length=200)
