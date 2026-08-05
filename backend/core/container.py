"""Dependency injection container.

The container is the single place where concrete adapters are chosen and
wired into services. Every component behind an interface can be swapped here
without touching the rest of the codebase. The container is also used as a
FastAPI dependency so the API layer stays thin.
"""

from __future__ import annotations

import contextlib
from typing import Any

from backend.agents.sql_agent import SQLAgent
from backend.cache.result_cache import ResultCache
from backend.core.config import Settings, get_settings
from backend.core.logging import get_logger
from backend.core.observability import get_tracer, setup_observability
from backend.database.connection import SqlAlchemyDialect
from backend.interfaces.cache import CacheBackend
from backend.interfaces.llm import LLMProvider
from backend.interfaces.vector import VectorStore
from backend.memory.context import ConversationMemory
from backend.models.datasource import DatasourceConfig, load_datasources
from backend.providers.caches.memory_cache import InMemoryCache
from backend.providers.caches.redis_cache import RedisCache
from backend.providers.llms.factory import build_llm_provider
from backend.providers.llms.traced import TracedLLMProvider
from backend.providers.memory.thread_store import InMemoryMemoryBackend
from backend.providers.vector.qdrant_store import QdrantStore
from backend.vector.schema_indexer import SchemaIndexer

logger = get_logger(__name__)


