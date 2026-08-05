"""LLM provider adapters and factory.

Each adapter wraps a LangChain chat model behind the :class:`LLMProvider`
protocol, so the rest of the system never depends on a specific vendor SDK.
The :func:`build_llm_provider` factory selects an adapter from configuration.
"""

from backend.providers.llms.factory import build_llm_provider
from backend.providers.llms.groq import GroqLLMProvider

__all__ = ["GroqLLMProvider", "build_llm_provider"]
