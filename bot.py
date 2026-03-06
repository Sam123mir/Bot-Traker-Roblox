import os as _os
import asyncio
import re
import time
import logging
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks
from datetime import datetime, timezone
from typing import Optional, List
import random
import threading
import math as _math
from flask import Flask
from dotenv import load_dotenv

# Cargar variables de entorno desde .env si existe
load_dotenv()

from config import DISCORD_BOT_TOKEN, DEVELOPERS, PLATFORMS, CHECK_INTERVAL, BOT_NAME, BOT_AVATAR_URL, UPDATE_BANNER_URL, BOT_VERSION
from core.checker import fetch_all, VersionInfo
from core.storage import (
    get_version_data, update_version, backfill_history,
    get_all_guilds, get_guild_config, set_guild_config,
    get_all_announcement_channels, save_announcement, get_announcements
)
from core.notifier import build_update_embed, create_language_view
from core.history import fetch_deploy_history, make_rdd_url
from core.i18n import get_text


from discord.ext import tasks

# ── Global Status Tracking ────────────────────────────────────
API_STATUS = {"WindowsPlayer": True, "MacPlayer": True, "AndroidApp": True, "iOS": True}

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
        intents.members = True
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
        # 1. Backfill history for Windows/Mac on startup
        from core.history import fetch_deploy_history
        import config
        for plat in ["WindowsPlayer", "MacPlayer"]:
            logger.info(f"BloxPulse: Backfilling history for {plat}...")
            entries = fetch_deploy_history(plat, days=config.HISTORY_DAYS)
            backfill_history(plat, entries)

        # 2. Update dynamic status for all guilds and check for new ones
        configured_guilds = get_all_guilds()
        for guild in self.guilds:
            await update_dynamic_status(guild)
            # If guild is not in our database, it's "new" (maybe joined while bot was off)
            if guild.id not in configured_guilds:
                await self.on_guild_join(guild)

    async def on_member_join(self, member: discord.Member):
        """Update member count channel."""
        await update_dynamic_status(member.guild)

    async def on_member_remove(self, member: discord.Member):
        """Update member count channel."""
        await update_dynamic_status(member.guild)

    async def on_guild_join(self, guild: discord.Guild):
        """Welcome message and setup prompt with inviter detection."""
        logger.info(f"BloxPulse: Joined new guild: {guild.name} ({guild.id})")
        
        # 1. Try to find who invited the bot (Audit Logs)
        inviter = None
        if guild.me.guild_permissions.view_audit_log:
            try:
                async for entry in guild.audit_logs(limit=3, action=discord.AuditLogAction.bot_add):
                    if entry.target.id == self.user.id:
                        inviter = entry.user
                        break
            except Exception as e:
                logger.debug(f"Could not fetch audit logs in {guild.name}: {e}")

        # 2. Select the best channel to send the message
        # Priority: System Channel > General/Text Channel with permissions
        target = guild.system_channel
        if not target or not target.permissions_for(guild.me).send_messages:
            # Fallback to the first available text channel
            target = next((c for c in guild.text_channels if c.permissions_for(guild.me).send_messages and c.permissions_for(guild.me).embed_links), None)

        if target:
            inviter_mention = f" {inviter.mention}" if inviter else ""
            embed = discord.Embed(
                title="✨ Welcome to BloxPulse | Roblox Monitoring",
                description=(
                    f"Hello{inviter_mention}! Thank you for trusting **BloxPulse** to stay on top of Roblox deployments.\n\n"
                    "⬢ **Security & Privacy**\n"
                    "We are a bot focused exclusively on technical data. We do NOT require Administrator permissions or access to personal server data.\n\n"
                    "✨ **Quick Start Guide**\n"
                    "To activate monitoring, use the following commands:\n"
                    "↳ `/setup alerts` — Set the channel to receive version alerts.\n"
                    "↳ `/setup announcements` — Receive important news about bot infrastructure.\n\n"
                    "Use `/help` to explore all capabilities."
                ),
                color=0x00D1FF, # Professional Cyan
                timestamp=datetime.now(timezone.utc)
            )
            
            avatar_url = self.user.display_avatar.url if self.user else BOT_AVATAR_URL
            embed.set_thumbnail(url=avatar_url)
            embed.set_image(url=UPDATE_BANNER_URL)
            embed.set_footer(text="Precision · Speed · Transparency", icon_url=avatar_url)
            
            try:
                await target.send(embed=embed)
                logger.info(f"Sent welcome message to {guild.name}")
            except Exception as e:
                logger.warning(f"Failed to send welcome message in {guild.name}: {e}")


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

                # 1. Official Update Check (clientsettingscdn)
                state = get_version_data(key)
                old_update_hash = state.get("last_update", "")

                if old_update_hash and old_update_hash != vi.version_hash:
                    logger.info(f"BloxPulse: Official Update detected for {key} -> {vi.version_hash}")
                    update_version(key, vi.version_hash, is_official=True)
                    await self.broadcast_update(key, vi, old_update_hash, is_build=False)
                elif not old_update_hash:
                    logger.info(f"BloxPulse: Initializing update data for {key} -> {vi.version_hash}")
                    update_version(key, vi.version_hash, is_official=True)

                # 2. Build Detection (DeployHistory.txt)
                # Only for Windows/Mac
                if key in ["WindowsPlayer", "MacPlayer"]:
                    history_entries = fetch_deploy_history(key, days=1)
                    if history_entries:
                        latest_build = history_entries[0]
                        latest_build_hash = latest_build["version_hash"]
                        old_build_hash = state.get("last_build", "")
                        
                        # Trigger if it's a NEW build hash AND it's NOT the current official unit
                        if latest_build_hash != old_build_hash and latest_build_hash != vi.version_hash:
                            logger.info(f"BloxPulse: Pre-release Build detected for {key} -> {latest_build_hash}")
                            update_version(key, latest_build_hash, is_official=False)
                            
                            # Create a VersionInfo for the build
                            build_vi = VersionInfo(
                                platform_key=key,
                                version=latest_build["version"],
                                version_hash=latest_build_hash,
                                channel="Build-Testing",
                                source="DeployHistory.txt"
                            )
                            await self.broadcast_update(key, build_vi, old_build_hash or old_update_hash, is_build=True)
                        elif latest_build_hash == old_build_hash:
                            logger.debug(f"BloxPulse: No new build for {key}")

        except Exception as e:
            logger.error(f"Error in monitor_task: {e}", exc_info=True)

    @monitor_task.before_loop
    async def before_monitor(self):
        await self.wait_until_ready()

    async def broadcast_update(self, platform_key: str, vi: VersionInfo, prev_hash: str, is_build: bool = False):
        """Sends update/build alert to all configured guild channels."""
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
            # Fetch last 4 versions for the history field
            state = get_version_data(platform_key)
            history_hashes = state.get("history", [])[:4]
            history_timestamps = state.get("timestamps", {})
            history_data = []
            for h in history_hashes:
                history_data.append({"hash": h, "date": history_timestamps.get(h, "Unknown")})

            avatar_url = self.user.display_avatar.url if self.user else bot.user.display_avatar.url if bot.user else BOT_AVATAR_URL
            embed   = build_update_embed(platform_key, vi, prev_hash, lang, bot_icon=avatar_url, is_build=is_build, history_data=history_data)
            view    = create_language_view(platform_key, vi, prev_hash, lang)

            try:
                await channel.send(content=mention, embed=embed, view=view)
            except Exception as e:
                logger.warning(f"Could not send to guild {gid_str}: {e}")

