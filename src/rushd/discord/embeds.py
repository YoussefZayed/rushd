"""Discord embed builders for rushd."""

import json as json_lib
from typing import Optional

import discord

from ..logs import LogEntry, ActivityState
from ..models import InstanceMetadata, InstanceStatus
from .utils import truncate


STATUS_COLORS = {
    InstanceStatus.RUNNING: discord.Color.green(),
    InstanceStatus.THINKING: discord.Color.blue(),
    InstanceStatus.TOOL_USE: discord.Color.purple(),
    InstanceStatus.IDLE: discord.Color.light_grey(),
    InstanceStatus.STOPPED: discord.Color.red(),
    InstanceStatus.ERROR: discord.Color.dark_red(),
    InstanceStatus.STARTING: discord.Color.yellow(),
}

STATUS_EMOJIS = {
    InstanceStatus.RUNNING: "\U0001f7e2",   # green circle
    InstanceStatus.THINKING: "\U0001f535",   # blue circle
    InstanceStatus.TOOL_USE: "\U0001f7e3",   # purple circle
    InstanceStatus.IDLE: "\u26aa",           # white circle
    InstanceStatus.STOPPED: "\U0001f534",    # red circle
    InstanceStatus.ERROR: "\U0001f534",      # red circle
    InstanceStatus.STARTING: "\U0001f7e1",   # yellow circle
}


def instance_status_embed(instance: InstanceMetadata) -> discord.Embed:
    """Create a rich embed for instance status."""
    color = STATUS_COLORS.get(instance.status, discord.Color.default())
    emoji = STATUS_EMOJIS.get(instance.status, "\u26aa")

    embed = discord.Embed(
        title=f"{emoji} Instance: {instance.name or instance.id}",
        color=color,
    )
    embed.add_field(name="Status", value=str(instance.status), inline=True)
    embed.add_field(name="ID", value=instance.id, inline=True)
    embed.add_field(name="Directory", value=f"`{instance.working_dir}`", inline=False)
    if instance.model:
        embed.add_field(name="Model", value=instance.model, inline=True)
    if instance.last_activity:
        embed.add_field(
            name="Last Activity",
            value=instance.last_activity.strftime("%H:%M:%S"),
            inline=True,
        )
    embed.add_field(
        name="Auto-Approve",
        value="Yes" if instance.auto_approve else "No",
        inline=True,
    )
    if instance.created_at:
        embed.set_footer(text=f"Created: {instance.created_at.strftime('%Y-%m-%d %H:%M:%S')}")
    return embed


def instance_list_embed(instances: list[InstanceMetadata]) -> discord.Embed:
    """Create an embed listing all instances."""
    embed = discord.Embed(title="Claude Code Instances", color=discord.Color.blue())
    if not instances:
        embed.description = "No instances running. Use `/start` to create one."
        return embed

    for inst in instances:
        emoji = STATUS_EMOJIS.get(inst.status, "\u26aa")
        name = inst.name or inst.id
        embed.add_field(
            name=f"{emoji} {name}",
            value=f"**Status:** {inst.status}\n**Dir:** `{inst.working_dir}`",
            inline=False,
        )
    return embed


def activity_embed(entry: LogEntry, instance_name: Optional[str] = None) -> Optional[discord.Embed]:
    """Create an embed for a single activity entry."""
    if entry.thinking:
        text = truncate(entry.thinking, 4000)
        embed = discord.Embed(
            title="\U0001f914 Thinking...",
            description=f"```\n{text}\n```",
            color=discord.Color.blue(),
        )
    elif entry.tool_name:
        embed = discord.Embed(
            title=f"\U0001f527 Tool: {entry.tool_name}",
            color=discord.Color.purple(),
        )
        if entry.tool_input:
            input_str = json_lib.dumps(entry.tool_input, indent=2) if isinstance(entry.tool_input, dict) else str(entry.tool_input)
            input_str = truncate(input_str, 1000)
            embed.add_field(
                name="Input",
                value=f"```json\n{input_str}\n```",
                inline=False,
            )
    elif entry.text_response:
        text = truncate(entry.text_response, 4000)
        embed = discord.Embed(
            description=f"\U0001f4ac {text}",
            color=discord.Color.green(),
        )
    elif entry.tool_result:
        text = truncate(entry.tool_result, 4000)
        embed = discord.Embed(
            title="\U0001f4cb Result",
            description=f"```\n{text}\n```",
            color=discord.Color.light_grey(),
        )
    else:
        return None

    if instance_name:
        embed.set_author(name=instance_name)
    if entry.timestamp:
        embed.set_footer(text=entry.timestamp[:19])
    return embed


