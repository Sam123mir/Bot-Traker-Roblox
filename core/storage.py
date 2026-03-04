# ============================================================
#   BloxPulse | Roblox Version Monitor — storage.py
#   Version persistence and server configuration.
# ============================================================

from __future__ import annotations
import json
import logging
import os
import shutil
from datetime import datetime, timezone
from typing import Optional

from config import VERSIONS_FILE, GUILDS_FILE, ANNOUNCEMENTS_FILE

logger = logging.getLogger("monitor.storage")

# ── File Helpers ──────────────────────────────────────────────

def _load_json(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as e:
        logger.error("Error reading %s: %s", path, e)
        return {}

def _save_json(path: str, data: dict) -> bool:
    # Asegurar que el directorio existe
    os.makedirs(os.path.dirname(path), exist_ok=True)
    
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=4, ensure_ascii=False)
        shutil.move(tmp, path)
        return True
    except Exception as e:
        logger.error("Error saving %s: %s", path, e)
        if os.path.exists(tmp):
            os.remove(tmp)
        return False

# ── Version Persistence ───────────────────────────────────────

def _now_str() -> str:
    """Returns current UTC time as a readable string."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

def get_version_data(platform_key: str) -> dict:
    """Returns {'current': str, 'last_update': str, 'last_build': str, 'history': list, 'timestamps': dict}."""
    data  = _load_json(VERSIONS_FILE)
    state = data.get(platform_key)
    if not isinstance(state, dict):
        return {
            "current": str(state) if state else "", 
            "last_update": "",
            "last_build": "",
            "history": [], 
            "timestamps": {}
        }
    # Ensure keys exist (migration)
    if "timestamps" not in state: state["timestamps"] = {}
    if "history" not in state: state["history"] = []
    if "last_update" not in state: state["last_update"] = state.get("current", "")
    if "last_build" not in state: state["last_build"] = ""
    return state

def update_version(platform_key: str, new_hash: str, is_official: bool = True, timestamp: Optional[str] = None) -> bool:
    """
    Updates the version record. 
    If is_official=True, updates last_update.
    If is_official=False, updates last_build.
    Stores all versions in history (unlimited).
    """
    full_data = _load_json(VERSIONS_FILE)
    state     = get_version_data(platform_key)
    history   = state.get("history", [])
    timestamps: dict = state.get("timestamps", {})

    # Record timestamp for new hash
    final_ts = timestamp or _now_str()
    if new_hash not in timestamps:
        timestamps[new_hash] = final_ts

    # Add to history if unique
    if new_hash not in history:
        history.insert(0, new_hash)
        state["history"] = history # No cap as requested: "keep all versions"

    if is_official:
        state["current"] = new_hash
        state["last_update"] = new_hash
    else:
        state["last_build"] = new_hash

    state["timestamps"] = timestamps
    full_data[platform_key] = state
    return _save_json(VERSIONS_FILE, full_data)

def backfill_history(platform_key: str, entries: list[dict]):
    """
    Populates the database with historical entries.
    entries: list of {"version_hash": str, "version": str, "timestamp": datetime}
    """
    if not entries:
        return
    
    full_data = _load_json(VERSIONS_FILE)
    state     = get_version_data(platform_key)
    history   = state.get("history", [])
    timestamps: dict = state.get("timestamps", {})
    
    changed = False
    # Sort entries by timestamp ascending to insert newest last (so newest ends up at index 0)
    sorted_entries = sorted(entries, key=lambda x: x["timestamp"])
    
    for entry in sorted_entries:
        h = entry["version_hash"]
        ts_str = entry["timestamp"].strftime("%Y-%m-%d %H:%M UTC")
        
        if h not in history:
            history.insert(0, h)
            timestamps[h] = ts_str
            changed = True
    
    if changed:
        state["history"] = history
        state["timestamps"] = timestamps
        # If current is empty, set it to the newest one
        if not state.get("current") and history:
            state["current"] = history[0]
            state["last_update"] = history[0]
            
        full_data[platform_key] = state
        _save_json(VERSIONS_FILE, full_data)
        logger.info("Backfilled %d versions for %s", len(entries), platform_key)

# ── Guild Configuration ───────────────────────────────────────

def get_guild_config(guild_id: int) -> dict:
    data = _load_json(GUILDS_FILE)
    return data.get(str(guild_id), {
        "channel_id":   None,
        "ping_role_id": None,
        "language":     "en",
        "announcement_channel_id": None,
    })

def set_guild_config(guild_id: int, key: str, value) -> bool:
    data = _load_json(GUILDS_FILE)
    gid  = str(guild_id)
    if gid not in data:
        data[gid] = {
            "channel_id": None, 
            "ping_role_id": None, 
            "language": "en",
            "announcement_channel_id": None
        }
    data[gid][key] = value
    return _save_json(GUILDS_FILE, data)

def get_all_guilds() -> dict:
    return _load_json(GUILDS_FILE)

def get_all_announcement_channels() -> list[int]:
    """Returns a list of all configured announcement channel IDs."""
    data = get_all_guilds()
    channels = []
    for config in data.values():
        chan_id = config.get("announcement_channel_id")
        if chan_id:
            channels.append(int(chan_id))
    return channels

# ── Announcement History ──────────────────────────────────────

def get_announcements() -> list[dict]:
    """Returns the list of the last 3 announcements."""
    data = _load_json(ANNOUNCEMENTS_FILE)
    return data.get("history", [])

def save_announcement(ann_data: dict) -> bool:
    """Saves an announcement to history, keeping only the last 3."""
    data = _load_json(ANNOUNCEMENTS_FILE)
    history = data.get("history", [])
    # Add to front
    history.insert(0, ann_data)
    # Keep last 3
    data["history"] = history[:3]
    return _save_json(ANNOUNCEMENTS_FILE, data)
