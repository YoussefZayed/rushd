"""JSON persistence for instance metadata."""

import fcntl
import json
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

from .models import InstanceMetadata, InstanceStore as StoreModel, InstanceStatus


class InstanceStore:
    """Manages persistence of instance metadata to ~/.rushd/instances.json."""

    def __init__(self, store_path: Optional[Path] = None):
        self.store_path = store_path or Path.home() / ".rushd" / "instances.json"
        self._lock_path = self.store_path.with_suffix(".lock")
        self._ensure_dir()

    def _ensure_dir(self) -> None:
        """Ensure the storage directory exists."""
        self.store_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _file_lock(self, exclusive: bool = True) -> Generator[None, None, None]:
        """
        Context manager for file locking to prevent concurrent access issues.

        Args:
            exclusive: If True, acquire exclusive (write) lock. If False, shared (read) lock.
        """
        self._ensure_dir()
        lock_file = open(self._lock_path, "w")
        try:
            lock_type = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
            fcntl.flock(lock_file.fileno(), lock_type)
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            lock_file.close()

    def _load_raw(self) -> StoreModel:
        """Load the store from disk (caller should hold lock if needed)."""
        if not self.store_path.exists():
            return StoreModel()
        try:
            with open(self.store_path, "r") as f:
                data = json.load(f)
            return StoreModel.model_validate(data)
        except (json.JSONDecodeError, IOError):
            return StoreModel()

    def _save_raw(self, store: StoreModel) -> None:
        """Save the store to disk (caller should hold lock if needed)."""
        self._ensure_dir()
        with open(self.store_path, "w") as f:
            json.dump(store.model_dump(mode="json"), f, indent=2, default=str)

    def load(self) -> dict[str, InstanceMetadata]:
        """Load all instances from storage."""
        with self._file_lock(exclusive=False):
            return self._load_raw().instances

    def save(self, instances: dict[str, InstanceMetadata]) -> None:
        """Save all instances to storage."""
        with self._file_lock(exclusive=True):
            store = self._load_raw()
            store.instances = instances
            self._save_raw(store)

    def find_by_name(self, name: str) -> Optional[InstanceMetadata]:
        """Find an instance by exact name match."""
        with self._file_lock(exclusive=False):
            store = self._load_raw()
            for inst in store.instances.values():
                if inst.name and inst.name == name:
                    return inst
            return None

    def add(self, instance: InstanceMetadata) -> None:
        """Add a new instance to storage. Raises ValueError if name already exists."""
        with self._file_lock(exclusive=True):
            if instance.name:
                store = self._load_raw()
                for inst in store.instances.values():
                    if inst.name and inst.name == instance.name:
                        raise ValueError(
                            f"Instance with name '{instance.name}' already exists (id: {inst.id})"
                        )
            store = self._load_raw()
            store.instances[instance.id] = instance
            self._save_raw(store)

    def update(self, instance_id: str, **updates) -> Optional[InstanceMetadata]:
        """Update an existing instance."""
        with self._file_lock(exclusive=True):
            store = self._load_raw()
            if instance_id not in store.instances:
                return None
            instance = store.instances[instance_id]
            updated_data = instance.model_dump()
            updated_data.update(updates)
            store.instances[instance_id] = InstanceMetadata.model_validate(updated_data)
            self._save_raw(store)
            return store.instances[instance_id]

    def remove(self, instance_id: str) -> bool:
        """Remove an instance from storage."""
        with self._file_lock(exclusive=True):
            store = self._load_raw()
            if instance_id not in store.instances:
                return False
            del store.instances[instance_id]
            self._save_raw(store)
            return True

    def get(self, instance_id: str) -> Optional[InstanceMetadata]:
        """Get an instance by ID."""
        with self._file_lock(exclusive=False):
            return self._load_raw().instances.get(instance_id)

    def list_all(self, include_stopped: bool = False) -> list[InstanceMetadata]:
        """List all instances, optionally including stopped ones."""
        with self._file_lock(exclusive=False):
            instances = list(self._load_raw().instances.values())
            if not include_stopped:
                instances = [i for i in instances if i.status != InstanceStatus.STOPPED]
            return sorted(instances, key=lambda x: x.created_at)

    def find_by_name_or_id(self, identifier: str) -> Optional[InstanceMetadata]:
        """Find an instance by name or ID (partial match supported)."""
        with self._file_lock(exclusive=False):
            store = self._load_raw()

            # Exact ID match
            if identifier in store.instances:
                return store.instances[identifier]

            # Partial ID match
            for inst_id, inst in store.instances.items():
                if inst_id.startswith(identifier):
                    return inst

            # Name match
            for inst in store.instances.values():
                if inst.name and inst.name == identifier:
                    return inst

            # Partial name match
            for inst in store.instances.values():
                if inst.name and identifier.lower() in inst.name.lower():
                    return inst

            return None

    def find_by_pane_id(self, pane_id: str) -> Optional[InstanceMetadata]:
        """Find an instance by its tmux pane ID."""
        with self._file_lock(exclusive=False):
            store = self._load_raw()
            for inst in store.instances.values():
                if inst.tmux_pane_id == pane_id:
                    return inst
            return None

    def get_session_name(self) -> str:
        """Get the tmux session name."""
        with self._file_lock(exclusive=False):
            return self._load_raw().session_name

    def clear_all(self) -> None:
        """Clear all instances from storage."""
        with self._file_lock(exclusive=True):
            store = self._load_raw()
            store.instances = {}
            self._save_raw(store)