bot = BloxPulseBot()

# ═══════════════════════════════════════════════════════════════
# ── ANNOUNCEMENT MODAL ───────────────────────────────────────
# ═══════════════════════════════════════════════════════════════

class AnnouncementModal(discord.ui.Modal, title='✨ Create BloxPulse Update'):
    ann_title = discord.ui.TextInput(
        label='Update Title',
        placeholder='e.g., BloxPulse v1.7: Premium Preview Stage',
        required=True,
        max_length=100
    )
    version = discord.ui.TextInput(
        label='Version Number',
        placeholder='e.g., v1.7.0',
        required=True,
        max_length=20
    )
    changes = discord.ui.TextInput(
        label='What\'s New?',
        placeholder='• Added live preview to broadcast\n• Improved visual layout\n• Stable monitoring system...',
        style=discord.TextStyle.paragraph,
        required=True,
        max_length=2000
    )
    footer = discord.ui.TextInput(
        label='Custom Footer (Optional)',
        placeholder='Thanks for your support!',
        required=False,
        max_length=100
    )

    async def on_submit(self, interaction: discord.Interaction):
        # Build the preview embed
        # Use user title directly but ensure it has the icon. 
        # If user includes "BloxPulse" we don't need to add it again.
        display_title = self.ann_title.value
        if "BloxPulse" not in display_title:
            display_title = f"BloxPulse: {display_title}"

        # Format changes with professional bullets
        lines = self.changes.value.split('\n')
        formatted_changes = []
        for line in lines:
            line = line.strip()
            if not line: continue
            # If it doesn't start with a bullet, add one
            if not any(line.startswith(b) for b in ['•', '-', '*', '◈', '❱']):
                line = f"◈ {line}"
            formatted_changes.append(f"> {line}")
        
        desc = "\n".join(formatted_changes)
        embed = discord.Embed(
            title=f"◈ {display_title}",
            description=(
                f"*Nueva versión:* `{self.version.value}`\n\n"
                f"{desc}"
            ),
            color=0x00FFBB,
            timestamp=datetime.now(timezone.utc)
        )
        embed.set_image(url=UPDATE_BANNER_URL)
        
        from config import OFFICIAL_SERVER_URL
        embed.add_field(
            name="⬢ Enlaces rápidos", 
            value=f"**[Comunidad oficial]({OFFICIAL_SERVER_URL})** | **[Invitación de bot](https://discord.com/api/oauth2/authorize?client_id={bot.user.id}&permissions=380288&scope=bot%20applications.commands)**",
            inline=False
        )
        
        avatar_url = bot.user.display_avatar.url if bot.user else BOT_AVATAR_URL
        embed.set_thumbnail(url=avatar_url)
        embed.set_footer(
            text=self.footer.value or "BloxPulse · The standard for Roblox Monitoring",
            icon_url=avatar_url
        )

        # Store data for history (used in confirm)
        self.ann_data = {
            "title": display_title,
            "version": self.version.value,
            "changes": self.changes.value,
            "footer": self.footer.value or "BloxPulse · The standard for Roblox Monitoring",
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

        # Show the preview view
        view = AnnouncementReviewView(embed, self.ann_data)
        await interaction.response.send_message(
            content="⬢ **Live Preview**: This is how the update will look. Check for typos!",
            embed=embed, 
            view=view, 
            ephemeral=True
        )


def build_announcement_embed(ann_data: dict) -> discord.Embed:
    """Helper to maintain a consistent style across broadcast and history."""
    formatted_changes = "\n".join([f"> {line}" for line in ann_data["changes"].split("\n") if line.strip()])
    
    embed = discord.Embed(
        title=f"◈ {ann_data['title']}",
        description=(
            f"*Nueva versión:* `{ann_data['version']}`\n\n"
            f"{formatted_changes}"
        ),
        color=0x00FFBB,
        timestamp=datetime.fromisoformat(ann_data["timestamp"])
    )
    embed.set_image(url=UPDATE_BANNER_URL)
    
    from config import OFFICIAL_SERVER_URL
    embed.add_field(
        name="⬢ Quick Links", 
        value=f"**[Official Community]({OFFICIAL_SERVER_URL})** | **[Bot Invitation](https://discord.com/api/oauth2/authorize?client_id={bot.user.id}&permissions=380288&scope=bot%20applications.commands)**",
        inline=False
    )
    
    # Use real bot avatar for thumbnail instead of the Flaticon dots
    avatar_url = bot.user.display_avatar.url if bot.user else BOT_AVATAR_URL
    embed.set_thumbnail(url=avatar_url)
    embed.set_footer(text=ann_data["footer"], icon_url=avatar_url)
    return embed


class AnnouncementReviewView(discord.ui.View):
    """Stage 2: Confirm or Cancel the broadcast."""
    def __init__(self, embed: discord.Embed, ann_data: dict):
        super().__init__(timeout=300)
        self.embed = embed
        self.ann_data = ann_data

    @discord.ui.button(label="✨ Send Broadcast", style=discord.ButtonStyle.success, emoji=None)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        
        # Save to history
        save_announcement(self.ann_data)
        
        # Prepare the view for the broadcast (Dropdown with history)
        history = get_announcements()
        broadcast_view = UpdatesHistoryView(history) if history else None

        channels = get_all_announcement_channels()
        count = 0
        failed = 0

        # Disable buttons on the preview stage
        for item in self.children:
            item.disabled = True
        await interaction.edit_original_response(view=self)

        for channel_id in channels:
            channel = bot.get_channel(channel_id)
            if channel:
                try:
                    await channel.send(embed=self.embed, view=broadcast_view)
                    count += 1
                except:
                    failed += 1
        
        await interaction.followup.send(
            f"✨ **Broadcast Complete!**\nSent to `{count}` servers.\nFailed in `{failed}` servers.",
            ephemeral=True
        )
        self.stop()

    @discord.ui.button(label="⬢ Cancel", style=discord.ButtonStyle.danger, emoji=None)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("⚠ Broadcast cancelled. Nothing was sent.", ephemeral=True)
        for item in self.children:
            item.disabled = True
        await interaction.edit_original_response(view=self)
        self.stop()

# ═══════════════════════════════════════════════════════════════
# ── DONATION VIEW ────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════

class DonationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(
            label="Paypal: Cuentadepruebas750@gmail.com",
            style=discord.ButtonStyle.link,
            url="https://www.paypal.com/paypalme/Cuentadepruebas750", 
            emoji=None
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
        "BloxPulse Monitor ⬢",
        "Global Roblox Tracker ⬢",
        "Monitoring with Pulse ✨",
        "Stay updated, stay fast ✨",
        "Professional Monitoring ◈ BloxPulse"
    ]
    avatar_url = bot.user.display_avatar.url if bot.user else BOT_AVATAR_URL
    embed.set_footer(text=f"{random.choice(footers)}", icon_url=avatar_url)
    
    if thumbnail == bot.user.display_avatar.url if bot.user else BOT_AVATAR_URL or not thumbnail:
        embed.set_thumbnail(url=avatar_url)
    else:
        embed.set_thumbnail(url=thumbnail)

    try:
        if interaction.response.is_done():
            return await interaction.followup.send(embed=embed, ephemeral=ephemeral)
        else:
            return await interaction.response.send_message(embed=embed, ephemeral=ephemeral)
    except discord.errors.NotFound:
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
                emoji=None,
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
        embed.add_field(name="𖤘 Version",     value=f"`{entry['version']}`",  inline=True)
        embed.add_field(name="⚿ Build Hash",   value=f"`{short}`",             inline=True)
        embed.add_field(name="⬢ Deployed",     value=ts_discord,               inline=False)
        if rdd_url:
            embed.add_field(name="↳ Download",  value=f"[◈ Download via RDD]({rdd_url})", inline=False)
        avatar_url = bot.user.display_avatar.url if bot.user else BOT_AVATAR_URL
        embed.set_thumbnail(url=plat.get("icon_url", avatar_url))
        embed.set_footer(text="BloxPulse Monitor", icon_url=avatar_url)
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
        embed.set_thumbnail(url=plat.get("icon_url", bot.user.display_avatar.url if bot.user else BOT_AVATAR_URL))
        embed.set_footer(text=f"{random.choice(['BloxPulse Monitor', 'Global BloxPulse', 'Global Roblox Monitoring State'])}", icon_url=bot.user.display_avatar.url if bot.user else BOT_AVATAR_URL)
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

    embed.set_footer(text="BloxPulse · Live Check", icon_url=bot.user.display_avatar.url if bot.user else BOT_AVATAR_URL)
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
        embed.set_footer(text="BloxPulse Monitor", icon_url=bot.user.display_avatar.url if bot.user else BOT_AVATAR_URL)
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
            ).set_footer(text="BloxPulse Monitor", icon_url=bot.user.display_avatar.url if bot.user else BOT_AVATAR_URL),
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
    embed.set_footer(text=f"BloxPulse · Last {len(entries)} versions · Use dropdown to inspect", icon_url=bot.user.display_avatar.url if bot.user else BOT_AVATAR_URL)
    view = VersionHistoryView(platform_key, entries)
    await interaction.followup.send(embed=embed, view=view)


