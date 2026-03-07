# api/errors.py
"""
Standardised error handling for the BloxPulse API.

Every error leaves the server with a consistent JSON envelope:

{
    "success": false,
    "error": {
        "code":    "NOT_FOUND",
        "message": "The requested resource could not be found.",
        "details": null          // optional extra context
    },
    "meta": {
        "timestamp": "...",
        "path":      "/api/v1/..."
    }
}
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from flask import Flask, jsonify, request
from werkzeug.exceptions import HTTPException

logger = logging.getLogger("BloxPulse.API")


# ──────────────────────────────────────────────────────────────────────────────
#  Custom exception hierarchy
# ──────────────────────────────────────────────────────────────────────────────

class APIError(Exception):
    """Base class for all intentional API errors."""

    status_code: int = 500
    error_code:  str = "INTERNAL_ERROR"

    def __init__(
        self,
        message: str = "An unexpected error occurred.",
        details: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = details

    def to_dict(self) -> dict:
        return {
            "success": False,
            "error": {
                "code":    self.error_code,
                "message": self.message,
                "details": self.details,
            },
            "meta": {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "path":      request.path,
            },
        }


class BadRequestError(APIError):
    status_code = 400
    error_code  = "BAD_REQUEST"

class UnauthorizedError(APIError):
    status_code = 401
    error_code  = "UNAUTHORIZED"

class ForbiddenError(APIError):
    status_code = 403
    error_code  = "FORBIDDEN"

class NotFoundError(APIError):
    status_code = 404
    error_code  = "NOT_FOUND"

class RateLimitError(APIError):
    status_code = 429
    error_code  = "RATE_LIMIT_EXCEEDED"

class ServiceUnavailableError(APIError):
    status_code = 503
    error_code  = "SERVICE_UNAVAILABLE"


# ──────────────────────────────────────────────────────────────────────────────
#  Registration helper
# ──────────────────────────────────────────────────────────────────────────────

def register_error_handlers(app: Flask) -> None:
    """Attach all error handlers to a Flask app instance."""

    @app.errorhandler(APIError)
    def handle_api_error(exc: APIError):
        logger.warning(
            "API error [%s] %s – %s",
            exc.status_code,
            exc.error_code,
            exc.message,
        )
        return jsonify(exc.to_dict()), exc.status_code

    @app.errorhandler(HTTPException)
    def handle_http_exception(exc: HTTPException):
        """Catch werkzeug / Flask HTTP errors (404, 405 …)."""
        payload = {
            "success": False,
            "error": {
                "code":    exc.name.upper().replace(" ", "_"),
                "message": exc.description,
                "details": None,
            },
            "meta": {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "path":      request.path,
            },
        }
        return jsonify(payload), exc.code

    @app.errorhandler(Exception)
    def handle_unexpected_error(exc: Exception):
        """Last-resort handler – never expose internal tracebacks."""
        logger.exception("Unhandled exception on %s", request.path)
        payload = {
            "success": False,
            "error": {
                "code":    "INTERNAL_SERVER_ERROR",
                "message": "An internal server error occurred.",
                "details": None,
            },
            "meta": {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "path":      request.path,
            },
        }
        return jsonify(payload), 500