def status_change_embed(
    status: str,
    activity: ActivityState,
    instance_name: Optional[str] = None,
) -> discord.Embed:
    """Create an embed for a status change."""
    status_messages = {
        "thinking": ("\U0001f914", "Claude is thinking...", discord.Color.blue()),
        "tool_use": ("\U0001f527", f"Claude is using **{activity.tool_name or 'a tool'}**", discord.Color.purple()),
        "running": ("\u26a1", "Claude is working...", discord.Color.green()),
        "idle": ("\U0001f4a4", f"Claude is idle ({activity.seconds_since_activity:.0f}s)", discord.Color.light_grey()),
        "unknown": ("\u2753", "Status unknown", discord.Color.default()),
    }

    emoji, message, color = status_messages.get(status, ("\u2753", f"Status: {status}", discord.Color.default()))

    embed = discord.Embed(
        description=f"{emoji} {message}",
        color=color,
    )
    if instance_name:
        embed.set_author(name=instance_name)
    return embed


def success_embed(message: str) -> discord.Embed:
    """Create a simple success embed."""
    return discord.Embed(description=f"\u2705 {message}", color=discord.Color.green())


def error_embed(message: str) -> discord.Embed:
    """Create a simple error embed."""
    return discord.Embed(description=f"\u274c {message}", color=discord.Color.red())


def info_embed(message: str) -> discord.Embed:
    """Create a simple info embed."""
    return discord.Embed(description=f"\u2139\ufe0f {message}", color=discord.Color.blue())


def help_embed() -> discord.Embed:
    """Create the /help embed showing all commands and how rushd works."""
    embed = discord.Embed(
        title="rushd — Claude Code Instance Manager",
        description=(
            "Manage multiple [Claude Code](https://claude.ai/claude-code) instances "
            "from Discord. Each instance runs in its own tmux window on the server."
        ),
        color=discord.Color.blurple(),
    )

    embed.add_field(
        name="\U0001f680 Instance Lifecycle",
        value=(
            "`/start` — Start a new instance (name, directory, model, prompt)\n"
            "`/stop` — Stop a running instance\n"
            "`/remove` — Remove a stopped instance from storage\n"
            "`/cleanup` — Stop everything and clean up the session"
        ),
        inline=False,
    )

    embed.add_field(
        name="\U0001f4ac Messaging",
        value=(
            "`/send` — Send a message to any instance\n"
            "`/clear` — Destroy and recreate an instance\n"
            "**Plain text** in `#*-commands` or `#*-responses` channels is sent directly to Claude"
        ),
        inline=False,
    )

    embed.add_field(
        name="\U0001f4cb Info & Approval",
        value=(
            "`/list` — List all instances with status\n"
            "`/status` — Detailed status of an instance\n"
            "`/approve` — Approve a pending plan\n"
            "`/help` — This message"
        ),
        inline=False,
    )

    embed.add_field(
        name="\U0001f4e2 Channels",
        value=(
            "Each instance gets its own category with 5 channels:\n"
            "**#name-commands** — Send messages to Claude\n"
            "**#name-responses** — Claude's text replies\n"
            "**#name-activity** — Full stream (thinking, tools, results)\n"
            "**#name-status** — Status change notifications\n"
            "**#name-live-view** — Auto-updating activity snapshot"
        ),
        inline=False,
    )

    embed.add_field(
        name="\u2705 Plan Approval",
        value=(
            "When Claude finishes a plan, interactive buttons appear:\n"
            "**Approve** — start implementation\n"
            "**Reject** — reject the plan\n"
            "**Modify** — open a text box to give feedback\n"
            "You can also type `yes`/`approve` as plain text."
        ),
        inline=False,
    )

    embed.add_field(
        name="\U0001f4ce Attachments",
        value="Drop screenshots or images in a commands/responses channel — they're forwarded to Claude for analysis.",
        inline=False,
    )

    embed.set_footer(text="rushd v0.5.0 — github.com/YoussefZayed/rushd")
    return embed
