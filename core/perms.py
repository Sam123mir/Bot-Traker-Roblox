import discord
from discord import app_commands
from config import DEVELOPERS

def is_owner():
    """Check if the user is in the DEVELOPERS list."""
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.id in DEVELOPERS:
            return True
        raise app_commands.CheckFailure(
            f"This command requires **Owner** access.\nYour ID: `{interaction.user.id}`"
        )
    return app_commands.check(predicate)

def has_manage_guild():
    """Check if the user has Manage Guild permissions."""
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.manage_guild:
            return True
        raise app_commands.CheckFailure("You need the `Manage Server` permission.")
    return app_commands.check(predicate)
