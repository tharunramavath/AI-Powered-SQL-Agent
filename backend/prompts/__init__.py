"""Prompt rendering and system prompt construction.

Framework-agnostic: this package has no knowledge of LangGraph or FastAPI.
It renders Jinja templates into system/user prompts from the schema,
semantic layer, and SQL rules.
"""

from backend.prompts.builder import (
    JinjaPromptRenderer,
    build_planner_prompt,
    build_sql_generation_prompt,
    build_system_prompt,
)
from backend.prompts.sql_rules import SQL_RULES

__all__ = [
    "JinjaPromptRenderer",
    "SQL_RULES",
    "build_planner_prompt",
    "build_sql_generation_prompt",
    "build_system_prompt",
]
