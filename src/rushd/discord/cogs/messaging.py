"""Slash commands for messaging and instance communication."""

from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from .instances import instance_autocomplete
from ..embeds import success_embed, error_embed, instance_status_embed


class MessagingCog(commands.Cog):
    """Slash commands for sending messages to instances."""

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="send", description="Send a message to a Claude Code instance")
    @app_commands.describe(
        instance="Instance name or ID",
        message="Message to send",
    )
    @app_commands.autocomplete(instance=instance_autocomplete)
    async def send(
        self,
        interaction: discord.Interaction,
        instance: str,
        message: str,
    ):
        await interaction.response.defer()

        result = self.bot.cmd.send_message(instance, message)
        if result.success:
            await interaction.followup.send(
                embed=success_embed(f"Message sent to **{instance}**"),
                ephemeral=True,
            )
        else:
            await interaction.followup.send(embed=error_embed(result.message))

    @app_commands.command(name="clear", description="Clear and recreate an instance")
    @app_commands.describe(instance="Instance name or ID (defaults to channel's instance)")
    @app_commands.autocomplete(instance=instance_autocomplete)
    async def clear(
        self,
        interaction: discord.Interaction,
        instance: Optional[str] = None,
    ):
        await interaction.response.defer()

        if instance is None:
            instance = self.bot.router.get_instance_for_channel(interaction.channel.id)
        if instance is None:
            instance = self.bot.primary_name

        # Pause monitor
        self.bot._clearing[instance] = True

        result = self.bot.cmd.clear_instance(instance)

        # Reset seen entries
        from ..utils import hash_entry
        self.bot.seen_entries[instance] = set()

        import asyncio
        await asyncio.sleep(3)

        # Mark existing entries as seen
        try:
            entries = self.bot.manager.get_activity(instance, last_n=500)
            for entry in entries:
                self.bot.seen_entries[instance].add(hash_entry(entry))
        except Exception:
            pass

        self.bot._clearing[instance] = False

        if result.success:
            embed = instance_status_embed(result.data)
            embed.title = f"\u2705 Cleared and recreated: {instance}"
            await interaction.followup.send(embed=embed)
        else:
            await interaction.followup.send(embed=error_embed(result.message))

    @app_commands.command(name="approve", description="Approve a pending plan")
    @app_commands.describe(instance="Instance name or ID (defaults to channel's instance)")
    @app_commands.autocomplete(instance=instance_autocomplete)
    async def approve(
        self,
        interaction: discord.Interaction,
        instance: Optional[str] = None,
    ):
        if instance is None:
            instance = self.bot.router.get_instance_for_channel(interaction.channel.id)
        if instance is None:
            instance = self.bot.primary_name

        if not self.bot._awaiting_plan_approval.get(instance, False):
            await interaction.response.send_message(
                embed=error_embed(f"No plan pending for '{instance}'"),
                ephemeral=True,
            )
            return

        self.bot.manager.send_key(instance, "2")
        await interaction.response.send_message(
            embed=success_embed(f"Plan approved for **{instance}**!"),
        )


async def setup(bot):
    await bot.add_cog(MessagingCog(bot))
