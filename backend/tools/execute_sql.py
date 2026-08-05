"""LangChain tool that executes read-only SQL.

Wraps a :class:`DatabaseDialect` as a :class:`StructuredTool` so a tool-calling
agent can run queries. Validation is applied before execution to preserve the
safety guarantees of the main pipeline.
"""

from __future__ import annotations

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from backend.agents.validator import SqlValidator
from backend.core.logging import get_logger
from backend.interfaces.database import DatabaseDialect
from backend.models.schemas import SchemaInfo

logger = get_logger(__name__)


class _SqlToolArgs(BaseModel):
    """Arguments accepted by the execute_sql tool."""

    sql: str = Field(..., description="The read-only SELECT SQL statement to run.")
    max_rows: int = Field(default=200, description="Maximum number of rows to return.")


def _build_run_fn(database: DatabaseDialect, schema: SchemaInfo, max_rows: int, timeout: int):
    """Create the tool's execution closure.

    Args:
        database: The database dialect to query.
        schema: Reflected schema used for validation.
        max_rows: Row cap.
        timeout: Statement timeout in seconds.

    Returns:
        A callable accepting (sql, max_rows).
    """

    def run(sql: str, max_rows: int = 200) -> str:
        """Validate and execute a read-only SQL statement.

        Args:
            sql: The SELECT statement.
            max_rows: Max rows to return (default 200).

        Returns:
            JSON-encoded rows and columns, or an error message.
        """
        validator = SqlValidator(schema=schema, dialect=database.dialect_name)
        result = validator.validate(sql)
        if not result.valid:
            return f"REJECTED: {', '.join(result.reasons)}"
        try:
            columns, rows, stats = database.execute_query(
                result.sql,
                max_rows=min(max(max_rows, 1), 1000),
                timeout_seconds=timeout,
            )
            import json

            return json.dumps(
                {"columns": columns, "rows": rows, "stats": stats.model_dump(mode="json")},
                default=str,
            )
        except Exception as exc:
            return f"ERROR: {exc}"

    return run


def ExecuteSqlTool(
    *,
    database: DatabaseDialect,
    schema: SchemaInfo,
    max_rows: int = 500,
    timeout_seconds: int = 30,
) -> StructuredTool:
    """Build the execute_sql LangChain tool.

    Args:
        database: The database dialect to query.
        schema: Reflected schema used for validation.
        max_rows: Default row cap.
        timeout_seconds: Statement timeout.

    Returns:
        A StructuredTool ready for use by a LangChain agent.
    """
    fn = _build_run_fn(database, schema, max_rows, timeout_seconds)
    return StructuredTool.from_function(
        func=fn,
        name="execute_sql",
        description="Execute a read-only SELECT query and return the result rows as JSON.",
        args_schema=_SqlToolArgs,
    )
