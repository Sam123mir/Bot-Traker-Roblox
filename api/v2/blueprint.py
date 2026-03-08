# api/v2/blueprint.py
"""
Central Blueprint for BloxPulse API v2.
Defines the v2 prefix and manages the request/response lifecycle.
"""

from __future__ import annotations

import logging
import time
from flask import Blueprint, g, request

from ..config import config
from .response import error_response

logger = logging.getLogger("BloxPulse.API.v2")

# Define the v2 Blueprint
v2_bp = Blueprint("api_v2", __name__, url_prefix=config.API_V2_PREFIX)

@v2_bp.before_request
def _start_v2_timer() -> None:
    """Initialize request-scoped metadata."""
    g.v2_start_time = time.perf_counter()

@v2_bp.after_request
def _log_v2_request(response):
    """Log v2 request performance."""
    duration_ms = round(
        (time.perf_counter() - getattr(g, "v2_start_time", time.perf_counter())) * 1000, 2
    )
    logger.info(
        "[v2] %s %s → %d (%.2fms)",
        request.method,
        request.path,
        response.status_code,
        duration_ms,
    )
    return response

# Error handlers at the Blueprint level
@v2_bp.errorhandler(404)
def handle_v2_not_found(e):
    return error_response("NOT_FOUND", "The requested v2 resource does not exist.", 404)

@v2_bp.errorhandler(405)
def handle_v2_method_not_allowed(e):
    return error_response("METHOD_NOT_ALLOWED", "This HTTP method is not supported for this endpoint.", 405)

# Import sub-modules to register routes on the blueprint
from .routes import platforms, status, versions, stats, widget, health
