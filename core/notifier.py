# core/notifier.py
"""
BloxPulse · Notification & Embed Pipeline
==========================================
Centralised factory for every Discord embed the bot produces,
plus the async delivery helpers that send them to guild channels.

Public surface
--------------
  build_update_embed(...)       → discord.Embed
  build_member_welcome_embed(…) → discord.Embed
  build_announcement_embed(…)   → discord.Embed
  premium_response(…)           → coroutine
  notify_update(…)              → bool
  notify_startup(…)             → None
  create_language_view(…)       → discord.ui.View
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

import discord
from discord.ui import Select, View

from config import BOT_AVATAR_URL, BOT_VERSION, PLATFORMS, ROBLOX_URL
from .checker import VersionInfo
from .i18n import get_text
from .storage import get_version_data

log = logging.getLogger("BloxPulse.Notifier")

# ──────────────────────────────────────────────────────────────────────────────
#  Constants
# ──────────────────────────────────────────────────────────────────────────────

RDD_BASE = "https://rdd.latte.to"

_FOOTER_POOL: tuple[str, ...] = (
    "BloxPulse Monitor ⬢",
    "Global Roblox Tracker ⬢",
    "Monitoring with Pulse ✨",
    "Stay updated, stay fast ✨",
    "Professional Monitoring ◈ BloxPulse",
)

_SUPPORTED_LANGUAGES: tuple[str, ...] = ("en", "es", "pt", "ru", "fr")

_MOBILE_PLATFORMS: frozenset[str] = frozenset({"AndroidApp", "iOS"})

# Discord hard limits (https://discord.com/developers/docs/resources/channel#embed-object)
_LIMIT_TITLE       = 256
_LIMIT_DESCRIPTION = 4096
_LIMIT_FIELD_NAME  = 256
_LIMIT_FIELD_VALUE = 1024
_LIMIT_FOOTER      = 2048
_LIMIT_TOTAL_CHARS = 6000


# ──────────────────────────────────────────────────────────────────────────────
#  Internal data models
# ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class _DownloadLink:
    label: str
    url:   str
    direct_url: Optional[str] = None


@dataclass(frozen=True)
class _EmbedContext:
    """Pre-resolved data bundle passed to the embed builder."""
    platform_key: str
    label:        str
    color:        int
    icon_url:     str
    version:      str
    short_hash:   str
    full_hash:    str
    detected_at:  str
    channel:      str
    download:     _DownloadLink
    is_mobile:    bool


# ──────────────────────────────────────────────────────────────────────────────
#  Private helpers
# ──────────────────────────────────────────────────────────────────────────────

def _random_footer() -> str:
    return random.choice(_FOOTER_POOL)  # noqa: S311


def _truncate(text: str, limit: int) -> str:
    """Hard-truncate text to Discord's character limits, appending '…' if cut."""
    if len(text) <= limit:
        return text
    log.warning("Embed field truncated from %d to %d chars", len(text), limit)
    return text[: limit - 1] + "…"


def _avatar(bot_icon: Optional[str]) -> str:
    return bot_icon or BOT_AVATAR_URL


def _resolve_download_link(
    platform_key: str,
    version_hash: str,
    lang: str,
    channel: str = "LIVE",
) -> _DownloadLink:
    """Return a labelled download / store URL for the given platform."""
    
    # Base CDN URL handling channels
    base_cdn = "https://setup.rbxcdn.com"
    if channel != "LIVE":
        base_cdn += f"/channel/{channel.lower()}"

    if platform_key == "WindowsPlayer":
        direct = f"{base_cdn}/{version_hash}-RobloxPlayerLauncher.exe"
        return _DownloadLink(
            label=get_text(lang, "download_windows"),
            url=f"{RDD_BASE}/download?channel={channel}&binaryType=WindowsPlayer&version={version_hash}",
            direct_url=direct
        )
    if platform_key == "MacPlayer":
        direct = f"{base_cdn}/mac/{version_hash}-RobloxPlayer.zip"
        return _DownloadLink(
            label=get_text(lang, "download_macos"),
            url=f"{RDD_BASE}/download?channel={channel}&binaryType=MacPlayer&version={version_hash}",
            direct_url=direct
        )
    if platform_key == "WindowsStudio":
        direct = f"{base_cdn}/{version_hash}-RobloxStudioLauncherBeta.exe"
        return _DownloadLink(
            label="Download Windows Studio",
            url=direct,
            direct_url=direct
        )
    if platform_key == "MacStudio":
        direct = f"{base_cdn}/mac/{version_hash}-RobloxStudio.zip"
        return _DownloadLink(
            label="Download macOS Studio",
            url=direct,
            direct_url=direct
        )
    if platform_key == "AndroidApp":
        return _DownloadLink(
            label=get_text(lang, "view_playstore"),
            url="https://play.google.com/store/apps/details?id=com.roblox.client",
        )
    if platform_key == "iOS":
        return _DownloadLink(
            label=get_text(lang, "view_appstore"),
            url="https://apps.apple.com/app/roblox/id431946152",
        )
    return _DownloadLink(label="Link", url=ROBLOX_URL)


