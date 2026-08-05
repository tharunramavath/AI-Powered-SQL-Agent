"""Qdrant-backed vector store with local sentence-transformers embeddings.

Embeds documents with ``sentence-transformers`` (all-MiniLM-L6-v2, 384 dims)
locally, so no separate embedding service is required. Supports both Qdrant
server mode (``url``) and embedded local mode (``path``). All Qdrant-specific
calls are confined to this adapter, keeping the rest of the system
vendor-agnostic.
"""

from __future__ import annotations

from typing import Any

from backend.core.logging import get_logger
from backend.interfaces.vector import VectorDocument, VectorStore

logger = get_logger(__name__)

DEFAULT_EMBEDDING_MODEL = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384  # dimensionality of all-MiniLM-L6-v2


class QdrantStore(VectorStore):
    """A Qdrant vector index implementing :class:`VectorStore`."""

    def __init__(
        self,
        *,
        url: str = "",
        path: str = "",
        api_key: str = "",
        collection_name: str = "schema_docs",
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
    ):
        """Initialize the Qdrant client and embedding model (lazily).

        Args:
            url: Qdrant server URL (e.g. http://localhost:6333). If empty,
                local embedded mode using ``path`` is used.
            path: Local persistence directory for embedded mode.
            api_key: Optional Qdrant API key for server mode.
            collection_name: Name of the collection to use.
            embedding_model: Sentence-transformer embedding model name.
        """
        self._url = url
        self._path = path
        self._api_key = api_key
        self._collection_name = collection_name
        self._embedding_model = embedding_model
        self._client: Any = None
        self._encoder: Any = None

    # -- internal helpers -------------------------------------------------

    def _get_client(self):
        """Return the Qdrant client, constructing it on first use."""
        if self._client is None:
            from qdrant_client import QdrantClient

            if self._url:
                self._client = QdrantClient(url=self._url, api_key=self._api_key or None)
            else:
                self._client = QdrantClient(path=self._path or "./.qdrant")
            self._ensure_collection()
        return self._client

    def _get_encoder(self):
        """Return the sentence-transformer encoder, loaded on first use."""
        if self._encoder is None:
            from sentence_transformers import SentenceTransformer

            self._encoder = SentenceTransformer(self._embedding_model)
        return self._encoder

    def _ensure_collection(self) -> None:
        """Create the collection with the correct vector config if missing."""
        from qdrant_client import models

        client = self._client
        existing = client.get_collections().collections
        if not any(c.name == self._collection_name for c in existing):
            client.create_collection(
                collection_name=self._collection_name,
                vectors_config=models.VectorParams(
                    size=EMBEDDING_DIM,
                    distance=models.Distance.COSINE,
                ),
            )

    # -- interface implementation ----------------------------------------

    def add(self, documents: list[VectorDocument]) -> None:
        """Embed and upsert documents into the Qdrant collection.

        Args:
            documents: Documents to index, keyed by their ``id``.
        """
        if not documents:
            return
        from qdrant_client import models

        client = self._get_client()
        texts = [d.text for d in documents]
        vectors = self._get_encoder().encode(texts).tolist()

        points = [
            models.PointStruct(
                id=str(d.id),
                vector=vector,
                payload={
                    "text": d.text,
                    **d.metadata,
                },
            )
            for d, vector in zip(documents, vectors, strict=False)
        ]
        client.upsert(collection_name=self._collection_name, points=points)

    def search(self, query: str, *, top_k: int = 5) -> list[VectorDocument]:
        """Return the most similar documents to the query.

        Args:
            query: The search text.
            top_k: Maximum number of results.

        Returns:
            Ranked list of matching documents with similarity scores.
        """
        try:
            client = self._get_client()
            query_vector = self._get_encoder().encode([query]).tolist()[0]
            result = client.query_points(
                collection_name=self._collection_name,
                query=query_vector,
                limit=top_k,
                with_payload=True,
            )
        except Exception as exc:
            logger.warning("vector_search_failed", error=str(exc))
            return []

        docs: list[VectorDocument] = []
        for point in result.points:
            payload = point.payload or {}
            docs.append(
                VectorDocument(
                    id=str(point.id),
                    text=payload.get("text", ""),
                    metadata={k: str(v) for k, v in payload.items() if k != "text"},
                    score=float(point.score),
                )
            )
        return docs

    def count(self) -> int:
        """Return the number of indexed documents."""
        try:
            client = self._get_client()
            return client.count(collection_name=self._collection_name).count
        except Exception:
            return 0

    def reset(self) -> None:
        """Delete the collection entirely."""
        try:
            self._get_client().delete_collection(self._collection_name)
        except Exception as exc:
            logger.warning("vector_reset_failed", error=str(exc))
