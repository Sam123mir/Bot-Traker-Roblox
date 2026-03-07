# api/response.py
"""
Uniform response builders.

Every successful response follows this envelope:

{
    "success": true,
    "data": { ... },       // or a list
    "meta": {
        "timestamp":  "2025-01-01T00:00:00+00:00",
        "api_version": "v1",
        "count":       10,   // only for list responses
        "limit":       10,   // only for paginated responses
        "total":       100   // only for paginated responses
    }
}
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from flask import jsonify

from .config import config


def _base_meta(extra: dict | None = None) -> dict:
    meta = {
        "timestamp":   datetime.now(timezone.utc).isoformat(),
        "api_version": config.API_VERSION,
    }
    if extra:
        meta.update(extra)
    return meta


def success(data: Any, status: int = 200, meta_extra: dict | None = None):
    """Single-object success response."""
    payload = {
        "success": True,
        "data":    data,
        "meta":    _base_meta(meta_extra),
    }
    return jsonify(payload), status


def success_list(
    items: list,
    *,
    total: int | None = None,
    limit: int | None = None,
    status: int = 200,
    meta_extra: dict | None = None,
):
    """List / paginated success response."""
    extra = {"count": len(items)}
    if total is not None:
        extra["total"] = total
    if limit is not None:
        extra["limit"] = limit
    if meta_extra:
        extra.update(meta_extra)

    payload = {
        "success": True,
        "data":    items,
        "meta":    _base_meta(extra),
    }
    return jsonify(payload), status