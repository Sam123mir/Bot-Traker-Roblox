# commands/member.py
"""
Public member commands.
Provides version lookups, downloads, and general bot information.
"""
from __future__ import annotations

import asyncio
import random
import time
from datetime import datetime, timezone

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
#  UI Components (Views & Modals)
# ──────────────────────────────────────────────────────────────────────────────

class VersionHistorySelect(discord.ui.Select):
    def __init__(self, platform_key: str, entries: list[dict]):
        self.platform_key = platform_key
        self.entries = entries
        options = []
        for i, e in enumerate(entries[:25]):
            ts_str = e["timestamp"].strftime("%Y-%m-%d %H:%M")
            options.append(discord.SelectOption(
                label=f"v{e['version']}",
                description=f"Hash: {e['version_hash'].replace('version-','')[:12]}… | {ts_str}",
                value=str(i)
            ))
        super().__init__(placeholder="Select a version to inspect...", options=options)

    async def callback(self, interaction: discord.Interaction):
        idx = int(self.values[0])
        entry = self.entries[idx]
        lang = get_guild_config(interaction.guild_id).get("language", "en")
        
        vi = VersionInfo(
            platform_key=self.platform_key,
            version=entry["version"],
            version_hash=entry["version_hash"],
            channel="LIVE",
            source="DeployHistory.txt"
        )
        
        avatar_url = interaction.client.user.display_avatar.url if interaction.client.user else BOT_AVATAR_URL
        embed = build_update_embed(self.platform_key, vi, None, lang=lang, selected_hash=vi.version_hash, bot_icon=avatar_url)
        # Re-use language view logic
        view = create_language_view(self.platform_key, vi, None, lang)
        # Also re-add this select to the new view if desired, but for now just update the msg
        await interaction.response.edit_message(embed=embed, view=view)

class VersionHistoryView(discord.ui.View):
    def __init__(self, platform_key: str, entries: list[dict]):
        super().__init__(timeout=120)
        self.add_item(VersionHistorySelect(platform_key, entries))

class ComparePrevSelect(discord.ui.Select):
    def __init__(self, platform_key: str, current_hash: str, current_ver: str, entries: list[dict]):
        self.platform_key = platform_key
        self.current_hash = current_hash
        self.current_ver = current_ver
        self.entries = entries
        options = []
        seen = {current_hash}
        for i, e in enumerate(entries):
            if e["version_hash"] in seen: continue
            seen.add(e["version_hash"])
            ts_str = e["timestamp"].strftime("%b %d, %H:%M")
            options.append(discord.SelectOption(
                label=f"Compare with v{e['version']}",
                description=f"Released: {ts_str}",
                value=str(i)
            ))
            if len(options) >= 25: break
        super().__init__(placeholder="Pick a previous version to compare...", options=options)

    async def callback(self, interaction: discord.Interaction):
        idx = int(self.values[0])
        old_entry = self.entries[idx]
        old_hash = old_entry["version_hash"]
        old_ver = old_entry["version"]
        
        lang = get_guild_config(interaction.guild_id).get("language", "en")
        plat = PLATFORMS[self.platform_key]
        
        embed = discord.Embed(
            title=f"◈ Version Comparison — {plat['label']}",
            description=(
                f"**Newer**: `{self.current_ver}`\n"
                f"**Older**: `{old_ver}`\n\u200b"
            ),
            color=plat["color"],
            timestamp=datetime.now(timezone.utc)
        )
        
        # We can add more detailed diff logic here later if needed
        diff_url = f"https://roblox-diff.latte.to/compare/{old_hash}/{self.current_hash}"
        embed.add_field(name="🔗 Detailed Diff (External)", value=f"**[➥ View Full Comparison]({diff_url})**", inline=False)
        
        avatar_url = interaction.client.user.display_avatar.url if interaction.client.user else BOT_AVATAR_URL
        embed.set_footer(text="BloxPulse · Precision Analysis", icon_url=avatar_url)
        await interaction.response.edit_message(embed=embed, view=None)

class ComparePrevView(discord.ui.View):
    def __init__(self, platform_key: str, current_hash: str, current_ver: str, entries: list[dict]):
        super().__init__(timeout=120)
        self.add_item(ComparePrevSelect(platform_key, current_hash, current_ver, entries))

class UpdatesHistorySelect(discord.ui.Select):
    def __init__(self, history: list[dict]):
        options = []
        for i, ann in enumerate(history[:25]):
            dt = datetime.fromisoformat(ann["timestamp"])
            date_str = dt.strftime("%b %d, %Y")
            options.append(discord.SelectOption(
                label=ann.get("title", f"Update {i+1}"),
                description=f"Released on {date_str}",
                value=str(i)
            ))
        super().__init__(placeholder="Switch to another update...", options=options)
        self.history = history

    async def callback(self, interaction: discord.Interaction):
        ann = self.history[int(self.values[0])]
        embed = build_announcement_embed(ann)
        await interaction.response.edit_message(embed=embed, view=self.view)