@bot.tree.command(name="download", description="Get the download link for the current Roblox version.")
@app_commands.describe(platform="Platform to download")
@app_commands.choices(platform=[
    app_commands.Choice(name="⬢ Windows", value="windows"),
    app_commands.Choice(name="⬢ macOS",   value="mac"),
    app_commands.Choice(name="⬢ Android", value="android"),
    app_commands.Choice(name="⬢ iOS",     value="ios"),
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
        embed.add_field(name="𖤘 Version",   value=f"`{vi.version}`",  inline=True)
        embed.add_field(name="⚿ Build Hash", value=f"`{short[:16]}…`", inline=True)
        embed.add_field(name="\u200b",        value="\u200b",            inline=True)

        rdd_url = make_rdd_url(platform_key, vi.version_hash)
        if rdd_url:
            embed.add_field(
                name="↳ Download Link",
                value=f"**[➥ Download {label} via RDD]({rdd_url})**\n*Links directly from Roblox's CDN*",
                inline=False,
            )
        elif platform == "android":
            embed.add_field(
                name="↳ Google Play Store",
                value="**[➥ Open on Google Play](https://play.google.com/store/apps/details?id=com.roblox.client)**",
                inline=False,
            )
        elif platform == "ios":
            embed.add_field(
                name="↳ App Store",
                value="**[➥ Open on App Store](https://apps.apple.com/app/roblox/id431946152)**",
                inline=False,
            )
    else:
        embed.description = "```diff\n- Version data unavailable. Try again shortly.\n```"

    embed.set_footer(text="BloxPulse Monitor", icon_url=bot.user.display_avatar.url if bot.user else BOT_AVATAR_URL)
    await interaction.followup.send(embed=embed, ephemeral=True)


@bot.tree.command(name="compare", description="Compare the current Roblox version with an older one.")
@app_commands.describe(platform="Platform to compare versions for")
@app_commands.choices(platform=[
    app_commands.Choice(name="⬢ Windows", value="windows"),
    app_commands.Choice(name="⬢ macOS",   value="mac"),
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
            ).set_footer(text="BloxPulse Monitor", icon_url=bot.user.display_avatar.url if bot.user else BOT_AVATAR_URL),
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
            ).set_footer(text="BloxPulse Monitor", icon_url=bot.user.display_avatar.url if bot.user else BOT_AVATAR_URL),
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
    embed.set_footer(text=f"BloxPulse · {len(entries)} versions available", icon_url=bot.user.display_avatar.url if bot.user else BOT_AVATAR_URL)
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
        title="◈ BloxPulse · Network & Latency",
        description="Detailed status of Discord connection and APIs.\n\u200b",
        color=0x2ECC71 if (ws_latency < 200 and roblox_ok) else 0xE67E22,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(name=f"{ws_indicator} Discord Latency", value=f"`{ws_latency} ms` {get_bar(ws_latency)}", inline=True)
    embed.add_field(name=f"{rbl_indicator} Roblox API",    value=f"`{http_ms if http_ms >= 0 else 'Timeout'} ms` {get_bar(http_ms)}", inline=True)
    embed.add_field(name="⏱︎ Uptime",               value=f"`{h}h {m}m {s}s`", inline=True)
    embed.add_field(name="⟳ Monitoring Cycle",          value=f"`{CHECK_INTERVAL}s`", inline=True)
    
    embed.set_footer(text=f"BloxPulse {BOT_VERSION} · {random.choice(['Stable', 'Operational', 'Online'])}", icon_url=bot.user.display_avatar.url if bot.user else BOT_AVATAR_URL)
    await interaction.followup.send(embed=embed, ephemeral=True)


@bot.tree.command(name="info", description="ⓘ Learn more about BloxPulse and its developers.")
async def info_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    embed = discord.Embed(
        title="✎ BloxPulse Project",
        description=(
            "**BloxPulse** is a global monitoring system for Roblox, "
            "designed to deliver precise and fast data on platform updates.\n\n"
            "**♚ Owner/Dev:** <@1420085090570207313>\n"
            "**⚒︎ Tech Stack:** Python, discord.py, Flask, Docker.\n"
            "**ᯓ ✈︎ Scope:** Global (Windows, Mac, Android, iOS).\n\n"
            "If you like the project, consider using `/donate` to support us."
        ),
        color=0x5865F2,
        timestamp=datetime.now(timezone.utc)
    )
    avatar_url = bot.user.display_avatar.url if bot.user else BOT_AVATAR_URL
    embed.set_thumbnail(url=avatar_url)
    embed.set_footer(text="BloxPulse · Innovation & Transparency", icon_url=avatar_url)
    await interaction.followup.send(embed=embed)


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
    embed.set_footer(text="BloxPulse · Monitoring Node: US-West", icon_url=bot.user.display_avatar.url if bot.user else BOT_AVATAR_URL)
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
    await interaction.response.defer(ephemeral=True)
    lang = get_guild_config(interaction.guild_id).get("language", "en")
    # Permissions: Send Messages, Embed Links, Attach Files, Use External Emojis, Add Reactions, Read History, View Channels, View Audit Log (380288)
    invite_url = f"https://discord.com/api/oauth2/authorize?client_id={bot.user.id}&permissions=380288&scope=bot%20applications.commands"
    
    embed = discord.Embed(
        title="🚀 Take Monitoring to the Next Level!",
        description=(
            "Add **BloxPulse** to your community and enjoy the most advanced Roblox tracker on the market.\n\n"
            "♖ **Guaranteed Security**\n"
            "• **No Admin Required**: We only ask for essential permissions to function.\n"
            "• **Total Privacy**: We don't read your messages; we only monitor the Roblox API.\n"
            "• **Performance**: Optimized to not cause lag in your server.\n\n"
            "☑ **Premium Features**\n"
            "• Instant alerts for Windows, Mac, iOS, and Android.\n"
            "• Detailed history and direct download links.\n"
            "• Automatic multi-language support (English by default)."
        ),
        color=0x5865F2,
        timestamp=datetime.now(timezone.utc)
    )
    avatar_url = bot.user.display_avatar.url if bot.user else BOT_AVATAR_URL
    embed.set_thumbnail(url=avatar_url)
    embed.set_footer(text="BloxPulse · Innovation & Transparency", icon_url=avatar_url)
    
    view = discord.ui.View()
    view.add_item(discord.ui.Button(
        label=get_text(lang, "invite_btn"),
        style=discord.ButtonStyle.link,
        url=invite_url,
        emoji="✨"
    ))
    
    await interaction.followup.send(embed=embed, view=view)


@bot.tree.command(name="setup_server", description="🏗️ Power-User: Create a professional server setup with categories and channels.")
@app_commands.checks.has_permissions(manage_channels=True, manage_roles=True)
async def setup_server(interaction: discord.Interaction):
    """Automatically creates a professional server layout for BloxPulse."""
    guild = interaction.guild
    lang = get_guild_config(guild.id).get("language", "en")
    
    try:
        await interaction.response.defer(ephemeral=True)
    except: return

    # Preview what will be created
    desc = (
        "**CHANNEL STRUCTURE**\n"
        "┇═════ STATUS ═════┇\n"
        "❱ Members: [Live Count]\n"
        f"❱ Bot Version: {BOT_VERSION}\n\n"
        "┇═════ API STATUS ═════┇\n"
        "❱ Windows: [🟢/🔴]\n"
        "❱ Mac: [🟢/🔴]\n"
        "❱ Android: [🟢/🔴]\n"
        "❱ iOS: [🟢/🔴]\n\n"
        "┇═════ INFO ═════┇\n"
        "❱ Rules | ❱ Announcements | ❱ Official\n\n"
        "┇═════ MONITOR ═════┇\n"
        "❱ Roblox-Alerts | ❱ Stats\n\n"
        "┇═════ COMMUNITY ═════┇\n"
        "❱ General | ❱ Bug-Reports | ❱ Suggestions\n\n"
        "**PROFESSIONAL ROLES**\n"
        "♕ 》BloxPulse Owner (Owner)\n"
        "♖ 》BloxPulse Staff (Staff)\n"
        "♙ 》Verified Member (Verified)"
    )
    
    embed = discord.Embed(
        title="🏗️ Professional Layout Configuration",
        description=f"Are you ready to apply this structure to **{interaction.guild.name}**?\n\n{desc}",
        color=0x00FFBB,
        timestamp=datetime.now(timezone.utc)
    )
    embed.set_footer(text="BloxPulse · Template Engine", icon_url=bot.user.display_avatar.url)
    
    view = SetupConfirmView()
    await interaction.followup.send(embed=embed, view=view, ephemeral=True)

class SetupConfirmView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="🚀 Apply Template", style=discord.ButtonStyle.green)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="⏳ Applying changes, please wait...", embed=None, view=None)
        await deploy_template(interaction.guild)
        await interaction.followup.send("✨ **Server configured successfully!** The professional structure has been deployed.", ephemeral=True)

    @discord.ui.button(label="⬢ Cancel", style=discord.ButtonStyle.red)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.edit_message(content="⚠ Setup cancelled.", embed=None, view=None)

