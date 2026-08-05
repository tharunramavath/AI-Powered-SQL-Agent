"""Query cost estimation and index suggestions.

Uses ``EXPLAIN`` where the dialect supports it to estimate rows scanned,
which powers the expensive-query approval workflow. Also provides simple
index suggestions based on filter/join columns used by a query.
"""

from __future__ import annotations

import re

from sqlalchemy import text
from sqlalchemy.engine import Engine

from backend.core.logging import get_logger

logger = get_logger(__name__)


def estimate_rows_scanned(engine: Engine, sql: str, dialect: str) -> int | None:
    """Estimate the number of rows a query would scan using EXPLAIN.

    Returns None when EXPLAIN is unsupported or fails (callers should then
    treat the query as "unknown cost").

    Args:
        engine: SQLAlchemy engine.
        sql: The SELECT statement to analyze.
        dialect: Canonical dialect name (postgresql/mysql/sqlite/...).

    Returns:
        An estimated row count, or None if unavailable.
    """
    if dialect not in {"postgresql", "mysql", "sqlite"}:
        return None
    try:
        explain_sql = f"EXPLAIN {sql}"
        with engine.connect() as conn:
            result = conn.execute(text(explain_sql))
            plan_lines = [str(row[0]) for row in result]
        return _parse_row_estimate("\n".join(plan_lines), dialect)
    except Exception as exc:
        logger.debug("explain_failed", error=str(exc))
        return None


def _parse_row_estimate(plan: str, dialect: str) -> int | None:
    """Parse a row-estimate out of an EXPLAIN plan text.

    Args:
        plan: The raw EXPLAIN output.
        dialect: Dialect name controlling the regex.

    Returns:
        An estimated row count, or None if nothing matched.
    """
    if dialect == "postgresql":
        match = re.search(r"rows=(\d+)", plan)
    elif dialect == "mysql":
        match = re.search(r"rows:\s*(\d+)", plan)
    elif dialect == "sqlite":
        match = re.search(r"SCAN TABLE\s+\w+(?:\s+\((\d+)\s+rows?\))?", plan)
    else:
        match = None
    if match:
        return int(match.group(1))
    return None


def suggest_indexes(sql: str, schema_tables: list) -> list[str]:
    """Suggest index candidates based on tables/columns referenced in the query.

    This is a lightweight heuristic: it collects column names used after
    ``WHERE``/``JOIN ... ON`` clauses and returns per-table suggestions. A
    production deployment would integrate real workload analysis.

    Args:
        sql: The generated SELECT statement.
        schema_tables: List of reflected TableInfo objects.

    Returns:
        List of human-readable index suggestions.
    """
    if not schema_tables:
        return []
    lowered = sql.lower()
    suggestions: list[str] = []
    for table in schema_tables:
        if table.name.lower() not in lowered:
            continue
        for col in table.columns:
            if not (col.is_primary_key or col.is_foreign_key):
                continue
            if (
                f"on {table.name.lower()}." in lowered
                or f"{table.name.lower()}.{col.name.lower()}" in lowered
            ):
                suggestions.append(
                    f"CREATE INDEX idx_{table.name}_{col.name} ON {table.qualified_name} ({col.name});"
                )
    return suggestions
