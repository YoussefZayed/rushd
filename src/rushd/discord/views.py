"""Discord UI components — buttons, modals, and select menus for rushd."""

import asyncio
from typing import TYPE_CHECKING

import discord

if TYPE_CHECKING:
    from .bot import RushdBot


class PlanApprovalView(discord.ui.View):
    """Buttons for approving/rejecting a plan."""

    def __init__(self, bot: "RushdBot", instance_name: str, timeout: float = 3600):
        super().__init__(timeout=timeout)
        self.bot = bot
        self.instance_name = instance_name

    @discord.ui.button(label="Approve", style=discord.ButtonStyle.green, emoji="\u2705")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.bot.manager.send_key(self.instance_name, "2")
        self.bot._awaiting_plan_approval[self.instance_name] = False

        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content=f"\u2705 **Plan approved** for `{self.instance_name}`!",
            view=self,
        )
        self.stop()

    @discord.ui.button(label="Reject", style=discord.ButtonStyle.red, emoji="\u274c")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.bot.manager.send_key(self.instance_name, "3")
        self.bot._awaiting_plan_approval[self.instance_name] = False

        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content=f"\u274c **Plan rejected** for `{self.instance_name}`.",
            view=self,
        )
        self.stop()

    @discord.ui.button(label="Modify...", style=discord.ButtonStyle.blurple, emoji="\u270f\ufe0f")
    async def modify(self, interaction: discord.Interaction, button: discord.ui.Button):
        modal = PlanFeedbackModal(self.bot, self.instance_name, self)
        await interaction.response.send_modal(modal)

    async def on_timeout(self):
        """Disable buttons when the view times out."""
        for child in self.children:
            child.disabled = True
        # We can't edit the message from on_timeout without a reference to it,
        # but the buttons will appear disabled on the next interaction attempt.


class PlanFeedbackModal(discord.ui.Modal, title="Plan Feedback"):
    """Modal for entering plan modification feedback."""

    feedback = discord.ui.TextInput(
        label="Your feedback",
        style=discord.TextStyle.paragraph,
        placeholder="Describe what should change in the plan...",
        required=True,
        max_length=2000,
    )

    def __init__(self, bot: "RushdBot", instance_name: str, parent_view: PlanApprovalView):
        super().__init__()
        self.bot = bot
        self.instance_name = instance_name
        self.parent_view = parent_view

    async def on_submit(self, interaction: discord.Interaction):
        # Navigate to "modify" option (Down x3), then send feedback text
        for _ in range(3):
            self.bot.manager.send_key(self.instance_name, "Down")
            await asyncio.sleep(0.1)
        await asyncio.sleep(0.2)
        self.bot.manager.send_message(self.instance_name, str(self.feedback))

        self.bot._awaiting_plan_approval[self.instance_name] = False

        # Disable parent buttons
        for child in self.parent_view.children:
            child.disabled = True
        self.parent_view.stop()

        await interaction.response.send_message(
            f"\u270f\ufe0f Feedback sent to `{self.instance_name}`:\n> {self.feedback}",
            ephemeral=True,
        )


class QuestionAnswerView(discord.ui.View):
    """Dynamic buttons for answering Claude's AskUserQuestion."""

    def __init__(self, bot: "RushdBot", instance_name: str, options: list[dict], timeout: float = 3600):
        super().__init__(timeout=timeout)
        self.bot = bot
        self.instance_name = instance_name

        # Dynamically add a button for each option (max 25 per view, but usually 2-4)
        for i, opt in enumerate(options[:25]):
            label = opt.get("label", f"Option {i + 1}")
            # Truncate label to Discord's 80-char limit
            if len(label) > 80:
                label = label[:77] + "..."

            button = discord.ui.Button(
                label=label,
                style=discord.ButtonStyle.secondary,
                custom_id=f"answer_{self.instance_name}_{i}",
            )
            button.callback = self._make_callback(str(i + 1), label)
            self.add_item(button)

    def _make_callback(self, answer_key: str, label: str):
        async def callback(interaction: discord.Interaction):
            # Send the answer number to Claude
            self.bot.manager.send_message(self.instance_name, answer_key)

            # Disable all buttons
            for child in self.children:
                child.disabled = True
            await interaction.response.edit_message(
                content=f"\u2705 Answered: **{label}**",
                view=self,
            )
            self.stop()

        return callback

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