async def deploy_template(guild: discord.Guild):
    # Cleanup: Delete previous BloxPulse channels and roles
    # We look for prefixes used in previous versions
    for channel in guild.channels:
        if any(p in channel.name for p in ["BloxPulse", "❱", "┇═════"]):
            try: await channel.delete()
            except: pass
    
    prefixes = ["♕ 》", "🛡️ 》", "🛡 》", "👤 》", "♙ 》", "✱ 》", "BloxPulse"]
    for role in guild.roles:
        if any(p in role.name for p in prefixes):
            try: await role.delete()
            except: pass

    # Roles creation
    roles_data = [
        {"name": "⬢ BloxPulse Owner",   "color": discord.Color.gold(),   "perm": discord.Permissions.all()},
        {"name": "⬢ BloxPulse Staff",   "color": discord.Color.blue(),   "perm": discord.Permissions(manage_messages=True, kick_members=True, mute_members=True)},
        {"name": "⬢ Verified Member", "color": discord.Color.light_grey(), "perm": discord.Permissions.none()},
        {"name": "⬢ Ping Version Roblox", "color": discord.Color.red(), "perm": discord.Permissions.none(), "mention": True},
    ]
    
    for r_info in roles_data:
        await guild.create_role(
            name=r_info["name"], 
            color=r_info["color"], 
            permissions=r_info["perm"], 
            hoist=True,
            mentionable=r_info.get("mention", False)
        )

    # Categories and Channels structure
    structure = [
        ("⬢ STATUS", [
            ("⬢ Members: 0", discord.ChannelType.voice),
            (f"⬢ Bot Version: {BOT_VERSION}", discord.ChannelType.voice)
        ]),
        ("⬢ STATUS APIs", [
            ("⬢ Windows: Online", discord.ChannelType.voice),
            ("⬢ Mac: Online", discord.ChannelType.voice),
            ("⬢ Android: Online", discord.ChannelType.voice),
            ("⬢ iOS: Online", discord.ChannelType.voice)
        ]),
        ("⬢ INFO", [
            ("⬢ rules", discord.ChannelType.text),
            ("⬢ announcements", discord.ChannelType.text),
            ("⬢ official", discord.ChannelType.text)
        ]),
        ("⬢ MONITOR", [
            ("⬢ roblox-alerts", discord.ChannelType.text),
            ("⬢ stats", discord.ChannelType.text)
        ]),
        ("⬢ COMMUNITY", [
            ("⬢ general", discord.ChannelType.text),
            ("⬢ bug-reports", discord.ChannelType.text),
            ("⬢ suggestions", discord.ChannelType.text)
        ])
    ]

    for cat_name, channels in structure:
        category = await guild.create_category(cat_name)
        for chan_name, chan_type in channels:
            overwrites = {}
            if "STATUS" in cat_name:
                overwrites = {guild.default_role: discord.PermissionOverwrite(connect=False)}
            
            if chan_type == discord.ChannelType.voice:
                channel = await guild.create_voice_channel(chan_name, category=category, overwrites=overwrites)
                if "Members" in chan_name:
                    await channel.edit(name=f"⬢ Members: {guild.member_count}")
            else:
                channel = await guild.create_text_channel(chan_name.replace(" ", "-"), category=category)
                if "announcements" in chan_name:
                    set_guild_config(guild.id, "announcement_channel_id", channel.id)
                    await channel.edit(topic="BloxPulse Official News")
                elif "roblox-alerts" in chan_name:
                    set_guild_config(guild.id, "channel_id", channel.id)
                    await channel.edit(topic="Roblox Version Updates")

