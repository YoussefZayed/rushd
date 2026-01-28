"""Read and parse Claude Code conversation logs."""

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional


@dataclass
class ActivityState:
    """Current activity state derived from log analysis."""

    status: Literal["thinking", "tool_use", "running", "idle", "unknown"]
    tool_name: Optional[str] = None
    seconds_since_activity: float = 0.0


@dataclass
class LogEntry:
    """Parsed log entry from Claude Code conversation."""

    type: str  # user, assistant, file-history-snapshot, summary
    timestamp: str
    uuid: str

    # Extracted fields
    thinking: Optional[str] = None
    tool_name: Optional[str] = None
    tool_input: Optional[dict] = field(default_factory=dict)
    tool_result: Optional[str] = None
    is_error: bool = False
    text_response: Optional[str] = None
    user_message: Optional[str] = None


class ClaudeLogReader:
    """Read and parse Claude Code conversation logs."""

    CLAUDE_DIR = Path.home() / ".claude"

    def __init__(self, working_dir: Path):
        self.working_dir = Path(working_dir).resolve()
        self.project_dir = self._get_project_dir()

    def _get_project_dir(self) -> Path:
        """Get the Claude project directory for this working dir."""
        # Claude encodes paths: /home/admin -> -home-admin
        encoded = str(self.working_dir).replace("/", "-")
        return self.CLAUDE_DIR / "projects" / encoded

    def find_latest_session(self) -> Optional[Path]:
        """Find the most recent session log file."""
        if not self.project_dir.exists():
            return None

        # Get all .jsonl files that look like session IDs (UUID format)
        logs = [
            p for p in self.project_dir.glob("*.jsonl")
            if len(p.stem) == 36 and "-" in p.stem  # UUID format
        ]

        if not logs:
            return None

        return max(logs, key=lambda p: p.stat().st_mtime)

    def get_session_id(self) -> Optional[str]:
        """Get the session ID of the latest session."""
        session_path = self.find_latest_session()
        if session_path:
            return session_path.stem
        return None

    def read_entries(self, session_path: Optional[Path] = None, last_n: int = 50) -> list[LogEntry]:
        """Read the last N entries from a session log."""
        if session_path is None:
            session_path = self.find_latest_session()

        if session_path is None or not session_path.exists():
            return []

        entries = []
        try:
            with open(session_path) as f:
                lines = f.readlines()

            for line in lines[-last_n:]:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    entry = self._parse_entry(data)
                    if entry:
                        entries.append(entry)
                except json.JSONDecodeError:
                    continue
        except IOError:
            pass

        return entries

    def _parse_entry(self, data: dict) -> Optional[LogEntry]:
        """Parse a raw log entry into structured LogEntry."""
        entry_type = data.get("type", "unknown")

        # Skip file-history-snapshot and other non-message types
        if entry_type in ("file-history-snapshot", "summary"):
            return None

        entry = LogEntry(
            type=entry_type,
            timestamp=data.get("timestamp", ""),
            uuid=data.get("uuid", ""),
        )

        # Handle user messages
        if entry_type == "user":
            message = data.get("message", {})
            content = message.get("content", "")

            # Simple text message
            if isinstance(content, str):
                entry.user_message = content

            # Tool result
            elif isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "tool_result":
                        entry.tool_result = str(item.get("content", ""))[:500]
                        entry.is_error = item.get("is_error", False)

                        # Also check toolUseResult for more details
                        tool_result = data.get("toolUseResult", {})
                        if tool_result:
                            stdout = tool_result.get("stdout", "")
                            stderr = tool_result.get("stderr", "")
                            if stderr:
                                entry.is_error = True
                                entry.tool_result = stderr[:500]
                            elif stdout:
                                entry.tool_result = stdout[:500]

        # Handle assistant messages
        elif entry_type == "assistant":
            message = data.get("message", {})
            content = message.get("content", [])

            if isinstance(content, list):
                for item in content:
                    if not isinstance(item, dict):
                        continue

                    item_type = item.get("type")

                    if item_type == "thinking":
                        entry.thinking = item.get("thinking", "")[:300]

                    elif item_type == "tool_use":
                        entry.tool_name = item.get("name")
                        entry.tool_input = item.get("input", {})

                    elif item_type == "text":
                        entry.text_response = item.get("text", "")[:500]

        return entry

    def detect_activity_state(self, idle_threshold_seconds: float = 5.0) -> ActivityState:
        """
        Detect the current activity state from the most recent log entries.

        Args:
            idle_threshold_seconds: Time after which to consider instance idle

        Returns:
            ActivityState with detected status and metadata
        """
        entries = self.read_entries(last_n=5)

        if not entries:
            return ActivityState(status="unknown")

        # Get the most recent entry
        latest = entries[-1]

        # Parse timestamp to determine age
        try:
            # Handle ISO format with Z suffix
            ts = latest.timestamp.replace("Z", "+00:00")
            entry_time = datetime.fromisoformat(ts)
            now = datetime.now(timezone.utc)
            seconds_ago = (now - entry_time).total_seconds()
        except (ValueError, AttributeError):
            seconds_ago = 0.0

        # If activity is stale, instance is idle
        if seconds_ago >= idle_threshold_seconds:
            return ActivityState(
                status="idle",
                seconds_since_activity=seconds_ago,
            )

        # Recent activity - determine specific state
        if latest.thinking:
            return ActivityState(
                status="thinking",
                seconds_since_activity=seconds_ago,
            )

        if latest.tool_name:
            return ActivityState(
                status="tool_use",
                tool_name=latest.tool_name,
                seconds_since_activity=seconds_ago,
            )

        if latest.tool_result is not None:
            # Just received tool result, still processing
            return ActivityState(
                status="tool_use",
                seconds_since_activity=seconds_ago,
            )

        # Default to running if recent activity but no specific state
        return ActivityState(
            status="running",
            seconds_since_activity=seconds_ago,
        )


