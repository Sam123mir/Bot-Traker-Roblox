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

from config import VERSIONS_FILE, GUILDS_FILE

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
    """Returns {'current': str, 'history': list, 'timestamps': dict}."""
    data  = _load_json(VERSIONS_FILE)
    state = data.get(platform_key)
    if not isinstance(state, dict):
        return {"current": str(state) if state else "", "history": [], "timestamps": {}}
    # Ensure timestamps key exists (migration)
    if "timestamps" not in state:
        state["timestamps"] = {}
    return state

def update_version(platform_key: str, new_hash: str) -> bool:
    """Updates the current hash, saves it to history with a timestamp (max 10 entries)."""
    full_data = _load_json(VERSIONS_FILE)
    state     = get_version_data(platform_key)
    old_hash  = state.get("current", "")

    timestamps: dict = state.get("timestamps", {})

    if old_hash and old_hash != new_hash:
        history = state.get("history", [])
        if old_hash not in history:
            history.insert(0, old_hash)
            state["history"] = history[:10]   # keep up to 10 entries

    # Record timestamp for new hash when first seen
    if new_hash not in timestamps:
        timestamps[new_hash] = _now_str()

    state["current"]    = new_hash
    state["timestamps"] = timestamps
    full_data[platform_key] = state
    return _save_json(VERSIONS_FILE, full_data)

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
