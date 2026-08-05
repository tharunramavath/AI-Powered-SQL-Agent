"""Database layer exports.

This package is fully reusable: it depends only on the interface contracts
and DTOs, never on the web framework or the agent orchestration layer.
"""

from backend.database.connection import SqlAlchemyDialect
from backend.database.dialects import (
    DIALECT_INFO,
    DialectInfo,
    detect_dialect,
    normalize_sql_for_dialect,
)
from backend.database.executor import execute_read_only
from backend.database.optimizer import estimate_rows_scanned, suggest_indexes
from backend.database.schema_loader import reflect_schema

__all__ = [
    "DIALECT_INFO",
    "DialectInfo",
    "SqlAlchemyDialect",
    "detect_dialect",
    "estimate_rows_scanned",
    "execute_read_only",
    "normalize_sql_for_dialect",
    "reflect_schema",
    "suggest_indexes",
]
