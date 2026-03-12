# commands/clear.py
"""
Clear command.
Allows moderators to delete multiple messages in a channel cleanly.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from core.notifier import premium_response

log = logging.getLogger("BloxPulse.ClearCommand")

class ClearCommand(commands.Cog):
    """Cog for the clear/purge message command."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(
        name="clear", 
        description="🧹  Delete a specified number of messages in this channel."
    )
    @app_commands.describe(
        amount="Number of messages to delete (1-100).",
        user="Optional: Only delete messages from this specific user."
    )
    @app_commands.default_permissions(manage_messages=True)
    async def clear_messages(
        self, 
        interaction: discord.Interaction, 
        amount: app_commands.Range[int, 1, 100],
        user: Optional[discord.Member] = None
    ):
        """Purge messages from a channel, optionally filtered by a specific user."""
        # Defer in case deletion takes a few seconds
        await interaction.response.defer(ephemeral=True)
        
        if not isinstance(interaction.channel, (discord.TextChannel, discord.Thread, discord.VoiceChannel)):
            embed = discord.Embed(
                title="❌  Invalid Channel",
                description="This command can only be used in text or voice channels.",
                color=0xED4245
            )
            return await interaction.followup.send(embed=embed, ephemeral=True)

        # Checking bot permissions first
        bot_member = interaction.guild.me
        if not interaction.channel.permissions_for(bot_member).manage_messages:
            embed = discord.Embed(
                title="❌  Missing Permissions",
                description="I don't have the **Manage Messages** permission in this channel.",
                color=0xED4245
            )
            return await interaction.followup.send(embed=embed, ephemeral=True)

        def check_msg(m: discord.Message) -> bool:
            if user:
                return m.author.id == user.id
            return True

        deleted_count = 0
        try:
            # We fetch amount + 1 because we don't want to count the invisible interaction message itself
            deleted = await interaction.channel.purge(
                limit=amount,
                check=check_msg
            )
            deleted_count = len(deleted)
            
            icon_url = self.bot.user.display_avatar.url if self.bot.user else discord.utils.MISSING
            
            description = f"Successfully deleted **{deleted_count}** message(s)."
            if user:
                description = f"Successfully deleted **{deleted_count}** message(s) from {user.mention}."

            embed = discord.Embed(
                title="🧹  Messages Cleared",
                description=description,
                color=0x57F287
            )
            embed.set_footer(text=f"Requested by {interaction.user.name}", icon_url=icon_url)
            
            await interaction.followup.send(embed=embed, ephemeral=True)
            
        except discord.HTTPException as exc:
            # Code 50034 is specifically older than 14 days error during bulk delete
            if exc.code == 50034:
                embed = discord.Embed(
                    title="⚠️  Bulk Delete Failed",
                    description=(
                        "I can only bulk-delete messages that are **younger than 14 days**.\n\n"
                        "Some of the messages you tried to delete are too old. "
                        "Try clearing a smaller amount."
                    ),
                    color=0xED4245
                )
            else:
                log.error("Failed to purge messages: %s", exc)
                embed = discord.Embed(
                    title="❌  Deletion Error",
                    description=f"An error occurred while deleting messages: `{exc}`",
                    color=0xED4245
                )
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception as exc:
            log.error("Unhandled error during purge: %s", exc)
            embed = discord.Embed(
                title="❌  Unexpected Error",
                description="A strange error occurred. Please try again later.",
                color=0xED4245
            )
            await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ClearCommand(bot))
