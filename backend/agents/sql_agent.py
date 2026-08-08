"""SQL Agent: the LangGraph workflow orchestrating the whole pipeline.

Builds the graph:

    START -> load_schema -> understand -> generate_sql -> validate
             (validate invalid & attempts left) ------------> generate_sql
             (validate invalid & no attempts) ---------------> fail
             (validate ok) ----------------------------------> execute
             (execute error & attempts left) -----------------> generate_sql
             (execute error & no attempts) -------------------> fail
             (execute ok) ------------------------------------> analyze
             analyze -> generate_response -> finalize -> END

Nodes are plain classes with injected dependencies, so the graph is a thin,
swappable shell. A checkpointer is required for the human-approval interrupt;
MemorySaver is used by default and a Postgres checkpointer can be supplied.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from langgraph.graph import END, START, StateGraph

from backend.agents.chart import HeuristicChartRecommender
from backend.agents.executor import ExecutorNode
from backend.agents.formatter import FormatterNode
from backend.agents.guardrails import InputGuardrailNode, OutputGuardrailNode
from backend.agents.planner import PlannerNode
from backend.agents.schema_loader import SchemaLoaderNode
from backend.agents.sql_generator import SqlGeneratorNode
from backend.agents.state import AgentState
from backend.agents.validator import SqlValidator
from backend.cache.result_cache import ResultCache
from backend.core.logging import get_logger
from backend.core.observability import TracingService, get_tracer
from backend.interfaces.database import DatabaseDialect
from backend.interfaces.llm import LLMProvider
from backend.memory.context import ConversationMemory
from backend.models.schemas import AgentResult, ExecutionStats
from backend.vector.schema_indexer import SchemaIndexer

logger = get_logger(__name__)


class SQLAgent:
    """A compiled LangGraph agent answering natural-language SQL questions."""

    def __init__(
        self,
        *,
        llm: LLMProvider,
        database: DatabaseDialect,
        memory: ConversationMemory | None = None,
        indexer: SchemaIndexer | None = None,
        metrics: list[Any] | None = None,
        glossary: dict[str, str] | None = None,
        max_rows: int = 500,
        timeout_seconds: int = 30,
        expensive_threshold: int = 1_000_000,
        require_approval: bool = False,
        max_sql_retries: int = 3,
        cache: ResultCache | None = None,
        checkpointer: Any = None,
        tracer: TracingService | None = None,
        input_guardrails_enabled: bool = True,
        output_guardrails_enabled: bool = True,
        pii_block: bool = False,
    ):
        """Initialize and compile the agent graph.

        Args:
            llm: The LLM provider.
            database: The DatabaseDialect to query.
            memory: Optional conversation memory.
            indexer: Optional vector schema indexer.
            metrics: Semantic-layer metrics.
            glossary: Semantic-layer glossary.
            max_rows: Hard cap on result rows.
            timeout_seconds: Statement timeout.
            expensive_threshold: Rows-scanned threshold for approval.
            require_approval: Whether expensive queries pause for approval.
            max_sql_retries: Max SQL regeneration attempts.
            cache: Optional ResultCache for SQL-level caching.
            checkpointer: LangGraph checkpointer. Defaults to an in-memory
                saver so that the approval interrupt works out of the box.
            tracer: Optional LangFuse TracingService. When provided, each
                run is recorded as a trace (falls back to the global tracer).
            input_guardrails_enabled: When True, run the input-safety gate.
            output_guardrails_enabled: When True, verify summary faithfulness.
            pii_block: When True, block PII/sensitive-data requests.
        """
        self._llm = llm
        self._database = database
        self._memory = memory
        self._max_rows = max_rows
        self._max_sql_retries = max_sql_retries
        self._metrics = metrics or []
        self._glossary = glossary or {}
        self._tracer = tracer

        recommender = HeuristicChartRecommender()
        guardrails_in = InputGuardrailNode(
            llm=llm,
            enabled=input_guardrails_enabled,
            pii_block=pii_block,
        )
        guardrails_out = OutputGuardrailNode(
            llm=llm,
            enabled=output_guardrails_enabled,
        )
        planner = PlannerNode(llm=llm, memory=memory)
        generator = SqlGeneratorNode(llm=llm, max_rows=max_rows)
        executor = ExecutorNode(
            database=database,
            max_rows=max_rows,
            timeout_seconds=timeout_seconds,
            expensive_threshold=expensive_threshold,
            require_approval=require_approval,
            cache=cache,
        )
        formatter = FormatterNode(llm=llm, memory=memory)
        loader = SchemaLoaderNode(
            database=database,
            indexer=indexer,
            metrics=self._metrics,
            glossary=self._glossary,
        )

        # Inline node functions for validation, analysis, and finalization.
        def _validate(state: dict[str, Any]) -> dict[str, Any]:
            """Validate the generated SQL (attempts increment on generation)."""
            schema = state.get("schema")
            dialect = schema.dialect if schema else "postgres"
            validator = SqlValidator(schema=schema, dialect=dialect)  # type: ignore[arg-type]
            result = validator.validate(state.get("sql", ""))
            update: dict[str, Any] = {"validation": result}
            if not result.valid:
                update["errors"] = ["Validation failed: " + "; ".join(result.reasons)]
            else:
                # Execute the extracted/normalized statement (not the raw LLM
                # output) so fenced SQL and dialect quirks are handled here.
                update["sql"] = result.sql
            return update

        def _analyze(state: dict[str, Any]) -> dict[str, Any]:
            """Recommend charts for the executed results."""
            charts = recommender.recommend(
                state.get("columns", []),
                state.get("rows", []),
                question=state.get("query", ""),
            )
            return {"charts": charts}

        def _finalize(state: dict[str, Any]) -> dict[str, Any]:
            """Assemble the final AgentResult from the pipeline products."""
            stats: ExecutionStats = state.get("execution_stats") or ExecutionStats()
            result = AgentResult(
                sql=state.get("sql", ""),
                plan=state.get("plan"),
                columns=state.get("columns", []),
                rows=state.get("rows", []),
                charts=state.get("charts", []),
                summary=state.get("summary", ""),
                execution_stats=stats,
                retries=max(0, state.get("attempts", 0) - 1),
                cached=bool(state.get("cached", False)),
                needs_approval=bool(state.get("needs_approval", False)),
                approval_required=False,
                error=None,
                data_truncated=stats.truncated,
            )
            return {"result": result}

        def _fail(state: dict[str, Any]) -> dict[str, Any]:
            """Produce a graceful error result when retries are exhausted."""
            if state.get("guardrail_blocked"):
                message = f"Request blocked by guardrails: {state.get('guardrail_reason', 'unsafe input')}"
            else:
                errors = state.get("errors", [])
                message = errors[-1] if errors else "Unknown agent failure."
            result = AgentResult(
                sql=state.get("sql", ""),
                plan=state.get("plan"),
                error=message,
                retries=state.get("attempts", 0),
                needs_approval=bool(state.get("needs_approval", False)),
            )
            return {"result": result}

        self._validate_fn: Callable[[dict], dict] = _validate
        self._analyze_fn = _analyze
        self._finalize_fn = _finalize
        self._fail_fn = _fail

        # -- graph construction ------------------------------------------
        builder = StateGraph(AgentState)
        builder.add_node("guardrails_in", guardrails_in)
        builder.add_node("load_schema", loader)
        builder.add_node("understand", planner)
        builder.add_node("generate_sql", generator)
        builder.add_node("validate", _validate)
        builder.add_node("execute", executor)
        builder.add_node("analyze", _analyze)
        builder.add_node("generate_response", formatter)
        builder.add_node("guardrails_out", guardrails_out)
        builder.add_node("finalize", _finalize)
        builder.add_node("fail", _fail)

        builder.add_edge(START, "guardrails_in")
        builder.add_conditional_edges(
            "guardrails_in",
            self._route_after_input_guardrail,
            {"load_schema": "load_schema", "fail": "fail"},
        )
        builder.add_edge("load_schema", "understand")
        builder.add_edge("understand", "generate_sql")
        builder.add_edge("generate_sql", "validate")
        builder.add_conditional_edges(
            "validate",
            self._route_after_validate,
            {"execute": "execute", "generate_sql": "generate_sql", "fail": "fail"},
        )
        builder.add_conditional_edges(
            "execute",
            self._route_after_execute,
            {"analyze": "analyze", "generate_sql": "generate_sql", "fail": "fail", END: END},
        )
        builder.add_edge("analyze", "generate_response")
        builder.add_edge("generate_response", "guardrails_out")
        builder.add_edge("guardrails_out", "finalize")
        builder.add_edge("finalize", END)
        builder.add_edge("fail", END)

        if checkpointer is None:
            from langgraph.checkpoint.memory import MemorySaver

            checkpointer = MemorySaver()
        self._checkpointer = checkpointer
        self.graph = builder.compile(checkpointer=checkpointer)

    # -- routing ---------------------------------------------------------

    def _route_after_input_guardrail(self, state: dict[str, Any]) -> str:
        """Decide the next node after the input-safety gate.

        Args:
            state: Current state.

        Returns:
            "load_schema" when safe, or "fail" when the input was blocked.
        """
        if state.get("guardrail_blocked"):
            return "fail"
        return "load_schema"

    def _route_after_validate(self, state: dict[str, Any]) -> str:
        """Decide the next node after validation.

        Args:
            state: Current state.

        Returns:
            "execute" if valid, "generate_sql" to retry, or "fail".
        """
        validation = state.get("validation")
        if validation is not None and getattr(validation, "valid", False):
            return "execute"
        # `attempts` counts generations so far; allow up to max_sql_retries
        # retries after the first generation.
        if state.get("attempts", 0) <= self._max_sql_retries:
            return "generate_sql"
        return "fail"

    def _route_after_execute(self, state: dict[str, Any]) -> str:
        """Decide the next node after execution.

        Args:
            state: Current state.

        Returns:
            "analyze" on success, END when approval is pending,
            "generate_sql" to retry, or "fail".
        """
        if state.get("needs_approval"):
            return END
        if state.get("columns"):
            return "analyze"
        if state.get("attempts", 0) <= self._max_sql_retries:
            return "generate_sql"
        return "fail"

    # -- public interface ------------------------------------------------

    def invoke(
        self,
        state: Mapping[str, Any],
        *,
        config: dict[str, Any] | None = None,
    ) -> AgentResult:
        """Run the agent once and return the structured result.

        Args:
            state: Initial graph state (see :func:`initial_state`).
            config: Optional LangGraph config (thread_id, recursion_limit, ...).

        Returns:
            The final AgentResult.
        """
        config = self._ensure_thread_id(config)
        tracer = self._tracer or get_tracer()
        trace = tracer.start_trace(
            name="sql-agent-run",
            input=state.get("query", ""),
            session_id=str(config.get("configurable", {}).get("thread_id", "")),
            metadata={
                "datasource_id": state.get("datasource_id", ""),
                "env": state.get("env", ""),
            },
            release=None,
        )
        with tracer.trace_context(trace):
            result_state = self.graph.invoke(dict(state), config=config)
        result = result_state.get("result") or AgentResult(
            error="Agent finished without producing a result."
        )
        tracer.update_trace(
            trace,
            output=_result_summary(result),
            metadata=_trace_metadata(result),
            status="success" if result.error is None else "error",
            level="DEFAULT" if result.error is None else "ERROR",
        )
        tracer.end_trace(trace)
        return result

    def stream(self, state: Mapping[str, Any], *, config: dict[str, Any] | None = None):
        """Run the agent and stream state updates.

        Args:
            state: Initial graph state.
            config: Optional LangGraph config.

        Returns:
            An iterator of streamed graph events.
        """
        config = self._ensure_thread_id(config)
        return self._stream_traced(state, config)

    def _stream_traced(self, state: Mapping[str, Any], config: dict[str, Any]):
        """Generator that streams snapshots while recording a LangFuse trace."""
        tracer = self._tracer or get_tracer()
        trace = tracer.start_trace(
            name="sql-agent-run",
            input=state.get("query", ""),
            session_id=str(config.get("configurable", {}).get("thread_id", "")),
            metadata={"datasource_id": state.get("datasource_id", "")},
            release=None,
        )
        last_result: AgentResult | None = None
        with tracer.trace_context(trace):
            for snapshot in self.graph.stream(dict(state), config=config, stream_mode="values"):
                if snapshot.get("result") is not None:
                    last_result = snapshot["result"]
                yield snapshot
        self._finish_stream_trace(tracer, trace, last_result)

    async def astream(self, state: Mapping[str, Any], *, config: dict[str, Any] | None = None):
        """Run the agent and asynchronously stream state updates (traced).

        Args:
            state: Initial graph state.
            config: Optional LangGraph config.

        Yields:
            Each graph state snapshot (dict) as it becomes available.
        """
        config = self._ensure_thread_id(config)
        tracer = self._tracer or get_tracer()
        trace = tracer.start_trace(
            name="sql-agent-run",
            input=state.get("query", ""),
            session_id=str(config.get("configurable", {}).get("thread_id", "")),
            metadata={"datasource_id": state.get("datasource_id", "")},
            release=None,
        )
        last_result: AgentResult | None = None
        with tracer.trace_context(trace):
            async for snapshot in self.graph.astream(
                dict(state), config=config, stream_mode="values"
            ):
                if snapshot.get("result") is not None:
                    last_result = snapshot["result"]
                yield snapshot
        self._finish_stream_trace(tracer, trace, last_result)

    @staticmethod
    def _finish_stream_trace(tracer, trace, last_result: AgentResult | None) -> None:
        """Close a streamed LangFuse trace with the last seen result."""
        tracer.update_trace(
            trace,
            output=_result_summary(last_result) if last_result else None,
            metadata=_trace_metadata(last_result) if last_result else {},
            status="success" if last_result and last_result.error is None else "error",
            level="DEFAULT" if last_result and last_result.error is None else "ERROR",
        )
        tracer.end_trace(trace)

    def resume(self, *, config: dict[str, Any], resume_value: Any) -> AgentResult:
        """Resume an interrupted run (e.g. after human approval).

        Args:
            config: The same config used for the original invoke (thread_id).
            resume_value: The value to feed to the pending interrupt.

        Returns:
            The final AgentResult after the run completes.
        """
        from langgraph.types import Command

        result_state = self.graph.invoke(Command(resume=resume_value), config=config)
        return result_state.get("result") or AgentResult(
            error="Agent finished without producing a result."
        )

    @staticmethod
    def _ensure_thread_id(config: dict[str, Any] | None) -> dict[str, Any]:
        """Ensure a thread_id exists in the config for the checkpointer.

        Args:
            config: User-provided graph config, possibly empty.

        Returns:
            A config dict guaranteed to contain a thread_id.
        """
        import uuid

        config = dict(config or {})
        configurable = dict(config.get("configurable", {}))
        if not configurable.get("thread_id"):
            configurable["thread_id"] = uuid.uuid4().hex
        config["configurable"] = configurable
        return config


def _result_summary(result: AgentResult | None) -> dict[str, Any] | None:
    """Build a compact, JSON-serializable view of an AgentResult for traces.

    Args:
        result: The final AgentResult.

    Returns:
        A dict with sql, row_count, cached, needs_approval, error, retries.
    """
    if result is None:
        return None
    return {
        "sql": result.sql,
        "row_count": result.row_count,
        "cached": result.cached,
        "needs_approval": result.needs_approval,
        "retries": result.retries,
        "error": result.error,
        "summary": result.summary[:500] if result.summary else "",
    }


def _trace_metadata(result: AgentResult | None) -> dict[str, Any]:
    """Extract metadata fields from an AgentResult for trace enrichment.

    Args:
        result: The final AgentResult.

    Returns:
        A dict of trace metadata.
    """
    if result is None or result.execution_stats is None:
        return {}
    return {
        "execution_time_ms": result.execution_stats.execution_time_ms,
        "estimated_rows_scanned": result.execution_stats.estimated_rows_scanned,
        "truncated": result.execution_stats.truncated,
    }
