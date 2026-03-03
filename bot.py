# ============================================================
#   X-Blaze | Roblox Version Monitor — bot.py
#   Full Discord Bot — architected for stability and premium UX.
# ============================================================

import asyncio
import os as _os
import time
import logging
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime, timezone
from typing import Optional
import threading
from flask import Flask
from dotenv import load_dotenv

# Cargar variables de entorno desde .env si existe
load_dotenv()

from config import DISCORD_BOT_TOKEN, DEVELOPERS, PLATFORMS, CHECK_INTERVAL, BOT_NAME, BOT_AVATAR_URL
from core.checker import fetch_all, VersionInfo
from core.storage import get_version_data, update_version, get_all_guilds, get_guild_config, set_guild_config
from core.notifier import build_update_embed, create_language_view
from core.history import fetch_deploy_history, make_rdd_url
from core.i18n import get_text

# ── Logging ──────────────────────────────────────────────────
_LOG_DIR = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "logs")
_os.makedirs(_LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(_os.path.join(_LOG_DIR, "bot.log"), encoding="utf-8")
    ]
)
logger = logging.getLogger("X-Blaze")

# ── Platform Map ─────────────────────────────────────────────
# Maps slash command choice values → internal platform keys
_PLATFORM_CHOICES = {
    "windows": "WindowsPlayer",
    "mac":     "MacPlayer",
    "android": "AndroidApp",
    "ios":     "iOS",
}

# ── Bot Class ─────────────────────────────────────────────────
class XBlazeBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)
        self.start_time = time.time()

    async def setup_hook(self):
        self.monitor_task.start()
        await self.tree.sync()
        logger.info("Bot configured and slash commands synchronized.")

    async def on_ready(self):
        logger.info(f"Connected as {self.user} (ID: {self.user.id})")
        await self.change_presence(
            activity=discord.Activity(type=discord.ActivityType.watching, name="Roblox Updates")
        )

    @tasks.loop(seconds=CHECK_INTERVAL)
    async def monitor_task(self):
        """Background monitoring task — runs checker in a thread to avoid blocking."""
        try:
            logger.info("Starting monitoring cycle...")
            loop = asyncio.get_event_loop()
            current_versions = await loop.run_in_executor(None, fetch_all)

            for key, vi in current_versions.items():
                if not vi:
                    continue
                state = get_version_data(key)
                stored_hash = state.get("current")

                if stored_hash and stored_hash != vi.version_hash:
                    logger.info(f"Change detected in {key}: {stored_hash} -> {vi.version_hash}")
                    update_version(key, vi.version_hash)
                    await self.broadcast_update(key, vi, stored_hash)
                elif not stored_hash:
                    logger.info(f"Registering initial version for {key}: {vi.version_hash}")
                    update_version(key, vi.version_hash)

        except Exception as e:
            logger.error(f"Error in monitor_task: {e}", exc_info=True)

    async def broadcast_update(self, platform_key: str, vi: VersionInfo, prev_hash: str):
        """Sends update to all configured guild channels."""
        guilds_data = get_all_guilds()
        for gid_str, config in guilds_data.items():
            channel_id = config.get("channel_id")
            if not channel_id:
                continue
            channel = self.get_channel(channel_id)
            if not channel:
                continue

            lang    = config.get("language", "en")
            role_id = config.get("ping_role_id")
            mention = f"<@&{role_id}>" if role_id else None
            embed   = build_update_embed(platform_key, vi, prev_hash, lang)
            view    = create_language_view(platform_key, vi, prev_hash, lang)

            try:
                await channel.send(content=mention, embed=embed, view=view)
            except Exception as e:
                logger.warning(f"Could not send to guild {gid_str}: {e}")

bot = XBlazeBot()

# ── UI Helpers ────────────────────────────────────────────────

async def premium_response(
    interaction: discord.Interaction,
    title: str,
    description: str,
    color: int = 0x5865F2,
    ephemeral: bool = True,
    fields: list = None,
    thumbnail: str = None,
):
    """Send a consistent, branded embed response."""
    embed = discord.Embed(
        title=f"◈ {title}",
        description=description,
        color=color,
        timestamp=datetime.now(timezone.utc),
    )
    if fields:
        for f in fields:
            embed.add_field(name=f[0], value=f[1], inline=f[2] if len(f) > 2 else True)
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)
    embed.set_footer(text="X-Blaze Monitor", icon_url=BOT_AVATAR_URL)
    if interaction.response.is_done():
        await interaction.followup.send(embed=embed, ephemeral=ephemeral)
    else:
        await interaction.response.send_message(embed=embed, ephemeral=ephemeral)


