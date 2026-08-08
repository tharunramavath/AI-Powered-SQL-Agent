"""Unit tests for LangFuse tracing wiring.

Uses a fake LangFuse-like client so the tracing path can be verified without
network access or API keys.
"""

from __future__ import annotations

from backend.agents.sql_agent import SQLAgent
from backend.agents.state import initial_state
from backend.core.observability import TracingService
from backend.providers.llms.traced import TracedLLMProvider
from tests.integration.test_agent_flow import FakeLLM


class FakeGeneration:
    """A fake LangFuse generation object (v4 start_observation API)."""

    def __init__(self, owner):
        self.owner = owner

    def update(self, **kwargs):
        pass

    def end(self, **kwargs):
        self.owner.generation_ends += 1


class FakeTrace:
    """A fake LangFuse trace/root-observation object (v4 API)."""

    def __init__(self, trace_id, owner):
        self.id = trace_id
        self.trace_id = trace_id
        self.owner = owner
        self.updates = 0

    def start_observation(self, **kwargs):
        self.owner.generation_starts += 1
        return FakeGeneration(self.owner)

    def update(self, **kwargs):
        self.updates += 1

    def end(self, **kwargs):
        self.owner.trace_ends += 1


class FakeClient:
    """A fake LangFuse client recording trace/score activity."""

    def __init__(self):
        self.traces: list[FakeTrace] = []
        self.scores: list[dict] = []
        self.generation_starts = 0
        self.generation_ends = 0
        self.trace_ends = 0

    def start_observation(self, **kwargs):
        trace = FakeTrace(f"t{len(self.traces) + 1}", self)
        self.traces.append(trace)
        return trace

    def create_score(self, **kwargs):
        self.scores.append(kwargs)

    def flush(self):
        pass


def _make_traced_agent(dialect):
    """Return (agent, client) with a TracedLLMProvider over FakeLLM."""
    client = FakeClient()
    tracer = TracingService(client=client)
    llm = TracedLLMProvider(FakeLLM(), tracer=tracer)
    agent = SQLAgent(llm=llm, database=dialect, tracer=tracer)
    return agent, client


class TestTracing:
    """SQLAgent.invoke records a trace with LLM generations."""

    def test_invoke_records_trace_and_generations(self, dialect):
        agent, client = _make_traced_agent(dialect)
        state = initial_state("List products", "test", "thread-1")
        result = agent.invoke(state, config={"configurable": {"thread_id": "thread-1"}})

        assert result.error is None
        assert len(client.traces) == 1
        assert client.traces[0].id == "t1"
        assert client.traces[0].updates >= 1  # output/status attached
        assert client.trace_ends == 1
        # Planner + generator + formatter are LLM calls, all traced.
        assert client.generation_starts >= 3
        assert client.generation_ends == client.generation_starts

    def test_disabled_tracer_is_noop(self, dialect):
        tracer = TracingService(client=None)
        llm = TracedLLMProvider(FakeLLM(), tracer=tracer)
        agent = SQLAgent(llm=llm, database=dialect, tracer=tracer)
        state = initial_state("List products", "test", "thread-2")
        result = agent.invoke(state, config={"configurable": {"thread_id": "thread-2"}})

        assert result.error is None  # tracing must not break the pipeline
