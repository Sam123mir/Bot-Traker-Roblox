# api/v2/routes/widget.py
"""
GET /api/v2/widget
Returns highly structured data for website status widgets and embeds.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from flask import request

from core.storage import get_version_data
from systems.monitoring import API_STATUS

from ..blueprint import v2_bp
from ..design import PLATFORM_META
from ..response import envelope

logger = logging.getLogger("BloxPulse.API.v2.Widget")

@v2_bp.get("/widget")
def get_widget():
    """Returns rich data for website status widgets."""
    platforms_raw = request.args.get("platforms", "")
    platforms_to_check = [p.strip() for p in platforms_raw.split(",") if p.strip()] if platforms_raw else PLATFORM_META.keys()
    
    cards = []
    for key in platforms_to_check:
        if key not in PLATFORM_META:
            continue
            
        meta = PLATFORM_META[key]
        state = get_version_data(key) or {}
        is_online = bool(API_STATUS.get(key, True))
        
        # Build widget card for this platform
        cards.append({
            "platform_key":    key,
            "platform_label":  meta["label"],
            "platform_emoji":  meta["emoji"],
            "platform_color":  meta["color"],
            "platform_icon":   meta["icon_url"],
            "status_emoji":    "🟢" if is_online else "🔴",
            "status_label":    "Online" if is_online else "Offline",
            "version":         state.get("current", "unknown"),
            "version_hash":    state.get("last_update", "unknown"),
            "version_short":   state.get("last_update", "unknown")[-12:] if state.get("last_update") else "unknown",
            "channel":         "LIVE",
            "last_updated":    state.get("timestamps", {}).get(state.get("current")) or None,
        })

    return envelope({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "cards":        cards
    })
