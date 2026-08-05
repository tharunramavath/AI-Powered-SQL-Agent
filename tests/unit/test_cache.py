"""Unit tests for the result cache and cache backends."""

from __future__ import annotations

from backend.cache.result_cache import ResultCache
from backend.models.schemas import AgentResult, ExecutionStats
from backend.providers.caches.memory_cache import InMemoryCache


class TestInMemoryCache:
    """In-memory cache backend behaviour."""

    def test_set_get_roundtrip(self):
        cache = InMemoryCache()
        cache.set("k", {"a": 1})
        assert cache.get("k") == {"a": 1}

    def test_ttl_expiry(self):
        cache = InMemoryCache()
        cache.set("k", 42, ttl_seconds=0)
        assert cache.get("k") is None

    def test_delete_and_exists(self):
        cache = InMemoryCache()
        cache.set("k", 1)
        assert cache.exists("k")
        cache.delete("k")
        assert not cache.exists("k")


class TestResultCache:
    """ResultCache facade behaviour."""

    def test_cache_key_is_stable_and_sensitive_to_sql(self, result_cache):
        key1 = result_cache.cache_key("SELECT * FROM products", datasource_id="x", max_rows=100)
        key2 = result_cache.cache_key("SELECT * FROM products", datasource_id="x", max_rows=100)
        key3 = result_cache.cache_key("SELECT * FROM orders", datasource_id="x", max_rows=100)
        assert key1 == key2
        assert key1 != key3

    def test_normalization_makes_cosmetic_variants_equal(self, result_cache):
        a = result_cache.cache_key("SELECT name FROM products", datasource_id="x", max_rows=100)
        b = result_cache.cache_key("select name from products", datasource_id="x", max_rows=100)
        assert a == b

    def test_put_and_get_roundtrip(self, result_cache):
        result = AgentResult(
            sql="SELECT * FROM products",
            columns=["name"],
            rows=[{"name": "Laptop"}],
            execution_stats=ExecutionStats(execution_time_ms=1.5, rows_returned=1),
        )
        key = result_cache.cache_key(result.sql, datasource_id="x", max_rows=100)
        result_cache.put(key, result)
        cached = result_cache.get(key)
        assert cached is not None
        assert cached.rows == [{"name": "Laptop"}]

    def test_missing_key_returns_none(self, result_cache):
        assert result_cache.get("missing") is None

    def test_disabled_cache_returns_none(self, cache_backend):
        result_cache = ResultCache(None)
        assert result_cache.get("any") is None
        result_cache.put("any", AgentResult(sql="SELECT 1"))
        assert result_cache.get("any") is None
