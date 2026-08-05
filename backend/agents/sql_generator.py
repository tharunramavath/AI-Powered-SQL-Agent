"""SQL generation node.

Calls the LLM to write SQL from the system prompt (schema + semantic layer +
rules) and the user question. Also injects error feedback from previous
failed attempts so regeneration is informed by what went wrong.
"""

from __future__ import annotations

from typing import Any

from backend.core.logging import get_logger
from backend.interfaces.llm import LLMMessage, LLMProvider
from backend.models.schemas import SchemaInfo
from backend.prompts.builder import (
    JinjaPromptRenderer,
    build_sql_generation_prompt,
    build_system_prompt,
)

logger = get_logger(__name__)


class SqlGeneratorNode:
    """LangGraph node that produces a SQL statement for the user question."""

    def __init__(
        self,
        *,
        llm: LLMProvider,
        max_rows: int = 500,
        renderer: JinjaPromptRenderer | None = None,
    ):
        """Initialize the SQL generator.

        Args:
            llm: The LLM provider used to write SQL.
            max_rows: Maximum allowed result rows (embedded in rules).
            renderer: Prompt renderer; defaults to a new Jinja renderer.
        """
        self._llm = llm
        self._max_rows = max_rows
        self._renderer = renderer or JinjaPromptRenderer()

    def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """Generate SQL for the current state.

        Args:
            state: Current graph state (query, schema, plan, attempts, errors).

        Returns:
            State updates containing the generated SQL.
        """
        query = state.get("query", "")
        schema: SchemaInfo = state.get("schema")  # type: ignore[assignment]
        attempts = state.get("attempts", 0)
        errors = state.get("errors", [])

        metrics = state.get("metrics", [])
        glossary = state.get("glossary", {})

        system_prompt = build_system_prompt(
            schema=schema,
            dialect=schema.dialect if schema else "postgres",
            max_rows=self._max_rows,
            metrics=metrics,
            glossary=glossary,
            extra_instructions=self._error_feedback(attempts, errors),
            renderer=self._renderer,
        )

        user_prompt = build_sql_generation_prompt(query)
        messages = [
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=user_prompt),
        ]

        response = self._llm.complete(messages, temperature=0.0)
        sql = response.content.strip()
        logger.info(
            "sql_generated",
            length=len(sql),
            attempts=attempts,
            tokens=response.usage,
            cost_usd=response.cost_usd,
        )
        return {"sql": sql, "attempts": 1}

    @staticmethod
    def _error_feedback(attempts: int, errors: list[str]) -> str:
        """Build a feedback block from previous validation/execution errors.

        Args:
            attempts: Number of previous attempts.
            errors: Error messages from earlier attempts.

        Returns:
            Instruction text, or empty string on the first attempt.
        """
        if attempts == 0 or not errors:
            return ""
        last = errors[-1]
        return (
            f"This is attempt {attempts}. The previous attempt failed with:\n"
            f"{last}\n"
            "Fix the SQL to avoid this exact problem. Do not repeat the same mistake."
        )
