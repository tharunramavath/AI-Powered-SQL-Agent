"""Structured logging built on structlog.

Provides a process-wide ``structlog`` configuration and a ``get_logger``
helper. Log output is JSON in production and pretty-console in development.
OpenTelemetry trace/span IDs are injected into every log record so logs can
be correlated with traces.
"""

from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(level: str = "INFO", *, json_logs: bool = False) -> None:
    """Configure structlog and the stdlib logging bridge.

    Args:
        level: Logging level string (INFO, DEBUG, ...).
        json_logs: If True emit JSON lines, otherwise pretty console output.
    """

    def _add_otel_fields(logger: object, method_name: str, event_dict: dict) -> dict:
        """Attach OpenTelemetry trace/span ids to the log event if available."""
        try:
            from opentelemetry import trace

            span = trace.get_current_span()
            if span is not None and span.is_recording():
                ctx = span.get_span_context()
                event_dict["trace_id"] = format(ctx.trace_id, "032x")
                event_dict["span_id"] = format(ctx.span_id, "016x")
        except Exception:  # pragma: no cover - otel optional
            pass
        return event_dict

    shared_processors: list = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        _add_otel_fields,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if json_logs:
        processors: list = [
            *shared_processors,
            structlog.processors.JSONRenderer(),
        ]
    else:
        processors = [
            *shared_processors,
            structlog.dev.ConsoleRenderer(),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Route stdlib logging (uvicorn, sqlalchemy, etc.) through structlog.
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            foreign_pre_chain=[
                structlog.stdlib.add_log_level,
                structlog.stdlib.add_logger_name,
            ],
            processors=[
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.dev.ConsoleRenderer()
                if not json_logs
                else structlog.processors.JSONRenderer(),
            ],
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level.upper())


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Return a bound structlog logger, optionally namespaced by module name."""
    return structlog.get_logger(name or __name__)
