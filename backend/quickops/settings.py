from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Server-only bootstrap settings.

    Model identity and endpoint are product configuration, not deployment knobs. They are
    intentionally fixed here for the first vertical slice and will move into the product's
    model registry when that surface is connected to the backend.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    siliconflow_api_key: str | None = Field(default=None, repr=False)
    quickops_db_file: Path = Path("data/quickops.db")
    quickops_allowed_hosts: tuple[str, ...] = ("prod-web-03",)
    quickops_auth_username: str | None = Field(default=None, repr=False)
    quickops_auth_password: str | None = Field(default=None, repr=False)
    quickops_auth_session_ttl_hours: int = Field(default=12, ge=1, le=168)
    # Production/offline installs can let the API process serve the compiled SPA directly,
    # avoiding a mandatory Nginx dependency on otherwise clean intranet hosts.
    quickops_static_dir: Path | None = None

    model_id: str = "deepseek-ai/DeepSeek-V4-Flash"
    model_base_url: str = "https://api.siliconflow.cn/v1"
    model_provider: str = "SiliconFlow"
    thinking_mode: str = "auto"
    max_context_tokens: int = 128_000
    # Optional Agno toolkits are selected by the product settings surface. Every toolkit is
    # disabled by default; credentials remain server-side inside toolkit_config.
    enabled_toolkits: tuple[str, ...] = ()
    toolkit_config: dict[str, dict[str, object]] = Field(default_factory=dict, repr=False)
    # Local-host development starts both AI tools and operator terminals in the login
    # account's home directory. Remote adapters can override this with the remote account home.
    quickops_workspace_root: Path = Field(default_factory=Path.home)
    # Per-run authoritative target identity populated by the product API.
    quickops_target_host_id: str = ""
    quickops_target_host_name: str = ""
    quickops_target_host_ip: str = ""
    quickops_target_host_platform: str = ""

    @field_validator("quickops_allowed_hosts", mode="before")
    @classmethod
    def parse_allowed_hosts(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(item.strip() for item in value.split(",") if item.strip())
        return value

    @field_validator("enabled_toolkits", mode="before")
    @classmethod
    def parse_enabled_toolkits(cls, value: object) -> object:
        if isinstance(value, str):
            return tuple(item.strip() for item in value.split(",") if item.strip())
        return value

    def ensure_data_dir(self) -> None:
        self.quickops_db_file.parent.mkdir(parents=True, exist_ok=True)
