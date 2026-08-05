"""Datasource configuration: connection metadata + semantic layer.

A datasource bundles a SQLAlchemy connection URL with optional schema,
semantic layer (business metrics/glossary), and access metadata. Multiple
datasources can be registered and selected per-query.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.core.security import redact_secrets


class MetricDefinition(BaseModel):
    """A business metric definition in the semantic layer."""

    name: str
    expression: str
    definition: str = ""
    table: str = ""


class DatasourceConfig(BaseModel):
    """Configuration for a single queryable database."""

    model_config = ConfigDict(extra="ignore")

    id: str
    display_name: str = ""
    dialect: str = ""
    url: str = ""
    # When url is empty, resolve from env var named DATASOURCE_URL_<ID upper>
    url_env: str = ""
    allowed_roles: list[str] = Field(default_factory=list)
    max_rows: int = 500
    semantic_layer: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _resolve_url(self) -> DatasourceConfig:
        """Resolve the connection URL from the direct value or env var."""
        if not self.url and self.url_env:
            self.url = os.getenv(self.url_env, "")
        if not self.display_name:
            self.display_name = self.id
        return self

    @property
    def metrics(self) -> list[MetricDefinition]:
        """Parse metric definitions from the semantic layer YAML."""
        metrics = self.semantic_layer.get("metrics", [])
        return [MetricDefinition(**m) for m in metrics]

    @property
    def glossary(self) -> dict[str, str]:
        """Return the glossary (term -> definition) from the semantic layer."""
        return self.semantic_layer.get("glossary", {})

    @property
    def safe_url(self) -> str:
        """Return the connection URL with secrets redacted for logging."""
        return redact_secrets(self.url)


def load_datasources(path: Path | None = None) -> list[DatasourceConfig]:
    """Load datasource configurations from a YAML file.

    Args:
        path: Path to the datasources YAML. Defaults to config/datasources.yaml.

    Returns:
        List of parsed DatasourceConfig objects.
    """
    if path is None:
        path = Path(__file__).parent.parent / "config" / "datasources.yaml"
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return [DatasourceConfig(**item) for item in data.get("datasources", [])]
