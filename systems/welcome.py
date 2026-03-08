# systems/welcome.py
"""
Server welcome and onboarding system.
Handles new members, auto-roles, and bot join events.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands

from core.i18n import get_text
from core.notifier import build_member_welcome_embed
from core.storage import get_guild_config, set_guild_config

logger = logging.getLogger("BloxPulse.Welcome")

# ──────────────────────────────────────────────
#  HELPERS
# ──────────────────────────────────────────────

def _account_age_label(member: discord.Member) -> str:
    """Return a human-readable account age string."""
    delta = datetime.now(timezone.utc) - member.created_at
    days = delta.days
    if days < 1:
        return "< 1 day"
    if days < 30:
        return f"{days} day{'s' if days != 1 else ''}"
    if days < 365:
        months = days // 30
        return f"~{months} month{'s' if months != 1 else ''}"
    years = days // 365
    return f"~{years} year{'s' if years != 1 else ''}"


def _member_number_suffix(n: int) -> str:
    """1 → 1st, 2 → 2nd, etc."""
    if 11 <= (n % 100) <= 13:
        return f"{n}th"
    return f"{n}{['th','st','nd','rd','th'][min(n % 10, 4)]}"


def _is_new_account(member: discord.Member, days_threshold: int = 7) -> bool:
    delta = datetime.now(timezone.utc) - member.created_at
    return delta.days < days_threshold


def _build_welcome_embed(member: discord.Member, cfg: dict) -> discord.Embed:
    """
    Builds a rich, server-quality welcome embed.
    Reads optional config keys:
      - welcome_color      : int  (hex color, default cyan)
      - welcome_message    : str  (custom description, supports {mention}, {name}, {server})
      - welcome_banner_url : str  (URL for embed image, e.g. a server banner)
      - welcome_thumbnail  : bool (show member avatar as thumbnail, default True)
    """
    guild = member.guild
    member_count = guild.member_count
    position_label = _member_number_suffix(member_count)
    account_age = _account_age_label(member)
    new_account = _is_new_account(member)

    color_value = cfg.get("welcome_color", 0x00e5ff)
    custom_msg = cfg.get("welcome_message", "")
    banner_url = cfg.get("welcome_banner_url", "")
    show_thumbnail = cfg.get("welcome_thumbnail", True)

    # ── Description ───────────────────────────────────────────────────────────
    if custom_msg:
        description = (
            custom_msg
            .replace("{mention}", member.mention)
            .replace("{name}", member.display_name)
            .replace("{server}", guild.name)
        )
    else:
        description = (
            f"### 👋 Welcome, {member.mention}!\n"
            f"We're thrilled to have you here. You are our "
            f"**{position_label} member** — make yourself at home.\n\n"
            f"📌 Check the server rules and introduction channels to get started.\n"
            f"🚀 Feel free to introduce yourself to the community!"
        )

    embed = discord.Embed(
        title=f"✨ A new member has arrived — {guild.name}",
        description=description,
        color=color_value,
        timestamp=datetime.now(timezone.utc),
    )

    # ── Author (member avatar + name) ─────────────────────────────────────────
    embed.set_author(
        name=f"{member.display_name} just joined!",
        icon_url=member.display_avatar.url,
    )

    # ── Thumbnail (member avatar) ─────────────────────────────────────────────
    if show_thumbnail:
        embed.set_thumbnail(url=member.display_avatar.url)

    # ── Server banner or custom image ─────────────────────────────────────────
    if banner_url:
        embed.set_image(url=banner_url)
    elif guild.banner:
        embed.set_image(url=guild.banner.url)

    # ── Fields ────────────────────────────────────────────────────────────────
    embed.add_field(
        name="👤 Username",
        value=f"`{member.name}`",
        inline=True,
    )
    embed.add_field(
        name="🪪 Account Age",
        value=f"`{account_age}`",
        inline=True,
    )
    embed.add_field(
        name="👥 Members",
        value=f"`{member_count:,}`",
        inline=True,
    )
    embed.add_field(
        name="📅 Joined Discord",
        value=discord.utils.format_dt(member.created_at, style="D"),
        inline=True,
    )
    embed.add_field(
        name="📥 Joined Server",
        value=discord.utils.format_dt(member.joined_at or datetime.now(timezone.utc), style="D"),
        inline=True,
    )
    embed.add_field(
        name="🎯 Position",
        value=f"`{position_label} member`",
        inline=True,
    )

    # ── New account warning ───────────────────────────────────────────────────
    if new_account:
        embed.add_field(
            name="⚠️ New Account",
            value="This account was created recently. Please be cautious.",
            inline=False,
        )

    # ── Footer ────────────────────────────────────────────────────────────────
    embed.set_footer(
        text=f"{guild.name} • Member ID: {member.id}",
        icon_url=guild.icon.url if guild.icon else discord.Embed.Empty,
    )

    return embed


def _build_dm_embed(member: discord.Member, cfg: dict) -> discord.Embed:
    """Private DM sent to the new member."""
    guild = member.guild
    rules_channel_id = cfg.get("rules_channel_id")
    roles_channel_id = cfg.get("roles_channel_id")
    intro_channel_id = cfg.get("intro_channel_id")

    lines = [
        f"## 👋 Welcome to **{guild.name}**, {member.display_name}!",
        "",
        "We're glad you're here. Here's a quick guide to get you started:",
        "",
    ]

    if rules_channel_id:
        lines.append(f"📜 **Rules** → <#{rules_channel_id}>")
    if roles_channel_id:
        lines.append(f"🎭 **Get Roles** → <#{roles_channel_id}>")
    if intro_channel_id:
        lines.append(f"🙋 **Introduce Yourself** → <#{intro_channel_id}>")

    lines += [
        "",
        "If you have any questions, feel free to ask the staff team.",
        "Enjoy your stay! 🚀",
    ]

    embed = discord.Embed(
        description="\n".join(lines),
        color=cfg.get("welcome_color", 0x00e5ff),
        timestamp=datetime.now(timezone.utc),
    )
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    embed.set_footer(text=f"Sent from {guild.name}")
    return embed


async def _find_welcome_channel(guild: discord.Guild, cfg: dict, key: str = "welcome_channel_id") -> discord.TextChannel | None:
    """Resolve the best channel to send the welcome/goodbye message."""
    # 1. Explicitly configured channel for this specific purpose
    if wid := cfg.get(key):
        if ch := guild.get_channel(wid):
            return ch

    # 2. Fallback general channel from config
    if cid := cfg.get("channel_id"):
        if ch := guild.get_channel(cid):
            return ch

    # 3. Discord's system channel
    if guild.system_channel and guild.system_channel.permissions_for(guild.me).send_messages:
        return guild.system_channel

    # 4. First channel whose name suggests a welcome area
    PRIORITY_NAMES = ("welcome", "general", "lobby", "chat", "bot")
    for name in PRIORITY_NAMES:
        for ch in guild.text_channels:
            if name in ch.name.lower() and ch.permissions_for(guild.me).send_messages:
                return ch

    # 5. Any writable text channel
    for ch in guild.text_channels:
        if ch.permissions_for(guild.me).send_messages:
            return ch

    return None


# ──────────────────────────────────────────────
#  COG
# ──────────────────────────────────────────────

class WelcomeSystem(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _update_member_count_channel(self, guild: discord.Guild):
        """Find and rename the voice channel for tracking member counts."""
        cfg = get_guild_config(guild.id)
        channel_id = cfg.get("member_count_channel_id")
        if not channel_id:
            return

        channel = guild.get_channel(channel_id)
        if not isinstance(channel, discord.VoiceChannel):
            return

        # Permissions check
        if not channel.permissions_for(guild.me).manage_channels:
            logger.warning(f"BloxPulse: Missing Manage Channels perm to update count in {guild.name}")
            return

        count = guild.member_count
        new_name = f"》 Members: {count}"
        
        if channel.name != new_name:
            try:
                await channel.edit(name=new_name)
                logger.debug(f"BloxPulse: Updated member count channel in {guild.name} to {count}")
            except discord.RateLimited:
                pass # Silent ignore, will catch up next time
            except Exception as e:
                logger.error(f"BloxPulse: Failed to update count channel in {guild.name}: {e}")

    async def _trigger_status_update(self, guild: discord.Guild):
        # Update dynamic status if available
        if hasattr(self.bot, "update_dynamic_status"):
            await self.bot.update_dynamic_status(guild)
        # Also update the voice channel name
        await self._update_member_count_channel(guild)

    async def _assign_auto_roles(self, member: discord.Member, cfg: dict):
        """Assign configured auto-roles to the new member."""
        auto_role_ids: list[int] = cfg.get("auto_role_ids", [])
        if not auto_role_ids:
            return
        roles = [r for rid in auto_role_ids if (r := member.guild.get_role(rid))]
        if roles:
            try:
                await member.add_roles(*roles, reason="BloxPulse auto-role on join")
                logger.info(
                    f"BloxPulse: Assigned {len(roles)} auto-role(s) to {member.name} "
                    f"in {member.guild.name}"
                )
            except discord.Forbidden:
                logger.warning(
                    f"BloxPulse: Missing permissions to assign auto-roles "
                    f"in {member.guild.name}"
                )
            except Exception as e:
                logger.error(f"BloxPulse: Error assigning auto-roles: {e}")

    async def _send_dm_welcome(self, member: discord.Member, cfg: dict):
        """Optionally DM the new member a welcome message."""
        if not cfg.get("welcome_dm_enabled", False):
            return
        try:
            embed = _build_dm_embed(member, cfg)
            await member.send(embed=embed)
            logger.info(f"BloxPulse: Sent DM welcome to {member.name}")
        except discord.Forbidden:
            # User has DMs disabled — silently ignore
            pass
        except Exception as e:
            logger.error(f"BloxPulse: Failed to DM {member.name}: {e}")

    # ── Listeners ─────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        """Welcome new member with a professional embed, optional DM, and auto-roles."""
        await self._trigger_status_update(member.guild)

        cfg = get_guild_config(member.guild.id)

        # Auto-roles (do this first so the member gets them ASAP)
        await self._assign_auto_roles(member, cfg)

        # DM welcome
        await self._send_dm_welcome(member, cfg)

        # Public welcome message
        target_channel = await _find_welcome_channel(member.guild, cfg)
        if not target_channel:
            logger.warning(
                f"BloxPulse: No writable channel found to welcome "
                f"{member.name} in {member.guild.name}"
            )
            return

        try:
            embed = _build_welcome_embed(member, cfg)
            await target_channel.send(content=member.mention, embed=embed)
            logger.info(
                f"BloxPulse: Welcomed {member.name} in "
                f"{member.guild.name} (#{target_channel.name})"
            )
        except Exception as e:
            logger.error(
                f"BloxPulse: Failed to send welcome for {member.name} "
                f"in {member.guild.name}: {e}"
            )

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        """Update dynamic status on member leave."""
        await self._trigger_status_update(member.guild)

        cfg = get_guild_config(member.guild.id)

        # ── Optional goodbye message ──────────────────────────────────────────
        if not cfg.get("goodbye_enabled", False):
            return

        target_channel = await _find_welcome_channel(member.guild, cfg, key="goodbye_channel_id")
        if not target_channel:
            return

        embed = discord.Embed(
            description=(
                f"**{member.display_name}** has left the server.\n"
                f"We now have **{member.guild.member_count:,}** members."
            ),
            color=0x778ca3,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_author(
            name=f"{member.display_name} left",
            icon_url=member.display_avatar.url,
        )
        embed.set_footer(text=f"ID: {member.id}")

        try:
            await target_channel.send(embed=embed)
        except Exception as e:
            logger.error(f"BloxPulse: Failed to send goodbye for {member.name}: {e}")

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild):
        """
        Send a polished onboarding embed when the bot is added to a new server.
        Tries to find who invited the bot via the audit log.
        """
        async with self.bot.welcome_lock:
            if guild.id in self.bot.welcomed_guilds:
                return
            self.bot.welcomed_guilds.add(guild.id)

        logger.info(f"BloxPulse: Joined guild {guild.name} ({guild.id})")

        # Try to find the person who invited the bot
        inviter: discord.Member | None = None
        if guild.me.guild_permissions.view_audit_log:
            try:
                async for entry in guild.audit_logs(
                    limit=5, action=discord.AuditLogAction.bot_add
                ):
                    if entry.target.id == self.bot.user.id:
                        inviter = entry.user
                        break
            except Exception:
                pass

        embed = discord.Embed(
            title="✨ BloxPulse is now live!",
            description=(
                "Hi! I'm **BloxPulse**, your all-in-one Roblox version monitor.\n\n"
                "**Getting started is easy:**\n"
                "⬢ `/setup alerts` — choose where to send update notifications\n"
                "⬢ `/setup welcome` — configure the member welcome system\n"
                "⬢ `/help` — explore every available feature\n\n"
                "Need support? Join our [support server](https://discord.gg/your-invite)."
            ),
            color=0x00e5ff,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=self.bot.user.display_avatar.url)
        embed.add_field(name="📡 Servers", value=f"`{len(self.bot.guilds):,}`", inline=True)
        embed.add_field(name="👥 Users", value=f"`{sum(g.member_count for g in self.bot.guilds):,}`", inline=True)
        embed.set_footer(
            text="Thank you for choosing BloxPulse!",
            icon_url=self.bot.user.display_avatar.url,
        )

        # Pick the best channel
        target = None
        if guild.system_channel and guild.system_channel.permissions_for(guild.me).send_messages:
            target = guild.system_channel

        if not target:
            PRIORITY = ("general", "welcome", "bot", "chat", "lobby")
            for name in PRIORITY:
                for ch in guild.text_channels:
                    if name in ch.name.lower() and ch.permissions_for(guild.me).send_messages:
                        target = ch
                        break
                if target:
                    break

        if not target:
            for ch in guild.text_channels:
                if ch.permissions_for(guild.me).send_messages:
                    target = ch
                    break

        if target:
            greeting = f"Thanks for the invite, {inviter.mention}! " if inviter else ""
            try:
                await target.send(content=greeting or None, embed=embed)
                logger.info(f"BloxPulse: Sent onboarding message in {guild.name} (#{target.name})")
            except Exception as e:
                logger.error(f"BloxPulse: Failed to send onboarding to {guild.name}: {e}")


async def setup(bot):
    await bot.add_cog(WelcomeSystem(bot))
