# api/middleware.py
"""
Flask middleware (before/after request hooks).

Responsibilities
----------------
1. CORS headers on every response.
2. Structured request / response logging.
3. In-memory sliding-window rate limiter per IP.
4. Optional API-key authentication on protected endpoints.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from threading import Lock
from typing import Callable

from flask import Flask, g, jsonify, request

from .config import config
from .errors import RateLimitError, UnauthorizedError

logger = logging.getLogger("BloxPulse.API")


# ──────────────────────────────────────────────────────────────────────────────
#  Rate limiter  (thread-safe sliding window per IP)
# ──────────────────────────────────────────────────────────────────────────────

class _SlidingWindowRateLimiter:
    """
    Keeps a deque of request timestamps per IP.
    Evicts entries older than `window_seconds` on every check.
    """

    def __init__(self, limit: int, window_seconds: int) -> None:
        self._limit   = limit
        self._window  = window_seconds
        self._buckets: dict[str, deque] = defaultdict(deque)
        self._lock    = Lock()

    def is_allowed(self, key: str) -> tuple[bool, int, int]:
        """
        Returns (allowed, remaining, retry_after_seconds).
        `retry_after` is 0 when the request is allowed.
        """
        now = time.monotonic()
        cutoff = now - self._window

        with self._lock:
            bucket = self._buckets[key]
            # Drop stale entries
            while bucket and bucket[0] < cutoff:
                bucket.popleft()

            if len(bucket) >= self._limit:
                retry_after = int(self._window - (now - bucket[0])) + 1
                return False, 0, retry_after

            bucket.append(now)
            remaining = self._limit - len(bucket)
            return True, remaining, 0


_limiter = _SlidingWindowRateLimiter(config.RATE_LIMIT, config.RATE_WINDOW)

# Endpoints that require a valid API key (exact paths or prefixes)
_PROTECTED_PREFIXES: tuple[str, ...] = (
    f"{config.API_PREFIX}/admin",
)


# ──────────────────────────────────────────────────────────────────────────────
#  Registration
# ──────────────────────────────────────────────────────────────────────────────

def register_middleware(app: Flask) -> None:
    """Attach all middleware to the Flask app."""

    # ── Before request ────────────────────────────────────────────────────────

    @app.before_request
    def _start_timer() -> None:
        g.start_time = time.perf_counter()
        g.request_id = f"{int(time.time() * 1000)}"  # simple ms timestamp ID

    @app.before_request
    def _rate_limit() -> None:
        # Use X-Forwarded-For if behind a proxy, fall back to remote_addr
        ip = (
            request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
            or request.remote_addr
            or "unknown"
        )
        allowed, remaining, retry_after = _limiter.is_allowed(ip)

        if not allowed:
            raise RateLimitError(
                message=(
                    f"Rate limit exceeded. "
                    f"Max {config.RATE_LIMIT} requests per {config.RATE_WINDOW}s. "
                    f"Retry after {retry_after}s."
                ),
                details={"retry_after_seconds": retry_after},
            )

        # Store for headers
        g.rate_remaining = remaining
        g.rate_limit = config.RATE_LIMIT

    @app.before_request
    def _authenticate() -> None:
        """Require API key for protected routes."""
        if not config.API_KEY:
            return  # Auth not configured – skip
        if not any(request.path.startswith(p) for p in _PROTECTED_PREFIXES):
            return  # Public endpoint – skip

        provided = (
            request.headers.get(config.API_KEY_HEADER)
            or request.args.get("api_key")
        )
        if not provided:
            raise UnauthorizedError(
                "Missing API key. "
                f"Provide it via the '{config.API_KEY_HEADER}' header or "
                "'api_key' query parameter."
            )
        if provided != config.API_KEY:
            raise UnauthorizedError("Invalid API key.")

    # ── After request ─────────────────────────────────────────────────────────

    @app.after_request
    def _add_cors(response):
        origins = ", ".join(config.CORS_ORIGINS)
        response.headers["Access-Control-Allow-Origin"]  = origins
        response.headers["Access-Control-Allow-Headers"] = (
            f"Content-Type, Authorization, {config.API_KEY_HEADER}"
        )
        response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
        return response

    @app.after_request
    def _add_rate_limit_headers(response):
        response.headers["X-RateLimit-Limit"]     = getattr(g, "rate_limit", config.RATE_LIMIT)
        response.headers["X-RateLimit-Remaining"] = getattr(g, "rate_remaining", 0)
        response.headers["X-RateLimit-Window"]    = config.RATE_WINDOW
        return response

    @app.after_request
    def _add_standard_headers(response):
        response.headers["X-Request-ID"]    = getattr(g, "request_id", "-")
        response.headers["X-Powered-By"]    = "BloxPulse"
        response.headers["Content-Type"]    = "application/json"
        return response

    @app.after_request
    def _log_request(response):
        duration_ms = round(
            (time.perf_counter() - getattr(g, "start_time", time.perf_counter())) * 1000, 2
        )
        logger.info(
            "[%s] %s %s → %d  (%.2fms)",
            getattr(g, "request_id", "-"),
            request.method,
            request.path,
            response.status_code,
            duration_ms,
        )
        return response