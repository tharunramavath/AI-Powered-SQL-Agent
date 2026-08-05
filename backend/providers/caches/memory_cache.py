"""In-memory cache implementation (thread-safe, TTL-aware).

Suitable for single-process dev/test environments. For production
multi-worker deployments use :class:`RedisCache` instead.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from backend.interfaces.cache import CacheBackend


class InMemoryCache(CacheBackend):
    """A simple TTL-aware in-memory key/value cache."""

    def __init__(self) -> None:
        """Initialize an empty store with a lock for thread safety."""
        self._store: dict[str, tuple[Any, float | None]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        """Return the cached value for key, expiring stale entries.

        Args:
            key: Cache key.

        Returns:
            The stored value, or None if missing/expired.
        """
        with self._lock:
            item = self._store.get(key)
            if item is None:
                return None
            value, expires_at = item
            if expires_at is not None and expires_at <= time.monotonic():
                del self._store[key]
                return None
            return value

    def set(self, key: str, value: Any, *, ttl_seconds: int | None = None) -> None:
        """Store a value with an optional TTL.

        Args:
            key: Cache key.
            value: Value to store (must be JSON-serializable for callers).
            ttl_seconds: Seconds until expiry; None means no expiry.
        """
        expires_at = time.monotonic() + ttl_seconds if ttl_seconds is not None else None
        with self._lock:
            self._store[key] = (value, expires_at)

    def delete(self, key: str) -> None:
        """Remove a key from the cache if present."""
        with self._lock:
            self._store.pop(key, None)

    def exists(self, key: str) -> bool:
        """Return True if the key currently has a live value."""
        return self.get(key) is not None

    def close(self) -> None:
        """Clear the store (no external resources to release)."""
        with self._lock:
            self._store.clear()
