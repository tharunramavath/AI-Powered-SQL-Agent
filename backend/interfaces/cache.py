"""Cache backend interface for storing/retrieving serializable values."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class CacheBackend(Protocol):
    """Protocol for a key-value cache (Redis, in-memory, ...)."""

    def get(self, key: str) -> Any | None:
        """Retrieve a cached value by key, or None on miss."""
        ...

    def set(self, key: str, value: Any, *, ttl_seconds: int | None = None) -> None:
        """Store a value under a key with an optional TTL."""
        ...

    def delete(self, key: str) -> None:
        """Remove a key from the cache."""
        ...

    def exists(self, key: str) -> bool:
        """Return True if the key is present."""
        ...

    def close(self) -> None:
        """Release any held resources."""
        ...
