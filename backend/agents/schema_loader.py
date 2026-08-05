"""Schema loading node.

Loads the reflected schema for the requested datasource, prunes it to the
tables relevant to the question using the vector index (when available), and
attaches the semantic layer metrics/glossary to the state.
"""

from __future__ import annotations

from typing import Any

from backend.core.logging import get_logger
from backend.interfaces.database import DatabaseDialect
from backend.vector.schema_indexer import SchemaIndexer

logger = get_logger(__name__)


class SchemaLoaderNode:
    """LangGraph node that loads and prunes the database schema."""

    def __init__(
        self,
        *,
        database: DatabaseDialect,
        indexer: SchemaIndexer | None = None,
        metrics: list[Any] | None = None,
        glossary: dict[str, str] | None = None,
    ):
        """Initialize the schema loader.

        Args:
            database: DatabaseDialect used to reflect the schema.
            indexer: Optional vector indexer used to prune the schema.
            metrics: Semantic-layer metric definitions for this datasource.
            glossary: Semantic-layer glossary terms.
        """
        self._database = database
        self._indexer = indexer
        self._metrics = metrics or []
        self._glossary = glossary or {}

    def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """Load the schema for the current state.

        Args:
            state: Current graph state.

        Returns:
            State updates containing the (pruned) schema and semantic layer.
        """
        query = state.get("query", "")
        full_schema = self._database.load_schema()
        logger.info(
            "schema_loaded",
            datasource=self._database.datasource_id,
            tables=len(full_schema.tables),
        )

        if self._indexer is not None and self._indexer.enabled:
            self._indexer.index_schema(full_schema)
            pruned = self._indexer.relevant_schema(query, full_schema)
            logger.info("schema_pruned", kept=len(pruned.tables), of=len(full_schema.tables))
        else:
            pruned = full_schema

        return {
            "schema": pruned,
            "metrics": self._metrics,
            "glossary": self._glossary,
        }
