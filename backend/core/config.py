"""Centralized, environment-driven configuration for the application.

Uses :mod:`pydantic_settings` with layered sources (defaults -> .env ->
real environment variables) so the same codebase can run as an API, a CLI,
or a worker without code changes.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Env(StrEnum):
    """Supported runtime environments."""

    DEV = "dev"
    TEST = "test"
    PROD = "prod"


class MemoryBackend(StrEnum):
    """Supported conversation memory backends."""

    MEMORY = "memory"
    POSTGRES = "postgres"


class Settings(BaseSettings):
    """Application settings loaded from defaults, .env, and environment."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # App metadata
    app_name: str = "ai-sql-agent"
    env: Env = Env.DEV
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8000
    log_level: str = "INFO"

    # Security
    api_keys: str = Field(default="", description="Comma-separated bearer API keys")
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    # LLM provider (Groq primary)
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"
    llm_temperature: float = 0.1
    llm_max_tokens: int = 4096

    # Agent behaviour
    max_sql_retries: int = 3
    max_rows: int = 500
    query_timeout_seconds: int = 30
    expensive_query_threshold: int = 1_000_000
    require_approval: bool = False

    # Default datasource
    datasource_url: str = ""
    datasource_id: str = "default"

    # Cache
    redis_url: str = "redis://localhost:6379/0"
    cache_ttl_seconds: int = 300
    cache_enabled: bool = False

    # Vector store (Qdrant)
    vector_enabled: bool = False
    qdrant_url: str = ""
    qdrant_path: str = "./.qdrant"
    qdrant_api_key: str = ""
    qdrant_collection: str = "schema_docs"
    embedding_model: str = "all-MiniLM-L6-v2"

    # Memory / persistence
    memory_backend: MemoryBackend = MemoryBackend.MEMORY
    postgres_checkpoint_dsn: str = ""

    # Observability
    otel_enabled: bool = False
    otel_exporter_otlp_endpoint: str = "http://localhost:4318"
    langfuse_enabled: bool = False
    langfuse_public_key: str = ""
    langfuse_secret_key: str = ""
    # Accept both LANGFUSE_HOST (documented) and LANGFUSE_BASE_URL (a common
    # alias) so the configured region is respected on langfuse 4.x.
    langfuse_host: str = Field(
        default="https://cloud.langfuse.com",
        validation_alias=AliasChoices("langfuse_host", "langfuse_base_url"),
    )
    langfuse_release: str = ""

    # Guardrails
    input_guardrails_enabled: bool = True
    output_guardrails_enabled: bool = True
    guardrail_pii_block: bool = False

    @field_validator("api_keys", "cors_origins")
    @classmethod
    def _split_list(cls, value: str) -> str:
        """Normalize comma-separated fields (validation hook)."""
        return value

    @property
    def api_key_list(self) -> list[str]:
        """Return configured API keys as a non-empty list."""
        return [k.strip() for k in self.api_keys.split(",") if k.strip()]

    @property
    def cors_origin_list(self) -> list[str]:
        """Return configured CORS origins as a list."""
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    """Return the cached, singleton application settings object."""
    return Settings()
