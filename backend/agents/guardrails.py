"""Input and output guardrail nodes for the SQL agent graph.

The input guardrail runs before any schema reflection or LLM planning. A cheap
heuristic pass blocks clear prompt-injection / forbidden-data requests; an LLM
verdict is only consulted for ambiguous input. The output guardrail runs after
the summary is generated and verifies (with an LLM judge) that the summary is
faithful to the returned rows, regenerating it once when it is not.

Both nodes degrade gracefully: any LLM failure or disabled flag passes the
input through / marks the output faithful so the pipeline is never broken by a
guardrail outage.
"""

from __future__ import annotations

import json
import re
from typing import Any

from backend.core.logging import get_logger
from backend.interfaces.llm import LLMMessage, LLMProvider
from backend.prompts.guardrails import (
    build_input_guardrail_prompt,
    build_output_faithfulness_prompt,
    build_summary_correction_prompt,
)

logger = get_logger(__name__)

# Strong markers that always block without consulting the LLM.
INJECTION_BLOCK_PATTERNS = [
    re.compile(r"\bignore\s+(all\s+)?(previous|prior|the\s+above|above|instructions|system)\b", re.I),
    re.compile(r"\byou\s+are\s+now\b", re.I),
    re.compile(r"\bdeveloper\s*mode\b", re.I),
    re.compile(r"\bjailbreak\b", re.I),
    re.compile(r"\bdisregard\s+(the\s+)?(instructions|system|rules)\b", re.I),
    re.compile(r"\bprint\s+(out\s+)?(the\s+)?(system\s+)?prompt\b", re.I),
    re.compile(r"\bexpose\s+(the\s+)?(system\s+)?prompt\b", re.I),
    re.compile(r"\bforget\s+(everything|all\s+(instructions|rules)|your\s+instructions)\b", re.I),
    re.compile(r"\bnew\s+instructions\b", re.I),
    re.compile(r"\bignore\s+your\s+rules\b", re.I),
]

# Weak markers that only trigger an LLM verdict when present.
SUSPICIOUS_PATTERNS = [
    re.compile(r"\bignore\b", re.I),
    re.compile(r"\bpretend\b", re.I),
    re.compile(r"\bact\s+as\b", re.I),
    re.compile(r"\bas\s+an?\s+(ai|assistant|language\s+model|chatbot|llm|gpt)\b", re.I),
    re.compile(r"\boverride\b", re.I),
    re.compile(r"\bbypass\b", re.I),
    re.compile(r"\brewrite\s+the\s+prompt\b", re.I),
    re.compile(r"\bwithout\s+(following|obeying|respecting)\b", re.I),
    re.compile(r"\b[=\s]*\bDAN\b", re.I),
]

# PII/sensitive-data markers (only enforced when pii_block is enabled).
PII_PATTERNS = [
    re.compile(r"\bssn(s)?\b", re.I),
    re.compile(r"social\s+security\s+(number|#)", re.I),
    re.compile(r"credit\s+card\s+(number|#)?", re.I),
    re.compile(r"passport\s+(number|#)?", re.I),
    re.compile(r"driver'?s\s+license", re.I),
    re.compile(r"\bbank\s+account\b", re.I),
    re.compile(r"routing\s+number", re.I),
    re.compile(r"medical\s+records?", re.I),
    re.compile(r"health\s+records?", re.I),
]

_JSON_SYSTEM = "You are a strict safety evaluator. Respond only with valid JSON."


class InputGuardrailNode:
    """LangGraph node that blocks unsafe or off-topic user input."""

    def __init__(
        self,
        *,
        llm: LLMProvider | None = None,
        enabled: bool = True,
        pii_block: bool = False,
    ):
        """Initialize the input guardrail.

        Args:
            llm: Optional LLM used for ambiguous-case verdicts.
            enabled: Master switch; when False the node always passes input.
            pii_block: When True, requests for PII/sensitive data are blocked.
        """
        self._llm = llm
        self._enabled = enabled
        self._pii_block = pii_block

    def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """Run the input-safety check for the current question.

        Args:
            state: Current graph state containing the user query.

        Returns:
            State updates with guardrail_blocked and guardrail_reason.
        """
        query = state.get("query", "")
        if not self._enabled or not query:
            return {"guardrail_blocked": False, "guardrail_reason": ""}

        reason = self._heuristic_blocked(query)
        if reason:
            logger.warning("input_guardrail_blocked", reason=reason)
            return {"guardrail_blocked": True, "guardrail_reason": reason}

        if self._llm is not None and self._heuristic_suspicious(query):
            verdict = self._llm_verdict(query)
            if verdict and verdict.get("blocked"):
                reason = str(verdict.get("reason") or "Request blocked by policy.")
                logger.warning("input_guardrail_llm_blocked", reason=reason)
                return {"guardrail_blocked": True, "guardrail_reason": reason}

        return {"guardrail_blocked": False, "guardrail_reason": ""}

    # -- internals --------------------------------------------------------

    def _heuristic_blocked(self, query: str) -> str:
        """Return a reason string if the query is clearly unsafe, else ''.

        Args:
            query: The user question.

        Returns:
            A human-readable reason, or empty string when not blocked.
        """
        patterns = list(INJECTION_BLOCK_PATTERNS)
        if self._pii_block:
            patterns.extend(PII_PATTERNS)
        for pattern in patterns:
            match = pattern.search(query)
            if match:
                return f"Detected suspicious request pattern: {match.group(0).strip()}"
        return ""

    @staticmethod
    def _heuristic_suspicious(query: str) -> bool:
        """Return True if weak markers warrant an LLM verdict.

        Args:
            query: The user question.

        Returns:
            True when an LLM verdict should be requested.
        """
        return any(pattern.search(query) for pattern in SUSPICIOUS_PATTERNS)

    def _llm_verdict(self, query: str) -> dict[str, Any] | None:
        """Ask the LLM whether the input should be blocked.

        Args:
            query: The user question.

        Returns:
            The parsed verdict dict, or None if the LLM call fails.
        """
        try:
            messages = [
                LLMMessage(role="system", content=_JSON_SYSTEM),
                LLMMessage(role="user", content=build_input_guardrail_prompt(query)),
            ]
            return self._llm.complete_json(messages, temperature=0.0, structured=True)  # type: ignore[union-attr]
        except Exception as exc:  # pragma: no cover - LLM outage fallback
            logger.warning("input_guardrail_llm_failed", error=str(exc))
            return None


