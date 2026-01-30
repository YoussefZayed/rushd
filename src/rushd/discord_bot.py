"""Discord bot integration for rushd."""

import asyncio
import hashlib
import time
from typing import Optional

import discord

from .config import ConfigManager, DiscordConfig, DiscordChannels
from .logs import LogEntry, ActivityState
from .manager import ClaudeInstanceManager


def truncate(text: str, max_len: int) -> str:
    """Truncate text with ellipsis if too long."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def split_message(text: str, max_len: int) -> list[str]:
    """Split message into chunks respecting Discord's limit."""
    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, max_len)
        if split_at == -1:
            split_at = max_len
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks


def hash_entry(entry: LogEntry) -> str:
    """Create unique hash for a log entry using UUID."""
    # UUID is unique per entry, making this reliable
    if entry.uuid:
        return entry.uuid
    # Fallback for entries without UUID
    content = f"{entry.timestamp}:{entry.type}:{entry.tool_name}"
    return hashlib.md5(content.encode()).hexdigest()[:16]


class RushdDiscordBot(discord.Client):
    """Discord bot that bridges rushd primary instance with Discord."""

    CHANNEL_SUFFIXES = {
        "activity": "activity",
        "responses": "responses",
        "status": "status",
        "commands": "commands",
        "live_view": "live-view",
    }

    def __init__(
        self,
        manager: ClaudeInstanceManager,
        config: DiscordConfig,
        config_manager: ConfigManager,
        primary_name: str,
    ):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.guilds = True
        super().__init__(intents=intents)

        self.manager = manager
        self.config = config
        self.config_manager = config_manager
        self.primary_name = primary_name
        self.seen_entries: set[str] = set()
        self.last_status: str = "unknown"
        self._clearing: bool = False  # Flag to pause monitor during /clear
        self._awaiting_plan_approval: bool = False  # Flag when ExitPlanMode was called
        self._live_view_message_id: Optional[int] = None
        self._last_live_view_update: float = 0

    # Keywords that indicate plan approval (case-insensitive)
    APPROVAL_KEYWORDS = {"yes", "y", "approve", "ok", "proceed", "lgtm", "looks good", "go ahead", "approved"}

    def _get_channel_name(self, suffix: str) -> str:
        """Generate channel name using primary instance name."""
        return f"{self.primary_name}-{suffix}"

    async def on_ready(self):
        print(f"Discord bot connected as {self.user}", flush=True)
        await self.ensure_channels_exist()
        await self._initialize_seen_entries()
        self.loop.create_task(self.monitor_primary())

    async def _handle_clear_command(self, message: discord.Message):
        """Handle /clear command - destroy and recreate primary instance."""
        print(f"[Discord] Processing /clear command", flush=True)

        # Pause monitor loop during clear operation
        self._clearing = True

        try:
            # Notify start
            await message.add_reaction("🔄")
            if self.config.channels.status:
                status_ch = self.get_channel(self.config.channels.status)
                if status_ch:
                    await status_ch.send("🔄 Clearing primary instance...")

            # Stop the primary instance
            self.manager.stop_instance(self.primary_name, force=True)
            print(f"[Discord] Stopped primary instance", flush=True)

            # Remove old instance from store to prevent duplicates
            self.manager.remove_instance(self.primary_name)
            print(f"[Discord] Removed old primary from store", flush=True)

            # Get primary config for recreation
            from .config import ConfigManager
            config_mgr = ConfigManager()
            primary_config = config_mgr.get_primary()

            # Recreate the instance
            instance = self.manager.start_instance(
                name=primary_config.name,
                working_dir=primary_config.working_dir,
                model=primary_config.model,
                auto_approve=primary_config.auto_approve,
            )
            print(f"[Discord] Recreated primary instance: {instance.id}", flush=True)

            # Clear seen entries
            self.seen_entries.clear()
            print(f"[Discord] Cleared seen entries", flush=True)

            # Wait for new instance to fully initialize
            await asyncio.sleep(3)

            # Mark a large number of entries as seen to catch ALL old messages
            try:
                entries = self.manager.get_activity(self.primary_name, last_n=500)
                for entry in entries:
                    self.seen_entries.add(hash_entry(entry))
                print(f"[Discord] Marked {len(self.seen_entries)} entries as seen after clear", flush=True)
            except Exception as e:
                print(f"[Discord] Error marking entries after clear: {e}", flush=True)

            # Resume monitor loop
            self._clearing = False
            print(f"[Discord] Clear complete, resuming monitor", flush=True)

            # Notify completion
            await message.remove_reaction("🔄", self.user)
            await message.add_reaction("✅")
            if self.config.channels.status:
                status_ch = self.get_channel(self.config.channels.status)
                if status_ch:
                    await status_ch.send("✅ Primary instance cleared and recreated!")

        except Exception as e:
            self._clearing = False  # Resume monitor even on error
            print(f"[Discord] Error in /clear: {e}", flush=True)
            await message.add_reaction("❌")
            await message.reply(f"Failed to clear instance: {e}")

    async def _initialize_seen_entries(self):
        """Mark all existing log entries as seen to avoid replaying history."""
        try:
            # Refresh to get current instance state
            self.manager.refresh_statuses()
            entries = self.manager.get_activity(self.primary_name, last_n=100)
            for entry in entries:
                self.seen_entries.add(hash_entry(entry))
            print(f"Initialized {len(self.seen_entries)} existing entries as seen", flush=True)
        except Exception as e:
            import traceback
            print(f"Error initializing seen entries: {e}", flush=True)
            traceback.print_exc()

    async def ensure_channels_exist(self):
        """Create channels if they don't exist, save IDs to config."""
        if not self.config.guild_id:
            print("Warning: guild_id not set, cannot auto-create channels")
            return

        guild = self.get_guild(self.config.guild_id)
        if not guild:
            print(f"Warning: Could not find guild {self.config.guild_id}")
            return

        # Find or create category using primary name
        category_name = self.primary_name
        category = discord.utils.get(guild.categories, name=category_name)
        if not category:
            print(f"Creating category: {category_name}")
            category = await guild.create_category(category_name)

        # Check/create each channel
        channels_updated = False
        for key, suffix in self.CHANNEL_SUFFIXES.items():
            channel_name = self._get_channel_name(suffix)
            current_id = getattr(self.config.channels, key)

            # Check if channel exists by ID
            if current_id:
                existing = guild.get_channel(current_id)
                if existing:
                    continue

            # Check if channel exists by name in category
            existing = discord.utils.get(category.text_channels, name=channel_name)
            if existing:
                setattr(self.config.channels, key, existing.id)
                channels_updated = True
                print(f"Found existing channel: #{channel_name} ({existing.id})")
                continue

            # Create the channel
            print(f"Creating channel: #{channel_name}")
            new_channel = await guild.create_text_channel(
                channel_name,
                category=category,
                topic=self._get_channel_topic(key),
            )
            setattr(self.config.channels, key, new_channel.id)
            channels_updated = True

        # Save updated config with channel IDs
        if channels_updated:
            full_config = self.config_manager.load()
            full_config.discord.channels = self.config.channels
            self.config_manager.save(full_config)
            print("Channel IDs saved to config")

    def _get_channel_topic(self, channel_key: str) -> str:
        topics = {
            "activity": "Full activity stream from Claude (thinking, tools, results)",
            "responses": "Claude's text responses only",
            "status": "Status notifications (working, idle, done)",
            "commands": "Send commands to Claude here",
            "live_view": "Live view of Claude's activity (auto-updating)",
        }
        return topics.get(channel_key, "rushd channel")

    async def update_live_view(self):
        """Update the live view message with current activity."""
        if not self.config.channels.live_view:
            return
        channel = self.get_channel(self.config.channels.live_view)
        if not channel:
            return

        # Get formatted activity
        output = self.manager.get_activity_formatted(self.primary_name, last_n=30)
        content = f"```\n{output[:1900]}\n```"

        try:
            if self._live_view_message_id:
                # Edit existing message
                msg = await channel.fetch_message(self._live_view_message_id)
                await msg.edit(content=content)
            else:
                # Create initial message
                msg = await channel.send(content)
                self._live_view_message_id = msg.id
        except discord.NotFound:
            # Message was deleted, create new one
            msg = await channel.send(content)
            self._live_view_message_id = msg.id
        except Exception as e:
            print(f"[LiveView] Error updating live view: {e}", flush=True)

    async def monitor_primary(self):
        """Poll primary instance and dispatch to appropriate channels."""
        print(f"Starting monitor loop for '{self.primary_name}'", flush=True)
        poll_count = 0
        while True:
            try:
                # Skip processing during /clear operation
                if self._clearing:
                    await asyncio.sleep(self.config.poll_interval)
                    continue

                poll_count += 1

                # Refresh instance statuses to get current state
                self.manager.refresh_statuses()

                # Debug: check why is_primary_running might fail
                inst = self.manager.get_instance(self.primary_name)
                if inst:
                    tmux_exists = self.manager.tmux.window_exists(inst.tmux_window)
                    if poll_count % 15 == 0:
                        print(f"[Monitor] Instance found: status={inst.status}, tmux_window={inst.tmux_window}, tmux_exists={tmux_exists}", flush=True)
                else:
                    if poll_count % 15 == 0:
                        print(f"[Monitor] No instance found for '{self.primary_name}'", flush=True)

                is_running = self.manager.is_primary_running(self.primary_name)
                if not is_running:
                    if poll_count % 30 == 0:  # Log every 60 seconds (30 * 2s)
                        print(f"[Monitor] Primary not running (is_running={is_running}), waiting...", flush=True)
                    await asyncio.sleep(self.config.poll_interval)
                    continue

                entries = self.manager.get_activity(self.primary_name, last_n=20)
                if poll_count % 15 == 0:  # Log every 30 seconds
                    print(f"[Monitor] Poll #{poll_count}: {len(entries)} entries, {len(self.seen_entries)} seen", flush=True)
                activity_state = self.manager.get_activity_state(self.primary_name)

                for entry in entries:
                    entry_hash = hash_entry(entry)
                    if entry_hash in self.seen_entries:
                        continue
                    self.seen_entries.add(entry_hash)

                    print(f"[Monitor] New entry: type={entry.type}, tool={entry.tool_name}, has_text={bool(entry.text_response)}, has_thinking={bool(entry.thinking)}", flush=True)

                    await self.send_to_activity(entry)

                    if entry.text_response:
                        await self.send_to_responses(entry.text_response)

                new_status = activity_state.status
                old_status = self.last_status

                if new_status != old_status:
                    print(f"[Monitor] Status changed: {old_status} -> {new_status}", flush=True)
                    # Reset plan approval flag only when transitioning FROM idle to active
                    # (This means user approved and Claude started implementation)
                    if (old_status == "idle" and
                        new_status in ("thinking", "tool_use", "running") and
                        self._awaiting_plan_approval):
                        self._awaiting_plan_approval = False
                        print(f"[Discord] Plan approved, Claude is working", flush=True)
                    await self.send_status_update(new_status, activity_state)
                    self.last_status = new_status

                # Update live view every 5 seconds when not idle
                now = time.time()
                if new_status != "idle":
                    if now - self._last_live_view_update >= 5:
                        await self.update_live_view()
                        self._last_live_view_update = now
                elif new_status == "idle" and old_status != "idle":
                    # Final update when transitioning to idle
                    await self.update_live_view()
                    self._last_live_view_update = now

            except Exception as e:
                print(f"Monitor error: {e}", flush=True)
                import traceback
                traceback.print_exc()

            await asyncio.sleep(self.config.poll_interval)

    async def send_to_activity(self, entry: LogEntry):
        """Send formatted activity to activity channel."""
        if not self.config.channels.activity:
            print(f"[Send] No activity channel configured", flush=True)
            return
        channel = self.get_channel(self.config.channels.activity)
        if not channel:
            print(f"[Send] Could not get activity channel {self.config.channels.activity}", flush=True)
            return

        sent_count = 0
        try:
            if entry.thinking:
                await channel.send(
                    f"🤔 *thinking...*\n```\n{truncate(entry.thinking, 1500)}\n```"
                )
                sent_count += 1
            if entry.tool_name:
                msg = f"🔧 **{entry.tool_name}**"
                if entry.tool_input:
                    msg += f"\n```json\n{truncate(str(entry.tool_input), 500)}\n```"
                await channel.send(msg)
                sent_count += 1

                # Special handling for tools that need user input
                if entry.tool_name == "ExitPlanMode":
                    await self._notify_plan_approval_needed()
                    self._awaiting_plan_approval = True
                    print(f"[Discord] Now awaiting plan approval", flush=True)
                elif entry.tool_name == "AskUserQuestion":
                    await self._notify_question_asked(entry.tool_input)
            if entry.tool_result:
                await channel.send(
                    f"📋 Result:\n```\n{truncate(entry.tool_result, 1500)}\n```"
                )
                sent_count += 1
            if entry.text_response:
                await channel.send(f"💬 {truncate(entry.text_response, 1900)}")
                sent_count += 1
            if sent_count > 0:
                print(f"[Send] Sent {sent_count} messages to activity channel", flush=True)
        except Exception as e:
            print(f"[Send] Error sending to activity: {e}", flush=True)

    async def _notify_plan_approval_needed(self):
        """Notify user that Claude is waiting for plan approval."""
        if not self.config.channels.responses:
            return
        channel = self.get_channel(self.config.channels.responses)
        if not channel:
            return
        try:
            await channel.send(
                "📋 **Plan Ready for Review**\n"
                "Claude has finished planning and is waiting for your approval.\n"
                "Reply with `yes`/`approve` to proceed, or provide feedback to modify the plan."
            )
            print(f"[Send] Sent plan approval notification", flush=True)
        except Exception as e:
            print(f"[Send] Error sending plan notification: {e}", flush=True)

    async def _notify_question_asked(self, tool_input: dict | None):
        """Notify user that Claude is asking a question."""
        if not self.config.channels.responses:
            return
        channel = self.get_channel(self.config.channels.responses)
        if not channel:
            return
        try:
            msg = "❓ **Claude is asking a question**\n"
            if tool_input and isinstance(tool_input, dict):
                questions = tool_input.get("questions", [])
                for q in questions:
                    if isinstance(q, dict):
                        question_text = q.get("question", "")
                        options = q.get("options", [])
                        if question_text:
                            msg += f"\n**{question_text}**\n"
                        for i, opt in enumerate(options, 1):
                            if isinstance(opt, dict):
                                label = opt.get("label", f"Option {i}")
                                desc = opt.get("description", "")
                                msg += f"{i}. **{label}** - {desc}\n"
                msg += "\nReply with your choice (number or text)."
            await channel.send(truncate(msg, 1900))
            print(f"[Send] Sent question notification", flush=True)
        except Exception as e:
            print(f"[Send] Error sending question notification: {e}", flush=True)

    async def send_to_responses(self, text: str):
        """Send Claude's response to responses channel."""
        if not self.config.channels.responses:
            print(f"[Send] No responses channel configured", flush=True)
            return
        channel = self.get_channel(self.config.channels.responses)
        if not channel:
            print(f"[Send] Could not get responses channel {self.config.channels.responses}", flush=True)
            return
        try:
            chunks = split_message(text, 1900)
            for chunk in chunks:
                await channel.send(chunk)
            print(f"[Send] Sent response to responses channel ({len(chunks)} chunks)", flush=True)
        except Exception as e:
            print(f"[Send] Error sending to responses: {e}", flush=True)

    async def send_status_update(self, status: str, activity: ActivityState):
        """Send status change notification."""
        if not self.config.channels.status:
            return
        channel = self.get_channel(self.config.channels.status)
        if not channel:
            return

        status_messages = {
            "thinking": "🤔 Claude is thinking...",
            "tool_use": f"🔧 Claude is using **{activity.tool_name or 'a tool'}**",
            "running": "⚡ Claude is working...",
            "idle": f"💤 Claude is idle ({activity.seconds_since_activity:.0f}s)",
            "unknown": "❓ Status unknown",
        }
        await channel.send(status_messages.get(status, f"Status: {status}"))

    async def on_message(self, message: discord.Message):
        """Handle incoming Discord messages."""
        if message.author == self.user:
            return

        # Accept commands from both commands and responses channels
        allowed_channels = [self.config.channels.commands, self.config.channels.responses]
        if message.channel.id not in allowed_channels:
            return

        if message.author.name not in self.config.allowed_users:
            print(f"[Discord] Rejected message from '{message.author.name}' - not in allowed_users", flush=True)
            await message.add_reaction("🚫")
            return

        print(f"[Discord] Received command from {message.author.name}: {message.content[:50]}...", flush=True)

        content = message.content.strip()

        # Handle /clear command - destroy and recreate primary instance
        if content.lower() == "/clear":
            await self._handle_clear_command(message)
            return

        # If awaiting plan approval, distinguish approval from feedback
        if self._awaiting_plan_approval:
            if content.lower() in self.APPROVAL_KEYWORDS:
                # Approval - press "2" to select approve option
                print(f"[Discord] Detected plan approval keyword: {content}", flush=True)
                success = self.manager.send_key(self.primary_name, "2")
            else:
                # Feedback - navigate to modify option (Down×3), then send text
                print(f"[Discord] Detected plan feedback, navigating to modify option", flush=True)
                for _ in range(3):
                    self.manager.send_key(self.primary_name, "Down")
                    await asyncio.sleep(0.1)
                await asyncio.sleep(0.2)
                # Send the feedback text
                success = self.manager.send_message(self.primary_name, content)
        else:
            success = self.manager.send_message(self.primary_name, content)

        if success:
            await message.add_reaction("✅")
            if self.config.channels.status:
                status_ch = self.get_channel(self.config.channels.status)
                if status_ch:
                    await status_ch.send(
                        f"📨 Received command from {message.author.name}"
                    )
        else:
            await message.add_reaction("❌")
            await message.reply(
                "Failed to send to Claude. Is the primary instance running?"
            )


def run_discord_bot(
    manager: ClaudeInstanceManager,
    config: DiscordConfig,
    config_manager: ConfigManager,
    primary_name: str,
    token: str,
):
    """Run the Discord bot (blocking)."""
    bot = RushdDiscordBot(manager, config, config_manager, primary_name)
    bot.run(token)
