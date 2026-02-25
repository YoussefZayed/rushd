"""Channel-to-instance routing for Discord bot."""

from typing import Optional

import discord

from ..config import ConfigManager, DiscordConfig


# Channel suffixes for per-instance categories
CHANNEL_SUFFIXES = {
    "activity": "activity",
    "responses": "responses",
    "status": "status",
    "commands": "commands",
    "live_view": "live-view",
}

CHANNEL_TOPICS = {
    "activity": "Full activity stream from Claude (thinking, tools, results)",
    "responses": "Claude's text responses only",
    "status": "Status notifications (working, idle, done)",
    "commands": "Send commands to Claude here",
    "live_view": "Live view of Claude's activity (auto-updating)",
}


class InstanceChannels:
    """Channel IDs for a single instance."""

    def __init__(self):
        self.activity: Optional[int] = None
        self.responses: Optional[int] = None
        self.status: Optional[int] = None
        self.commands: Optional[int] = None
        self.live_view: Optional[int] = None

    def get(self, key: str) -> Optional[int]:
        return getattr(self, key, None)

    def set(self, key: str, value: int):
        setattr(self, key, value)

    def all_ids(self) -> list[int]:
        """Return all non-None channel IDs."""
        return [
            v for v in [self.activity, self.responses, self.status, self.commands, self.live_view]
            if v is not None
        ]


class ChannelRouter:
    """Maps Discord channels to rushd instances."""

    def __init__(self, config: DiscordConfig, config_manager: ConfigManager):
        self.config = config
        self.config_manager = config_manager
        # instance_name -> InstanceChannels
        self._instances: dict[str, InstanceChannels] = {}
        # channel_id -> (instance_name, channel_purpose)
        self._channel_map: dict[int, tuple[str, str]] = {}

    def register_instance(self, instance_name: str, channels: InstanceChannels):
        """Register channel mappings for an instance."""
        self._instances[instance_name] = channels
        for key in CHANNEL_SUFFIXES:
            channel_id = channels.get(key)
            if channel_id:
                self._channel_map[channel_id] = (instance_name, key)

    def get_instance_for_channel(self, channel_id: int) -> Optional[str]:
        """Determine which instance a channel message should route to."""
        if channel_id in self._channel_map:
            return self._channel_map[channel_id][0]
        return None

    def get_channel_purpose(self, channel_id: int) -> Optional[str]:
        """Get the purpose of a channel (activity, responses, etc.)."""
        if channel_id in self._channel_map:
            return self._channel_map[channel_id][1]
        return None

    def is_command_channel(self, channel_id: int) -> bool:
        """Check if a channel accepts commands."""
        if channel_id in self._channel_map:
            _, purpose = self._channel_map[channel_id]
            return purpose in ("commands", "responses")
        return False

    def get_instance_channels(self, instance_name: str) -> Optional[InstanceChannels]:
        """Get the channels for an instance."""
        return self._instances.get(instance_name)

    def get_channel_name(self, instance_name: str, suffix: str) -> str:
        """Generate channel name for an instance."""
        return f"{instance_name}-{suffix}"

    async def ensure_channels_for_instance(
        self,
        guild: discord.Guild,
        instance_name: str,
    ) -> InstanceChannels:
        """Create or find channels for an instance, return InstanceChannels."""
        # Find or create category
        category = discord.utils.get(guild.categories, name=instance_name)
        if not category:
            print(f"Creating category: {instance_name}")
            category = await guild.create_category(instance_name)

        channels = self._instances.get(instance_name, InstanceChannels())

        for key, suffix in CHANNEL_SUFFIXES.items():
            channel_name = self.get_channel_name(instance_name, suffix)
            current_id = channels.get(key)

            # Check if channel exists by ID
            if current_id:
                existing = guild.get_channel(current_id)
                if existing:
                    continue

            # Check if channel exists by name in category
            existing = discord.utils.get(category.text_channels, name=channel_name)
            if existing:
                channels.set(key, existing.id)
                print(f"Found existing channel: #{channel_name} ({existing.id})")
                continue

            # Create the channel
            print(f"Creating channel: #{channel_name}")
            new_channel = await guild.create_text_channel(
                channel_name,
                category=category,
                topic=CHANNEL_TOPICS.get(key, "rushd channel"),
            )
            channels.set(key, new_channel.id)

        self.register_instance(instance_name, channels)
        return channels
