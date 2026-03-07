# api/logging_setup.py
"""
Configures a clean, structured logger for the BloxPulse API.
Call `setup_api_logging()` once before creating the Flask app.
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone


class _UTCFormatter(logging.Formatter):
    """Formats log records with a UTC ISO-8601 timestamp."""

    converter = datetime.utcfromtimestamp  # type: ignore[assignment]

    def formatTime(self, record, datefmt=None):  # noqa: N802
        dt = datetime.fromtimestamp(record.created, tz=timezone.utc)
        return dt.strftime(datefmt or "%Y-%m-%dT%H:%M:%S+00:00")


_FORMAT = "%(asctime)s [%(levelname)-8s] %(name)s – %(message)s"


def setup_api_logging(level: int = logging.INFO) -> None:
    """Set up console logging for all BloxPulse.API loggers."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_UTCFormatter(_FORMAT))

    root_logger = logging.getLogger("BloxPulse.API")
    if not root_logger.handlers:
        root_logger.setLevel(level)
        root_logger.addHandler(handler)
        root_logger.propagate = False

    # Silence noisy werkzeug access logs (we log ourselves in middleware)
    logging.getLogger("werkzeug").setLevel(logging.WARNING)