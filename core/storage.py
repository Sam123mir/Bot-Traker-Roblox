# core/storage.py
"""
BloxPulse · Storage Engine
============================
Atomic JSON persistence for version state, guild configuration,
and announcement history.

All writes go through a write-then-rename pattern (tmp → final)
so a crash mid-write never corrupts the live file.

Public surface
--------------
Version state
    get_version_data(platform_key, channel)    → VersionState
    update_version(platform_key, ...)          → bool
    backfill_history(platform_key, entries)    → int   (new entries added)

Guild configuration
    get_all_guilds()                           → dict[str, GuildConfig]
    get_guild_config(guild_id)                 → GuildConfig
    set_guild_config(guild_id, key, value)     → bool
    get_all_announcement_channels()            → list[int]

Announcements
    get_announcements()                        → list[dict]
    save_announcement(ann_data)                → bool
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import threading
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import Any, Optional, TypedDict

from config import ANNOUNCEMENTS_FILE, GUILDS_FILE, VERSIONS_FILE, SERVERS_DIR

log = logging.getLogger("BloxPulse.Storage")


# ──────────────────────────────────────────────────────────────────────────────
#  Path & Name Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _sanitize_name(name: Optional[str]) -> str:
    """Clean a guild name for use as a folder name."""
    if not name:
        return "Unknown_Server"
    # Replace spaces and invalid chars with underscores
    clean = re.sub(r'[^\w\s-]', '', name).strip()
    clean = re.sub(r'[-\s]+', '_', clean)
    return clean or "Unknown_Server"


def _get_guild_dir(guild_id: int, guild_name: Optional[str] = None) -> Path:
    """
    Resolve the directory for a guild. 
    Format: data/servers/SanitizedName_ID/
    """
    gid_str = str(guild_id)
    base_dir = Path(SERVERS_DIR)
    
    # Try to find existing folder ending with _ID
    if base_dir.exists():
        for entry in base_dir.iterdir():
            if entry.is_dir() and entry.name.endswith(f"_{gid_str}"):
                return entry

    # If not found, create a new one
    safe_name = _sanitize_name(guild_name)
    folder_name = f"{safe_name}_{gid_str}"
    path = base_dir / folder_name
    path.mkdir(parents=True, exist_ok=True)
    return path


def _get_guild_config_path(guild_id: int, guild_name: Optional[str] = None) -> str:
    folder = _get_guild_dir(guild_id, guild_name)
    return str(folder / "config.json")


# ──────────────────────────────────────────────────────────────────────────────
#  Typed interfaces
# ──────────────────────────────────────────────────────────────────────────────

class VersionState(TypedDict, total=False):
    current:     str
    last_update: str
    last_build:  str
    history:     list[str]
    timestamps:  dict[str, str]
    fflag_count: int


class GuildConfig(TypedDict, total=False):
    channel_id:              Optional[int]
    ping_role_id:            Optional[int]
    language:                str
    announcement_channel_id: Optional[int]
    welcome_channel_id:      Optional[int]
    goodbye_channel_id:      Optional[int]
    welcome_dm_enabled:      bool
    goodbye_enabled:         bool
    auto_role_ids:           list[int]
    welcome_color:           int
    member_count_channel_id: Optional[int]
    rules_channel_id:        Optional[int]
    roles_channel_id:        Optional[int]
    intro_channel_id:        Optional[int]
    bug_reports_channel_id:  Optional[int]
    suggestions_channel_id:  Optional[int]
    api_status_win_id:       Optional[int]
    api_status_mac_id:       Optional[int]
    api_status_android_id:   Optional[int]
    api_status_ios_id:       Optional[int]
    bot_version_channel_id:  Optional[int]


_DEFAULT_GUILD_CONFIG: GuildConfig = {
    "channel_id":              None,
    "ping_role_id":            None,
    "language":                "en",
    "announcement_channel_id": None,
    "welcome_channel_id":      None,
    "goodbye_channel_id":      None,
    "welcome_dm_enabled":      False,
    "goodbye_enabled":         False,
    "auto_role_ids":           [],
    "welcome_color":           0x00E5FF,
    "member_count_channel_id": None,
    "rules_channel_id":        None,
    "roles_channel_id":        None,
    "intro_channel_id":        None,
    "bug_reports_channel_id":  None,
    "suggestions_channel_id":  None,
    "api_status_win_id":       None,
    "api_status_mac_id":       None,
    "api_status_android_id":   None,
    "api_status_ios_id":       None,
    "bot_version_channel_id":  None,
}

# ──────────────────────────────────────────────────────────────────────────────
#  Thread-safe file lock registry
#  One lock per path so concurrent reads/writes to different files don't block.
# ──────────────────────────────────────────────────────────────────────────────

_file_locks: dict[str, threading.Lock] = {
    VERSIONS_FILE:      threading.Lock(),
    GUILDS_FILE:        threading.Lock(),
    ANNOUNCEMENTS_FILE: threading.Lock(),
}


def _lock_for(path: str) -> threading.Lock:
    return _file_locks.setdefault(path, threading.Lock())


# ──────────────────────────────────────────────────────────────────────────────
#  Low-level JSON I/O
# ──────────────────────────────────────────────────────────────────────────────

def _load_json(path: str) -> dict:
    """
    Load a JSON file into a dict.
    Returns an empty dict if the file does not exist or is malformed.
    The caller is responsible for holding the appropriate lock.
    """
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError as exc:
        log.error("Corrupt JSON in %s (offset %d): %s", path, exc.pos, exc.msg)
        _rotate_corrupt(path)
        return {}
    except OSError as exc:
        log.error("Cannot read %s: %s", path, exc)
        return {}


def _save_json(path: str, data: dict) -> bool:
    """
    Atomically write `data` to `path` using a tmp-file + rename strategy.
    The caller is responsible for holding the appropriate lock.
    Returns True on success.
    """
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except OSError as e:
        log.error("Failed to create parent directory for %s: %s", path, e)
        
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=4, ensure_ascii=False)
        shutil.move(tmp, path)
        return True
    except OSError as exc:
        log.error("Failed to write %s: %s", path, exc)
        _cleanup_tmp(tmp)
        return False


def _rotate_corrupt(path: str) -> None:
    """Rename a corrupt file to .corrupt so we don't loop on bad data."""
    corrupt = path + ".corrupt"
    try:
        shutil.move(path, corrupt)
        log.warning("Renamed corrupt file: %s → %s", path, corrupt)
    except OSError:
        pass


