# ============================================================
#   BloxPulse | Roblox Version Monitor — core/history.py
#   Fetches version history from Roblox's public DeployHistory.txt
# ============================================================

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone, timedelta
from typing import Optional

import requests

from config import REQUEST_TIMEOUT, RETRY_ATTEMPTS, RETRY_DELAY, HISTORY_DAYS, HISTORY_MAX

logger = logging.getLogger("monitor.history")

# ── CDN URLs ─────────────────────────────────────────────────

_DEPLOY_HISTORY_URLS = {
    "WindowsPlayer":   "https://setup.rbxcdn.com/DeployHistory.txt",
    "WindowsStudio64": "https://setup.rbxcdn.com/DeployHistory.txt",
    "MacPlayer":       "https://setup.rbxcdn.com/mac/DeployHistory.txt",
    "MacStudio":       "https://setup.rbxcdn.com/mac/DeployHistory.txt",
}

# Type labels as they appear in DeployHistory.txt
_TYPE_LABELS = {
    "WindowsPlayer":   "WindowsPlayer",
    "WindowsStudio64": "Studio64",
    "MacPlayer":       "Client",
    "MacStudio":       "Studio",
}

# Regex: "New WindowsPlayer version-abc123 at 3/2/2026 5:13:57 PM, file version: 0, 711, 0, 7110873, ..."
# Flexible with spaces after commas for version numbers
_LINE_RE = re.compile(
    r"New (\S+) (version-[0-9a-f]+) at (\d+/\d+/\d+ \d+:\d+:\d+ [AP]M)"
    r".*?file version:\s*(\d+),\s*(\d+),\s*(\d+),\s*(\d+)"
)


def _fetch_text(url: str) -> Optional[str]:
    """GET with retries, returns plain text or None."""
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            r = requests.get(url, timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            return r.text
        except Exception as e:
            logger.warning("History fetch error (attempt %d/%d): %s", attempt, RETRY_ATTEMPTS, e)
            if attempt < RETRY_ATTEMPTS:
                time.sleep(RETRY_DELAY)
    return None


def _parse_history_txt(text: str, type_label: str, cutoff: datetime) -> list[dict]:
    """
    Parses the DeployHistory.txt file content and returns entries matching
    the given type_label that are newer than cutoff.
    Result is sorted newest first.
    """
    results = []
    for line in text.splitlines():
        m = _LINE_RE.match(line.strip())
        if not m:
            continue
        entry_type, version_hash, ts_str, v1, v2, v3, v4 = m.groups()
        if entry_type != type_label:
            continue

        try:
            # e.g. "3/2/2026 5:13:57 PM"
            ts = datetime.strptime(ts_str, "%m/%d/%Y %I:%M:%S %p")
            ts = ts.replace(tzinfo=timezone.utc)
        except ValueError:
            continue

        if ts < cutoff:
            continue

        version_str = f"{v1}.{v2}.{v3}.{v4}"
        results.append({
            "version_hash": version_hash,
            "version":      version_str,
            "timestamp":    ts,
            "type":         entry_type,
        })

    results.sort(key=lambda x: x["timestamp"], reverse=True)
    return results[:HISTORY_MAX]


def fetch_deploy_history(platform_key: str, days: int = HISTORY_DAYS) -> list[dict]:
    """
    Returns up to HISTORY_MAX version entries for a platform from the last `days` days.
    Each entry: {"version_hash": str, "version": str, "timestamp": datetime, "type": str}
    Supported: WindowsPlayer, WindowsStudio64, MacPlayer, MacStudio.
    Returns [] for platforms without public history (Android, iOS).
    """
    url = _DEPLOY_HISTORY_URLS.get(platform_key)
    if not url:
        logger.info("No public deploy history for %s", platform_key)
        return []

    type_label = _TYPE_LABELS.get(platform_key, platform_key)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    text = _fetch_text(url)
    if not text:
        logger.error("Failed to fetch deploy history for %s", platform_key)
        return []

    entries = _parse_history_txt(text, type_label, cutoff)
    logger.info("Fetched %d history entries for %s (last %d days)", len(entries), platform_key, days)
    return entries


def make_rdd_url(platform_key: str, version_hash: str, channel: str = "LIVE") -> Optional[str]:
    """
    Build a direct RDD download URL for Windows or Mac versions.
    Note: RDD (rdd.latte.to) is a third-party service and may occasionally fail with 403.
    """
    binary_map = {
        "WindowsPlayer":   "WindowsPlayer",
        "WindowsStudio64": "WindowsStudio64",
        "MacPlayer":       "MacPlayer",
        "MacStudio":       "MacStudio",
    }
    bt = binary_map.get(platform_key)
    if not bt:
        return None
    
    # Ensure version_hash is clean
    clean_hash = version_hash.strip()
    return f"https://rdd.latte.to/?channel={channel}&binaryType={bt}&version={clean_hash}"
