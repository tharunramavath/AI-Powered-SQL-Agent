"""Planner node: understands the user's question and extracts query structure.

Uses the LLM to convert the natural language question into a structured
:class:`SQLPlan` (intent, metrics, filters, tables, aggregations, sorting).
The plan is used to guide SQL generation and to enrich the prompt with
resolved conversation context.
"""

from __future__ import annotations

from typing import Any

from backend.core.logging import get_logger
from backend.interfaces.llm import LLMMessage, LLMProvider
from backend.memory.context import ConversationMemory
from backend.models.schemas import SchemaInfo, SQLPlan
from backend.prompts.builder import build_planner_prompt

logger = get_logger(__name__)


class PlannerNode:
    """LangGraph node that structures the user question into a SQLPlan."""

    def __init__(
        self,
        *,
        llm: LLMProvider,
        memory: ConversationMemory | None = None,
    ):
        """Initialize the planner.

        Args:
            llm: The LLM provider used for understanding the question.
            memory: Optional conversation memory for context resolution.
        """
        self._llm = llm
        self._memory = memory

    def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """Run the planning step for the current state.

        Args:
            state: Current graph state.

        Returns:
            State updates containing the structured plan.
        """
        query = state.get("query", "")
        schema: SchemaInfo = state.get("schema")  # type: ignore[assignment]
        thread_id = state.get("thread_id", "")

        history = ""
        if self._memory is not None and thread_id:
            history = self._format_history(self._memory.history(thread_id, limit=6))

        prompt = build_planner_prompt(query, schema=schema, history=history)
        messages = [
            LLMMessage(
                role="system",
                content="You are a precise query planner. Respond only with valid JSON.",
            ),
            LLMMessage(role="user", content=prompt),
        ]

        try:
            raw = self._llm.complete_json(messages, temperature=0.0)
            plan = SQLPlan.model_validate(raw)
        except Exception as exc:
            logger.warning("planner_failed", error=str(exc))
            plan = SQLPlan(intent=query, explanation="Planner could not structure the question.")

        logger.info("plan_created", intent=plan.intent, confidence=plan.confidence)
        return {"plan": plan}

    @staticmethod
    def _format_history(history: list[dict[str, str]]) -> str:
        """Format recent history lines for inclusion in the prompt.

        Args:
            history: List of {role, content} dicts.

        Returns:
            A readable history string.
        """
        return "\n".join(f"{m['role']}: {m['content']}" for m in history)
