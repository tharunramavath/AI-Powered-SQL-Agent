"""Formatter node: analyzes raw results and generates a natural-language summary.

The formatter runs the "explain" template against the LLM with the question,
the executed SQL, and a sample of the result rows. It also records the
question/answer into conversation memory when a thread is present.
"""

from __future__ import annotations

from typing import Any

from backend.core.logging import get_logger
from backend.interfaces.llm import LLMMessage, LLMProvider
from backend.memory.context import ConversationMemory
from backend.prompts.builder import JinjaPromptRenderer

logger = get_logger(__name__)


class FormatterNode:
    """LangGraph node that produces the final natural-language summary."""

    def __init__(
        self,
        *,
        llm: LLMProvider,
        memory: ConversationMemory | None = None,
        renderer: JinjaPromptRenderer | None = None,
    ):
        """Initialize the formatter.

        Args:
            llm: The LLM provider used to write the summary.
            memory: Optional conversation memory to persist the turn.
            renderer: Prompt renderer; defaults to a new Jinja renderer.
        """
        self._llm = llm
        self._memory = memory
        self._renderer = renderer or JinjaPromptRenderer()

    def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """Generate the natural-language summary for the current results.

        Args:
            state: Current graph state with columns, rows, and SQL.

        Returns:
            State updates containing the summary string.
        """
        query = state.get("query", "")
        sql = state.get("sql", "")
        columns = state.get("columns", [])
        rows = state.get("rows", [])
        stats = state.get("execution_stats")

        sample = self._sample_rows(rows, limit=20)
        prompt = self._renderer.render(
            "explain.j2",
            question=query,
            sql=sql,
            columns=", ".join(columns),
            sample_rows=sample,
            stats=stats.model_dump(mode="json") if stats else {},
        )

        messages = [
            LLMMessage(
                role="system", content="You are a concise data analyst writing user-facing answers."
            ),
            LLMMessage(role="user", content=prompt),
        ]
        response = self._llm.complete(messages, temperature=0.2)
        summary = response.content.strip()

        thread_id = state.get("thread_id", "")
        if self._memory is not None and thread_id:
            self._memory.remember(thread_id, query, summary)

        return {"summary": summary}

    @staticmethod
    def _sample_rows(rows: list[dict[str, Any]], limit: int = 20) -> str:
        """Serialize a small sample of rows as readable text for the prompt.

        Args:
            rows: The result rows.
            limit: Maximum number of rows to include.

        Returns:
            A JSON-ish text representation of the sample.
        """
        if not rows:
            return "(no rows returned)"
        sample = rows[:limit]
        try:
            import json

            return json.dumps(sample, default=str, ensure_ascii=False)
        except Exception:
            return "\n".join(str(r) for r in sample)
