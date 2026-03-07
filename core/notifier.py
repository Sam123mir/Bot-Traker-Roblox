# core/notifier.py
"""
Embed builders and messaging utilities.
Handles the creation of professional Discord embeds for notifications.
"""
from __future__ import annotations

import random
from datetime import datetime, timezone
from typing import Optional

import discord
from discord.ui import Select, View

from config import BOT_AVATAR_URL, BOT_VERSION, PLATFORMS, ROBLOX_URL
from .checker import VersionInfo
from .i18n import get_text
from .storage import get_version_data

RDD_BASE = "https://rdd.latte.to"

# ──────────────────────────────────────────────────────────────────────────────
#  Premium Responses
# ──────────────────────────────────────────────────────────────────────────────

async def premium_response(
    interaction: discord.Interaction,
    title: str,
    description: str,
    color: int = 0x5865F2,
    ephemeral: bool = True,
    fields: list = None,
    thumbnail: str = None,
    bot_icon: str = None
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
    
    avatar_url = bot_icon or BOT_AVATAR_URL
    
    if thumbnail:
        embed.set_thumbnail(url=thumbnail)
    else:
        embed.set_thumbnail(url=avatar_url)
    
    footers = [
        "BloxPulse Monitor ⬢",
        "Global Roblox Tracker ⬢",
        "Monitoring with Pulse ✨",
        "Stay updated, stay fast ✨",
        "Professional Monitoring ◈ BloxPulse"
    ]
    embed.set_footer(text=f"{random.choice(footers)}", icon_url=avatar_url)
    
    try:
        if interaction.response.is_done():
            return await interaction.followup.send(embed=embed, ephemeral=ephemeral)
        else:
            return await interaction.response.send_message(embed=embed, ephemeral=ephemeral)
    except Exception:
        pass

# ──────────────────────────────────────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────────────────────────────────────
def _download_link(platform_key: str, version_hash: str, lang: str, channel: str = "LIVE") -> tuple[str, str]:
    if platform_key == "WindowsPlayer":
        url = f"{RDD_BASE}/?channel={channel}&binaryType=WindowsPlayer&version={version_hash}"
        return get_text(lang, "download_windows"), url
    if platform_key == "MacPlayer":
        url = f"{RDD_BASE}/?channel={channel}&binaryType=MacPlayer&version={version_hash}"
        return get_text(lang, "download_macos"), url
    if platform_key == "AndroidApp":
        return get_text(lang, "view_playstore"), "https://play.google.com/store/apps/details?id=com.roblox.client"
    if platform_key == "iOS":
        return get_text(lang, "view_appstore"), "https://apps.apple.com/app/roblox/id431946152"
    return "Link", ROBLOX_URL

def _is_mobile(platform_key: str) -> bool:
    return platform_key in ("AndroidApp", "iOS")

# ──────────────────────────────────────────────────────────────────────────────
#  Embed Builder
# ──────────────────────────────────────────────────────────────────────────────
def build_update_embed(
    platform_key: str,
    vi: VersionInfo,
    prev_hash: Optional[str],
    lang: str = "en",
    selected_hash: Optional[str] = None,
    bot_icon: Optional[str] = None,
    is_build: bool = False,
    history_data: Optional[list] = None
) -> discord.Embed:
    cfg = PLATFORMS[platform_key]
    label = cfg["label"]
    
    state = get_version_data(platform_key)
    timestamps = state.get("timestamps", {})
    channel = vi.channel

    if selected_hash and selected_hash != state.get("current", ""):
        d_hash = selected_hash
        d_short = d_hash.replace("version-", "")
        d_version = d_short
        dt_str = timestamps.get(d_hash, "Unknown date")
        dl_label, dl_url = _download_link(platform_key, d_hash, lang, channel=channel)
    else:
        d_hash = vi.version_hash
        d_short = vi.short_hash
        d_version = vi.version
        dt_str = timestamps.get(d_hash, "Just detected")
        dl_label, dl_url = _download_link(platform_key, d_hash, lang, channel=channel)

    t_ver = get_text(lang, "version")
    t_plat = get_text(lang, "platform")
    t_hash = get_text(lang, "build_hash")
    
    gap = "\u2800" * 6

    if not _is_mobile(platform_key): 
        data_block = (
            f"𖤘 **{t_ver}**{gap}{gap}⬢ **{t_plat}**\n"
            f"| `{d_version}`{gap}| **{label}**\n\n"
            f"⚿ **{t_hash}**{gap}{gap}🗓️ **Detected**\n"
            f"| `{d_short}`{gap}| `{dt_str}`\n\n"
            f"⬢ **Channel**\n"
            f"| `{channel}`"
        )
    else:
        data_block = (
            f"𖤘 **{t_ver}**: | `{d_version}`\n"
            f"⬢ **{t_plat}**: | **{label}**\n"
            f"⚿ **{t_hash}**: | `{d_short}`\n"
            f"🗓️ **Detected**: | `{dt_str}`\n"
            f"⬢ **Channel**: | `{channel}`"
        )

    title = get_text(lang, "update_title").format(platform=label)
    if is_build:
        title = f"🛠️ Pre-release Build: {label}"

    embed = discord.Embed(
        title=title,
        description=get_text(lang, "intro_1").format(platform=label) + "\n\n" + data_block,
        color=cfg["color"],
        timestamp=datetime.now(timezone.utc),
    )
    
    if history_data:
        h_text = ""
        for h in history_data:
            h_short = h['hash'].replace('version-','')[:12]
            h_text += f"• `{h_short}` — {h['date']}\n"
        embed.add_field(name=f"🕒 {get_text(lang, 'history_header')}", value=h_text or "No history", inline=False)

    embed.add_field(name=f"📦 {get_text(lang, 'download_header')}", value=f"**[{dl_label}]({dl_url})**", inline=False)
    
    avatar_url = bot_icon or BOT_AVATAR_URL
    embed.set_footer(text=f"BloxPulse {BOT_VERSION} · Professional Monitoring", icon_url=avatar_url)
    embed.set_thumbnail(url=cfg["icon_url"])
    
    return embed

def build_member_welcome_embed(member: discord.Member, lang: str = "en") -> discord.Embed:
    """Builds a professional welcome embed for new members."""
    guild = member.guild
    server_name = guild.name
    user_mention = member.mention
    
    title = get_text(lang, "welcome_member_title").format(server=server_name)
    body = get_text(lang, "welcome_member_body").format(user=user_mention)
    footer_text = get_text(lang, "welcome_member_footer")
    
    embed = discord.Embed(
        title=title,
        description=body,
        color=0x00e5ff, 
        timestamp=datetime.now(timezone.utc)
    )
    
    avatar_url = member.display_avatar.url if member.display_avatar else None
    if avatar_url:
        embed.set_thumbnail(url=avatar_url)
        
    icon_url = guild.icon.url if guild.icon else None
    if icon_url:
        embed.set_footer(text=footer_text, icon_url=icon_url)
    else:
        embed.set_footer(text=footer_text)
        
    return embed

def build_announcement_embed(ann_data: dict) -> discord.Embed:
    """Helper to maintain a consistent style across broadcast and history."""
    embed = discord.Embed(
        title=ann_data.get("title", "BloxPulse Update"),
        description=ann_data.get("content", "No content provided."),
        color=0x00e5ff,
        timestamp=datetime.fromisoformat(ann_data.get("timestamp", datetime.now(timezone.utc).isoformat()))
    )
    
    version = ann_data.get("version", "v1.0")
    footer = ann_data.get("footer", "Thank you for your support!")
    embed.set_footer(text=f"BloxPulse {version} | {footer}")
    
    if ann_data.get("image_url"):
        embed.set_image(url=ann_data.get("image_url"))
        
    return embed

# ──────────────────────────────────────────────────────────────────────────────
#  Views
# ──────────────────────────────────────────────────────────────────────────────
class LanguageSelect(Select):
    def __init__(self, platform_key, vi, prev_hash, current_lang):
        options = [
            discord.SelectOption(label="English 🇺🇸",   value="en", default=(current_lang=="en")),
            discord.SelectOption(label="Español 🇪🇸",   value="es", default=(current_lang=="es")),
            discord.SelectOption(label="Português 🇧🇷", value="pt", default=(current_lang=="pt")),
            discord.SelectOption(label="Русский 🇷🇺",   value="ru", default=(current_lang=="ru")),
            discord.SelectOption(label="Français 🇫🇷",  value="fr", default=(current_lang=="fr")),
        ]
        super().__init__(placeholder="Change Language", options=options)
        self.platform_key = platform_key
        self.vi = vi
        self.prev_hash = prev_hash

    async def callback(self, interaction: discord.Interaction):
        new_lang = self.values[0]
        avatar_url = interaction.client.user.display_avatar.url if interaction.client.user else BOT_AVATAR_URL
        new_embed = build_update_embed(self.platform_key, self.vi, self.prev_hash, lang=new_lang, bot_icon=avatar_url)
        new_view = create_language_view(self.platform_key, self.vi, self.prev_hash, new_lang)
        await interaction.response.edit_message(embed=new_embed, view=new_view)

def create_language_view(platform_key, vi, prev_hash, current_lang):
    view = View(timeout=None)
    view.add_item(LanguageSelect(platform_key, vi, prev_hash, current_lang))
    return view
