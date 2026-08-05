"""SQLAlchemy-based database connection management.

Implements the :class:`DatabaseDialect` protocol using SQLAlchemy engines,
supporting all configured dialects (PostgreSQL, MySQL, SQL Server, SQLite,
Snowflake, BigQuery). Engines are pooled, lazily created, and cached per
datasource id so multiple queries reuse the same pool.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from backend.core.logging import get_logger
from backend.database.dialects import DialectInfo, detect_dialect
from backend.models.datasource import DatasourceConfig
from backend.models.schemas import ExecutionStats, SchemaInfo

logger = get_logger(__name__)


class SqlAlchemyDialect:
    """A DatabaseDialect implementation backed by SQLAlchemy engines."""

    def __init__(self, config: DatasourceConfig):
        """Initialize the dialect from a datasource configuration.

        Args:
            config: Datasource config containing the connection URL.
        """
        self.config = config
        self.datasource_id = config.id
        self._info: DialectInfo | None = detect_dialect(config.url)
        if config.dialect:
            self.dialect_name = config.dialect
        elif self._info is not None:
            self.dialect_name = self._info.name
        else:
            self.dialect_name = "unknown"
        self._engine: Engine | None = None

    @property
    def engine(self) -> Engine:
        """Return the lazily created SQLAlchemy engine (creates it on demand)."""
        if self._engine is None:
            self._engine = create_engine(
                self.config.url,
                pool_pre_ping=True,
                pool_recycle=1800,
                pool_size=5,
                max_overflow=10,
                echo=False,
            )
        return self._engine

    # -- lifecycle -------------------------------------------------------

    def connect(self) -> None:
        """Establish a connection and validate it works."""
        _ = self.engine
        if not self.test_connection():
            raise ConnectionError(f"Could not connect to datasource '{self.datasource_id}'")

    def close(self) -> None:
        """Dispose of pooled connections."""
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None

    def test_connection(self) -> bool:
        """Attempt a live connection to verify the URL is reachable."""
        try:
            with self.engine.connect() as conn:
                conn.exec_driver_sql("SELECT 1")
            return True
        except Exception as exc:
            logger.warning("connection_test_failed", datasource=self.datasource_id, error=str(exc))
            return False

    # -- schema discovery ------------------------------------------------

    def load_schema(self, max_rows_sample: int = 200) -> SchemaInfo:
        """Reflect tables, columns, keys, and indexes via SQLAlchemy inspection.

        Args:
            max_rows_sample: Reserved for future row-count estimation.

        Returns:
            A SchemaInfo describing all public tables in the datasource.
        """
        from backend.database.schema_loader import reflect_schema

        return reflect_schema(self.engine, self.datasource_id, self.dialect_name)

    # -- query execution -------------------------------------------------

    def execute_query(
        self,
        sql: str,
        *,
        max_rows: int,
        timeout_seconds: int,
    ) -> tuple[list[str], list[dict[str, Any]], ExecutionStats]:
        """Execute a read-only SELECT and return columns, rows, and stats.

        Rows are returned as dicts keyed by column name and are hard-capped
        at ``max_rows`` with a truncation flag in the returned stats.

        Args:
            sql: The validated SELECT statement to run.
            max_rows: Maximum number of rows to return.
            timeout_seconds: Statement execution timeout.

        Returns:
            Tuple of (column names, rows, execution stats).

        Raises:
            RuntimeError: On query failure with the underlying error message.
        """
        from backend.database.executor import execute_read_only

        return execute_read_only(
            self.engine,
            sql,
            max_rows=max_rows,
            timeout_seconds=timeout_seconds,
        )
