import os as _os
_BASE = _os.path.dirname(_os.path.abspath(__file__))

# ── Discord Bot ─────────────────────────────────────────────
DISCORD_BOT_TOKEN = _os.getenv("DISCORD_BOT_TOKEN", "REPLACE_ME_IN_HOSTING")
DEVELOPERS       = [1420085090570207313] # ID del usuario dueño/dev
DEFAULT_LANGUAGE  = "en" 

# ── Intervalos ────────────────────────────────────────────────
CHECK_INTERVAL   = 300    # Segundos entre cada ciclo de chequeo (5 min)
HEARTBEAT_EVERY  = 3600   # Segundos entre logs de "sigo vivo" (1 hora)
REQUEST_TIMEOUT  = 10     # Timeout por petición HTTP
RETRY_ATTEMPTS   = 3      # Reintentos ante fallo de red
RETRY_DELAY      = 5      # Segundos entre reintentos
HISTORY_DAYS     = 7      # Días de historial a mostrar en /version
HISTORY_MAX      = 25     # Máximo de entradas en dropdown de Discord

# ── Almacenamiento ────────────────────────────────────────────
VERSIONS_FILE  = _os.path.join(_BASE, "data", "versions.json")
GUILDS_FILE    = _os.path.join(_BASE, "data", "guilds.json")
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
BOT_NAME       = "X-Blaze · Roblox Monitor"
BOT_AVATAR_URL = "https://cdn-icons-png.flaticon.com/512/18868/18868601.png"
ROBLOX_ICON    = "https://cdn-icons-png.flaticon.com/512/18868/18868601.png"
ROBLOX_URL     = "https://www.roblox.com"
