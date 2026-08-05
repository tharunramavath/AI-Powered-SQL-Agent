"""Database schema reflection.

Uses SQLAlchemy's inspector to read tables, columns, primary/foreign keys,
and indexes, then builds the framework-agnostic :class:`SchemaInfo` DTO.
"""

from __future__ import annotations

from sqlalchemy import inspect
from sqlalchemy.engine import Engine

from backend.core.logging import get_logger
from backend.models.schemas import ColumnInfo, SchemaInfo, TableInfo

logger = get_logger(__name__)


def reflect_schema(engine: Engine, datasource_id: str, dialect_name: str) -> SchemaInfo:
    """Reflect the full schema of a database into a SchemaInfo DTO.

    Skips internal/system tables (e.g. Postgres ``pg_*``, SQLite ``sqlite_*``)
    and inspects foreign keys + indexes where the dialect supports it.

    Args:
        engine: SQLAlchemy engine for the target database.
        datasource_id: Datasource identifier used in the result.
        dialect_name: Canonical dialect name for the result.

    Returns:
        A populated SchemaInfo object.
    """
    inspector = inspect(engine)
    table_infos: list[TableInfo] = []

    try:
        table_names = inspector.get_table_names()
    except Exception as exc:  # pragma: no cover - dialect differences
        logger.warning("schema_reflection_failed", datasource=datasource_id, error=str(exc))
        return SchemaInfo(datasource_id=datasource_id, dialect=dialect_name, tables=[])

    # If a default schema exists (Postgres "public", etc.), reflect it too.
    default_schema = None
    try:
        schemas = inspector.get_schema_names()
        default_schema = next(
            (s for s in schemas if s.lower() in {"public", "main"}), schemas[0] if schemas else None
        )
    except Exception:
        pass

    for name in table_names:
        if name.startswith(("pg_", "sqlite_", "_")):
            continue
        table_info = _reflect_table(inspector, name, default_schema)
        if table_info is not None:
            table_infos.append(table_info)

    return SchemaInfo(
        datasource_id=datasource_id,
        dialect=dialect_name,
        tables=table_infos,
    )


def _reflect_table(inspector, name: str, schema: str | None) -> TableInfo | None:
    """Reflect a single table's columns, keys, and indexes.

    Args:
        inspector: SQLAlchemy inspector bound to the engine.
        name: Table name.
        schema: Schema to inspect within (best effort).

    Returns:
        A TableInfo, or None if reflection failed.
    """
    try:
        columns_raw = inspector.get_columns(name, schema=schema)
        pk_raw = set(
            inspector.get_pk_constraint(name, schema=schema).get("constrained_columns", [])
        )
        fks_raw = inspector.get_foreign_keys(name, schema=schema)
        try:
            indexes_raw = [
                i["name"] for i in inspector.get_indexes(name, schema=schema) if i["name"]
            ]
        except Exception:
            indexes_raw = []

        pk_map = {c["name"] for c in columns_raw}
        _ = pk_map
    except Exception as exc:  # pragma: no cover - partial reflection failures
        logger.debug("table_reflection_failed", table=name, error=str(exc))
        return None

    fk_targets: dict[str, str] = {}
    for fk in fks_raw:
        cols = fk.get("constrained_columns") or []
        ref_table = fk.get("referred_table", "")
        for col in cols:
            fk_targets[col] = ref_table

    columns: list[ColumnInfo] = []
    for col in columns_raw:
        columns.append(
            ColumnInfo(
                name=col["name"],
                data_type=str(col.get("type", "")),
                nullable=bool(col.get("nullable", True)),
                is_primary_key=col["name"] in pk_raw,
                is_foreign_key=col["name"] in fk_targets,
                references=fk_targets.get(col["name"]),
            )
        )

    return TableInfo(
        name=name,
        schema_name=schema,
        columns=columns,
        indexes=indexes_raw,
    )
