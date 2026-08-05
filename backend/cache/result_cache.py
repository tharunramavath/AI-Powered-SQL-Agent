"""Query result cache service.

Caches query results keyed by the normalized SQL plus the datasource id and
row limit. Normalization is applied via SQLGlot so that cosmetic variations
in the generated SQL map to the same cache entry.
"""

from __future__ import annotations

import hashlib
import json

from backend.interfaces.cache import CacheBackend
from backend.models.schemas import AgentResult


class ResultCache:
    """Facade over a CacheBackend for storing full AgentResult objects."""

    def __init__(self, backend: CacheBackend | None, *, ttl_seconds: int = 300):
        """Initialize the result cache.

        Args:
            backend: The underlying cache backend, or None to disable caching.
            ttl_seconds: Default TTL for cached results.
        """
        self._backend = backend
        self._ttl = ttl_seconds

    @property
    def enabled(self) -> bool:
        """Return True if caching is active."""
        return self._backend is not None

    @staticmethod
    def normalize_sql(sql: str, dialect: str = "postgres") -> str:
        """Normalize SQL to a canonical form for cache keying.

        Args:
            sql: The generated SQL.
            dialect: Dialect used for parsing/normalization.

        Returns:
            Canonicalized SQL string.
        """
        try:
            import sqlglot

            parsed = sqlglot.parse_one(sql, read=dialect)
            return parsed.sql(dialect=dialect, pretty=False)
        except Exception:
            return " ".join(sql.split())

    def cache_key(self, sql: str, *, datasource_id: str, max_rows: int, thread_id: str = "") -> str:
        """Compute a stable cache key for a query.

        Args:
            sql: The generated SQL.
            datasource_id: Datasource the query runs against.
            max_rows: Row limit applied.
            thread_id: Optional thread id (excluded to share across threads).

        Returns:
            A sha256-based cache key string.
        """
        normalized = self.normalize_sql(sql)
        payload = json.dumps(
            {"sql": normalized, "datasource_id": datasource_id, "max_rows": max_rows},
            sort_keys=True,
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return f"result:{digest}"

    def get(self, key: str) -> AgentResult | None:
        """Retrieve a cached AgentResult by key.

        Args:
            key: Cache key from :meth:`cache_key`.

        Returns:
            The cached result, or None on miss.
        """
        if self._backend is None:
            return None
        raw = self._backend.get(key)
        if raw is None:
            return None
        try:
            return AgentResult.model_validate(raw)
        except Exception:
            return None

    def put(self, key: str, result: AgentResult, *, ttl_seconds: int | None = None) -> None:
        """Store an AgentResult under a key.

        Args:
            key: Cache key.
            result: The result to cache.
            ttl_seconds: Optional TTL override; defaults to instance TTL.
        """
        if self._backend is None:
            return
        payload = result.model_dump(mode="json")
        payload["cached"] = False  # cached flag is set on retrieval, not storage
        self._backend.set(key, payload, ttl_seconds=ttl_seconds or self._ttl)
