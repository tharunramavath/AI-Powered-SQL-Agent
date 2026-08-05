"""Interface contracts (Protocols) implemented by all provider adapters.

Packages in this codebase depend only on these interfaces, never on concrete
providers. This makes every adapter swappable and the whole system reusable
from any host application.
"""

from backend.interfaces.cache import CacheBackend
from backend.interfaces.chart import ChartRecommender
from backend.interfaces.database import DatabaseDialect
from backend.interfaces.llm import (
    LLMMessage,
    LLMProvider,
    LLMResponse,
)
from backend.interfaces.memory import MemoryBackend
from backend.interfaces.prompt import PromptRenderer
from backend.interfaces.vector import VectorDocument, VectorStore

__all__ = [
    "CacheBackend",
    "ChartRecommender",
    "DatabaseDialect",
    "LLMMessage",
    "LLMProvider",
    "LLMResponse",
    "MemoryBackend",
    "PromptRenderer",
    "VectorDocument",
    "VectorStore",
]
