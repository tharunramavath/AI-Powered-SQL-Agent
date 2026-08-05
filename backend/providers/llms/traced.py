"""Tracing decorator for :class:`LLMProvider` implementations.

Wraps any provider so each ``complete``/``complete_json`` call is recorded as
a LangFuse generation attached to the currently active trace. When LangFuse is
disabled the wrapper is a transparent pass-through.
"""

from __future__ import annotations

from typing import Any

from backend.core.logging import get_logger
from backend.core.observability import TracingService, get_tracer
from backend.interfaces.llm import LLMMessage, LLMProvider, LLMResponse

logger = get_logger(__name__)


class TracedLLMProvider:
    """A proxy that records every LLM call as a LangFuse generation."""

    def __init__(self, provider: LLMProvider, tracer: TracingService | None = None):
        """Initialize the traced proxy.

        Args:
            provider: The underlying LLMProvider to wrap.
            tracer: TracingService to record into; defaults to the global
                tracer (a no-op when LangFuse is disabled).
        """
        self._inner = provider
        self._tracer = tracer or get_tracer()
        self.model = provider.model
        self.temperature = provider.temperature
        self.max_tokens = provider.max_tokens

    @property
    def inner(self) -> LLMProvider:
        """Return the wrapped provider (useful for tests)."""
        return self._inner

    def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stop: list[str] | None = None,
        structured: bool = False,
    ) -> LLMResponse:
        """Generate a completion, tracing it as a LangFuse generation.

        Args:
            messages: Conversation history.
            temperature: Optional temperature override.
            max_tokens: Optional token budget override.
            stop: Optional stop sequences.
            structured: If True, request JSON output.

        Returns:
            The underlying provider's LLMResponse.
        """
        tracer = self._tracer
        trace = tracer.current_trace()
        generation = tracer.start_generation(
            trace,
            tracer.current_span(),
            name="llm",
            model=self.model,
            input=_messages_to_dict(messages),
            model_params={
                "temperature": temperature if temperature is not None else self.temperature,
                "max_tokens": max_tokens if max_tokens is not None else self.max_tokens,
            },
        )
        try:
            response = self._inner.complete(
                messages,
                temperature=temperature,
                max_tokens=max_tokens,
                stop=stop,
                structured=structured,
            )
        except Exception as exc:
            tracer.end_generation(
                generation,
                output=str(exc),
                level="ERROR",
                metadata={"error": str(exc)},
            )
            raise
        tracer.end_generation(
            generation,
            output=response.content,
            usage=response.usage or {},
            metadata={"model": response.model, "cost_usd": response.cost_usd},
        )
        return response

    def complete_json(self, messages: list[LLMMessage], **kwargs: Any) -> dict[str, Any]:
        """Generate a completion and parse JSON, tracing the call.

        Args:
            messages: Conversation history.
            **kwargs: Forwarded to :meth:`complete`.

        Returns:
            Parsed JSON object (possibly empty).
        """
        from backend.providers.llms.base import parse_json_content

        response = self.complete(messages, **kwargs)
        return parse_json_content(response.content)


def _messages_to_dict(messages: list[LLMMessage]) -> list[dict[str, Any]]:
    """Convert LLMMessage objects into plain dicts for LangFuse input.

    Args:
        messages: The message list.

    Returns:
        A JSON-serializable list of {role, content} dicts.
    """
    return [{"role": m.role, "content": m.content} for m in messages]
