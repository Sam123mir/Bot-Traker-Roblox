# ============================================================
#   BloxPulse | Roblox Version Monitor — notifier.py
#   Builds update embeds and interactive dual-dropdown view.
# ============================================================

import discord
from discord.ui import View, Select
from datetime import datetime, timezone
from typing import Optional

from config import PLATFORMS, BOT_AVATAR_URL, ROBLOX_URL, BOT_VERSION
from .checker import VersionInfo
from .i18n import get_text
from .storage import get_version_data

RDD_BASE = "https://rdd.latte.to"

# ── Helpers ───────────────────────────────────────────────────

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

# ── Embed Builder ─────────────────────────────────────────────

def build_update_embed(
    platform_key: str,
    vi: VersionInfo,
    prev_hash: Optional[str],
    lang: str = "en",
    selected_hash: Optional[str] = None,  # None = show current vi
    bot_icon: Optional[str] = None,
    is_build: bool = False,
    history_data: Optional[list] = None
) -> discord.Embed:
    cfg   = PLATFORMS[platform_key]
    label = cfg["label"]
    gap   = "\u2800" * 4

    # Determine what to display
    state      = get_version_data(platform_key)
    timestamps = state.get("timestamps", {})
    channel    = vi.channel # Get channel from VersionInfo

    if selected_hash and selected_hash != state.get("current", ""):
        # Viewing a historical version
        d_hash    = selected_hash
        d_short   = d_hash.replace("version-", "")
        d_version = d_short
        dt_str    = timestamps.get(d_hash, "Unknown date")
        dl_label, dl_url = _download_link(platform_key, d_hash, lang, channel=channel)
        is_historical = True
    else:
        # Current version
        d_hash    = vi.version_hash
        d_short   = vi.short_hash
        d_version = vi.version
        dt_str    = timestamps.get(d_hash, "Just detected")
        dl_label, dl_url = _download_link(platform_key, d_hash, lang, channel=channel)
        is_historical = False

    # Translated field labels
    t_ver  = get_text(lang, "version")
    t_plat = get_text(lang, "platform")
    t_hash = get_text(lang, "build_hash")
    t_dl_h = get_text(lang, "download_header")

    # Data block refined for "WOW" factor
    mobile = _is_mobile(platform_key)
    if not mobile:
        data_block = (
            f"📦 **{t_ver}**\n"
            f"┗ `{d_version}`\n\n"
            f"📡 **{t_plat}**\n"
            f"┗ **{label}**\n\n"
            f"🔑 **{t_hash}**\n"
            f"┗ `{d_short}`\n\n"
            f"🌐 **Channel**\n"
            f"┗ `{channel}`\n\n"
            f"📅 **Detected**\n"
            f"┗ `{dt_str}`"
        )
    else:
        # Mobile layout - compact but clear
        data_block = (
            f"🔖 **{t_ver}**: `{d_version}`\n"
            f"📡 **{t_plat}**: {label}\n"
            f"🔑 **{t_hash}**: `{d_short}`\n"
            f"🌐 **Channel**: `{channel}`\n"
            f"📅 **Detected**: {dt_str}"
        )

    intro_tag = " — *Historical Build*" if is_historical else ""
    intro     = (
        f"{get_text(lang, 'intro_1', platform=label)}\n"
        f"{get_text(lang, 'intro_2')}{intro_tag}"
    )
    description = f"{intro}\n\n{data_block}"

    title = get_text(lang, "update_title", platform=label)
    color = cfg["color"]
    
    if is_build:
        title = f"⚠️ Build Detected on {label}!"
        color = 0xF1C40F # Warning Yellow for pre-release
        description = (
            f"**{label} has just built a new version!**\n"
            f"**THIS IS NOT A ROBLOX UPDATE**\n\n"
            f"Roblox has just built a new version! This version might be the next update!\n\n"
            f"{data_block}"
        )
    embed = discord.Embed(
        title=title,
        description=description,
        url=ROBLOX_URL,
        color=color,
    )
    
    # LOGOS: Use platform-specific icon for thumbnail, bot avatar for footer
    platform_icon = cfg.get("icon_url")
    avatar_url = bot_icon or BOT_AVATAR_URL
    
    if platform_icon:
        embed.set_thumbnail(url=platform_icon)
    else:
        embed.set_thumbnail(url=avatar_url)
    
    # COMPONENTS: Show detected components from manifest
    if vi.components:
        # Identify "key" components (exe, dll, or first few zips)
        key_items = [c for c in vi.components if c.endswith((".exe", ".dll"))][:5]
        other_zips = [c for c in vi.components if c.endswith(".zip") and c not in key_items]
        
        comp_text = ""
        if key_items:
            comp_text += "**Principales:**\n" + "\n".join([f"• `{c}`" for c in key_items]) + "\n"
        
        if other_zips:
            comp_text += f"\n**Otros:** `{len(other_zips)}` archivos .zip detectados."
            
        embed.add_field(name="📦 Componentes del Despliegue", value=comp_text or "No se detectaron archivos individuales.", inline=False)

    if history_data:
        history_text = ""
        for item in history_data:
            h_short = item["hash"].replace("version-", "")
            history_text += f"• `{h_short}` — {item['date']}\n"
        embed.add_field(name="📜 Recent History", value=history_text or "No history", inline=False)

    embed.add_field(
        name=f"*{t_dl_h}*",
        value=f"**[{dl_label}]({dl_url})**",
        inline=False,
    )
    embed.set_footer(
        text=f"BloxPulse {BOT_VERSION} · Professional Monitoring | {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC",
        icon_url=avatar_url,
    )
    return embed

