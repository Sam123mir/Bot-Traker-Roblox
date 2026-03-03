# ============================================================
#   BloxPulse | Roblox Version Monitor — core/checker.py
#   Fetches versions from all supported platforms.
# ============================================================

from __future__ import annotations

import re
import time
import logging
from dataclasses import dataclass, field
from typing import Optional

import requests

from config import PLATFORMS, REQUEST_TIMEOUT, RETRY_ATTEMPTS, RETRY_DELAY

logger = logging.getLogger("monitor.checker")

# ── Data Model ────────────────────────────────────────────────

@dataclass
class VersionInfo:
    platform_key: str
    version:      str          # e.g. "0.710.1.7100707"
    version_hash: str          # e.g. "version-760d064d05424689"
    channel:      str = "LIVE"
    source:       str = ""
    raw:          dict = field(default_factory=dict)

    @property
    def short_hash(self) -> str:
        """Returns only the hex part of the hash, e.g. 760d064d05424689"""
        return self.version_hash.replace("version-", "")

    def __str__(self) -> str:
        return f"{self.version} ({self.version_hash})"


# ── Network Utilities ─────────────────────────────────────────

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    )
}

def _get_json(url: str, headers: dict = None, **kwargs) -> Optional[dict]:
    """GET with retries, returns parsed JSON or None."""
    h = {**_HEADERS, **(headers or {})}
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            r = requests.get(url, timeout=REQUEST_TIMEOUT, headers=h, **kwargs)
            r.raise_for_status()
            return r.json()
        except requests.HTTPError as e:
            logger.warning("HTTP %s on %s (attempt %d/%d)", e.response.status_code, url, attempt, RETRY_ATTEMPTS)
        except Exception as e:
            logger.warning("Error on %s (attempt %d/%d): %s", url, attempt, RETRY_ATTEMPTS, e)
        if attempt < RETRY_ATTEMPTS:
            time.sleep(RETRY_DELAY)
    return None

def _get_text(url: str, headers: dict = None, **kwargs) -> Optional[str]:
    """GET with retries, returns plain text or None."""
    h = {**_HEADERS, **(headers or {})}
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            r = requests.get(url, timeout=REQUEST_TIMEOUT, headers=h, **kwargs)
            r.raise_for_status()
            return r.text.strip()
        except requests.HTTPError as e:
            logger.warning("HTTP %s on %s (attempt %d/%d)", e.response.status_code, url, attempt, RETRY_ATTEMPTS)
        except Exception as e:
            logger.warning("Error on %s (attempt %d/%d): %s", url, attempt, RETRY_ATTEMPTS, e)
        if attempt < RETRY_ATTEMPTS:
            time.sleep(RETRY_DELAY)
    return None


# ── Source Functions ──────────────────────────────────────────

def _from_cdn(platform_key: str, cfg: dict) -> Optional[VersionInfo]:
    """
    Fetches Windows/Mac version hash from the Roblox CDN (setup.rbxcdn.com).
    Windows: https://setup.rbxcdn.com/version      → plain text hash
    Mac:     https://setup.rbxcdn.com/mac/version  → plain text hash
    """
    if platform_key == "WindowsPlayer":
        cdn_url = "https://setup.rbxcdn.com/version"
    elif platform_key == "MacPlayer":
        cdn_url = "https://setup.rbxcdn.com/mac/version"
    else:
        return None

    version_hash = _get_text(cdn_url)
    if not version_hash or not version_hash.startswith("version-"):
        logger.warning("Unexpected CDN response for %s: %s", platform_key, version_hash)
        return _from_roblox_api(platform_key, cfg)

    # Get pretty version number from Roblox API
    api_key = cfg.get("api_key", platform_key)
    api_url = f"https://clientsettingscdn.roblox.com/v2/client-version/{api_key}/channel/LIVE"
    data    = _get_json(api_url)
    version = data.get("version", version_hash.replace("version-", "")) if data else version_hash.replace("version-", "")

    return VersionInfo(
        platform_key=platform_key,
        version=version,
        version_hash=version_hash,
        channel="LIVE",
        source="Roblox CDN",
        raw={"hash": version_hash, "version": version},
    )