def is_owner():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.id in DEVELOPERS:
            return True
        raise app_commands.CheckFailure(
            f"This command requires **Owner** access.\nYour ID: `{interaction.user.id}`"
        )
    return app_commands.check(predicate)


def has_manage_guild():
    async def predicate(interaction: discord.Interaction) -> bool:
        if interaction.user.guild_permissions.manage_guild:
            return True
        raise app_commands.CheckFailure("You need the `Manage Server` permission.")
    return app_commands.check(predicate)


def _ts_fmt(ts: datetime) -> str:
    """Format a datetime as Discord timestamp."""
    return f"<t:{int(ts.timestamp())}:R>"


# ═══════════════════════════════════════════════════════════════
# ── VERSION HISTORY VIEWS ────────────────────────────────────
# ═══════════════════════════════════════════════════════════════

class VersionHistorySelect(discord.ui.Select):
    """Dropdown of past versions for /version command."""
    def __init__(self, platform_key: str, entries: list[dict]):
        self.platform_key = platform_key
        self.entries = entries
        options = []
        for e in entries:
            short = e["version_hash"].replace("version-", "")[:16]
            ts_str = e["timestamp"].strftime("%b %d, %H:%M UTC")
            label = f"{e['version']}  —  {ts_str}"
            options.append(discord.SelectOption(
                label=label[:100],
                value=e["version_hash"],
                description=f"Hash: {short}",
                emoji="🏷️",
            ))
        super().__init__(
            placeholder="Select a version to inspect...",
            options=options,
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction):
        chosen_hash = self.values[0]
        entry = next((e for e in self.entries if e["version_hash"] == chosen_hash), None)
        if not entry:
            await interaction.response.send_message("Version not found.", ephemeral=True)
            return

        plat = PLATFORMS.get(self.platform_key, {})
        label = plat.get("label", self.platform_key)
        color = plat.get("color", 0x5865F2)
        short = chosen_hash.replace("version-", "")
        ts_discord = f"<t:{int(entry['timestamp'].timestamp())}:F>"
        rdd_url = make_rdd_url(self.platform_key, chosen_hash)

        embed = discord.Embed(
            title=f"◈ Version Detail — {label}",
            color=color,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="🏷️ Version",     value=f"`{entry['version']}`",  inline=True)
        embed.add_field(name="🔑 Build Hash",   value=f"`{short}`",             inline=True)
        embed.add_field(name="📅 Deployed",     value=ts_discord,               inline=False)
        if rdd_url:
            embed.add_field(name="⬇️ Download",  value=f"[◈ Download via RDD]({rdd_url})", inline=False)
        embed.set_thumbnail(url=plat.get("icon_url", BOT_AVATAR_URL))
        embed.set_footer(text="X-Blaze Monitor", icon_url=BOT_AVATAR_URL)
        await interaction.response.edit_message(embed=embed)


class VersionHistoryView(discord.ui.View):
    def __init__(self, platform_key: str, entries: list[dict]):
        super().__init__(timeout=120)
        self.add_item(VersionHistorySelect(platform_key, entries))


# ── Compare: previous version picker ─────────────────────────

