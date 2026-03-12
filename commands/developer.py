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
from core.notifier import build_announcement_embed, build_update_embed, build_alert_view, create_language_view, premium_response
from core.perms import is_owner
from core.storage import get_all_guilds, get_guild_config, get_version_data, save_announcement

logger = logging.getLogger("BloxPulse.Developer")


# ──────────────────────────────────────────────────────────────────────────────
#  Design System  (mirrors member.py palette for cross-cog consistency)
# ──────────────────────────────────────────────────────────────────────────────

COLOR_PRIMARY  = 0x5865F2   # Discord Blurple
COLOR_SUCCESS  = 0x57F287   # Green
COLOR_WARNING  = 0xFEE75C   # Yellow
COLOR_DANGER   = 0xED4245   # Red
COLOR_DEV      = 0xA855F7   # Purple – developer-only actions
COLOR_ACCENT   = 0x00E5FF   # Cyan

STATUS_DOT = {True: "🟢", False: "🔴"}


def _bot_icon(interaction: discord.Interaction) -> str:
    return interaction.client.user.display_avatar.url if interaction.client.user else BOT_AVATAR_URL


def _base_embed(
    title: str,
    description: str = "",
    color: int = COLOR_PRIMARY,
    *,
    timestamp: bool = True,
) -> discord.Embed:
    """Consistently styled base embed."""
    embed = discord.Embed(
        title=title,
        description=description or discord.utils.MISSING,
        color=color,
        timestamp=datetime.now(timezone.utc) if timestamp else discord.utils.MISSING,
    )
    return embed


# ──────────────────────────────────────────────────────────────────────────────
#  UI Components
# ──────────────────────────────────────────────────────────────────────────────

