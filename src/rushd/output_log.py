"""Output logging for rushd instances."""

import hashlib
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional


class OutputLogWriter:
    """Manages log file for a single instance."""

    def __init__(
        self,
        log_dir: Path,
        instance_id: str,
        instance_name: Optional[str],
        max_file_size_mb: int = 50,
    ):
        self.log_dir = log_dir
        self.instance_id = instance_id
        self.instance_name = instance_name or instance_id
        self.max_file_size_bytes = max_file_size_mb * 1024 * 1024
        self._last_content_hash: Optional[str] = None
        self._current_log_file: Optional[Path] = None

        # Ensure log directory exists
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def _get_log_filename(self) -> str:
        """Generate log filename: {name}_{id}_{date}.log"""
        date_str = datetime.now().strftime("%Y-%m-%d")
        # Sanitize name for filesystem
        safe_name = re.sub(r"[^\w\-]", "_", self.instance_name)
        return f"{safe_name}_{self.instance_id}_{date_str}.log"

    def _get_current_log_file(self) -> Path:
        """Get current log file, creating new one if needed for rotation."""
        filename = self._get_log_filename()
        log_file = self.log_dir / filename

        # Check if we need to rotate (file too large)
        if log_file.exists() and log_file.stat().st_size >= self.max_file_size_bytes:
            # Add timestamp suffix for rotation
            timestamp = datetime.now().strftime("%H%M%S")
            base = filename.rsplit(".", 1)[0]
            filename = f"{base}_{timestamp}.log"
            log_file = self.log_dir / filename

        self._current_log_file = log_file
        return log_file

    def write_output(self, content: str) -> bool:
        """
        Write timestamped output to log, skipping if content unchanged.

        Returns True if content was written, False if skipped (duplicate).
        """
        if not content.strip():
            return False

        # Hash to detect duplicates
        content_hash = hashlib.md5(content.encode()).hexdigest()
        if content_hash == self._last_content_hash:
            return False

        self._last_content_hash = content_hash

        # Prepare timestamped lines
        timestamp = datetime.now().isoformat()
        lines = content.split("\n")
        timestamped_lines = [f"[{timestamp}] {line}" for line in lines]

        # Write to log file
        log_file = self._get_current_log_file()
        with open(log_file, "a") as f:
            f.write("\n".join(timestamped_lines) + "\n")

        return True

    def get_log_files(self) -> list[Path]:
        """Get all log files for this instance, sorted by modification time."""
        pattern = f"*_{self.instance_id}_*.log"
        files = list(self.log_dir.glob(pattern))
        return sorted(files, key=lambda p: p.stat().st_mtime)

    def read_logs(self, lines: int = 100) -> str:
        """Read last N lines across all log files for this instance."""
        log_files = self.get_log_files()
        if not log_files:
            return ""

        all_lines: list[str] = []
        # Read from newest to oldest until we have enough lines
        for log_file in reversed(log_files):
            with open(log_file, "r") as f:
                file_lines = f.readlines()
            all_lines = file_lines + all_lines
            if len(all_lines) >= lines:
                break

        # Return last N lines
        return "".join(all_lines[-lines:])

    def clear_logs(self) -> int:
        """Delete all logs for this instance. Returns count of deleted files."""
        log_files = self.get_log_files()
        count = 0
        for f in log_files:
            try:
                f.unlink()
                count += 1
            except OSError:
                pass
        self._last_content_hash = None
        return count


class OutputLogManager:
    """Manages output logs for all instances."""

    def __init__(self, log_dir: Path, max_file_size_mb: int = 50, retention_days: int = 7):
        self.log_dir = log_dir
        self.max_file_size_mb = max_file_size_mb
        self.retention_days = retention_days
        self._writers: dict[str, OutputLogWriter] = {}

        # Ensure log directory exists
        self.log_dir.mkdir(parents=True, exist_ok=True)

    def get_writer(self, instance_id: str, name: Optional[str] = None) -> OutputLogWriter:
        """Get or create a writer for an instance."""
        if instance_id not in self._writers:
            self._writers[instance_id] = OutputLogWriter(
                log_dir=self.log_dir,
                instance_id=instance_id,
                instance_name=name,
                max_file_size_mb=self.max_file_size_mb,
            )
        return self._writers[instance_id]

    def cleanup_old_logs(self) -> int:
        """Delete log files older than retention_days. Returns count deleted."""
        if not self.log_dir.exists():
            return 0

        cutoff = datetime.now() - timedelta(days=self.retention_days)
        count = 0

        for log_file in self.log_dir.glob("*.log"):
            try:
                mtime = datetime.fromtimestamp(log_file.stat().st_mtime)
                if mtime < cutoff:
                    log_file.unlink()
                    count += 1
            except OSError:
                pass

        return count

    def list_all_logs(self) -> list[tuple[Path, int]]:
        """List all log files with sizes. Returns list of (path, size_bytes)."""
        if not self.log_dir.exists():
            return []

        result = []
        for log_file in sorted(self.log_dir.glob("*.log")):
            try:
                size = log_file.stat().st_size
                result.append((log_file, size))
            except OSError:
                pass
        return result

    def search_logs(self, pattern: str, max_results: int = 100) -> list[tuple[Path, int, str]]:
        """
        Search across all logs with regex pattern.

        Returns list of (file_path, line_number, line_content).
        """
        if not self.log_dir.exists():
            return []

        results: list[tuple[Path, int, str]] = []
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except re.error:
            # Invalid regex, treat as literal string
            regex = re.compile(re.escape(pattern), re.IGNORECASE)

        for log_file in sorted(self.log_dir.glob("*.log")):
            try:
                with open(log_file, "r") as f:
                    for line_num, line in enumerate(f, 1):
                        if regex.search(line):
                            results.append((log_file, line_num, line.rstrip()))
                            if len(results) >= max_results:
                                return results
            except OSError:
                pass

        return results

    def get_total_size(self) -> int:
        """Get total size of all log files in bytes."""
        total = 0
        for _, size in self.list_all_logs():
            total += size
        return total

    def clear_all_logs(self) -> int:
        """Delete all log files. Returns count deleted."""
        if not self.log_dir.exists():
            return 0

        count = 0
        for log_file in self.log_dir.glob("*.log"):
            try:
                log_file.unlink()
                count += 1
            except OSError:
                pass

        self._writers.clear()
        return count
