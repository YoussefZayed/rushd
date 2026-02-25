"""Slash commands for instance lifecycle management."""

from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from ..embeds import instance_status_embed, instance_list_embed, success_embed, error_embed, help_embed


async def instance_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Autocomplete for instance names."""
    bot = interaction.client
    bot.manager.refresh_statuses()
    instances = bot.manager.list_instances(include_stopped=False)
    return [
        app_commands.Choice(
            name=f"{i.name or i.id} ({i.status})",
            value=i.name or i.id,
        )
        for i in instances
        if current.lower() in (i.name or i.id).lower()
    ][:25]


async def all_instance_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Autocomplete for all instances including stopped."""
    bot = interaction.client
    bot.manager.refresh_statuses()
    instances = bot.manager.list_instances(include_stopped=True)
    return [
        app_commands.Choice(
            name=f"{i.name or i.id} ({i.status})",
            value=i.name or i.id,
        )
        for i in instances
        if current.lower() in (i.name or i.id).lower()
    ][:25]


class InstancesCog(commands.Cog):
    """Slash commands for managing Claude Code instances."""

    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="help", description="Show all rushd commands and how it works")
    async def help(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=help_embed(), ephemeral=True)

    @app_commands.command(name="start", description="Start a new Claude Code instance")
    @app_commands.describe(
        name="Instance name (defaults to primary)",
        directory="Working directory path",
        model="Claude model to use",
        prompt="Initial prompt to send",
    )
    async def start(
        self,
        interaction: discord.Interaction,
        name: Optional[str] = None,
        directory: Optional[str] = None,
        model: Optional[str] = None,
        prompt: Optional[str] = None,
    ):
        await interaction.response.defer()

        from pathlib import Path
        working_dir = Path(directory).expanduser().resolve() if directory else None

        result = self.bot.cmd.start_instance(
            name=name,
            working_dir=working_dir,
            model=model,
            prompt=prompt,
        )

        if result.success:
            instance = result.data
            embed = instance_status_embed(instance)
            embed.title = f"\u2705 Started: {instance.name or instance.id}"
            await interaction.followup.send(embed=embed)

            # Set up channels for new instance if it's not primary
            if instance.name and instance.name != self.bot.primary_name:
                guild = interaction.guild
                if guild:
                    channels = await self.bot.router.ensure_channels_for_instance(
                        guild, instance.name
                    )
                    if channels:
                        await self.bot._initialize_monitor(instance.name)
        else:
            await interaction.followup.send(embed=error_embed(result.message))

    @app_commands.command(name="stop", description="Stop a Claude Code instance")
    @app_commands.describe(instance="Instance name or ID")
    @app_commands.autocomplete(instance=instance_autocomplete)
    async def stop(self, interaction: discord.Interaction, instance: str):
        await interaction.response.defer()

        result = self.bot.cmd.stop_instance(instance, force=False)
        if result.success:
            await interaction.followup.send(embed=success_embed(f"Stopped: {instance}"))
            await self.bot.stop_monitor(instance)
        else:
            await interaction.followup.send(embed=error_embed(result.message))

    @app_commands.command(name="list", description="List all Claude Code instances")
    @app_commands.describe(all="Include stopped instances")
    async def list_instances(
        self, interaction: discord.Interaction, all: bool = False
    ):
        await interaction.response.defer()

        result = self.bot.cmd.list_instances(include_stopped=all)
        embed = instance_list_embed(result.data)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="status", description="Show detailed status of an instance")
    @app_commands.describe(instance="Instance name or ID (defaults to channel's instance)")
    @app_commands.autocomplete(instance=all_instance_autocomplete)
    async def status(
        self, interaction: discord.Interaction, instance: Optional[str] = None
    ):
        await interaction.response.defer()

        # Default to the instance mapped to this channel
        if instance is None:
            instance = self.bot.router.get_instance_for_channel(interaction.channel.id)
        if instance is None:
            instance = self.bot.primary_name

        result = self.bot.cmd.get_status(instance)
        if result.success:
            embed = instance_status_embed(result.data)
            await interaction.followup.send(embed=embed)
        else:
            await interaction.followup.send(embed=error_embed(result.message))

    @app_commands.command(name="remove", description="Remove a stopped instance from storage")
    @app_commands.describe(instance="Instance name or ID")
    @app_commands.autocomplete(instance=all_instance_autocomplete)
    async def remove(self, interaction: discord.Interaction, instance: str):
        await interaction.response.defer()

        result = self.bot.cmd.remove_instance(instance)
        if result.success:
            await interaction.followup.send(embed=success_embed(f"Removed: {instance}"))
        else:
            await interaction.followup.send(embed=error_embed(result.message))

    @app_commands.command(name="cleanup", description="Stop all instances and clean up session")
    async def cleanup(self, interaction: discord.Interaction):
        await interaction.response.defer()

        result = self.bot.cmd.cleanup(force=True)
        # Stop all monitors
        for name in list(self.bot.monitor_tasks.keys()):
            await self.bot.stop_monitor(name)

        await interaction.followup.send(embed=success_embed(result.message))


async def setup(bot):
    await bot.add_cog(InstancesCog(bot))
