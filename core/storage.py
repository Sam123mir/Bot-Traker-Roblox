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
    get_version_data(platform_key)             → VersionState
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
from datetime import datetime, timezone
from typing import Any, Optional, TypedDict

from config import ANNOUNCEMENTS_FILE, GUILDS_FILE, VERSIONS_FILE

log = logging.getLogger("BloxPulse.Storage")

# ──────────────────────────────────────────────────────────────────────────────
#  Typed interfaces
# ──────────────────────────────────────────────────────────────────────────────

class VersionState(TypedDict, total=False):
    current:     str
    last_update: str
    last_build:  str
    history:     list[str]
    timestamps:  dict[str, str]


class GuildConfig(TypedDict, total=False):
    channel_id:              Optional[int]
    ping_role_id:            Optional[int]
    language:                str
    announcement_channel_id: Optional[int]
    welcome_channel_id:      Optional[int]
    welcome_dm_enabled:      bool
    goodbye_enabled:         bool
    auto_role_ids:           list[int]
    welcome_color:           int


_DEFAULT_GUILD_CONFIG: GuildConfig = {
    "channel_id":              None,
    "ping_role_id":            None,
    "language":                "en",
    "announcement_channel_id": None,
    "welcome_channel_id":      None,
    "welcome_dm_enabled":      False,
    "goodbye_enabled":         False,
    "auto_role_ids":           [],
    "welcome_color":           0x00E5FF,
}

_EMPTY_VERSION_STATE: VersionState = {
    "current":     "",
    "last_update": "",
    "last_build":  "",
    "history":     [],
    "timestamps":  {},
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
    os.makedirs(os.path.dirname(path), exist_ok=True)
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
    if not isinstance(raw, dict):
        # Legacy: stored value was just a plain hash string
        current = str(raw) if raw else ""
        return {**_EMPTY_VERSION_STATE, "current": current, "last_update": current}

    state: VersionState = {**_EMPTY_VERSION_STATE, **raw}

    # Back-fill missing fields
    if not state.get("last_update"):
        state["last_update"] = state.get("current", "")

    return state


# ──────────────────────────────────────────────────────────────────────────────
#  Version state
# ──────────────────────────────────────────────────────────────────────────────

def get_version_data(platform_key: str) -> VersionState:
    """
    Return the full version state for *platform_key*.
    Always returns a fully-shaped VersionState dict (never raises).
    """
    with _lock_for(VERSIONS_FILE):
        raw = _load_json(VERSIONS_FILE).get(platform_key)
    return _migrate_version_state(raw)


def update_version(
    platform_key: str,
    new_hash:     str,
    is_official:  bool = True,
    timestamp:    Optional[str] = None,
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

    with _lock_for(VERSIONS_FILE):
        full_data = _load_json(VERSIONS_FILE)
        state     = _migrate_version_state(full_data.get(platform_key))

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
        else:
            state["last_build"] = new_hash

        state["history"]    = history
        state["timestamps"] = timestamps
        full_data[platform_key] = state

        ok = _save_json(VERSIONS_FILE, full_data)

    if ok:
        log.debug(
            "update_version: %s → %s (official=%s)",
            platform_key, new_hash, is_official,
        )
    else:
        log.error("update_version: write failed for %s", platform_key)

    return ok


def backfill_history(platform_key: str, entries: list) -> int:
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

    # Sort ascending so newest ends up at index 0 after insert
    try:
        sorted_entries = sorted(entries, key=lambda e: getattr(e, "timestamp", None) or e["timestamp"])
    except (TypeError, KeyError) as exc:
        log.error("backfill_history: cannot sort entries for %s: %s", platform_key, exc)
        return 0

    added = 0

    with _lock_for(VERSIONS_FILE):
        full_data = _load_json(VERSIONS_FILE)
        state     = _migrate_version_state(full_data.get(platform_key))
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

            full_data[platform_key] = state
            _save_json(VERSIONS_FILE, full_data)
            log.info("backfill_history: added %d new entries for %s", added, platform_key)

    return added


# ──────────────────────────────────────────────────────────────────────────────
#  Guild configuration
# ──────────────────────────────────────────────────────────────────────────────

def get_all_guilds() -> dict[str, GuildConfig]:
    """Return a snapshot of every guild's configuration dict."""
    with _lock_for(GUILDS_FILE):
        return _load_json(GUILDS_FILE)


def get_guild_config(guild_id: int) -> GuildConfig:
    """
    Return the configuration for a single guild, merging defaults for any
    missing keys so callers never have to handle KeyError / None.
    """
    with _lock_for(GUILDS_FILE):
        data = _load_json(GUILDS_FILE)

    raw = data.get(str(guild_id), {})
    return {**_DEFAULT_GUILD_CONFIG, **raw}


def set_guild_config(guild_id: int, key: str, value: Any) -> bool:
    """
    Set a single configuration key for a guild.

    Creates the guild entry if it does not exist yet.
    Returns True on successful write.
    """
    gid = str(guild_id)

    with _lock_for(GUILDS_FILE):
        data = _load_json(GUILDS_FILE)

        if gid not in data:
            data[gid] = dict(_DEFAULT_GUILD_CONFIG)

        data[gid][key] = value
        ok = _save_json(GUILDS_FILE, data)

    if not ok:
        log.error("set_guild_config: write failed for guild %s key=%s", guild_id, key)
    return ok


def set_guild_config_bulk(guild_id: int, updates: dict[str, Any]) -> bool:
    """
    Set multiple configuration keys for a guild in a single atomic write.
    More efficient than calling ``set_guild_config`` in a loop.
    """
    gid = str(guild_id)

    with _lock_for(GUILDS_FILE):
        data = _load_json(GUILDS_FILE)

        if gid not in data:
            data[gid] = dict(_DEFAULT_GUILD_CONFIG)

        data[gid].update(updates)
        ok = _save_json(GUILDS_FILE, data)

    if not ok:
        log.error("set_guild_config_bulk: write failed for guild %s", guild_id)
    return ok


def remove_guild(guild_id: int) -> bool:
    """
    Delete all stored configuration for a guild (called on bot kick/leave).
    Returns True if the guild was present and removed.
    """
    gid = str(guild_id)
    with _lock_for(GUILDS_FILE):
        data = _load_json(GUILDS_FILE)
        if gid not in data:
            return False
        del data[gid]
        return _save_json(GUILDS_FILE, data)


def get_all_announcement_channels() -> list[int]:
    """Return every configured announcement channel ID across all guilds."""
    with _lock_for(GUILDS_FILE):
        data = _load_json(GUILDS_FILE)
    return [
        int(cfg["announcement_channel_id"])
        for cfg in data.values()
        if cfg.get("announcement_channel_id")
    ]


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