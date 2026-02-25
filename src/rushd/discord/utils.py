"""Shared utilities for Discord bot."""

import hashlib

from ..logs import LogEntry


def truncate(text: str, max_len: int) -> str:
    """Truncate text with ellipsis if too long."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def split_message(text: str, max_len: int) -> list[str]:
    """Split message into chunks at sentence/word boundaries."""
    if not text:
        return [""]
    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        split_at = max_len
        for sep in [". ", ".\n", "! ", "? ", "\n\n", "\n", " "]:
            pos = text.rfind(sep, 0, max_len)
            if pos > max_len // 2:
                split_at = pos + len(sep.rstrip())
                break
        chunks.append(text[:split_at].rstrip())
        text = text[split_at:].lstrip()
    return chunks if chunks else [""]


def hash_entry(entry: LogEntry) -> str:
    """Create unique hash for a log entry using UUID."""
    if entry.uuid:
        return entry.uuid
    content = f"{entry.timestamp}:{entry.type}:{entry.tool_name}"
    return hashlib.md5(content.encode()).hexdigest()[:16]
