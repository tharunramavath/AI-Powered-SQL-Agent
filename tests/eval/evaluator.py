"""Evaluation harness for the AI SQL Agent.

Measures the product metrics defined in the spec:
* SQL accuracy (valid, schema-conformant SQL generated)
* Execution accuracy (rows match the expected reference SQL)
* Latency (total wall time)
* Retries (how often regeneration was needed)

Runs a suite of (question, expected_sql) pairs against the agent using a
scripted LLM and/or a live LLM, then prints a report. When LangFuse is enabled
every case is logged as a ``sql-agent-eval`` trace and scored in the LangFuse
UI, so runs can be compared over time. Optional LLM-as-judge metrics (SQL
semantic equivalence and answer faithfulness) are attached when an LLM is
provided.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field

from backend.agents.sql_agent import SQLAgent
from backend.agents.state import initial_state
from backend.core.observability import TracingService, get_tracer
from backend.interfaces.llm import LLMMessage, LLMProvider
from backend.models.schemas import AgentResult
from backend.prompts.eval import build_sql_equivalence_prompt
from backend.prompts.guardrails import build_output_faithfulness_prompt


@dataclass
class EvalCase:
    """A single evaluation case."""

    id: str
    question: str
    expected_sql: str = ""
    expected_rows: int = -1


@dataclass
class EvalResult:
    """Outcome of evaluating one case."""

    case: EvalCase
    sql: str = ""
    valid: bool = False
    sql_ok: bool = False
    row_match: bool = False
    sql_semantic_match: bool | None = None
    faithful: bool | None = None
    row_count: int = 0
    latency_ms: float = 0.0
    retries: int = 0
    error: str | None = None


@dataclass
class EvalReport:
    """Aggregated evaluation report."""

    total: int = 0
    sql_accuracy: float = 0.0
    execution_accuracy: float = 0.0
    sql_semantic_accuracy: float | None = None
    faithfulness: float | None = None
    avg_latency_ms: float = 0.0
    avg_retries: float = 0.0
    results: list[EvalResult] = field(default_factory=list)

    def summary(self) -> str:
        """Render the report as a compact text block.

        Returns:
            Multi-line summary string.
        """
        lines = [
            f"Eval summary over {self.total} cases",
            f"  SQL accuracy:          {self.sql_accuracy:.1%}",
            f"  Execution accuracy:    {self.execution_accuracy:.1%}",
        ]
        if self.sql_semantic_accuracy is not None:
            lines.append(f"  SQL semantic accuracy: {self.sql_semantic_accuracy:.1%}")
        if self.faithfulness is not None:
            lines.append(f"  Faithfulness:          {self.faithfulness:.1%}")
        lines.append(f"  Avg latency:           {self.avg_latency_ms:.0f} ms")
        lines.append(f"  Avg SQL retries:       {self.avg_retries:.2f}")
        return "\n".join(lines)


class Evaluator:
    """Runs the eval suite against an agent, optionally scoring in LangFuse."""

    def __init__(
        self,
        *,
        agent: SQLAgent,
        cases: list[EvalCase],
        sql_match_fn: Callable[[EvalCase, AgentResult], bool] | None = None,
        row_match_fn: Callable[[EvalCase, AgentResult], bool] | None = None,
        llm: LLMProvider | None = None,
        tracer: TracingService | None = None,
    ):
        """Initialize the evaluator.

        Args:
            agent: The compiled SQLAgent to evaluate.
            cases: The evaluation cases.
            sql_match_fn: Optional custom SQL equivalence function.
            row_match_fn: Optional custom row-equivalence function.
            llm: Optional LLM used for judge-based metrics (semantic match,
                faithfulness). When omitted those metrics are skipped.
            tracer: Optional TracingService; defaults to the global tracer
                (a no-op when LangFuse is disabled).
        """
        self._agent = agent
        self._cases = cases
        self._sql_match = sql_match_fn or _default_sql_match
        self._row_match = row_match_fn or _default_row_match
        self._llm = llm
        self._tracer = tracer or get_tracer()

    def run(self, *, datasource_id: str = "test", dataset: str = "sql-agent-eval") -> EvalReport:
        """Evaluate all cases and aggregate the report.

        Each case is logged as a LangFuse trace and scored when tracing is
        enabled.

        Args:
            datasource_id: Datasource to run the agent against.
            dataset: Dataset name recorded in trace metadata.

        Returns:
            An aggregated EvalReport.
        """
        report = EvalReport(total=len(self._cases))
        latencies: list[float] = []
        retries: list[int] = []
        semantic: list[bool] = []
        faithful: list[bool] = []

        for case in self._cases:
            ev = self._run_case(case, datasource_id=datasource_id, dataset=dataset)
            report.results.append(ev)
            latencies.append(ev.latency_ms)
            retries.append(ev.retries)
            if ev.sql_semantic_match is not None:
                semantic.append(ev.sql_semantic_match)
            if ev.faithful is not None:
                faithful.append(ev.faithful)

        report.sql_accuracy = (
            sum(1 for r in report.results if r.valid and r.sql_ok) / report.total
        )
        report.execution_accuracy = sum(1 for r in report.results if r.row_match) / report.total
        report.avg_latency_ms = sum(latencies) / len(latencies)
        report.avg_retries = sum(retries) / len(retries)
        report.sql_semantic_accuracy = sum(semantic) / len(semantic) if semantic else None
        report.faithfulness = sum(faithful) / len(faithful) if faithful else None
        return report

    # -- internals --------------------------------------------------------

    def _run_case(self, case: EvalCase, *, datasource_id: str, dataset: str) -> EvalResult:
        """Evaluate a single case with tracing and scoring.

        Args:
            case: The case to run.
            datasource_id: Datasource to run against.
            dataset: Dataset name for trace metadata.

        Returns:
            An EvalResult for the case.
        """
        tracer = self._tracer
        trace = tracer.start_trace(
            name="sql-agent-eval",
            input=case.question,
            session_id=f"eval-{case.id}",
            metadata={"dataset": dataset, "case_id": case.id, "datasource_id": datasource_id},
        )
        with tracer.trace_context(trace):
            start = time.perf_counter()
            state = initial_state(case.question, datasource_id, f"eval-{case.id}")
            result = self._agent.invoke(state)
            latency_ms = (time.perf_counter() - start) * 1000.0

        ev = EvalResult(
            case=case,
            sql=result.sql,
            valid=result.error is None,
            row_count=result.row_count,
            latency_ms=round(latency_ms, 1),
            retries=result.retries,
            error=result.error,
        )
        if result.error is None:
            ev.sql_ok = self._sql_match(case, result)
            ev.row_match = self._row_match(case, result)
            ev.sql_semantic_match = self._judge_sql(case, result)
            ev.faithful = self._judge_faithfulness(case, result)

        self._score(trace, ev)
        tracer.end_trace(trace)
        return ev

    def _score(self, trace, ev: EvalResult) -> None:
        """Attach evaluation scores to the case trace.

        Args:
            trace: The LangFuse trace for the case.
            ev: The case result.
        """
        tracer = self._tracer
        tracer.score_trace(
            trace, name="sql_validity", value=1.0 if ev.valid and ev.sql_ok else 0.0
        )
        tracer.score_trace(trace, name="execution_accuracy", value=1.0 if ev.row_match else 0.0)
        if ev.sql_semantic_match is not None:
            tracer.score_trace(
                trace,
                name="sql_semantic_equivalence",
                value=1.0 if ev.sql_semantic_match else 0.0,
            )
        if ev.faithful is not None:
            tracer.score_trace(
                trace, name="answer_faithfulness", value=1.0 if ev.faithful else 0.0
            )

    def _judge_sql(self, case: EvalCase, result: AgentResult) -> bool | None:
        """Judge whether generated SQL is semantically equivalent to the reference.

        Args:
            case: The eval case with expected SQL.
            result: The agent result.

        Returns:
            True/False verdict, or None when no judge is available or the
            case has no reference SQL.
        """
        if self._llm is None or not case.expected_sql:
            return None
        verdict = self._llm_verdict(
            build_sql_equivalence_prompt(
                question=case.question,
                generated_sql=result.sql,
                expected_sql=case.expected_sql,
            )
        )
        if verdict is None:
            return None
        return bool(verdict.get("equivalent", False))

    def _judge_faithfulness(self, case: EvalCase, result: AgentResult) -> bool | None:
        """Judge whether the summary is faithful to the returned rows.

        Args:
            case: The eval case.
            result: The agent result.

        Returns:
            True/False verdict, or None when no judge is available.
        """
        if self._llm is None:
            return None
        sample = _serialize_rows(result.rows)
        verdict = self._llm_verdict(
            build_output_faithfulness_prompt(
                question=case.question,
                summary=result.summary,
                sample_rows=sample,
                sql=result.sql,
            )
        )
        if verdict is None:
            return None
        return bool(verdict.get("faithful", False))

    def _llm_verdict(self, prompt: str) -> dict | None:
        """Ask the judge LLM for a structured JSON verdict.

        Args:
            prompt: The judge user prompt.

        Returns:
            The parsed verdict dict, or None if the call/parse fails.
        """
        try:
            messages = [
                LLMMessage(
                    role="system",
                    content="You are a strict evaluator. Respond only with valid JSON.",
                ),
                LLMMessage(role="user", content=prompt),
            ]
            return self._llm.complete_json(messages, temperature=0.0, structured=True)  # type: ignore[union-attr]
        except Exception:  # pragma: no cover - judge outage fallback
            return None


def _serialize_rows(rows: list[dict], limit: int = 20) -> str:
    """Serialize a sample of rows as readable text for judge prompts.

    Args:
        rows: The result rows.
        limit: Maximum number of rows to include.

    Returns:
        A JSON-ish text representation of the sample.
    """
    if not rows:
        return "(no rows returned)"
    import json

    return json.dumps(rows[:limit], default=str, ensure_ascii=False)


def _default_sql_match(case: EvalCase, result: AgentResult) -> bool:
    """Default SQL equivalence: exact normalized comparison.

    Args:
        case: The eval case with the expected SQL.
        result: The agent result.

    Returns:
        True if the generated SQL matches the expected SQL.
    """
    if not case.expected_sql:
        return True  # no expectation set
    from backend.cache.result_cache import ResultCache

    return ResultCache.normalize_sql(result.sql) == ResultCache.normalize_sql(case.expected_sql)


def _default_row_match(case: EvalCase, result: AgentResult) -> bool:
    """Default row match: compare returned row count to the expectation.

    Args:
        case: The eval case with the expected row count.
        result: The agent result.

    Returns:
        True if the row count matches (or no expectation is set).
    """
    if case.expected_rows < 0:
        return True
    return result.row_count == case.expected_rows
