# api/v2/cache.py
"""
Lightweight in-memory TTL cache for BloxPulse API v2.
Reduces storage lookups and ensures high performance.
"""

from __future__ import annotations

import time
from threading import Lock
from typing import Any

_store: dict[str, tuple[Any, float]] = {}
_lock = Lock()

def get(key: str) -> Any | None:
    """Retrieve a value if it exists and hasn't expired."""
    with _lock:
        if key in _store:
            value, expires_at = _store[key]
            if time.time() < expires_at:
                return value
            del _store[key]
    return None

def set(key: str, value: Any, ttl: int = 30) -> None:
    """Store a value with a given TTL (seconds)."""
    with _lock:
        _store[key] = (value, time.time() + ttl)

def invalidate(key: str) -> None:
    """Remove a specific key from the cache."""
    with _lock:
        _store.pop(key, None)

def invalidate_all() -> None:
    """Clear the entire cache."""
    with _lock:
        _store.clear()
