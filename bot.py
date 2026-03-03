# ============================================================
#   BloxPulse | Roblox Version Monitor — bot.py
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
import random
import threading
import math as _math
from flask import Flask
from dotenv import load_dotenv

# Cargar variables de entorno desde .env si existe
load_dotenv()

from config import DISCORD_BOT_TOKEN, DEVELOPERS, PLATFORMS, CHECK_INTERVAL, BOT_NAME, BOT_AVATAR_URL, UPDATE_BANNER_URL
from core.checker import fetch_all, VersionInfo
from core.storage import get_version_data, update_version, get_all_guilds, get_guild_config, set_guild_config, get_all_announcement_channels
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
logger = logging.getLogger("BloxPulse")

# ── Platform Map ─────────────────────────────────────────────
# Maps slash command choice values → internal platform keys
_PLATFORM_CHOICES = {
    "windows": "WindowsPlayer",
    "mac":     "MacPlayer",
    "android": "AndroidApp",
    "ios":     "iOS",
}

# ── Bot Instance ─────────────────────────────────────────────

class BloxPulseBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(
            command_prefix="!",
            intents=intents,
            help_command=None
        )
        self.start_time = time.time()
        self.is_ready_flag = False

    async def setup_hook(self):
        logger.info("BloxPulse: Bot configured and slash commands synchronized.")
        # Ensure data dir exists
        _os.makedirs("data", exist_ok=True)
        self.monitor_task.start()
        # Background sync to avoid blocking the first few interactions
        asyncio.create_task(self.tree.sync())

    async def on_ready(self):
        logger.info(f"BloxPulse: Connected as {self.user} (ID: {self.user.id})")
        await self.change_presence(
            activity=discord.Activity(type=discord.ActivityType.watching, name="Roblox Updates")
        )
        self.is_ready_flag = True

    async def on_guild_join(self, guild: discord.Guild):
        """Welcome message and setup prompt."""
        logger.info(f"BloxPulse: Joined new guild: {guild.name} ({guild.id})")
        # Try to find a system channel or a general text channel
        target = guild.system_channel or next((c for c in guild.text_channels if c.permissions_for(guild.me).send_messages), None)
        if target:
            embed = discord.Embed(
                title="✨ ¡Gracias por invitar a BloxPulse!",
                description=(
                    "Estoy listo para monitorear las versiones de Roblox por ti.\n\n"
                    "**Configura el bot ahora:**\n"
                    "🔹 **Alertas de Roblox**: `/setup alerts` (Recomendado)\n"
                    "🔹 **Noticias de BloxPulse**: `/setup announcements` (Opcional)\n\n"
                    "Usa `/help` para ver la lista completa de comandos."
                ),
                color=0x00FFBB,
                timestamp=datetime.now(timezone.utc)
            )
            embed.set_thumbnail(url=BOT_AVATAR_URL)
            embed.set_footer(text="BloxPulse · Monitoring System", icon_url=BOT_AVATAR_URL)
            try: await target.send(embed=embed)
            except: pass

    @tasks.loop(seconds=CHECK_INTERVAL)
    async def monitor_task(self):
        """Background monitoring task — runs checker in a thread to avoid blocking."""
        try:
            logger.info("Starting monitoring cycle...")
            loop = asyncio.get_event_loop()
            # fetch_all now returns a dict of {key: VersionCheckResult}
            results = await loop.run_in_executor(None, fetch_all)

            for key, vi in results.items():
                if not vi:
                    continue # Skip if no data was fetched for this platform

                state = get_version_data(key)
                old_hash = state.get("current", "")

                if old_hash and old_hash != vi.version_hash:
                    logger.info(f"BloxPulse: Change detected for {key} -> {vi.version_hash}")
                    update_version(key, vi.version_hash) # Update the stored version
                    await self.broadcast_update(key, vi, old_hash)
                elif not old_hash:
                    # Initial run: store but don't broadcast
                    logger.info(f"BloxPulse: Initializing data for {key} -> {vi.version_hash}")
                    update_version(key, vi.version_hash)
                else:
                    logger.debug(f"BloxPulse: No change for {key}")

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

bot = BloxPulseBot()

