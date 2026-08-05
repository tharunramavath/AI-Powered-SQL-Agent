"""LangChain tool exposing the reflected database schema.

Lets a tool-calling agent inspect available tables and columns.
"""

from __future__ import annotations

from langchain_core.tools import StructuredTool

from backend.models.schemas import SchemaInfo


def _build_schema_fn(schema: SchemaInfo):
    """Create the schema inspection closure.

    Args:
        schema: The reflected schema to expose.

    Returns:
        A callable returning a text summary of the schema.
    """

    def show_schema(table: str = "") -> str:
        """Return a text summary of the schema (optionally one table).

        Args:
            table: Optional table name to filter on.

        Returns:
            A readable schema description.
        """
        lines: list[str] = []
        for t in schema.tables:
            if table and t.name != table:
                continue
            cols = ", ".join(
                f"{c.name}:{c.data_type}" + (" PK" if c.is_primary_key else "") for c in t.columns
            )
            lines.append(f"TABLE {t.qualified_name} ({cols})")
        return "\n".join(lines) or "No tables found."

    return show_schema


def SchemaTool(*, schema: SchemaInfo) -> StructuredTool:
    """Build the schema_tool LangChain tool.

    Args:
        schema: The reflected schema to expose.

    Returns:
        A StructuredTool for schema inspection.
    """
    return StructuredTool.from_function(
        func=_build_schema_fn(schema),
        name="schema_tool",
        description="Describe the available database tables and their columns.",
    )
