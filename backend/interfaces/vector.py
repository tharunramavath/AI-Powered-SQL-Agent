"""Vector store interface for similarity search over documents."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable


@dataclass
class VectorDocument:
    """A document plus optional metadata stored in the vector index."""

    id: str
    text: str
    metadata: dict[str, str] = field(default_factory=dict)
    score: float = 0.0


@runtime_checkable
class VectorStore(Protocol):
    """Protocol for a vector similarity store (Chroma, PGVector, ...)."""

    def add(self, documents: list[VectorDocument]) -> None:
        """Insert or upsert documents into the index."""
        ...

    def search(self, query: str, *, top_k: int = 5) -> list[VectorDocument]:
        """Return the most similar documents to the query text."""
        ...

    def count(self) -> int:
        """Return the number of indexed documents."""
        ...

    def reset(self) -> None:
        """Clear the index entirely."""
        ...
