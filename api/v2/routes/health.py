# api/v2/routes/health.py
"""
GET /api/v2/health
GET /api/v2/ready
Standard health and readiness probes for container orchestration.
"""

from __future__ import annotations

from flask import current_app
from core.storage import get_all_guilds
from ..blueprint import v2_bp
from ..response import envelope

@v2_bp.get("/health")
def get_health():
    """Liveness probe. Returns 200 if the API is running."""
    return envelope({"status": "live"})

@v2_bp.get("/ready")
def get_ready():
    """Readiness probe. Returns 200 if storage/bot are accessible."""
    checks = {
        "storage": "pass",
        "bot":     "pass"
    }
    
    # Simple checks
    try:
        get_all_guilds()
    except Exception:
        checks["storage"] = "fail"
        
    bot = current_app.config.get("BOT")
    if not bot:
        checks["bot"] = "fail"
        
    status = 200 if all(v == "pass" for v in checks.values()) else 503
    return envelope({"status": "ready" if status == 200 else "unready", "checks": checks}, status=status)
