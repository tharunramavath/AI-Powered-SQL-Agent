"""LLM provider factory.

Builds an :class:`LLMProvider` from configuration, defaulting to Groq.
The provider name can be overridden via the ``LLM_PROVIDER`` environment
variable (one of: groq, openai, anthropic, gemini).
"""

from __future__ import annotations

import os

from backend.interfaces.llm import LLMProvider
from backend.providers.llms.groq import GroqLLMProvider


def build_llm_provider(
    *,
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    temperature: float = 0.1,
    max_tokens: int = 4096,
) -> LLMProvider:
    """Construct the configured LLM provider adapter.

    Args:
        provider: Provider name. Defaults to env ``LLM_PROVIDER`` or "groq".
        api_key: Vendor API key. Defaults to ``GROQ_API_KEY`` (or the
            provider-specific env var for non-groq providers).
        model: Model id. Defaults to ``GROQ_MODEL``.
        temperature: Sampling temperature.
        max_tokens: Max completion tokens.

    Returns:
        A concrete LLMProvider instance.

    Raises:
        ValueError: If the provider name is unsupported or a required
            API key is missing.
    """
    provider = (provider or os.getenv("LLM_PROVIDER", "groq")).lower()
    api_key = api_key or os.getenv("GROQ_API_KEY", "") or os.getenv("LLM_API_KEY", "")
    model = model or os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

    if not api_key:
        raise ValueError(f"No API key configured for LLM provider '{provider}'")

    if provider == "groq":
        return GroqLLMProvider(
            api_key=api_key, model=model, temperature=temperature, max_tokens=max_tokens
        )

    if provider == "openai":
        from backend.providers.llms.vendors import OpenAILLMProvider

        return OpenAILLMProvider(
            api_key=api_key, model=model, temperature=temperature, max_tokens=max_tokens
        )

    if provider == "anthropic":
        from backend.providers.llms.vendors import AnthropicLLMProvider

        return AnthropicLLMProvider(
            api_key=api_key, model=model, temperature=temperature, max_tokens=max_tokens
        )

    if provider == "gemini":
        from backend.providers.llms.vendors import GeminiLLMProvider

        return GeminiLLMProvider(
            api_key=api_key, model=model, temperature=temperature, max_tokens=max_tokens
        )

    raise ValueError(f"Unsupported LLM provider: '{provider}'")
