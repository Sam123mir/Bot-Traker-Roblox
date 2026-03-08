# bot.py
"""
BloxPulse · Bot Entry Point
=============================
Initialises the Discord client, dynamically loads every Cog from
``commands/`` and ``systems/``, wires up global slash-command error
handling, launches the REST API, and connects to Discord.

Design notes
------------
- ``BloxPulseBot`` overrides ``setup_hook`` for all async initialisation
  so nothing async runs at module import time.
- Extensions are loaded in dependency order: systems first, then commands.
- A single ``on_app_command_error`` handler converts all slash-command
  errors into branded embed responses.
- Logging is configured once in ``_configure_logging()`` before the bot
  object is created.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands

from config import BOT_AVATAR_URL, BOT_VERSION, DISCORD_BOT_TOKEN, LOG_FILE
from core.notifier import premium_response
from api import start_api

# ──────────────────────────────────────────────────────────────────────────────
#  Logging
# ──────────────────────────────────────────────────────────────────────────────

def _configure_logging() -> None:
    """
    Set up structured logging to both stdout and a rotating log file.
    Called once before anything else.
    """
    Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)

    fmt     = "%(asctime)s [%(levelname)-8s] %(name)s – %(message)s"
    datefmt = "%Y-%m-%dT%H:%M:%S"

    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
    ]
    for h in handlers:
        h.setFormatter(logging.Formatter(fmt, datefmt))

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in handlers:
        root.addHandler(h)

    # Suppress noisy third-party loggers
    for noisy in ("discord.gateway", "discord.http", "werkzeug"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


_configure_logging()
log = logging.getLogger("BloxPulse.Core")


# ──────────────────────────────────────────────────────────────────────────────
#  Extension discovery
# ──────────────────────────────────────────────────────────────────────────────

_BASE = Path(__file__).resolve().parent

def _discover_extensions(directory: str) -> list[str]:
    """
    Return dotted module paths for every non-dunder .py file in ``directory``.
    e.g.  "systems/monitoring.py"  →  "systems.monitoring"
    """
    folder = _BASE / directory
    if not folder.is_dir():
        log.warning("Extension directory not found: %s", folder)
        return []
    return [
        f"{directory}.{f.stem}"
        for f in sorted(folder.glob("*.py"))
        if not f.name.startswith("__")
    ]


# ──────────────────────────────────────────────────────────────────────────────
#  Bot class
# ──────────────────────────────────────────────────────────────────────────────

class BloxPulseBot(commands.Bot):
    """
    Custom Bot subclass.

    Extra attributes
    ----------------
    start_time      : Unix timestamp of when the bot process started.
    welcome_lock    : asyncio.Lock used by WelcomeSystem to de-duplicate
                      on_guild_join events.
    welcomed_guilds : Set of guild IDs that have already received a welcome.
    """

    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members          = True

        super().__init__(
            command_prefix=commands.when_mentioned,   # no text prefix needed
            intents=intents,
            help_command=None,
            # Reduce memory usage by not storing every message
            max_messages=None,
        )

        self.start_time:      float           = datetime.now(timezone.utc).timestamp()
        self.welcome_lock:    asyncio.Lock    = asyncio.Lock()
        self.welcomed_guilds: set[int]        = set()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def setup_hook(self) -> None:
        """
        Called once by discord.py after login, before connecting to the gateway.
        All async setup (extension loading, tree sync) happens here.
        """
        log.info("Loading extensions…")

        # Load in order: systems → commands  (systems may define things commands depend on)
        for directory in ("systems", "commands"):
            for ext in _discover_extensions(directory):
                await self._load_ext(ext)

        log.info("Syncing application command tree…")
        try:
            synced = await self.tree.sync()
            log.info("Synced %d global command(s).", len(synced))
        except discord.HTTPException as exc:
            log.error("Failed to sync command tree: %s", exc)

    async def _load_ext(self, ext: str) -> None:
        """Load a single extension with structured error logging."""
        try:
            await self.load_extension(ext)
            log.info("  ✔ %s", ext)
        except commands.ExtensionAlreadyLoaded:
            log.debug("  ↷ already loaded: %s", ext)
        except commands.NoEntryPointError:
            log.error("  ✘ %s – missing setup() function", ext)
        except Exception:
            log.exception("  ✘ %s – unexpected error", ext)

    async def on_ready(self) -> None:
        log.info(
            "BloxPulse online — %s (ID: %s)  |  v%s  |  %d guild(s)",
            self.user, self.user.id, BOT_VERSION, len(self.guilds),
        )
        await self._set_presence()

    async def on_resumed(self) -> None:
        log.info("Gateway connection resumed.")
        await self._set_presence()

    async def on_error(self, event: str, *args, **kwargs) -> None:
        log.exception("Unhandled error in event '%s'", event)

    async def _set_presence(self) -> None:
        await self.change_presence(
            status=discord.Status.online,
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name=f"Roblox Deployments · {BOT_VERSION}",
            ),
        )

    # ── Guild tracking ────────────────────────────────────────────────────────

    async def on_guild_join(self, guild: discord.Guild) -> None:
        log.info("Joined guild: %s (ID: %s, members: %d)", guild.name, guild.id, guild.member_count)

    async def on_guild_remove(self, guild: discord.Guild) -> None:
        log.info("Removed from guild: %s (ID: %s)", guild.name, guild.id)
        # Clean up stored config for this guild
        try:
            from core.storage import remove_guild
            remove_guild(guild.id)
        except Exception as exc:
            log.warning("Could not remove guild config for %s: %s", guild.id, exc)


# ──────────────────────────────────────────────────────────────────────────────
#  Global slash-command error handler
# ──────────────────────────────────────────────────────────────────────────────

def _register_error_handler(bot: BloxPulseBot) -> None:
    @bot.tree.error
    async def on_app_command_error(
        interaction: discord.Interaction,
        error:       app_commands.AppCommandError,
    ) -> None:
        avatar_url = bot.user.display_avatar.url if bot.user else BOT_AVATAR_URL

        # Unwrap TransformerError to see the original cause
        original = getattr(error, "original", error)

        if isinstance(original, (app_commands.MissingPermissions, app_commands.CheckFailure)):
            await premium_response(
                interaction,
                title="Access Denied",
                description=str(original),
                color=0xE74C3C,
                bot_icon=avatar_url,
            )

        elif isinstance(original, app_commands.CommandOnCooldown):
            await premium_response(
                interaction,
                title="Slow Down!",
                description=f"This command is on cooldown. Try again in **{original.retry_after:.1f}s**.",
                color=0xF39C12,
                bot_icon=avatar_url,
            )

        elif isinstance(original, app_commands.BotMissingPermissions):
            await premium_response(
                interaction,
                title="Missing Bot Permissions",
                description=(
                    "I'm missing the following permissions:\n"
                    + "\n".join(f"• `{p}`" for p in original.missing_permissions)
                ),
                color=0xE74C3C,
                bot_icon=avatar_url,
            )

        else:
            log.error(
                "Unhandled slash command error in /%s: %s",
                getattr(interaction.command, "name", "unknown"),
                original,
                exc_info=True,
            )
            await premium_response(
                interaction,
                title="Unexpected Error",
                description=(
                    f"An unexpected error occurred.\n"
                    f"```{type(original).__name__}: {original}```"
                ),
                color=0xE74C3C,
                bot_icon=avatar_url,
            )


# ──────────────────────────────────────────────────────────────────────────────
#  Entry point
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    if not DISCORD_BOT_TOKEN:
        log.critical("DISCORD_BOT_TOKEN is not set – cannot start.")
        sys.exit(1)

    bot = BloxPulseBot()
    _register_error_handler(bot)

    log.info("Starting REST API…")
    start_api()

    log.info("Connecting to Discord…")
    try:
        bot.run(DISCORD_BOT_TOKEN, log_handler=None)  # we handle logging ourselves
    except discord.LoginFailure:
        log.critical("Invalid DISCORD_BOT_TOKEN. Check your environment variables.")
        sys.exit(1)
    except KeyboardInterrupt:
        log.info("Interrupted – shutting down.")


if __name__ == "__main__":
    main()