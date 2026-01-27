"""Data models for rushd."""

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field


class InstanceStatus(str, Enum):
    """Status states for a Claude Code instance."""

    STARTING = "starting"
    RUNNING = "running"
    THINKING = "thinking"
    TOOL_USE = "tool_use"
    IDLE = "idle"
    STOPPED = "stopped"
    ERROR = "error"


class DisplayMode(str, Enum):
    """Display mode for instance output."""

    ACTIVITY = "activity"  # Structured activity from logs
    RAW = "raw"  # Raw terminal output


class InstanceMetadata(BaseModel):
    """Metadata for a managed Claude Code instance."""

    id: str = Field(description="Short UUID (8 chars)")
    full_id: str = Field(description="Full UUID for uniqueness")
    name: Optional[str] = Field(default=None, description="User-friendly name")
    status: InstanceStatus = Field(default=InstanceStatus.STARTING)
    working_dir: Path = Field(description="Working directory for the instance")
    tmux_window: str = Field(description="Tmux window target (e.g., rushd-instances:1)")
    tmux_pane_id: str = Field(default="", description="Tmux pane ID (e.g., %5)")
    created_at: datetime = Field(default_factory=datetime.now)
    model: Optional[str] = Field(default=None, description="Claude model being used")
    last_activity: Optional[datetime] = Field(default=None)

    # New fields for v0.2
    claude_session_id: Optional[str] = Field(default=None, description="Claude Code session UUID")
    display_mode: DisplayMode = Field(default=DisplayMode.ACTIVITY, description="Output display mode")
    auto_approve: bool = Field(default=True, description="Whether instance uses --dangerously-skip-permissions")

    class Config:
        use_enum_values = True


class InstanceStore(BaseModel):
    """Root model for the instances.json file."""

    version: str = "1.0"
    session_name: str = "rushd-instances"
    instances: dict[str, InstanceMetadata] = Field(default_factory=dict)
