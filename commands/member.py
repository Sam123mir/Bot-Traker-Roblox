# commands/member.py
"""
Public member commands.
Provides version lookups, downloads, comparisons, and general bot information.
"""
from __future__ import annotations

import asyncio
import random
import time
from datetime import datetime, timezone
from typing import Optional

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from config import API_PLATFORM_MAPPING, BOT_AVATAR_URL, BOT_VERSION, CHECK_INTERVAL, PLATFORMS
from core.checker import VersionInfo, fetch_all
from core.history import fetch_deploy_history, make_rdd_url
from core.i18n import get_text
from core.notifier import build_announcement_embed, build_update_embed, create_language_view, premium_response
from core.storage import get_announcements, get_guild_config, get_version_data


# ──────────────────────────────────────────────────────────────────────────────
#  Constants & Design System
# ──────────────────────────────────────────────────────────────────────────────

# Unified color palette for embed consistency
COLOR_PRIMARY   = 0x5865F2   # Discord Blurple – main brand color
COLOR_SUCCESS   = 0x57F287   # Green – positive states
COLOR_WARNING   = 0xFEE75C   # Yellow – caution / info
COLOR_DANGER    = 0xED4245   # Red – errors / failures
COLOR_NEUTRAL   = 0x2B2D31   # Dark – neutral / system
COLOR_ACCENT    = 0x00E5FF   # Cyan – highlights / version info

MEDAL_ICONS     = ("🥇", "🥈", "🥉")
STATUS_DOT      = {True: "🟢", False: "🔴"}

RULES_LANGUAGES = [
    ("🇺🇸", "English",    "en"),
    ("🇪🇸", "Español",    "es"),
    ("🇧🇷", "Português",  "pt"),
    ("🇷🇺", "Русский",    "ru"),
    ("🇫🇷", "Français",   "fr"),
]

# ──────────────────────────────────────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _bot_icon(interaction: discord.Interaction) -> str:
    """Returns the bot's display avatar URL, falling back to the configured constant."""
    return interaction.client.user.display_avatar.url if interaction.client.user else BOT_AVATAR_URL


def _base_embed(
    title: str,
    description: str = "",
    color: int = COLOR_PRIMARY,
    *,
    timestamp: bool = True,
) -> discord.Embed:
    """Creates a consistently styled base embed."""
    embed = discord.Embed(
        title=title,
        description=description or discord.utils.MISSING,
        color=color,
        timestamp=datetime.now(timezone.utc) if timestamp else discord.utils.MISSING,
    )
    return embed


def _build_rules_embed(
    lang: str,
    interaction: discord.Interaction,
    guild_name: str,
) -> discord.Embed:
    """Builds the rules embed for the given language."""
    title = get_text(lang, "rules_title")
    body  = get_text(lang, "rules_body")
    icon  = _bot_icon(interaction)
    guild_icon = interaction.guild.icon.url if interaction.guild and interaction.guild.icon else icon

    embed = _base_embed(title, body, COLOR_SUCCESS)
    embed.set_thumbnail(url=guild_icon)
    embed.set_footer(text=f"{guild_name} · Rules ({lang.upper()})", icon_url=icon)
    return embed


# ──────────────────────────────────────────────────────────────────────────────
#  UI Components — Views & Selects
# ──────────────────────────────────────────────────────────────────────────────

