# core/history.py
"""
BloxPulse · Version History Engine
====================================
Fetches and parses Roblox platform version history from multiple sources:

  • Roblox CDN  DeployHistory.txt  (Windows / Mac)
  • Local storage fallback          (Android / iOS)

Public surface
--------------
  fetch_deploy_history(platform_key, days) → list[HistoryEntry]
  make_rdd_url(platform_key, version_hash, channel) → str | None
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests
from requests import Response, Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import HISTORY_DAYS, HISTORY_MAX, REQUEST_TIMEOUT, RETRY_ATTEMPTS, RETRY_DELAY

log = logging.getLogger("BloxPulse.History")


# ──────────────────────────────────────────────────────────────────────────────
#  Data model
# ──────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class HistoryEntry:
    """Immutable record representing a single versioned release."""
    version_hash: str
    version:      str
    timestamp:    datetime
    type:         str

    def as_dict(self) -> dict:
        return {
            "version_hash": self.version_hash,
            "version":      self.version,
            "timestamp":    self.timestamp.isoformat(),
            "type":         self.type,
        }


# ──────────────────────────────────────────────────────────────────────────────
#  Constants
# ──────────────────────────────────────────────────────────────────────────────

_DEPLOY_HISTORY_URLS: dict[str, str] = {
    "WindowsPlayer":   "https://setup.rbxcdn.com/DeployHistory.txt",
    "WindowsStudio64": "https://setup.rbxcdn.com/DeployHistory.txt",
    "MacPlayer":       "https://setup.rbxcdn.com/mac/DeployHistory.txt",
    "MacStudio":       "https://setup.rbxcdn.com/mac/DeployHistory.txt",
}

# Maps platform key → label used inside DeployHistory.txt
_DEPLOY_TYPE_LABELS: dict[str, str] = {
    "WindowsPlayer":   "WindowsPlayer",
    "WindowsStudio64": "Studio64",
    "MacPlayer":       "Client",
    "MacStudio":       "Studio",
}

# RDD binary type identifiers
_RDD_BINARY_MAP: dict[str, str] = {
    "WindowsPlayer":   "WindowsPlayer",
    "WindowsStudio64": "WindowsStudio64",
    "MacPlayer":       "MacPlayer",
    "MacStudio":       "MacStudio",
}

# Local timestamp format stored by storage.py
_LOCAL_TS_FORMAT = "%Y-%m-%d %H:%M UTC"

# Matches lines like:
#   New WindowsPlayer version-abc123 at 3/2/2026 5:13:57 PM, file version: 0, 711, 0, 7110873
_DEPLOY_LINE_RE = re.compile(
    r"New (\S+) (version-[0-9a-f]+) at (\d+/\d+/\d+ \d+:\d+:\d+ [AP]M)"
    r".*?file version:\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)"
)

_DEPLOY_TS_FORMAT = "%m/%d/%Y %I:%M:%S %p"


# ──────────────────────────────────────────────────────────────────────────────
#  HTTP session (shared, with retry logic)
# ──────────────────────────────────────────────────────────────────────────────

def _build_session() -> Session:
    """Create a requests Session with automatic exponential-backoff retries."""
    session = Session()
    retry = Retry(
        total=RETRY_ATTEMPTS,
        backoff_factor=RETRY_DELAY,
        status_forcelist={429, 500, 502, 503, 504},
        allowed_methods={"GET"},
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://",  adapter)
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "text/plain, text/html;q=0.9, */*;q=0.8",
    })
    return session


_session: Session = _build_session()


def _fetch_text(url: str) -> Optional[str]:
    """
    GET `url` and return the response body as plain text.
    Returns None on any error after exhausting retries.
    """
    try:
        response: Response = _session.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        return response.text
    except requests.HTTPError as exc:
        log.error(
            "HTTP %s fetching history from %s",
            exc.response.status_code if exc.response is not None else "?",
            url,
        )
    except requests.ConnectionError:
        log.error("Connection error fetching history from %s", url)
    except requests.Timeout:
        log.error("Timeout fetching history from %s (limit=%ss)", url, REQUEST_TIMEOUT)
    except Exception as exc:
        log.error("Unexpected error fetching history from %s: %s", url, exc, exc_info=True)
    return None


# ──────────────────────────────────────────────────────────────────────────────
#  Parsers
# ──────────────────────────────────────────────────────────────────────────────

def _parse_deploy_history(
    text:       str,
    type_label: str,
    cutoff:     datetime,
) -> list[HistoryEntry]:
    """
    Parse the raw text of a DeployHistory.txt file.

    Only entries matching `type_label` and newer than `cutoff` are kept.
    Results are sorted newest-first and capped at HISTORY_MAX.
    """
    entries: list[HistoryEntry] = []

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        match = _DEPLOY_LINE_RE.match(line)
        if not match:
            continue

        entry_type, version_hash, ts_str, v1, v2, v3, v4 = match.groups()

        if entry_type != type_label:
            continue

        try:
            ts = datetime.strptime(ts_str, _DEPLOY_TS_FORMAT).replace(tzinfo=timezone.utc)
        except ValueError:
            log.debug("Unparseable timestamp %r in DeployHistory line – skipped", ts_str)
            continue

        if ts < cutoff:
            continue

        entries.append(
            HistoryEntry(
                version_hash=version_hash,
                version=f"{v1}.{v2}.{v3}.{v4}",
                timestamp=ts,
                type=entry_type,
            )
        )

    entries.sort(key=lambda e: e.timestamp, reverse=True)
    return entries[:HISTORY_MAX]


def _parse_local_storage(platform_key: str) -> list[HistoryEntry]:
    """
    Build history from BloxPulse's local storage when no CDN source exists
    (Android / iOS) or as an emergency fallback.
    """
    from core.storage import get_version_data  # local import to avoid circular deps

    state          = get_version_data(platform_key) or {}
    history_hashes = state.get("history", [])
    timestamps_map = state.get("timestamps", {})

    entries: list[HistoryEntry] = []

    for version_hash in history_hashes:
        ts_str = timestamps_map.get(version_hash)
        if not ts_str:
            continue
        try:
            ts = datetime.strptime(ts_str, _LOCAL_TS_FORMAT).replace(tzinfo=timezone.utc)
        except ValueError:
            log.debug("Unparseable local timestamp %r for %s – skipped", ts_str, platform_key)
            continue

        clean = (
            version_hash
            .replace("version-", "")
            .replace("android-", "")
            .replace("ios-", "")
        )
        entries.append(
            HistoryEntry(
                version_hash=version_hash,
                version=clean,
                timestamp=ts,
                type=platform_key,
            )
        )

    entries.sort(key=lambda e: e.timestamp, reverse=True)
    return entries[:HISTORY_MAX]


# ──────────────────────────────────────────────────────────────────────────────
#  Public API
# ──────────────────────────────────────────────────────────────────────────────

def fetch_deploy_history(
    platform_key: str,
    days:         int = HISTORY_DAYS,
) -> list[HistoryEntry]:
    """
    Return up to ``HISTORY_MAX`` version entries for *platform_key*
    from the last *days* calendar days.

    Strategy
    --------
    1. If the platform has a public CDN DeployHistory.txt, fetch and parse it.
    2. On CDN failure, fall back to local storage.
    3. For platforms without a CDN URL (Android / iOS), go straight to local storage.

    Parameters
    ----------
    platform_key : One of PLATFORMS keys (WindowsPlayer, MacPlayer, etc.)
    days         : How far back to look. Defaults to HISTORY_DAYS from config.

    Returns
    -------
    Sorted list of HistoryEntry objects, newest first.
    """
    cdn_url    = _DEPLOY_HISTORY_URLS.get(platform_key)
    type_label = _DEPLOY_TYPE_LABELS.get(platform_key)
    cutoff     = datetime.now(timezone.utc) - timedelta(days=days)

    # ── Platforms with a CDN source ───────────────────────────────────────────
    if cdn_url and type_label:
        text = _fetch_text(cdn_url)

        if text:
            entries = _parse_deploy_history(text, type_label, cutoff)
            log.info(
                "Fetched %d history entries for %s from CDN (last %d days)",
                len(entries), platform_key, days,
            )
            return entries

        log.warning(
            "CDN fetch failed for %s – falling back to local storage", platform_key
        )

    # ── Platforms without CDN source (or CDN failed) ──────────────────────────
    entries = _parse_local_storage(platform_key)
    log.info(
        "Loaded %d history entries for %s from local storage",
        len(entries), platform_key,
    )
    return entries


def make_rdd_url(
    platform_key: str,
    version_hash: str,
    channel:      str = "LIVE",
) -> Optional[str]:
    """
    Build a direct RDD download URL for a Windows or Mac release.

    Returns None for unsupported platforms (Android / iOS do not have RDD URLs).

    Note
    ----
    RDD (rdd.latte.to) is a third-party service. It may occasionally return
    403 responses for very new or very old versions.
    """
    binary_type = _RDD_BINARY_MAP.get(platform_key)
    if not binary_type:
        log.debug("make_rdd_url: platform %s has no RDD binary type", platform_key)
        return None

    clean_hash = version_hash.strip()
    url = f"https://rdd.latte.to/?channel={channel}&binaryType={binary_type}&version={clean_hash}"
    log.debug("make_rdd_url: %s", url)
    return url