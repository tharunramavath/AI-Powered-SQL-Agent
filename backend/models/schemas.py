"""Shared domain DTOs used as the contract between all layers.

These Pydantic models are framework-agnostic and can be imported by any
package (database, agents, prompts, API, frontend-facing contract).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class QueryRequest(BaseModel):
    """Incoming natural-language query from a user."""

    query: str = Field(..., min_length=1, max_length=4000)
    datasource_id: str = "default"
    thread_id: str | None = None
    session_id: str | None = None
    max_rows: int | None = Field(default=None, ge=1, le=1000)


class SQLStatementType(StrEnum):
    """Classified top-level SQL statement type after validation."""

    SELECT = "SELECT"
    WITH = "WITH"


class ValidationResult(BaseModel):
    """Outcome of validating a generated SQL statement."""

    model_config = ConfigDict(extra="forbid")

    sql: str
    valid: bool = True
    statement_type: SQLStatementType | None = None
    reasons: list[str] = Field(default_factory=list)
    is_select_only: bool = True


class ColumnInfo(BaseModel):
    """Metadata for a single database column."""

    name: str
    data_type: str
    nullable: bool = True
    is_primary_key: bool = False
    is_foreign_key: bool = False
    references: str | None = None
    description: str = ""


class TableInfo(BaseModel):
    """Metadata for a single database table."""

    name: str
    schema_name: str | None = None
    columns: list[ColumnInfo] = Field(default_factory=list)
    indexes: list[str] = Field(default_factory=list)
    row_count_estimate: int | None = None
    description: str = ""

    @property
    def qualified_name(self) -> str:
        """Return schema-qualified table name if a schema exists."""
        return f"{self.schema_name}.{self.name}" if self.schema_name else self.name


class SchemaInfo(BaseModel):
    """Full reflected schema for a datasource."""

    datasource_id: str
    dialect: str
    tables: list[TableInfo] = Field(default_factory=list)

    def table_names(self) -> list[str]:
        """Return all table names."""
        return [t.name for t in self.tables]

    def column_names(self, table: str) -> list[str]:
        """Return column names for a given table."""
        for t in self.tables:
            if t.name == table:
                return [c.name for c in t.columns]
        return []


class SQLPlan(BaseModel):
    """Structured understanding of the user's question (planner output)."""

    intent: str
    metrics: list[str] = Field(default_factory=list)
    filters: list[dict[str, Any]] = Field(default_factory=list)
    tables: list[str] = Field(default_factory=list)
    joins: list[str] = Field(default_factory=list)
    aggregations: list[str] = Field(default_factory=list)
    sorting: str | None = None
    window_function: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    needs_approval: bool = False
    explanation: str = ""


class ExecutionStats(BaseModel):
    """Timing and size statistics about a SQL execution."""

    execution_time_ms: float = 0.0
    rows_returned: int = 0
    truncated: bool = False
    estimated_rows_scanned: int | None = None


class ChartType(StrEnum):
    """Chart types the recommender may emit."""

    BAR = "bar"
    LINE = "line"
    PIE = "pie"
    TABLE = "table"


class ChartSpec(BaseModel):
    """A Vega-Lite specification describing a recommended visualization."""

    model_config = ConfigDict(extra="allow")

    type: str = "spec"  # vega-lite spec marker
    vega_lite: dict[str, Any] = Field(default_factory=dict)
    recommended_type: ChartType = ChartType.TABLE
    title: str = ""
    rationale: str = ""


class AgentResult(BaseModel):
    """Structured result of an agent run, returned to the caller."""

    model_config = ConfigDict(extra="ignore")

    sql: str = ""
    plan: SQLPlan | None = None
    columns: list[str] = Field(default_factory=list)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    charts: list[ChartSpec] = Field(default_factory=list)
    summary: str = ""
    execution_stats: ExecutionStats = Field(default_factory=ExecutionStats)
    retries: int = 0
    cached: bool = False
    needs_approval: bool = False
    approval_required: bool = False
    error: str | None = None
    data_truncated: bool = False

    @property
    def row_count(self) -> int:
        """Return number of data rows returned."""
        return len(self.rows)