class OutputGuardrailNode:
    """LangGraph node that verifies summary faithfulness to the result rows."""

    def __init__(
        self,
        *,
        llm: LLMProvider | None = None,
        enabled: bool = True,
        render_sample_limit: int = 20,
    ):
        """Initialize the output guardrail.

        Args:
            llm: LLM judge used to verify/regenerate the summary.
            enabled: Master switch; when False the node always passes.
            render_sample_limit: Max rows included in judge prompts.
        """
        self._llm = llm
        self._enabled = enabled
        self._sample_limit = render_sample_limit

    def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """Check (and if needed correct) the generated summary.

        Args:
            state: Current graph state with summary, rows, sql, query.

        Returns:
            State updates with summary (possibly corrected), faithful, and
            guardrail_warning.
        """
        summary = state.get("summary", "")
        if not self._enabled or not self._llm or not summary:
            return {"summary": summary, "faithful": True, "guardrail_warning": ""}

        question = state.get("query", "")
        sql = state.get("sql", "")
        sample = self._sample_rows(state.get("rows", []))

        first = self._check(question, summary, sample, sql)
        if first is None or first.get("faithful", True):
            return {"summary": summary, "faithful": True, "guardrail_warning": ""}

        reason = str(first.get("reason") or "Summary not faithful to returned data.")
        logger.warning("output_guardrail_unfaithful", reason=reason)
        corrected = self._regenerate(question, summary, sample, sql, reason)
        if not corrected:
            return {"faithful": False, "guardrail_warning": reason}

        second = self._check(question, corrected, sample, sql)
        if second is None or second.get("faithful", True):
            return {"summary": corrected, "faithful": True, "guardrail_warning": ""}

        return {
            "summary": corrected,
            "faithful": False,
            "guardrail_warning": "Final summary could not be verified as faithful.",
        }

    # -- internals --------------------------------------------------------

    def _check(self, question: str, summary: str, sample: str, sql: str) -> dict[str, Any] | None:
        """Return the LLM faithfulness verdict for a summary.

        Args:
            question: The user question.
            summary: The summary to verify.
            sample: Serialized sample rows.
            sql: The executed SQL.

        Returns:
            The parsed verdict, or None on failure.
        """
        try:
            messages = [
                LLMMessage(role="system", content=_JSON_SYSTEM),
                LLMMessage(
                    role="user",
                    content=build_output_faithfulness_prompt(
                        question=question,
                        summary=summary,
                        sample_rows=sample,
                        sql=sql,
                    ),
                ),
            ]
            return self._llm.complete_json(messages, temperature=0.0, structured=True)  # type: ignore[union-attr]
        except Exception as exc:  # pragma: no cover - LLM outage fallback
            logger.warning("output_guardrail_llm_failed", error=str(exc))
            return None

    def _regenerate(
        self,
        question: str,
        summary: str,
        sample: str,
        sql: str,
        reason: str,
    ) -> str:
        """Request a corrected, faithful summary from the LLM.

        Args:
            question: The user question.
            summary: The unfaithful summary.
            sample: Serialized sample rows.
            sql: The executed SQL.
            reason: Why the summary was flagged.

        Returns:
            The corrected summary text (possibly empty).
        """
        try:
            messages = [
                LLMMessage(
                    role="system",
                    content="You are a concise data analyst writing faithful, data-grounded answers.",
                ),
                LLMMessage(
                    role="user",
                    content=build_summary_correction_prompt(
                        question=question,
                        summary=summary,
                        sample_rows=sample,
                        sql=sql,
                        reason=reason,
                    ),
                ),
            ]
            return self._llm.complete(messages, temperature=0.2).content.strip()  # type: ignore[union-attr]
        except Exception as exc:  # pragma: no cover
            logger.warning("output_guardrail_regenerate_failed", error=str(exc))
            return ""

    def _sample_rows(self, rows: list[dict[str, Any]]) -> str:
        """Serialize a small sample of rows for the judge prompts.

        Args:
            rows: The result rows.

        Returns:
            A JSON-ish text representation.
        """
        if not rows:
            return "(no rows returned)"
        sample = rows[: self._sample_limit]
        try:
            return json.dumps(sample, default=str, ensure_ascii=False)
        except Exception:  # pragma: no cover
            return "\n".join(str(r) for r in sample)
