"""SQL generation rules and guardrails embedded into the system prompt.

These are plain strings so they are easy to audit and extend without
touching code. The validator enforces them programmatically as well.
"""

SQL_RULES = """\
## SQL Generation Rules
- You may ONLY generate SELECT statements. Never generate DELETE, UPDATE,
  INSERT, DROP, ALTER, TRUNCATE, EXECUTE, or any data-modifying statement.
- Always include a LIMIT clause. The maximum allowed rows is {max_rows}.
- Use only tables and columns present in the provided schema. If a table or
  column does not exist in the schema, do not invent it.
- Use JOINs only when they are needed to answer the question.
- Prefer standard SQL features. Use window functions and CTEs when they make
  the query clearer.
- For date filtering, use ISO dates (YYYY-MM-DD) and the target database's
  date functions when possible.
- Do not use multiple statements separated by semicolons. Return exactly one
  statement.
- Do not use comments inside the SQL.
- Quote identifiers only when they contain special characters.
- Use aggregate functions (COUNT, SUM, AVG, MIN, MAX) with appropriate GROUP BY.
"""

DANGEROUS_KEYWORDS = [
    "DELETE",
    "UPDATE",
    "INSERT",
    "DROP",
    "ALTER",
    "TRUNCATE",
    "EXECUTE",
    "CREATE",
    "GRANT",
    "REVOKE",
    "MERGE",
    "REPLACE",
    "COPY",
    "VACUUM",
    "ATTACH",
    "DETACH",
]
