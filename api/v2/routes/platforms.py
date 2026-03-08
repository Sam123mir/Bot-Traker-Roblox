# api/v2/routes/platforms.py
"""
GET /api/v2/platforms
Returns metadata for all supported platforms.
"""

from __future__ import annotations

from ..blueprint import v2_bp
from ..design import PLATFORM_META
from ..response import envelope

@v2_bp.get("/platforms")
def get_platforms():
    """Returns the full design-system metadata for all supported platforms."""
    platforms = []
    groups = set()
    
    for key, meta in PLATFORM_META.items():
        platforms.append({
            "key":      key,
            "label":    meta["label"],
            "emoji":    meta["emoji"],
            "color":    meta["color"],
            "icon_url": meta["icon_url"],
            "group":    meta["group"],
        })
        groups.add(meta["group"])
        
    return envelope({
        "platforms": platforms,
        "groups":    sorted(list(groups)),
        "total":     len(platforms),
    })
