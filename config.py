# config.py
"""
BloxPulse · Global Configuration
==================================
Single source of truth for every tuneable value in the project.
All secrets and environment-specific values are read from environment
variables so the file is safe to commit (no plaintext tokens).

Import pattern
--------------
    from config import CHECK_INTERVAL, PLATFORMS, ...

Never mutate these values at runtime — treat them as constants.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from dotenv import load_dotenv

# Load environment variables from .env before defining constants
load_dotenv()

# ──────────────────────────────────────────────────────────────────────────────
#  Paths
# ──────────────────────────────────────────────────────────────────────────────

_BASE: Final[Path] = Path(__file__).resolve().parent

DATA_DIR: Final[Path] = _BASE / "data"
LOGS_DIR: Final[Path] = _BASE / "logs"

# Ensure directories exist at import time so nothing else has to worry about it
DATA_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)

VERSIONS_FILE:      Final[str] = str(DATA_DIR / "versions.json")
GUILDS_FILE:        Final[str] = str(DATA_DIR / "guilds.json")
ANNOUNCEMENTS_FILE: Final[str] = str(DATA_DIR / "announcements.json")
LOG_FILE:           Final[str] = str(LOGS_DIR / "monitor.log")


# ──────────────────────────────────────────────────────────────────────────────
#  Environment helpers
# ──────────────────────────────────────────────────────────────────────────────

def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def _env_int(key: str, default: int) -> int:
    raw = os.environ.get(key)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        print(
            f"[config] WARNING: env var {key!r} = {raw!r} is not a valid integer. "
            f"Using default {default}.",
            file=sys.stderr,
        )
        return default


def _env_list_int(key: str, default: list[int]) -> list[int]:
    raw = os.environ.get(key)
    if not raw:
        return default
    try:
        return [int(x.strip()) for x in raw.split(",") if x.strip()]
    except ValueError:
        return default


# ──────────────────────────────────────────────────────────────────────────────
#  Discord
# ──────────────────────────────────────────────────────────────────────────────

DISCORD_BOT_TOKEN: Final[str] = _env("DISCORD_BOT_TOKEN")
if not DISCORD_BOT_TOKEN:
    print(
        "[config] CRITICAL: DISCORD_BOT_TOKEN is not set. "
        "The bot cannot start without it.",
        file=sys.stderr,
    )

DEVELOPERS: Final[list[int]] = _env_list_int(
    "BLOXPULSE_DEVELOPERS",
    default=[1420085090570207313],
)
OFFICIAL_GUILD_ID: Final[int] = _env_int("BLOXPULSE_GUILD_ID", default=1474129389125107883)
DEFAULT_LANGUAGE:  Final[str] = _env("BLOXPULSE_LANGUAGE", default="en")


# ──────────────────────────────────────────────────────────────────────────────
#  Monitoring intervals
# ──────────────────────────────────────────────────────────────────────────────

CHECK_INTERVAL:      Final[int] = _env_int("CHECK_INTERVAL",   default=60)    # 1 min (Polling)
HEARTBEAT_EVERY:     Final[int] = _env_int("HEARTBEAT_EVERY",  default=3600)  # 1 hour
REQUEST_TIMEOUT:  Final[int] = _env_int("REQUEST_TIMEOUT",  default=10)
RETRY_ATTEMPTS:   Final[int] = _env_int("RETRY_ATTEMPTS",   default=3)
RETRY_DELAY:      Final[int] = _env_int("RETRY_DELAY",      default=5)
HISTORY_DAYS:     Final[int] = _env_int("HISTORY_DAYS",     default=30)
HISTORY_MAX:      Final[int] = _env_int("HISTORY_MAX",      default=50)


# ──────────────────────────────────────────────────────────────────────────────
#  Branding & assets
# ──────────────────────────────────────────────────────────────────────────────

BOT_VERSION: Final[str] = "v1.9.6"
BOT_NAME:    Final[str] = "BloxPulse · Roblox Monitor"

BOT_AVATAR_URL: Final[str] = _env(
    "BLOXPULSE_AVATAR_URL",
    default="https://cdn-icons-png.flaticon.com/512/8157/8157523.png",
)
ROBLOX_ICON:        Final[str] = "https://cdn-icons-png.flaticon.com/512/18868/18868601.png"
ROBLOX_URL:         Final[str] = "https://www.roblox.com"
OFFICIAL_SERVER_URL: Final[str] = _env("BLOXPULSE_SERVER_URL", default="https://discord.gg/7XU8YbDC")
UPDATE_BANNER_URL:  Final[str] = (
    "https://media1.giphy.com/media/v1.Y2lkPTc5MGI3NjExNXpoZTZ4ZXg2NjFra3hqa3BwMHY4Mm5pemY0Mms3eTU4ZzRtNjd0NiZlcD12MV9pbnRlcm5hbF9naWZfYnlfaWQmY3Q9Zw/7qJWn3LsiSe2WoOABJ/giphy.gif"
)


# ──────────────────────────────────────────────────────────────────────────────
#  Platform definitions
# ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PlatformConfig:
    """Typed descriptor for a single monitored platform."""
    label:     str
    color:     int
    icon_url:  str
    source:    str           # "cdn" | "roblox_api" | "appstore" | "playstore"
    api_key:   str = ""
    bundle_id: str = ""

    def as_dict(self) -> dict:
        return {
            "label":     self.label,
            "color":     self.color,
            "icon_url":  self.icon_url,
            "source":    self.source,
            "api_key":   self.api_key,
            "bundle_id": self.bundle_id,
        }


# Keep PLATFORMS as plain dicts so existing code that does cfg["label"] keeps
# working without changes. PlatformConfig is used for documentation / typing.
PLATFORMS: Final[dict[str, dict]] = {
    "WindowsPlayer": {
        "label":    "Windows (PC)",
        "color":    0x0078D4,
        "icon_url": "https://cdn-icons-png.flaticon.com/512/882/882702.png",
        "source":   "roblox_api",
        "api_key":  "WindowsPlayer",
    },
    "WindowsStudio": {
        "label":    "Windows Studio",
        "color":    0x00A2ED,
        "icon_url": "https://cdn-icons-png.flaticon.com/512/18868/18868601.png",
        "source":   "roblox_api",
        "api_key":  "WindowsStudio",
    },
    "MacPlayer": {
        "label":    "macOS Client",
        "color":    0x636366,
        "icon_url": "https://cdn-icons-png.flaticon.com/512/2/2235.png",
        "source":   "roblox_api",
        "api_key":  "MacPlayer",
    },
    "MacStudio": {
        "label":    "macOS Studio",
        "color":    0xA2A2A2,
        "icon_url": "https://cdn-icons-png.flaticon.com/512/2/2235.png",
        "source":   "roblox_api",
        "api_key":  "MacStudio",
    },
    "AndroidApp": {
        "label":    "Android",
        "color":    0x3DDC84,
        "icon_url": "https://cdn-icons-png.flaticon.com/512/270/270780.png",
        "source":   "playstore",
        "api_key":  "AndroidApp",
    },
    "iOS": {
        "label":     "iPhone / iPad",
        "color":     0x1C1C1E,
        "icon_url":  "https://cdn-icons-png.flaticon.com/512/0/747.png",
        "source":    "appstore",
        "bundle_id": "com.roblox.roblox",
    },
}

# Deployment channels to track for each PC/Studio platform
MONITORED_CHANNELS: Final[list[str]] = ["LIVE", "znext", "zintegration"]

# Platforms that use the Deployment API source
PC_STUDIO_PLATFORMS: Final[frozenset[str]] = frozenset({
    "WindowsPlayer", "WindowsStudio", "MacPlayer", "MacStudio"
})

# ──────────────────────────────────────────────────────────────────────────────
#  API platform alias mapping  (short alias → internal key)
# ──────────────────────────────────────────────────────────────────────────────

API_PLATFORM_MAPPING: Final[dict[str, str]] = {
    "windows":    "WindowsPlayer",
    "studio":     "WindowsStudio",
    "mac":        "MacPlayer",
    "mac_studio": "MacStudio",
    "android":    "AndroidApp",
    "ios":        "iOS",
}