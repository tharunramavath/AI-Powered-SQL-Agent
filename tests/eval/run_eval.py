"""Eval suite CLI: run the agent against a live datasource + LLM.

Pushes each case to LangFuse as a ``sql-agent-eval`` trace with scores when
LangFuse is enabled. Without LangFuse keys it still prints a local report.

Usage:
    python -m tests.eval.run_eval [--datasource <id>] [--case c1,c2]
"""

from __future__ import annotations

import argparse
import sys

from backend.core.config import get_settings
from backend.core.container import Container
from backend.core.logging import configure_logging
from tests.eval.cases import load_default_cases
from tests.eval.evaluator import Evaluator


def main(argv: list[str] | None = None) -> int:
    """Run the evaluation suite and print the report.

    Args:
        argv: CLI arguments; defaults to ``sys.argv[1:]``.

    Returns:
        Exit code 0 on success, 1 on failure.
    """
    parser = argparse.ArgumentParser(description="Evaluate the SQL agent.")
    parser.add_argument("--datasource", default="default", help="Datasource id to evaluate against")
    parser.add_argument(
        "--case",
        default="",
        help="Comma-separated case ids to run (default: all).",
    )
    parser.add_argument("--dataset", default="sql-agent-eval", help="LangFuse dataset name")
    args = parser.parse_args(argv)

    configure_logging("INFO")
    settings = get_settings()
    container = Container(settings=settings)

    cases = load_default_cases()
    if args.case:
        wanted = {c.strip() for c in args.case.split(",") if c.strip()}
        cases = [c for c in cases if c.id in wanted]
    if not cases:
        print(f"No eval cases matched: {args.case!r}")
        return 1

    agent = container.get_agent(args.datasource)
    evaluator = Evaluator(agent=agent, cases=cases, llm=container.llm)
    report = evaluator.run(datasource_id=args.datasource, dataset=args.dataset)

    print(report.summary())
    print()
    for ev in report.results:
        status = "OK " if ev.valid and ev.sql_ok else "FAIL"
        print(
            f"[{status}] {ev.case.id:<28} rows={ev.row_count:<3} "
            f"latency={ev.latency_ms:>7.0f}ms retries={ev.retries} "
            f"err={ev.error or ''}"
        )

    ok = report.execution_accuracy == 1.0 and report.sql_accuracy == 1.0
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
