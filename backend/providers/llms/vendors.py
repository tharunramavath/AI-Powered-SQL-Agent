"""Optional LLM provider adapters for OpenAI, Anthropic, and Gemini.

These adapters share the same BaseLangChainLLM base so they are true
drop-in replacements. They are imported lazily so missing vendor packages
never break the default (Groq) path.
"""

from __future__ import annotations

from typing import Any

from backend.providers.llms.base import BaseLangChainLLM


class OpenAILLMProvider(BaseLangChainLLM):
    """LLM provider backed by OpenAI's chat completions API."""

    json_mode_kwargs = {"response_format": {"type": "json_object"}}

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gpt-4o",
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ):
        """Initialize the OpenAI provider.

        Args:
            api_key: OpenAI API key.
            model: OpenAI model id.
            temperature: Sampling temperature.
            max_tokens: Max completion tokens.
        """
        super().__init__(model=model, temperature=temperature, max_tokens=max_tokens)
        self.api_key = api_key

    def _build_chat_model(self) -> Any:
        """Construct a LangChain ChatOpenAI model instance."""
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            api_key=self.api_key,
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )


class AnthropicLLMProvider(BaseLangChainLLM):
    """LLM provider backed by Anthropic's Claude models."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "claude-sonnet-4-5",
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ):
        """Initialize the Anthropic provider.

        Args:
            api_key: Anthropic API key.
            model: Claude model id.
            temperature: Sampling temperature.
            max_tokens: Max completion tokens.
        """
        super().__init__(model=model, temperature=temperature, max_tokens=max_tokens)
        self.api_key = api_key

    def _build_chat_model(self) -> Any:
        """Construct a LangChain ChatAnthropic model instance."""
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            api_key=self.api_key,
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )


class GeminiLLMProvider(BaseLangChainLLM):
    """LLM provider backed by Google's Gemini models."""

    def __init__(
        self,
        *,
        api_key: str,
        model: str = "gemini-2.0-flash",
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ):
        """Initialize the Gemini provider.

        Args:
            api_key: Google API key.
            model: Gemini model id.
            temperature: Sampling temperature.
            max_tokens: Max completion tokens.
        """
        super().__init__(model=model, temperature=temperature, max_tokens=max_tokens)
        self.api_key = api_key

    def _build_chat_model(self) -> Any:
        """Construct a LangChain ChatGoogleGenerativeAI model instance."""
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            google_api_key=self.api_key,
            model=self.model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
        )
