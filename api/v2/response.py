# api/v2/response.py
"""
Standardized response wrappers for BloxPulse API v2.
Guarantees every response follows the same JSON envelope.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from flask import jsonify

API_VERSION = "2.0.0"


def envelope(data: Any, *, meta: dict | None = None, status: int = 200):
    """
    Wraps data in the standard BloxPulse v2 JSON envelope.
    
    :param data: The primary payload (dict or list).
    :param meta: Optional additional metadata to include.
    :param status: HTTP status code (default 200).
    """
    body = {
        "ok":          True,
        "api_version": API_VERSION,
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "data":        data,
        "meta":        {
            "request_id": f"req_{uuid.uuid4().hex[:8]}",
            **(meta or {}),
        },
    }
    return jsonify(body), status


def error_response(code: str, message: str, status: int = 400, details: dict | None = None):
    """
    Returns a standardized error response.
    
    :param code: Machine-readable error code (e.g. 'PLATFORM_NOT_FOUND').
    :param message: Human-readable explanation.
    :param status: HTTP status code.
    :param details: Optional additional error context.
    """
    body = {
        "ok":          False,
        "api_version": API_VERSION,
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "error": {
            "code":    code,
            "message": message,
            "details": details or {},
            "docs":    f"https://bloxpulse.dev/docs/api/v2/errors#{code}",
        },
    }
    return jsonify(body), status
