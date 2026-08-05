"""Unit tests for conversation memory."""

from __future__ import annotations

from backend.memory.context import ConversationMemory


class TestConversationMemory:
    """Memory facade must persist history and context."""

    def test_remember_stores_history(self, conversation_memory):
        conversation_memory.remember("t1", "Show top customers", "Here are the top customers")
        history = conversation_memory.history("t1")
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[1]["role"] == "assistant"

    def test_clear_removes_thread(self, conversation_memory):
        conversation_memory.remember("t1", "q", "a")
        conversation_memory.clear("t1")
        assert conversation_memory.history("t1") == []
        assert conversation_memory.context("t1") == ""

    def test_facts_per_thread_isolated(self, conversation_memory):
        conversation_memory.set_fact("t1", "country", "India")
        conversation_memory.set_fact("t2", "country", "USA")
        assert conversation_memory.context("t1") == ""
        # Facts stored via set_fact are retrievable through the backend.
        assert conversation_memory._backend.get("t1", "country") == "India"

    def test_history_bounded(self, memory_backend):
        memory = ConversationMemory(memory_backend)
        for i in range(50):
            memory.remember("t", f"q{i}", f"a{i}")
        assert len(memory.history("t")) <= 40
