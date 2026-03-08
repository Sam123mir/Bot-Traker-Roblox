# api/v2/routes/stats.py
"""
GET /api/v2/stats
Bot-wide metrics and system health summary.
Requires API Key.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from flask import current_app

from core.storage import get_all_guilds
from systems.monitoring import CHECK_INTERVAL

from ..blueprint import v2_bp
from ..auth import is_authorized
from ..response import envelope, error_response

logger = logging.getLogger("BloxPulse.API.v2.Stats")

@v2_bp.get("/stats")
def get_stats():
    """Returns bot-wide metrics. Protected by API key."""
    if not is_authorized():
        return error_response("UNAUTHORIZED", "A valid API key is required to access stats.", 401)

    bot = current_app.config.get("BOT")
    guilds = get_all_guilds() or []

    # Bot metadata
    stats = {
        "bot": {
            "version":        "2.0.0", # Bot version constant
            "guild_count":    len(guilds),
            "latency_ms":     round(bot.latency * 1000, 2) if bot else None,
        },
        "monitoring": {
            "check_interval_seconds": CHECK_INTERVAL,
            "generated_at":           datetime.now(timezone.utc).isoformat(),
        }
    }

    return envelope(stats)
