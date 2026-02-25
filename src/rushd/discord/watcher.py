"""Filesystem watcher for Claude Code log files.

Replaces polling with near-instant detection of log changes (~200ms).
Falls back to polling if watchdog events don't fire reliably.
"""

import asyncio
import threading
from pathlib import Path
from typing import Callable, Awaitable, Optional

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler, FileModifiedEvent


class _LogFileHandler(FileSystemEventHandler):
    """Watches for JSONL log file modifications."""

    def __init__(
        self,
        callback: Callable[[], Awaitable[None]],
        loop: asyncio.AbstractEventLoop,
        debounce_ms: int = 100,
    ):
        self.callback = callback
        self.loop = loop
        self.debounce_ms = debounce_ms
        self._pending: Optional[asyncio.TimerHandle] = None

    def on_modified(self, event):
        if not isinstance(event, FileModifiedEvent):
            return
        if not event.src_path.endswith(".jsonl"):
            return

        # Debounce: cancel any pending callback, schedule a new one
        def schedule():
            asyncio.run_coroutine_threadsafe(self.callback(), self.loop)

        if self._pending:
            self._pending.cancel()
        self._pending = self.loop.call_later(self.debounce_ms / 1000, schedule)


class LogWatcher:
    """Watches Claude Code log directories for changes.

    Usage:
        watcher = LogWatcher()
        watcher.start()
        watcher.watch("primary", Path("/home/admin/.claude/projects/..."), callback)
        # ...
        watcher.stop()
    """

    def __init__(self):
        self._observer = Observer()
        self._watches: dict[str, object] = {}  # instance_name -> watch handle
        self._started = False

    def start(self):
        """Start the filesystem observer thread."""
        if not self._started:
            self._observer.start()
            self._started = True

    def stop(self):
        """Stop the filesystem observer and wait for thread to finish."""
        if self._started:
            self._observer.stop()
            self._observer.join(timeout=5)
            self._started = False

    def watch(
        self,
        instance_name: str,
        log_dir: Path,
        callback: Callable[[], Awaitable[None]],
        loop: Optional[asyncio.AbstractEventLoop] = None,
        debounce_ms: int = 100,
    ):
        """Start watching a log directory for an instance.

        Args:
            instance_name: Name to track this watch by
            log_dir: Directory containing JSONL log files
            callback: Async function to call when changes detected
            loop: Event loop to schedule callback on (defaults to running loop)
            debounce_ms: Debounce interval in milliseconds
        """
        if instance_name in self._watches:
            self.unwatch(instance_name)

        if not log_dir.exists():
            print(f"[Watcher] Log dir does not exist yet: {log_dir}", flush=True)
            return

        event_loop = loop or asyncio.get_event_loop()
        handler = _LogFileHandler(callback, event_loop, debounce_ms)
        watch = self._observer.schedule(handler, str(log_dir), recursive=False)
        self._watches[instance_name] = watch
        print(f"[Watcher] Watching '{instance_name}' at {log_dir}", flush=True)

    def unwatch(self, instance_name: str):
        """Stop watching an instance."""
        watch = self._watches.pop(instance_name, None)
        if watch:
            try:
                self._observer.unschedule(watch)
            except Exception:
                pass
            print(f"[Watcher] Unwatched '{instance_name}'", flush=True)

    def is_watching(self, instance_name: str) -> bool:
        """Check if an instance is being watched."""
        return instance_name in self._watches
