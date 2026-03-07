# api/routes.py
"""
All BloxPulse API route blueprints.

Blueprints
----------
health_bp   – GET /           health check & index
status_bp   – GET /api/v1/status[/<platform>]
stats_bp    – GET /api/v1/stats
history_bp  – GET /api/v1/history
admin_bp    – GET /api/v1/admin/*   (protected)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from flask import Blueprint, request

# ── Project imports (adjust paths as needed) ──────────────────────────────────
from config import BOT_VERSION, OFFICIAL_GUILD_ID, OFFICIAL_SERVER_URL
from core.storage import get_all_guilds, get_announcements, get_version_data
from systems.monitoring import API_STATUS

from .config import PLATFORM_MAP, config
from .errors import BadRequestError, NotFoundError, ServiceUnavailableError
from .response import success, success_list

logger = logging.getLogger("BloxPulse.API")


# ──────────────────────────────────────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _get_bot():
    """Access the Discord bot instance from Flask current_app."""
    from flask import current_app
    return current_app.config.get("BOT")


def _serialize_platform(key: str, state: dict) -> dict:
# ... (rest of helper functions)
    return {
        "platform":      key,
        "version":       state.get("current") or "unknown",
        "hash":          state.get("last_update") or "unknown",
        "last_build":    state.get("last_build") or None,
        "online":        bool(API_STATUS.get(key, True)),
        "updated_at":    state.get("timestamps", {}).get(state.get("current")) or None,
        "history_count": len(state.get("history", [])),
    }


def _clamp_limit(raw: Any, default: int, maximum: int) -> int:
    """Parse and clamp a ?limit= query parameter."""
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = default
    return max(1, min(value, maximum))


# ──────────────────────────────────────────────────────────────────────────────
#  Health / root  ──  GET /
# ──────────────────────────────────────────────────────────────────────────────

health_bp = Blueprint("health", __name__)


@health_bp.get("/")
def index():
    """Root health check – also doubles as a quick API directory."""
    return success({
        "service":     "BloxPulse API",
        "version":     BOT_VERSION,
        "status":      "healthy",
        "uptime":      "see /api/v1/stats",
        "docs":        "https://docs.bloxpulse.dev",   # update to real docs
        "endpoints": {
            "health":  "GET /",
            "status":  f"GET {config.API_PREFIX}/status",
            "status_platform": f"GET {config.API_PREFIX}/status/<platform>",
            "stats":   f"GET {config.API_PREFIX}/stats",
            "history": f"GET {config.API_PREFIX}/history",
            "widget":  f"GET {config.API_PREFIX}/widget",
            "admin":   f"GET {config.API_PREFIX}/admin/info  (requires API key)",
        },
        "platforms": list(PLATFORM_MAP.keys()),
    })


@health_bp.get("/healthz")
def healthz():
    """Kubernetes / uptime-monitor liveness probe."""
    return success({"alive": True})


# ──────────────────────────────────────────────────────────────────────────────
#  /api/v1/status[/<platform>]
# ──────────────────────────────────────────────────────────────────────────────

status_bp = Blueprint("status", __name__, url_prefix=config.API_PREFIX)


@status_bp.get("/status")
def all_status():
    """
    Returns real-time status for **all** monitored platforms.

    Response body:
        data: { "WindowsPlayer": {...}, "MacPlayer": {...}, ... }
    """
    result: dict[str, dict] = {}
    for _alias, platform_key in PLATFORM_MAP.items():
        try:
            state = get_version_data(platform_key) or {}
            result[platform_key] = _serialize_platform(platform_key, state)
        except Exception:
            logger.exception("Error fetching data for platform %s", platform_key)
            result[platform_key] = {
                "platform": platform_key,
                "error":    "data unavailable",
            }
    return success(result)


@status_bp.get("/status/<string:platform>")
def single_status(platform: str):
    """
    Returns status for **one** platform.

    :param platform: alias (win | mac | android | ios)
                     OR the full internal key (WindowsPlayer …)
    """
    # Accept both short alias and full key
    platform_key = (
        PLATFORM_MAP.get(platform.lower())
        or (platform if platform in PLATFORM_MAP.values() else None)
    )
    if not platform_key:
        raise NotFoundError(
            f"Platform '{platform}' not found. "
            f"Valid options: {', '.join(PLATFORM_MAP.keys())}."
        )

    try:
        state = get_version_data(platform_key) or {}
    except Exception:
        logger.exception("Error fetching data for platform %s", platform_key)
        raise

    return success(_serialize_platform(platform_key, state))


# ──────────────────────────────────────────────────────────────────────────────
#  /api/v1/stats
# ──────────────────────────────────────────────────────────────────────────────

stats_bp = Blueprint("stats", __name__, url_prefix=config.API_PREFIX)


@stats_bp.get("/stats")
def stats():
    """Returns global bot / service statistics."""
    guilds = get_all_guilds() or []

    total_versions = 0
    for platform_key in PLATFORM_MAP.values():
        try:
            data = get_version_data(platform_key) or {}
            total_versions += len(data.get("history", []))
        except Exception:
            pass

    platforms_online = sum(
        1 for key in PLATFORM_MAP.values() if API_STATUS.get(key, True)
    )
    platforms_total  = len(PLATFORM_MAP)

    return success({
        "bot_version":           BOT_VERSION,
        "server_count":          len(guilds),
        "platforms_monitored":   platforms_total,
        "platforms_online":      platforms_online,
        "platforms_degraded":    platforms_total - platforms_online,
        "total_tracked_versions": total_versions,
        "overall_status":        "operational" if platforms_online == platforms_total else "degraded",
        "generated_at":          datetime.now(timezone.utc).isoformat(),
    })


# ──────────────────────────────────────────────────────────────────────────────
#  /api/v1/history
# ──────────────────────────────────────────────────────────────────────────────

history_bp = Blueprint("history", __name__, url_prefix=config.API_PREFIX)


@history_bp.get("/history")
def history():
    """
    Returns recent announcements / version update events.

    Query params:
        limit   – max items to return  (default 10, max 100)
        platform – filter by platform alias or key (optional)
    """
    raw_limit = request.args.get("limit", config.DEFAULT_HISTORY_LIMIT)
    limit     = _clamp_limit(raw_limit, config.DEFAULT_HISTORY_LIMIT, config.MAX_HISTORY_LIMIT)
    platform_filter = request.args.get("platform", "").strip().lower()

    if platform_filter and platform_filter not in PLATFORM_MAP:
        # Also allow full key names
        reverse = {v.lower(): v for v in PLATFORM_MAP.values()}
        if platform_filter not in reverse:
            raise BadRequestError(
                f"Unknown platform filter '{platform_filter}'. "
                f"Valid values: {', '.join(PLATFORM_MAP.keys())}."
            )

    try:
        all_updates: list = get_announcements() or []
    except Exception:
        logger.exception("Error fetching announcements")
        all_updates = []

    if platform_filter:
        resolved = PLATFORM_MAP.get(platform_filter, platform_filter)
        all_updates = [
            u for u in all_updates
            if str(u.get("platform", "")).lower() in (platform_filter, resolved.lower())
        ]

    total = len(all_updates)
    page  = all_updates[:limit]

    return success_list(
        page,
        total=total,
        limit=limit,
        meta_extra={
            "platform_filter": platform_filter or None,
            "has_more":        total > limit,
        },
    )


# ──────────────────────────────────────────────────────────────────────────────
#  /api/v1/widget
# ──────────────────────────────────────────────────────────────────────────────

widget_bp = Blueprint("widget", __name__, url_prefix=config.API_PREFIX)


@widget_bp.get("/widget")
def widget():
    """
    Returns information about the official Discord server to use as a widget.
    
    Response body:
        data: { "name", "icon_url", "member_count", "presence_count", "invite_url" }
    """
    bot = _get_bot()
    if not bot:
        raise ServiceUnavailableError("Discord bot instance not available.")
        
    guild = bot.get_guild(OFFICIAL_GUILD_ID)
    if not guild:
        # Fallback if bot is not in the official guild yet or ID is wrong
        return success({
            "name":         "BloxPulse Community",
            "icon_url":     "https://cdn-icons-png.flaticon.com/512/8157/8157523.png",
            "member_count": 0,
            "presence_count": 0,
            "invite_url":   OFFICIAL_SERVER_URL,
            "status":       "offline"
        })

    return success({
        "name":           guild.name,
        "icon_url":       guild.icon.url if guild.icon else None,
        "member_count":   guild.member_count,
        "presence_count": len([m for m in guild.members if m.status != discord.Status.offline]),
        "invite_url":     OFFICIAL_SERVER_URL,
        "status":         "online"
    })


# ──────────────────────────────────────────────────────────────────────────────
#  /api/v1/admin/*  (API-key protected)
# ──────────────────────────────────────────────────────────────────────────────

admin_bp = Blueprint("admin", __name__, url_prefix=f"{config.API_PREFIX}/admin")


@admin_bp.get("/info")
def admin_info():
    """Returns detailed internal diagnostics. Requires API key."""
    guilds = get_all_guilds() or []

    platform_detail = {}
    for alias, key in PLATFORM_MAP.items():
        try:
            state = get_version_data(key) or {}
            platform_detail[alias] = {
                "key":           key,
                "current":       state.get("current"),
                "history_count": len(state.get("history", [])),
                "online":        API_STATUS.get(key, True),
            }
        except Exception as exc:
            platform_detail[alias] = {"error": str(exc)}

    return success({
        "bot_version":    BOT_VERSION,
        "guild_count":    len(guilds),
        "platform_detail": platform_detail,
        "rate_limit_cfg": {
            "limit":  config.RATE_LIMIT,
            "window": config.RATE_WINDOW,
        },
    })
