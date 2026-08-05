"""Memory backend interface for conversation context persistence."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class MemoryBackend(Protocol):
    """Protocol for persisting and retrieving conversational context.

    Implementations may store context per thread/session and may optionally
    provide cross-session long-term memory.
    """

    def put(self, thread_id: str, key: str, value: Any) -> None:
        """Store a value under (thread_id, key)."""
        ...

    def get(self, thread_id: str, key: str) -> Any | None:
        """Retrieve a value by (thread_id, key), or None."""
        ...

    def add_history(self, thread_id: str, role: str, content: str) -> None:
        """Append a message to the thread's conversation history."""
        ...

    def history(self, thread_id: str, limit: int = 20) -> list[dict[str, str]]:
        """Return the recent conversation history for a thread."""
        ...

    def clear(self, thread_id: str) -> None:
        """Remove all memory for a thread."""
        ...
