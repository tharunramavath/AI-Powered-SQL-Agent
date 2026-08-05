"""LLM provider interface.

Any LLM backend (Groq, OpenAI, Anthropic, Gemini, local Ollama, ...) can be
plugged in by implementing this protocol. The rest of the system talks only
to this interface, so models can be swapped via configuration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


@dataclass
class LLMMessage:
    """A single message in a chat conversation."""

    role: str  # "system" | "user" | "assistant"
    content: str
    name: str | None = None


@dataclass
class LLMResponse:
    """A structured LLM completion result."""

    content: str
    raw: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, int] = field(default_factory=dict)  # prompt/completion tokens
    model: str = ""
    cost_usd: float = 0.0


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol for a chat-capable language model provider."""

    model: str
    temperature: float
    max_tokens: int

    def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stop: list[str] | None = None,
        structured: bool = False,
    ) -> LLMResponse:
        """Generate a completion for a conversation.

        Args:
            messages: The conversation history (system + user + assistant).
            temperature: Optional per-call override.
            max_tokens: Optional per-call token budget override.
            stop: Optional stop sequences.
            structured: If True, request a JSON-encoded object in the response.

        Returns:
            An LLMResponse with content, usage, and estimated cost.
        """
        ...

    def complete_json(self, messages: list[LLMMessage], **kwargs: Any) -> dict[str, Any]:
        """Generate a completion and parse it as JSON.

        Args:
            messages: The conversation history.
            **kwargs: Forwarded to :meth:`complete`.

        Returns:
            Parsed JSON object, or empty dict on parse failure.
        """
        ...
