"""Notification storage for rushd worker-to-primary communication."""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from .models import Notification, NotificationStatus


class NotificationStore:
    """Manages notification storage for worker-to-primary communication."""

    def __init__(
        self,
        store_dir: Optional[Path] = None,
        retention_days: int = 7,
    ):
        self.store_dir = store_dir or Path.home() / ".rushd" / "notifications"
        self.retention_days = retention_days

        # Ensure store directory exists
        self.store_dir.mkdir(parents=True, exist_ok=True)

    def _get_filename(self, notification: Notification) -> str:
        """Generate filename: {worker_name}_{worker_id}_{timestamp}.json"""
        timestamp = notification.created_at.strftime("%Y%m%d_%H%M%S")
        # Sanitize worker name for filesystem
        safe_name = re.sub(r"[^\w\-]", "_", notification.worker_name or "unknown")
        return f"{safe_name}_{notification.worker_id}_{timestamp}.json"

    def save(self, notification: Notification) -> Path:
        """
        Save a notification to disk.

        Args:
            notification: The notification to save

        Returns:
            Path to the saved notification file
        """
        filename = self._get_filename(notification)
        filepath = self.store_dir / filename

        data = notification.model_dump(mode="json")
        # Convert datetime to ISO format strings
        if data.get("created_at"):
            data["created_at"] = notification.created_at.isoformat()
        if data.get("delivered_at") and notification.delivered_at:
            data["delivered_at"] = notification.delivered_at.isoformat()

        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)

        return filepath

    def mark_delivered(self, filepath: Path) -> bool:
        """
        Mark a notification as delivered.

        Args:
            filepath: Path to the notification file

        Returns:
            True if successfully updated
        """
        if not filepath.exists():
            return False

        try:
            with open(filepath, "r") as f:
                data = json.load(f)

            data["delivered"] = True
            data["delivered_at"] = datetime.now().isoformat()

            with open(filepath, "w") as f:
                json.dump(data, f, indent=2)

            return True
        except (json.JSONDecodeError, OSError):
            return False

    def _load_notification(self, filepath: Path) -> Optional[Notification]:
        """Load a notification from a file."""
        try:
            with open(filepath, "r") as f:
                data = json.load(f)

            # Parse datetime fields
            if data.get("created_at"):
                data["created_at"] = datetime.fromisoformat(data["created_at"])
            if data.get("delivered_at"):
                data["delivered_at"] = datetime.fromisoformat(data["delivered_at"])

            return Notification(**data)
        except (json.JSONDecodeError, OSError, ValueError):
            return None

    def list_notifications(
        self,
        worker_id: Optional[str] = None,
        undelivered_only: bool = False,
        limit: int = 100,
    ) -> list[Notification]:
        """
        List notifications, optionally filtered.

        Args:
            worker_id: Filter by worker instance ID
            undelivered_only: Only return undelivered notifications
            limit: Maximum number of notifications to return

        Returns:
            List of notifications, sorted by created_at descending
        """
        if not self.store_dir.exists():
            return []

        notifications: list[Notification] = []

        # Get all JSON files, sorted by modification time (newest first)
        files = sorted(
            self.store_dir.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        for filepath in files:
            if len(notifications) >= limit:
                break

            notification = self._load_notification(filepath)
            if not notification:
                continue

            # Apply filters
            if worker_id and notification.worker_id != worker_id:
                continue
            if undelivered_only and notification.delivered:
                continue

            notifications.append(notification)

        return notifications

    def cleanup_old_notifications(self) -> int:
        """
        Delete notification files older than retention_days.

        Returns:
            Count of deleted files
        """
        if not self.store_dir.exists():
            return 0

        cutoff = datetime.now() - timedelta(days=self.retention_days)
        count = 0

        for filepath in self.store_dir.glob("*.json"):
            try:
                mtime = datetime.fromtimestamp(filepath.stat().st_mtime)
                if mtime < cutoff:
                    filepath.unlink()
                    count += 1
            except OSError:
                pass

        return count

    def get_by_id(self, notification_id: str) -> Optional[Notification]:
        """
        Find a notification by its ID.

        Args:
            notification_id: The notification UUID to find

        Returns:
            The notification if found, None otherwise
        """
        if not self.store_dir.exists():
            return None

        for filepath in self.store_dir.glob("*.json"):
            notification = self._load_notification(filepath)
            if notification and notification.id == notification_id:
                return notification

        return None