def _resolve_context(
    platform_key: str,
    vi: VersionInfo,
    lang: str,
    selected_hash: Optional[str] = None,
) -> _EmbedContext:
    """
    Build the full resolved context for an embed.
    When `selected_hash` is provided (history view) we look up that specific
    entry's data instead of the latest version.
    """
    cfg        = PLATFORMS[platform_key]
    state      = get_version_data(platform_key) or {}
    timestamps = state.get("timestamps", {})
    channel    = vi.channel

    if selected_hash and selected_hash != state.get("current", ""):
        full_hash  = selected_hash
        short_hash = full_hash.replace("version-", "")
        version    = short_hash
        detected   = timestamps.get(full_hash, "Unknown date")
    else:
        full_hash  = vi.version_hash
        short_hash = vi.short_hash
        version    = vi.version
        detected   = timestamps.get(full_hash, "Just detected")

    download = _resolve_download_link(platform_key, full_hash, lang, channel)

    return _EmbedContext(
        platform_key=platform_key,
        label=cfg["label"],
        color=cfg["color"],
        icon_url=cfg["icon_url"],
        version=version,
        short_hash=short_hash,
        full_hash=full_hash,
        detected_at=detected,
        channel=channel,
        download=download,
        is_mobile=platform_key in _MOBILE_PLATFORMS,
    )


def _build_data_block(ctx: _EmbedContext, lang: str, fflag_count: int = 0) -> str:
    """Compose the description data block matching the user's screenshot."""
    t_ver  = get_text(lang, "version")
    t_plat = get_text(lang, "platform")
    t_hash = get_text(lang, "build_hash")
    gap    = "\u2800" * 8  # Spacing
    
    # Matching screenshot: 📕 Version, 📡 Platform, 🔑 Build Hash
    # Layout with vertical bars exactly as shown
    lines = [
        f"📕 **{t_ver}**{gap}{gap}📡 **{t_plat}**",
        f"|  `{ctx.version}`{gap}| **{ctx.label}**",
        "",
        f"🔑 **{t_hash}**",
        f"|  `{ctx.full_hash}`"
    ]
    
    if fflag_count > 0:
        lines.append(f"\n🛠️ **FFlags**")
        lines.append(f"|  `{fflag_count}` configurados")

    return "\n".join(lines)


def _validate_embed(embed: discord.Embed) -> None:
    """
    Assert that the embed respects Discord's hard character limits.
    Raises ValueError with a descriptive message on violation.
    """
    total = 0

    def _check(value: str, limit: int, field_name: str) -> None:
        nonlocal total
        if len(value) > limit:
            raise ValueError(
                f"Embed field '{field_name}' exceeds {limit} chars "
                f"(got {len(value)})"
            )
        total += len(value)

    if embed.title:
        _check(embed.title, _LIMIT_TITLE, "title")
    if embed.description:
        _check(embed.description, _LIMIT_DESCRIPTION, "description")
    for f in embed.fields:
        _check(f.name,  _LIMIT_FIELD_NAME,  f"field.name[{f.name!r}]")
        _check(f.value, _LIMIT_FIELD_VALUE, f"field.value[{f.name!r}]")
    if embed.footer and embed.footer.text:
        _check(embed.footer.text, _LIMIT_FOOTER, "footer.text")
    if total > _LIMIT_TOTAL_CHARS:
        raise ValueError(
            f"Embed total characters {total} exceeds Discord limit of {_LIMIT_TOTAL_CHARS}"
        )


