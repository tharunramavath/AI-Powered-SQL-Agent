"""Groq LLM provider adapter (primary default provider)."""

from __future__ import annotations

from typing import Any

from backend.core.logging import get_logger
from backend.providers.llms.base import BaseLangChainLLM

logger = get_logger(__name__)


class GroqLLMProvider(BaseLangChainLLM):
    """LLM provider backed by Groq's fast inference API."""

    json_mode_kwargs = {"response_format": {"type": "json_object"}}

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "llama-3.3-70b-versatile",
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ):
        """Initialize the Groq provider.

        Args:
            api_key: Groq API key.
            model: Groq model id (e.g. llama-3.3-70b-versatile).
            temperature: Sampling temperature.
            max_tokens: Max completion tokens.
        """
        super().__init__(model=model, temperature=temperature, max_tokens=max_tokens)
        self.api_key = api_key

    def _build_chat_model(self) -> Any:
        """Construct a LangChain ChatGroq model instance on each call."""
        from langchain_groq import ChatGroq

        return ChatGroq(
            api_key=self.api_key,
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
