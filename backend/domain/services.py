"""Domain service layer: application use-cases independent of transport.

The QueryService is the single entry point that the API (or a CLI, or a
worker) uses to answer a question. It handles datasource resolution, approval
resumption, telemetry counters, and converting graph results to responses.
"""

from __future__ import annotations

from typing import Any

from backend.agents.state import initial_state
from backend.core.container import Container
from backend.core.logging import get_logger
from backend.core.telemetry import get_metrics
from backend.models.schemas import AgentResult, QueryRequest

logger = get_logger(__name__)


class QueryService:
    """Application service for executing natural-language SQL queries."""

    def __init__(self, container: Container):
        """Initialize the service with a dependency container.

        Args:
            container: The wired application container.
        """
        self._container = container

    def list_datasources(self) -> list[dict[str, Any]]:
        """Return safe summaries of the registered datasources.

        Returns:
            List of datasource metadata dicts.
        """
        return self._container.datasource_summaries()

    def run(self, request: QueryRequest) -> AgentResult:
        """Execute a query end-to-end and return the structured result.

        Args:
            request: The validated query request.

        Returns:
            An AgentResult containing SQL, rows, charts, summary, and stats.
        """
        agent = self._container.get_agent(request.datasource_id)
        state = initial_state(
            query=request.query,
            datasource_id=request.datasource_id,
            thread_id=request.thread_id or "",
        )
        config = self._build_config(request)

        metrics = get_metrics()
        metrics.active_requests.inc()
        try:
            with metrics.query_duration.labels(stage="total").time():
                result = agent.invoke(state, config=config)
        finally:
            metrics.active_requests.dec()

        self._record_outcome(request.datasource_id, result)
        if result is not None and result.execution_stats is not None:
            metrics.query_duration.labels(stage="execution").observe(
                result.execution_stats.execution_time_ms / 1000.0
            )
        return result

    def resume(self, *, thread_id: str, datasource_id: str, approved: bool) -> AgentResult:
        """Resume an interrupted run after a human approval decision.

        Args:
            thread_id: The thread used for the original run.
            datasource_id: The datasource of the original run.
            approved: Whether the human approved the expensive query.

        Returns:
            The final AgentResult.
        """
        agent = self._container.get_agent(datasource_id)
        config = {"configurable": {"thread_id": thread_id}}
        return agent.resume(config=config, resume_value=approved)

    async def stream(self, request: QueryRequest):
        """Stream agent state snapshots as an async iterator.

        Args:
            request: The query request.

        Yields:
            Each graph state snapshot (dict) as it becomes available.
        """
        from backend.agents.state import initial_state

        agent = self._container.get_agent(request.datasource_id)
        state = initial_state(
            query=request.query,
            datasource_id=request.datasource_id,
            thread_id=request.thread_id or "",
        )
        config = {"configurable": {"thread_id": request.thread_id}} if request.thread_id else {}
        async for snapshot in agent.graph.astream(state, config=config, stream_mode="values"):
            yield snapshot

    # -- helpers ---------------------------------------------------------

    @staticmethod
    def _build_config(request: QueryRequest) -> dict[str, Any]:
        """Build the LangGraph runtime config from the request.

        Args:
            request: The query request.

        Returns:
            A LangGraph config dict.
        """
        config: dict[str, Any] = {}
        if request.thread_id:
            config["configurable"] = {"thread_id": request.thread_id}
        return config

    def _record_outcome(self, datasource_id: str, result: AgentResult) -> None:
        """Update Prometheus counters based on the run outcome.

        Args:
            datasource_id: Datasource the query ran against.
            result: The agent result.
        """
        outcome = "error" if result.error else "success"
        get_metrics().queries_total.labels(datasource=datasource_id, outcome=outcome).inc()
        if result.error:
            logger.warning("query_failed", datasource=datasource_id, error=result.error)
