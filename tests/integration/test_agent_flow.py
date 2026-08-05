"""Integration tests: full agent pipeline with a scripted fake LLM.

A fake LLM stands in for Groq so the entire LangGraph workflow can be
exercised against the in-memory SQLite database without API keys.
"""

from __future__ import annotations

import json

from backend.agents.sql_agent import SQLAgent
from backend.agents.state import initial_state
from backend.interfaces.llm import LLMResponse


class FakeLLM:
    """A scriptable LLM provider implementing the LLMProvider protocol."""

    def __init__(self, *, sql_responses: list[str] | None = None):
        """Initialize the fake with a queue of SQL responses.

        Args:
            sql_responses: List of SQL strings returned for generation
                prompts in order (for testing retries).
        """
        self.model = "fake"
        self.temperature = 0.1
        self.max_tokens = 1000
        self.sql_responses = list(sql_responses or ["SELECT name FROM products LIMIT 5"])
        self._last_sql: str | None = None
        self.calls: list[str] = []

    def complete(self, messages, *, temperature=None, max_tokens=None, stop=None, structured=False):
        """Return a canned response depending on the prompt type."""
        user_content = "\n".join(m.content for m in messages if m.role == "user")
        self.calls.append(user_content[:100])

        if "Write a single read-only SQL query" in user_content:
            if self.sql_responses:
                self._last_sql = self.sql_responses.pop(0)
            sql = self._last_sql or "SELECT 1"
            return LLMResponse(
                content=sql, model="fake", usage={"prompt_tokens": 10, "completion_tokens": 10}
            )
        if "query planner" in user_content or "Available tables" in user_content:
            plan = {
                "intent": "list products",
                "metrics": [],
                "filters": [],
                "tables": ["products"],
                "joins": [],
                "aggregations": [],
                "sorting": "name",
                "confidence": 0.9,
                "explanation": "test plan",
            }
            return LLMResponse(content=json.dumps(plan), model="fake")
        # explainer prompt
        return LLMResponse(content="Laptop is the top product by name.", model="fake")

    def complete_json(self, messages, **kwargs):
        """Return a parsed JSON plan."""
        response = self.complete(messages, **kwargs)
        return json.loads(response.content)


def _make_agent(dialect, schema, memory=None, result_cache=None, sql_responses=None, **kwargs):
    """Construct a SQLAgent wired with a FakeLLM for testing."""
    fake = FakeLLM(sql_responses=sql_responses)
    agent = SQLAgent(
        llm=fake,
        database=dialect,
        memory=memory,
        max_sql_retries=kwargs.pop("max_sql_retries", 3),
        cache=result_cache,
        **kwargs,
    )
    return agent, fake


class TestHappyPath:
    """A successful query produces a complete AgentResult."""

    def test_end_to_end(self, dialect, schema, conversation_memory):
        agent, fake = _make_agent(dialect, schema, memory=conversation_memory)
        state = initial_state("List products", "test", "thread-1")
        result = agent.invoke(state, config={"configurable": {"thread_id": "thread-1"}})

        assert result.error is None
        assert result.sql.strip().upper().startswith("SELECT")
        assert result.columns == ["name"]
        assert result.row_count == 3
        assert result.summary != ""
        assert result.charts, "Expected at least a table chart"
        assert result.retries == 0

    def test_memory_records_turn(self, dialect, schema, conversation_memory):
        agent, _ = _make_agent(dialect, schema, memory=conversation_memory)
        state = initial_state("List products", "test", "mem-1")
        agent.invoke(state, config={"configurable": {"thread_id": "mem-1"}})
        history = conversation_memory.history("mem-1")
        assert any("List products" in m["content"] for m in history)


class TestRetries:
    """The agent regenerates SQL after validation failures, up to the limit."""

    def test_invalid_then_valid(self, dialect, schema):
        # First response is dangerous, second is valid.
        sqls = [
            "DELETE FROM products",
            "SELECT name FROM products LIMIT 5",
        ]
        agent, fake = _make_agent(dialect, schema, sql_responses=sqls)
        state = initial_state("List products", "test", "t")
        result = agent.invoke(state)

        assert result.error is None
        assert result.retries == 1

    def test_exhausts_retries(self, dialect, schema):
        sqls = ["DELETE FROM products"] * 5
        agent, fake = _make_agent(dialect, schema, sql_responses=sqls, max_sql_retries=2)
        state = initial_state("List products", "test", "t")
        result = agent.invoke(state)

        assert result.error is not None
        assert "Validation" in result.error or "Forbidden" in result.error


class TestCaching:
    """Repeated identical SQL should hit the result cache."""

    def test_second_run_is_cached(self, dialect, schema, result_cache):
        agent, fake = _make_agent(dialect, schema, result_cache=result_cache)
        state = initial_state("List products", "test", "t")
        first = agent.invoke(state, config={"configurable": {"thread_id": "t"}})
        assert first.cached is False

        second = agent.invoke(state, config={"configurable": {"thread_id": "t"}})
        assert second.cached is True
        assert second.rows == first.rows


class TestRowCap:
    """The row cap must be enforced end-to-end."""

    def test_row_cap_via_agent(self, dialect, schema):
        agent, fake = _make_agent(
            dialect,
            schema,
            sql_responses=["SELECT * FROM orders"],
            max_rows=2,
        )
        state = initial_state("Show orders", "test", "t")
        result = agent.invoke(state)
        assert result.row_count <= 2
