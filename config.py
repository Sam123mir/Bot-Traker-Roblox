# config.py
"""
Global configuration for the BloxPulse Bot project.
Contains API keys, paths, default intervals, and branding settings.
"""
from __future__ import annotations

import os as _os

_BASE = _os.path.dirname(_os.path.abspath(__file__))

# ──────────────────────────────────────────────────────────────────────────────
#  Discord Bot settings
# ──────────────────────────────────────────────────────────────────────────────
DISCORD_BOT_TOKEN: str = _os.getenv("DISCORD_BOT_TOKEN", "REPLACE_ME_IN_HOSTING")
DEVELOPERS: list[int]  = [1420085090570207313]  # ID del usuario administrador principal
OFFICIAL_GUILD_ID: int = 1474129389125107883    # ID de tu servidor oficial
DEFAULT_LANGUAGE: str  = "en"

# ──────────────────────────────────────────────────────────────────────────────
#  Monitoring Intervals
# ──────────────────────────────────────────────────────────────────────────────
CHECK_INTERVAL: int   = 300    # Segundos entre cada ciclo de chequeo (5 min)
HEARTBEAT_EVERY: int  = 3600   # Segundos entre logs de "sigo vivo" (1 hora)
REQUEST_TIMEOUT: int  = 10     # Timeout por petición HTTP
RETRY_ATTEMPTS: int   = 3      # Reintentos ante fallo de red
RETRY_DELAY: int      = 5      # Segundos entre reintentos
HISTORY_DAYS: int     = 30     # Días de historial a mostrar en /version
HISTORY_MAX: int      = 50     # Máximo de entradas en dropdown de Discord

# ──────────────────────────────────────────────────────────────────────────────
#  Storage Paths
# ──────────────────────────────────────────────────────────────────────────────
VERSIONS_FILE: str      = _os.path.join(_BASE, "data", "versions.json")
GUILDS_FILE: str        = _os.path.join(_BASE, "data", "guilds.json")
ANNOUNCEMENTS_FILE: str = _os.path.join(_BASE, "data", "announcements.json")
LOG_FILE: str           = _os.path.join(_BASE, "logs", "monitor.log")

# ... (Plataformas se mantienen igual)
PLATFORMS: dict = {
    "WindowsPlayer": {
        "label":      "Windows (PC)",
        "color":      0x0078D4,
        "icon_url":   "https://cdn-icons-png.flaticon.com/512/882/882702.png",
        "source":     "cdn",
        "api_key":    "WindowsPlayer",
    },
    "MacPlayer": {
        "label":      "macOS",
        "color":      0x636366,
        "icon_url":   "https://cdn-icons-png.flaticon.com/512/2/2235.png",
        "source":     "cdn",
        "api_key":    "MacPlayer",
    },
    "AndroidApp": {
        "label":      "Android",
        "color":      0x3DDC84,
        "icon_url":   "https://cdn-icons-png.flaticon.com/512/270/270780.png",
        "source":     "playstore",
        "api_key":    "AndroidApp",
    },
    "iOS": {
        "label":      "iPhone / iPad",
        "color":      0xFFFFFF,
        "icon_url":   "https://cdn-icons-png.flaticon.com/512/0/747.png",
        "source":     "appstore",
        "bundle_id":  "com.roblox.roblox",
    },
}

# ──────────────────────────────────────────────────────────────────────────────
#  Branding & Assets
# ──────────────────────────────────────────────────────────────────────────────
BOT_VERSION: str         = "v1.9.6"
BOT_NAME: str            = "BloxPulse · Roblox Monitor"
BOT_AVATAR_URL: str      = "https://cdn-icons-png.flaticon.com/512/8157/8157523.png"
ROBLOX_ICON: str         = "https://cdn-icons-png.flaticon.com/512/18868/18868601.png"
ROBLOX_URL: str          = "https://www.roblox.com"
OFFICIAL_SERVER_URL: str = "https://discord.gg/7XU8YbDC" # Placeholder for user's community server
UPDATE_BANNER_URL: str   = "https://media1.giphy.com/media/v1.Y2lkPTc5MGI3NjExNXpoZTZ4ZXg2NjFra3hqa3BwMHY4Mm5pemY0Mms3eTU4ZzRtNjd0NiZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/7qJWn3LsiSe2WoOABJ/giphy.gif"

# ──────────────────────────────────────────────────────────────────────────────
#  Platform Mapping (for API and internal key resolution)
# ──────────────────────────────────────────────────────────────────────────────
API_PLATFORM_MAPPING: dict[str, str] = {
    "windows": "WindowsPlayer",
    "mac":     "MacPlayer",
    "android": "AndroidApp",
    "ios":     "iOS",
}
