"""Shared command handlers for rushd.

This module provides the CommandHandler class that encapsulates all rushd
business logic. Both the CLI and Discord bot call these same handlers,
formatting the structured CommandResult for their respective interfaces.
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .config import ConfigManager
from .logs import LogEntry, ActivityState
from .manager import ClaudeInstanceManager
from .models import InstanceMetadata, InstanceStatus, DisplayMode


@dataclass
class CommandResult:
    """Structured result from a command handler."""

    success: bool
    message: str
    data: Optional[Any] = None
    error: Optional[str] = None


class CommandHandler:
    """Shared command handlers used by CLI, Discord, and TUI."""

    def __init__(self, manager: ClaudeInstanceManager, config_manager: ConfigManager):
        self.manager = manager
        self.config = config_manager

    def start_instance(
        self,
        name: Optional[str] = None,
        working_dir: Optional[Path] = None,
        model: Optional[str] = None,
        prompt: Optional[str] = None,
        resume: Optional[str] = None,
        auto_approve: bool = True,
    ) -> CommandResult:
        """Start a new Claude Code instance."""
        # If no name or dir specified, use primary config
        if name is None and working_dir is None:
            primary = self.config.get_primary()
            name = primary.name
            working_dir = primary.working_dir
            model = model or primary.model
            auto_approve = primary.auto_approve

        if working_dir and not working_dir.exists():
            return CommandResult(
                success=False,
                message=f"Working directory does not exist: {working_dir}",
                error="directory_not_found",
            )

        try:
            instance = self.manager.start_instance(
                name=name,
                working_dir=working_dir,
                model=model,
                initial_prompt=prompt,
                resume=resume,
                auto_approve=auto_approve,
            )
            return CommandResult(
                success=True,
                message=f"Started instance: {instance.name or instance.id}",
                data=instance,
            )
        except Exception as e:
            return CommandResult(
                success=False, message=f"Failed to start instance: {e}", error="start_failed"
            )

    def stop_instance(self, identifier: str, force: bool = False) -> CommandResult:
        """Stop an instance."""
        inst = self.manager.get_instance(identifier)
        if not inst:
            return CommandResult(
                success=False, message=f"Instance not found: {identifier}", error="not_found"
            )

        if self.manager.stop_instance(identifier, force=force):
            return CommandResult(success=True, message=f"Stopped: {identifier}", data=inst)
        return CommandResult(
            success=False, message=f"Failed to stop: {identifier}", error="stop_failed"
        )

    def stop_all(self, force: bool = False) -> CommandResult:
        """Stop all running instances."""
        count = self.manager.stop_all(force=force)
        return CommandResult(success=True, message=f"Stopped {count} instance(s)", data=count)

    def list_instances(self, include_stopped: bool = False) -> CommandResult:
        """List all instances."""
        self.manager.refresh_statuses()
        instances = self.manager.list_instances(include_stopped=include_stopped)
        return CommandResult(
            success=True,
            message=f"{len(instances)} instance(s)",
            data=instances,
        )

    def get_status(self, identifier: Optional[str] = None) -> CommandResult:
        """Get detailed status of an instance."""
        if identifier is None:
            identifier = self.config.get_primary().name

        self.manager.refresh_statuses()
        inst = self.manager.get_instance(identifier)
        if not inst:
            return CommandResult(
                success=False, message=f"Instance not found: {identifier}", error="not_found"
            )
        return CommandResult(success=True, message=f"Status: {inst.status}", data=inst)

    def send_message(self, identifier: str, message: str) -> CommandResult:
        """Send a message to an instance."""
        inst = self.manager.get_instance(identifier)
        if not inst:
            return CommandResult(
                success=False, message=f"Instance not found: {identifier}", error="not_found"
            )

        if self.manager.send_message(identifier, message):
            return CommandResult(success=True, message="Message sent")
        return CommandResult(
            success=False, message=f"Failed to send to: {identifier}", error="send_failed"
        )

    def send_key(self, identifier: str, key: str) -> CommandResult:
        """Send a special key to an instance."""
        inst = self.manager.get_instance(identifier)
        if not inst:
            return CommandResult(
                success=False, message=f"Instance not found: {identifier}", error="not_found"
            )

        if self.manager.send_key(identifier, key):
            return CommandResult(success=True, message=f"Key '{key}' sent")
        return CommandResult(
            success=False, message=f"Failed to send key to: {identifier}", error="send_failed"
        )

    def clear_instance(self, identifier: Optional[str] = None) -> CommandResult:
        """Stop, remove, and recreate an instance from primary config."""
        if identifier is None:
            identifier = self.config.get_primary().name

        # Stop and remove
        self.manager.stop_instance(identifier, force=True)
        self.manager.remove_instance(identifier)

        # Recreate from primary config
        primary = self.config.get_primary()
        try:
            instance = self.manager.start_instance(
                name=primary.name,
                working_dir=primary.working_dir,
                model=primary.model,
                auto_approve=primary.auto_approve,
            )
            return CommandResult(
                success=True,
                message=f"Cleared and recreated: {instance.name or instance.id}",
                data=instance,
            )
        except Exception as e:
            return CommandResult(
                success=False, message=f"Failed to recreate: {e}", error="clear_failed"
            )

    def get_activity(self, identifier: str, last_n: int = 30) -> CommandResult:
        """Get activity entries for an instance."""
        inst = self.manager.get_instance(identifier)
        if not inst:
            return CommandResult(
                success=False, message=f"Instance not found: {identifier}", error="not_found"
            )

        entries = self.manager.get_activity(identifier, last_n=last_n)
        return CommandResult(
            success=True,
            message=f"{len(entries)} entries",
            data=entries,
        )

    def get_activity_formatted(self, identifier: str, last_n: int = 30) -> CommandResult:
        """Get formatted activity string for display."""
        inst = self.manager.get_instance(identifier)
        if not inst:
            return CommandResult(
                success=False, message=f"Instance not found: {identifier}", error="not_found"
            )

        output = self.manager.get_activity_formatted(identifier, last_n=last_n)
        return CommandResult(success=True, message="Activity retrieved", data=output)

    def remove_instance(self, identifier: str) -> CommandResult:
        """Remove a stopped instance from storage."""
        inst = self.manager.get_instance(identifier)
        if not inst:
            return CommandResult(
                success=False, message=f"Instance not found: {identifier}", error="not_found"
            )

        if inst.status != InstanceStatus.STOPPED:
            if self.manager.tmux.window_exists(inst.tmux_window):
                return CommandResult(
                    success=False,
                    message="Instance is still running. Stop it first.",
                    error="still_running",
                )

        if self.manager.remove_instance(identifier):
            return CommandResult(success=True, message=f"Removed: {identifier}", data=inst)
        return CommandResult(
            success=False, message=f"Failed to remove: {identifier}", error="remove_failed"
        )

    def cleanup(self, force: bool = False) -> CommandResult:
        """Stop all instances and clean up the tmux session."""
        self.manager.cleanup(force=force)
        return CommandResult(success=True, message="Cleanup complete")

    def get_activity_state(self, identifier: str) -> CommandResult:
        """Get the current activity state of an instance."""
        state = self.manager.get_activity_state(identifier)
        return CommandResult(success=True, message=state.status, data=state)

    def is_running(self, identifier: Optional[str] = None) -> bool:
        """Check if an instance is running."""
        if identifier is None:
            identifier = self.config.get_primary().name
        return self.manager.is_primary_running(identifier)

    def capture_output(self, identifier: str, lines: int = 500) -> CommandResult:
        """Capture recent terminal output from an instance."""
        inst = self.manager.get_instance(identifier)
        if not inst:
            return CommandResult(
                success=False, message=f"Instance not found: {identifier}", error="not_found"
            )

        output = self.manager.capture_output(identifier, lines=lines)
        return CommandResult(success=True, message="Output captured", data=output)
