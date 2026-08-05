"""Unit tests for the database layer (schema reflection + execution)."""

from __future__ import annotations

import pytest

from backend.database.dialects import detect_dialect, normalize_sql_for_dialect
from backend.database.executor import execute_read_only
from backend.database.optimizer import estimate_rows_scanned
from backend.database.schema_loader import reflect_schema


class TestDialectDetection:
    """URL scheme detection must identify each supported database."""

    @pytest.mark.parametrize(
        ("url", "expected"),
        [
            ("postgresql+psycopg://u:p@h:5432/db", "postgresql"),
            ("mysql+pymysql://u:p@h:3306/db", "mysql"),
            ("mssql+pyodbc://u:p@h/db", "mssql"),
            ("sqlite:///data.db", "sqlite"),
            ("snowflake://u:p@account/db", "snowflake"),
            ("bigquery://project/dataset", "bigquery"),
            ("oracle://u:p@h/db", None),
        ],
    )
    def test_detect(self, url: str, expected):
        info = detect_dialect(url)
        if expected is None:
            assert info is None
        else:
            assert info is not None
            assert info.name == expected


class TestNormalization:
    """SQLGlot normalization should preserve semantics."""

    def test_postgres_to_sqlite(self):
        sql = "SELECT name FROM products LIMIT 5"
        out = normalize_sql_for_dialect(sql, "sqlite")
        assert "SELECT" in out.upper()

    def test_unknown_dialect_returns_input(self):
        sql = "SELECT 1"
        assert normalize_sql_for_dialect(sql, "nope") == sql


class TestSchemaReflection:
    """Schema reflection must expose tables, columns, and keys."""

    def test_reflects_tables(self, sqlite_engine):
        schema = reflect_schema(sqlite_engine, "test", "sqlite")
        names = {t.name for t in schema.tables}
        assert {"products", "orders", "customers"} <= names

    def test_reflects_columns_and_primary_keys(self, sqlite_engine):
        schema = reflect_schema(sqlite_engine, "test", "sqlite")
        products = next(t for t in schema.tables if t.name == "products")
        names = {c.name for c in products.columns}
        assert "id" in names and "name" in names
        pk = next(c for c in products.columns if c.name == "id")
        assert pk.is_primary_key is True

    def test_reflects_foreign_keys(self, sqlite_engine):
        schema = reflect_schema(sqlite_engine, "test", "sqlite")
        orders = next(t for t in schema.tables if t.name == "orders")
        fk_cols = [c for c in orders.columns if c.is_foreign_key]
        assert any(c.references == "products" for c in fk_cols)


class TestExecution:
    """Read-only execution must return rows and enforce row caps."""

    def test_returns_rows(self, sqlite_engine):
        columns, rows, stats = execute_read_only(
            sqlite_engine, "SELECT name FROM products", max_rows=100, timeout_seconds=10
        )
        assert columns == ["name"]
        assert len(rows) == 3
        assert stats.rows_returned == 3
        assert stats.execution_time_ms >= 0

    def test_row_cap_enforced(self, sqlite_engine):
        _, rows, stats = execute_read_only(
            sqlite_engine, "SELECT * FROM orders", max_rows=2, timeout_seconds=10
        )
        assert len(rows) == 2
        assert stats.truncated is True

    def test_execution_error_raises(self, sqlite_engine):
        with pytest.raises(RuntimeError):
            execute_read_only(
                sqlite_engine, "SELECT * FROM missing", max_rows=10, timeout_seconds=10
            )


class TestOptimizer:
    """EXPLAIN-based cost estimation."""

    def test_estimate_on_sqlite(self, sqlite_engine):
        estimate = estimate_rows_scanned(sqlite_engine, "SELECT * FROM products", "sqlite")
        # SQLite EXPLAIN output may not always yield a row estimate.
        assert estimate is None or estimate >= 0

    def test_unsupported_dialect_returns_none(self, sqlite_engine):
        assert estimate_rows_scanned(sqlite_engine, "SELECT 1", "snowflake") is None
