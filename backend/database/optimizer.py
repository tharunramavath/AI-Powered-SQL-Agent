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
        if dialect == "sqlite":
            return _estimate_sqlite_scan(engine, sql)

        with engine.connect() as conn:
            result = conn.execute(text(f"EXPLAIN {sql}"))
            key_names = result.keys()
            column_names = [k.lower() for k in key_names]
            rows = list(result.fetchall())
        if dialect == "mysql":
            # MySQL EXPLAIN carries the per-row estimate in the `rows`
            # column (tab-9), not the `id` column (tab-0).
            try:
                idx = column_names.index("rows")
            except ValueError:
                logger.debug("mysql_explain_missing_rows", keys=column_names)
                return None
            estimates = []
            for row in rows:
                value = row[idx]
                if value is not None:
                    try:
                        estimates.append(int(value))
                    except (TypeError, ValueError):
                        continue
            return max(estimates) if estimates else None
        # postgresql: plan text lives in the single QUERY PLAN column.
        return _parse_row_estimate("\n".join(str(row[0]) for row in rows), dialect)
    except Exception as exc:
        logger.debug("explain_failed", error=str(exc))
        return None


def _estimate_sqlite_scan(engine: Engine, sql: str) -> int | None:
    """Estimate rows scanned for SQLite via ``EXPLAIN QUERY PLAN``.

    SQLite plans do not embed row counts, so we resolve every table that is
    full-scanned (``SCAN`` without an index) and return the largest live row
    count. Returns None when nothing can be estimated.

    Args:
        engine: SQLAlchemy engine.
        sql: The SELECT statement to analyze.

    Returns:
        An estimated row count, or None if unavailable.
    """
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(f"EXPLAIN QUERY PLAN {sql}")).fetchall()
    except Exception as exc:
        logger.debug("sqlite_explain_plan_failed", error=str(exc))
        return None
    if not rows:
        return None

    scanned = [str(row[3]) for row in rows]
    if not any(re.search(r"^\s*SCAN\s+\S+", line) for line in scanned):
        return None  # no full-table scans to cost

    alias_map, table_names = _resolve_tables(sql)
    counts = []
    for line in scanned:
        match = re.search(r"^\s*SCAN\s+(\S+)", line)
        if not match:
            continue
        token = match.group(1).strip('"')
        table = alias_map.get(token.lower())
        if not table:
            # Schema-qualified in the plan (e.g. "main.products").
            table = token.split(".")[-1]
        if table.lower() not in table_names:
            continue
        try:
            with engine.connect() as conn:
                count = conn.execute(
                    text(f'SELECT COUNT(*) FROM "{table}"')
                ).scalar_one()
            counts.append(int(count))
        except Exception:
            continue
    return max(counts) if counts else None


def _resolve_tables(sql: str) -> tuple[dict[str, str], set[str]]:
    """Map SQL aliases to real table names for EXPLAIN-plan resolution.

    Args:
        sql: The SELECT statement.

    Returns:
        Tuple of (alias -> table name, set of lowercased table names).
    """
    try:
        import sqlglot

        expression = sqlglot.parse_one(sql, read="sqlite")
    except Exception:
        return {}, set()
    alias_map: dict[str, str] = {}
    table_names: set[str] = set()
    for table in expression.find_all(sqlglot.exp.Table):
        name = table.name
        if not name:
            continue
        table_names.add(name.lower())
        alias = getattr(table, "alias", None)
        if alias and alias.lower() != name.lower():
            alias_map[alias.lower()] = name
    return alias_map, table_names


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
