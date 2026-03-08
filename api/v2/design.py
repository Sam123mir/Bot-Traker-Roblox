# api/v2/design.py
"""
Single source of truth for BloxPulse branding and design tokens.
Synchronized with the Discord bot's premium visual style.
"""

from __future__ import annotations

PLATFORM_META: dict[str, dict] = {
    "WindowsPlayer": {
        "label":    "Windows",
        "emoji":    "🪟",
        "color":    "#00B4D8",        # hex for web
        "color_int": 0x00B4D8,        # int for Discord
        "icon_url": "https://cdn.bloxpulse.dev/icons/windows.png",
        "group":    "desktop",
    },
    "MacPlayer": {
        "label":    "macOS",
        "emoji":    "🍎",
        "color":    "#A8DADC",
        "color_int": 0xA8DADC,
        "icon_url": "https://cdn.bloxpulse.dev/icons/macos.png",
        "group":    "desktop",
    },
    "AndroidApp": {
        "label":    "Android",
        "emoji":    "🤖",
        "color":    "#A8D5A2",
        "color_int": 0xA8D5A2,
        "icon_url": "https://cdn.bloxpulse.dev/icons/android.png",
        "group":    "mobile",
    },
    "iOS": {
        "label":    "iOS",
        "emoji":    "📱",
        "color":    "#F4A261",
        "color_int": 0xF4A261,
        "icon_url": "https://cdn.bloxpulse.dev/icons/ios.png",
        "group":    "mobile",
    },
}

# Generic Branding
COLOR_PRIMARY = "#5865F2"
COLOR_SUCCESS = "#57F287"
COLOR_DANGER  = "#ED4245"
COLOR_NEUTRAL = "#2B2D31"
