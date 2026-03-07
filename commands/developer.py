# commands/developer.py
"""
Developer and owner-exclusive commands.
Provides system diagnostics, broadcast utilities, and debugging tools.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from config import API_PLATFORM_MAPPING, BOT_AVATAR_URL, BOT_VERSION, CHECK_INTERVAL, DEVELOPERS, PLATFORMS
from core.checker import VersionInfo, fetch_all
from core.i18n import get_text
from core.notifier import build_announcement_embed, build_update_embed, create_language_view, premium_response
from core.perms import is_owner
from core.storage import get_all_guilds, get_guild_config, get_version_data, save_announcement

logger = logging.getLogger("BloxPulse.Developer")

# ──────────────────────────────────────────────────────────────────────────────
#  UI Components (Views & Modals)
# ──────────────────────────────────────────────────────────────────────────────

class AnnouncementModal(discord.ui.Modal, title='📣 Create Global Broadcast'):
    ann_title = discord.ui.TextInput(
        label='Update Title',
        placeholder='e.g., BloxPulse v1.7: Premium Preview Stage',
        required=True,
        max_length=100
    )
    version = discord.ui.TextInput(
        label='Bot Version',
        default=BOT_VERSION,
        required=True,
        max_length=20
    )
    content = discord.ui.TextInput(
        label='Announcement Content',
        style=discord.TextStyle.paragraph,
        placeholder='Describe the new features or maintenance...',
        required=True,
        max_length=1024
    )
    image_url = discord.ui.TextInput(
        label='Image/GIF URL (Optional)',
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
        ann_data = {
            "title": self.ann_title.value,
            "version": self.version.value,
            "content": self.content.value,
            "image_url": self.image_url.value,
            "footer": self.footer.value,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        embed = build_announcement_embed(ann_data)
        view = AnnouncementReviewView(embed, ann_data)
        await interaction.response.send_message(
            content="⬢ **Review your broadcast:**",
            embed=embed,
            view=view,
            ephemeral=True
        )

class AnnouncementReviewView(discord.ui.View):
    def __init__(self, embed: discord.Embed, ann_data: dict):
        super().__init__(timeout=300)
        self.embed = embed
        self.ann_data = ann_data

    @discord.ui.button(label="🚀 Broadcast to All", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        save_announcement(self.ann_data)
        
        guilds = get_all_guilds()
        count = 0
        for gid_str, cfg in guilds.items():
            ch_id = cfg.get("announcement_channel_id")
            if not ch_id: continue
            
            channel = interaction.client.get_channel(ch_id)
            if channel:
                try:
                    await channel.send(embed=self.embed)
                    count += 1
                except: pass
        
        await interaction.followup.send(f"✅ Success! Announcement sent to **{count}** servers.", ephemeral=True)
        self.stop()

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Broadcast cancelled.", ephemeral=True)
        self.stop()

# ──────────────────────────────────────────────────────────────────────────────
#  Developer Commands Cog
# ──────────────────────────────────────────────────────────────────────────────
class DeveloperCommands(commands.Cog):
    """Cog grouping all owner-exclusive tools."""
    
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="help_dev", description="🛠️ Exclusive Developer command — Full command list.")
    @is_owner()
    async def help_dev(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        lang = get_guild_config(interaction.guild_id).get("language", "en")
        
        embed = discord.Embed(
            title="🛠️ BloxPulse | Developer Console Help",
            description="Comprehensive guide to all system commands (Member, Admin, and Developer).\n\u200b",
            color=0xa855f7,
            timestamp=datetime.now(timezone.utc),
        )
        
        # Member Section
        embed.add_field(
            name=get_text(lang, "user_cmds"),
            value="`/updates`, `/version`, `/download`, `/compare`, `/ping`, `/info`, `/platforms`, `/myid`, `/invite`, `/donate`.",
            inline=False
        )
        
        # Admin Section
        embed.add_field(
            name=get_text(lang, "admin_cmds"),
            value="`/setup alerts`, `/setup announcements`, `/setup welcome`, `/language`, `/config`.",
            inline=False
        )
        
        # Developer Section
        embed.add_field(
            name=get_text(lang, "owner_cmds"),
            value=(
                "`/broadcast` — Send official announcements\n"
                "`/status` — Real-time bot diagnostics\n"
                "`/test` — Mock a version update event\n"
                "`/reload` — Hot-reload bot tree & cache\n"
                "`/guilds` — List all active server connections"
            ),
            inline=False
        )
        
        avatar_url = self.bot.user.display_avatar.url if self.bot.user else BOT_AVATAR_URL
        embed.set_footer(text="Developer Mode Active", icon_url=avatar_url)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="broadcast", description="Create and send a professional bot update (Owner only).")
    @is_owner()
    async def broadcast(self, interaction: discord.Interaction):
        await interaction.response.send_modal(AnnouncementModal())

    @app_commands.command(name="status", description="Advanced system diagnostics (Owner only).")
    @is_owner()
    async def status(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        uptime = time.time() - getattr(self.bot, "start_time", time.time())
        h, m, s = int(uptime // 3600), int((uptime % 3600) // 60), int(uptime % 60)

        fields = [
            ("⏱︎ Uptime",   f"`{h}h {m}m {s}s`",                 True),
            ("⬢ Guilds",   f"`{len(self.bot.guilds)} servers`",        True),
            ("📶 Latency",  f"`{round(self.bot.latency * 1000)}ms`",    True),
            ("⬢ Version",  f"`{BOT_VERSION} · Premium`",           True),
            ("♚ Owner ID",  f"`{interaction.user.id}`",             True),
        ]
        
        avatar_url = self.bot.user.display_avatar.url if self.bot.user else BOT_AVATAR_URL
        await premium_response(
            interaction,
            "System Diagnostics",
            "Real-time internal performance metrics.\n\u200b",
            color=0x27AE60,
            fields=fields,
            bot_icon=avatar_url
        )

    @app_commands.command(name="test", description="Send a preview of the latest update embed (Owner only).")
    @app_commands.describe(platform="Platform to preview")
    @app_commands.choices(platform=[
        app_commands.Choice(name="Windows", value="windows"),
        app_commands.Choice(name="macOS",   value="mac"),
        app_commands.Choice(name="Android", value="android"),
        app_commands.Choice(name="iOS",     value="ios"),
    ])
    @is_owner()
    async def test(self, interaction: discord.Interaction, platform: str):
        await interaction.response.defer(ephemeral=True)
        
        platform_key = API_PLATFORM_MAPPING[platform]
        lang = get_guild_config(interaction.guild_id).get("language", "en")
        
        state = get_version_data(platform_key)
        curr_hash = state.get("current", "")
        hist = state.get("history", [])
        prev_hash = hist[0] if hist else curr_hash

        loop = asyncio.get_event_loop()
        
        if curr_hash:
            vi = VersionInfo(
                platform_key=platform_key,
                version=curr_hash.replace("version-", ""),
                version_hash=curr_hash,
                channel="LIVE",
                source=f"Stored · {platform_key}",
            )
        else:
            versions = await loop.run_in_executor(None, fetch_all)
            vi = versions.get(platform_key)
            if not vi:
                return await interaction.followup.send("No version data found for this platform.")
            prev_hash = vi.version_hash

        avatar_url = self.bot.user.display_avatar.url if self.bot.user else BOT_AVATAR_URL
        embed = build_update_embed(platform_key, vi, prev_hash, lang=lang, bot_icon=avatar_url)
        view = create_language_view(platform_key, vi, prev_hash, lang)
        
        # Bug fix: Merged "Preview Sent" into a cleaner single response
        embed.title = f"🧪 PREVIEW: {embed.title}"
        await interaction.followup.send(
            content=f"⬢ **Developer Preview Generated** for {PLATFORMS[platform_key]['label']}",
            embed=embed,
            view=view,
            ephemeral=True
        )

    @app_commands.command(name="reload", description="Force an immediate version check (Owner only).")
    @is_owner()
    async def reload(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        loop = asyncio.get_event_loop()
        try:
            versions = await loop.run_in_executor(None, fetch_all)
            platform_list = ", ".join(k for k, v in versions.items() if v)
            await interaction.followup.send(f"◈ Monitoring cycle forced. Fetched: `{platform_list}`", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"◈ Cycle failed: `{e}`", ephemeral=True)

    @app_commands.command(name="guilds", description="List all servers using BloxPulse (Owner only).")
    @is_owner()
    async def guilds(self, interaction: discord.Interaction):
        guild_lines = []
        for g in self.bot.guilds:
            cfg = get_guild_config(g.id)
            ch_id = cfg.get("channel_id")
            status = f"<#{ch_id}>" if ch_id else "`Not configured`"
            guild_lines.append(f"● **{g.name}** (`{g.id}`) → {status}")

        desc = "\n".join(guild_lines) if guild_lines else "*No guilds found.*"
        avatar_url = self.bot.user.display_avatar.url if self.bot.user else BOT_AVATAR_URL
        await premium_response(interaction, f"Active Guilds ({len(self.bot.guilds)})", desc, color=0x9B59B6, bot_icon=avatar_url)

async def setup(bot):
    await bot.add_cog(DeveloperCommands(bot))
