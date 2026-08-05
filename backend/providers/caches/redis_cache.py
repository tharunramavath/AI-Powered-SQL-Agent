"""Redis-backed cache implementation.

Values are stored as JSON so any process can read them. Uses a connection
pool shared across calls. This is the recommended cache for production
multi-worker deployments.
"""

from __future__ import annotations

import contextlib
import json
from typing import Any

from backend.core.logging import get_logger
from backend.interfaces.cache import CacheBackend

logger = get_logger(__name__)


class RedisCache(CacheBackend):
    """A JSON-serializing cache backed by Redis."""

    def __init__(self, url: str, *, prefix: str = "aiagent:"):
        """Initialize the Redis connection pool.

        Args:
            url: Redis connection URL (redis://host:port/db).
            prefix: Key prefix to namespace all cache keys.

        Raises:
            ImportError: If the ``redis`` package is not installed.
        """
        import redis  # lazily imported so redis remains optional

        self._client = redis.Redis.from_url(url, decode_responses=True)
        self._prefix = prefix

    def _key(self, key: str) -> str:
        """Return the namespaced cache key."""
        return f"{self._prefix}{key}"

    def get(self, key: str) -> Any | None:
        """Retrieve and deserialize a cached JSON value.

        Args:
            key: Cache key.

        Returns:
            The deserialized value, or None on miss/failure.
        """
        try:
            raw = self._client.get(self._key(key))
            if raw is None:
                return None
            return json.loads(str(raw))  # type: ignore[arg-type]
        except Exception as exc:  # pragma: no cover - redis errors
            logger.warning("cache_get_failed", error=str(exc))
            return None

    def set(self, key: str, value: Any, *, ttl_seconds: int | None = None) -> None:
        """Serialize and store a value, optionally with a TTL.

        Args:
            key: Cache key.
            value: JSON-serializable value.
            ttl_seconds: Seconds until expiry; None means no expiry.
        """
        try:
            self._client.set(self._key(key), json.dumps(value), ex=ttl_seconds)
        except Exception as exc:  # pragma: no cover
            logger.warning("cache_set_failed", error=str(exc))

    def delete(self, key: str) -> None:
        """Remove a key from Redis."""
        try:
            self._client.delete(self._key(key))
        except Exception as exc:  # pragma: no cover
            logger.warning("cache_delete_failed", error=str(exc))

    def exists(self, key: str) -> bool:
        """Return True if the key exists in Redis."""
        try:
            return bool(self._client.exists(self._key(key)))
        except Exception:  # pragma: no cover
            return False

    def close(self) -> None:
        """Close the Redis connection pool."""
        with contextlib.suppress(Exception):
            self._client.close()