# Note: Member count updates are already handled by the BloxPulseBot class events

async def update_member_count_channel(guild):
    for channel in guild.voice_channels:
        if "Members:" in channel.name:
            try:
                await channel.edit(name=f"⬢ Members: {guild.member_count}")
            except: pass


@bot.tree.command(name="help", description="📖 All command details & features.")
async def help_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    lang = get_guild_config(interaction.guild_id).get("language", "en")
    
    embed = discord.Embed(
        title="✨ BloxPulse | Command Guide",
        description=(
            "Welcome to **BloxPulse**. Use these commands to monitor Roblox deployments in real-time.\n\u200b"
        ),
        color=0x5865F2,
        timestamp=datetime.now(timezone.utc),
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
    embed.set_footer(text="BloxPulse Global Monitor", icon_url=bot.user.display_avatar.url)
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
async def setup_alerts(interaction: discord.Interaction, channel: discord.abc.GuildChannel, ping_role: Optional[discord.Role] = None):
    if not hasattr(channel, "send"):
        return await premium_response(interaction, "Invalid Channel", "Please select a text, news, or voice channel where the bot can speak.", color=0xE74C3C)

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
async def setup_announcements(interaction: discord.Interaction, channel: discord.abc.GuildChannel):
    if not hasattr(channel, "send"):
        return await premium_response(interaction, "Invalid Channel", "Please select a text-based channel.", color=0xE74C3C)

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

@bot.tree.command(name="updates", description="🕒 View the 3 most recent BloxPulse updates.")
async def updates_history(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    history = get_announcements()
    if not history:
        return await premium_response(interaction, "History Empty", "No announcements have been sent yet.", color=0xE74C3C)

    # Show latest by default with the dropdown
    latest_embed = build_announcement_embed(history[0])
    view = UpdatesHistoryView(history)
    
    await interaction.followup.send(
        content="⬢ **BloxPulse Update History**",
        embed=latest_embed,
        view=view,
        ephemeral=True
    )


class UpdatesHistorySelect(discord.ui.Select):
    def __init__(self, history: list[dict]):
        options = []
        for i, ann in enumerate(history):
            dt = datetime.fromisoformat(ann["timestamp"])
            date_str = dt.strftime("%b %d, %Y")
            options.append(discord.SelectOption(
                label=f"{ann['title'][:50]}",
                description=f"Version: {ann['version']} — {date_str}",
                value=str(i),
                emoji=None
            ))
        super().__init__(placeholder="Switch to another update...", options=options)
        self.history = history

    async def callback(self, interaction: discord.Interaction):
        ann = self.history[int(self.values[0])]
        embed = build_announcement_embed(ann)
        # Keep the view so they can switch again
        await interaction.response.edit_message(embed=embed, view=self.view)

class UpdatesHistoryView(discord.ui.View):
    def __init__(self, history: list[dict]):
        super().__init__(timeout=None)
        self.add_item(UpdatesHistorySelect(history))

@bot.tree.command(name="status", description="Advanced system diagnostics (Owner only).")
@is_owner()
async def status(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    uptime  = time.time() - bot.start_time
    h, m, s = int(uptime // 3600), int((uptime % 3600) // 60), int(uptime % 60)

    fields = [
        ("⏱︎ Uptime",   f"`{h}h {m}m {s}s`",                 True),
        ("⬢ Guilds",   f"`{len(bot.guilds)} servers`",        True),
        ("📶 Latency",  f"`{round(bot.latency * 1000)}ms`",    True),
        ("⬢ Version",  f"`{BOT_VERSION} · Premium`",           True),
        ("⟳ Interval", f"`{CHECK_INTERVAL}s cycles`",         True),
        ("♚ Owner",    f"`{interaction.user.id}`",             True),
    ]
    await premium_response(
        interaction,
        "System Diagnostics",
        "Real-time internal performance metrics.\n\u200b",
        color=0x27AE60,
        fields=fields,
    )


@bot.tree.command(name="config", description="⬢ View current BloxPulse configuration for this server.")
@has_manage_guild()
async def config_cmd(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    cfg       = get_guild_config(interaction.guild_id)
    ch_id     = cfg.get("channel_id")
    role_id   = cfg.get("ping_role_id")
    ann_id    = cfg.get("announcement_channel_id")
    lang      = cfg.get("language", "en")
    lang_names = {"en": "English (US)", "es": "Español (ES)", "pt": "Português (BR)", "ru": "Русский (RU)", "fr": "Français (FR)"}

    ch_str   = f"<#{ch_id}>" if ch_id else "`Not configured`"
    role_str = f"<@&{role_id}>" if role_id else "`None`"
    ann_str  = f"<#{ann_id}>" if ann_id else "`Not set`"

    desc = (
        f"↳ **Alerts Channel**: {ch_str}\n"
        f"↳ **Ping Role**: {role_str}\n"
        f"↳ **Updates Channel**: {ann_str}\n"
        f"↳ **Language**: {lang_names.get(lang, lang)}"
    )
    await premium_response(interaction, "Server Configuration", desc, color=0x3498DB)


@bot.tree.command(name="donate", description="✨ Support BloxPulse development and hosting.")
async def donate(interaction: discord.Interaction):
    await interaction.response.defer(ephemeral=True)
    embed = discord.Embed(
        title="✨ Support BloxPulse Development",
        description=(
            "If you like **BloxPulse** and want to support its maintenance (servers and coffee ☕), "
            "you can do so via **PayPal**.\n\n"
            "**PayPal**: `Cuentadepruebas750@gmail.com`\n\n"
            "Every donation helps us keep bringing constant improvements and staying 24/7!"
        ),
        color=0x00FFBB,
        timestamp=datetime.now(timezone.utc)
    )
    embed.set_thumbnail(url="https://cdn-icons-png.flaticon.com/512/174/174861.png")
    avatar_url = bot.user.display_avatar.url if bot.user else None
    embed.set_footer(text="Thank you for your support ❤️", icon_url=avatar_url)
    
    view = DonationView()
    await interaction.followup.send(embed=embed, view=view)


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
                ).set_footer(text="BloxPulse Monitor", icon_url=bot.user.display_avatar.url),
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
        ).set_footer(text="BloxPulse Monitor", icon_url=bot.user.display_avatar.url),
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
            ).set_footer(text="BloxPulse Monitor", icon_url=bot.user.display_avatar.url),
            ephemeral=True,
        )
    except Exception as e:
        await interaction.followup.send(f"⚠ Cycle failed: `{e}`", ephemeral=True)


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
        "bot": f"BloxPulse {BOT_VERSION}",
        "uptime": f"{h}h {m}m {s}s",
        "latency": latency,
        "guilds": len(bot.guilds)
    }

