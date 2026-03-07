import os as _os
_BASE = _os.path.dirname(_os.path.abspath(__file__))

# ── Discord Bot ─────────────────────────────────────────────
DISCORD_BOT_TOKEN = _os.getenv("DISCORD_BOT_TOKEN", "REPLACE_ME_IN_HOSTING")
DEVELOPERS       = [1420085090570207313] # ID del usuario dueño/dev
OFFICIAL_GUILD_ID = 134444555666777888  # Reemplaza con el ID de tu servidor oficial
DEFAULT_LANGUAGE  = "en" 

# ── Intervalos ────────────────────────────────────────────────
CHECK_INTERVAL   = 300    # Segundos entre cada ciclo de chequeo (5 min)
HEARTBEAT_EVERY  = 3600   # Segundos entre logs de "sigo vivo" (1 hora)
REQUEST_TIMEOUT  = 10     # Timeout por petición HTTP
RETRY_ATTEMPTS   = 3      # Reintentos ante fallo de red
RETRY_DELAY      = 5      # Segundos entre reintentos
HISTORY_DAYS     = 30     # Días de historial a mostrar en /version
HISTORY_MAX      = 50     # Máximo de entradas en dropdown de Discord

# ── Almacenamiento ────────────────────────────────────────────
VERSIONS_FILE  = _os.path.join(_BASE, "data", "versions.json")
GUILDS_FILE    = _os.path.join(_BASE, "data", "guilds.json")
ANNOUNCEMENTS_FILE = _os.path.join(_BASE, "data", "announcements.json")
LOG_FILE       = _os.path.join(_BASE, "logs", "monitor.log")

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

# ── Branding ──────────────────────────────────────────────────
BOT_VERSION    = "v1.9.6"
BOT_NAME       = "BloxPulse · Roblox Monitor"
BOT_AVATAR_URL = "https://cdn-icons-png.flaticon.com/512/8157/8157523.png"
ROBLOX_ICON    = "https://cdn-icons-png.flaticon.com/512/18868/18868601.png"
ROBLOX_URL     = "https://www.roblox.com"
OFFICIAL_SERVER_URL = "https://discord.gg/7XU8YbDC" # Placeholder for user's community server
UPDATE_BANNER_URL   = "https://media1.giphy.com/media/v1.Y2lkPTc5MGI3NjExNXpoZTZ4ZXg2NjFra3hqa3BwMHY4Mm5pemY0Mms3eTU4ZzRtNjd0NiZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/7qJWn3LsiSe2WoOABJ/giphy.gif"

# ── Platform Mapping ──────────────────────────────────────────
API_PLATFORM_MAPPING = {
    "windows": "WindowsPlayer",
    "mac":     "MacPlayer",
    "android": "AndroidApp",
    "ios":     "iOS",
}