def _cleanup_tmp(tmp: str) -> None:
    try:
        if os.path.exists(tmp):
            os.remove(tmp)
    except OSError:
        pass


# ──────────────────────────────────────────────────────────────────────────────
#  Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _migrate_version_state(raw: Any) -> VersionState:
    """
    Ensure a raw storage value has the full VersionState shape.
    Handles both legacy string values and partially-migrated dicts.
    """
    # Always start with a fresh copy of the template to avoid cross-contamination
    state: VersionState = {
        "current":     "",
        "last_update": "",
        "last_build":  "",
        "history":     [],
        "timestamps":  {},
        "fflag_count": 0,
    }

    if not isinstance(raw, dict):
        if raw:
            val = str(raw)
            state["current"] = val
            state["last_update"] = val
        return state

    # Merge existing data into the fresh template
    state.update(raw)
    
    # Ensure nested objects are copies if they were just updated from raw
    state["history"] = list(state.get("history") or [])
    state["timestamps"] = dict(state.get("timestamps") or {})

    if not state.get("last_update"):
        state["last_update"] = state.get("current", "")

    return state


# ──────────────────────────────────────────────────────────────────────────────
#  Version state
# ──────────────────────────────────────────────────────────────────────────────

def get_version_data(platform_key: str, channel: str = "LIVE") -> VersionState:
    """
    Return the full version state for *platform_key* on a specific *channel*.
    Unique storage key: "platform:channel".
    """
    key = f"{platform_key}:{channel}" if channel != "LIVE" else platform_key
    with _lock_for(VERSIONS_FILE):
        raw = _load_json(VERSIONS_FILE).get(key)
        # Fallback to legacy key if no channel-specific key exists for LIVE
        if raw is None and channel == "LIVE":
            raw = _load_json(VERSIONS_FILE).get(platform_key)
            
    return _migrate_version_state(raw)


