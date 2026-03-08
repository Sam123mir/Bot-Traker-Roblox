# api/v2/auth.py
"""
API key authentication logic for BloxPulse API v2.
Supports key-based access for protected endpoints.
"""

from __future__ import annotations

import logging
from flask import request

from ..config import config

logger = logging.getLogger("BloxPulse.API.v2.Auth")

def is_authorized() -> bool:
    """
    Checks if the current request is authorized via API key.
    
    Returns True if:
    1. Authorization is not configured (API_KEY is empty).
    2. A valid key is provided in the header or query string.
    """
    if not config.API_KEY:
        return True  # Auth not enforced

    provided = (
        request.headers.get(config.API_KEY_HEADER)
        or request.args.get("api_key")
    )
    
    if not provided:
        return False
        
    return provided == config.API_KEY