def run_web_server():
    port = int(_os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)


async def update_dynamic_status(guild: discord.Guild):
    """Updates the status voice channels with real-time data."""
    if not guild or not hasattr(guild, "voice_channels"): return
    
    # 1. Update Member Count
    member_channel = discord.utils.get(guild.voice_channels, name=lambda n: "Members:" in n)
    if member_channel:
        try:
            await member_channel.edit(name=f"⬢ Members: {guild.member_count}")
        except: pass

    # 2. Update Bot Version
    version_channel = discord.utils.get(guild.voice_channels, name=lambda n: "Bot Version:" in n)
    if version_channel:
        try:
            await version_channel.edit(name=f"⬢ Bot Version: {BOT_VERSION}")
        except: pass

    # 3. Update API Status Channels (Granular)
    status_map = {
        "Windows": API_STATUS.get("WindowsPlayer"),
        "Mac": API_STATUS.get("MacPlayer"),
        "Android": API_STATUS.get("AndroidApp"),
        "iOS": API_STATUS.get("iOS")
    }
    
    for platform, is_online in status_map.items():
        status_text = "Online" if is_online else "Offline"
        new_name = f"⬢ {platform}: {status_text}"
        
        # Find exact channel by prefix
        chan = discord.utils.get(guild.voice_channels, name=lambda n: f"⬢ {platform}:" in n or f"❱ {platform}:" in n)
        if chan:
            try:
                if chan.name != new_name:
                    await chan.edit(name=new_name)
            except: pass

async def update_api_health(results: dict):
    """Updates global API_STATUS and triggers guild channel updates."""
    global API_STATUS
    changed = False
    for plat_key in API_STATUS.keys():
        is_on = results.get(plat_key) is not None
        if API_STATUS.get(plat_key) != is_on:
            API_STATUS[plat_key] = is_on
            changed = True
    
    if changed:
        for guild in bot.guilds:
            await update_dynamic_status(guild)

if __name__ == "__main__":
    # Iniciar Flask en un hilo para UptimeRobot
    threading.Thread(target=run_web_server, daemon=True).start()
    
    # Register the group
    bot.tree.add_command(setup_group)
    
    bot.run(DISCORD_BOT_TOKEN)
