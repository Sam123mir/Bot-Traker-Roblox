# api/v2/routes/status.py
"""
GET /api/v2/status
Returns current live version and API health for all platforms.
"""

from __future__ import annotations

import logging
from flask import request

from core.storage import get_version_data
from systems.monitoring import API_STATUS

from ..blueprint import v2_bp
from ..design import PLATFORM_META
from ..response import envelope, error_response

logger = logging.getLogger("BloxPulse.API.v2.Status")

@v2_bp.get("/status")
def get_status():
    """Returns current live version and API health for all platforms."""
    platform_filter = request.args.get("platform", "").strip()
    
    # Validation
    if platform_filter and platform_filter not in PLATFORM_META:
        return error_response(
            "PLATFORM_NOT_FOUND",
            f"Platform '{platform_filter}' is not recognized.",
            404
        )

    results = {}
    platforms_to_check = [platform_filter] if platform_filter else PLATFORM_META.keys()
    
    platforms_online = 0
    total_checked = 0

    for key in platforms_to_check:
        try:
            state = get_version_data(key) or {}
            is_online = bool(API_STATUS.get(key, True))
            
            # Simple latency tier logic (actual latency would come from monitoring stats)
            # For now, we'll mark as 'fast' if online, 'offline' otherwise
            # or we could peek into the monitoring module's global LATENCY dict if it was accessible
            
            results[key] = {
                "online":       is_online,
                "version":      state.get("current", "unknown"),
                "version_hash": state.get("last_update", "unknown"),
                "channel":      "LIVE", # Default for now
                "last_updated": state.get("timestamps", {}).get(state.get("current")) or None,
                "fflag_count":  state.get("fflag_count", 0), # if tracked
            }
            
            if is_online:
                platforms_online += 1
            total_checked += 1
            
        except Exception:
            logger.exception("Error fetching status for %s", key)
            results[key] = {"error": "data unavailable"}

    # Overall health calculation
    health = "healthy"
    if platforms_online == 0:
        health = "outage"
    elif platforms_online < total_checked:
        health = "degraded"

    return envelope({
        "platforms":      results,
        "overall_health": health,
        "degraded_platforms": [k for k, v in results.items() if not v.get("online", True)]
    })