# ── Dropdown: Language Selector ───────────────────────────────

class LanguageSelector(Select):
    def __init__(self, platform_key: str, vi: VersionInfo, prev_hash: str, lang: str, selected_hash: Optional[str] = None, bot_icon: Optional[str] = None):
        self.platform_key  = platform_key
        self.vi            = vi
        self.prev_hash     = prev_hash
        self.current_lang  = lang
        self.selected_hash = selected_hash
        self.bot_icon      = bot_icon

        options = [
            discord.SelectOption(label="English",   value="en"),
            discord.SelectOption(label="Espanol",   value="es"),
            discord.SelectOption(label="Portugues", value="pt"),
            discord.SelectOption(label="Russkiy",   value="ru"),
            discord.SelectOption(label="Francais",  value="fr"),
        ]
        super().__init__(placeholder="Change Language", options=options, row=0)

    async def callback(self, interaction: discord.Interaction):
        new_lang = self.values[0]
        embed    = build_update_embed(self.platform_key, self.vi, self.prev_hash, new_lang, self.selected_hash, bot_icon=self.bot_icon)
        view     = create_language_view(self.platform_key, self.vi, self.prev_hash, new_lang, self.selected_hash, bot_icon=self.bot_icon)
        await interaction.response.edit_message(embed=embed, view=view)

# ── Dropdown: Version History Selector ───────────────────────

class VersionHistorySelector(Select):
    def __init__(self, platform_key: str, vi: VersionInfo, prev_hash: str, lang: str, selected_hash: Optional[str] = None, bot_icon: Optional[str] = None):
        self.platform_key  = platform_key
        self.vi            = vi
        self.prev_hash     = prev_hash
        self.lang          = lang
        self.selected_hash = selected_hash
        self.bot_icon      = bot_icon

        state      = get_version_data(platform_key)
        history    = state.get("history", [])
        current    = state.get("current", "")
        timestamps = state.get("timestamps", {})

        options = []

        # Current version option
        curr_date = timestamps.get(current, "Latest")
        options.append(discord.SelectOption(
            label=f"Current  —  {curr_date}",
            value="__current__",
            description=current.replace("version-", ""),
            default=(selected_hash is None or selected_hash == current),
        ))

        # Historical entries
        for h in history:
            if h == current:
                continue
            date_str = timestamps.get(h, "Unknown date")
            short    = h.replace("version-", "")
            options.append(discord.SelectOption(
                label=f"Previous  —  {date_str}",
                value=h,
                description=short,
                default=(selected_hash == h),
            ))

        if len(options) == 1:
            options.append(discord.SelectOption(
                label="No history recorded yet",
                value="__none__",
                description="The bot will track versions from now on",
            ))

        super().__init__(
            placeholder="View Previous Version",
            options=options[:25],  # Discord max
            row=1,
        )

    async def callback(self, interaction: discord.Interaction):
        val = self.values[0]
        if val == "__none__":
            await interaction.response.defer()
            return

        new_sel = None if val == "__current__" else val
        embed   = build_update_embed(self.platform_key, self.vi, self.prev_hash, self.lang, new_sel, bot_icon=self.bot_icon)
        view    = create_language_view(self.platform_key, self.vi, self.prev_hash, self.lang, new_sel, bot_icon=self.bot_icon)
        await interaction.response.edit_message(embed=embed, view=view)

# ── View Factory ──────────────────────────────────────────────

def create_language_view(
    platform_key: str,
    vi: VersionInfo,
    prev_hash: str,
    current_lang: str = "en",
    selected_hash: Optional[str] = None,
    bot_icon: Optional[str] = None,
) -> View:
    """Creates the dual-dropdown View (Language + Version History)."""
    view = View(timeout=None)
    view.add_item(LanguageSelector(platform_key, vi, prev_hash, current_lang, selected_hash, bot_icon=bot_icon))
    view.add_item(VersionHistorySelector(platform_key, vi, prev_hash, current_lang, selected_hash, bot_icon=bot_icon))
    return view