class ComparePrevSelect(discord.ui.Select):
    """Dropdown of previous versions for /compare."""
    def __init__(self, platform_key: str, current_hash: str, current_ver: str, entries: list[dict]):
        self.platform_key = platform_key
        self.current_hash = current_hash
        self.current_ver  = current_ver
        # Remove current from options
        prev_entries = [e for e in entries if e["version_hash"] != current_hash]
        self.entries = prev_entries
        options = []
        for e in prev_entries:
            short = e["version_hash"].replace("version-", "")[:16]
            ts_str = e["timestamp"].strftime("%b %d, %H:%M UTC")
            label = f"{e['version']}  —  {ts_str}"
            options.append(discord.SelectOption(
                label=label[:100],
                value=e["version_hash"],
                description=f"Hash: {short}",
                emoji="📦",
            ))
        if not options:
            options = [discord.SelectOption(label="No previous versions found", value="none")]
        super().__init__(
            placeholder="Pick a previous version to compare...",
            options=options,
            min_values=1,
            max_values=1,
        )

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "none":
            await interaction.response.send_message("No previous versions to compare.", ephemeral=True)
            return

        chosen_hash = self.values[0]
        prev_entry = next((e for e in self.entries if e["version_hash"] == chosen_hash), None)
        if not prev_entry:
            await interaction.response.send_message("Version not found.", ephemeral=True)
            return

        plat = PLATFORMS.get(self.platform_key, {})
        label = plat.get("label", self.platform_key)
        color = plat.get("color", 0x5865F2)

        curr_short = self.current_hash.replace("version-", "")
        prev_short = chosen_hash.replace("version-", "")
        curr_rdd = make_rdd_url(self.platform_key, self.current_hash)
        prev_rdd = make_rdd_url(self.platform_key, chosen_hash)

        embed = discord.Embed(
            title=f"◈ Version Comparison — {label}",
            description=f"Comparing two builds for **{label}**.\n\u200b",
            color=color,
            timestamp=datetime.now(timezone.utc),
        )
        # Current
        embed.add_field(
            name="🟢 Current (Newer)",
            value=(
                f"**Version:** `{self.current_ver}`\n"
                f"**Hash:** `{curr_short}`\n"
                + (f"[⬇️ Download]({curr_rdd})" if curr_rdd else "*(no download)*")
            ),
            inline=True,
        )
        embed.add_field(name="\u200b", value="\u200b", inline=True)
        # Previous
        ts_discord = f"<t:{int(prev_entry['timestamp'].timestamp())}:F>"
        embed.add_field(
            name="🔴 Previous (Older)",
            value=(
                f"**Version:** `{prev_entry['version']}`\n"
                f"**Hash:** `{prev_short}`\n"
                f"**Deployed:** {ts_discord}\n"
                + (f"[⬇️ Download]({prev_rdd})" if prev_rdd else "*(no download)*")
            ),
            inline=True,
        )
        embed.set_thumbnail(url=plat.get("icon_url", BOT_AVATAR_URL))
        embed.set_footer(text="X-Blaze Monitor", icon_url=BOT_AVATAR_URL)
        await interaction.response.edit_message(embed=embed)


class ComparePrevView(discord.ui.View):
    def __init__(self, platform_key: str, current_hash: str, current_ver: str, entries: list[dict]):
        super().__init__(timeout=120)
        self.add_item(ComparePrevSelect(platform_key, current_hash, current_ver, entries))


# ═══════════════════════════════════════════════════════════════
# ── USER COMMANDS ────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════