def update_version(
    platform_key: str,
    new_hash:     str,
    is_official:  bool = True,
    timestamp:    Optional[str] = None,
    channel:      str = "LIVE",
    fflag_count:  int = 0,
) -> bool:
    """
    Persist a new version hash for *platform_key*.

    Parameters
    ----------
    platform_key : e.g. "WindowsPlayer"
    new_hash     : The new version hash (e.g. "version-abc123…")
    is_official  : True → update ``current`` / ``last_update``.
                   False → update ``last_build`` only.
    timestamp    : Human-readable UTC string; defaults to now.

    Returns
    -------
    True on a successful write.
    """
    final_ts = timestamp or _now_str()
    key      = f"{platform_key}:{channel}" if channel != "LIVE" else platform_key

    with _lock_for(VERSIONS_FILE):
        full_data = _load_json(VERSIONS_FILE)
        state     = _migrate_version_state(full_data.get(key))

        history:    list[str]      = state["history"]
        timestamps: dict[str, str] = state["timestamps"]

        # Record timestamp only for new hashes
        if new_hash not in timestamps:
            timestamps[new_hash] = final_ts

        # Prepend to history if not already present
        if new_hash not in history:
            history.insert(0, new_hash)

        if is_official:
            state["current"]     = new_hash
            state["last_update"] = new_hash
            state["fflag_count"] = fflag_count
        else:
            state["last_build"] = new_hash

        state["history"]    = history
        state["timestamps"] = timestamps
        full_data[key]      = state

        ok = _save_json(VERSIONS_FILE, full_data)

    if ok:
        log.debug(
            "update_version: %s → %s (official=%s)",
            platform_key, new_hash, is_official,
        )
    else:
        log.error("update_version: write failed for %s", platform_key)

    return ok


def backfill_history(platform_key: str, entries: list, channel: str = "LIVE") -> int:
    """
    Populate the database with historical HistoryEntry objects (or plain dicts).

    Parameters
    ----------
    entries : Iterable of HistoryEntry / dict with keys:
              ``version_hash`` (str) and ``timestamp`` (datetime).

    Returns
    -------
    Number of new entries actually added to storage.
    """
    if not entries:
        return 0

    added = 0
    key = f"{platform_key}:{channel}" if channel != "LIVE" else platform_key

    # Sort ascending so newest ends up at index 0 after insert
    try:
        sorted_entries = sorted(entries, key=lambda e: getattr(e, "timestamp", None) or e["timestamp"])
    except (TypeError, KeyError) as exc:
        log.error("backfill_history: cannot sort entries for %s: %s", key, exc)
        return 0

    with _lock_for(VERSIONS_FILE):
        full_data = _load_json(VERSIONS_FILE)
        state     = _migrate_version_state(full_data.get(key))
        history:    list[str]      = state["history"]
        timestamps: dict[str, str] = state["timestamps"]

        for entry in sorted_entries:
            if isinstance(entry, dict):
                version_hash = entry["version_hash"]
                ts_obj       = entry["timestamp"]
            else:
                version_hash = entry.version_hash
                ts_obj       = entry.timestamp

            if isinstance(ts_obj, datetime):
                ts_str = ts_obj.strftime("%Y-%m-%d %H:%M UTC")
            else:
                ts_str = str(ts_obj)

            if version_hash not in history:
                history.insert(0, version_hash)
                timestamps[version_hash] = ts_str
                added += 1

        if added:
            state["history"]    = history
            state["timestamps"] = timestamps

            if not state.get("current") and history:
                state["current"]     = history[0]
                state["last_update"] = history[0]

            full_data[key] = state
            _save_json(VERSIONS_FILE, full_data)
            log.info("backfill_history: added %d new entries for %s", added, key)

    return added


# ──────────────────────────────────────────────────────────────────────────────
#  Guild configuration (Refactored for per-server storage)
# ──────────────────────────────────────────────────────────────────────────────

def get_all_guilds() -> dict[str, GuildConfig]:
    """
    Return a snapshot of every guild's configuration dict.
    Scans the data/servers/ directory.
    """
    all_configs = {}
    if not os.path.exists(SERVERS_DIR):
        return {}
        
    for entry in os.scandir(SERVERS_DIR):
        if entry.is_dir():
            # Extract ID from folder name (SanitizedName_ID)
            match = re.search(r'_(\d+)$', entry.name)
            if match:
                gid_str = match.group(1)
                config_path = os.path.join(entry.path, "config.json")
                if os.path.exists(config_path):
                    with _lock_for(config_path):
                        raw = _load_json(config_path)
                    all_configs[gid_str] = {**_DEFAULT_GUILD_CONFIG, **raw}
                    
    return all_configs


