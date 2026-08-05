"""Prompt builders for LLM-as-judge evaluation metrics.

Used by the evaluation harness to (1) compare generated SQL to a reference
semantically (textual equality is too strict for live LLM output) and (2) score
answer faithfulness against the returned rows. These are the same judgment
principles used by the output guardrail.
"""

from __future__ import annotations


def build_sql_equivalence_prompt(
    *,
    question: str,
    generated_sql: str,
    expected_sql: str,
    dialect: str = "sqlite",
) -> str:
    """Build the prompt that judges SQL semantic equivalence.

    Args:
        question: The user question both queries should answer.
        generated_sql: SQL produced by the agent.
        expected_sql: Reference SQL from the evaluation dataset.
        dialect: SQL dialect name (informational).

    Returns:
        The judge prompt requesting a structured JSON verdict.
    """
    return (
        "You are a SQL equivalence judge for a data agent. Two SQL queries are "
        "equivalent if they return the same logical result for the same data, "
        "even when written differently (e.g. different column aliases, "
        "CAST/COALESCE, JOIN order, or formatting).\n"
        'Respond with ONLY a JSON object: {"equivalent": true or false, '
        '"reason": "short justification"}.\n\n'
        f"Question: {question}\n"
        f"Dialect: {dialect}\n"
        f"Generated SQL:\n{generated_sql}\n\n"
        f"Reference SQL:\n{expected_sql}"
    )


def build_answer_correctness_prompt(
    *,
    question: str,
    summary: str,
    expected_rows: int,
    returned_rows: int,
) -> str:
    """Build the prompt that judges whether an answer is correct for a question.

    Args:
        question: The user question.
        summary: The agent's natural-language answer.
        expected_rows: Expected number of result rows.
        returned_rows: Actual number of result rows.

    Returns:
        The judge prompt requesting a structured JSON verdict.
    """
    return (
        "You judge whether an AI assistant's answer to a database question is "
        "correct and complete given the row-count metadata.\n"
        'Respond with ONLY a JSON object: {"correct": true or false, '
        '"reason": "short justification"}.\n\n'
        f"Question: {question}\n"
        f"Returned row count: {returned_rows}\n"
        f"Expected row count: {expected_rows}\n\n"
        f"Assistant answer:\n{summary}"
    )
