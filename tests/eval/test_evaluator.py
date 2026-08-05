"""Tests for the evaluation harness.

Verifies the Evaluator can run a suite of cases against an agent wired with
the scripted FakeLLM, produces accurate aggregate metrics, and computes
LLM-as-judge metrics (semantic SQL equivalence, answer faithfulness) when a
judge LLM is supplied.
"""

from __future__ import annotations

from backend.agents.sql_agent import SQLAgent
from backend.interfaces.llm import LLMResponse
from tests.eval.evaluator import EvalCase, Evaluator
from tests.integration.test_agent_flow import FakeLLM


class FakeJudgeLLM:
    """A scripted LLM that returns JSON verdicts for judge prompts."""

    model = "fake"
    temperature = 0.0
    max_tokens = 200

    def __init__(self, *, equivalent: bool = True, faithful: bool = True):
        """Configure the judge verdicts.

        Args:
            equivalent: SQL-equivalence verdict.
            faithful: Faithfulness verdict.
        """
        self.equivalent = equivalent
        self.faithful = faithful

    def complete(self, messages, **kwargs) -> LLMResponse:
        """Return a trivial completion (unused by judges)."""
        return LLMResponse(content="{}", model="fake")

    def complete_json(self, messages, **kwargs) -> dict:
        """Return a verdict depending on the prompt type."""
        text = "\n".join(m.content for m in messages if m.role == "user")
        if "SQL equivalence judge" in text:
            return {"equivalent": self.equivalent, "reason": "test"}
        return {"faithful": self.faithful, "reason": "test"}


def _make_agent(dialect, sql_responses=None):
    """Construct a SQLAgent with a FakeLLM for evaluation tests."""
    fake = FakeLLM(sql_responses=sql_responses)
    agent = SQLAgent(llm=fake, database=dialect, max_sql_retries=3)
    return agent, fake


class TestEvaluator:
    """Evaluator aggregates per-case outcomes into a report."""

    def test_report_metrics(self, dialect):
        agent, _ = _make_agent(dialect)
        cases = [
            EvalCase(id="c1", question="List products", expected_rows=3),
            EvalCase(id="c2", question="List customers", expected_rows=3),
        ]
        report = Evaluator(agent=agent, cases=cases).run(datasource_id="test")

        assert report.total == 2
        assert report.sql_accuracy == 1.0
        assert report.execution_accuracy == 1.0
        assert report.avg_retries == 0.0
        assert len(report.results) == 2
        assert "Eval summary" in report.summary()
        # No judge LLM supplied -> judge-based metrics are absent.
        assert report.sql_semantic_accuracy is None
        assert report.faithfulness is None

    def test_sql_mismatch_lowers_accuracy(self, dialect):
        agent, _ = _make_agent(dialect)
        cases = [
            EvalCase(
                id="c1",
                question="List products",
                expected_sql="SELECT name, price FROM products ORDER BY price DESC",
                expected_rows=3,
            ),
        ]
        report = Evaluator(agent=agent, cases=cases).run(datasource_id="test")

        assert report.total == 1
        # FakeLLM returns `SELECT name FROM products LIMIT 5`, which does not
        # match the expected SQL textually, so SQL accuracy is 0%.
        assert report.sql_accuracy == 0.0
        assert report.execution_accuracy == 1.0

    def test_judge_metrics_with_llm(self, dialect):
        agent, _ = _make_agent(dialect)
        judge = FakeJudgeLLM(equivalent=True, faithful=True)
        cases = [
            EvalCase(
                id="c1",
                question="List products",
                expected_sql="SELECT name FROM products ORDER BY name",
                expected_rows=3,
            ),
        ]
        report = Evaluator(agent=agent, cases=cases, llm=judge).run(datasource_id="test")

        assert report.sql_semantic_accuracy == 1.0
        assert report.faithfulness == 1.0
        assert report.execution_accuracy == 1.0

    def test_judge_metrics_capture_failures(self, dialect):
        agent, _ = _make_agent(dialect)
        judge = FakeJudgeLLM(equivalent=False, faithful=False)
        cases = [
            EvalCase(
                id="c1",
                question="List products",
                expected_sql="SELECT name FROM products ORDER BY name",
                expected_rows=3,
            ),
        ]
        report = Evaluator(agent=agent, cases=cases, llm=judge).run(datasource_id="test")

        assert report.sql_semantic_accuracy == 0.0
        assert report.faithfulness == 0.0

    def test_judge_tolerates_non_json_llm(self, dialect):
        # A judge LLM that returns garbage must degrade gracefully (None).
        class BadJudge:
            model = "fake"
            temperature = 0.0
            max_tokens = 100

            def complete(self, messages, **kwargs) -> LLMResponse:
                return LLMResponse(content="not json", model="fake")

            def complete_json(self, messages, **kwargs) -> dict:
                raise ValueError("bad json")

        agent, _ = _make_agent(dialect)
        report = Evaluator(
            agent=agent,
            cases=[EvalCase(id="c1", question="List products", expected_rows=3)],
            llm=BadJudge(),
        ).run(datasource_id="test")

        assert report.total == 1
        assert report.sql_semantic_accuracy is None
        assert report.faithfulness is None
