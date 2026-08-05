"""Prompt rendering interface.

Keeps prompt building framework-agnostic: any renderer (Jinja templates,
string formatting, LiteLLM-style templating) can implement this protocol.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class PromptRenderer(Protocol):
    """Protocol for rendering prompt templates with context variables."""

    def render(self, template_name: str, **context: Any) -> str:
        """Render a named template to a final prompt string.

        Args:
            template_name: Identifier of the template to render.
            **context: Variables available to the template.

        Returns:
            The fully rendered prompt.
        """
        ...

    def render_system(self, **context: Any) -> str:
        """Render the system prompt with the given context."""
        ...
