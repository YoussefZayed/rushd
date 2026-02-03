"""User configuration management for rushd."""

import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class PrimaryConfig(BaseModel):
    """Configuration for the primary instance."""

    name: str = Field(default="primary", description="Name for the primary instance")
    working_dir: Path = Field(
        default=Path("/home/admin/control-center"),
        description="Working directory for primary instance",
    )
    model: Optional[str] = Field(default=None, description="Default model")
    auto_approve: bool = Field(default=True, description="Auto-approve prompts")


class DefaultsConfig(BaseModel):
    """Default settings for rushd."""

    session_name: str = Field(
        default="rushd-instances", description="Tmux session name"
    )


class DiscordChannels(BaseModel):
    """Discord channel IDs for each purpose."""

    activity: Optional[int] = Field(default=None, description="Activity stream channel")
    responses: Optional[int] = Field(default=None, description="Responses only channel")
    status: Optional[int] = Field(default=None, description="Status notifications channel")
    commands: Optional[int] = Field(default=None, description="Commands input channel")
    live_view: Optional[int] = Field(default=None, description="Live view channel (single updating message)")


class DiscordConfig(BaseModel):
    """Discord bot configuration."""

    enabled: bool = Field(default=False, description="Enable Discord bot")
    guild_id: Optional[int] = Field(default=None, description="Discord server ID")
    channels: DiscordChannels = Field(default_factory=DiscordChannels)
    allowed_users: list[str] = Field(default_factory=list, description="Discord usernames allowed to send commands")
    poll_interval: float = Field(default=2.0, description="Seconds between activity checks")
    screenshot_retention_days: int = Field(default=5, description="Days to keep screenshots before deletion")


class LogConfig(BaseModel):
    """Output logging configuration."""

    enabled: bool = Field(default=True, description="Enable output logging")
    max_file_size_mb: int = Field(default=50, description="Max log file size before rotation")
    retention_days: int = Field(default=7, description="Days to keep logs before cleanup")
    log_dir: Path = Field(
        default_factory=lambda: Path.home() / ".rushd" / "logs",
        description="Directory for output logs",
    )


class RushdConfig(BaseModel):
    """Root configuration model."""

    version: str = "1.0"
    primary: PrimaryConfig = Field(default_factory=PrimaryConfig)
    defaults: DefaultsConfig = Field(default_factory=DefaultsConfig)
    discord: DiscordConfig = Field(default_factory=DiscordConfig)
    logs: LogConfig = Field(default_factory=LogConfig)


class ConfigManager:
    """Manages user configuration at ~/.rushd/config.json."""

    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or Path.home() / ".rushd" / "config.json"

    def _ensure_dir(self) -> None:
        """Ensure the config directory exists."""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> RushdConfig:
        """Load configuration, returning defaults if not found."""
        if not self.config_path.exists():
            return RushdConfig()
        try:
            with open(self.config_path, "r") as f:
                data = json.load(f)
            return RushdConfig.model_validate(data)
        except (json.JSONDecodeError, IOError):
            return RushdConfig()

    def save(self, config: RushdConfig) -> None:
        """Save configuration to disk."""
        self._ensure_dir()
        with open(self.config_path, "w") as f:
            json.dump(config.model_dump(mode="json"), f, indent=2, default=str)

    def get_primary(self) -> PrimaryConfig:
        """Get primary instance configuration."""
        return self.load().primary

    def exists(self) -> bool:
        """Check if config file exists."""
        return self.config_path.exists()