def _from_roblox_api(platform_key: str, cfg: dict) -> Optional[VersionInfo]:
    """
    Fallback: Fetches version from Roblox Client Settings API.
    https://clientsettingscdn.roblox.com/v2/client-version/{key}/channel/LIVE
    """
    api_key = cfg.get("api_key", platform_key)
    url     = f"https://clientsettingscdn.roblox.com/v2/client-version/{api_key}/channel/LIVE"
    data    = _get_json(url)

    if not data or "clientVersionUpload" not in data:
        return None

    return VersionInfo(
        platform_key=platform_key,
        version=data.get("version", ""),
        version_hash=data.get("clientVersionUpload", ""),
        channel="LIVE",
        source="Roblox Client Settings API",
        raw=data,
    )


def _from_appstore(platform_key: str, cfg: dict) -> Optional[VersionInfo]:
    """
    Fetches iOS version from the iTunes Lookup API using the app numeric ID.
    Uses id=431946152 (more reliable than bundleId lookup).
    Falls back to bundleId if needed.
    """
    # Primary: numeric app ID (more reliable)
    url  = "https://itunes.apple.com/lookup?id=431946152&country=us"
    data = _get_json(url)

    if not data or data.get("resultCount", 0) == 0:
        # Fallback: bundleId lookup
        bundle_id = cfg.get("bundle_id", "com.roblox.roblox")
        url2  = f"https://itunes.apple.com/lookup?bundleId={bundle_id}&country=us"
        data  = _get_json(url2)

    if not data or data.get("resultCount", 0) == 0:
        logger.warning("iTunes API returned no results for iOS Roblox")
        return None

    result  = data["results"][0]
    version = result.get("version", "")
    if not version:
        return None

    return VersionInfo(
        platform_key=platform_key,
        version=version,
        version_hash=f"appstore-{version.replace('.', '_')}",
        channel="App Store",
        source="Apple iTunes API",
        raw=result,
    )


def _from_playstore(platform_key: str, cfg: dict) -> Optional[VersionInfo]:
    """
    Fetches Android version by scraping the Google Play Store page.
    This is the most reliable method since Roblox's clientsettingscdn
    endpoint for AndroidApp is currently returning HTTP 500.
    """
    PACKAGE = "com.roblox.client"
    url     = f"https://play.google.com/store/apps/details?id={PACKAGE}&hl=en"
    html    = _get_text(url)
    if not html:
        logger.warning("Failed to fetch Google Play page for Android")
        return None

    # Google Play embeds version in multiple patterns:
    # Pattern 1: "[[["2.712.001"" in the JSON-embedded data
    # Pattern 2: data-version="x.x.x" (older layout)
    # We try multiple regexes for resilience
    version = None

    # Most reliable: looks for the version string near the package name
    patterns = [
        r'"' + PACKAGE + r'"[^]]*?\[\[\["([\d.]+)"',
        r'\[\[\["([\d]+\.[\d]+\.[\d]+)"',
        r'Current Version.*?<span[^>]*>([\d.]+)</span>',
        r'"softwareVersion":"([\d.]+)"',
        r'itemprop="softwareVersion"[^>]*>\s*([\d.]+)',
    ]
    for pat in patterns:
        m = re.search(pat, html, re.DOTALL)
        if m:
            candidate = m.group(1)
            # Sanity check: must look like a version number (digits and dots)
            if re.match(r'^\d+\.\d+', candidate):
                version = candidate
                logger.info("Android version found via pattern '%s': %s", pat[:40], version)
                break

    if not version:
        logger.warning("Could not extract Android version from Play Store HTML")
        return None

    return VersionInfo(
        platform_key=platform_key,
        version=version,
        version_hash=f"android-{version.replace('.', '_')}",
        channel="Google Play",
        source="Google Play Store",
        raw={"version": version, "package": PACKAGE},
    )


# ── Dispatcher ────────────────────────────────────────────────

_SOURCES = {
    "cdn":        _from_cdn,
    "roblox_api": _from_roblox_api,  # kept for any future use
    "appstore":   _from_appstore,
    "playstore":  _from_playstore,
}

def fetch_version(platform_key: str) -> Optional[VersionInfo]:
    """Entry point: fetches the version for a single platform."""
    cfg = PLATFORMS.get(platform_key)
    if not cfg:
        logger.error("Unknown platform: %s", platform_key)
        return None

    source_fn = _SOURCES.get(cfg["source"])
    if not source_fn:
        logger.error("Unknown source '%s' for %s", cfg["source"], platform_key)
        return None

    return source_fn(platform_key, cfg)


def fetch_all() -> dict[str, Optional[VersionInfo]]:
    """Fetches versions for all configured platforms."""
    results = {}
    for key in PLATFORMS:
        results[key] = fetch_version(key)
        logger.debug("Version for %s: %s", key, results[key])
    return results