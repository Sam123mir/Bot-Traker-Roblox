# commands/admin.py
"""
Server management commands.
Allows administrators to configure alerts, announcements, and language.
"""
from __future__ import annotations

from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from core.i18n import get_text
from core.notifier import premium_response
from core.perms import has_manage_guild
from core.storage import get_guild_config, set_guild_config

# ──────────────────────────────────────────────────────────────────────────────
#  Admin Commands Cog
# ──────────────────────────────────────────────────────────────────────────────
class AdminCommands(commands.Cog):
    """Cog for server administrator configurations."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    setup_group = app_commands.Group(name="setup", description="🔧 Configure BloxPulse settings for your server.")

    @setup_group.command(name="alerts", description="📡 Set the channel for Roblox version alerts.")
    @app_commands.describe(
        channel="Channel to receive updates",
        ping_role="Role to mention on each update (optional)"
    )
    @has_manage_guild()
    async def setup_alerts(self, interaction: discord.Interaction, channel: discord.abc.GuildChannel, ping_role: Optional[discord.Role] = None):
        if not hasattr(channel, "send"):
            return await premium_response(interaction, "Invalid Channel", "Please select a text, news, or voice channel.", color=0xE74C3C)

        set_guild_config(interaction.guild_id, "channel_id", channel.id)
        if ping_role:
            set_guild_config(interaction.guild_id, "ping_role_id", ping_role.id)

        desc = (
            "**✅ Setup Completed**\n\n"
            f"● **Channel**: {channel.mention}\n"
            f"● **Ping**: {ping_role.mention if ping_role else '`Disabled`'}\n\n"
            "*BloxPulse will send version alerts here.*"
        )
        await premium_response(interaction, "Monitor Setup", desc, color=0x2ECC71)

    @setup_group.command(name="announcements", description="⬢ Set the channel for official BloxPulse broadcasts.")
    @app_commands.describe(channel="The channel where official announcements will be sent.")
    @has_manage_guild()
    async def setup_announcements(self, interaction: discord.Interaction, channel: discord.abc.GuildChannel):
        if not isinstance(channel, discord.TextChannel):
            return await premium_response(interaction, "❌ Error", "Must be a text channel.", color=0xFF0000)
        
        set_guild_config(interaction.guild.id, "announcement_channel_id", channel.id)
        cfg = get_guild_config(interaction.guild.id)
        lang = cfg.get("language", "en")
        
        await premium_response(
            interaction,
            get_text(lang, "setup_server_done"),
            f"↳ **Updates Channel**: {channel.mention}\n\nAll future official broadcasts will be sent there.",
            color=0x00e5ff
        )

    @setup_group.command(name="welcome", description="⬢ Set the channel for member welcome messages.")
    @app_commands.describe(channel="The channel where welcome messages will be sent.")
    @has_manage_guild()
    async def setup_welcome(self, interaction: discord.Interaction, channel: discord.abc.GuildChannel):
        if not isinstance(channel, discord.TextChannel):
            return await premium_response(interaction, "❌ Error", "Must be a text channel.", color=0xFF0000)
        
        set_guild_config(interaction.guild.id, "welcome_channel_id", channel.id)
        cfg = get_guild_config(interaction.guild.id)
        lang = cfg.get("language", "en")
        
        await premium_response(
            interaction,
            get_text(lang, "setup_server_done"),
            f"↳ **Welcome Channel**: {channel.mention}\n\nNew members will be greeted here professionally.",
            color=0x00e5ff
        )

    @app_commands.command(name="language", description="🌐 Change the bot's language for this server.")
    @app_commands.describe(lang="Choose a language")
    @app_commands.choices(lang=[
        app_commands.Choice(name="English 🇺🇸",   value="en"),
        app_commands.Choice(name="Español 🇪🇸",   value="es"),
        app_commands.Choice(name="Português 🇧🇷", value="pt"),
        app_commands.Choice(name="Русский 🇷🇺",   value="ru"),
        app_commands.Choice(name="Français 🇫🇷",  value="fr"),
    ])
    @has_manage_guild()
    async def language(self, interaction: discord.Interaction, lang: str):
        set_guild_config(interaction.guild_id, "language", lang)
        
        names = {"en":"English","es":"Español","pt":"Português","ru":"Русский","fr":"Français"}
        name = names.get(lang, lang)
        
        await premium_response(
            interaction, 
            "Language Updated", 
            f"⬢ The server language has been set to **{name}**.\nAll embeds and messages will now use this language.",
            color=0x3498DB
        )

    @app_commands.command(name="config", description="⬢ View current BloxPulse configuration for this server.")
    @has_manage_guild()
    async def config_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        cfg = get_guild_config(interaction.guild_id)
        ch_id = cfg.get("channel_id")
        role_id = cfg.get("ping_role_id")
        ann_id = cfg.get("announcement_channel_id")
        welcome_id = cfg.get("welcome_channel_id")
        lang = cfg.get("language", "en")
        
        lang_names = {"en": "English (US)", "es": "Español (ES)", "pt": "Português (BR)", "ru": "Русский (RU)", "fr": "Français (FR)"}

        ch_str = f"<#{ch_id}>" if ch_id else "`Not configured`"
        role_str = f"<@&{role_id}>" if role_id else "`None`"
        ann_str = f"<#{ann_id}>" if ann_id else "`Not set`"
        welcome_str = f"<#{welcome_id}>" if welcome_id else "`Fallback`"

        desc = (
            f"↳ **Alerts Channel**: {ch_str}\n"
            f"↳ **Ping Role**: {role_str}\n"
            f"↳ **Updates Channel**: {ann_str}\n"
            f"↳ **Welcome Channel**: {welcome_str}\n"
            f"↳ **Language**: {lang_names.get(lang, lang)}"
        )
        await premium_response(interaction, "Server Configuration", desc, color=0x3498DB)

async def setup(bot):
    await bot.add_cog(AdminCommands(bot))