# ═══════════════════════════════════════════════════════════════
# ── ANNOUNCEMENT MODAL ───────────────────────────────────────
# ═══════════════════════════════════════════════════════════════

class AnnouncementModal(discord.ui.Modal, title='🚀 Create BloxPulse Update'):
    ann_title = discord.ui.TextInput(
        label='Update Title',
        placeholder='e.g., BloxPulse v1.5: Final Rebranding',
        required=True,
        max_length=100
    )
    version = discord.ui.TextInput(
        label='Version Number',
        placeholder='e.g., v1.5.0',
        required=True,
        max_length=20
    )
    changes = discord.ui.TextInput(
        label='What\'s New?',
        placeholder='• Rebranded to BloxPulse\n• Added /donate command\n• Fixed mobile detection...',
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=2000
    )
    image_url = discord.ui.TextInput(
        label='Image URL (Optional)',
        placeholder='https://example.com/image.png',
        required=False
    )
    footer = discord.ui.TextInput(
        label='Custom Footer (Optional)',
        placeholder='Thanks for your support!',
        required=False,
        max_length=100
    )

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        
        # Build the premium announcement embed
        embed = discord.Embed(
            title=f"� BloxPulse Update: {self.ann_title.value}",
            description=(
                f"**New Version**: `{self.version.value}`\n\n"
                f"{self.changes.value}\n\n"
                f"---"
            ),
            color=0x00FFBB,
            timestamp=datetime.now(timezone.utc)
        )
        if self.image_url.value:
            embed.set_image(url=self.image_url.value)
        else:
            # Use the official update banner GIF by default
            embed.set_image(url=UPDATE_BANNER_URL)
        
        from config import OFFICIAL_SERVER_URL
        embed.add_field(
            name="🔗 Quick Links", 
            value=f"[Official Community]({OFFICIAL_SERVER_URL}) • [Bot Invite](https://discord.com/api/oauth2/authorize?client_id={bot.user.id}&permissions=8&scope=bot%20applications.commands)",
            inline=False
        )
        
        embed.set_thumbnail(url=BOT_AVATAR_URL)
        embed.set_footer(
            text=self.footer.value or "BloxPulse · The standard for Roblox Monitoring",
            icon_url=bot.user.avatar.url if bot.user.avatar else BOT_AVATAR_URL
        )

        channels = get_all_announcement_channels()
        count = 0
        failed = 0

        for channel_id in channels:
            channel = bot.get_channel(channel_id)
            if channel:
                try:
                    await channel.send(embed=embed)
                    count += 1
                except:
                    failed += 1
        
        await interaction.followup.send(
            f"✅ **Broadcast Complete!**\nSent to `{count}` servers.\nFailed in `{failed}` servers.",
            ephemeral=True
        )

# ═══════════════════════════════════════════════════════════════
# ── DONATION VIEW ────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════

class DonationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(
            label="Paypal: Cuentadepruebas750@gmail.com",
            style=discord.ButtonStyle.link,
            url="https://www.paypal.com/paypalme/YOUR_LINK_HERE", # Note: User provided email, typically we'd use a link
            emoji="💳"
        ))

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
    desc = description
    embed = discord.Embed(
        title=f"◈ {title}",
        description=desc,
        color=color,
        timestamp=datetime.now(timezone.utc),
    )
    if fields:
        for f in fields:
            embed.add_field(name=f[0], value=f[1], inline=f[2] if len(f) > 2 else True)
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)
    
    footers = [
        "BloxPulse Monitor 📡",
        "Global Roblox Tracker 🌍",
        "Monitoring with Pulse 🟢",
        "Stay updated, stay fast 🚀",
        "Professional Monitoring ◈ BloxPulse"
    ]
    embed.set_footer(text=f"{random.choice(footers)}", icon_url=BOT_AVATAR_URL)
    try:
        if interaction.response.is_done():
            return await interaction.followup.send(embed=embed, ephemeral=ephemeral)
        else:
            return await interaction.response.send_message(embed=embed, ephemeral=ephemeral)
    except discord.errors.NotFound:
        # Interaction expired or invalid
        logger.warning(f"Could not send premium response to {interaction.user}: Interaction already expired.")
    except Exception as e:
        logger.error(f"Error in premium_response: {e}")


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
        embed.set_footer(text="BloxPulse Monitor", icon_url=BOT_AVATAR_URL)
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
        embed.set_footer(text=f"{random.choice(['BloxPulse Monitor', 'Global BloxPulse', 'Global Roblox Monitoring State'])}", icon_url=BOT_AVATAR_URL)
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
    lang = get_guild_config(interaction.guild_id).get("language", "en")
    loop = asyncio.get_event_loop()
    versions = await loop.run_in_executor(None, fetch_all)

    embed = discord.Embed(
        title=f"◈ {get_text(lang, 'update_title', platform='Monitor')}",
        description=get_text(lang, "startup_desc"),
        color=0x5865F2,
        timestamp=datetime.now(timezone.utc),
    )
    for key, vi in versions.items():
        plat = PLATFORMS[key]
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

    embed.set_footer(text="BloxPulse · Live Check", icon_url=BOT_AVATAR_URL)
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
        embed.set_footer(text="BloxPulse Monitor", icon_url=BOT_AVATAR_URL)
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
            ).set_footer(text="BloxPulse Monitor", icon_url=BOT_AVATAR_URL),
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
    embed.set_footer(text=f"BloxPulse · Last {len(entries)} versions · Use dropdown to inspect", icon_url=BOT_AVATAR_URL)
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

    embed.set_footer(text="BloxPulse Monitor", icon_url=BOT_AVATAR_URL)
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
            ).set_footer(text="BloxPulse Monitor", icon_url=BOT_AVATAR_URL),
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
            ).set_footer(text="BloxPulse Monitor", icon_url=BOT_AVATAR_URL),
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
    embed.set_footer(text=f"BloxPulse · {len(entries)} versions available", icon_url=BOT_AVATAR_URL)
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

    def get_bar(ms):
        if ms < 0: return "⬛⬛⬛⬛⬛"
        filled = min(5, max(1, 5 - int(ms / 150)))
        return "🟩" * filled + "⬜" * (5 - filled)

    embed = discord.Embed(
        title="◈ BloxPulse · Red & Latencia",
        description="Estado detallado de la conexión con Discord y APIs.\n\u200b",
        color=0x2ECC71 if (ws_latency < 200 and roblox_ok) else 0xE67E22,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name=f"{ws_indicator} Latencia Discord", value=f"`{ws_latency} ms` {get_bar(ws_latency)}", inline=True)
    embed.add_field(name=f"{rbl_indicator} API Roblox",    value=f"`{http_ms if http_ms >= 0 else 'Timeout'} ms` {get_bar(http_ms)}", inline=True)
    embed.add_field(name="⏱️ Tiempo Activo",               value=f"`{h}h {m}m {s}s`", inline=True)
    embed.add_field(name="🔁 Ciclo de Monitoreo",          value=f"`{CHECK_INTERVAL}s`", inline=True)
    
    embed.set_footer(text=f"BloxPulse v1.5 · {random.choice(['Estable', 'Operativo', 'Online'])}", icon_url=BOT_AVATAR_URL)
    await interaction.followup.send(embed=embed, ephemeral=True)


