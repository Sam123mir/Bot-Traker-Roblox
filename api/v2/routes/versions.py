# api/v2/routes/versions.py
"""
GET /api/v2/versions
Paginated version history with optional platform filtering.
"""

from __future__ import annotations

import logging
from flask import request

from core.storage import get_announcements
from ..blueprint import v2_bp
from ..design import PLATFORM_META
from ..response import envelope, error_response

logger = logging.getLogger("BloxPulse.API.v2.Versions")

@v2_bp.get("/versions")
def get_versions():
    """Returns paginated version history with platform filtering."""
    platform_filter = request.args.get("platform", "").strip()
    
    # Validation
    if platform_filter and platform_filter not in PLATFORM_META:
        return error_response(
            "PLATFORM_NOT_FOUND",
            f"Platform '{platform_filter}' is not recognized.",
            404
        )

    # Fetch data
    try:
        all_updates: list = get_announcements() or []
    except Exception:
        logger.exception("Error fetching announcements")
        all_updates = []

    # Optional filtering
    if platform_filter:
        all_updates = [
            u for u in all_updates
            if str(u.get("platform", "")).lower() in (platform_filter.lower(), PLATFORM_META.get(platform_filter, {}).get("label", "").lower())
        ]

    # Pagination
    try:
        limit  = int(request.args.get("limit", 20))
        offset = int(request.args.get("offset", 0))
    except (ValueError, TypeError):
        return error_response("INVALID_PARAM", "Limit and offset must be integers.", 400)

    # Clamping
    limit  = max(1, min(limit, 100))
    offset = max(0, offset)

    total = len(all_updates)
    page  = all_updates[offset : offset + limit]

    # Map to v2 version objects
    versions = []
    for u in page:
        key = u.get("platform", "unknown")
        meta = PLATFORM_META.get(key, {})
        
        versions.append({
            "platform_key":   key,
            "platform_label": meta.get("label", key),
            "version":        u.get("version", "unknown"),
            "version_hash":   u.get("hash", "unknown"),
            "channel":        "LIVE",
            "detected_at":    u.get("timestamp"),
            "diff_url":       u.get("diff_url"),
        })

    return envelope({
        "versions": versions,
        "pagination": {
            "total":       total,
            "limit":       limit,
            "offset":      offset,
            "has_more":    total > (offset + limit),
            "next_offset": offset + limit if total > (offset + limit) else None
        }
    })
