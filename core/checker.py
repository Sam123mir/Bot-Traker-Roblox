# core/checker.py
"""
BloxPulse · Version Fetcher & Dispatcher
=========================================
Fetches the current Roblox client version for every supported platform
using the most reliable source for each one:

  Windows / Mac  → Roblox CDN  (primary)  → Client Settings API (fallback)
  iOS            → Apple iTunes Lookup API
  Android        → Google Play Store HTML scrape

Public surface
--------------
  fetch_version(platform_key, channel) → VersionInfo | None
  fetch_all(channel)                   → dict[str, VersionInfo | None]
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Optional

import requests
from requests import Response, Session
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config import PLATFORMS, REQUEST_TIMEOUT, RETRY_ATTEMPTS, RETRY_DELAY

log = logging.getLogger("BloxPulse.Checker")


# ──────────────────────────────────────────────────────────────────────────────
#  Data model
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class VersionInfo:
    """Structured result of a version fetch for a single platform."""

    platform_key: str
    version:      str            # Human-readable e.g. "0.710.1.7100707"
    version_hash: str            # CDN hash  e.g. "version-760d064d05424689"
    channel:      str  = "LIVE"
    source:       str  = ""
    raw:          dict = field(default_factory=dict)
    components:   list[str] = field(default_factory=list)
    fflag_count:  int = 0

    # ── Computed properties ────────────────────────────────────────────────────

    @property
    def short_hash(self) -> str:
        """Hex part only – strips the 'version-' prefix."""
        return self.version_hash.replace("version-", "")

    @property
    def is_mobile(self) -> bool:
        return self.platform_key in ("AndroidApp", "iOS")

    def __str__(self) -> str:
        return f"{self.platform_key} {self.version} ({self.version_hash}) [{self.channel}]"


# ──────────────────────────────────────────────────────────────────────────────
#  Shared HTTP session
# ──────────────────────────────────────────────────────────────────────────────

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Accept-Language":        "en-US,en;q=0.9",
    "Connection":             "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


def _build_session() -> Session:
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
    session.headers.update(_BROWSER_HEADERS)
    return session


_session: Session = _build_session()


# ──────────────────────────────────────────────────────────────────────────────
#  Low-level request helpers
# ──────────────────────────────────────────────────────────────────────────────

def _get(url: str, *, extra_headers: dict | None = None, **kwargs) -> Optional[Response]:
    """
    Perform a GET with the shared session and unified error handling.
    Returns the Response object on success (2xx), None otherwise.
    """
    headers = {**_BROWSER_HEADERS, **(extra_headers or {})}
    try:
        resp = _session.get(url, timeout=REQUEST_TIMEOUT, headers=headers, **kwargs)
        resp.raise_for_status()
        return resp
    except requests.HTTPError as exc:
        code = exc.response.status_code if exc.response is not None else "?"
        # We silence 401 (Auth) and 404 (Not Found) as they are common fallbacks
        if code in (401, 404):
            log.debug("HTTP %s on GET %s (Expected fallback)", code, url)
        else:
            log.warning("HTTP %s on GET %s", code, url)
        
        if exc.response is not None and exc.response.status_code == 403:
            time.sleep(RETRY_DELAY * 2)   # back off harder on auth failures
    except requests.Timeout:
        log.warning("Timeout on GET %s (limit=%ss)", url, REQUEST_TIMEOUT)
    except requests.ConnectionError:
        log.warning("Connection error on GET %s", url)
    except Exception as exc:
        log.error("Unexpected error on GET %s: %s", url, exc, exc_info=True)
    return None


def _get_json(url: str, **kwargs) -> Optional[dict]:
    resp = _get(url, **kwargs)
    if resp is None:
        return None
    try:
        return resp.json()
    except ValueError:
        log.warning("Non-JSON response from %s", url)
        return None


def _get_text(url: str, **kwargs) -> Optional[str]:
    resp = _get(url, **kwargs)
    return resp.text.strip() if resp is not None else None


# ──────────────────────────────────────────────────────────────────────────────
#  Manifest fetcher
# ──────────────────────────────────────────────────────────────────────────────

_MANIFEST_FILE_EXTENSIONS = (".zip", ".exe", ".dll", ".app", ".dmg")


def _fetch_manifest(platform_key: str, version_hash: str) -> list[str]:
    """
    Download and parse rbxPkgManifest.txt for `version_hash`.
    Returns a list of component filenames. Empty list on failure.
    """
    if platform_key == "WindowsPlayer":
        url     = f"https://setup.rbxcdn.com/{version_hash}-rbxPkgManifest.txt"
        referer = "https://www.roblox.com/"
    elif platform_key == "MacPlayer":
        url     = f"https://setup.rbxcdn.com/mac/{version_hash}-rbxPkgManifest.txt"
        referer = "https://www.roblox.com/download/client?os=mac"
    else:
        return []

    text = _get_text(url, extra_headers={"Referer": referer})
    if not text:
        log.warning("Manifest not available for %s @ %s", platform_key, version_hash)
        return []

    components = [
        line.strip()
        for line in text.splitlines()
        if line.strip().endswith(_MANIFEST_FILE_EXTENSIONS)
    ]
    log.debug(
        "Parsed %d component(s) from manifest for %s %s",
        len(components), platform_key, version_hash,
    )
    return components


# ──────────────────────────────────────────────────────────────────────────────
#  Source functions
# ──────────────────────────────────────────────────────────────────────────────

def _from_maximumadhd(
    platform_key: str,
    cfg:          dict,
    channel:      str = "LIVE",
) -> Optional[VersionInfo]:
    """
    Primary source inspired by MaximumADHD's trackers.
    Fetches version and GUID from GitHub raw content (Roblox-Client-Tracker).
    Only supports LIVE channel as Maximum usually tracks live production builds.
    """
    if channel != "LIVE":
        return None

    # Branch mapping for MaximumADHD/Roblox-Client-Tracker
    branch_map = {
        "WindowsPlayer": "roblox",
        "MacPlayer":     "mac-roblox",
        "WindowsStudio": "studio",
        "MacStudio":     "mac-studio",
    }
    branch = branch_map.get(platform_key)
    if not branch:
        return None

    try:
        base_url = f"https://raw.githubusercontent.com/MaximumADHD/Roblox-Client-Tracker/{branch}"
        version  = _get_text(f"{base_url}/version.txt")
        guid     = _get_text(f"{base_url}/version-guid.txt")

        if not version or not guid:
            return None

        # FFlag count from Roblox-FFlag-Tracker
        fflag_file_map = {
            "WindowsPlayer": "PCDesktopClient.json",
            "WindowsStudio": "StudioApp.json",
            "MacPlayer":     "MacDesktopClient.json",
            "MacStudio":     "MacStudioApp.json",
        }
        fflag_file = fflag_file_map.get(platform_key)
        ff_count   = 0
        if fflag_file:
            ff_data = _get_json(f"https://raw.githubusercontent.com/MaximumADHD/Roblox-FFlag-Tracker/main/{fflag_file}")
            ff_count = len(ff_data) if ff_data else 0

        return VersionInfo(
            platform_key=platform_key,
            version=version.strip(),
            version_hash=guid.strip(),
            channel=channel,
            source="MaximumADHD API",
            raw={"version": version, "guid": guid},
            fflag_count=ff_count,
        )
    except Exception as exc:
        log.warning("MaximumADHD API fetch failed for %s: %s", platform_key, exc)
        return None


def _from_deployment_api(
    platform_key: str,
    cfg:          dict,
    channel:      str = "LIVE",
) -> Optional[VersionInfo]:
    """
    Secondary/Fallback source for PC, Mac, and Studio platforms.
    Polls the official Roblox Client Settings API for deployment info.
    """
    api_key = cfg.get("api_key", platform_key)
    url     = (
        f"https://clientsettingscdn.roblox.com/v2/client-version"
        f"/{api_key}/channel/{channel}"
    )
    data    = _get_json(url)

    if not data or "clientVersionUpload" not in data:
        log.warning("Deployment API returned no usable data for %s [%s]", platform_key, channel)
        return None

    version_hash = data["clientVersionUpload"]
    version      = data.get("version", version_hash.replace("version-", ""))
    
    # FFlags from Roblox API (Fallback)
    fflags      = _fetch_fflags(platform_key, channel)
    fflag_count = len(fflags.get("applicationSettings", {})) if fflags else 0

    return VersionInfo(
        platform_key=platform_key,
        version=version,
        version_hash=version_hash,
        channel=channel,
        source="Roblox Deployment API",
        raw=data,
        fflag_count=fflag_count,
    )


def _fetch_fflags(platform_key: str, channel: str) -> Optional[dict]:
    """
    Fetch the current FFlags for a given platform and channel.
    Maps platform_key to internal Roblox application names.
    """
    app_map = {
        "WindowsPlayer": "PCDesktopClient",
        "WindowsStudio": "PCStudioApp",
        "MacPlayer":     "MacDesktopClient",
        "MacStudio":     "MacStudioApp",
    }
    app_name = app_map.get(platform_key)
    if not app_name:
        return None

    url = (
        f"https://clientsettings.roblox.com/v1/settings/application"
        f"?applicationName={app_name}&channel={channel}"
    )
    return _get_json(url)




def _from_appstore(
    platform_key: str,
    cfg:          dict,
) -> Optional[VersionInfo]:
    """
    Fetch the current iOS Roblox version from the Apple iTunes Lookup API.
    Tries the numeric app-ID first (most stable), then the bundle-ID.
    """
    for url in [
        "https://itunes.apple.com/lookup?id=431946152&country=us",
        f"https://itunes.apple.com/lookup?bundleId={cfg.get('bundle_id', 'com.roblox.roblox')}&country=us",
    ]:
        data = _get_json(url)
        if data and data.get("resultCount", 0) > 0:
            break
    else:
        log.error("iTunes API returned no results for iOS Roblox after both attempts")
        return None

    result  = data["results"][0]
    version = result.get("version", "")
    if not version:
        log.warning("iTunes result has no 'version' field: %s", result)
        return None

    return VersionInfo(
        platform_key=platform_key,
        version=version,
        version_hash=f"appstore-{version.replace('.', '_')}",
        channel="App Store",
        source="Apple iTunes API",
        raw=result,
    )


# Ordered list of regex patterns tried against Google Play HTML, most reliable first
_PLAY_VERSION_PATTERNS: tuple[re.Pattern, ...] = (
    re.compile(r'"com\.roblox\.client"[^]]*?\[\[\["([\d.]+)"', re.DOTALL),
    re.compile(r'\[\[\["([\d]+\.[\d]+\.[\d]+)"'),
    re.compile(r'"softwareVersion":"([\d.]+)"'),
    re.compile(r'itemprop="softwareVersion"[^>]*>\s*([\d.]+)'),
    re.compile(r'Current Version.*?<span[^>]*>([\d.]+)</span>', re.DOTALL),
)

_PLAY_VERSION_RE = re.compile(r'^\d+\.\d+')   # sanity check


def _from_playstore(
    platform_key: str,
    cfg:          dict,
) -> Optional[VersionInfo]:
    """
    Fetch the current Android Roblox version by scraping the Google Play page.

    Roblox's clientsettingscdn endpoint for Android returns HTTP 500,
    making scraping the only reliable source.
    Multiple regex patterns are tried in order so that minor Play Store
    HTML changes do not silently break version detection.
    """
    package = "com.roblox.client"
    url     = f"https://play.google.com/store/apps/details?id={package}&hl=en"
    html    = _get_text(url)

    if not html:
        log.error("Failed to fetch Google Play page for Android")
        return None

    version: Optional[str] = None
    matched_pattern: Optional[str] = None

    for pattern in _PLAY_VERSION_PATTERNS:
        match = pattern.search(html)
        if not match:
            continue
        candidate = match.group(1)
        if _PLAY_VERSION_RE.match(candidate):
            version         = candidate
            matched_pattern = pattern.pattern[:50]
            break

    if not version:
        log.error(
            "Could not extract Android version from Play Store HTML. "
            "The page layout may have changed."
        )
        return None

    log.info("Android version detected via pattern %r: %s", matched_pattern, version)

    return VersionInfo(
        platform_key=platform_key,
        version=version,
        version_hash=f"android-{version.replace('.', '_')}",
        channel="Google Play",
        source="Google Play Store",
        raw={"version": version, "package": package},
    )


# ──────────────────────────────────────────────────────────────────────────────
#  Dispatcher
# ──────────────────────────────────────────────────────────────────────────────

# Maps the "source" config key to the corresponding fetch function
_SOURCE_DISPATCH = {
    "roblox_api": _from_deployment_api,
    "appstore":   _from_appstore,
    "playstore":  _from_playstore,
}

# Sources that accept a `channel` argument
_CHANNEL_AWARE_SOURCES = frozenset({"cdn", "roblox_api"})


def _compare_versions(v1: str, v2: str) -> int:
    """Returns 1 if v1 > v2, -1 if v1 < v2, 0 if equal."""
    try:
        p1 = [int(p) for p in v1.split('.')]
        p2 = [int(p) for p in v2.split('.')]
        for i in range(min(len(p1), len(p2))):
            if p1[i] > p2[i]: return 1
            if p1[i] < p2[i]: return -1
        return 0
    except Exception:
        return 0


def fetch_version(
    platform_key: str,
    channel:      str = "LIVE",
) -> Optional[VersionInfo]:
    """
    Main entry point for fetching a specific platform's version.
    Priority:
    1. MaximumADHD API (GitHub) for PC/Studio LIVE.
    2. Roblox Deployment API (Fallback/Other channels).
    3. platform-specific stores (Mobile).
    """
    cfg = PLATFORMS.get(platform_key)
    if not cfg:
        log.error("fetch_version: Unknown platform key: %r", platform_key)
        return None

    source_id = cfg["source"]
    
    # ── Source Dispatch ───────────────────────────────────────────────────────
    
    # PC/Studio: Compare MaximumADHD vs Official API
    if source_id == "roblox_api" and channel == "LIVE":
        vi_max = _from_maximumadhd(platform_key, cfg, channel)
        vi_api = _from_deployment_api(platform_key, cfg, channel)
        
        if not vi_max: return vi_api
        if not vi_api: return vi_max
        
        # Compare build numbers
        if _compare_versions(vi_api.version, vi_max.version) > 0:
            log.info("Official API is newer than MaximumADHD for %s (%s > %s)", platform_key, vi_api.version, vi_max.version)
            # Use official metadata but keep FFlag count from Maximum if available
            vi_api.fflag_count = vi_max.fflag_count
            return vi_api
        return vi_max

    fetch_fn = _SOURCE_DISPATCH.get(source_id)
    if not fetch_fn:
        log.error("No fetch function defined for source: %s", source_id)
        return None

    result = fetch_fn(platform_key, cfg, channel) if source_id in _CHANNEL_AWARE_SOURCES else fetch_fn(platform_key, cfg)

    if result is None:
        log.warning("fetch_version: all sources failed for %s [channel=%s]", platform_key, channel)
    else:
        log.debug("fetch_version: successful for %s", platform_key)

    return result


def fetch_all(channel: str = "LIVE") -> dict[str, Optional[VersionInfo]]:
    """
    Fetch versions for every platform defined in PLATFORMS config.

    Parameters
    ----------
    channel : Release channel to query for all platforms (default "LIVE").

    Returns
    -------
    Dict mapping platform_key → VersionInfo (or None on failure).
    """
    results: dict[str, Optional[VersionInfo]] = {}
    for platform_key in PLATFORMS:
        results[platform_key] = fetch_version(platform_key, channel)
    return results