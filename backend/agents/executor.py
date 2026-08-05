"""Executor node: runs the validated SQL and handles approval + retries.

Executes the generated SQL via a :class:`DatabaseDialect`, enforces the row
cap, estimates cost when possible, and triggers the human-approval interrupt
for expensive queries. On failure it records the error so the graph can
regenerate SQL (up to the configured retry limit).
"""

from __future__ import annotations

from typing import Any

from langgraph.types import interrupt

from backend.cache.result_cache import ResultCache
from backend.core.logging import get_logger
from backend.database.optimizer import estimate_rows_scanned
from backend.interfaces.database import DatabaseDialect
from backend.models.schemas import ExecutionStats

logger = get_logger(__name__)


class ExecutorNode:
    """LangGraph node that executes validated SQL against the datasource."""

    def __init__(
        self,
        *,
        database: DatabaseDialect,
        max_rows: int = 500,
        timeout_seconds: int = 30,
        expensive_threshold: int = 1_000_000,
        require_approval: bool = False,
        cache: ResultCache | None = None,
    ):
        """Initialize the executor.

        Args:
            database: DatabaseDialect used to run the query.
            max_rows: Hard cap on returned rows.
            timeout_seconds: Statement execution timeout.
            expensive_threshold: Estimated rows scanned at which a query is
                considered expensive and requires approval.
            require_approval: Whether to actually pause for human approval.
            cache: Optional ResultCache for caching query results by SQL.
        """
        self._database = database
        self._max_rows = max_rows
        self._timeout = timeout_seconds
        self._expensive_threshold = expensive_threshold
        self._require_approval = require_approval
        self._cache = cache

    def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """Execute the current SQL statement.

        Args:
            state: Current graph state containing the validated SQL.

        Returns:
            State updates with columns, rows, stats, or an error entry.
        """
        sql = state.get("sql", "")
        dialect = self._database.dialect_name
        attempts = state.get("attempts", 0)
        plan = state.get("plan")

        # Try the result cache first (keyed on the validated SQL).
        if self._cache is not None and self._cache.enabled:
            cache_key = self._cache.cache_key(
                sql,
                datasource_id=self._database.datasource_id,
                max_rows=self._max_rows,
            )
            cached = self._cache.get(cache_key)
            if cached is not None:
                logger.info("cache_hit", key=cache_key)
                return {
                    "columns": cached.columns,
                    "rows": cached.rows,
                    "execution_stats": cached.execution_stats,
                    "needs_approval": False,
                    "approved": True,
                    "cached": True,
                }

        # Cost estimation to decide on approval.
        estimated = estimate_rows_scanned(self._database.engine, sql, dialect)  # type: ignore[attr-defined]
        needs_approval = False
        if self._require_approval and plan and getattr(plan, "needs_approval", False) or (
            self._require_approval
            and estimated is not None
            and estimated > self._expensive_threshold
        ):
            needs_approval = True

        if needs_approval and not state.get("approved", False):
            approved = interrupt({"type": "approval_required", "estimated_rows_scanned": estimated})
            if not approved:
                return {
                    "needs_approval": True,
                    "approved": False,
                    "error": "Query requires approval and was not approved.",
                }

        try:
            columns, rows, stats = self._database.execute_query(
                sql,
                max_rows=self._max_rows,
                timeout_seconds=self._timeout,
            )
        except Exception as exc:
            error_msg = str(exc)
            logger.warning("execution_failed", attempts=attempts, error=error_msg)
            return {
                "errors": [f"Execution error (attempt {attempts + 1}): {error_msg}"],
                "needs_approval": False,
            }

        if estimated is not None:
            stats = ExecutionStats(
                **stats.model_dump(),
                estimated_rows_scanned=estimated,
            )

        # Store the successful result in the cache for future identical queries.
        if self._cache is not None and self._cache.enabled:
            from backend.models.schemas import AgentResult

            cached_result = AgentResult(
                sql=sql,
                columns=columns,
                rows=rows,
                execution_stats=stats,
            )
            self._cache.put(cache_key, cached_result)

        logger.info("execution_succeeded", rows=len(rows), ms=stats.execution_time_ms)
        return {
            "columns": columns,
            "rows": rows,
            "execution_stats": stats,
            "needs_approval": False,
            "approved": True,
        }
