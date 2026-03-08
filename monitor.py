#!/usr/bin/env python3
# monitor.py
"""
BloxPulse · Standalone Monitor Process
========================================
An independent 24/7 version-detection daemon that runs without Discord.
Useful for:
  • Bare-metal deployments where the bot runs separately.
  • CI pipelines that need to detect version changes without a bot token.
  • Local testing of the detection pipeline.

Usage
-----
    python monitor.py               # run forever
    python monitor.py --once        # single check cycle, then exit
    python monitor.py --dry-run     # check cycle without persisting or notifying
"""
from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── Path bootstrap ─────────────────────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
import core.storage as storage
from core.checker import VersionInfo, fetch_all
from core.notifier import notify_update, notify_startup, notify_error


# ──────────────────────────────────────────────────────────────────────────────
#  Logging
# ──────────────────────────────────────────────────────────────────────────────

def _configure_logging(verbose: bool = False) -> None:
    level   = logging.DEBUG if verbose else logging.INFO
    fmt     = "%(asctime)s [%(levelname)-8s] %(name)s – %(message)s"
    datefmt = "%Y-%m-%dT%H:%M:%S"

    Path(config.LOG_FILE).parent.mkdir(parents=True, exist_ok=True)

    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(config.LOG_FILE, encoding="utf-8"),
    ]
    for h in handlers:
        h.setFormatter(logging.Formatter(fmt, datefmt))

    root = logging.getLogger()
    root.setLevel(level)
    for h in handlers:
        root.addHandler(h)


log = logging.getLogger("BloxPulse.Monitor")


# ──────────────────────────────────────────────────────────────────────────────
#  State & metrics
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class CycleMetrics:
    """Lightweight stats collected per check cycle."""
    started_at:   datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at:  Optional[datetime] = None
    platforms_ok: int = 0
    platforms_err: int = 0
    changes_found: int = 0
    notified_ok:   int = 0
    notified_err:  int = 0

    @property
    def duration_s(self) -> float:
        if self.finished_at is None:
            return 0.0
        return (self.finished_at - self.started_at).total_seconds()

    def summary(self) -> str:
        return (
            f"duration={self.duration_s:.2f}s  "
            f"ok={self.platforms_ok}  err={self.platforms_err}  "
            f"changes={self.changes_found}  "
            f"notified={self.notified_ok}/{self.changes_found}"
        )


@dataclass
class MonitorState:
    """Mutable runtime state shared across check cycles."""
    # platform_key → last known version hash
    known: dict[str, str] = field(default_factory=dict)
    total_cycles:    int   = 0
    total_changes:   int   = 0
    last_heartbeat:  float = field(default_factory=time.monotonic)


# ──────────────────────────────────────────────────────────────────────────────
#  Signal handling
# ──────────────────────────────────────────────────────────────────────────────

class _ShutdownRequested(Exception):
    """Raised by the signal handler to initiate a clean shutdown."""


_shutdown = False


def _install_signal_handlers() -> None:
    def _handler(sig, _frame):
        global _shutdown
        log.info("Signal %s received – requesting shutdown…", sig)
        _shutdown = True

    signal.signal(signal.SIGINT,  _handler)
    signal.signal(signal.SIGTERM, _handler)


# ──────────────────────────────────────────────────────────────────────────────
#  Check cycle
# ──────────────────────────────────────────────────────────────────────────────

def _run_check_cycle(
    state:   MonitorState,
    dry_run: bool = False,
) -> CycleMetrics:
    """
    Execute one full version check pass.

    1. Fetch all platforms.
    2. Compare each against the known state.
    3. Notify + persist on change (unless dry_run).

    Parameters
    ----------
    state   : Shared MonitorState updated in-place.
    dry_run : If True, skip persistence and notifications.

    Returns
    -------
    CycleMetrics for this cycle.
    """
    metrics = CycleMetrics()
    results = fetch_all()

    for platform_key, vi in results.items():
        if vi is None:
            log.warning("Failed to fetch version for %s", platform_key)
            metrics.platforms_err += 1
            continue

        metrics.platforms_ok += 1
        prev_hash = state.known.get(platform_key)

        # ── First detection ────────────────────────────────────────────────────
        if prev_hash is None:
            log.info("First detection – %s: %s", platform_key, vi)
            state.known[platform_key] = vi.version_hash
            if not dry_run:
                storage.update_version(platform_key, vi.version_hash, is_official=True)
            continue

        # ── No change ─────────────────────────────────────────────────────────
        if prev_hash == vi.version_hash:
            log.debug("No change – %s (%s)", platform_key, vi.version)
            continue

        # ── Version changed ───────────────────────────────────────────────────
        metrics.changes_found += 1
        log.info(
            "🆕 Change detected – %s: %s → %s",
            platform_key,
            prev_hash[:20],
            vi.version_hash[:20],
        )

        if dry_run:
            log.info("(dry-run) Skipping persist & notify for %s", platform_key)
            state.known[platform_key] = vi.version_hash
            continue

        # Persist first so state is consistent even if notify fails
        storage.update_version(platform_key, vi.version_hash, is_official=True)
        state.known[platform_key] = vi.version_hash

        # Notify
        ok = notify_update(platform_key, vi, prev_hash=prev_hash)
        if ok:
            metrics.notified_ok += 1
        else:
            metrics.notified_err += 1
            log.error("Notification failed for %s – state was still persisted.", platform_key)

    metrics.finished_at = datetime.now(timezone.utc)
    state.total_cycles  += 1
    state.total_changes += metrics.changes_found
    return metrics