class VersionHistorySelect(discord.ui.Select):
    """Lets users pick a version from the history dropdown to inspect it."""

    def __init__(self, platform_key: str, entries: list[dict]):
        self.platform_key = platform_key
        self.entries      = entries

        options = [
            discord.SelectOption(
                label=f"v{e['version']}",
                description=(
                    f"Hash: {e['version_hash'].replace('version-', '')[:14]}…"
                    f"  ·  {e['timestamp'].strftime('%Y-%m-%d %H:%M')} UTC"
                ),
                value=str(i),
                emoji=MEDAL_ICONS[i] if i < 3 else "📦",
            )
            for i, e in enumerate(entries[:25])
        ]
        super().__init__(
            placeholder="🔍  Select a version to inspect…",
            options=options,
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction):
        idx   = int(self.values[0])
        entry = self.entries[idx]
        lang  = get_guild_config(interaction.guild_id).get("language", "en")

        vi = VersionInfo(
            platform_key=self.platform_key,
            version=entry["version"],
            version_hash=entry["version_hash"],
            channel="LIVE",
            source="DeployHistory.txt",
        )

        icon  = _bot_icon(interaction)
        embed = build_update_embed(
            self.platform_key, vi, None,
            lang=lang, selected_hash=vi.version_hash, bot_icon=icon,
        )
        view = create_language_view(self.platform_key, vi, None, lang, is_build=False)
        await interaction.response.edit_message(embed=embed, view=view)


class VersionHistoryView(discord.ui.View):
    def __init__(self, platform_key: str, entries: list[dict]):
        super().__init__(timeout=120)
        self.add_item(VersionHistorySelect(platform_key, entries))

    async def on_timeout(self) -> None:
        # Disable the select when the view expires
        for item in self.children:
            item.disabled = True  # type: ignore[attr-defined]


# ──────────────────────────────────────────────────────────────────────────────

class ComparePrevSelect(discord.ui.Select):
    """Dropdown to pick a previous version for side-by-side comparison."""

    def __init__(
        self,
        platform_key: str,
        current_hash: str,
        current_ver: str,
        entries: list[dict],
    ):
        self.platform_key = platform_key
        self.current_hash = current_hash
        self.current_ver  = current_ver
        self.entries      = entries

        options = []
        seen    = {current_hash}
        for i, e in enumerate(entries):
            if e["version_hash"] in seen:
                continue
            seen.add(e["version_hash"])
            ts_str = e["timestamp"].strftime("%b %d · %H:%M UTC")
            options.append(discord.SelectOption(
                label=f"v{e['version']}",
                description=f"Released: {ts_str}",
                value=str(i),
                emoji="📋",
            ))
            if len(options) >= 25:
                break

        super().__init__(
            placeholder="📂  Pick an older version to compare…",
            options=options,
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction):
        idx       = int(self.values[0])
        old_entry = self.entries[idx]
        old_hash  = old_entry["version_hash"]
        old_ver   = old_entry["version"]

        plat      = PLATFORMS[self.platform_key]
        diff_url  = f"https://roblox-diff.latte.to/compare/{old_hash}/{self.current_hash}"
        icon      = _bot_icon(interaction)

        embed = _base_embed(
            title=f"◈  Version Comparison — {plat['label']}",
            description=(
                f"> 🔼 **Newer** · `{self.current_ver}`\n"
                f"> 🔽 **Older** · `{old_ver}`\n"
                f"> \u200b"
            ),
            color=plat["color"],
        )
        embed.add_field(
            name="🔗  Full Diff (External Tool)",
            value=f"**[➥ Open Detailed Comparison]({diff_url})**",
            inline=False,
        )
        embed.set_thumbnail(url=plat["icon_url"])
        embed.set_footer(text="BloxPulse · Precision Analysis", icon_url=icon)

        await interaction.response.edit_message(embed=embed, view=None)


class ComparePrevView(discord.ui.View):
    def __init__(
        self,
        platform_key: str,
        current_hash: str,
        current_ver: str,
        entries: list[dict],
    ):
        super().__init__(timeout=120)
        self.add_item(ComparePrevSelect(platform_key, current_hash, current_ver, entries))


# ──────────────────────────────────────────────────────────────────────────────

class UpdatesHistorySelect(discord.ui.Select):
    """Lets users browse through recent announcements."""

    def __init__(self, history: list[dict]):
        self.history = history
        options = [
            discord.SelectOption(
                label=ann.get("title", f"Update #{i + 1}"),
                description=f"📅  {datetime.fromisoformat(ann['timestamp']).strftime('%b %d, %Y')}",
                value=str(i),
                emoji="📣",
            )
            for i, ann in enumerate(history[:25])
        ]
        super().__init__(
            placeholder="📜  Browse past updates…",
            options=options,
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction):
        ann   = self.history[int(self.values[0])]
        embed = build_announcement_embed(ann)
        await interaction.response.edit_message(embed=embed, view=self.view)


