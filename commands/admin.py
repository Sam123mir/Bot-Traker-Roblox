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


    @setup_group.command(name="member-count", description="👥 Set the voice channel for the real-time member count.")
    @app_commands.describe(channel="Voice channel to rename with the member count")
    @has_manage_guild()
    async def setup_member_count(self, interaction: discord.Interaction, channel: discord.VoiceChannel):
        set_guild_config(interaction.guild.id, "member_count_channel_id", channel.id)
        
        # Initial update
        count = interaction.guild.member_count
        try:
            await channel.edit(name=f"👥 Members: {count:,}")
        except:
            pass

        await premium_response(
            interaction,
            "Member Count Setup",
            f"↳ **Channel**: {channel.mention}\n\nThis channel will now update automatically in real-time.",
            color=0x00e5ff
        )

    @setup_group.command(name="server", description="🚀 Reconstruct the professional server template (Categories & Channels).")
    @has_manage_guild()
    async def setup_server(self, interaction: discord.Interaction):
        """Creates the full professional template as seen in the screenshot."""
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        lang = get_guild_config(guild.id).get("language", "en")
        
        await interaction.followup.send(get_text(lang, "setup_server_start"), ephemeral=True)

        try:
            # 1. Category: STATUS
            cat_status = await guild.create_category("┇═══════ STATUS ═══════┇")
            ch_join = await guild.create_text_channel("》-join-server", category=cat_status)
            ch_members = await guild.create_voice_channel(f"》 Members: {guild.member_count}", category=cat_status)
            from config import BOT_VERSION
            ch_version = await guild.create_voice_channel(f"》 Bot Version: {BOT_VERSION}", category=cat_status)

            # 2. Category: STATUS APIs
            cat_apis = await guild.create_category("┇═══════ STATUS APIs ═══════┇")
            ch_win = await guild.create_voice_channel("》 Windows: 🟢", category=cat_apis)
            ch_mac = await guild.create_voice_channel("》 Mac: 🟢", category=cat_apis)
            ch_android = await guild.create_voice_channel("》 Android: 🟢", category=cat_apis)
            ch_ios = await guild.create_voice_channel("》 iOS: 🟢", category=cat_apis)

            # 3. Category: INFO
            cat_info = await guild.create_category("┇═══════ INFO ═══════┇")
            ch_rules = await guild.create_text_channel("》-rules", category=cat_info)
            ch_ann = await guild.create_text_channel("》-announcements", category=cat_info)
            ch_upd = await guild.create_text_channel("》-updates-bot", category=cat_info)

            # 4. Category: MONITOR
            cat_monitor = await guild.create_category("┇═══════ MONITOR ═══════┇")
            ch_alerts = await guild.create_text_channel("》-roblox-alerts", category=cat_monitor)
            ch_test = await guild.create_text_channel("》-alerts-test", category=cat_monitor)
            ch_stats = await guild.create_text_channel("》-stats", category=cat_monitor)

            # 5. Category: COMMUNITY
            cat_comm = await guild.create_category("┇═══════ COMMUNITY ═══════┇")
            ch_gen = await guild.create_text_channel("》-general", category=cat_comm)
            ch_good = await guild.create_text_channel("》-goodbye", category=cat_comm)
            ch_bugs = await guild.create_text_channel("》-bug-reports", category=cat_comm)
            ch_sugg = await guild.create_text_channel("》-suggestions", category=cat_comm)

            # 6. Save Configuration
            updates = {
                "channel_id": ch_alerts.id,
                "announcement_channel_id": ch_ann.id,
                "welcome_channel_id": ch_join.id,
                "goodbye_channel_id": ch_good.id, # Using the goodbye channel created above
                "member_count_channel_id": ch_members.id,
                "rules_channel_id": ch_rules.id,
                "intro_channel_id": ch_join.id, # Using join as intro fallback
                "bug_reports_channel_id": ch_bugs.id,
                "suggestions_channel_id": ch_sugg.id,
                "api_status_win_id": ch_win.id,
                "api_status_mac_id": ch_mac.id,
                "api_status_android_id": ch_android.id,
                "api_status_ios_id": ch_ios.id,
                "bot_version_channel_id": ch_version.id,
            }
            from core.storage import set_guild_config_bulk
            set_guild_config_bulk(guild.id, updates)

            desc = (
                "✅ **Template created and configured!**\n\n"
                f"↳ **Alerts**: {ch_alerts.mention}\n"
                f"↳ **Welcome**: {ch_join.mention}\n"
                f"↳ **Counter**: {ch_members.mention}\n\n"
                "*All categories and channels have been deployed successfully.*"
            )
            await premium_response(interaction, "Server Reconstructed", desc, color=0x2ECC71)

        except Exception as e:
            await interaction.followup.send(f"❌ Error during setup: `{e}`", ephemeral=True)

    welcome_group = app_commands.Group(name="welcome", description="👋 Configure the professional welcome and goodbye system.")

    @welcome_group.command(name="setup", description="⚙️ Configure channels for welcome/goodbye messages.")
    @app_commands.describe(
        welcome_channel="Channel for welcome messages",
        goodbye_channel="Channel for goodbye messages",
        enabled="Enable or disable the system"
    )
    @has_manage_guild()
    async def welcome_setup(
        self, 
        interaction: discord.Interaction, 
        welcome_channel: Optional[discord.TextChannel] = None,
        goodbye_channel: Optional[discord.TextChannel] = None,
        enabled: bool = True
    ):
        updates = {"goodbye_enabled": enabled}
        if welcome_channel:
            updates["welcome_channel_id"] = welcome_channel.id
        if goodbye_channel:
            updates["goodbye_channel_id"] = goodbye_channel.id
        
        from core.storage import set_guild_config_bulk
        set_guild_config_bulk(interaction.guild.id, updates)
        
        await premium_response(
            interaction, 
            "Welcome System Updated", 
            f"✅ Configuration saved.\n"
            f"↳ **Welcome**: {welcome_channel.mention if welcome_channel else '`Unchanged`'}\n"
            f"↳ **Goodbye**: {goodbye_channel.mention if goodbye_channel else '`Unchanged`'}\n"
            f"↳ **Status**: {'`Enabled`' if enabled else '`Disabled`'}",
            color=0x00E5FF
        )

    @welcome_group.command(name="test", description="🧪 Test the welcome message in a channel.")
    @app_commands.describe(channel="Target channel for the test")
    @has_manage_guild()
    async def welcome_test(self, interaction: discord.Interaction, channel: discord.TextChannel):
        from systems.welcome import _build_welcome_embed
        cfg = get_guild_config(interaction.guild_id)
        embed = _build_welcome_embed(interaction.user, cfg)
        await channel.send(content=f"🧪 **Test Welcome**: {interaction.user.mention}", embed=embed)
        await interaction.response.send_message(f"✅ Preview sent to {channel.mention}", ephemeral=True)

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
        count_id = cfg.get("member_count_channel_id")
        lang = cfg.get("language", "en")
        
        lang_names = {"en": "English (US)", "es": "Español (ES)", "pt": "Português (BR)", "ru": "Русский (RU)", "fr": "Français (FR)"}

        ch_str = f"<#{ch_id}>" if ch_id else "`Not configured`"
        role_str = f"<@&{role_id}>" if role_id else "`None`"
        ann_str = f"<#{ann_id}>" if ann_id else "`Not set`"
        welcome_str = f"<#{welcome_id}>" if welcome_id else "`Fallback`"
        count_str = f"<#{count_id}>" if count_id else "`Disabled`"

        desc = (
            f"↳ **Alerts Channel**: {ch_str}\n"
            f"↳ **Ping Role**: {role_str}\n"
            f"↳ **Updates Channel**: {ann_str}\n"
            f"↳ **Welcome Channel**: {welcome_str}\n"
            f"↳ **Counter Channel**: {count_str}\n"
            f"↳ **Language**: {lang_names.get(lang, lang)}"
        )
        await premium_response(interaction, "Server Configuration", desc, color=0x3498DB)

async def setup(bot):
    await bot.add_cog(AdminCommands(bot))
