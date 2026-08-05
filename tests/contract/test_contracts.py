"""Contract tests: prove that every adapter satisfies its interface.

These tests ensure the abstraction boundaries hold: if a provider stops
honoring its Protocol, these tests fail before dependent packages break.
"""

from __future__ import annotations

from backend.interfaces.cache import CacheBackend
from backend.interfaces.memory import MemoryBackend
from backend.interfaces.vector import VectorDocument, VectorStore
from backend.providers.caches.memory_cache import InMemoryCache


class TestCacheContract:
    """InMemoryCache must satisfy CacheBackend behaviour."""

    def test_conforms(self, cache_backend: CacheBackend):
        assert isinstance(cache_backend, CacheBackend)
        key = "contract:k"
        cache_backend.set(key, {"v": 1})
        assert cache_backend.get(key) == {"v": 1}
        assert cache_backend.exists(key)
        cache_backend.delete(key)
        assert not cache_backend.exists(key)
        cache_backend.close()

    def test_swap_to_other_backend(self):
        # A different backend implementation must work identically.
        other = InMemoryCache()
        other.set("k", 7)
        assert other.get("k") == 7


class TestMemoryContract:
    """InMemoryMemoryBackend must satisfy MemoryBackend behaviour."""

    def test_conforms(self, memory_backend: MemoryBackend):
        assert isinstance(memory_backend, MemoryBackend)
        memory_backend.put("t", "fact", {"a": 1})
        assert memory_backend.get("t", "fact") == {"a": 1}
        memory_backend.add_history("t", "user", "hello")
        assert memory_backend.history("t")[-1]["content"] == "hello"
        memory_backend.clear("t")
        assert memory_backend.get("t", "fact") is None


class TestVectorContract:
    """A minimal in-memory VectorStore must satisfy VectorStore behaviour."""

    def test_contract_roundtrip(self):
        class DummyVectorStore(VectorStore):
            """Tiny test-only implementation of the VectorStore protocol."""

            def __init__(self):
                self._docs: list[VectorDocument] = []

            def add(self, documents: list[VectorDocument]) -> None:
                self._docs.extend(documents)

            def search(self, query: str, *, top_k: int = 5) -> list[VectorDocument]:
                return self._docs[:top_k]

            def count(self) -> int:
                return len(self._docs)

            def reset(self) -> None:
                self._docs.clear()

        store = DummyVectorStore()
        store.add([VectorDocument(id="1", text="products table")])
        assert store.count() == 1
        hits = store.search("products", top_k=1)
        assert hits and hits[0].id == "1"
        store.reset()
        assert store.count() == 0
