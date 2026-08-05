"""Database dialect interface.

Encapsulates everything needed to connect to and query a database using
SQLAlchemy, without exposing SQLAlchemy specifics to the rest of the system.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from backend.models.schemas import ExecutionStats, SchemaInfo


@runtime_checkable
class DatabaseDialect(Protocol):
    """Protocol for a queryable database backend."""

    datasource_id: str
    dialect_name: str

    def connect(self) -> None:
        """Establish a connection (creates/validates the engine)."""
        ...

    def close(self) -> None:
        """Dispose of pooled connections."""
        ...

    def test_connection(self) -> bool:
        """Return True if a live connection can be established."""
        ...

    def load_schema(self, max_rows_sample: int = 200) -> SchemaInfo:
        """Reflect tables, columns, keys, and indexes from the database.

        Args:
            max_rows_sample: Not used for reflection; reserved for future
                row-count estimation heuristics.

        Returns:
            A SchemaInfo describing the datasource.
        """
        ...

    def execute_query(
        self, sql: str, *, max_rows: int, timeout_seconds: int
    ) -> tuple[list[str], list[dict[str, Any]], ExecutionStats]:
        """Execute a read-only SELECT statement.

        Args:
            sql: The validated SELECT statement.
            max_rows: Hard cap on rows returned.
            timeout_seconds: Statement execution timeout.

        Returns:
            A (columns, rows, stats) tuple where rows are dicts keyed by column.
        """
        ...
