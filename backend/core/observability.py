"""LangFuse observability (tracing + scoring) for the SQL agent.

The LLM provider is a custom ``Protocol`` rather than a LangChain model, so
LangChain callbacks cannot capture LLM calls automatically. Instead we use
LangFuse's manual SDK: a :class:`TracingService` opens a trace per agent run,
records LLM generations via :class:`TracedLLMProvider` (see
``backend/providers/llms/traced.py``), and attaches evaluation scores.

Everything is guarded by ``langfuse_enabled`` so disabling observability never
breaks the application or the test-suite (which expects a no-op).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from backend.core.config import Settings
from backend.core.logging import get_logger

logger = get_logger(__name__)

_TRACING_ENABLED = False

_current_trace: ContextVar[Any | None] = ContextVar("langfuse_current_trace", default=None)
_current_span: ContextVar[Any | None] = ContextVar("langfuse_current_span", default=None)


class TracingService:
    """Thin wrapper around the LangFuse client.

    When LangFuse is disabled every method becomes a no-op returning ``None``,
    so callers can always pass the result to LangFuse's start/end signatures.
    """

    def __init__(self, client: Any | None = None):
        """Initialize the service with an optional pre-built client.

        Args:
            client: A configured ``langfuse.Langfuse`` instance, or None.
        """
        self._client = client
        self.enabled = client is not None

    # -- lifecycle --------------------------------------------------------

    def current_trace(self) -> Any | None:
        """Return the trace active in the current context (or None)."""
        return _current_trace.get()

    def current_span(self) -> Any | None:
        """Return the span active in the current context (or None)."""
        return _current_span.get()

    @contextmanager
    def trace_context(self, trace: Any, span: Any | None = None) -> Iterator[Any | None]:
        """Make a trace (and optional span) the active context.

        LLM generations started inside the wrapped block attach to the trace.
        Restores the previous context on exit.

        Args:
            trace: The trace to make active.
            span: Optional span to make active.

        Yields:
            The active trace.
        """
        prev_trace = _current_trace.get()
        prev_span = _current_span.get()
        _current_trace.set(trace)
        _current_span.set(span)
        try:
            yield trace
        finally:
            _current_trace.set(prev_trace)
            _current_span.set(prev_span)

    def start_trace(
        self,
        *,
        name: str,
        input: Any = None,
        session_id: str | None = None,
        user_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        release: str | None = None,
    ) -> Any | None:
        """Start a trace for a single agent run.

        Args:
            name: Trace name.
            input: The user input (question).
            session_id: Thread/session identifier.
            user_id: Optional authenticated user id.
            metadata: Additional metadata (datasource, env, ...).
            release: App release version tag.

        Returns:
            A LangFuse trace, or None when tracing is disabled.
        """
        if not self.enabled:
            return None
        kwargs: dict[str, Any] = {"trace": name, "name": name, "input": input}
        if session_id:
            kwargs["session_id"] = session_id
        if user_id:
            kwargs["user_id"] = user_id
        if metadata:
            kwargs["metadata"] = metadata
        if release:
            kwargs["release"] = release
        try:
            return self._client.trace(**kwargs)
        except Exception as exc:  # pragma: no cover - best effort in prod
            logger.warning("langfuse_trace_failed", error=str(exc))
            return None

    def update_trace(
        self,
        trace: Any,
        *,
        output: Any = None,
        metadata: dict[str, Any] | None = None,
        status: str | None = None,
        level: str | None = None,
    ) -> None:
        """Attach the final result/status to a trace.

        Args:
            trace: The trace returned by :meth:`start_trace`.
            output: Final structured result.
            metadata: Additional metadata to merge.
            status: LangFuse trace status tag.
            level: LangFuse trace level tag.
        """
        if not self.enabled or trace is None:
            return
        try:
            trace.update(
                output=output,
                metadata=metadata or {},
                status=status,
                level=level,
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("langfuse_trace_update_failed", error=str(exc))

    def end_trace(self, trace: Any, *, status: str | None = None) -> None:
        """Flush/close a trace.

        Args:
            trace: The trace to close.
            status: Final status tag.
        """
        if not self.enabled or trace is None:
            return
        try:
            if status:
                trace.update(status=status)
            trace.end()
        except Exception as exc:  # pragma: no cover
            logger.warning("langfuse_trace_end_failed", error=str(exc))

    def start_generation(
        self,
        trace: Any,
        span: Any | None = None,
        *,
        name: str = "llm-call",
        model: str = "",
        input: Any = None,
        model_params: dict[str, Any] | None = None,
    ) -> Any | None:
        """Start an LLM generation span.

        Args:
            trace: The parent trace.
            span: Optional parent span.
            name: Generation name.
            model: Model identifier.
            input: The messages/prompt sent to the model.
            model_params: Sampling parameters (temperature, max_tokens).

        Returns:
            A LangFuse generation, or None when disabled.
        """
        if not self.enabled:
            return None
        parent = span if span is not None else trace
        if parent is None:
            return None
        try:
            return parent.generation(
                name=name,
                model=model,
                input=input,
                model_parameters=model_params or {},
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("langfuse_generation_failed", error=str(exc))
            return None

    def end_generation(
        self,
        generation: Any,
        *,
        output: Any = None,
        usage: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        level: str | None = None,
    ) -> None:
        """Finish an LLM generation with output and token usage.

        Args:
            generation: The generation returned by :meth:`start_generation`.
            output: The model response.
            usage: Token usage dict (prompt/completion/total).
            metadata: Additional metadata.
            level: Generation level tag.
        """
        if not self.enabled or generation is None:
            return
        try:
            generation.end(
                output=output,
                usage=usage or {},
                metadata=metadata or {},
                level=level,
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("langfuse_generation_end_failed", error=str(exc))

    def score_trace(
        self,
        trace: Any | None,
        *,
        name: str,
        value: float,
        comment: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Attach an evaluation score to a trace.

        Args:
            trace: The trace to score.
            name: Score name.
            value: Numeric score.
            comment: Optional justification.
            metadata: Optional score metadata.
        """
        if not self.enabled or trace is None:
            return
        trace_id = getattr(trace, "id", None)
        if not trace_id:
            return
        try:
            payload: dict[str, Any] = {
                "trace": trace_id,
                "trace_id": trace_id,
                "name": name,
                "value": value,
            }
            if comment:
                payload["comment"] = comment
            if metadata:
                payload["metadata"] = metadata
            self._client.score(**payload)
        except Exception as exc:  # pragma: no cover
            logger.warning("langfuse_score_failed", error=str(exc))


_service: TracingService | None = None


def setup_observability(settings: Settings) -> None:
    """Initialize the global TracingService from settings.

    Args:
        settings: Application settings controlling observability flags.
    """
    global _TRACING_ENABLED, _service
    _TRACING_ENABLED = bool(settings.langfuse_enabled)
    if not _TRACING_ENABLED:
        _service = TracingService(client=None)
        return
    try:
        from langfuse import Langfuse

        client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
            release=settings.langfuse_release or None,
        )
        _service = TracingService(client=client)
        logger.info("langfuse_tracing_enabled", host=settings.langfuse_host)
    except Exception as exc:  # pragma: no cover
        logger.warning("langfuse_setup_failed", error=str(exc))
        _service = TracingService(client=None)


def get_tracer() -> TracingService:
    """Return the process-wide TracingService.

    Returns:
        The global TracingService (a no-op when observability is disabled).
    """
    global _service
    if _service is None:
        _service = TracingService(client=None)
    return _service