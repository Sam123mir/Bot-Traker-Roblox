# api/config.py
"""
Centralised configuration for the BloxPulse REST API.
All tuneable values live here; override via environment variables.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


@dataclass(frozen=True)
class APIConfig:
    # ── Server ────────────────────────────────────────────────────────────────
    HOST: str                   = "0.0.0.0"
    PORT: int                   = int(os.getenv("PORT", 8080))
    DEBUG: bool                 = os.getenv("API_DEBUG", "false").lower() == "true"
    WORKERS: int                = int(os.getenv("API_WORKERS", 1))

    # ── Auth ──────────────────────────────────────────────────────────────────
    API_KEY: str                = os.getenv("BLOXPULSE_API_KEY", "")
    API_KEY_HEADER: str         = "X-API-Key"

    # ── Rate limiting  (requests / window_seconds per IP) ─────────────────────
    RATE_LIMIT: int             = int(os.getenv("API_RATE_LIMIT", 60))
    RATE_WINDOW: int            = int(os.getenv("API_RATE_WINDOW", 60))   # seconds

    # ── Pagination ────────────────────────────────────────────────────────────
    MAX_HISTORY_LIMIT: int      = 100
    DEFAULT_HISTORY_LIMIT: int  = 10

    # ── CORS ──────────────────────────────────────────────────────────────────
    CORS_ORIGINS: list[str]     = field(default_factory=lambda: ["*"])

    # ── Misc ──────────────────────────────────────────────────────────────────
    API_VERSION: str            = "v2.0.0"
    API_V1_PREFIX: str          = "/api/v1"
    API_V2_PREFIX: str          = "/api/v2"

    # Deprecated v1 prefix (for compatibility in some places)
    API_PREFIX: str             = "/api/v1"


# Singleton – import this everywhere
config = APIConfig()


# Platform key mapping  (short alias → internal storage key)
PLATFORM_MAP: dict[str, str] = {
    "win":     "WindowsPlayer",
    "mac":     "MacPlayer",
    "android": "AndroidApp",
    "ios":     "iOS",
}