# ──────────────────────────────────────────────────────────────────────────────
#  Interruptible sleep
# ──────────────────────────────────────────────────────────────────────────────

def _sleep_until(deadline: float, check_interval: float = 0.5) -> bool:
    """
    Sleep until ``deadline`` (monotonic), waking every ``check_interval``
    to check the shutdown flag.

    Returns True if shutdown was requested during the sleep.
    """
    while not _shutdown and time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        time.sleep(min(check_interval, max(0.0, remaining)))
    return _shutdown


# ──────────────────────────────────────────────────────────────────────────────
#  Main loop
# ──────────────────────────────────────────────────────────────────────────────

def _print_banner() -> None:
    width = 62
    log.info("=" * width)
    log.info("  BloxPulse · Standalone Monitor")
    log.info("  Version  : %s", config.BOT_VERSION)
    log.info("  Interval : %ds", config.CHECK_INTERVAL)
    log.info("  Platforms: %s", ", ".join(config.PLATFORMS.keys()))
    log.info("=" * width)


def run(once: bool = False, dry_run: bool = False) -> int:
    """
    Main entry point for the monitoring daemon.

    Parameters
    ----------
    once    : Run a single check cycle, then exit.
    dry_run : Skip persistence and Discord notifications.

    Returns
    -------
    Exit code (0 = clean exit, 1 = startup failure).
    """
    _install_signal_handlers()
    _print_banner()

    if dry_run:
        log.info("⚠  DRY RUN – no data will be persisted or sent to Discord.")

    # ── Bootstrap state from storage ──────────────────────────────────────────
    state = MonitorState()
    for platform_key in config.PLATFORMS:
        platform_state = storage.get_version_data(platform_key)
        if current := platform_state.get("last_update"):
            state.known[platform_key] = current

    log.info("Loaded %d known version(s) from storage.", len(state.known))

    # ── Startup notification ───────────────────────────────────────────────────
    if not dry_run and not once:
        log.info("Fetching startup snapshot…")
        startup_versions = fetch_all()
        notify_startup(startup_versions)

        # Register any platform we have no record of
        for platform_key, vi in startup_versions.items():
            if vi and platform_key not in state.known:
                storage.update_version(platform_key, vi.version_hash, is_official=True)
                state.known[platform_key] = vi.version_hash

    # ── Main loop ─────────────────────────────────────────────────────────────
    last_heartbeat = time.monotonic()

    while not _shutdown:
        cycle_start = time.monotonic()
        log.info("── Cycle #%d starting ──────────────────", state.total_cycles + 1)

        try:
            metrics = _run_check_cycle(state, dry_run=dry_run)
            log.info("── Cycle complete: %s", metrics.summary())
        except Exception:
            tb = traceback.format_exc()
            log.error("Unhandled exception in check cycle:\n%s", tb)
            if not dry_run:
                try:
                    notify_error(tb)
                except Exception:
                    pass

        if once or _shutdown:
            break

        # ── Heartbeat ─────────────────────────────────────────────────────────
        now = time.monotonic()
        if now - last_heartbeat >= config.HEARTBEAT_EVERY:
            log.info(
                "◈ Heartbeat – cycles: %d | total changes: %d | next check in %ds",
                state.total_cycles,
                state.total_changes,
                config.CHECK_INTERVAL,
            )
            last_heartbeat = now

        # ── Sleep until next cycle ─────────────────────────────────────────────
        elapsed  = time.monotonic() - cycle_start
        sleep_s  = max(0.0, config.CHECK_INTERVAL - elapsed)
        log.debug("Sleeping %.1fs until next cycle.", sleep_s)
        if _sleep_until(time.monotonic() + sleep_s):
            break   # shutdown requested during sleep

    log.info(
        "Monitor stopped cleanly after %d cycle(s) and %d change(s).",
        state.total_cycles,
        state.total_changes,
    )
    return 0


# ──────────────────────────────────────────────────────────────────────────────
#  CLI
# ──────────────────────────────────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="monitor",
        description="BloxPulse standalone version monitor daemon.",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single check cycle and exit immediately.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Check for changes without persisting state or sending notifications.",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable DEBUG-level logging.",
    )
    return parser


if __name__ == "__main__":
    args = _build_parser().parse_args()
    _configure_logging(verbose=args.verbose)
    sys.exit(run(once=args.once, dry_run=args.dry_run))