"""Main Discord bot for rushd using commands.Bot with slash command support."""

import asyncio
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

import discord
from discord.ext import commands as discord_commands

from ..commands import CommandHandler
from ..config import ConfigManager, DiscordConfig
from ..logs import LogEntry, ActivityState
from ..manager import ClaudeInstanceManager
from .embeds import (
    status_change_embed,
    success_embed,
    error_embed,
)
from .routing import ChannelRouter, InstanceChannels
from .utils import hash_entry, split_message, truncate


class RushdBot(discord_commands.Bot):
    """Discord bot with slash commands for full rushd control."""

    APPROVAL_KEYWORDS = {
        "yes", "y", "approve", "ok", "proceed",
        "lgtm", "looks good", "go ahead", "approved",
    }

    SCREENSHOT_DIR = Path.home() / ".rushd" / "screenshots"

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
        super().__init__(command_prefix="!", intents=intents)

        self.manager = manager
        self.discord_config = config
        self.config_manager = config_manager
        self.primary_name = primary_name
        self.cmd = CommandHandler(manager, config_manager)
        self.router = ChannelRouter(config, config_manager)

        # Per-instance monitoring state
        self.seen_entries: dict[str, set[str]] = {}  # instance_name -> set of hashes
        self.last_status: dict[str, str] = {}  # instance_name -> status string
        self.monitor_tasks: dict[str, asyncio.Task] = {}  # instance_name -> task

        # Per-instance state flags
        self._clearing: dict[str, bool] = {}
        self._awaiting_plan_approval: dict[str, bool] = {}
        self._live_view_message_ids: dict[str, int] = {}
        self._last_live_view_update: dict[str, float] = {}

    async def setup_hook(self):
        """Load cogs and sync slash commands."""
        await self.load_extension("rushd.discord.cogs.instances")
        await self.load_extension("rushd.discord.cogs.messaging")
        await self.load_extension("rushd.discord.cogs.approvals")

        # Sync commands to the guild for instant availability
        if self.discord_config.guild_id:
            guild = discord.Object(id=self.discord_config.guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            print(f"[Discord] Slash commands synced to guild {self.discord_config.guild_id}", flush=True)

    async def on_ready(self):
        print(f"Discord bot connected as {self.user}", flush=True)

        # Set up channels for primary instance
        if self.discord_config.guild_id:
            guild = self.get_guild(self.discord_config.guild_id)
            if guild:
                # Migrate legacy channels config to router
                channels = await self._ensure_primary_channels(guild)
                if channels:
                    self.router.register_instance(self.primary_name, channels)

        # Clean up old screenshots
        deleted = await self._cleanup_old_screenshots()
        if deleted > 0:
            print(f"[Discord] Cleaned up {deleted} old screenshots on startup", flush=True)

        # Initialize seen entries and start monitoring for primary
        await self._initialize_monitor(self.primary_name)

        # Also start monitors for any other running instances
        self.manager.refresh_statuses()
        for inst in self.manager.list_instances(include_stopped=False):
            if inst.name and inst.name != self.primary_name:
                instance_channels = self.router.get_instance_channels(inst.name)
                if instance_channels:
                    await self._initialize_monitor(inst.name)

    async def _ensure_primary_channels(self, guild: discord.Guild) -> Optional[InstanceChannels]:
        """Set up channels for the primary instance, migrating from legacy config."""
        channels = await self.router.ensure_channels_for_instance(guild, self.primary_name)

        # Save channel IDs back to config
        config = self.config_manager.load()
        config.discord.channels.activity = channels.activity
        config.discord.channels.responses = channels.responses
        config.discord.channels.status = channels.status
        config.discord.channels.commands = channels.commands
        config.discord.channels.live_view = channels.live_view
        self.config_manager.save(config)
        print("[Discord] Channel IDs saved to config", flush=True)

        return channels

    async def _initialize_monitor(self, instance_name: str):
        """Initialize seen entries and start monitoring for an instance."""
        if instance_name in self.monitor_tasks:
            return  # Already monitoring

        # Initialize seen entries
        self.seen_entries[instance_name] = set()
        self.last_status[instance_name] = "unknown"
        self._clearing[instance_name] = False
        self._awaiting_plan_approval[instance_name] = False
        self._last_live_view_update[instance_name] = 0

        try:
            self.manager.refresh_statuses()
            entries = self.manager.get_activity(instance_name, last_n=300)
            for entry in entries:
                self.seen_entries[instance_name].add(hash_entry(entry))
            print(
                f"[Discord] Initialized {len(self.seen_entries[instance_name])} "
                f"existing entries as seen for '{instance_name}'",
                flush=True,
            )
        except Exception as e:
            import traceback
            print(f"[Discord] Error initializing seen entries for '{instance_name}': {e}", flush=True)
            traceback.print_exc()

        # Start monitor task
        task = self.loop.create_task(self._monitor_instance(instance_name))
        self.monitor_tasks[instance_name] = task
        print(f"[Discord] Started monitor for '{instance_name}'", flush=True)

    async def stop_monitor(self, instance_name: str):
        """Stop monitoring an instance."""
        task = self.monitor_tasks.pop(instance_name, None)
        if task:
            task.cancel()
            print(f"[Discord] Stopped monitor for '{instance_name}'", flush=True)

    async def _monitor_instance(self, instance_name: str):
        """Poll an instance and dispatch to appropriate channels."""
        print(f"[Discord] Starting monitor loop for '{instance_name}'", flush=True)
        poll_count = 0

        while True:
            try:
                if self._clearing.get(instance_name, False):
                    await asyncio.sleep(self.discord_config.poll_interval)
                    continue

                poll_count += 1
                self.manager.refresh_statuses()

                is_running = self.manager.is_primary_running(instance_name)
                if not is_running:
                    if poll_count % 30 == 0:
                        print(f"[Monitor:{instance_name}] Not running, waiting...", flush=True)
                    await asyncio.sleep(self.discord_config.poll_interval)
                    continue

                entries = self.manager.get_activity(instance_name, last_n=200)
                if poll_count % 15 == 0:
                    seen_count = len(self.seen_entries.get(instance_name, set()))
                    print(
                        f"[Monitor:{instance_name}] Poll #{poll_count}: "
                        f"{len(entries)} entries, {seen_count} seen",
                        flush=True,
                    )

                activity_state = self.manager.get_activity_state(instance_name)
                seen = self.seen_entries.get(instance_name, set())

                for entry in entries:
                    entry_hash = hash_entry(entry)
                    if entry_hash in seen:
                        continue
                    seen.add(entry_hash)

                    print(
                        f"[Monitor:{instance_name}] New entry: type={entry.type}, "
                        f"tool={entry.tool_name}, has_text={bool(entry.text_response)}",
                        flush=True,
                    )

                    await self._send_to_activity(instance_name, entry)

                    if entry.text_response:
                        await self._send_to_responses(instance_name, entry.text_response)

                # Status change detection
                new_status = activity_state.status
                old_status = self.last_status.get(instance_name, "unknown")

                if new_status != old_status:
                    print(f"[Monitor:{instance_name}] Status changed: {old_status} -> {new_status}", flush=True)

                    if (
                        old_status == "idle"
                        and new_status in ("thinking", "tool_use", "running")
                        and self._awaiting_plan_approval.get(instance_name, False)
                    ):
                        self._awaiting_plan_approval[instance_name] = False
                        print(f"[Discord:{instance_name}] Plan approved, Claude is working", flush=True)

                    await self._send_status_update(instance_name, new_status, activity_state)
                    self.last_status[instance_name] = new_status

                # Live view updates
                now = time.time()
                last_update = self._last_live_view_update.get(instance_name, 0)
                if new_status != "idle":
                    if now - last_update >= 5:
                        await self._update_live_view(instance_name)
                        self._last_live_view_update[instance_name] = now
                elif new_status == "idle" and old_status != "idle":
                    await self._update_live_view(instance_name)
                    self._last_live_view_update[instance_name] = now

            except asyncio.CancelledError:
                print(f"[Monitor:{instance_name}] Monitor cancelled", flush=True)
                return
            except Exception as e:
                print(f"[Monitor:{instance_name}] Error: {e}", flush=True)
                import traceback
                traceback.print_exc()

            await asyncio.sleep(self.discord_config.poll_interval)

    async def _send_to_activity(self, instance_name: str, entry: LogEntry):
        """Send formatted activity to activity channel."""
        channels = self.router.get_instance_channels(instance_name)
        if not channels or not channels.activity:
            return
        channel = self.get_channel(channels.activity)
        if not channel:
            return

        try:
            if entry.thinking:
                for chunk in split_message(entry.thinking, 1500):
                    await channel.send(f"\U0001f914 *thinking...*\n```\n{chunk}\n```")
            if entry.tool_name:
                msg = f"\U0001f527 **{entry.tool_name}**"
                if entry.tool_input:
                    tool_input_str = str(entry.tool_input)
                    for i, chunk in enumerate(split_message(tool_input_str, 500)):
                        if i == 0:
                            await channel.send(f"{msg}\n```json\n{chunk}\n```")
                        else:
                            await channel.send(f"```json\n{chunk}\n```")
                else:
                    await channel.send(msg)

                # Detect tools that need user input
                if entry.tool_name == "ExitPlanMode":
                    await self._notify_plan_approval_needed(instance_name)
                    self._awaiting_plan_approval[instance_name] = True
                elif entry.tool_name == "AskUserQuestion":
                    await self._notify_question_asked(instance_name, entry.tool_input)

            if entry.tool_result:
                for chunk in split_message(entry.tool_result, 1500):
                    await channel.send(f"\U0001f4cb Result:\n```\n{chunk}\n```")
            if entry.text_response:
                for chunk in split_message(entry.text_response, 1900):
                    await channel.send(f"\U0001f4ac {chunk}")
        except Exception as e:
            print(f"[Send:{instance_name}] Error sending to activity: {e}", flush=True)

    async def _notify_plan_approval_needed(self, instance_name: str):
        """Notify user that Claude is waiting for plan approval — with buttons."""
        channels = self.router.get_instance_channels(instance_name)
        if not channels or not channels.responses:
            return
        channel = self.get_channel(channels.responses)
        if not channel:
            return

        try:
            # Import views here to avoid circular imports
            from .views import PlanApprovalView

            view = PlanApprovalView(self, instance_name)
            await channel.send(
                "\U0001f4cb **Plan Ready for Review**\n"
                "Claude has finished planning and is waiting for your approval.\n"
                "Use the buttons below, or reply with `yes`/`approve` to proceed.",
                view=view,
            )
            print(f"[Send:{instance_name}] Sent plan approval notification with buttons", flush=True)
        except Exception as e:
            print(f"[Send:{instance_name}] Error sending plan notification: {e}", flush=True)

    async def _notify_question_asked(self, instance_name: str, tool_input: dict | None):
        """Notify user that Claude is asking a question — with buttons."""
        channels = self.router.get_instance_channels(instance_name)
        if not channels or not channels.responses:
            return
        channel = self.get_channel(channels.responses)
        if not channel:
            return

        try:
            from .views import QuestionAnswerView

            msg = "\u2753 **Claude is asking a question**\n"
            questions_data = []
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
                                questions_data.append({"label": label, "description": desc})
                msg += "\nUse buttons below or reply with your choice."

            view = QuestionAnswerView(self, instance_name, questions_data) if questions_data else None
            await channel.send(truncate(msg, 1900), view=view)
            print(f"[Send:{instance_name}] Sent question notification", flush=True)
        except Exception as e:
            print(f"[Send:{instance_name}] Error sending question notification: {e}", flush=True)

    async def _send_to_responses(self, instance_name: str, text: str):
        """Send Claude's response to responses channel."""
        self._store_response(instance_name, text)

        channels = self.router.get_instance_channels(instance_name)
        if not channels or not channels.responses:
            return
        channel = self.get_channel(channels.responses)
        if not channel:
            return

        try:
            for chunk in split_message(text, 1900):
                await channel.send(chunk)
        except Exception as e:
            print(f"[Send:{instance_name}] Error sending to responses: {e}", flush=True)

    def _store_response(self, instance_name: str, text: str):
        """Store response locally for CLI retrieval."""
        try:
            responses_dir = Path.home() / ".rushd" / "responses"
            responses_dir.mkdir(parents=True, exist_ok=True)

            data = {
                "timestamp": datetime.now().isoformat(),
                "text": text,
                "primary": instance_name,
            }
            filename = f"{int(time.time() * 1000)}.json"
            (responses_dir / filename).write_text(json.dumps(data))
        except Exception as e:
            print(f"[Store] Error storing response: {e}", flush=True)

    async def _send_status_update(self, instance_name: str, status: str, activity: ActivityState):
        """Send status change notification."""
        channels = self.router.get_instance_channels(instance_name)
        if not channels or not channels.status:
            return
        channel = self.get_channel(channels.status)
        if not channel:
            return

        embed = status_change_embed(status, activity, instance_name)
        await channel.send(embed=embed)

    async def _update_live_view(self, instance_name: str):
        """Update the live view message with current activity."""
        channels = self.router.get_instance_channels(instance_name)
        if not channels or not channels.live_view:
            return
        channel = self.get_channel(channels.live_view)
        if not channel:
            return

        output = self.manager.get_activity_formatted(instance_name, last_n=30)
        content = f"```\n{output[:1900]}\n```"

        msg_id = self._live_view_message_ids.get(instance_name)
        try:
            if msg_id:
                msg = await channel.fetch_message(msg_id)
                await msg.edit(content=content)
            else:
                msg = await channel.send(content)
                self._live_view_message_ids[instance_name] = msg.id
        except discord.NotFound:
            msg = await channel.send(content)
            self._live_view_message_ids[instance_name] = msg.id
        except Exception as e:
            print(f"[LiveView:{instance_name}] Error updating: {e}", flush=True)

    async def on_message(self, message: discord.Message):
        """Handle incoming Discord messages — routes to correct instance."""
        if message.author == self.user:
            return

        # Check if this is a command channel for any instance
        if not self.router.is_command_channel(message.channel.id):
            # Still process slash commands
            await self.process_commands(message)
            return

        # Auth check
        if message.author.name not in self.discord_config.allowed_users:
            print(f"[Discord] Rejected message from '{message.author.name}'", flush=True)
            await message.add_reaction("\U0001f6ab")
            return

        # Determine target instance
        instance_name = self.router.get_instance_for_channel(message.channel.id)
        if not instance_name:
            return

        print(
            f"[Discord] Received from {message.author.name} "
            f"for '{instance_name}': {message.content[:50]}...",
            flush=True,
        )

        # Auto-start if primary and not running
        if not self.manager.is_primary_running(instance_name):
            if instance_name == self.primary_name:
                started = await self._auto_start_primary()
                if not started:
                    await message.add_reaction("\u274c")
                    await message.reply("Failed to auto-start primary instance.")
                    return
            else:
                await message.add_reaction("\u274c")
                await message.reply(f"Instance '{instance_name}' is not running. Use `/start` to start it.")
                return

        content = message.content.strip()

        # Ignore slash commands — these are handled by the interaction system,
        # but if typed as plain text we should not forward them to Claude
        SLASH_COMMANDS = {
            "/start", "/stop", "/list", "/status", "/send", "/clear",
            "/remove", "/cleanup", "/approve", "/help",
        }
        first_word = content.split()[0].lower() if content else ""
        if first_word in SLASH_COMMANDS:
            return

        # Handle attachments
        attachment_paths = []
        for attachment in message.attachments:
            if attachment.content_type and attachment.content_type.startswith("image/"):
                filepath = await self._download_attachment(attachment)
                if filepath:
                    attachment_paths.append(str(filepath))

        if attachment_paths:
            paths_text = "\n".join(f"Please read and analyze this image file: {p}" for p in attachment_paths)
            content = f"{content}\n\n{paths_text}" if content else paths_text

        # Handle plan approval
        if self._awaiting_plan_approval.get(instance_name, False):
            if content.lower() in self.APPROVAL_KEYWORDS:
                print(f"[Discord:{instance_name}] Plan approval keyword: {content}", flush=True)
                self.manager.send_key(instance_name, "2")
                await message.add_reaction("\u2705")
                return
            else:
                # Feedback — navigate to modify option
                print(f"[Discord:{instance_name}] Plan feedback, navigating to modify", flush=True)
                for _ in range(3):
                    self.manager.send_key(instance_name, "Down")
                    await asyncio.sleep(0.1)
                await asyncio.sleep(0.2)
                success = self.manager.send_message(instance_name, content)
                await message.add_reaction("\u2705" if success else "\u274c")
                return

        # Regular message
        success = self.manager.send_message(instance_name, content)
        if success:
            await message.add_reaction("\u2705")
        else:
            await message.add_reaction("\u274c")
            await message.reply(f"Failed to send to '{instance_name}'. Is it running?")

        await self.process_commands(message)

    async def _handle_clear_command(self, message: discord.Message, instance_name: str):
        """Handle /clear command — destroy and recreate instance."""
        print(f"[Discord] Processing /clear for '{instance_name}'", flush=True)
        self._clearing[instance_name] = True

        try:
            await message.add_reaction("\U0001f504")

            channels = self.router.get_instance_channels(instance_name)
            if channels and channels.status:
                status_ch = self.get_channel(channels.status)
                if status_ch:
                    await status_ch.send(f"\U0001f504 Clearing instance '{instance_name}'...")

            result = self.cmd.clear_instance(instance_name)

            # Clear seen entries
            self.seen_entries[instance_name] = set()

            # Wait for initialization
            await asyncio.sleep(3)

            # Mark existing entries as seen
            try:
                entries = self.manager.get_activity(instance_name, last_n=500)
                for entry in entries:
                    self.seen_entries[instance_name].add(hash_entry(entry))
            except Exception:
                pass

            self._clearing[instance_name] = False

            await message.remove_reaction("\U0001f504", self.user)
            if result.success:
                await message.add_reaction("\u2705")
                if channels and channels.status:
                    status_ch = self.get_channel(channels.status)
                    if status_ch:
                        await status_ch.send(f"\u2705 Instance '{instance_name}' cleared and recreated!")
            else:
                await message.add_reaction("\u274c")
                await message.reply(f"Clear failed: {result.message}")

        except Exception as e:
            self._clearing[instance_name] = False
            print(f"[Discord] Error in /clear: {e}", flush=True)
            await message.add_reaction("\u274c")
            await message.reply(f"Failed to clear instance: {e}")

    async def _auto_start_primary(self) -> bool:
        """Auto-start the primary instance if not running."""
        try:
            result = self.cmd.start_instance()
            if not result.success:
                return False

            print(f"[Discord] Auto-started primary instance", flush=True)
            await asyncio.sleep(3)

            channels = self.router.get_instance_channels(self.primary_name)
            if channels and channels.status:
                status_ch = self.get_channel(channels.status)
                if status_ch:
                    await status_ch.send("\U0001f680 Auto-started primary instance")

            return True
        except Exception as e:
            print(f"[Discord] Failed to auto-start primary: {e}", flush=True)
            return False

    async def _download_attachment(self, attachment: discord.Attachment) -> Optional[Path]:
        """Download a Discord attachment and save it locally."""
        try:
            self.SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
            timestamp = int(time.time() * 1000)
            suffix = Path(attachment.filename).suffix or ".png"
            filename = f"screenshot_{timestamp}{suffix}"
            filepath = self.SCREENSHOT_DIR / filename

            await attachment.save(filepath)
            print(f"[Discord] Saved attachment to {filepath}", flush=True)
            return filepath
        except Exception as e:
            print(f"[Discord] Error downloading attachment: {e}", flush=True)
            return None

    async def _cleanup_old_screenshots(self) -> int:
        """Delete screenshots older than retention period."""
        retention_days = self.discord_config.screenshot_retention_days
        cutoff_time = time.time() - (retention_days * 24 * 60 * 60)
        deleted_count = 0

        if not self.SCREENSHOT_DIR.exists():
            return 0

        for filepath in self.SCREENSHOT_DIR.iterdir():
            if filepath.is_file():
                try:
                    if filepath.stat().st_mtime < cutoff_time:
                        filepath.unlink()
                        deleted_count += 1
                except Exception:
                    pass

        return deleted_count


def run_discord_bot(
    manager: ClaudeInstanceManager,
    config: DiscordConfig,
    config_manager: ConfigManager,
    primary_name: str,
    token: str,
):
    """Run the Discord bot (blocking)."""
    bot = RushdBot(manager, config, config_manager, primary_name)
    bot.run(token)