@bot.tree.command(name="info", description="ℹ️ Learn more about BloxPulse and its developers.")
async def info_cmd(interaction: discord.Interaction):
    embed = discord.Embed(
        title="◈ BloxPulse Project",
        description=(
            "**BloxPulse** es un sistema de monitoreo global para Roblox, "
            "diseñado para ofrecer datos precisos y rápidos sobre actualizaciones de plataformas.\n\n"
            "**👑 Owner/Dev:** <@1420085090570207313>\n"
            "**🛠️ Tech Stack:** Python, discord.py, Flask, Docker.\n"
            "**🌎 Alcance:** Global (Windows, Mac, Android, iOS).\n\n"
            "Si te gusta el proyecto, considera usar `/donate` para apoyarnos."
        ),
        color=0x5865F2,
        timestamp=datetime.now(timezone.utc)
    )
    embed.set_thumbnail(url=BOT_AVATAR_URL)
    embed.set_image(url="https://images-ext-1.discordapp.net/external/E-hF_N79Uv0z_Jj_UoX4B2j7j0J6Y3tF6e7f_n7_j0/https/media.giphy.com/media/v1.Y2lkPTc5MGI3NjExM2I1YzM0ZGQzYjU0Y2EyZTM1ZTM1ZTM1ZTM1ZTM1ZTM1ZTM1ZTM1JmVwPXYxX2ludGVybmFsX2dpZl9ieV9pZCZjdD1n/3o7TKMGpxS7tHjN0_y/giphy.gif") # Nice aesthetic pulse gif
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="platforms", description="List all monitored platforms and their status.")
async def platforms(interaction: discord.Interaction):
    embed = discord.Embed(
        title="◈ Monitored Platforms",
        description="BloxPulse actively tracks version changes on the following platforms:\n\u200b",
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
    embed.set_footer(text="BloxPulse · Monitoring Node: US-West", icon_url=BOT_AVATAR_URL)
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="myid", description="Display your Discord user ID.")
async def myid(interaction: discord.Interaction):
    await premium_response(
        interaction,
        "Your Identity",
        f"**Username:** {interaction.user.mention}\n**User ID:** `{interaction.user.id}`",
        color=0x9B59B6,
    )


@bot.tree.command(name="invite", description="🚀 Get the link to add BloxPulse to your server.")
async def invite(interaction: discord.Interaction):
    lang = get_guild_config(interaction.guild_id).get("language", "en")
    invite_url = f"https://discord.com/api/oauth2/authorize?client_id={bot.user.id}&permissions=8&scope=bot%20applications.commands"
    
    embed = discord.Embed(
        title=get_text(lang, "invite_title"),
        description=get_text(lang, "invite_desc"),
        color=0x5865F2,
        timestamp=datetime.now(timezone.utc)
    )
    embed.set_thumbnail(url=BOT_AVATAR_URL)
    embed.set_footer(text="BloxPulse · Community Growth", icon_url=BOT_AVATAR_URL)
    
    view = discord.ui.View()
    view.add_item(discord.ui.Button(
        label=get_text(lang, "invite_btn"),
        style=discord.ButtonStyle.link,
        url=invite_url,
        emoji="🤖"
    ))
    
    await interaction.response.send_message(embed=embed, view=view)