class Container:
    """Wires configuration and providers into a ready-to-use application."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        datasources: list[DatasourceConfig] | None = None,
        llm_provider: LLMProvider | None = None,
    ):
        """Initialize the container.

        Args:
            settings: Application settings; defaults to the cached settings.
            datasources: Datasource list; defaults to those loaded from YAML
                plus any configured via the ``DATASOURCE_URL`` env var.
            llm_provider: Optional pre-built LLM provider (mainly for tests);
                otherwise the provider is built from settings.
        """
        self.settings = settings or get_settings()
        setup_observability(self.settings)
        self.datasources = datasources if datasources is not None else self._resolve_datasources()

        self._llm: LLMProvider | None = llm_provider
        self._cache: CacheBackend | None = None
        self._vector: VectorStore | None = None
        self._memory: InMemoryMemoryBackend | None = None
        self._agents: dict[str, SQLAgent] = {}
        self._dialects: dict[str, SqlAlchemyDialect] = {}

    # -- provider construction ------------------------------------------

    @property
    def llm(self) -> LLMProvider:
        """Return the configured LLM provider (built lazily)."""
        if self._llm is None:
            provider = build_llm_provider(
                api_key=self.settings.groq_api_key,
                model=self.settings.groq_model,
                temperature=self.settings.llm_temperature,
                max_tokens=self.settings.llm_max_tokens,
            )
            self._llm = provider if not get_tracer().enabled else TracedLLMProvider(provider, get_tracer())
        return self._llm

    @property
    def cache(self) -> CacheBackend:
        """Return the configured cache backend (Redis if enabled)."""
        if self._cache is None:
            if self.settings.cache_enabled and self.settings.redis_url:
                try:
                    self._cache = RedisCache(self.settings.redis_url)
                except Exception as exc:
                    logger.warning("redis_unavailable_falling_back", error=str(exc))
                    self._cache = InMemoryCache()
            else:
                self._cache = InMemoryCache()
        return self._cache

    @property
    def vector_store(self) -> VectorStore | None:
        """Return the configured vector store (Qdrant) or None."""
        if self._vector is None and self.settings.vector_enabled:
            self._vector = QdrantStore(
                url=self.settings.qdrant_url,
                path=self.settings.qdrant_path,
                api_key=self.settings.qdrant_api_key,
                collection_name=self.settings.qdrant_collection,
                embedding_model=self.settings.embedding_model,
            )
        return self._vector

    @property
    def result_cache(self) -> ResultCache:
        """Return the query-result cache facade."""
        return ResultCache(self.cache, ttl_seconds=self.settings.cache_ttl_seconds)

    @property
    def memory(self) -> ConversationMemory:
        """Return the conversation memory facade."""
        if self._memory is None:
            self._memory = InMemoryMemoryBackend()
        return ConversationMemory(self._memory)

    @property
    def schema_indexer(self) -> SchemaIndexer:
        """Return the schema vector indexer (disabled when no store is set)."""
        return SchemaIndexer(self.vector_store, enabled=self.settings.vector_enabled)

    # -- datasource wiring ----------------------------------------------

    def _resolve_datasources(self) -> list[DatasourceConfig]:
        """Merge YAML datasources with the env-var default datasource.

        A datasource entry whose ``url_env`` variable is not exported resolves
        to an empty URL; when it matches the configured default id, backfill
        it from ``DATASOURCE_URL`` (already read from ``.env`` by Settings).

        Returns:
            A de-duplicated list of DatasourceConfig objects.
        """
        configs = load_datasources()
        if not self.settings.datasource_url:
            return configs
        for config in configs:
            if config.id == self.settings.datasource_id and not config.url:
                config.url = self.settings.datasource_url
                return configs
        if self.settings.datasource_id not in {c.id for c in configs}:
            configs.append(
                DatasourceConfig(
                    id=self.settings.datasource_id,
                    url=self.settings.datasource_url,
                )
            )
        return configs

    def get_dialect(self, datasource_id: str) -> SqlAlchemyDialect:
        """Return the DatabaseDialect for a datasource id.

        Args:
            datasource_id: Datasource identifier.

        Returns:
            A SqlAlchemyDialect for the datasource.

        Raises:
            KeyError: If the datasource is not registered.
        """
        if datasource_id in self._dialects:
            return self._dialects[datasource_id]
        config = self.get_datasource(datasource_id)
        dialect = SqlAlchemyDialect(config)
        self._dialects[datasource_id] = dialect
        return dialect

    def get_datasource(self, datasource_id: str) -> DatasourceConfig:
        """Return the config for a datasource id.

        Args:
            datasource_id: Datasource identifier.

        Returns:
            The matching DatasourceConfig.

        Raises:
            KeyError: If the datasource is not registered.
        """
        for config in self.datasources:
            if config.id == datasource_id:
                return config
        raise KeyError(f"Datasource '{datasource_id}' is not configured")

    def get_agent(self, datasource_id: str) -> SQLAgent:
        """Return (building if needed) the SQLAgent for a datasource.

        Args:
            datasource_id: Datasource identifier.

        Returns:
            A ready-to-invoke SQLAgent bound to the datasource.
        """
        if datasource_id in self._agents:
            return self._agents[datasource_id]
        config = self.get_datasource(datasource_id)
        dialect = self.get_dialect(datasource_id)
        agent = SQLAgent(
            llm=self.llm,
            database=dialect,
            memory=self.memory,
            indexer=self.schema_indexer,
            metrics=config.metrics,
            glossary=config.glossary,
            max_rows=config.max_rows or self.settings.max_rows,
            timeout_seconds=self.settings.query_timeout_seconds,
            expensive_threshold=self.settings.expensive_query_threshold,
            require_approval=self.settings.require_approval,
            max_sql_retries=self.settings.max_sql_retries,
            cache=self.result_cache,
            tracer=get_tracer(),
            input_guardrails_enabled=self.settings.input_guardrails_enabled,
            output_guardrails_enabled=self.settings.output_guardrails_enabled,
            pii_block=self.settings.guardrail_pii_block,
        )
        self._agents[datasource_id] = agent
        return agent

    def datasource_summaries(self) -> list[dict[str, Any]]:
        """Return safe metadata for each registered datasource (no secrets).

        Returns:
            List of dicts with id, display_name, dialect, max_rows.
        """
        return [
            {
                "id": c.id,
                "display_name": c.display_name,
                "dialect": c.dialect or "auto",
                "max_rows": c.max_rows,
            }
            for c in self.datasources
        ]

    def close(self) -> None:
        """Release pooled connections and other resources."""
        for dialect in self._dialects.values():
            with contextlib.suppress(Exception):
                dialect.close()
        self.cache.close()
