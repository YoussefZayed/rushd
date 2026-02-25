"""Cog for handling plan approvals and question answering via Discord interactions."""

from discord.ext import commands


class ApprovalsCog(commands.Cog):
    """Handles persistent view registration for plan approvals and questions.

    The actual button/modal handling is in views.py. This cog ensures views
    are registered on bot startup so they persist across restarts.
    """

    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        """Register persistent views on startup."""
        # Views with timeout (non-persistent) don't need registration.
        # If we later add persistent views (timeout=None), register them here:
        # self.bot.add_view(SomePersistentView())
        pass


async def setup(bot):
    await bot.add_cog(ApprovalsCog(bot))
