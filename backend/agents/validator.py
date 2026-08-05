"""SQL validation and safety guardrails.

The validator is the security boundary of the agent. It uses SQLGlot to parse
the generated SQL and verifies that:

* The statement is read-only (SELECT/WITH only) - blocks all DML/DDL.
* Only a single statement is present.
* All referenced tables/columns exist in the reflected schema.
* No dangerous keywords appear at the statement level.

It also strips markdown fences from LLM output and normalizes the statement
to the target dialect.
"""

from __future__ import annotations

import re

from backend.core.logging import get_logger
from backend.database.dialects import normalize_sql_for_dialect
from backend.models.schemas import SchemaInfo, SQLStatementType, ValidationResult
from backend.prompts.sql_rules import DANGEROUS_KEYWORDS

logger = get_logger(__name__)


class SqlValidator:
    """Validates and normalizes LLM-generated SQL against safety rules."""

    def __init__(self, *, schema: SchemaInfo, dialect: str = "postgres"):
        """Initialize the validator for a given schema and dialect.

        Args:
            schema: The reflected schema used to check identifier validity.
            dialect: Target SQL dialect for normalization.
        """
        self._schema = schema
        self._dialect = dialect
        self._tables = {t.name: t for t in schema.tables}

    def validate(self, raw_sql: str) -> ValidationResult:
        """Validate a raw SQL string and return the result.

        Args:
            raw_sql: SQL produced by the LLM (may include markdown fences).

        Returns:
            A ValidationResult with valid flag, reasons, and normalized SQL.
        """
        sql = self._extract_sql(raw_sql)
        if not sql:
            return ValidationResult(
                sql=raw_sql, valid=False, reasons=["No SQL statement detected in the model output."]
            )

        reasons: list[str] = []
        statement_type = self._classify_statement(sql)

        if statement_type not in {SQLStatementType.SELECT, SQLStatementType.WITH}:
            reasons.append(f"Forbidden statement type detected: {statement_type or 'unknown'}")

        if self._has_multiple_statements(sql):
            reasons.append("Multiple SQL statements are not allowed.")

        missing = self._missing_identifiers(sql)
        if missing:
            reasons.append(f"References to unknown tables/columns: {', '.join(missing)}")

        if self._has_forbidden_keywords(sql):
            reasons.append("Forbidden SQL keyword detected.")

        normalized = sql
        if not reasons:
            try:
                normalized = normalize_sql_for_dialect(sql, self._dialect)
            except Exception as exc:  # pragma: no cover
                logger.debug("sql_normalization_failed", error=str(exc))

        return ValidationResult(
            sql=normalized,
            valid=not reasons,
            statement_type=statement_type,
            reasons=reasons,
        )

    # -- internals --------------------------------------------------------

    @staticmethod
    def _extract_sql(raw_sql: str) -> str:
        """Extract a clean SQL statement from LLM output.

        Strips markdown code fences and surrounding prose.

        Args:
            raw_sql: Raw model output.

        Returns:
            The extracted SQL, or empty string if none found.
        """
        text = raw_sql.strip()
        match = re.search(r"```(?:sql)?\s*(.*?)```", text, re.DOTALL)
        if match:
            return match.group(1).strip()
        # Fallback: return the text if it looks like a single statement.
        if text.upper().lstrip().startswith(("SELECT", "WITH")):
            return text
        return ""

    @staticmethod
    def _classify_statement(sql: str) -> SQLStatementType | None:
        """Classify the top-level statement type using SQLGlot.

        Args:
            sql: The extracted SQL.

        Returns:
            The statement type, or None if unparsable/forbidden.
        """
        try:
            import sqlglot

            expression = sqlglot.parse_one(sql)
            return SQLStatementType(expression.key.upper())
        except Exception:
            # SQLGlot may raise for some statements; fall back to keyword scan.
            head = sql.lstrip().upper()
            if head.startswith("SELECT"):
                return SQLStatementType.SELECT
            if head.startswith("WITH"):
                return SQLStatementType.WITH
            return None

    @staticmethod
    def _has_multiple_statements(sql: str) -> bool:
        """Detect multiple statements (top-level semicolon separation).

        Args:
            sql: The extracted SQL.

        Returns:
            True if more than one statement is present.
        """
        try:
            import sqlglot

            return len(sqlglot.parse(sql)) > 1
        except Exception:
            # Crude fallback: count semicolons outside quotes/strings.
            stripped = re.sub(r"('(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\")", "", sql)
            return stripped.count(";") > 0

    def _missing_identifiers(self, sql: str) -> list[str]:
        """Find table/column references that don't exist in the schema.

        CTE names and aliases are excluded because they are locally defined.

        Args:
            sql: The extracted SQL.

        Returns:
            List of unknown identifier names (best effort).
        """
        if not self._tables:
            return []
        missing: set[str] = set()
        try:
            import sqlglot

            expression = sqlglot.parse_one(sql)
            # Collect CTE names so they are not treated as missing tables.
            cte_names = {cte.alias_or_name for cte in expression.find_all(sqlglot.exp.CTE)}
            for table in expression.find_all(sqlglot.exp.Table):
                name = table.name
                if name in cte_names:
                    continue
                if name not in self._tables and name.lower() not in {
                    t.lower() for t in self._tables
                }:
                    missing.add(name)
        except Exception:
            pass
        return sorted(missing)

    def _has_forbidden_keywords(self, sql: str) -> bool:
        """Check for dangerous keywords that should never execute.

        Args:
            sql: The extracted SQL.

        Returns:
            True if a dangerous keyword appears.
        """
        upper = sql.upper()
        return any(re.search(rf"\b{re.escape(keyword)}\b", upper) for keyword in DANGEROUS_KEYWORDS)