def format_entry(entry: LogEntry) -> Optional[str]:
    """Format a log entry for display."""
    if entry.thinking:
        # Truncate thinking to first line or 100 chars
        thinking_preview = entry.thinking.split("\n")[0][:100]
        if len(entry.thinking) > 100:
            thinking_preview += "..."
        return f"🤔 {thinking_preview}"

    if entry.tool_name:
        desc = entry.tool_input.get("description", "") if entry.tool_input else ""
        if desc:
            return f"🔧 {entry.tool_name}: {desc}"
        else:
            # Try to get a useful preview from the input
            if entry.tool_name == "Read":
                file_path = entry.tool_input.get("file_path", "") if entry.tool_input else ""
                return f"🔧 Read: {file_path}"
            elif entry.tool_name == "Glob":
                pattern = entry.tool_input.get("pattern", "") if entry.tool_input else ""
                return f"🔧 Glob: {pattern}"
            elif entry.tool_name == "Grep":
                pattern = entry.tool_input.get("pattern", "") if entry.tool_input else ""
                return f"🔧 Grep: {pattern}"
            elif entry.tool_name == "Bash":
                cmd = entry.tool_input.get("command", "") if entry.tool_input else ""
                return f"🔧 Bash: {cmd[:60]}..."
            elif entry.tool_name == "Write":
                file_path = entry.tool_input.get("file_path", "") if entry.tool_input else ""
                return f"🔧 Write: {file_path}"
            elif entry.tool_name == "Edit":
                file_path = entry.tool_input.get("file_path", "") if entry.tool_input else ""
                return f"🔧 Edit: {file_path}"
            else:
                return f"🔧 {entry.tool_name}"

    if entry.tool_result is not None:
        icon = "✗" if entry.is_error else "✓"
        result_preview = entry.tool_result.split("\n")[0][:80]
        if len(entry.tool_result) > 80:
            result_preview += "..."
        return f"   {icon} {result_preview}"

    if entry.text_response:
        # Format as Claude's response
        response_preview = entry.text_response[:200]
        if len(entry.text_response) > 200:
            response_preview += "..."
        return f"💬 {response_preview}"

    if entry.user_message:
        msg_preview = entry.user_message[:100]
        if len(entry.user_message) > 100:
            msg_preview += "..."
        return f"👤 {msg_preview}"

    return None


def format_activity(entries: list[LogEntry]) -> str:
    """Format a list of log entries into a displayable string."""
    lines = []
    for entry in entries:
        formatted = format_entry(entry)
        if formatted:
            lines.append(formatted)
    return "\n".join(lines)