class AnnouncementModal(discord.ui.Modal, title="📣  Create Global Broadcast"):
    ann_title = discord.ui.TextInput(
        label="Update Title",
        placeholder="e.g., BloxPulse v2.0 — Major Release",
        required=True,
        max_length=100,
    )
    version = discord.ui.TextInput(
        label="Bot Version",
        default=BOT_VERSION,
        required=True,
        max_length=20,
    )
    content = discord.ui.TextInput(
        label="Announcement Content",
        style=discord.TextStyle.paragraph,
        placeholder="Describe new features, fixes, or important notices…",
        required=True,
        max_length=1024,
    )
    image_url = discord.ui.TextInput(
        label="Banner Image / GIF URL  (optional)",
        placeholder="https://cdn.example.com/banner.png",
        required=False,
    )
    footer = discord.ui.TextInput(
        label="Custom Footer Text  (optional)",
        placeholder="Thanks for your continued support!",
        required=False,
        max_length=100,
    )

    async def on_submit(self, interaction: discord.Interaction):
        ann_data = {
            "title":     self.ann_title.value,
            "version":   self.version.value,
            "content":   self.content.value,
            "image_url": self.image_url.value,
            "footer":    self.footer.value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        embed = build_announcement_embed(ann_data)
        view  = AnnouncementReviewView(embed, ann_data)
        await interaction.response.send_message(
            content="### 👁️  Broadcast Preview — Review before sending",
            embed=embed,
            view=view,
            ephemeral=True,
        )


class AnnouncementReviewView(discord.ui.View):
    """Confirmation step before fanning out the announcement to all guilds."""

    def __init__(self, embed: discord.Embed, ann_data: dict):
        super().__init__(timeout=300)
        self.embed    = embed
        self.ann_data = ann_data

    @discord.ui.button(label="🚀  Broadcast to All Servers", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        save_announcement(self.ann_data)

        guilds = get_all_guilds()
        count  = 0
        failed = 0

        for gid_str, cfg in guilds.items():
            ch_id = cfg.get("announcement_channel_id")
            if not ch_id:
                continue
            channel = interaction.client.get_channel(ch_id)
            if channel:
                try:
                    await channel.send(embed=self.embed)
                    count += 1
                except Exception:
                    failed += 1

        icon = _bot_icon(interaction)
        embed = _base_embed(
            title="✅  Broadcast Complete",
            description=(
                f"Successfully delivered to **{count}** server(s).\n"
                + (f"> ⚠️  Failed deliveries: **{failed}**" if failed else "")
            ),
            color=COLOR_SUCCESS,
        )
        embed.set_footer(text="BloxPulse · Broadcast System", icon_url=icon)
        await interaction.followup.send(embed=embed, ephemeral=True)
        self.stop()

    @discord.ui.button(label="✖  Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        icon  = _bot_icon(interaction)
        embed = _base_embed(
            title="🚫  Broadcast Cancelled",
            description="No announcement was sent. The draft has been discarded.",
            color=COLOR_DANGER,
        )
        embed.set_footer(text="BloxPulse · Broadcast System", icon_url=icon)
        await interaction.response.edit_message(content=None, embed=embed, view=None)
        self.stop()


# ──────────────────────────────────────────────────────────────────────────────
#  Developer Commands Cog
# ──────────────────────────────────────────────────────────────────────────────

class DeveloperCommands(commands.Cog):
    """Owner-exclusive tools: diagnostics, broadcasts, and system control."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── /help_dev ─────────────────────────────────────────────────────────────

    @app_commands.command(name="help_dev", description="🛠️  Developer console — full command reference.")
    @is_owner()
    async def help_dev(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        lang = get_guild_config(interaction.guild_id).get("language", "en")
        icon = _bot_icon(interaction)

        embed = _base_embed(
            title="🛠️  BloxPulse · Developer Console",
            description=(
                "Full reference for all command tiers.\n"
                "Developer commands are restricted to bot owners only.\n\u200b"
            ),
            color=COLOR_DEV,
        )
        embed.add_field(
            name="👥  Member Commands",
            value=(
                "`/version` · `/download` · `/compare` · `/updates`\n"
                "`/ping` · `/info` · `/rules` · `/invite` · `/donate`"
            ),
            inline=False,
        )
        embed.add_field(
            name="🛡️  Admin Commands",
            value=(
                "`/setup alerts` · `/setup announcements` · `/setup member-count`\n"
                "`/setup server` · `/welcome setup` · `/welcome test`\n"
                "`/language` · `/config`"
            ),
            inline=False,
        )
        embed.add_field(
            name="🔐  Developer Commands",
            value=(
                "`/broadcast`  ·  Send official global announcements\n"
                "`/status`     ·  Real-time system diagnostics\n"
                "`/test`       ·  Simulate a version update event\n"
                "`/reload`     ·  Force an immediate version check cycle\n"
                "`/guilds`     ·  List all active server connections\n"
                "`/sync`       ·  Sync & clear ghost slash commands\n"
                "`/help_dev`   ·  This command"
            ),
            inline=False,
        )
        embed.set_thumbnail(url=icon)
        embed.set_footer(text=f"BloxPulse {BOT_VERSION}  ·  Developer Mode Active", icon_url=icon)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /broadcast ────────────────────────────────────────────────────────────

    @app_commands.command(name="broadcast", description="📣  Create and send a global bot announcement  (Owner only).")
    @is_owner()
    async def broadcast(self, interaction: discord.Interaction):
        await interaction.response.send_modal(AnnouncementModal())

    # ── /status ───────────────────────────────────────────────────────────────

    @app_commands.command(name="status", description="📊  Advanced system diagnostics  (Owner only).")
    @is_owner()
    async def status(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        uptime     = time.time() - getattr(self.bot, "start_time", time.time())
        h          = int(uptime // 3600)
        m          = int((uptime % 3600) // 60)
        s          = int(uptime % 60)
        ws_ms      = round(self.bot.latency * 1000)
        ws_status  = STATUS_DOT[ws_ms < 100]
        icon       = _bot_icon(interaction)

        embed = _base_embed(
            title="📊  BloxPulse · System Diagnostics",
            description="Real-time internal performance metrics.\n\u200b",
            color=COLOR_SUCCESS,
        )
        embed.add_field(name="⏱️  Uptime",           value=f"`{h}h {m}m {s}s`",              inline=True)
        embed.add_field(name="🌐  Guilds",            value=f"`{len(self.bot.guilds):,}`",     inline=True)
        embed.add_field(name=f"{ws_status}  Latency", value=f"`{ws_ms} ms`",                  inline=True)
        embed.add_field(name="🤖  Bot Version",       value=f"`{BOT_VERSION}`",               inline=True)
        embed.add_field(name="🔑  Owner ID",          value=f"`{interaction.user.id}`",        inline=True)
        embed.add_field(name="📦  Cogs Loaded",       value=f"`{len(self.bot.cogs)}`",        inline=True)
        embed.set_thumbnail(url=icon)
        embed.set_footer(text="BloxPulse · Internal Diagnostics", icon_url=icon)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /test ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="test", description="🧪  Simulate a version update alert  (Owner only).")
    @app_commands.describe(
        platform="Platform to simulate",
        is_build="Force the 'New Build Detected' pre-release style",
    )
    @app_commands.choices(platform=[
        app_commands.Choice(name="🪟  Windows", value="windows"),
        app_commands.Choice(name="🍎  macOS",   value="mac"),
        app_commands.Choice(name="🤖  Android", value="android"),
        app_commands.Choice(name="📱  iOS",     value="ios"),
    ])
    @is_owner()
    async def test(self, interaction: discord.Interaction, platform: str, is_build: bool = False):
        await interaction.response.defer(ephemeral=True)

        platform_key = API_PLATFORM_MAPPING[platform]
        lang         = get_guild_config(interaction.guild_id).get("language", "en")
        icon         = _bot_icon(interaction)
        loop         = asyncio.get_event_loop()

        # Attempt to fetch fresh live data first
        versions  = await loop.run_in_executor(None, fetch_all)
        vi        = versions.get(platform_key)
        state     = get_version_data(platform_key)
        hist      = state.get("history", [])
        prev_hash = hist[0] if hist else (vi.version_hash if vi else "")

        if not vi:
            curr_hash = state.get("current", "")
            if not curr_hash:
                embed = _base_embed(
                    title="⚠️  No Data Available",
                    description=f"No version data found for **{platform}**. Run a monitoring cycle first.",
                    color=COLOR_DANGER,
                )
                embed.set_footer(text="BloxPulse · Test Command", icon_url=icon)
                return await interaction.followup.send(embed=embed, ephemeral=True)

            vi = VersionInfo(
                platform_key=platform_key,
                version=curr_hash.replace("version-", ""),
                version_hash=curr_hash,
                channel="LIVE",
                source=f"Stored · {platform_key}",
            )

        embed = build_update_embed(
            platform_key, vi, prev_hash,
            lang=lang, bot_icon=icon, is_build=is_build,
        )
        view = build_alert_view(platform_key, vi, prev_hash, lang, is_build=is_build)

        await interaction.followup.send(embed=embed, view=view, ephemeral=False)

    # ── /reload ───────────────────────────────────────────────────────────────

    @app_commands.command(name="reload", description="🔄  Force an immediate version check cycle  (Owner only).")
    @is_owner()
    async def reload(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        icon = _bot_icon(interaction)

        try:
            loop     = asyncio.get_event_loop()
            versions = await loop.run_in_executor(None, fetch_all)
            fetched  = [k for k, v in versions.items() if v]
            skipped  = [k for k, v in versions.items() if not v]

            embed = _base_embed(
                title="🔄  Monitoring Cycle Forced",
                description="Version check completed successfully.\n\u200b",
                color=COLOR_SUCCESS,
            )
            embed.add_field(
                name=f"✅  Fetched ({len(fetched)})",
                value="`" + "`, `".join(fetched) + "`" if fetched else "`—`",
                inline=False,
            )
            if skipped:
                embed.add_field(
                    name=f"⚠️  Unavailable ({len(skipped)})",
                    value="`" + "`, `".join(skipped) + "`",
                    inline=False,
                )
        except Exception as exc:
            embed = _base_embed(
                title="❌  Cycle Failed",
                description=f"An error occurred during the forced cycle.\n```\n{exc}\n```",
                color=COLOR_DANGER,
            )

        embed.set_footer(text="BloxPulse · Monitoring System", icon_url=icon)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /guilds ───────────────────────────────────────────────────────────────

    @app_commands.command(name="guilds", description="📋  List all servers using BloxPulse  (Owner only).")
    @is_owner()
    async def guilds(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        icon = _bot_icon(interaction)

        lines = []
        configured = 0
        for g in self.bot.guilds:
            cfg   = get_guild_config(g.id)
            ch_id = cfg.get("channel_id")
            if ch_id:
                configured += 1
                status = f"<#{ch_id}>"
            else:
                status = "`⚠️ Not configured`"
            lines.append(f"**{g.name}** · `{g.id}` → {status}")

        # Truncate if too long for a single embed field
        body = "\n".join(lines[:20])
        if len(lines) > 20:
            body += f"\n*… and {len(lines) - 20} more*"

        embed = _base_embed(
            title=f"📋  Active Guilds — {len(self.bot.guilds):,} total",
            description=f"> ✅ Configured: **{configured}**  ·  ⚠️ Unconfigured: **{len(self.bot.guilds) - configured}**\n\u200b",
            color=COLOR_DEV,
        )
        embed.add_field(name="Server List", value=body or "*No guilds found.*", inline=False)
        embed.set_footer(text="BloxPulse · Guild Registry", icon_url=icon)
        await interaction.followup.send(embed=embed, ephemeral=True)

    # ── /sync ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="sync", description="⚙️  Sync slash commands globally and load new cogs  (Owner only).")
    @is_owner()
    async def sync_cmds(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        icon = _bot_icon(interaction)

        try:
            # 1. Dynamically Load/Reload all extensions first
            import pathlib
            base_dir = pathlib.Path(__file__).resolve().parent.parent
            loaded_count = 0
            
            for directory in ("systems", "commands"):
                folder = base_dir / directory
                if folder.is_dir():
                    for f in folder.glob("*.py"):
                        if not f.name.startswith("__"):
                            ext = f"{directory}.{f.stem}"
                            try:
                                if ext in self.bot.extensions:
                                    await self.bot.reload_extension(ext)
                                else:
                                    await self.bot.load_extension(ext)
                                loaded_count += 1
                            except Exception as plugin_exc:
                                logger.warning("Failed to load/reload %s: %s", ext, plugin_exc)

            # 2. Clear any guild-specific ghost commands
            self.bot.tree.clear_commands(guild=interaction.guild)
            await self.bot.tree.sync(guild=interaction.guild)
            
            # 3. Push global commands
            synced = await self.bot.tree.sync()

            embed = _base_embed(
                title="⚙️  Commands Synced & Reloaded",
                description=(
                    f"Successfully loaded/reloaded **{loaded_count}** cog(s).\n"
                    f"Registered **{len(synced)}** global command(s).\n"
                    f"Guild-specific command cache has been cleared.\n\u200b"
                ),
                color=COLOR_SUCCESS,
            )
            embed.add_field(
                name="📦  Synced Commands",
                value="`" + "`, `".join(f"/{c.name}" for c in synced) + "`" if synced else "`—`",
                inline=False,
            )
        except Exception as exc:
            embed = _base_embed(
                title="❌  Sync Failed",
                description=f"An error occurred while syncing commands.\n```\n{exc}\n```",
                color=COLOR_DANGER,
            )

        embed.set_footer(text="BloxPulse · Command Tree", icon_url=icon)
        await interaction.followup.send(embed=embed, ephemeral=True)


# ──────────────────────────────────────────────────────────────────────────────
#  Cog Setup
# ──────────────────────────────────────────────────────────────────────────────

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DeveloperCommands(bot))