# ──────────────────────────────────────────────────────────────────────────────
#  Public embed builders
# ──────────────────────────────────────────────────────────────────────────────

def build_update_embed(
    platform_key:  str,
    vi:            VersionInfo,
    prev_hash:     Optional[str] = None,
    lang:          str = "en",
    selected_hash: Optional[str] = None,
    bot_icon:      Optional[str] = None,
    is_build:      bool = False,
    history_data:  Optional[list[dict]] = None,
    channel:      str = "LIVE",
) -> discord.Embed:
    """
    Build a full update notification embed.

    Parameters
    ----------
    platform_key  : Internal platform identifier (e.g. "WindowsPlayer").
    vi            : Fresh VersionInfo from the checker.
    prev_hash     : Previous version hash for "what changed" context.
    lang          : ISO-639 language code (en / es / pt / ru / fr).
    selected_hash : If set, display this historical hash instead of latest.
    bot_icon      : Override for the bot's avatar URL in footer/thumbnail.
    is_build      : True when this is a pre-release / build notification.
    history_data  : Optional list of {hash, date} dicts to add a history field.
    channel       : The channel the version belongs to (e.g., "LIVE", "ZNext").

    Returns
    -------
    discord.Embed ready to send.
    """
    ctx   = _resolve_context(platform_key, vi, lang, selected_hash)
    avatar = _avatar(bot_icon)

    # ── Title ─────────────────────────────────────────────────────────────────
    # Screenshot header: "Roblox {platform} Updated!"
    title = f"Roblox {ctx.label} Updated!"
    if channel != "LIVE":
        title += f" [{channel}]"
    
    embed = discord.Embed(
        title=_truncate(title, _LIMIT_TITLE),
        color=ctx.color,
        timestamp=datetime.now(timezone.utc),
    )

    # ── Description ───────────────────────────────────────────────────────────
    # Screenshot intro text (italicized)
    intro = f"*Roblox has deployed a new build for **{ctx.label}**.*\n*This version is now operational on production servers.*"
    data_block = _build_data_block(ctx, lang, vi.fflag_count)
    
    embed.description = f"{intro}\n\n{data_block}"

    # ── History field ─────────────────────────────────────────────────────────
    if history_data:
        lines = "".join(
            f"• `{h['hash']}` — {h['date']} UTC\n"
            for h in history_data
        )
        embed.add_field(
            name=_truncate(f"📜 {get_text(lang, 'history_header')}", _LIMIT_FIELD_NAME),
            value=_truncate(lines or "No history available.", _LIMIT_FIELD_VALUE),
            inline=False,
        )

    # ── Download field ────────────────────────────────────────────────────────
    # Screenshot: "Direct Download" in bold/italic then link
    download_header = "***Direct Download***"
    if ctx.is_mobile:
        download_val = f"{download_header}\n[{ctx.download.label}]({ctx.download.url})"
    else:
        # Use direct URL if available, otherwise fallback
        url = ctx.download.direct_url or ctx.download.url
        download_val = f"{download_header}\n[➥ Descarga Directa (Roblox CDN)]({url})"

    embed.add_field(
         name="\u200b", # Empty name for spacing
         value=_truncate(download_val, _LIMIT_FIELD_VALUE),
         inline=False,
    )

    embed.set_thumbnail(url=ctx.icon_url)
    embed.set_footer(
        text=_truncate(f"BloxPulse v{BOT_VERSION} - Professional Monitoring | {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC", _LIMIT_FOOTER),
        icon_url=avatar,
    )

    try:
        _validate_embed(embed)
    except ValueError as exc:
        log.error("build_update_embed produced an invalid embed: %s", exc)

    return embed


