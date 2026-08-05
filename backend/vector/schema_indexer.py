"""Schema indexing service for the Qdrant vector store.

Indexes per-table and per-column documentation (plus semantic-layer terms)
so that large schemas can be pruned to a relevant subset before prompt
construction. The index itself is optional; when no vector store is
configured, this service simply returns the full schema.
"""

from __future__ import annotations

from backend.interfaces.vector import VectorDocument, VectorStore
from backend.models.schemas import SchemaInfo


class SchemaIndexer:
    """Builds and queries a vector index of schema + metric documentation."""

    def __init__(self, store: VectorStore | None, *, enabled: bool = True):
        """Initialize the indexer.

        Args:
            store: The underlying vector store, or None to disable indexing.
            enabled: Master switch; if False, retrieval returns nothing.
        """
        self._store = store
        self._enabled = enabled and store is not None

    @property
    def enabled(self) -> bool:
        """Return True if indexing is active."""
        return self._enabled

    def index_schema(self, schema: SchemaInfo) -> int:
        """Embed the schema's tables, columns, and joins into the index.

        Args:
            schema: Reflected schema to index.

        Returns:
            Number of documents indexed.
        """
        if not self._enabled or self._store is None:
            return 0
        docs: list[VectorDocument] = []
        for table in schema.tables:
            docs.append(
                VectorDocument(
                    id=f"table:{schema.datasource_id}:{table.name}",
                    text=f"Table {table.qualified_name}: "
                    + ", ".join(c.name for c in table.columns),
                    metadata={
                        "kind": "table",
                        "table": table.name,
                        "datasource": schema.datasource_id,
                    },
                )
            )
            for col in table.columns:
                docs.append(
                    VectorDocument(
                        id=f"column:{schema.datasource_id}:{table.name}:{col.name}",
                        text=f"Column {table.name}.{col.name} of type {col.data_type}",
                        metadata={
                            "kind": "column",
                            "table": table.name,
                            "column": col.name,
                            "datasource": schema.datasource_id,
                        },
                    )
                )
        self._store.add(docs)
        return len(docs)

    def relevant_schema(self, query: str, schema: SchemaInfo, *, top_k: int = 10) -> SchemaInfo:
        """Return a pruned schema containing only tables relevant to the query.

        When the vector store is unavailable, the full schema is returned.

        Args:
            query: The user question.
            schema: The full reflected schema.
            top_k: Maximum documents to retrieve.

        Returns:
            A SchemaInfo with only the relevant tables.
        """
        if not self._enabled or self._store is None:
            return schema
        hits = self._store.search(query, top_k=top_k)
        relevant_tables: set[str] = set()
        for hit in hits:
            table = hit.metadata.get("table")
            if table:
                relevant_tables.add(table)
        if not relevant_tables:
            return schema
        pruned_tables = [t for t in schema.tables if t.name in relevant_tables]
        if not pruned_tables:
            return schema
        return schema.model_copy(update={"tables": pruned_tables})
