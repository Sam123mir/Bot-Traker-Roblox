# commands/admin.py
"""
Server management commands.
Allows administrators to configure alerts, announcements, welcome systems, and language.
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
#  Design System
# ──────────────────────────────────────────────────────────────────────────────

COLOR_PRIMARY = 0x5865F2   # Discord Blurple
COLOR_SUCCESS = 0x57F287   # Green
COLOR_WARNING = 0xFEE75C   # Yellow
COLOR_DANGER  = 0xED4245   # Red
COLOR_ACCENT  = 0x00E5FF   # Cyan


def _bot_icon(interaction: discord.Interaction) -> str:
    return interaction.client.user.display_avatar.url


def _base_embed(
    title: str,
    description: str = "",
    color: int = COLOR_PRIMARY,
    *,
    timestamp: bool = True,
) -> discord.Embed:
    from datetime import datetime, timezone
    embed = discord.Embed(
        title=title,
        description=description or discord.utils.MISSING,
        color=color,
        timestamp=datetime.now(timezone.utc) if timestamp else discord.utils.MISSING,
    )
    return embed


def _success_embed(title: str, description: str, icon: str) -> discord.Embed:
    """Shorthand for a consistently styled success embed."""
    embed = _base_embed(title, description, COLOR_SUCCESS)
    embed.set_footer(text="BloxPulse · Configuration", icon_url=icon)
    return embed


def _error_embed(title: str, description: str, icon: str) -> discord.Embed:
    """Shorthand for a consistently styled error embed."""
    embed = _base_embed(title, description, COLOR_DANGER)
    embed.set_footer(text="BloxPulse · Configuration", icon_url=icon)
    return embed


# ──────────────────────────────────────────────────────────────────────────────
#  Admin Commands Cog
# ──────────────────────────────────────────────────────────────────────────────

class AdminCommands(commands.Cog):
    """Cog for server administrator configurations."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── /setup group ──────────────────────────────────────────────────────────

    setup_group = app_commands.Group(
        name="setup",
        description="🔧  Configure BloxPulse settings for your server.",
    )

    @setup_group.command(name="alerts", description="📡  Set the channel that receives Roblox version alerts.")
    @app_commands.describe(
        channel="Text channel for update notifications.",
        ping_role="Role to @mention on each update (optional).",
    )
    @has_manage_guild()
    async def setup_alerts(
        self,
        interaction: discord.Interaction,
        channel: discord.abc.GuildChannel,
        ping_role: Optional[discord.Role] = None,
    ):
        await interaction.response.defer(ephemeral=True)
        icon = _bot_icon(interaction)

        if not hasattr(channel, "send"):
            embed = _error_embed(
                title="❌  Invalid Channel",
                description="Please select a **text** or **news** channel. Voice channels are not supported.",
                icon=icon,
            )
            return await interaction.followup.send(embed=embed, ephemeral=True)

        set_guild_config(interaction.guild_id, "channel_id", channel.id, guild_name=interaction.guild.name)
        if ping_role:
            set_guild_config(interaction.guild_id, "ping_role_id", ping_role.id, guild_name=interaction.guild.name)

        embed = _base_embed(
            title="📡  Alerts Channel Configured",
            description="BloxPulse will now send Roblox version alerts to the selected channel.\n\u200b",
            color=COLOR_SUCCESS,
        )
        embed.add_field(name="📢  Channel",   value=channel.mention,                                   inline=True)
        embed.add_field(name="🔔  Ping Role", value=ping_role.mention if ping_role else "`Disabled`",  inline=True)
        embed.set_footer(text="BloxPulse · Alert Setup", icon_url=icon)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @setup_group.command(name="announcements", description="📣  Set the channel for official BloxPulse broadcasts.")
    @app_commands.describe(channel="Text channel where official announcements will appear.")
    @has_manage_guild()
    async def setup_announcements(
        self,
        interaction: discord.Interaction,
        channel: discord.abc.GuildChannel,
    ):
        await interaction.response.defer(ephemeral=True)
        icon = _bot_icon(interaction)

        if not isinstance(channel, discord.TextChannel):
            embed = _error_embed(
                title="❌  Invalid Channel",
                description="Announcements can only be sent to a **text channel**.",
                icon=icon,
            )
            return await interaction.followup.send(embed=embed, ephemeral=True)

        set_guild_config(interaction.guild_id, "announcement_channel_id", channel.id, guild_name=interaction.guild.name)
        cfg  = get_guild_config(interaction.guild_id)
        lang = cfg.get("language", "en")

        embed = _base_embed(
            title="📣  Announcements Channel Set",
            description="All future official BloxPulse broadcasts will be delivered here.\n\u200b",
            color=COLOR_SUCCESS,
        )
        embed.add_field(name="📢  Channel", value=channel.mention, inline=True)
        embed.set_footer(text="BloxPulse · Announcement Setup", icon_url=icon)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @setup_group.command(name="member-count", description="👥  Set the voice channel for the real-time member counter.")
    @app_commands.describe(channel="Voice channel to rename dynamically with the member count.")
    @has_manage_guild()
    async def setup_member_count(
        self,
        interaction: discord.Interaction,
        channel: discord.VoiceChannel,
    ):
        await interaction.response.defer(ephemeral=True)
        icon = _bot_icon(interaction)

        set_guild_config(interaction.guild_id, "member_count_channel_id", channel.id, guild_name=interaction.guild.name)

        # Perform an immediate update so the user sees it working right away
        count = interaction.guild.member_count
        try:
            await channel.edit(name=f"》 Members: {count:,}", reason="BloxPulse — initial member count setup")
        except discord.Forbidden:
            pass  # Will update on next cycle

        embed = _base_embed(
            title="👥  Member Counter Configured",
            description="The voice channel will now update in real-time as members join or leave.\n\u200b",
            color=COLOR_SUCCESS,
        )
        embed.add_field(name="🔊  Channel",        value=channel.mention,    inline=True)
        embed.add_field(name="👥  Current Count",  value=f"`{count:,}`",     inline=True)
        embed.set_footer(text="BloxPulse · Member Counter  ·  Updates every ~6 min", icon_url=icon)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @setup_group.command(name="server", description="🚀  Deploy the full professional server template (categories & channels).")
    @has_manage_guild()
    async def setup_server(self, interaction: discord.Interaction):
        """Creates the complete BloxPulse server template with all categories and channels."""
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        lang  = get_guild_config(guild.id).get("language", "en")
        icon  = _bot_icon(interaction)

        # Notify the user that we're working — this can take a few seconds
        await interaction.followup.send(
            embed=_base_embed(
                title="⏳  Building Template…",
                description="Creating all categories and channels. This may take a moment.",
                color=COLOR_WARNING,
            ),
            ephemeral=True,
        )

        try:
            from config import BOT_VERSION

            # ── Category: STATUS ──────────────────────────────────────────────
            cat_status  = await guild.create_category("┇═══════ STATUS ═══════┇")
            ch_join     = await guild.create_text_channel("》-join-server",                  category=cat_status)
            ch_members  = await guild.create_voice_channel(f"》 Members: {guild.member_count}", category=cat_status)
            ch_version  = await guild.create_voice_channel(f"》 Bot Version: {BOT_VERSION}", category=cat_status)

            # ── Category: API STATUS ──────────────────────────────────────────
            cat_apis    = await guild.create_category("┇═════ STATUS APIs ═════┇")
            ch_win      = await guild.create_voice_channel("》 Windows: 🟢",  category=cat_apis)
            ch_mac      = await guild.create_voice_channel("》 Mac: 🟢",      category=cat_apis)
            ch_android  = await guild.create_voice_channel("》 Android: 🟢",  category=cat_apis)
            ch_ios      = await guild.create_voice_channel("》 iOS: 🟢",      category=cat_apis)

            # ── Category: INFO ────────────────────────────────────────────────
            cat_info    = await guild.create_category("┇════════ INFO ════════┇")
            ch_rules    = await guild.create_text_channel("》-rules",          category=cat_info)
            ch_ann      = await guild.create_text_channel("》-announcements",  category=cat_info)
            ch_upd      = await guild.create_text_channel("》-updates-bot",    category=cat_info)

            # ── Category: MONITOR ─────────────────────────────────────────────
            cat_monitor = await guild.create_category("┇══════ MONITOR ══════┇")
            ch_alerts   = await guild.create_text_channel("》-roblox-alerts",  category=cat_monitor)
            ch_test     = await guild.create_text_channel("》-alerts-test",    category=cat_monitor)
            ch_stats    = await guild.create_text_channel("》-stats",          category=cat_monitor)

            # ── Category: COMMUNITY ───────────────────────────────────────────
            cat_comm    = await guild.create_category("┇═════ COMMUNITY ═════┇")
            ch_gen      = await guild.create_text_channel("》-general",        category=cat_comm)
            ch_goodbye  = await guild.create_text_channel("》-goodbye",        category=cat_comm)
            ch_bugs     = await guild.create_text_channel("》-bug-reports",    category=cat_comm)
            ch_sugg     = await guild.create_text_channel("》-suggestions",    category=cat_comm)

            # ── Persist all channel IDs ───────────────────────────────────────
            from core.storage import set_guild_config_bulk
            set_guild_config_bulk(guild.id, {
                "channel_id":              ch_alerts.id,
                "announcement_channel_id": ch_ann.id,
                "welcome_channel_id":      ch_join.id,
                "goodbye_channel_id":      ch_goodbye.id,
                "member_count_channel_id": ch_members.id,
                "rules_channel_id":        ch_rules.id,
                "intro_channel_id":        ch_join.id,
                "bug_reports_channel_id":  ch_bugs.id,
                "suggestions_channel_id":  ch_sugg.id,
                "api_status_win_id":       ch_win.id,
                "api_status_mac_id":       ch_mac.id,
                "api_status_android_id":   ch_android.id,
                "api_status_ios_id":       ch_ios.id,
                "bot_version_channel_id":  ch_version.id,
            }, guild_name=guild.name)

            embed = _base_embed(
                title="🚀  Server Template Deployed",
                description="All categories and channels have been created and configured.\n\u200b",
                color=COLOR_SUCCESS,
            )
            embed.add_field(name="🚨  Roblox Alerts",   value=ch_alerts.mention,  inline=True)
            embed.add_field(name="📣  Announcements",   value=ch_ann.mention,     inline=True)
            embed.add_field(name="👋  Welcome",         value=ch_join.mention,    inline=True)
            embed.add_field(name="👥  Member Counter",  value=ch_members.mention, inline=True)
            embed.add_field(name="📜  Rules",           value=ch_rules.mention,   inline=True)
            embed.add_field(name="💬  General",         value=ch_gen.mention,     inline=True)
            embed.set_footer(text="BloxPulse · Server Setup  ·  All settings auto-saved", icon_url=icon)

        except Exception as exc:
            embed = _error_embed(
                title="❌  Setup Failed",
                description=f"An error occurred during template creation.\n```\n{exc}\n```",
                icon=icon,
            )

        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /welcome group ────────────────────────────────────────────────────────

    welcome_group = app_commands.Group(
        name="welcome",
        description="👋  Configure the welcome & goodbye system.",
    )

    @welcome_group.command(name="setup", description="⚙️  Configure welcome and goodbye channels.")
    @app_commands.describe(
        welcome_channel="Channel for welcome messages.",
        goodbye_channel="Channel for goodbye messages.",
        enabled="Enable or disable the goodbye message system.",
    )
    @has_manage_guild()
    async def welcome_setup(
        self,
        interaction: discord.Interaction,
        welcome_channel: Optional[discord.TextChannel] = None,
        goodbye_channel: Optional[discord.TextChannel] = None,
        enabled: bool = True,
    ):
        await interaction.response.defer(ephemeral=True)
        icon = _bot_icon(interaction)

        updates = {"goodbye_enabled": enabled}
        if welcome_channel:
            updates["welcome_channel_id"] = welcome_channel.id
        if goodbye_channel:
            updates["goodbye_channel_id"] = goodbye_channel.id

        from core.storage import set_guild_config_bulk
        set_guild_config_bulk(interaction.guild_id, updates, guild_name=interaction.guild.name)

        embed = _base_embed(
            title="👋  Welcome System Updated",
            description="Configuration saved successfully.\n\u200b",
            color=COLOR_SUCCESS,
        )
        embed.add_field(
            name="📥  Welcome Channel",
            value=welcome_channel.mention if welcome_channel else "`Unchanged`",
            inline=True,
        )
        embed.add_field(
            name="📤  Goodbye Channel",
            value=goodbye_channel.mention if goodbye_channel else "`Unchanged`",
            inline=True,
        )
        embed.add_field(
            name="🔘  Goodbye Messages",
            value="`Enabled`" if enabled else "`Disabled`",
            inline=True,
        )
        embed.set_footer(text="BloxPulse · Welcome System", icon_url=icon)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @welcome_group.command(name="test", description="🧪  Send a test welcome message to a channel.")
    @app_commands.describe(channel="Channel to send the preview in.")
    @has_manage_guild()
    async def welcome_test(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
    ):
        await interaction.response.defer(ephemeral=True)
        icon = _bot_icon(interaction)

        from systems.welcome import _build_welcome_embed
        cfg   = get_guild_config(interaction.guild_id)
        embed = _build_welcome_embed(interaction.user, cfg)

        try:
            await channel.send(
                content=f"🧪  **Welcome Preview** → {interaction.user.mention}",
                embed=embed,
            )
            result_embed = _base_embed(
                title="✅  Test Message Sent",
                description=f"Preview delivered to {channel.mention}.",
                color=COLOR_SUCCESS,
            )
        except discord.Forbidden:
            result_embed = _error_embed(
                title="❌  Missing Permissions",
                description=f"I don't have permission to send messages in {channel.mention}.",
                icon=icon,
            )

        result_embed.set_footer(text="BloxPulse · Welcome Test", icon_url=icon)
        await interaction.followup.send(embed=result_embed, ephemeral=True)

    # ── /language ─────────────────────────────────────────────────────────────

    @app_commands.command(name="language", description="🌐  Change the bot's display language for this server.")
    @app_commands.describe(lang="Select a language.")
    @app_commands.choices(lang=[
        app_commands.Choice(name="English 🇺🇸",    value="en"),
        app_commands.Choice(name="Español 🇪🇸",    value="es"),
        app_commands.Choice(name="Português 🇧🇷",  value="pt"),
        app_commands.Choice(name="Русский 🇷🇺",    value="ru"),
        app_commands.Choice(name="Français 🇫🇷",   value="fr"),
    ])
    @has_manage_guild()
    async def language(self, interaction: discord.Interaction, lang: str):
        await interaction.response.defer(ephemeral=True)
        set_guild_config(interaction.guild_id, "language", lang, guild_name=interaction.guild.name)
        icon = _bot_icon(interaction)

        names = {
            "en": ("English",   "🇺🇸"),
            "es": ("Español",   "🇪🇸"),
            "pt": ("Português", "🇧🇷"),
            "ru": ("Русский",   "🇷🇺"),
            "fr": ("Français",  "🇫🇷"),
        }
        label, flag = names.get(lang, (lang, "🌐"))

        embed = _base_embed(
            title="🌐  Server Language Updated",
            description=(
                f"All BloxPulse embeds and messages will now appear in **{flag} {label}**.\n\u200b"
            ),
            color=COLOR_SUCCESS,
        )
        embed.add_field(name="🗣️  Language",  value=f"`{flag} {label}`",  inline=True)
        embed.add_field(name="🔑  Code",       value=f"`{lang}`",          inline=True)
        embed.set_footer(text="BloxPulse · Language Settings", icon_url=icon)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /config ───────────────────────────────────────────────────────────────

    @app_commands.command(name="config", description="📋  View the current BloxPulse configuration for this server.")
    @has_manage_guild()
    async def config_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        icon = _bot_icon(interaction)
        cfg  = get_guild_config(interaction.guild_id)

        ch_id       = cfg.get("channel_id")
        role_id     = cfg.get("ping_role_id")
        ann_id      = cfg.get("announcement_channel_id")
        welcome_id  = cfg.get("welcome_channel_id")
        goodbye_id  = cfg.get("goodbye_channel_id")
        count_id    = cfg.get("member_count_channel_id")
        lang        = cfg.get("language", "en")
        goodbye_on  = cfg.get("goodbye_enabled", False)

        lang_labels = {
            "en": "English 🇺🇸",
            "es": "Español 🇪🇸",
            "pt": "Português 🇧🇷",
            "ru": "Русский 🇷🇺",
            "fr": "Français 🇫🇷",
        }

        def ch(cid):  return f"<#{cid}>"  if cid else "`Not set`"
        def ro(rid):  return f"<@&{rid}>" if rid else "`None`"

        embed = _base_embed(
            title="📋  Server Configuration",
            description=f"Current BloxPulse settings for **{interaction.guild.name}**.\n\u200b",
            color=COLOR_PRIMARY,
        )
        embed.add_field(name="🚨  Alerts Channel",      value=ch(ch_id),      inline=True)
        embed.add_field(name="🔔  Ping Role",            value=ro(role_id),    inline=True)
        embed.add_field(name="📣  Announcements",        value=ch(ann_id),     inline=True)
        embed.add_field(name="👋  Welcome Channel",      value=ch(welcome_id), inline=True)
        embed.add_field(name="👋  Goodbye Channel",      value=ch(goodbye_id), inline=True)
        embed.add_field(name="🔘  Goodbye Messages",     value="`Enabled`" if goodbye_on else "`Disabled`", inline=True)
        embed.add_field(name="👥  Member Counter",       value=ch(count_id),   inline=True)
        embed.add_field(name="🌐  Language",             value=lang_labels.get(lang, lang), inline=True)
        embed.set_thumbnail(url=interaction.guild.icon.url if interaction.guild.icon else icon)
        embed.set_footer(text="BloxPulse · Server Config  ·  Use /setup to make changes", icon_url=icon)
        await interaction.followup.send(embed=embed, ephemeral=True)


# ──────────────────────────────────────────────────────────────────────────────
#  Cog Setup
# ──────────────────────────────────────────────────────────────────────────────

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AdminCommands(bot))