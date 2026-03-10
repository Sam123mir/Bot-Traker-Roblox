# systems/welcome.py
"""
BloxPulse · Welcome & Onboarding System
=========================================
Handles new member greetings, auto-role assignment, DM onboarding,
goodbye messages, and the bot's own guild-join announcement.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import discord
from discord.ext import commands

from core.i18n import get_text
from core.storage import get_guild_config, set_guild_config

logger = logging.getLogger("BloxPulse.Welcome")


# ──────────────────────────────────────────────────────────────────────────────
#  Rate-limit guard for member-count voice channels
#  (shared with monitoring.py to avoid conflicting edits)
# ──────────────────────────────────────────────────────────────────────────────

_last_member_count_edit: dict[int, float] = {}
_MEMBER_COUNT_COOLDOWN: float = 360.0   # 6 minutes — Discord allows 2 renames / 10 min


# ──────────────────────────────────────────────────────────────────────────────
#  Pure helper functions  (no Discord I/O — easy to unit-test)
# ──────────────────────────────────────────────────────────────────────────────

def _account_age_label(member: discord.Member) -> str:
    """Human-readable account age: '3 days', '~2 months', '~1 year'."""
    days = (datetime.now(timezone.utc) - member.created_at).days
    if days < 1:    return "< 1 day"
    if days < 30:   return f"{days} day{'s' if days != 1 else ''}"
    if days < 365:
        m = days // 30
        return f"~{m} month{'s' if m != 1 else ''}"
    y = days // 365
    return f"~{y} year{'s' if y != 1 else ''}"


def _ordinal(n: int) -> str:
    """1 → '1st', 2 → '2nd', 3 → '3rd', 4 → '4th', …"""
    suffix = (
        "th" if 11 <= (n % 100) <= 13
        else ["th", "st", "nd", "rd", "th"][min(n % 10, 4)]
    )
    return f"{n}{suffix}"


def _is_new_account(member: discord.Member, threshold_days: int = 7) -> bool:
    return (datetime.now(timezone.utc) - member.created_at).days < threshold_days


# ──────────────────────────────────────────────────────────────────────────────
#  Embed builders
# ──────────────────────────────────────────────────────────────────────────────

def _build_welcome_embed(member: discord.Member, cfg: dict) -> discord.Embed:
    """
    Builds the public welcome embed for a new member.

    Optional config keys
    --------------------
    welcome_color      : int   Hex color  (default: 0x00E5FF)
    welcome_message    : str   Custom description; supports {mention}, {name}, {server}
    welcome_banner_url : str   URL for embed image (overrides server banner)
    welcome_thumbnail  : bool  Show member avatar as thumbnail (default: True)
    """
    guild        = member.guild
    count        = guild.member_count
    position     = _ordinal(count)
    account_age  = _account_age_label(member)
    is_new       = _is_new_account(member)

    color        = cfg.get("welcome_color", 0x00E5FF)
    custom_msg   = cfg.get("welcome_message", "")
    banner_url   = cfg.get("welcome_banner_url", "")
    show_thumb   = cfg.get("welcome_thumbnail", True)

    # ── Description ───────────────────────────────────────────────────────────
    if custom_msg:
        description = (
            custom_msg
            .replace("{mention}", member.mention)
            .replace("{name}",    member.display_name)
            .replace("{server}",  guild.name)
        )
    else:
        description = (
            f"### 👋  Welcome, {member.mention}!\n"
            f"We're thrilled to have you. You are our **{position} member** — make yourself at home.\n\n"
            f"📌  Head over to the rules and introduction channels to get started.\n"
            f"🚀  Feel free to introduce yourself to the community!"
        )

    embed = discord.Embed(
        title=f"✨  New Member — {guild.name}",
        description=description,
        color=color,
        timestamp=datetime.now(timezone.utc),
    )

    # ── Author row ────────────────────────────────────────────────────────────
    embed.set_author(
        name=f"{member.display_name} just joined!",
        icon_url=member.display_avatar.url,
    )

    # ── Thumbnail ────────────────────────────────────────────────────────────
    if show_thumb:
        embed.set_thumbnail(url=member.display_avatar.url)

    # ── Banner image ──────────────────────────────────────────────────────────
    if banner_url:
        embed.set_image(url=banner_url)
    elif guild.banner:
        embed.set_image(url=guild.banner.url)

    # ── Info fields ───────────────────────────────────────────────────────────
    embed.add_field(name="👤  Username",       value=f"`{member.name}`",                                                    inline=True)
    embed.add_field(name="🪪  Account Age",    value=f"`{account_age}`",                                                    inline=True)
    embed.add_field(name="👥  Total Members",  value=f"`{count:,}`",                                                        inline=True)
    embed.add_field(name="📅  Discord Since",  value=discord.utils.format_dt(member.created_at, style="D"),                 inline=True)
    embed.add_field(name="📥  Server Joined",  value=discord.utils.format_dt(member.joined_at or datetime.now(timezone.utc), style="D"), inline=True)
    embed.add_field(name="🎯  Position",       value=f"`{position} member`",                                                inline=True)

    # ── New-account warning ───────────────────────────────────────────────────
    if is_new:
        embed.add_field(
            name="⚠️  New Account",
            value="This account was created very recently. Please be cautious.",
            inline=False,
        )

    # ── Footer ────────────────────────────────────────────────────────────────
    embed.set_footer(
        text=f"{guild.name}  ·  Member ID: {member.id}",
        icon_url=guild.icon.url if guild.icon else None,
    )
    return embed


def _build_goodbye_embed(member: discord.Member, cfg: dict, lang: str) -> discord.Embed:
    """Builds the goodbye embed when a member leaves the server."""
    guild = member.guild

    title  = get_text(lang, "goodbye_member_title", user=member.display_name)
    body   = get_text(lang, "goodbye_member_body",  user=member.display_name, count=f"{guild.member_count:,}")
    footer = get_text(lang, "goodbye_member_footer")

    embed = discord.Embed(
        title=title,
        description=body,
        color=0xFF4757,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    embed.set_footer(
        text=f"{footer}  ·  ID: {member.id}",
        icon_url=guild.icon.url if guild.icon else None,
    )
    return embed


def _build_dm_embed(member: discord.Member, cfg: dict) -> discord.Embed:
    """Private DM sent to a newly joined member."""
    guild            = member.guild
    rules_channel_id = cfg.get("rules_channel_id")
    roles_channel_id = cfg.get("roles_channel_id")
    intro_channel_id = cfg.get("intro_channel_id")

    lines = [
        f"## 👋  Welcome to **{guild.name}**, {member.display_name}!",
        "",
        "We're glad to have you. Here's a quick guide to get started:",
        "",
    ]
    if rules_channel_id:
        lines.append(f"📜  **Rules** → <#{rules_channel_id}>")
    if roles_channel_id:
        lines.append(f"🎭  **Get Roles** → <#{roles_channel_id}>")
    if intro_channel_id:
        lines.append(f"🙋  **Introduce Yourself** → <#{intro_channel_id}>")

    lines += [
        "",
        "If you have any questions, the staff team is always happy to help.",
        "Enjoy your stay! 🚀",
    ]

    embed = discord.Embed(
        description="\n".join(lines),
        color=cfg.get("welcome_color", 0x00E5FF),
        timestamp=datetime.now(timezone.utc),
    )
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    embed.set_footer(text=f"Sent from {guild.name}")
    return embed


def _build_guild_join_embed(bot: discord.Client, guild: discord.Guild) -> discord.Embed:
    """Onboarding embed sent when the bot joins a new server."""
    embed = discord.Embed(
        title="✨  BloxPulse is now live!",
        description=(
            "Hi! I'm **BloxPulse** — your all-in-one Roblox version monitor.\n\n"
            "**Getting started is easy:**\n"
            "⬢  `/setup alerts`  ·  Choose where to send update notifications\n"
            "⬢  `/setup welcome` ·  Configure the member welcome system\n"
            "⬢  `/help`          ·  Explore every available feature\n\n"
            "Need help? Visit our [support server](https://discord.gg/your-invite)."
        ),
        color=0x00E5FF,
        timestamp=datetime.now(timezone.utc),
    )
    total_users = sum(g.member_count for g in bot.guilds if g.member_count)
    embed.set_thumbnail(url=bot.user.display_avatar.url)
    embed.add_field(name="📡  Servers",  value=f"`{len(bot.guilds):,}`", inline=True)
    embed.add_field(name="👥  Users",    value=f"`{total_users:,}`",     inline=True)
    embed.set_footer(
        text="Thank you for choosing BloxPulse!",
        icon_url=bot.user.display_avatar.url,
    )
    return embed


# ──────────────────────────────────────────────────────────────────────────────
#  Channel resolution helpers
# ──────────────────────────────────────────────────────────────────────────────

_WELCOME_FALLBACK_NAMES  = ("welcome", "general", "lobby", "chat", "bot")
_ONBOARD_FALLBACK_NAMES  = ("general", "welcome", "bot", "chat", "lobby")


async def _resolve_channel(
    guild: discord.Guild,
    cfg: dict,
    cfg_key: str,
    fallback_names: tuple[str, ...] = _WELCOME_FALLBACK_NAMES,
) -> discord.TextChannel | None:
    """
    Resolve the best text channel for a message, in priority order:
      1. Channel stored in config under ``cfg_key``
      2. General alert channel from config (``channel_id``)
      3. Discord's system channel
      4. First channel whose name matches a priority keyword
      5. Any writable text channel
    """
    bot_member = guild.me

    def _can_send(ch: discord.TextChannel) -> bool:
        return ch.permissions_for(bot_member).send_messages

    # 1. Explicit config key
    if cid := cfg.get(cfg_key):
        if ch := guild.get_channel(cid):
            return ch

    # 2. Fallback alert channel
    if cid := cfg.get("channel_id"):
        if ch := guild.get_channel(cid):
            return ch

    # 3. Discord system channel
    if (sc := guild.system_channel) and _can_send(sc):
        return sc

    # 4. Name-based priority search
    for name in fallback_names:
        for ch in guild.text_channels:
            if name in ch.name.lower() and _can_send(ch):
                return ch

    # 5. Any writable channel
    for ch in guild.text_channels:
        if _can_send(ch):
            return ch

    return None


# ──────────────────────────────────────────────────────────────────────────────
#  WelcomeSystem Cog
# ──────────────────────────────────────────────────────────────────────────────

class WelcomeSystem(commands.Cog):
    """Handles member join/leave events, auto-roles, DMs, and bot onboarding."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _update_member_count_channel(self, guild: discord.Guild) -> None:
        """
        Rename the member-count voice channel to reflect the current count.
        Respects Discord's rename rate limit via _last_member_count_edit.
        """
        import time

        cfg        = get_guild_config(guild.id, guild_name=guild.name)
        new_name   = f"》 Members: {guild.member_count}"

        # Resolve target channel: config key → name search
        channel_id = cfg.get("member_count_channel_id")
        channel    = guild.get_channel(channel_id) if channel_id else None

        if not isinstance(channel, discord.VoiceChannel):
            channel = discord.utils.find(
                lambda c: isinstance(c, discord.VoiceChannel) and "members:" in c.name.lower(),
                guild.voice_channels,
            )

        if not channel:
            return
        if not channel.permissions_for(guild.me).manage_channels:
            logger.debug("Missing Manage Channels for member counter in %s.", guild.name)
            return
        if channel.name == new_name:
            return  # Already correct — skip the API call

        now       = time.time()
        last_edit = _last_member_count_edit.get(channel.id, 0.0)
        remaining = _MEMBER_COUNT_COOLDOWN - (now - last_edit)

        if remaining > 0:
            logger.debug(
                "Member counter cooldown in %s — %.0fs remaining.", guild.name, remaining
            )
            return

        try:
            await channel.edit(name=new_name, reason="BloxPulse — member count update")
            _last_member_count_edit[channel.id] = now
            logger.info("Member counter updated in %s → %d.", guild.name, guild.member_count)
        except discord.HTTPException as exc:
            if exc.status == 429:
                logger.warning("Rate limited (429) on member counter in %s. Penalising 10 min.", guild.name)
                _last_member_count_edit[channel.id] = now + 600.0
            else:
                logger.error("HTTP error updating member counter in %s: %s", guild.name, exc)
        except Exception as exc:
            logger.error("Unexpected error updating member counter in %s: %s", guild.name, exc)

    async def _trigger_status_update(self, guild: discord.Guild) -> None:
        """Notify the monitoring system and update the member counter."""
        if hasattr(self.bot, "update_dynamic_status"):
            await self.bot.update_dynamic_status(guild)
        await self._update_member_count_channel(guild)

    async def _assign_auto_roles(self, member: discord.Member, cfg: dict) -> None:
        """Assign all configured auto-roles to a new member."""
        role_ids: list[int] = cfg.get("auto_role_ids", [])
        if not role_ids:
            return

        roles = [r for rid in role_ids if (r := member.guild.get_role(rid))]
        if not roles:
            return

        try:
            await member.add_roles(*roles, reason="BloxPulse — auto-role on join")
            logger.info(
                "Assigned %d auto-role(s) to %s in %s.",
                len(roles), member.name, member.guild.name,
            )
        except discord.Forbidden:
            logger.warning(
                "Missing permissions to assign auto-roles in %s.", member.guild.name
            )
        except Exception as exc:
            logger.error("Error assigning auto-roles to %s: %s", member.name, exc)

    async def _send_dm_welcome(self, member: discord.Member, cfg: dict) -> None:
        """Optionally send a private welcome DM to the new member."""
        if not cfg.get("welcome_dm_enabled", False):
            return
        try:
            embed = _build_dm_embed(member, cfg)
            await member.send(embed=embed)
            logger.info("DM welcome sent to %s.", member.name)
        except discord.Forbidden:
            pass  # User has DMs closed — silently skip
        except Exception as exc:
            logger.error("Failed to DM welcome to %s: %s", member.name, exc)

    # ── Event listeners ───────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        """Welcome a new member with a rich embed, optional DM, and auto-roles."""
        await self._trigger_status_update(member.guild)

        cfg = get_guild_config(member.guild.id, guild_name=member.guild.name)

        # Assign roles first so the member gets them as soon as possible
        await self._assign_auto_roles(member, cfg)
        await self._send_dm_welcome(member, cfg)

        target = await _resolve_channel(member.guild, cfg, "welcome_channel_id")
        if not target:
            logger.warning(
                "No writable welcome channel in %s for %s.",
                member.guild.name, member.name,
            )
            return

        try:
            embed = _build_welcome_embed(member, cfg)
            await target.send(content=member.mention, embed=embed)
            logger.info(
                "Welcomed %s in %s (#%s).",
                member.name, member.guild.name, target.name,
            )
        except Exception as exc:
            logger.error(
                "Failed to send welcome for %s in %s: %s",
                member.name, member.guild.name, exc,
            )

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member) -> None:
        """Update dynamic counters and optionally send a goodbye message."""
        await self._trigger_status_update(member.guild)

        cfg = get_guild_config(member.guild.id, guild_name=member.guild.name)
        if not cfg.get("goodbye_enabled", False):
            return

        target = await _resolve_channel(
            member.guild, cfg, "goodbye_channel_id",
            fallback_names=("goodbye", "farewell", "general"),
        )
        if not target:
            return

        lang  = cfg.get("language", "en")
        embed = _build_goodbye_embed(member, cfg, lang)

        try:
            await target.send(embed=embed)
        except Exception as exc:
            logger.error(
                "Failed to send goodbye for %s in %s: %s",
                member.name, member.guild.name, exc,
            )

    @commands.Cog.listener()
    async def on_guild_join(self, guild: discord.Guild) -> None:
        """
        Send a polished onboarding embed when the bot is added to a new server.
        Uses the audit log to personalise the greeting with the inviter's mention.
        """
        # De-duplicate in case the event fires more than once
        async with self.bot.welcome_lock:
            if guild.id in self.bot.welcomed_guilds:
                return
            self.bot.welcomed_guilds.add(guild.id)

        logger.info("Joined guild %s (%d).", guild.name, guild.id)

        # Attempt to identify who invited the bot
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
                pass  # Audit log is optional — gracefully skip

        embed  = _build_guild_join_embed(self.bot, guild)
        target = await _resolve_channel(
            guild, {}, "",
            fallback_names=_ONBOARD_FALLBACK_NAMES,
        )

        if not target:
            logger.warning("Could not find a writable channel in %s for onboarding.", guild.name)
            return

        greeting = f"Thanks for the invite, {inviter.mention}! " if inviter else None
        try:
            await target.send(content=greeting, embed=embed)
            logger.info(
                "Onboarding message sent in %s (#%s).",
                guild.name, target.name,
            )
        except Exception as exc:
            logger.error("Failed to send onboarding in %s: %s", guild.name, exc)


# ──────────────────────────────────────────────────────────────────────────────
#  Cog Setup
# ──────────────────────────────────────────────────────────────────────────────

async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(WelcomeSystem(bot))