@bot.tree.command(name="check", description="View current Roblox versions across all platforms.")
async def check(interaction: discord.Interaction):
    await interaction.response.defer()
    loop = asyncio.get_event_loop()
    versions = await loop.run_in_executor(None, fetch_all)

    embed = discord.Embed(
        title="◈ Live Version Monitor",
        description="Real-time Roblox build status across all supported platforms.\n\u200b",
        color=0x5865F2,
        timestamp=datetime.now(timezone.utc),
    )
    for key, vi in versions.items():
        plat = PLATFORMS[key]
        state = get_version_data(key)
        curr  = state.get("current", "")

        if vi:
            short = vi.version_hash.replace("version-", "")[:12]
            ver_line = f"```fix\n{vi.version}```"
            hash_line = f"`{short}...`"
        else:
            ver_line  = "```diff\n- Unavailable```"
            hash_line = "`—`"

        embed.add_field(
            name=f"● {plat['label']}",
            value=f"{ver_line}Hash: {hash_line}",
            inline=True,
        )

    embed.set_footer(text="X-Blaze · Live Check", icon_url=BOT_AVATAR_URL)
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="version", description="Browse version history for a platform (last 7 days).")
@app_commands.describe(platform="Platform to look up")
@app_commands.choices(platform=[
    app_commands.Choice(name="🪟 Windows", value="windows"),
    app_commands.Choice(name="🍎 macOS",   value="mac"),
    app_commands.Choice(name="🤖 Android", value="android"),
    app_commands.Choice(name="📱 iOS",     value="ios"),
])
async def version_cmd(interaction: discord.Interaction, platform: str):
    await interaction.response.defer()
    platform_key = _PLATFORM_CHOICES[platform]
    plat         = PLATFORMS[platform_key]
    label        = plat["label"]
    color        = plat["color"]

    loop = asyncio.get_event_loop()

    if platform in ("android", "ios"):
        # No public history — show current version
        versions = await loop.run_in_executor(None, fetch_all)
        vi = versions.get(platform_key)
        state = get_version_data(platform_key)
        curr  = state.get("current", "")

        embed = discord.Embed(
            title=f"◈ {label} — Current Version",
            description=f"*No public deployment history available for mobile platforms.*\n\u200b",
            color=color,
            timestamp=datetime.now(timezone.utc),
        )
        if vi:
            embed.add_field(name="🏷️ Version",   value=f"`{vi.version}`",                   inline=True)
            embed.add_field(name="🔑 Build Hash", value=f"`{vi.version_hash.replace('version-','')}`", inline=True)
            embed.add_field(name="🗂 Source",     value=f"`{vi.source}`",                   inline=True)
        else:
            embed.add_field(name="Status", value="```diff\n- Data unavailable```", inline=False)
        embed.set_thumbnail(url=plat["icon_url"])
        embed.set_footer(text="X-Blaze Monitor", icon_url=BOT_AVATAR_URL)
        await interaction.followup.send(embed=embed)
        return

    # Windows / Mac — show dropdown with last 7 days of history
    entries = await loop.run_in_executor(None, lambda: fetch_deploy_history(platform_key))

    if not entries:
        await interaction.followup.send(
            embed=discord.Embed(
                title=f"◈ {label} — No History",
                description="Could not fetch deployment history. The CDN may be temporarily unavailable.",
                color=0xE74C3C,
                timestamp=datetime.now(timezone.utc),
            ).set_footer(text="X-Blaze Monitor", icon_url=BOT_AVATAR_URL),
        )
        return

    embed = discord.Embed(
        title=f"◈ Version History — {label}",
        description=(
            f"Found **{len(entries)}** deployment(s) in the last 7 days.\n"
            f"Select a version below to inspect it.\n\u200b"
        ),
        color=color,
        timestamp=datetime.now(timezone.utc),
    )
    # Show quick summary of the 3 newest
    for i, e in enumerate(entries[:3]):
        short = e["version_hash"].replace("version-", "")[:16]
        ts    = f"<t:{int(e['timestamp'].timestamp())}:R>"
        embed.add_field(
            name=f"{'🥇' if i==0 else '🥈' if i==1 else '🥉'} {e['version']}",
            value=f"`{short}` · {ts}",
            inline=False,
        )

    embed.set_thumbnail(url=plat["icon_url"])
    embed.set_footer(text=f"X-Blaze · Last {len(entries)} versions · Use dropdown to inspect", icon_url=BOT_AVATAR_URL)
    view = VersionHistoryView(platform_key, entries)
    await interaction.followup.send(embed=embed, view=view)