class UpdatesHistoryView(discord.ui.View):
    def __init__(self, history: list[dict]):
        super().__init__(timeout=None)
        self.add_item(UpdatesHistorySelect(history))


# ──────────────────────────────────────────────────────────────────────────────
#  Member Commands Cog
# ──────────────────────────────────────────────────────────────────────────────
class MemberCommands(commands.Cog):
    """Cog grouping all public-facing member commands."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help", description="📖 All command details & features for members and owners.")
    async def help_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        lang = get_guild_config(interaction.guild_id).get("language", "en")
        
        embed = discord.Embed(
            title=get_text(lang, "help_title"),
            description=get_text(lang, "help_desc"),
            color=0x00e5ff,
            timestamp=datetime.now(timezone.utc),
        )
        
        # Member Commands
        embed.add_field(
            name=get_text(lang, "user_cmds"),
            value=(
                "`/updates` — View recent bot news\n"
                "`/version` — In-depth version checker\n"
                "`/download` — Get direct install links\n"
                "`/compare` — Diff two versions\n"
                "`/ping` — Check bot latency\n"
                "`/info` — Bot & System details\n"
                "`/invite` — Bring BloxPulse to your server\n"
                "`/donate` — Support development"
            ),
            inline=False,
        )
        
        # Server Owner Commands
        embed.add_field(
            name=get_text(lang, "admin_cmds"),
            value=(
                "`/setup alerts` — Configure update channel\n"
                "`/setup server` — Professional template setup\n"
                "`/setup announcements` — Set news channel\n"
                "`/setup member-count` — Set dynamic voice counter\n"
                "`/welcome_system` — Consolidated welcome config\n"
                "`/welcome_test` — Preview welcome message\n"
                "`/language` — Change server language\n"
                "`/config` — View current server settings"
            ),
            inline=False,
        )
        
        avatar_url = interaction.client.user.display_avatar.url if interaction.client.user else BOT_AVATAR_URL
        embed.set_footer(text="BloxPulse | Professional Monitoring", icon_url=avatar_url)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="updates", description="🕒 View the 3 most recent BloxPulse updates.")
    async def updates_history(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        history = get_announcements()
        if not history:
            return await premium_response(interaction, "History Empty", "No announcements have been sent yet.", color=0xE74C3C)

        latest_embed = build_announcement_embed(history[0])
        view = UpdatesHistoryView(history)
        
        await interaction.followup.send(
            content="⬢ **BloxPulse Update History**",
            embed=latest_embed,
            view=view,
            ephemeral=True
        )

    @app_commands.command(name="version", description="Browse version history for a platform (last 7 days).")
    @app_commands.describe(platform="Platform to look up")
    @app_commands.choices(platform=[
        app_commands.Choice(name="🪟 Windows", value="windows"),
        app_commands.Choice(name="🍎 macOS",   value="mac"),
        app_commands.Choice(name="🤖 Android", value="android"),
        app_commands.Choice(name="📱 iOS",     value="ios"),
    ])
    async def version_cmd(self, interaction: discord.Interaction, platform: str):
        await interaction.response.defer()
        platform_key = API_PLATFORM_MAPPING[platform]
        plat = PLATFORMS[platform_key]
        label = plat["label"]
        color = plat["color"]

        loop = asyncio.get_event_loop()
        avatar_url = self.bot.user.display_avatar.url if self.bot.user else BOT_AVATAR_URL

        if platform in ("android", "ios"):
            versions = await loop.run_in_executor(None, fetch_all)
            vi = versions.get(platform_key)
            state = get_version_data(platform_key)

            embed = discord.Embed(
                title=f"◈ {label} — Current Version",
                description=f"*No public deployment history available for mobile platforms.*\n\u200b",
                color=color,
                timestamp=datetime.now(timezone.utc),
            )
            if vi:
                embed.add_field(name="🏷️ Version",   value=f"`{vi.version}`", inline=True)
                embed.add_field(name="🔑 Build Hash", value=f"`{vi.version_hash.replace('version-','')}`", inline=True)
                embed.add_field(name="🗂 Source",     value=f"`{vi.source}`", inline=True)
            else:
                embed.add_field(name="Status", value="```diff\n- Data unavailable```", inline=False)
            embed.set_thumbnail(url=plat["icon_url"])
            embed.set_footer(text="BloxPulse Monitor", icon_url=avatar_url)
            await interaction.followup.send(embed=embed)
            return

        entries = await loop.run_in_executor(None, lambda: fetch_deploy_history(platform_key))
        if not entries:
            await interaction.followup.send(
                embed=discord.Embed(
                    title=f"◈ {label} — No History",
                    description="Could not fetch deployment history. The CDN may be temporarily unavailable.",
                    color=0xE74C3C,
                    timestamp=datetime.now(timezone.utc),
                ).set_footer(text="BloxPulse Monitor", icon_url=avatar_url),
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
        for i, e in enumerate(entries[:3]):
            short = e["version_hash"].replace("version-", "")[:16]
            ts = f"<t:{int(e['timestamp'].timestamp())}:R>"
            embed.add_field(
                name=f"{'🥇' if i==0 else '🥈' if i==1 else '🥉'} {e['version']}",
                value=f"`{short}` · {ts}",
                inline=False,
            )

        embed.set_thumbnail(url=plat["icon_url"])
        embed.set_footer(text=f"BloxPulse · Last {len(entries)} versions", icon_url=avatar_url)
        view = VersionHistoryView(platform_key, entries)
        await interaction.followup.send(embed=embed, view=view)

    @app_commands.command(name="download", description="Get the download link for the current Roblox version.")
    @app_commands.describe(platform="Platform to download")
    @app_commands.choices(platform=[
        app_commands.Choice(name="⬢ Windows Client", value="windows"),
        app_commands.Choice(name="⬢ Windows Studio", value="studio"),
        app_commands.Choice(name="⬢ macOS Client",   value="mac"),
        app_commands.Choice(name="⬢ macOS Studio",   value="mac_studio"),
        app_commands.Choice(name="⬢ Android",        value="android"),
        app_commands.Choice(name="⬢ iOS",            value="ios"),
    ])
    async def download(self, interaction: discord.Interaction, platform: str):
        await interaction.response.defer(ephemeral=True)
        platform_key = API_PLATFORM_MAPPING[platform]
        plat = PLATFORMS[platform_key]
        color = plat["color"]
        label = plat["label"]

        loop = asyncio.get_event_loop()
        versions = await loop.run_in_executor(None, fetch_all)
        vi = versions.get(platform_key)
        avatar_url = self.bot.user.display_avatar.url if self.bot.user else BOT_AVATAR_URL

        embed = discord.Embed(
            title=f"◈ Download — {label}",
            color=color,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=plat["icon_url"])

        if vi:
            short = vi.version_hash.replace("version-", "")
            embed.description = (
                f"🚀 **Build:** `{vi.version_hash}`\n"
                f"🔢 **Versión:** `{vi.version}`"
            )
            if vi.fflag_count > 0:
                embed.description += f"\n🛠️ **FFlags:** `{vi.fflag_count}`"

            if platform_key in ["WindowsPlayer", "WindowsStudio", "MacPlayer", "MacStudio"]:
                # The MaximumADHD direct link style with channel support
                channel = vi.channel
                base_cdn = "https://setup.rbxcdn.com"
                if channel and channel != "LIVE":
                    base_cdn += f"/channel/{channel.lower()}"

                prefix = "" if "Windows" in platform_key else "mac/"
                suffix = "RobloxPlayerLauncher.exe" if "Player" in platform_key else "RobloxStudioLauncherBeta.exe"
                if "Mac" in platform_key:
                    suffix = "RobloxPlayer.zip" if "Player" in platform_key else "RobloxStudio.zip"

                direct_url = f"{base_cdn}/{prefix}{vi.version_hash}-{suffix}"
                embed.add_field(
                    name="📥 Enlace de Descarga", 
                    value=f"**[➥ Descargar {label} (Directo)]({direct_url})**", 
                    inline=False
                )
            elif platform == "android":
                embed.add_field(name="↳ Google Play Store", value="**[➥ Open on Google Play](https://play.google.com/store/apps/details?id=com.roblox.client)**", inline=False)
            elif platform == "ios":
                embed.add_field(name="↳ App Store", value="**[➥ Open on App Store](https://apps.apple.com/app/roblox/id431946152)**", inline=False)
        else:
            embed.description = "```diff\n- Version data unavailable.\n```"

        embed.set_footer(text="BloxPulse Monitor", icon_url=avatar_url)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="compare", description="Compare current version with an older one.")
    @app_commands.describe(platform="Platform to compare")
    @app_commands.choices(platform=[
        app_commands.Choice(name="⬢ Windows", value="windows"),
        app_commands.Choice(name="⬢ macOS",   value="mac"),
    ])
    async def compare(self, interaction: discord.Interaction, platform: str):
        await interaction.response.defer()
        platform_key = API_PLATFORM_MAPPING[platform]
        plat = PLATFORMS[platform_key]
        
        loop = asyncio.get_event_loop()
        versions = await loop.run_in_executor(None, fetch_all)
        vi = versions.get(platform_key)
        state = get_version_data(platform_key)
        curr_hash = state.get("current", "") or (vi.version_hash if vi else "")
        curr_ver = vi.version if vi else curr_hash.replace("version-", "")

        if not curr_hash:
            return await interaction.followup.send("No version data available.")

        entries = await loop.run_in_executor(None, lambda: fetch_deploy_history(platform_key))
        if not entries or all(e["version_hash"] == curr_hash for e in entries):
            return await interaction.followup.send("No older versions found to compare.")

        embed = discord.Embed(
            title=f"◈ Compare — {plat['label']}",
            description=f"**Current**: `{curr_ver}`\nSelect an older version below.\n\u200b",
            color=plat["color"],
            timestamp=datetime.now(timezone.utc),
        )
        avatar_url = self.bot.user.display_avatar.url if self.bot.user else BOT_AVATAR_URL
        embed.set_thumbnail(url=plat["icon_url"])
        embed.set_footer(text="BloxPulse Comparisons", icon_url=avatar_url)
        
        view = ComparePrevView(platform_key, curr_hash, curr_ver, entries)
        await interaction.followup.send(embed=embed, view=view)

    @app_commands.command(name="ping", description="Check bot latency and API status.")
    async def ping_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        ws_latency = round(self.bot.latency * 1000)
        
        start = time.perf_counter()
        roblox_ok = False
        http_ms = 0
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get("https://clientsettingscdn.roblox.com/v2/client-version/WindowsPlayer/channel/LIVE", timeout=5) as resp:
                    roblox_ok = resp.status == 200
                    http_ms = round((time.perf_counter() - start) * 1000)
        except: http_ms = -1

        ws_indicator = "🟢" if ws_latency < 100 else "🔴"
        rbl_indicator = "🟢" if roblox_ok else "🔴"
        uptime = time.time() - getattr(self.bot, "start_time", time.time())
        h, m, s = int(uptime // 3600), int((uptime % 3600) // 60), int(uptime % 60)

        embed = discord.Embed(title="◈ BloxPulse · Latency", color=0x2ECC71, timestamp=datetime.now(timezone.utc))
        embed.add_field(name=f"{ws_indicator} Discord", value=f"`{ws_latency} ms`", inline=True)
        embed.add_field(name=f"{rbl_indicator} Roblox API", value=f"`{http_ms} ms`", inline=True)
        embed.add_field(name="⏱︎ Uptime", value=f"`{h}h {m}m {s}s`", inline=True)
        
        avatar_url = self.bot.user.display_avatar.url if self.bot.user else BOT_AVATAR_URL
        embed.set_footer(text=f"BloxPulse {BOT_VERSION}", icon_url=avatar_url)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="info", description="Learn more about BloxPulse.")
    async def info_cmd(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        embed = discord.Embed(
            title="✎ BloxPulse Project",
            description="**BloxPulse** is a precision Roblox version tracker.\n\n**Dev:** <@1420085090570207313>\n**Tech:** Python & Flask",
            color=0x5865F2, timestamp=datetime.now(timezone.utc)
        )
        avatar_url = self.bot.user.display_avatar.url if self.bot.user else BOT_AVATAR_URL
        embed.set_thumbnail(url=avatar_url)
        embed.set_footer(text="Innovation & Transparency", icon_url=avatar_url)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="invite", description="Add BloxPulse to your server.")
    async def invite(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        lang = get_guild_config(interaction.guild_id).get("language", "en")
        url = f"https://discord.com/api/oauth2/authorize?client_id={self.bot.user.id}&permissions=380288&scope=bot%20applications.commands"
        
        embed = discord.Embed(title="🚀 Add BloxPulse!", description="Premium monitoring for your Roblox community.", color=0x5865F2)
        avatar_url = self.bot.user.display_avatar.url if self.bot.user else BOT_AVATAR_URL
        embed.set_footer(text="BloxPulse Monitor", icon_url=avatar_url)
        
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label=get_text(lang, "invite_btn"), style=discord.ButtonStyle.link, url=url, emoji="✨"))
        await interaction.followup.send(embed=embed, view=view)

    @app_commands.command(name="donate", description="Support BloxPulse development.")
    async def donate(self, interaction: discord.Interaction):
        await premium_response(interaction, "Support Us", "PayPal: `Cuentadepruebas750@gmail.com`", color=0x00FFBB)

async def setup(bot):
    await bot.add_cog(MemberCommands(bot))