class UpdatesHistoryView(discord.ui.View):
    def __init__(self, history: list[dict]):
        super().__init__(timeout=None)
        self.add_item(UpdatesHistorySelect(history))


# ──────────────────────────────────────────────────────────────────────────────

class RulesLanguageSelect(discord.ui.Select):
    """
    Language picker for /rules.
    Edits the existing message so the select stays visible after selection.
    """

    def __init__(self, guild_name: str):
        self.guild_name = guild_name
        options = [
            discord.SelectOption(label=label, value=code, emoji=flag)
            for flag, label, code in RULES_LANGUAGES
        ]
        super().__init__(
            placeholder="🌍  Change language / Cambiar idioma…",
            options=options,
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction):
        lang  = self.values[0]
        embed = _build_rules_embed(lang, interaction, self.guild_name)
        # Keep the view alive so the user can switch again
        await interaction.response.edit_message(embed=embed, view=self.view)


class RulesLanguageView(discord.ui.View):
    def __init__(self, guild_name: str):
        super().__init__(timeout=None)
        self.add_item(RulesLanguageSelect(guild_name))


# ──────────────────────────────────────────────────────────────────────────────
#  Member Commands Cog
# ──────────────────────────────────────────────────────────────────────────────

class MemberCommands(commands.Cog):
    """All public-facing member commands for BloxPulse."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── /help ────────────────────────────────────────────────────────────────

    @app_commands.command(name="help", description="📖  All commands & features — members and admins.")
    async def help_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        lang = get_guild_config(interaction.guild_id).get("language", "en")
        icon = _bot_icon(interaction)

        embed = _base_embed(
            title="✨  BloxPulse Help Center",
            description=(
                "Welcome to **BloxPulse** — the precision Roblox version tracking bot.\n"
                "Below you'll find every available command.\n\u200b"
            ),
            color=COLOR_PRIMARY,
        )
        embed.add_field(
            name="👥  Member Commands",
            value=(
                "`/version`  ·  Real-time Roblox version lookup\n"
                "`/download` ·  Get direct install links\n"
                "`/compare`  ·  Diff two platform versions\n"
                "`/updates`  ·  Browse latest bot announcements\n"
                "`/ping`     ·  Check bot & API latency\n"
                "`/rules`    ·  View server rules (multi-language)\n"
                "`/info`     ·  About BloxPulse\n"
                "`/invite`   ·  Add BloxPulse to another server\n"
                "`/donate`   ·  Support development"
            ),
            inline=False,
        )
        embed.add_field(
            name="🛡️  Admin / Owner Commands",
            value=(
                "`/setup alerts`         ·  Configure version alert channel\n"
                "`/setup server`         ·  Professional template setup\n"
                "`/setup announcements`  ·  Set news broadcast channel\n"
                "`/setup member-count`   ·  Dynamic voice counter\n"
                "`/welcome_system`       ·  Consolidated welcome config\n"
                "`/welcome_test`         ·  Preview welcome message\n"
                "`/language`             ·  Change server language\n"
                "`/config`               ·  View current server settings"
            ),
            inline=False,
        )
        embed.set_thumbnail(url=icon)
        embed.set_footer(text=f"BloxPulse {BOT_VERSION}  ·  Professional Monitoring", icon_url=icon)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /updates ─────────────────────────────────────────────────────────────

    @app_commands.command(name="updates", description="🕒  Browse the 3 most recent BloxPulse updates.")
    async def updates_history(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        history = get_announcements()

        if not history:
            embed = _base_embed(
                title="📭  No Announcements Yet",
                description="There are no announcements on record. Check back soon!",
                color=COLOR_DANGER,
            )
            icon = _bot_icon(interaction)
            embed.set_footer(text="BloxPulse Monitor", icon_url=icon)
            return await interaction.followup.send(embed=embed, ephemeral=True)

        embed = build_announcement_embed(history[0])
        view  = UpdatesHistoryView(history)

        await interaction.followup.send(
            content="### 📣  BloxPulse — Update History",
            embed=embed,
            view=view,
            ephemeral=True,
        )

    # ── /version ─────────────────────────────────────────────────────────────

    @app_commands.command(name="version", description="🔎  Browse version history for a platform (last 7 days).")
    @app_commands.describe(platform="The platform you want to inspect.")
    @app_commands.choices(platform=[
        app_commands.Choice(name="🪟  Windows", value="windows"),
        app_commands.Choice(name="🍎  macOS",   value="mac"),
        app_commands.Choice(name="🤖  Android", value="android"),
        app_commands.Choice(name="📱  iOS",     value="ios"),
    ])
    async def version_cmd(self, interaction: discord.Interaction, platform: str):
        await interaction.response.defer()

        platform_key = API_PLATFORM_MAPPING[platform]
        plat         = PLATFORMS[platform_key]
        icon         = _bot_icon(interaction)
        loop         = asyncio.get_event_loop()

        # ── Mobile platforms: no deploy history available ──────────────────
        if platform in ("android", "ios"):
            versions = await loop.run_in_executor(None, fetch_all)
            vi       = versions.get(platform_key)

            embed = _base_embed(
                title=f"◈  {plat['label']} — Current Version",
                description=(
                    "*Mobile platforms do not expose public deployment history.*\n\u200b"
                ),
                color=plat["color"],
            )
            if vi:
                short = vi.version_hash.replace("version-", "")
                embed.add_field(name="🏷️  Version",    value=f"`{vi.version}`",  inline=True)
                embed.add_field(name="🔑  Build Hash", value=f"`{short}`",        inline=True)
                embed.add_field(name="🗂  Source",     value=f"`{vi.source}`",    inline=True)
            else:
                embed.add_field(
                    name="⚠️  Status",
                    value="```diff\n- Version data currently unavailable.\n```",
                    inline=False,
                )

            embed.set_thumbnail(url=plat["icon_url"])
            embed.set_footer(text="BloxPulse Monitor", icon_url=icon)
            return await interaction.followup.send(embed=embed)

        # ── Desktop platforms: full history dropdown ───────────────────────
        entries = await loop.run_in_executor(None, lambda: fetch_deploy_history(platform_key))

        if not entries:
            embed = _base_embed(
                title=f"◈  {plat['label']} — History Unavailable",
                description=(
                    "Could not retrieve deployment history.\n"
                    "The CDN may be temporarily down — please try again shortly."
                ),
                color=COLOR_DANGER,
            )
            embed.set_footer(text="BloxPulse Monitor", icon_url=icon)
            return await interaction.followup.send(embed=embed)

        embed = _base_embed(
            title=f"◈  Version History — {plat['label']}",
            description=(
                f"Found **{len(entries)}** deployment(s) in the last 7 days.\n"
                f"Use the dropdown below to inspect any version.\n\u200b"
            ),
            color=plat["color"],
        )
        for i, e in enumerate(entries[:3]):
            short = e["version_hash"].replace("version-", "")[:16]
            ts    = f"<t:{int(e['timestamp'].timestamp())}:R>"
            embed.add_field(
                name=f"{MEDAL_ICONS[i]}  {e['version']}",
                value=f"`{short}…` · {ts}",
                inline=False,
            )

        embed.set_thumbnail(url=plat["icon_url"])
        embed.set_footer(
            text=f"BloxPulse · Showing {min(len(entries), 25)} of {len(entries)} version(s)",
            icon_url=icon,
        )

        view = VersionHistoryView(platform_key, entries)
        await interaction.followup.send(embed=embed, view=view)

    # ── /download ────────────────────────────────────────────────────────────

    @app_commands.command(name="download", description="⬇️  Get the direct download link for the current Roblox version.")
    @app_commands.describe(platform="The platform / edition you want to download.")
    @app_commands.choices(platform=[
        app_commands.Choice(name="🪟  Windows Client", value="windows"),
        app_commands.Choice(name="🪟  Windows Studio", value="studio"),
        app_commands.Choice(name="🍎  macOS Client",   value="mac"),
        app_commands.Choice(name="🍎  macOS Studio",   value="mac_studio"),
        app_commands.Choice(name="🤖  Android",        value="android"),
        app_commands.Choice(name="📱  iOS",            value="ios"),
    ])
    async def download(self, interaction: discord.Interaction, platform: str):
        await interaction.response.defer(ephemeral=True)

        platform_key = API_PLATFORM_MAPPING[platform]
        plat         = PLATFORMS[platform_key]
        icon         = _bot_icon(interaction)
        loop         = asyncio.get_event_loop()

        versions = await loop.run_in_executor(None, fetch_all)
        vi       = versions.get(platform_key)

        embed = _base_embed(
            title=f"⬇️  Download — {plat['label']}",
            color=plat["color"],
        )
        embed.set_thumbnail(url=plat["icon_url"])

        if vi:
            short = vi.version_hash.replace("version-", "")
            embed.description = (
                f"🔢  **Version** · `{vi.version}`\n"
                f"🔑  **Build Hash** · `{short}`"
            )
            if vi.fflag_count > 0:
                embed.description += f"\n🛠️  **FFlags Detected** · `{vi.fflag_count}`"
            embed.description += "\n\u200b"

            if platform_key in ("WindowsPlayer", "WindowsStudio", "MacPlayer", "MacStudio"):
                channel  = vi.channel
                base_cdn = "https://setup.rbxcdn.com"
                if channel and channel != "LIVE":
                    base_cdn += f"/channel/{channel.lower()}"

                is_mac    = "Mac" in platform_key
                is_studio = "Studio" in platform_key
                prefix    = "mac/" if is_mac else ""
                suffix    = (
                    ("RobloxStudio.zip"          if is_studio else "RobloxPlayer.zip")
                    if is_mac
                    else
                    ("RobloxStudioLauncherBeta.exe" if is_studio else "RobloxPlayerLauncher.exe")
                )
                direct_url = f"{base_cdn}/{prefix}{vi.version_hash}-{suffix}"
                embed.add_field(
                    name="📥  Direct Download",
                    value=f"**[➥ Download {plat['label']} ({suffix})]({direct_url})**",
                    inline=False,
                )

            elif platform == "android":
                embed.add_field(
                    name="🤖  Google Play Store",
                    value="**[➥ Open on Google Play](https://play.google.com/store/apps/details?id=com.roblox.client)**",
                    inline=False,
                )
            elif platform == "ios":
                embed.add_field(
                    name="📱  Apple App Store",
                    value="**[➥ Open on the App Store](https://apps.apple.com/app/roblox/id431946152)**",
                    inline=False,
                )
        else:
            embed.description = "```diff\n- Version data is currently unavailable.\n  Please try again in a few minutes.\n```"

        embed.set_footer(text="BloxPulse Monitor · Direct CDN Links", icon_url=icon)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /compare ─────────────────────────────────────────────────────────────

    @app_commands.command(name="compare", description="🔄  Compare the current version with an older one.")
    @app_commands.describe(platform="Desktop platform to compare (Windows or macOS).")
    @app_commands.choices(platform=[
        app_commands.Choice(name="🪟  Windows", value="windows"),
        app_commands.Choice(name="🍎  macOS",   value="mac"),
    ])
    async def compare(self, interaction: discord.Interaction, platform: str):
        await interaction.response.defer()

        platform_key = API_PLATFORM_MAPPING[platform]
        plat         = PLATFORMS[platform_key]
        icon         = _bot_icon(interaction)
        loop         = asyncio.get_event_loop()

        versions  = await loop.run_in_executor(None, fetch_all)
        vi        = versions.get(platform_key)
        state     = get_version_data(platform_key)
        curr_hash = state.get("current", "") or (vi.version_hash if vi else "")
        curr_ver  = vi.version if vi else curr_hash.replace("version-", "")

        if not curr_hash:
            embed = _base_embed(
                title="⚠️  No Data Available",
                description="Could not retrieve the current version. Please try again shortly.",
                color=COLOR_DANGER,
            )
            embed.set_footer(text="BloxPulse Monitor", icon_url=icon)
            return await interaction.followup.send(embed=embed)

        entries = await loop.run_in_executor(None, lambda: fetch_deploy_history(platform_key))

        if not entries or all(e["version_hash"] == curr_hash for e in entries):
            embed = _base_embed(
                title="📭  No Older Versions Found",
                description=(
                    "There are no older versions in the deployment history to compare against.\n"
                    "Check back after the next Roblox update."
                ),
                color=COLOR_WARNING,
            )
            embed.set_footer(text="BloxPulse Monitor", icon_url=icon)
            return await interaction.followup.send(embed=embed)

        embed = _base_embed(
            title=f"🔄  Compare Versions — {plat['label']}",
            description=(
                f"> 🔼 **Current** · `{curr_ver}`\n"
                f"Use the dropdown to select an older version.\n\u200b"
            ),
            color=plat["color"],
        )
        embed.set_thumbnail(url=plat["icon_url"])
        embed.set_footer(text="BloxPulse · Version Comparisons", icon_url=icon)

        view = ComparePrevView(platform_key, curr_hash, curr_ver, entries)
        await interaction.followup.send(embed=embed, view=view)

    # ── /ping ────────────────────────────────────────────────────────────────

    @app_commands.command(name="ping", description="📡  Check bot latency and Roblox API status.")
    async def ping_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        ws_ms = round(self.bot.latency * 1000)

        # HTTP round-trip to Roblox CDN
        t0 = time.perf_counter()
        roblox_ok = False
        http_ms   = -1
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(
                    "https://clientsettingscdn.roblox.com/v2/client-version/WindowsPlayer/channel/LIVE",
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    roblox_ok = resp.status == 200
                    http_ms   = round((time.perf_counter() - t0) * 1000)
        except Exception:
            pass

        uptime = time.time() - getattr(self.bot, "start_time", time.time())
        h = int(uptime // 3600)
        m = int((uptime % 3600) // 60)
        s = int(uptime % 60)

        icon = _bot_icon(interaction)

        embed = _base_embed(
            title="📡  BloxPulse · System Status",
            description="\u200b",
            color=COLOR_SUCCESS if (ws_ms < 100 and roblox_ok) else COLOR_WARNING,
        )
        embed.add_field(
            name=f"{STATUS_DOT[ws_ms < 100]}  Discord Gateway",
            value=f"`{ws_ms} ms`",
            inline=True,
        )
        embed.add_field(
            name=f"{STATUS_DOT[roblox_ok]}  Roblox CDN",
            value=f"`{http_ms} ms`" if http_ms >= 0 else "`Timeout`",
            inline=True,
        )
        embed.add_field(
            name="⏱️  Uptime",
            value=f"`{h}h {m}m {s}s`",
            inline=True,
        )
        embed.set_footer(text=f"BloxPulse {BOT_VERSION}", icon_url=icon)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /info ────────────────────────────────────────────────────────────────

    @app_commands.command(name="info", description="ℹ️  Learn more about BloxPulse.")
    async def info_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        icon = _bot_icon(interaction)

        embed = _base_embed(
            title="✎  About BloxPulse",
            description=(
                "**BloxPulse** is a precision Roblox version tracking bot.\n"
                "It monitors every platform 24/7 and delivers instant alerts when a new build goes live.\n\u200b"
            ),
            color=COLOR_PRIMARY,
        )
        embed.add_field(name="👨‍💻  Developer",  value="<@1420085090570207313>",        inline=True)
        embed.add_field(name="⚙️  Built with",  value="Python · discord.py · Flask",  inline=True)
        embed.add_field(name="🤖  Version",     value=f"`{BOT_VERSION}`",              inline=True)
        embed.set_thumbnail(url=icon)
        embed.set_footer(text="BloxPulse · Innovation & Transparency", icon_url=icon)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /invite ──────────────────────────────────────────────────────────────

    @app_commands.command(name="invite", description="🔗  Add BloxPulse to your server.")
    async def invite(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        lang = get_guild_config(interaction.guild_id).get("language", "en")
        icon = _bot_icon(interaction)

        url = (
            f"https://discord.com/api/oauth2/authorize"
            f"?client_id={self.bot.user.id}"
            f"&permissions=380288"
            f"&scope=bot%20applications.commands"
        )

        embed = _base_embed(
            title="🚀  Add BloxPulse to Your Server!",
            description=(
                "Get real-time Roblox version alerts, multi-platform monitoring, "
                "and advanced server tools — all in one bot.\n\u200b"
            ),
            color=COLOR_PRIMARY,
        )
        embed.set_thumbnail(url=icon)
        embed.set_footer(text="BloxPulse · Free to use", icon_url=icon)

        view = discord.ui.View()
        view.add_item(discord.ui.Button(
            label=get_text(lang, "invite_btn"),
            style=discord.ButtonStyle.link,
            url=url,
            emoji="✨",
        ))
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    # ── /donate ──────────────────────────────────────────────────────────────

    @app_commands.command(name="donate", description="💖  Support BloxPulse development.")
    async def donate(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        icon = _bot_icon(interaction)

        embed = _base_embed(
            title="💖  Support BloxPulse",
            description=(
                "BloxPulse is free and always will be.\n"
                "If you enjoy using the bot, a small donation goes a long way!\n\u200b"
            ),
            color=0x00FFBB,
        )
        embed.add_field(
            name="💳  PayPal",
            value="`Cuentadepruebas750@gmail.com`",
            inline=False,
        )
        embed.set_footer(text="Thank you for your support ♥", icon_url=icon)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /rules ───────────────────────────────────────────────────────────────

    @app_commands.command(name="rules", description="⚖️  View community rules or publish them to a channel.")
    @app_commands.describe(
        channel="(Admin only) Publish rules publicly to this channel.",
    )
    async def rules_cmd(
        self,
        interaction: discord.Interaction,
        channel: Optional[discord.TextChannel] = None,
    ):
        """
        Displays server rules with a language picker.
        If a channel is provided, posts the rules there publicly (requires Manage Server).
        """
        # Permission guard for public publishing
        if channel:
            if not interaction.permissions.manage_guild:
                return await interaction.response.send_message(
                    "❌  You need the **Manage Server** permission to publish rules to a channel.",
                    ephemeral=True,
                )

        guild_name = interaction.guild.name if interaction.guild else "Server"
        lang       = "en"  # Default language; user can switch via the dropdown
        embed      = _build_rules_embed(lang, interaction, guild_name)

        # ── Publish to a specific channel ─────────────────────────────────
        if channel:
            await interaction.response.defer(ephemeral=True)
            try:
                # Post without language picker when publishing (keeps it clean)
                await channel.send(embed=embed)
                await interaction.followup.send(
                    f"✅  Rules successfully published to {channel.mention}.",
                    ephemeral=True,
                )
            except discord.Forbidden:
                await interaction.followup.send(
                    f"❌  I don't have permission to send messages in {channel.mention}.",
                    ephemeral=True,
                )
            return

        # ── Ephemeral view with language picker ───────────────────────────
        view = RulesLanguageView(guild_name)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


# ──────────────────────────────────────────────────────────────────────────────
#  Cog Setup
# ──────────────────────────────────────────────────────────────────────────────

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MemberCommands(bot))