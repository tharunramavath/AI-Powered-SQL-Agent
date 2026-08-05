"""LangGraph state schema and reducers.

The state is a typed dict shared across graph nodes. Fields that accumulate
(retries, errors) use reducers so updates merge correctly across super-steps.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from langgraph.graph.message import add_messages

from backend.models.schemas import (
    AgentResult,
    ChartSpec,
    ExecutionStats,
    SchemaInfo,
    SQLPlan,
    ValidationResult,
)


def _increment(current: int, update: int) -> int:
    """Reducer: add the update to the current value (used for retry counts)."""
    return current + update


class AgentState(TypedDict, total=False):
    """Shared state flowing through the SQL agent graph."""

    # Inputs
    query: str
    datasource_id: str
    thread_id: str

    # Pipeline products
    schema: SchemaInfo
    plan: SQLPlan
    sql: str
    validation: ValidationResult
    columns: list[str]
    rows: list[dict[str, Any]]
    charts: list[ChartSpec]
    summary: str
    execution_stats: ExecutionStats

    # Semantic layer (from datasource config) for prompt construction
    metrics: list[Any]
    glossary: dict[str, str]

    # Retry / approval bookkeeping
    attempts: Annotated[int, _increment]
    errors: Annotated[list[str], operator.add]
    needs_approval: bool
    approved: bool
    cached: bool

    # Guardrail outcomes
    guardrail_blocked: bool
    guardrail_reason: str
    faithful: bool
    guardrail_warning: str

    # Message channel for LangGraph conversation tracking
    messages: Annotated[list[Any], add_messages]

    # Final structured output
    result: AgentResult


def initial_state(query: str, datasource_id: str, thread_id: str) -> AgentState:
    """Construct the initial state for a query run.

    Args:
        query: The user's natural language question.
        datasource_id: Datasource to query.
        thread_id: Session/thread identifier.

    Returns:
        A new AgentState dict.
    """
    return {
        "query": query,
        "datasource_id": datasource_id,
        "thread_id": thread_id or "",
        "attempts": 0,
        "errors": [],
        "needs_approval": False,
        "approved": False,
        "guardrail_blocked": False,
        "guardrail_reason": "",
        "faithful": True,
        "guardrail_warning": "",
        "messages": [],
        "columns": [],
        "rows": [],
        "charts": [],
    }