def get_guild_config(guild_id: int, guild_name: Optional[str] = None) -> GuildConfig:
    """
    Return the configuration for a single guild.
    """
    path = _get_guild_config_path(guild_id, guild_name)
    with _lock_for(path):
        raw = _load_json(path)

    return {**_DEFAULT_GUILD_CONFIG, **raw}


def set_guild_config(guild_id: int, key: str, value: Any, guild_name: Optional[str] = None) -> bool:
    """
    Set a single configuration key for a guild.
    """
    path = _get_guild_config_path(guild_id, guild_name)
    with _lock_for(path):
        data = _load_json(path)
        data[key] = value
        # Ensure server name is always stored
        if guild_name:
            data["server_name"] = guild_name
        ok = _save_json(path, data)

    if not ok:
        log.error("set_guild_config: write failed for guild %s key=%s", guild_id, key)
    return ok


def set_guild_config_bulk(guild_id: int, updates: dict[str, Any], guild_name: Optional[str] = None) -> bool:
    """
    Set multiple configuration keys for a guild.
    """
    path = _get_guild_config_path(guild_id, guild_name)
    with _lock_for(path):
        data = _load_json(path)
        data.update(updates)
        if guild_name:
            data["server_name"] = guild_name
        ok = _save_json(path, data)

    if not ok:
        log.error("set_guild_config_bulk: write failed for guild %s", guild_id)
    return ok


def remove_guild(guild_id: int) -> bool:
    """
    Delete all stored configuration for a guild.
    """
    folder = _get_guild_dir(guild_id)
    if folder.exists() and folder.is_dir():
        try:
            shutil.rmtree(folder)
            return True
        except OSError as e:
            log.error("Failed to remove guild folder %s: %s", folder, e)
            return False
    return False


def _migrate_guilds_if_needed():
    """Move data from legacy guilds.json to per-server files."""
    if not os.path.exists(GUILDS_FILE):
        return
        
    try:
        with _lock_for(GUILDS_FILE):
            legacy_data = _load_json(GUILDS_FILE)
            if not legacy_data:
                return
                
            log.info("Migrating legacy guilds data for %d servers...", len(legacy_data))
            for gid_str, config in legacy_data.items():
                try:
                    guild_id = int(gid_str)
                    # We don't have the name in legacy data easily, 
                    # use the stored name if it exists or fallback
                    name = config.get("server_name")
                    path = _get_guild_config_path(guild_id, name)
                    with _lock_for(path):
                        _save_json(path, config)
                except ValueError:
                    continue
            
            # Archive the old file
            shutil.move(GUILDS_FILE, GUILDS_FILE + ".migrated")
            log.info("Migration complete. Legacy file archived.")
    except Exception as e:
        log.error("Migration failed: %s", e)

# Run migration on import
_migrate_guilds_if_needed()


def get_all_announcement_channels() -> list[int]:
    """Return every configured announcement channel ID across all guilds."""
    channels = []
    guilds = get_all_guilds()
    for cfg in guilds.values():
        if cfg.get("announcement_channel_id"):
            try:
                channels.append(int(cfg["announcement_channel_id"]))
            except (ValueError, TypeError):
                continue
    return channels


# ──────────────────────────────────────────────────────────────────────────────
#  Announcement history
# ──────────────────────────────────────────────────────────────────────────────

_ANNOUNCEMENT_HISTORY_LIMIT = 3


def get_announcements() -> list[dict]:
    """Return the stored announcement history (newest first)."""
    with _lock_for(ANNOUNCEMENTS_FILE):
        data = _load_json(ANNOUNCEMENTS_FILE)
    return data.get("history", [])


def save_announcement(ann_data: dict) -> bool:
    """
    Prepend *ann_data* to the announcement history.
    Only the most recent ``_ANNOUNCEMENT_HISTORY_LIMIT`` entries are kept.
    Returns True on success.
    """
    with _lock_for(ANNOUNCEMENTS_FILE):
        data    = _load_json(ANNOUNCEMENTS_FILE)
        history = data.get("history", [])
        history.insert(0, ann_data)
        data["history"] = history[:_ANNOUNCEMENT_HISTORY_LIMIT]
        return _save_json(ANNOUNCEMENTS_FILE, data)