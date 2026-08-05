"""Shared pytest fixtures.

Provides an in-memory SQLite database populated with a small sales schema,
plus common objects (validator, cache, memory) used across test modules.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

from backend.cache.result_cache import ResultCache
from backend.database.connection import SqlAlchemyDialect
from backend.database.schema_loader import reflect_schema
from backend.interfaces.cache import CacheBackend
from backend.memory.context import ConversationMemory
from backend.models.datasource import DatasourceConfig
from backend.models.schemas import SchemaInfo
from backend.providers.caches.memory_cache import InMemoryCache
from backend.providers.memory.thread_store import InMemoryMemoryBackend

SCHEMA_SQL = """
CREATE TABLE products (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    price REAL
);
CREATE TABLE customers (
    id INTEGER PRIMARY KEY,
    name TEXT,
    country TEXT
);
CREATE TABLE orders (
    id INTEGER PRIMARY KEY,
    product_id INTEGER REFERENCES products(id),
    customer_id INTEGER REFERENCES customers(id),
    total_price REAL,
    order_date TEXT
);
INSERT INTO products VALUES (1, 'Laptop', 80000), (2, 'Mouse', 500), (3, 'Keyboard', 1200);
INSERT INTO customers VALUES (1, 'Alice', 'India'), (2, 'Bob', 'India'), (3, 'Carol', 'USA');
INSERT INTO orders VALUES
  (1, 1, 1, 420000, '2026-06-01'),
  (2, 2, 2, 65000, '2026-06-02'),
  (3, 1, 3, 180000, '2026-06-03'),
  (4, 3, 1, 36000, '2026-06-04'),
  (5, 2, 2, 7800, '2026-05-30');
"""


@pytest.fixture()
def sqlite_engine():
    """Create a fresh in-memory SQLite engine with sample data."""
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        for stmt in SCHEMA_SQL.split(";"):
            if stmt.strip():
                conn.execute(text(stmt))
    yield engine
    engine.dispose()


@pytest.fixture()
def dialect(sqlite_engine) -> SqlAlchemyDialect:
    """Return a SqlAlchemyDialect bound to the in-memory database."""
    config = DatasourceConfig(id="test", url="sqlite:///:memory:", dialect="sqlite")
    d = SqlAlchemyDialect(config)
    d._engine = sqlite_engine  # share the seeded engine
    return d


@pytest.fixture()
def schema(dialect: SqlAlchemyDialect) -> SchemaInfo:
    """Return the reflected schema of the test database."""
    return reflect_schema(dialect.engine, "test", "sqlite")


@pytest.fixture()
def memory_backend() -> InMemoryMemoryBackend:
    """Return a fresh in-memory memory backend."""
    return InMemoryMemoryBackend()


@pytest.fixture()
def conversation_memory(memory_backend) -> ConversationMemory:
    """Return a ConversationMemory facade over the in-memory backend."""
    return ConversationMemory(memory_backend)


@pytest.fixture()
def cache_backend() -> CacheBackend:
    """Return a fresh in-memory cache backend."""
    return InMemoryCache()


@pytest.fixture()
def result_cache(cache_backend) -> ResultCache:
    """Return a ResultCache facade over the in-memory backend."""
    return ResultCache(cache_backend, ttl_seconds=60)
