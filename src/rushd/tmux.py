"""Tmux controller for managing Claude Code instances in tmux windows."""

import hashlib
import subprocess
import time
from typing import Optional


class TmuxController:
    """Controller for managing tmux sessions and windows for Claude Code instances."""

    def __init__(self, session_name: str = "rushd-instances"):
        self.session_name = session_name
        self._ensure_session()

    def _run_tmux(self, args: list[str], check: bool = False) -> tuple[str, int]:
        """Run a tmux command and return (stdout, exit_code)."""
        cmd = ["tmux"] + args
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.stdout.strip(), result.returncode

    def _ensure_session(self) -> None:
        """Create the tmux session if it doesn't exist."""
        _, code = self._run_tmux(["has-session", "-t", self.session_name])
        if code != 0:
            # Create detached session with a placeholder window
            self._run_tmux([
                "new-session", "-d", "-s", self.session_name, "-n", "placeholder"
            ])

    def session_exists(self) -> bool:
        """Check if the managed session exists."""
        _, code = self._run_tmux(["has-session", "-t", self.session_name])
        return code == 0

    def create_window(
        self,
        name: str,
        command: str,
        working_dir: Optional[str] = None
    ) -> tuple[str, str]:
        """
        Create a new window in the session and run a command.

        Returns (window_target, pane_id).
        """
        self._ensure_session()

        args = ["new-window", "-t", self.session_name, "-n", name, "-P", "-F", "#{window_index}:#{pane_id}"]
        if working_dir:
            args.extend(["-c", working_dir])
        args.append(command)

        output, code = self._run_tmux(args)
        if code != 0:
            raise RuntimeError(f"Failed to create tmux window: {output}")

        # Parse output like "1:%5"
        parts = output.split(":")
        window_index = parts[0] if parts else "0"
        pane_id = parts[1] if len(parts) > 1 else ""

        window_target = f"{self.session_name}:{window_index}"
        return window_target, pane_id

    def list_windows(self) -> list[dict]:
        """List all windows in the session."""
        if not self.session_exists():
            return []

        output, code = self._run_tmux([
            "list-windows", "-t", self.session_name,
            "-F", "#{window_index}|#{window_name}|#{pane_id}|#{pane_current_command}"
        ])
        if code != 0:
            return []

        windows = []
        for line in output.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|")
            if len(parts) >= 4:
                windows.append({
                    "index": parts[0],
                    "name": parts[1],
                    "pane_id": parts[2],
                    "command": parts[3],
                    "target": f"{self.session_name}:{parts[0]}"
                })
        return windows

    def window_exists(self, window_target: str) -> bool:
        """Check if a specific window exists."""
        _, code = self._run_tmux(["select-window", "-t", window_target])
        return code == 0

    def kill_window(self, window_target: str) -> bool:
        """Kill a specific window."""
        _, code = self._run_tmux(["kill-window", "-t", window_target])
        return code == 0

    def send_keys(
        self,
        window_target: str,
        text: str,
        enter: bool = True,
        delay_enter: float = 0.5
    ) -> bool:
        """
        Send keys to a window.

        Args:
            window_target: The tmux window target
            text: Text to send
            enter: Whether to send Enter after the text
            delay_enter: Delay before sending Enter (for reliability)
        """
        # Ensure text is a string
        text = str(text)

        # Send the text
        _, code = self._run_tmux(["send-keys", "-t", window_target, text])
        if code != 0:
            return False

        if enter:
            time.sleep(delay_enter)
            _, code = self._run_tmux(["send-keys", "-t", window_target, "Enter"])
            return code == 0

        return True

    def send_interrupt(self, window_target: str) -> bool:
        """Send Ctrl+C to a window."""
        _, code = self._run_tmux(["send-keys", "-t", window_target, "C-c"])
        return code == 0

    def capture_pane(self, window_target: str, lines: int = 500) -> str:
        """Capture the current content of a pane."""
        output, code = self._run_tmux([
            "capture-pane", "-t", window_target, "-p", "-S", f"-{lines}"
        ])
        if code != 0:
            return ""
        return output

    def wait_for_idle(
        self,
        window_target: str,
        timeout: float = 30.0,
        poll_interval: float = 0.5,
        stable_count: int = 3
    ) -> bool:
        """
        Wait until the pane output stops changing.

        Uses MD5 hashing to detect changes efficiently.
        """
        start = time.time()
        last_hash = None
        stable = 0

        while time.time() - start < timeout:
            content = self.capture_pane(window_target)
            current_hash = hashlib.md5(content.encode()).hexdigest()

            if current_hash == last_hash:
                stable += 1
                if stable >= stable_count:
                    return True
            else:
                stable = 0
                last_hash = current_hash

            time.sleep(poll_interval)

        return False

    def attach_session(self, window_target: Optional[str] = None) -> None:
        """Attach to the managed session (blocking, hands off to tmux).

        If already inside tmux, uses switch-client instead of attach-session.
        """
        import os

        # Select the specific window first if provided
        if window_target:
            self.select_window(window_target)

        if os.environ.get("TMUX"):
            # Already inside tmux - use switch-client
            subprocess.run(["tmux", "switch-client", "-t", self.session_name])
        else:
            # Not in tmux - use attach-session
            subprocess.run(["tmux", "attach-session", "-t", self.session_name])

    def select_window(self, window_target: str) -> bool:
        """Select (focus) a specific window."""
        _, code = self._run_tmux(["select-window", "-t", window_target])
        return code == 0

    def cleanup_session(self) -> bool:
        """Kill the entire managed session."""
        _, code = self._run_tmux(["kill-session", "-t", self.session_name])
        return code == 0

    def get_pane_pid(self, window_target: str) -> Optional[int]:
        """Get the PID of the process running in a pane."""
        output, code = self._run_tmux([
            "display-message", "-t", window_target, "-p", "#{pane_pid}"
        ])
        if code != 0 or not output:
            return None
        try:
            return int(output)
        except ValueError:
            return None
