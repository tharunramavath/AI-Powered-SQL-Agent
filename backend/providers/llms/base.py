"""Shared base class for LangChain-backed LLM providers.

Centralizes token usage extraction, JSON parsing, and per-call options so
each concrete provider only has to supply its LangChain chat model.
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Any

from backend.core.logging import get_logger
from backend.interfaces.llm import LLMMessage, LLMProvider, LLMResponse

logger = get_logger(__name__)

# Approximate USD cost per 1M tokens (input/output) for common models.
# Extend when adding models; used for cost tracking.
MODEL_COST_PER_1M = {
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "llama-3.1-8b-instant": (0.05, 0.08),
    "default": (0.30, 0.60),
}


def estimate_cost_usd(model: str, usage: dict[str, int]) -> float:
    """Estimate the USD cost of a completion from token usage.

    Args:
        model: Model name used to look up pricing.
        usage: Dict with prompt_tokens/completion_tokens keys.

    Returns:
        Estimated cost in USD.
    """
    cost_in, cost_out = MODEL_COST_PER_1M.get(model, MODEL_COST_PER_1M["default"])
    return (
        usage.get("prompt_tokens", 0) * cost_in + usage.get("completion_tokens", 0) * cost_out
    ) / 1_000_000.0


class BaseLangChainLLM(LLMProvider, ABC):
    """Abstract base for LangChain chat-model-backed providers."""

    def __init__(self, *, model: str, temperature: float = 0.1, max_tokens: int = 4096):
        """Store provider options.

        Args:
            model: Model identifier used with the vendor.
            temperature: Sampling temperature.
            max_tokens: Max completion tokens.
        """
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens

    @abstractmethod
    def _build_chat_model(self) -> Any:
        """Construct and return the underlying LangChain chat model."""
        ...

    def complete(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        stop: list[str] | None = None,
        structured: bool = False,
    ) -> LLMResponse:
        """Generate a completion via the LangChain chat model.

        Args:
            messages: Conversation history (system/user/assistant roles).
            temperature: Optional override; falls back to instance value.
            max_tokens: Optional override; falls back to instance value.
            stop: Optional stop sequences.
            structured: If True, instruct the model to return JSON.

        Returns:
            An LLMResponse with content, usage, model, and cost estimate.
        """
        chat = self._build_chat_model()
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        # Map our roles to LangChain message classes.
        role_map = {"system": SystemMessage, "user": HumanMessage, "assistant": AIMessage}
        langchain_messages = [role_map[m.role](content=m.content) for m in messages]

        kwargs: dict[str, Any] = {
            "temperature": temperature if temperature is not None else self.temperature,
            "max_tokens": max_tokens if max_tokens is not None else self.max_tokens,
        }
        if stop:
            kwargs["stop"] = stop
        if structured:
            kwargs["format"] = "json_object"

        try:
            response = chat.invoke(langchain_messages, **kwargs)
        except Exception as exc:
            logger.error("llm_completion_failed", model=self.model, error=str(exc))
            raise

        content = response.content if isinstance(response.content, str) else str(response.content)
        usage = _extract_usage(response)
        return LLMResponse(
            content=content,
            raw={"response_metadata": getattr(response, "response_metadata", {})},
            usage=usage,
            model=self.model,
            cost_usd=estimate_cost_usd(self.model, usage),
        )

    def complete_json(self, messages: list[LLMMessage], **kwargs: Any) -> dict[str, Any]:
        """Generate a completion and parse the content as JSON.

        Tries strict JSON parsing first, then extracts a JSON object from the
        text. Returns an empty dict on failure.

        Args:
            messages: Conversation history.
            **kwargs: Forwarded to :meth:`complete`.

        Returns:
            Parsed JSON object (possibly empty).
        """
        response = self.complete(messages, **kwargs)
        return parse_json_content(response.content)


def _extract_usage(response: Any) -> dict[str, int]:
    """Extract token usage from a LangChain AIMessage response.

    Args:
        response: LangChain AIMessage.

    Returns:
        Dict with prompt_tokens and completion_tokens.
    """
    usage: dict[str, int] = {}
    meta = getattr(response, "response_metadata", {}) or {}
    token_usage = meta.get("token_usage") or meta.get("usage") or meta.get("tokenUsage")
    if token_usage:
        usage["prompt_tokens"] = int(
            token_usage.get("prompt_tokens") or token_usage.get("input_tokens") or 0
        )
        usage["completion_tokens"] = int(
            token_usage.get("completion_tokens") or token_usage.get("output_tokens") or 0
        )
    return usage


def parse_json_content(content: str) -> dict[str, Any]:
    """Parse a JSON object from an LLM text response (best-effort).

    Args:
        content: Raw LLM output that should contain JSON.

    Returns:
        The parsed dict, or an empty dict if parsing fails.
    """
    content = content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass
    # Strip markdown code fences if present.
    match = re.search(r"```(?:json)?\s*(.*?)\s*```", content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    # Fall back to first balanced { ... } block.
    start = content.find("{")
    end = content.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(content[start : end + 1])
        except json.JSONDecodeError:
            pass
    return {}
