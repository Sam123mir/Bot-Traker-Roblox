# api/app.py
"""
Flask application factory + server launcher.

Usage
-----
# From your main bot entrypoint:
from api import start_api
start_api()

# Or for testing / manual:
from api.app import create_app
app = create_app()
app.run(...)
"""
from __future__ import annotations

import logging
import os
import threading

from flask import Flask

from .config import config
from .errors import register_error_handlers
from .logging_setup import setup_api_logging
from .middleware import register_middleware
from .v1_routes import admin_bp, health_bp, history_bp, stats_bp, status_bp, widget_bp
from .v2 import v2_bp

logger = logging.getLogger("BloxPulse.API")


# ──────────────────────────────────────────────────────────────────────────────
#  App factory
# ──────────────────────────────────────────────────────────────────────────────

def create_app(bot: Any = None) -> Flask:
    """
    Build and configure the Flask application.

    Returns a fully-wired Flask instance ready to be served.
    """
    setup_api_logging()

    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"]     = False   # preserve insertion order
    app.config["PROPAGATE_EXCEPTIONS"] = False  # let our handlers catch everything
    app.config["BOT"]                = bot     # Store Discord bot instance

    # Register components in order: errors → middleware → routes
    register_error_handlers(app)
    register_middleware(app)

    app.register_blueprint(health_bp)
    app.register_blueprint(status_bp)
    app.register_blueprint(stats_bp)
    app.register_blueprint(history_bp)
    app.register_blueprint(widget_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(v2_bp)

    logger.info(
        "BloxPulse API ready  |  prefix=%s  rate=%d req/%ds  auth=%s",
        config.API_PREFIX,
        config.RATE_LIMIT,
        config.RATE_WINDOW,
        "on" if config.API_KEY else "off",
    )
    return app


# ──────────────────────────────────────────────────────────────────────────────
#  Server runner
# ──────────────────────────────────────────────────────────────────────────────

_server_thread: threading.Thread | None = None


def _run_server(app: Flask) -> None:
    """Target function for the background thread."""
    logger.info("Starting Flask server on %s:%d", config.HOST, config.PORT)
    app.run(
        host=config.HOST,
        port=config.PORT,
        debug=False,       # never True in a thread – causes reloader issues
        use_reloader=False,
        threaded=True,     # handle concurrent requests
    )


def start_api(bot: Any = None) -> None:
    """
    Create the app and launch it in a daemon background thread.
    Safe to call multiple times – subsequent calls are no-ops.
    """
    global _server_thread

    if _server_thread and _server_thread.is_alive():
        logger.debug("API server already running – skipping start.")
        return

    app = create_app(bot=bot)

    _server_thread = threading.Thread(
        target=_run_server,
        args=(app,),
        name="BloxPulse-API",
        daemon=True,  # dies automatically when the bot process exits
    )
    _server_thread.start()
    logger.info(
        "API server started in background thread (port %d)",
        config.PORT,
    )
