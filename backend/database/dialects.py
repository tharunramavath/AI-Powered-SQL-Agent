"""Dialect identification and registry for supported SQL databases.

Given a SQLAlchemy URL, determines the database flavor and returns the
matching dialect metadata. New databases can be added by extending the
``DIALECT_INFO`` mapping (and adding the corresponding DBAPI dependency).
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.engine import make_url


@dataclass(frozen=True)
class DialectInfo:
    """Static metadata describing a supported SQL dialect."""

    name: str
    scheme_prefix: str
    supports_explain: bool = False
    supports_cte: bool = True
    supports_window: bool = True
    # SQLGlot dialect name used for normalization/validation.
    sqlglot_dialect: str = ""


# Mapping of supported dialects. The key is the canonical name; the value
# holds the accepted URL scheme prefixes and SQLGlot dialect name.
DIALECT_INFO: dict[str, DialectInfo] = {
    "postgresql": DialectInfo(
        name="postgresql",
        scheme_prefix="postgresql",
        supports_explain=True,
        sqlglot_dialect="postgres",
    ),
    "mysql": DialectInfo(
        name="mysql",
        scheme_prefix="mysql",
        supports_explain=True,
        sqlglot_dialect="mysql",
    ),
    "mssql": DialectInfo(
        name="mssql",
        scheme_prefix="mssql",
        supports_explain=False,
        sqlglot_dialect="tsql",
    ),
    "sqlite": DialectInfo(
        name="sqlite",
        scheme_prefix="sqlite",
        supports_explain=True,
        sqlglot_dialect="sqlite",
    ),
    "snowflake": DialectInfo(
        name="snowflake",
        scheme_prefix="snowflake",
        supports_explain=True,
        sqlglot_dialect="snowflake",
    ),
    "bigquery": DialectInfo(
        name="bigquery",
        scheme_prefix="bigquery",
        supports_explain=False,
        sqlglot_dialect="bigquery",
    ),
}


def detect_dialect(url: str) -> DialectInfo | None:
    """Detect the dialect info from a SQLAlchemy connection URL.

    Args:
        url: SQLAlchemy URL string, e.g. "postgresql+psycopg://user:pass@host/db".

    Returns:
        The matching DialectInfo, or None if unsupported.
    """
    try:
        parsed = make_url(url)
    except Exception:
        return None
    scheme = (parsed.drivername or "").lower()
    for info in DIALECT_INFO.values():
        if scheme == info.scheme_prefix or scheme.startswith(info.scheme_prefix + "+"):
            return info
    return None


def normalize_sql_for_dialect(sql: str, sqlglot_dialect: str) -> str:
    """Normalize a SQL statement to the target dialect using SQLGlot.

    Used to adapt the LLM-generated SQL (usually PostgreSQL-ish) to the
    actual target database.

    Args:
        sql: The generated SQL.
        sqlglot_dialect: The SQLGlot dialect name for the target database.

    Returns:
        The normalized SQL string. Returns the input unchanged if the
        dialect is unknown to SQLGlot.
    """
    try:
        import sqlglot
        from sqlglot import transpile

        parsed = sqlglot.parse_one(sql, read="postgres")
        return transpile(str(parsed), read="postgres", write=sqlglot_dialect)[0]
    except Exception:
        return sql
