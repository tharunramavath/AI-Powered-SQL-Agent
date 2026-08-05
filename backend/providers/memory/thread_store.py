"""In-memory conversation memory backend.

Stores per-thread key/value context and a bounded conversation history.
This is the default backend; a PostgreSQL-backed backend can be added
behind the same :class:`MemoryBackend` interface for production.
"""

from __future__ import annotations

from collections import deque
from threading import Lock
from typing import Any

from backend.interfaces.memory import MemoryBackend


class InMemoryMemoryBackend(MemoryBackend):
    """Thread-safe in-memory storage of conversational context."""

    def __init__(self, *, max_history: int = 40) -> None:
        """Initialize empty per-thread stores.

        Args:
            max_history: Maximum messages retained per thread.
        """
        self._kv: dict[str, dict[str, Any]] = {}
        self._history: dict[str, deque] = {}
        self._lock = Lock()
        self._max_history = max_history

    def put(self, thread_id: str, key: str, value: Any) -> None:
        """Store a key/value under a thread.

        Args:
            thread_id: Thread/session identifier.
            key: Attribute name.
            value: Any JSON-serializable value.
        """
        with self._lock:
            self._kv.setdefault(thread_id, {})[key] = value

    def get(self, thread_id: str, key: str) -> Any | None:
        """Retrieve a value for a thread/key, or None.

        Args:
            thread_id: Thread/session identifier.
            key: Attribute name.
        """
        with self._lock:
            return self._kv.get(thread_id, {}).get(key)

    def add_history(self, thread_id: str, role: str, content: str) -> None:
        """Append a message to the thread's conversation history.

        Args:
            thread_id: Thread/session identifier.
            role: Message role (user/assistant/system).
            content: Message text.
        """
        with self._lock:
            history = self._history.setdefault(thread_id, deque(maxlen=self._max_history))
            history.append({"role": role, "content": content})

    def history(self, thread_id: str, limit: int = 20) -> list[dict[str, str]]:
        """Return the recent history for a thread.

        Args:
            thread_id: Thread/session identifier.
            limit: Maximum number of messages to return.

        Returns:
            List of message dicts (role/content), oldest-first.
        """
        with self._lock:
            return list(self._history.get(thread_id, []))[-limit:]

    def clear(self, thread_id: str) -> None:
        """Remove all memory for a thread.

        Args:
            thread_id: Thread/session identifier.
        """
        with self._lock:
            self._kv.pop(thread_id, None)
            self._history.pop(thread_id, None)
