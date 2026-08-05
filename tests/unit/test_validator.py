"""Unit tests for the SQL validator (the security boundary)."""

from __future__ import annotations

import pytest

from backend.agents.validator import SqlValidator


@pytest.fixture()
def validator(schema):
    """Return a validator bound to the test schema."""
    return SqlValidator(schema=schema, dialect="sqlite")


class TestValidStatements:
    """Valid read-only SELECT statements must pass."""

    def test_simple_select(self, validator):
        result = validator.validate("SELECT name FROM products")
        assert result.valid is True

    def test_select_with_join(self, validator):
        sql = "SELECT p.name, SUM(o.total_price) AS revenue FROM orders o JOIN products p ON p.id = o.product_id GROUP BY p.name ORDER BY revenue DESC LIMIT 5"
        result = validator.validate(sql)
        assert result.valid is True

    def test_cte_allowed(self, validator):
        sql = "WITH r AS (SELECT product_id, SUM(total_price) AS t FROM orders GROUP BY product_id) SELECT * FROM r"
        result = validator.validate(sql)
        assert result.valid is True

    def test_markdown_fences_stripped(self, validator):
        sql = "```sql\nSELECT name FROM products\n```"
        result = validator.validate(sql)
        assert result.valid is True
        assert result.sql.startswith("SELECT")

    def test_no_limit_still_valid(self, validator):
        result = validator.validate("SELECT * FROM products")
        assert result.valid is True


class TestForbiddenStatements:
    """All data-modifying / dangerous statements must be rejected."""

    @pytest.mark.parametrize(
        "sql",
        [
            "DELETE FROM products WHERE id = 1",
            "UPDATE products SET price = 1",
            "INSERT INTO products (name) VALUES ('x')",
            "DROP TABLE products",
            "ALTER TABLE products ADD COLUMN x INT",
            "TRUNCATE TABLE products",
            "EXEC sp_who",
            "CREATE TABLE x (y INT)",
            "SELECT * FROM products; DROP TABLE products",
            "SELECT * FROM products; DELETE FROM products",
            "GRANT ALL ON products TO public",
        ],
    )
    def test_rejects_dangerous_sql(self, validator, sql: str):
        result = validator.validate(sql)
        assert result.valid is False, f"Expected rejection for: {sql}"
        assert result.reasons, "Expected a reason for rejection"


class TestIdentifierChecks:
    """Hallucinated tables must be rejected."""

    def test_unknown_table_rejected(self, validator):
        result = validator.validate("SELECT * FROM nonexistent_table")
        assert result.valid is False
        assert any("nonexistent_table" in r for r in result.reasons)

    def test_case_insensitive_table_match(self, validator):
        result = validator.validate("SELECT * FROM PRODUCTS")
        assert result.valid is True


class TestPromptInjectionDefense:
    """User attempts to inject SQL must be neutralized."""

    def test_injection_in_question_text(self, validator):
        # The LLM might echo user text; a value-looking injection should not
        # produce a second statement.
        result = validator.validate(
            "SELECT name FROM products WHERE name = 'x'; DROP TABLE products"
        )
        assert result.valid is False
        assert result.reasons
