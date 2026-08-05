"""Read-only SQL execution with row caps and timing.

Executes validated SELECT statements against a SQLAlchemy engine, enforces a
hard row limit, measures execution time, and returns dict rows.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine

from backend.core.logging import get_logger
from backend.models.schemas import ExecutionStats

logger = get_logger(__name__)


def execute_read_only(
    engine: Engine,
    sql: str,
    *,
    max_rows: int,
    timeout_seconds: int,
) -> tuple[list[str], list[dict[str, Any]], ExecutionStats]:
    """Run a SELECT statement and return columns, rows, and stats.

    The statement is wrapped so that at most ``max_rows`` rows are fetched.
    The database connection is used read-only via a transaction; the engine's
    URL should belong to a database role with SELECT-only privileges for
    defense in depth.

    Args:
        engine: SQLAlchemy engine.
        sql: The SELECT statement to execute.
        max_rows: Hard cap on returned rows.
        timeout_seconds: Statement timeout.

    Returns:
        Tuple of (column names, rows, execution stats).

    Raises:
        RuntimeError: On database errors, with the DB error message attached.
    """
    start = time.perf_counter()
    try:
        with engine.connect() as conn:
            stmt = text(sql).execution_options(timeout=timeout_seconds)
            result = conn.execute(stmt)
            columns = list(result.keys())
            rows: list[dict[str, Any]] = []
            truncated = False
            for idx, row in enumerate(result.mappings()):
                if idx >= max_rows:
                    truncated = True
                    break
                rows.append(_sanitize_row(dict(row)))
    except Exception as exc:
        logger.warning("query_execution_failed", error=str(exc))
        raise RuntimeError(f"Query execution failed: {exc}") from exc

    elapsed_ms = (time.perf_counter() - start) * 1000.0
    stats = ExecutionStats(
        execution_time_ms=round(elapsed_ms, 2),
        rows_returned=len(rows),
        truncated=truncated,
    )
    return columns, rows, stats


def _sanitize_row(row: dict[str, Any]) -> dict[str, Any]:
    """Convert non-JSON-serializable values (dates, decimals, bytes) to JSON-safe types.

    Args:
        row: A raw row dict from the driver.

    Returns:
        A row dict whose values are JSON-serializable.
    """
    cleaned: dict[str, Any] = {}
    for key, value in row.items():
        if value is None:
            cleaned[key] = None
        elif isinstance(value, (str, int, float, bool)):
            cleaned[key] = value
        elif hasattr(value, "isoformat"):
            try:
                cleaned[key] = value.isoformat()
            except Exception:
                cleaned[key] = str(value)
        elif isinstance(value, (bytes, bytearray)):
            cleaned[key] = value.hex()
        else:
            cleaned[key] = str(value)
    return cleaned