@bot.tree.command(name="setup_server", description="🏗️ Power-User: Create a professional server setup with categories and channels.")
@app_commands.checks.has_permissions(manage_channels=True, manage_roles=True)
async def setup_server(interaction: discord.Interaction):
    """Automatically creates a professional server layout for BloxPulse."""
    guild = interaction.guild
    lang = get_guild_config(guild.id).get("language", "en")
    
    try:
        await interaction.response.defer(ephemeral=True)
    except Exception as e:
        logger.error(f"Initial defer failed for setup_server: {e}")
        return

    # Categories and Channels structure
    structure = {
        "◈ BloxPulse Info": ["#rules", "#announcements", "#official-server"],
        "◈ BloxPulse Monitoring": ["#roblox-alerts"],
        "◈ Community": ["#chat", "#bugs", "#suggestions"]
    }

    try:
        await interaction.followup.send(get_text(lang, "setup_server_start"), ephemeral=True)
        
        for cat_name, channels in structure.items():
            category = await guild.create_category(cat_name)
            for chan_name in channels:
                if "#announcements" in chan_name:
                    channel = await guild.create_text_channel(chan_name.replace("#", ""), category=category, topic="BloxPulse Official News")
                    # Auto-set as announcement channel for this guild
                    set_guild_config(guild.id, "announcement_channel_id", channel.id)
                elif "#roblox-alerts" in chan_name:
                    channel = await guild.create_text_channel(chan_name.replace("#", ""), category=category, topic="Roblox Version Updates")
                    # Auto-set as alert channel for this guild
                    set_guild_config(guild.id, "channel_id", channel.id)
                else:
                    await guild.create_text_channel(chan_name.replace("#", ""), category=category)
        
        await interaction.followup.send(get_text(lang, "setup_server_done"), ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Error creating template: `{e}`", ephemeral=True)


@bot.tree.command(name="help", description="Show a guide to all available commands.")
async def help_cmd(interaction: discord.Interaction):
    lang = get_guild_config(interaction.guild_id).get("language", "en")
    
    embed = discord.Embed(
        title=get_text(lang, "help_title"),
        description=get_text(lang, "help_desc"),
        color=0x5865F2,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(
        name=get_text(lang, "user_cmds"),
        value=(
            "`/check` — Live platform versions\n"
            "`/version` — History dropdown (last 7 days)\n"
            "`/download` — Get download link for current version\n"
            "`/compare` — Compare current vs. older version\n"
            "`/platforms` — All tracked platforms\n"
            "`/ping` — Bot & API latency\n"
            "`/donate` — Support BloxPulse development 💖\n"
            "`/invite` — Add BloxPulse to your server 🚀\n"
            "`/info` — Project details & credits ℹ️\n"
            "`/myid` — Your Discord ID\n"
            "`/help` — This menu"
        ),
        inline=False,
    )
    embed.add_field(
        name=get_text(lang, "admin_cmds"),
        value=(
            "`/setup alerts` — Configure alert channel\n"
            "`/setup announcements` — Configure news channel\n"
            "`/setup_server` — Create pro server template 🏗️\n"
            "`/language` — Set server language\n"
            "`/config` — View current server config"
        ),
        inline=False,
    )
    embed.add_field(
        name=get_text(lang, "owner_cmds"),
        value=(
            "`/broadcast` — Send an update via Form (Modal)\n"
            "`/status` — System diagnostics\n"
            "`/test` — Simulate a version update"
        ),
        inline=False,
    )
    embed.set_footer(text="BloxPulse Global Monitor", icon_url=BOT_AVATAR_URL)
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ═══════════════════════════════════════════════════════════════
# ── ADMIN COMMANDS (Manage Server) ──────────────────────────
# ═══════════════════════════════════════════════════════════════

# ── Admin Group ──
setup_group = app_commands.Group(name="setup", description="🔧 Configure BloxPulse settings for your server.")

@setup_group.command(name="alerts", description="📡 Set the channel for Roblox version alerts.")
@app_commands.describe(
    channel="Channel to receive updates",
    ping_role="Role to mention on each update (optional)"
)
async def setup_alerts(interaction: discord.Interaction, channel: discord.TextChannel, ping_role: Optional[discord.Role] = None):
    set_guild_config(interaction.guild_id, "channel_id", channel.id)
    if ping_role:
        set_guild_config(interaction.guild_id, "ping_role_id", ping_role.id)

    desc = (
        "**✅ Configuración de Alertas Completada**\n\n"
        f"● **Canal**: {channel.mention}\n"
        f"● **Ping**: {ping_role.mention if ping_role else '`Desactivado`'}\n\n"
        "*BloxPulse enviará alertas de versiones aquí.*"
    )
    await premium_response(interaction, "Monitor Setup", desc, color=0x2ECC71)

@setup_group.command(name="announcements", description="📢 Set the channel for BloxPulse news and updates.")
@app_commands.describe(channel="Channel to receive dev updates")
async def setup_announcements(interaction: discord.Interaction, channel: discord.TextChannel):
    set_guild_config(interaction.guild_id, "announcement_channel_id", channel.id)
    desc = (
        "**✅ Canal de Noticias Configurado**\n\n"
        f"● **Canal**: {channel.mention}\n\n"
        "*Aquí recibirás noticias sobre nuevas funciones del bot.*"
    )
    await premium_response(interaction, "News Setup", desc, color=0x3498DB)


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


# ═══════════════════════════════════════════════════════════════
# ── OWNER / DEV COMMANDS ────────────────────────────────────
# ═══════════════════════════════════════════════════════════════

@bot.tree.command(name="broadcast", description="Create and send a professional bot update (Owner only).")
@is_owner()
async def broadcast(interaction: discord.Interaction):
    await interaction.response.send_modal(AnnouncementModal())

@bot.tree.command(name="status", description="Advanced system diagnostics (Owner only).")
@is_owner()
async def status(interaction: discord.Interaction):
    uptime  = time.time() - bot.start_time
    h, m, s = int(uptime // 3600), int((uptime % 3600) // 60), int(uptime % 60)

    fields = [
        ("⏱️ Uptime",   f"`{h}h {m}m {s}s`",                 True),
        ("🏠 Guilds",   f"`{len(bot.guilds)} servers`",        True),
        ("📶 Latency",  f"`{round(bot.latency * 1000)}ms`",    True),
        ("🤖 Version",  "`BloxPulse v1.5 · Global`",            True),
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


@bot.tree.command(name="config", description="⚙️ View current BloxPulse configuration for this server.")
@has_manage_guild()
async def config_cmd(interaction: discord.Interaction):
    cfg       = get_guild_config(interaction.guild_id)
    ch_id     = cfg.get("channel_id")
    role_id   = cfg.get("ping_role_id")
    ann_id    = cfg.get("announcement_channel_id")
    lang      = cfg.get("language", "en")
    lang_names = {"en": "English 🇺🇸", "es": "Español 🇪🇸", "pt": "Português 🇧🇷", "ru": "Русский 🇷🇺", "fr": "Français 🇫🇷"}

    ch_str   = f"<#{ch_id}>" if ch_id else "`Not configured`"
    role_str = f"<@&{role_id}>" if role_id else "`None`"
    ann_str  = f"<#{ann_id}>" if ann_id else "`Not set`"

    desc = (
        f"● **Alerts Channel**: {ch_str}\n"
        f"● **Ping Role**: {role_str}\n"
        f"● **Updates Channel**: {ann_str}\n"
        f"● **Language**: {lang_names.get(lang, lang)}"
    )
    await premium_response(interaction, "Server Configuration", desc, color=0x3498DB)


@bot.tree.command(name="donate", description="💖 Support BloxPulse development and hosting.")
async def donate(interaction: discord.Interaction):
    embed = discord.Embed(
        title="💖 Support BloxPulse Development",
        description=(
            "Si te gusta **BloxPulse** y quieres apoyar su mantenimiento (servidores y café ☕), "
            "puedes hacerlo mediante **PayPal**.\n\n"
            "**PayPal**: `Cuentadepruebas750@gmail.com`\n\n"
            "¡Cada donación nos ayuda a seguir trayendo mejoras constantes y mantenernos 24/7!"
        ),
        color=0x00FFBB,
        timestamp=datetime.now(timezone.utc)
    )
    embed.set_thumbnail(url="https://cdn-icons-png.flaticon.com/512/174/174861.png")
    embed.set_footer(text="Gracias por tu apoyo ❤️", icon_url=interaction.user.avatar.url if interaction.user.avatar else None)
    
    view = DonationView()
    await interaction.response.send_message(embed=embed, view=view)


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
                ).set_footer(text="BloxPulse Monitor", icon_url=BOT_AVATAR_URL),
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
        ).set_footer(text="BloxPulse Monitor", icon_url=BOT_AVATAR_URL),
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
            ).set_footer(text="BloxPulse Monitor", icon_url=BOT_AVATAR_URL),
            ephemeral=True,
        )
    except Exception as e:
        await interaction.followup.send(f"❌ Cycle failed: `{e}`", ephemeral=True)


@bot.tree.command(name="guilds", description="📂 List all servers using BloxPulse (Owner only).")
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
    
    # Manejar caso de latencia NaN antes de la conexión inicial
    latency = "Connecting..."
    try:
        if not _math.isnan(bot.latency):
            latency = f"{round(bot.latency * 1000)}ms"
    except:
        pass

    return {
        "status": "online",
        "bot": "BloxPulse v1.5",
        "uptime": f"{h}h {m}m {s}s",
        "latency": latency,
        "guilds": len(bot.guilds)
    }

def run_web_server():
    port = int(_os.environ.get("PORT", 8080))
    # Flask en modo producción básico
    app.run(host="0.0.0.0", port=port)

if __name__ == "__main__":
    # Iniciar Flask en un hilo para UptimeRobot
    threading.Thread(target=run_web_server, daemon=True).start()
    
    # Register the group
    bot.tree.add_command(setup_group)
    
    bot.run(DISCORD_BOT_TOKEN)
