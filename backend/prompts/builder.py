"""Prompt rendering via Jinja2 and high-level prompt builders.

Renders system prompts that combine the reflected schema, the semantic layer
(business metrics/glossary), and SQL rules. The builders are pure functions
so they are trivially testable and reusable outside the agent graph.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from backend.interfaces.prompt import PromptRenderer
from backend.models.schemas import SchemaInfo
from backend.prompts.sql_rules import SQL_RULES

_TEMPLATE_DIR = Path(__file__).parent / "templates"


class JinjaPromptRenderer:
    """Renders Jinja2 templates from the package templates directory."""

    def __init__(self, template_dir: str | Path | None = None):
        """Initialize the Jinja environment.

        Args:
            template_dir: Directory containing templates. Defaults to the
                package's templates folder.
        """
        self._env = Environment(
            loader=FileSystemLoader(str(template_dir or _TEMPLATE_DIR)),
            autoescape=select_autoescape(disabled_extensions=("j2", "jinja"), default=False),
            trim_blocks=True,
            lstrip_blocks=True,
        )

    def render(self, template_name: str, **context: Any) -> str:
        """Render a named template with context variables.

        Args:
            template_name: Template file name (e.g. "system.j2").
            **context: Variables passed into the template.

        Returns:
            The rendered prompt string.
        """
        template = self._env.get_template(template_name)
        return template.render(**context)

    def render_system(self, **context: Any) -> str:
        """Convenience wrapper for rendering the main system prompt.

        Args:
            **context: Variables for the system template.

        Returns:
            The rendered system prompt.
        """
        return self.render("system.j2", **context)


def _schema_to_text(schema: SchemaInfo, include_types: bool = True) -> str:
    """Serialize a SchemaInfo into a compact textual form for prompts.

    Args:
        schema: The reflected schema.
        include_types: Whether to include column data types.

    Returns:
        A human/LLM-readable schema description.
    """
    lines: list[str] = []
    for table in schema.tables:
        cols = []
        for col in table.columns:
            parts = [col.name]
            if include_types:
                parts.append(f":{col.data_type}")
            if col.is_primary_key:
                parts.append("PK")
            if col.is_foreign_key:
                parts.append(f"FK->{col.references}")
            cols.append(" ".join(parts))
        lines.append(f"TABLE {table.qualified_name} ({', '.join(cols)})")
        if table.indexes:
            lines.append(f"  indexes: {', '.join(table.indexes)}")
    return "\n".join(lines)


def _semantic_layer_to_text(metrics: list[Any], glossary: dict[str, str]) -> str:
    """Serialize the semantic layer (metrics + glossary) for prompts.

    Args:
        metrics: List of MetricDefinition objects.
        glossary: Term -> definition mapping.

    Returns:
        A text block describing business metrics and definitions.
    """
    lines: list[str] = []
    for metric in metrics:
        lines.append(f"- {metric.name} = {metric.expression}")
        if metric.definition:
            lines.append(f"    definition: {metric.definition}")
    if glossary:
        lines.append("Glossary:")
        for term, definition in glossary.items():
            lines.append(f"- {term}: {definition}")
    return "\n".join(lines)


def build_system_prompt(
    *,
    schema: SchemaInfo,
    dialect: str,
    max_rows: int,
    metrics: list[Any] | None = None,
    glossary: dict[str, str] | None = None,
    extra_instructions: str = "",
    renderer: PromptRenderer | None = None,
) -> str:
    """Build the full system prompt for SQL generation.

    Args:
        schema: Reflected database schema.
        dialect: Target SQL dialect name.
        max_rows: Maximum allowed result rows (embedded in rules).
        metrics: Business metric definitions from the semantic layer.
        glossary: Business glossary terms.
        extra_instructions: Additional guardrails/instructions to append.
        renderer: Renderer to use; defaults to a new JinjaPromptRenderer.

    Returns:
        The complete system prompt string.
    """
    renderer = renderer or JinjaPromptRenderer()
    schema_text = _schema_to_text(schema)
    semantic_text = _semantic_layer_to_text(metrics or [], glossary or {})
    rules = SQL_RULES.format(max_rows=max_rows)
    return renderer.render_system(
        dialect=dialect,
        schema=schema_text,
        semantic_layer=semantic_text,
        sql_rules=rules,
        extra_instructions=extra_instructions,
    )


def build_sql_generation_prompt(
    question: str,
    *,
    context: str = "",
    history: str = "",
) -> str:
    """Build the user-side prompt that asks the LLM to generate SQL.

    Args:
        question: The user's natural language question.
        context: Extra context (resolved references, previous results, etc.).
        history: Recent conversation history for context.

    Returns:
        The user prompt string for SQL generation.
    """
    parts = []
    if history:
        parts.append(f"Conversation history:\n{history}\n")
    if context:
        parts.append(f"Context:\n{context}\n")
    parts.append(
        f"Write a single read-only SQL query that answers the following question. "
        f"Return ONLY the SQL statement, with no markdown fences and no commentary.\n\n"
        f"Question: {question}"
    )
    return "\n".join(parts)


def build_planner_prompt(question: str, *, schema: SchemaInfo, history: str = "") -> str:
    """Build the prompt used by the planner node to structure the question.

    Args:
        question: The user's natural language question.
        schema: The reflected schema.
        history: Recent conversation history for context.

    Returns:
        The planner user prompt string.
    """
    tables = ", ".join(schema.table_names()) if schema else "(no schema loaded)"
    history_block = f"\nConversation history:\n{history}\n" if history else ""
    return (
        "You are a query planner. Given a user question and the available tables, "
        "produce a JSON object with this exact shape:\n"
        '{"intent": "...", "metrics": ["..."], "filters": [{"column": "...", '
        '"op": "...", "value": "..."}], "tables": ["..."], "joins": ["..."], '
        '"aggregations": ["..."], "sorting": "...", "confidence": 0.0, '
        '"explanation": "..."}\n'
        f"{history_block}"
        f"Available tables: {tables}\n"
        f"Question: {question}"
    )