@bot.tree.command(name="download", description="Get the download link for the current Roblox version.")
@app_commands.describe(platform="Platform to download")
@app_commands.choices(platform=[
    app_commands.Choice(name="🪟 Windows", value="windows"),
    app_commands.Choice(name="🍎 macOS",   value="mac"),
    app_commands.Choice(name="🤖 Android", value="android"),
    app_commands.Choice(name="📱 iOS",     value="ios"),
])
async def download(interaction: discord.Interaction, platform: str):
    await interaction.response.defer(ephemeral=True)
    platform_key = _PLATFORM_CHOICES[platform]
    plat  = PLATFORMS[platform_key]
    label = plat["label"]
    color = plat["color"]

    loop = asyncio.get_event_loop()
    versions = await loop.run_in_executor(None, fetch_all)
    vi = versions.get(platform_key)

    embed = discord.Embed(
        title=f"◈ Download — {label}",
        color=color,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_thumbnail(url=plat["icon_url"])

    if vi:
        short = vi.version_hash.replace("version-", "")
        embed.add_field(name="🏷️ Version",   value=f"`{vi.version}`",  inline=True)
        embed.add_field(name="🔑 Build Hash", value=f"`{short[:16]}…`", inline=True)
        embed.add_field(name="\u200b",        value="\u200b",            inline=True)

        rdd_url = make_rdd_url(platform_key, vi.version_hash)
        if rdd_url:
            embed.add_field(
                name="⬇️ Download Link",
                value=f"**[◈ Download {label} via RDD]({rdd_url})**\n*Links directly from Roblox's CDN*",
                inline=False,
            )
        elif platform == "android":
            embed.add_field(
                name="⬇️ Google Play Store",
                value="**[◈ Open on Google Play](https://play.google.com/store/apps/details?id=com.roblox.client)**",
                inline=False,
            )
        elif platform == "ios":
            embed.add_field(
                name="⬇️ App Store",
                value="**[◈ Open on App Store](https://apps.apple.com/app/roblox/id431946152)**",
                inline=False,
            )
    else:
        embed.description = "```diff\n- Version data unavailable. Try again shortly.\n```"

    embed.set_footer(text="X-Blaze Monitor", icon_url=BOT_AVATAR_URL)
    await interaction.followup.send(embed=embed, ephemeral=True)


@bot.tree.command(name="compare", description="Compare the current Roblox version with an older one.")
@app_commands.describe(platform="Platform to compare versions for")
@app_commands.choices(platform=[
    app_commands.Choice(name="🪟 Windows", value="windows"),
    app_commands.Choice(name="🍎 macOS",   value="mac"),
])
async def compare(interaction: discord.Interaction, platform: str):
    await interaction.response.defer()
    platform_key = _PLATFORM_CHOICES[platform]
    plat  = PLATFORMS[platform_key]
    label = plat["label"]
    color = plat["color"]

    loop = asyncio.get_event_loop()

    # Get current version
    versions = await loop.run_in_executor(None, fetch_all)
    vi = versions.get(platform_key)
    state = get_version_data(platform_key)
    curr_hash = state.get("current", "") or (vi.version_hash if vi else "")
    curr_ver  = vi.version if vi else curr_hash.replace("version-", "")

    if not curr_hash:
        await interaction.followup.send(
            embed=discord.Embed(
                title="◈ No Current Version",
                description="No version data available. Try `/check` first to initialize.",
                color=0xE74C3C,
            ).set_footer(text="X-Blaze Monitor", icon_url=BOT_AVATAR_URL),
        )
        return

    # Fetch history for the dropdown
    entries = await loop.run_in_executor(None, lambda: fetch_deploy_history(platform_key))

    if not entries or all(e["version_hash"] == curr_hash for e in entries):
        await interaction.followup.send(
            embed=discord.Embed(
                title="◈ No Previous Versions",
                description="No older versions found in the last 7 days to compare against.",
                color=0xE67E22,
            ).set_footer(text="X-Blaze Monitor", icon_url=BOT_AVATAR_URL),
        )
        return

    curr_short = curr_hash.replace("version-", "")[:16]
    embed = discord.Embed(
        title=f"◈ Compare Versions — {label}",
        description=(
            f"**Current version is fixed:** `{curr_ver}` (`{curr_short}…`)\n"
            f"Now pick a **previous version** from the dropdown below.\n\u200b"
        ),
        color=color,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_thumbnail(url=plat["icon_url"])
    embed.set_footer(text=f"X-Blaze · {len(entries)} versions available", icon_url=BOT_AVATAR_URL)
    view = ComparePrevView(platform_key, curr_hash, curr_ver, entries)
    await interaction.followup.send(embed=embed, view=view)


@bot.tree.command(name="ping", description="Check bot latency and Roblox API status.")
async def ping_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)

    ws_latency = round(bot.latency * 1000)

    # HTTP latency to Roblox API
    start = time.perf_counter()
    roblox_ok = False
    http_ms = 0
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://clientsettingscdn.roblox.com/v2/client-version/WindowsPlayer/channel/LIVE",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                roblox_ok = resp.status == 200
                http_ms = round((time.perf_counter() - start) * 1000)
    except Exception:
        http_ms = -1

    ws_indicator  = "🟢" if ws_latency < 100 else "🟡" if ws_latency < 250 else "🔴"
    rbl_indicator = "🟢" if roblox_ok and http_ms < 500 else "🔴"

    uptime = time.time() - bot.start_time
    h, m, s = int(uptime // 3600), int((uptime % 3600) // 60), int(uptime % 60)

    embed = discord.Embed(
        title="◈ X-Blaze · Network Status",
        description="Real-time latency and connectivity diagnostics.\n\u200b",
        color=0x2ECC71 if (ws_latency < 200 and roblox_ok) else 0xE67E22,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name=f"{ws_indicator} Discord WebSocket", value=f"`{ws_latency} ms`",                          inline=True)
    embed.add_field(name=f"{rbl_indicator} Roblox API",       value=f"`{http_ms if http_ms >= 0 else 'Timeout'} ms`", inline=True)
    embed.add_field(name="⏱️ Uptime",                         value=f"`{h}h {m}m {s}s`",                           inline=True)
    embed.add_field(name="🤖 Bot",                            value=f"`X-Blaze v1.4`",                              inline=True)
    embed.add_field(name="📡 Roblox API",                     value="`Online`" if roblox_ok else "`Unreachable`",   inline=True)
    embed.add_field(name="🔁 Check Interval",                 value=f"`{CHECK_INTERVAL}s`",                         inline=True)
    embed.set_footer(text="X-Blaze Monitor", icon_url=BOT_AVATAR_URL)
    await interaction.followup.send(embed=embed, ephemeral=True)


@bot.tree.command(name="platforms", description="List all monitored platforms and their status.")
async def platforms(interaction: discord.Interaction):
    embed = discord.Embed(
        title="◈ Monitored Platforms",
        description="X-Blaze actively tracks version changes on the following platforms:\n\u200b",
        color=0x5865F2,
        timestamp=datetime.now(timezone.utc),
    )
    for key, plat in PLATFORMS.items():
        state = get_version_data(key)
        curr  = state.get("current", "")
        display = curr.replace("version-", "") if curr else "No data"
        embed.add_field(
            name=f"● {plat['label']}",
            value=f"```\n{display}```",
            inline=True,
        )
    embed.set_footer(text="X-Blaze Monitor", icon_url=BOT_AVATAR_URL)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="myid", description="Display your Discord user ID.")
async def myid(interaction: discord.Interaction):
    await premium_response(
        interaction,
        "Your Identity",
        f"**Username:** {interaction.user.mention}\n**User ID:** `{interaction.user.id}`",
        color=0x9B59B6,
    )


@bot.tree.command(name="help", description="Show a guide to all available commands.")
async def help_cmd(interaction: discord.Interaction):
    embed = discord.Embed(
        title="◈ X-Blaze Command Guide",
        description="Full list of available commands by access level.\n\u200b",
        color=0x5865F2,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(
        name="👤 User Commands",
        value=(
            "`/check` — Live platform versions\n"
            "`/version` — History dropdown (last 7 days)\n"
            "`/download` — Get download link for current version\n"
            "`/compare` — Compare current vs. older version\n"
            "`/platforms` — All tracked platforms\n"
            "`/ping` — Bot & API latency\n"
            "`/myid` — Your Discord ID\n"
            "`/help` — This menu"
        ),
        inline=False,
    )
    embed.add_field(
        name="🛡️ Admin Commands (Manage Server)",
        value=(
            "`/setup` — Configure notification channel & role\n"
            "`/language` — Set server language\n"
            "`/config` — View current server config"
        ),
        inline=False,
    )
    embed.add_field(
        name="⚙️ Owner Commands",
        value=(
            "`/status` — System diagnostics\n"
            "`/test` — Simulate a version update\n"
            "`/reload` — Force immediate version check\n"
            "`/guilds` — List all guilds using the bot"
        ),
        inline=False,
    )
    embed.set_footer(text="X-Blaze Monitor", icon_url=BOT_AVATAR_URL)
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ═══════════════════════════════════════════════════════════════
# ── ADMIN COMMANDS (Manage Server) ──────────────────────────
# ═══════════════════════════════════════════════════════════════

@bot.tree.command(name="setup", description="Configure where update notifications are sent.")
@app_commands.describe(
    channel="Channel to receive updates",
    ping_role="Role to mention on each update (optional)"
)
@has_manage_guild()
async def setup(interaction: discord.Interaction, channel: discord.TextChannel, ping_role: Optional[discord.Role] = None):
    set_guild_config(interaction.guild_id, "channel_id", channel.id)
    if ping_role:
        set_guild_config(interaction.guild_id, "ping_role_id", ping_role.id)

    desc = (
        "**Server notification settings updated.**\n\n"
        f"● **Channel**: {channel.mention}\n"
        f"● **Ping Role**: {ping_role.mention if ping_role else '`None — no pings`'}\n\n"
        "*X-Blaze will now send Roblox update alerts to this channel.*"
    )
    await premium_response(interaction, "Server Setup Complete", desc, color=0x2ECC71)


@bot.tree.command(name="language", description="Set the default language for update notifications.")
@app_commands.describe(lang="Language for this server")
@has_manage_guild()
@app_commands.choices(lang=[
    app_commands.Choice(name="English 🇺🇸",   value="en"),
    app_commands.Choice(name="Español 🇪🇸",   value="es"),
    app_commands.Choice(name="Português 🇧🇷", value="pt"),
    app_commands.Choice(name="Русский 🇷🇺",   value="ru"),
    app_commands.Choice(name="Français 🇫🇷",  value="fr"),
])
async def language(interaction: discord.Interaction, lang: str):
    set_guild_config(interaction.guild_id, "language", lang)
    lang_names = {"en": "English", "es": "Español", "pt": "Português", "ru": "Русский", "fr": "Français"}
    await premium_response(
        interaction,
        "Language Updated",
        f"Notification language set to **{lang_names.get(lang, lang)}** for this server.",
        color=0x3498DB,
    )


@bot.tree.command(name="config", description="View current bot configuration for this server.")
@has_manage_guild()
async def config_cmd(interaction: discord.Interaction):
    cfg       = get_guild_config(interaction.guild_id)
    ch_id     = cfg.get("channel_id")
    role_id   = cfg.get("ping_role_id")
    lang      = cfg.get("language", "en")
    lang_names = {"en": "English 🇺🇸", "es": "Español 🇪🇸", "pt": "Português 🇧🇷", "ru": "Русский 🇷🇺", "fr": "Français 🇫🇷"}

    ch_str   = f"<#{ch_id}>" if ch_id else "`Not configured`"
    role_str = f"<@&{role_id}>" if role_id else "`None`"

    desc = (
        f"● **Notifications Channel**: {ch_str}\n"
        f"● **Ping Role**: {role_str}\n"
        f"● **Language**: {lang_names.get(lang, lang)}"
    )
    await premium_response(interaction, "Server Configuration", desc, color=0x3498DB)


# ═══════════════════════════════════════════════════════════════
# ── OWNER / DEV COMMANDS ────────────────────────────────────
# ═══════════════════════════════════════════════════════════════

@bot.tree.command(name="status", description="Advanced system diagnostics (Owner only).")
@is_owner()
async def status(interaction: discord.Interaction):
    uptime  = time.time() - bot.start_time
    h, m, s = int(uptime // 3600), int((uptime % 3600) // 60), int(uptime % 60)

    fields = [
        ("⏱️ Uptime",   f"`{h}h {m}m {s}s`",                 True),
        ("🏠 Guilds",   f"`{len(bot.guilds)} servers`",        True),
        ("📶 Latency",  f"`{round(bot.latency * 1000)}ms`",    True),
        ("🤖 Version",  "`X-Blaze v1.4 · Stable`",            True),
        ("🔁 Interval", f"`{CHECK_INTERVAL}s cycles`",         True),
        ("👑 Owner",    f"`{interaction.user.id}`",             True),
    ]
    await premium_response(
        interaction,
        "System Diagnostics",
        "Real-time internal performance metrics.\n\u200b",
        color=0x27AE60,
        fields=fields,
    )


@bot.tree.command(name="test", description="Send a preview of the latest update embed (Owner only).")
@app_commands.describe(platform="Platform to preview")
@app_commands.choices(platform=[
    app_commands.Choice(name="Windows", value="WindowsPlayer"),
    app_commands.Choice(name="macOS",   value="MacPlayer"),
    app_commands.Choice(name="Android", value="AndroidApp"),
    app_commands.Choice(name="iOS",     value="iOS"),
])
@is_owner()
async def test(interaction: discord.Interaction, platform: str):
    await interaction.response.defer(ephemeral=True)

    lang  = get_guild_config(interaction.guild_id).get("language", "en")
    state = get_version_data(platform)
    curr_hash = state.get("current", "")
    hist      = state.get("history", [])
    prev_hash = hist[0] if hist else curr_hash

    if curr_hash:
        vi = VersionInfo(
            platform_key=platform,
            version=curr_hash.replace("version-", ""),
            version_hash=curr_hash,
            channel="LIVE",
            source=f"Stored · {platform}",
        )
    else:
        loop = asyncio.get_event_loop()
        versions = await loop.run_in_executor(None, fetch_all)
        vi = versions.get(platform)
        if not vi:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="◈ No Version Data",
                    description=f"No stored or live version found for **{PLATFORMS[platform]['label']}**.\nTry `/check` first.",
                    color=0xE74C3C, timestamp=datetime.now(timezone.utc)
                ).set_footer(text="X-Blaze Monitor", icon_url=BOT_AVATAR_URL),
                ephemeral=True
            )
            return
        prev_hash = vi.version_hash

    embed   = build_update_embed(platform, vi, prev_hash, lang)
    view    = create_language_view(platform, vi, prev_hash, lang)
    role_id = get_guild_config(interaction.guild_id).get("ping_role_id")
    mention = f"<@&{role_id}>" if role_id else None

    await interaction.channel.send(content=mention, embed=embed, view=view)
    await interaction.followup.send(
        embed=discord.Embed(
            title="◈ Preview Sent",
            description=f"Embed sent for **{PLATFORMS[platform]['label']}**\nHash: `{vi.version_hash}`",
            color=0x27AE60, timestamp=datetime.now(timezone.utc)
        ).set_footer(text="X-Blaze Monitor", icon_url=BOT_AVATAR_URL),
        ephemeral=True
    )


@bot.tree.command(name="reload", description="Force an immediate version check (Owner only).")
@is_owner()
async def reload(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    loop = asyncio.get_event_loop()
    try:
        versions = await loop.run_in_executor(None, fetch_all)
        platform_list = ", ".join(k for k, v in versions.items() if v)
        await interaction.followup.send(
            embed=discord.Embed(
                title="◈ Monitoring Cycle Forced",
                description=f"✅ Fetched data for: `{platform_list}`\nAll changes will be broadcast if detected.",
                color=0x27AE60,
                timestamp=datetime.now(timezone.utc),
            ).set_footer(text="X-Blaze Monitor", icon_url=BOT_AVATAR_URL),
            ephemeral=True,
        )
    except Exception as e:
        await interaction.followup.send(f"❌ Cycle failed: `{e}`", ephemeral=True)


@bot.tree.command(name="guilds", description="List all servers using X-Blaze (Owner only).")
@is_owner()
async def guilds(interaction: discord.Interaction):
    guild_lines = []
    for g in bot.guilds:
        cfg    = get_guild_config(g.id)
        ch_id  = cfg.get("channel_id")
        status = f"<#{ch_id}>" if ch_id else "`Not configured`"
        guild_lines.append(f"● **{g.name}** (`{g.id}`) → {status}")

    desc = "\n".join(guild_lines) if guild_lines else "*No guilds found.*"
    await premium_response(interaction, f"Active Guilds ({len(bot.guilds)})", desc, color=0x9B59B6)


# ── Error Handler ─────────────────────────────────────────────

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, (app_commands.MissingPermissions, app_commands.CheckFailure)):
        await premium_response(interaction, "Access Denied", str(error), color=0xE74C3C)
    else:
        logger.error(f"Unhandled slash command error: {error}", exc_info=True)
        await premium_response(interaction, "Unexpected Error", f"`{type(error).__name__}: {error}`", color=0xE74C3C)

# ── Entry Point (Flask + Bot) ─────────────────────────────────

app = Flask(__name__)

@app.route('/')
def home():
    uptime = time.time() - bot.start_time
    h, m, s = int(uptime // 3600), int((uptime % 3600) // 60), int(uptime % 60)
    return {
        "status": "online",
        "bot": "X-Blaze v1.4",
        "uptime": f"{h}h {m}m {s}s",
        "latency": f"{round(bot.latency * 1000)}ms",
        "guilds": len(bot.guilds)
    }

def run_web_server():
    port = int(_os.environ.get("PORT", 8080))
    # Flask en modo producción básico
    app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    # Iniciar Flask en un hilo para UptimeRobot
    threading.Thread(target=run_web_server, daemon=True).start()
    bot.run(DISCORD_BOT_TOKEN)