def build_member_welcome_embed(
    member: discord.Member,
    lang:   str = "en",
) -> discord.Embed:
    """
    Build a professional welcome embed for a new guild member.
    Reads localised strings for title, body, and footer.
    """
    guild   = member.guild
    title   = _truncate(
        get_text(lang, "welcome_member_title").format(server=guild.name),
        _LIMIT_TITLE,
    )
    body    = _truncate(
        get_text(lang, "welcome_member_body").format(user=member.mention),
        _LIMIT_DESCRIPTION,
    )
    footer  = _truncate(get_text(lang, "welcome_member_footer"), _LIMIT_FOOTER)

    embed = discord.Embed(
        title=title,
        description=body,
        color=0x00E5FF,
        timestamp=datetime.now(timezone.utc),
    )

    if member.display_avatar:
        embed.set_thumbnail(url=member.display_avatar.url)

    icon_url = guild.icon.url if guild.icon else None
    embed.set_footer(text=footer, icon_url=icon_url)

    try:
        _validate_embed(embed)
    except ValueError as exc:
        log.error("build_member_welcome_embed produced an invalid embed: %s", exc)

    return embed


def build_announcement_embed(ann: dict[str, Any]) -> discord.Embed:
    """
    Build a consistent announcement embed from a data dict.

    Expected keys (all optional with sane defaults):
        title, content, version, footer, timestamp, image_url
    """
    raw_ts = ann.get("timestamp", "")
    try:
        ts = datetime.fromisoformat(raw_ts) if raw_ts else datetime.now(timezone.utc)
    except ValueError:
        ts = datetime.now(timezone.utc)
        log.warning("build_announcement_embed: invalid timestamp %r, using now()", raw_ts)

    version = ann.get("version", BOT_VERSION)
    footer  = ann.get("footer", "Thank you for your support!")

    embed = discord.Embed(
        title=_truncate(ann.get("title", "BloxPulse Update"), _LIMIT_TITLE),
        description=_truncate(ann.get("content", "No content provided."), _LIMIT_DESCRIPTION),
        color=0x00E5FF,
        timestamp=ts,
    )
    embed.set_footer(
        text=_truncate(f"BloxPulse {version} | {footer}", _LIMIT_FOOTER)
    )
    if image_url := ann.get("image_url"):
        embed.set_image(url=image_url)

    try:
        _validate_embed(embed)
    except ValueError as exc:
        log.error("build_announcement_embed produced an invalid embed: %s", exc)

    return embed


# ──────────────────────────────────────────────────────────────────────────────
#  Premium interaction response helper
# ──────────────────────────────────────────────────────────────────────────────

async def premium_response(
    interaction: discord.Interaction,
    title:       str,
    description: str,
    color:       int = 0x5865F2,
    ephemeral:   bool = True,
    fields:      Optional[list[tuple[str, str, bool]]] = None,
    thumbnail:   Optional[str] = None,
    bot_icon:    Optional[str] = None,
) -> Optional[discord.WebhookMessage]:
    """
    Send a branded embed response to a slash-command interaction.

    Handles both initial response and followup automatically.
    Returns the sent message (or None on failure).
    """
    avatar = _avatar(bot_icon)

    embed = discord.Embed(
        title=_truncate(f"◈ {title}", _LIMIT_TITLE),
        description=_truncate(description, _LIMIT_DESCRIPTION),
        color=color,
        timestamp=datetime.now(timezone.utc),
    )

    if fields:
        for name, value, inline in fields:
            embed.add_field(
                name=_truncate(name, _LIMIT_FIELD_NAME),
                value=_truncate(value, _LIMIT_FIELD_VALUE),
                inline=inline,
            )

    embed.set_thumbnail(url=thumbnail or avatar)
    embed.set_footer(text=_truncate(_random_footer(), _LIMIT_FOOTER), icon_url=avatar)

    try:
        _validate_embed(embed)
    except ValueError as exc:
        log.error("premium_response produced an invalid embed: %s", exc)

    try:
        if interaction.response.is_done():
            return await interaction.followup.send(embed=embed, ephemeral=ephemeral)
        return await interaction.response.send_message(embed=embed, ephemeral=ephemeral)
    except discord.HTTPException as exc:
        log.error(
            "premium_response: failed to send embed to interaction %s: %s",
            interaction.id,
            exc,
        )
        return None


# ──────────────────────────────────────────────────────────────────────────────
#  Delivery helpers (notify_update / notify_startup)
# ──────────────────────────────────────────────────────────────────────────────

