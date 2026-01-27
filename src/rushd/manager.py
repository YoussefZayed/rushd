"""Main manager for Claude Code instances."""

import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import InstanceMetadata, InstanceStatus, DisplayMode
from .store import InstanceStore
from .tmux import TmuxController
from .logs import ClaudeLogReader, LogEntry, format_activity


class ClaudeInstanceManager:
    """Manager for creating, controlling, and monitoring Claude Code instances."""

    def __init__(self, session_name: str = "rushd-instances"):
        self.session_name = session_name
        self.store = InstanceStore()
        self.tmux = TmuxController(session_name)

    def _generate_id(self) -> tuple[str, str]:
        """Generate a new instance ID (short_id, full_id)."""
        full_id = str(uuid.uuid4())
        short_id = full_id[:8]
        return short_id, full_id

    def _build_claude_command(
        self,
        working_dir: Path,
        model: Optional[str] = None,
        resume: Optional[str] = None,
        initial_prompt: Optional[str] = None,
        auto_approve: bool = True
    ) -> str:
        """Build the claude command to run."""
        cmd_parts = ["claude"]

        # Auto-approve all prompts by default (trust + permissions)
        if auto_approve:
            cmd_parts.append("--dangerously-skip-permissions")

        if model:
            cmd_parts.extend(["--model", model])

        if resume:
            cmd_parts.extend(["--resume", resume])

        if initial_prompt:
            # Escape quotes in the prompt
            escaped = initial_prompt.replace('"', '\\"')
            cmd_parts.extend(["-p", f'"{escaped}"'])

        return " ".join(cmd_parts)

    def start_instance(
        self,
        name: Optional[str] = None,
        working_dir: Optional[Path] = None,
        model: Optional[str] = None,
        resume: Optional[str] = None,
        initial_prompt: Optional[str] = None,
        auto_approve: bool = True
    ) -> InstanceMetadata:
        """
        Start a new Claude Code instance.

        Args:
            name: User-friendly name for the instance
            working_dir: Working directory (defaults to current)
            model: Claude model to use
            resume: Session ID to resume
            initial_prompt: Initial prompt to send
            auto_approve: Use --dangerously-skip-permissions (default True)

        Returns:
            The created instance metadata
        """
        short_id, full_id = self._generate_id()
        working_dir = working_dir or Path.cwd()
        working_dir = working_dir.resolve()

        # Create the window name
        window_name = name or short_id

        # Build and run the command
        command = self._build_claude_command(
            working_dir, model, resume, initial_prompt, auto_approve
        )
        window_target, pane_id = self.tmux.create_window(
            name=window_name,
            command=command,
            working_dir=str(working_dir)
        )

        # Create and store metadata
        instance = InstanceMetadata(
            id=short_id,
            full_id=full_id,
            name=name,
            status=InstanceStatus.STARTING,
            working_dir=working_dir,
            tmux_window=window_target,
            tmux_pane_id=pane_id,
            model=model,
            auto_approve=auto_approve,
        )

        self.store.add(instance)

        # Update status after a brief delay
        self._update_instance_status(instance)

        return instance

    def _update_instance_status(self, instance: InstanceMetadata) -> None:
        """Update the status of an instance based on tmux state."""
        if not self.tmux.window_exists(instance.tmux_window):
            self.store.update(instance.id, status=InstanceStatus.STOPPED)
            return

        # Check if there's activity
        self.store.update(
            instance.id,
            status=InstanceStatus.RUNNING,
            last_activity=datetime.now()
        )

    def stop_instance(self, identifier: str, force: bool = False) -> bool:
        """
        Stop a Claude Code instance.

        Args:
            identifier: Instance ID or name
            force: Skip graceful shutdown

        Returns:
            True if stopped successfully
        """
        instance = self.store.find_by_name_or_id(identifier)
        if not instance:
            return False

        if not force:
            # Try graceful shutdown with Ctrl+C
            self.tmux.send_interrupt(instance.tmux_window)
            # Wait a bit for graceful exit
            import time
            time.sleep(1)

        # Kill the window
        self.tmux.kill_window(instance.tmux_window)

        # Update store
        self.store.update(
            instance.id,
            status=InstanceStatus.STOPPED
        )

        return True

    def stop_all(self, force: bool = False) -> int:
        """Stop all running instances. Returns count of stopped instances."""
        instances = self.store.list_all(include_stopped=False)
        count = 0
        for instance in instances:
            if self.stop_instance(instance.id, force=force):
                count += 1
        return count

    def list_instances(self, include_stopped: bool = False) -> list[InstanceMetadata]:
        """List all managed instances."""
        instances = self.store.list_all(include_stopped=include_stopped)

        # Sync with actual tmux state
        for instance in instances:
            if instance.status != InstanceStatus.STOPPED:
                if not self.tmux.window_exists(instance.tmux_window):
                    self.store.update(instance.id, status=InstanceStatus.STOPPED)

        return self.store.list_all(include_stopped=include_stopped)

    def get_instance(self, identifier: str) -> Optional[InstanceMetadata]:
        """Get an instance by ID or name."""
        return self.store.find_by_name_or_id(identifier)

    def send_message(self, identifier: str, message: str) -> bool:
        """Send a message to an instance."""
        instance = self.store.find_by_name_or_id(identifier)
        if not instance:
            return False

        success = self.tmux.send_keys(instance.tmux_window, message, enter=True)
        if success:
            self.store.update(instance.id, last_activity=datetime.now())
        return success

    def capture_output(self, identifier: str, lines: int = 500) -> str:
        """Capture recent output from an instance."""
        instance = self.store.find_by_name_or_id(identifier)
        if not instance:
            return ""

        return self.tmux.capture_pane(instance.tmux_window, lines=lines)

    def attach(self, identifier: str) -> bool:
        """
        Attach to an instance's tmux window.

        This hands control to tmux and blocks until detached.
        """
        instance = self.store.find_by_name_or_id(identifier)
        if not instance:
            return False

        # Select the window first
        self.tmux.select_window(instance.tmux_window)
        # Then attach to the session
        self.tmux.attach_session()
        return True

    def cleanup(self, force: bool = False) -> None:
        """Stop all instances and clean up the tmux session."""
        self.stop_all(force=force)
        self.tmux.cleanup_session()
        self.store.clear_all()

    def refresh_statuses(self) -> None:
        """Refresh the status of all instances based on tmux state."""
        instances = self.store.list_all(include_stopped=True)
        for instance in instances:
            if instance.status == InstanceStatus.STOPPED:
                continue
            if not self.tmux.window_exists(instance.tmux_window):
                self.store.update(instance.id, status=InstanceStatus.STOPPED)
            else:
                self.store.update(instance.id, last_activity=datetime.now())

    def get_activity(self, identifier: str, last_n: int = 30) -> list[LogEntry]:
        """
        Get structured activity from Claude Code conversation logs.

        Args:
            identifier: Instance ID or name
            last_n: Number of recent log entries to return

        Returns:
            List of parsed LogEntry objects
        """
        instance = self.store.find_by_name_or_id(identifier)
        if not instance:
            return []

        log_reader = ClaudeLogReader(instance.working_dir)

        # Try to detect and store session ID if not already known
        if not instance.claude_session_id:
            session_id = log_reader.get_session_id()
            if session_id:
                self.store.update(instance.id, claude_session_id=session_id)

        return log_reader.read_entries(last_n=last_n)

    def get_activity_formatted(self, identifier: str, last_n: int = 30) -> str:
        """
        Get formatted activity string for display.

        Args:
            identifier: Instance ID or name
            last_n: Number of recent log entries

        Returns:
            Formatted string for display
        """
        entries = self.get_activity(identifier, last_n)
        if not entries:
            return "[No activity yet]"
        return format_activity(entries)

    def set_display_mode(self, identifier: str, mode: DisplayMode) -> bool:
        """Set the display mode for an instance."""
        instance = self.store.find_by_name_or_id(identifier)
        if not instance:
            return False
        self.store.update(instance.id, display_mode=mode)
        return True

    def get_display_mode(self, identifier: str) -> DisplayMode:
        """Get the current display mode for an instance."""
        instance = self.store.find_by_name_or_id(identifier)
        if not instance:
            return DisplayMode.ACTIVITY
        return DisplayMode(instance.display_mode)
