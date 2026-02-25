"""Backward-compatible shim — imports from rushd.discord package.

This module is kept for backward compatibility. All functionality has
moved to the rushd.discord package.
"""

# Re-export for backward compat
from .discord import run_discord_bot
from .discord.utils import truncate, split_message, hash_entry

__all__ = ["run_discord_bot", "truncate", "split_message", "hash_entry"]