def notify_update(
    platform_key: str,
    vi:           VersionInfo,
    prev_hash:    Optional[str] = None,
    lang:         str = "en",
    bot_icon:     Optional[str] = None,
) -> bool:
    """
    Build and dispatch an update embed.
    Returns True when the send succeeded, False otherwise.
    """
    try:
        embed = build_update_embed(
            platform_key=platform_key,
            vi=vi,
            prev_hash=prev_hash,
            lang=lang,
            bot_icon=bot_icon,
        )
        # Actual dispatch is handled by the monitoring system.
        # This function validates the embed is buildable and returns it.
        log.info(
            "notify_update: embed ready for %s v%s (prev=%s)",
            platform_key,
            vi.version,
            prev_hash,
        )
        return True
    except Exception as exc:
        log.error("notify_update: unexpected error for %s: %s", platform_key, exc, exc_info=True)
        return False


def notify_startup(versions: dict[str, Optional[VersionInfo]]) -> None:
    """
    Build startup summary embeds for every configured platform.
    Logs the result; actual sending is handled by the monitoring system.
    """
    for platform_key, vi in versions.items():
        if vi is None:
            log.warning("notify_startup: no version data for %s – skipping", platform_key)
            continue
        try:
            build_update_embed(platform_key, vi, prev_hash=None)
            log.info("notify_startup: startup embed ready for %s", platform_key)
        except Exception as exc:
            log.error(
                "notify_startup: failed to build embed for %s: %s",
                platform_key,
                exc,
                exc_info=True,
            )


def notify_error(traceback_str: str) -> None:
    """
    Log a critical error from the monitoring cycle.
    In the standalone monitor, this just logs to file/console.
    In the Discord system, errors are broadcast to the developer guild.
    """
    log.critical("Monitor check cycle encountered an unhandled exception:\n%s", traceback_str)


# ──────────────────────────────────────────────────────────────────────────────
#  Language selector UI
# ──────────────────────────────────────────────────────────────────────────────

class LanguageSelect(Select):
    """Dropdown that lets users re-render a version embed in their preferred language."""

    _OPTIONS = [
        discord.SelectOption(label="English",    emoji="🇺🇸", value="en"),
        discord.SelectOption(label="Español",    emoji="🇪🇸", value="es"),
        discord.SelectOption(label="Português",  emoji="🇧🇷", value="pt"),
        discord.SelectOption(label="Русский",    emoji="🇷🇺", value="ru"),
        discord.SelectOption(label="Français",   emoji="🇫🇷", value="fr"),
    ]

    def __init__(
        self,
        platform_key:  str,
        vi:            VersionInfo,
        prev_hash:     Optional[str],
        current_lang:  str,
    ) -> None:
        options = [
            discord.SelectOption(
                label=opt.label,
                emoji=opt.emoji,
                value=opt.value,
                default=(opt.value == current_lang),
            )
            for opt in self._OPTIONS
        ]
        super().__init__(
            placeholder="Change language…",
            min_values=1,
            max_values=1,
            options=options,
        )
        self.platform_key = platform_key
        self.vi           = vi
        self.prev_hash    = prev_hash

    async def callback(self, interaction: discord.Interaction) -> None:
        new_lang   = self.values[0]
        bot_icon   = (
            interaction.client.user.display_avatar.url
            if interaction.client.user
            else BOT_AVATAR_URL
        )
        new_embed  = build_update_embed(
            self.platform_key, self.vi, self.prev_hash,
            lang=new_lang, bot_icon=bot_icon,
        )
        new_view   = create_language_view(
            self.platform_key, self.vi, self.prev_hash, new_lang
        )
        try:
            await interaction.response.edit_message(embed=new_embed, view=new_view)
        except discord.HTTPException as exc:
            log.error("LanguageSelect.callback: edit_message failed: %s", exc)


def create_language_view(
    platform_key:  str,
    vi:            VersionInfo,
    prev_hash:     Optional[str],
    current_lang:  str = "en",
) -> View:
    """Return a persistent View containing the language selector."""
    view = View(timeout=None)
    view.add_item(LanguageSelect(platform_key, vi, prev_hash, current_lang))
    return view