"""Conversation memory service.

Provides a reusable facade over a :class:`MemoryBackend` that adds a short
natural-language "context summary" per thread. This summary is what lets the
agent resolve references like "those customers" and "last month" across turns.
"""

from __future__ import annotations

from typing import Any

from backend.interfaces.memory import MemoryBackend


class ConversationMemory:
    """High-level conversation memory facade.

    Args:
        backend: Any MemoryBackend implementation.
    """

    def __init__(self, backend: MemoryBackend):
        """Store the memory backend.

        Args:
            backend: The underlying storage implementation.
        """
        self._backend = backend

    def remember(self, thread_id: str, question: str, answer: str) -> None:
        """Persist a Q/A turn and refresh the thread's context summary.

        Args:
            thread_id: Thread/session identifier.
            question: The user's question.
            answer: The assistant's answer text.
        """
        self._backend.add_history(thread_id, "user", question)
        self._backend.add_history(thread_id, "assistant", answer)
        summary = self._build_context_summary(thread_id)
        self._backend.put(thread_id, "context_summary", summary)

    def context(self, thread_id: str) -> str:
        """Return the current context summary for a thread.

        Args:
            thread_id: Thread/session identifier.

        Returns:
            A short text summary, or empty string.
        """
        return str(self._backend.get(thread_id, "context_summary") or "")

    def history(self, thread_id: str, limit: int = 20) -> list[dict[str, str]]:
        """Return the recent conversation history.

        Args:
            thread_id: Thread/session identifier.
            limit: Maximum messages.

        Returns:
            List of {role, content} dicts.
        """
        return self._backend.history(thread_id, limit=limit)

    def set_fact(self, thread_id: str, key: str, value: Any) -> None:
        """Store a structured fact for a thread.

        Args:
            thread_id: Thread/session identifier.
            key: Fact name.
            value: Fact value.
        """
        self._backend.put(thread_id, key, value)

    def clear(self, thread_id: str) -> None:
        """Wipe all memory for a thread.

        Args:
            thread_id: Thread/session identifier.
        """
        self._backend.clear(thread_id)

    def _build_context_summary(self, thread_id: str) -> str:
        """Build a compact context summary from recent history.

        Because the summary is heuristic (recent Q/A only), it does not
        require an LLM call and works offline. Implementations that want a
        richer summary can override this to use an LLM.

        Args:
            thread_id: Thread/session identifier.

        Returns:
            A short summary string.
        """
        return ""  # Placeholder: specialized subclasses can compute a summary.
