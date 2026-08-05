"""OpenTelemetry setup for tracing and metrics.

Initializes the OTLP exporter, the Prometheus metrics registry, and
instruments FastAPI and SQLAlchemy when enabled. All code in this module is
guarded so that disabling telemetry never breaks the application.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from backend.core.config import Settings
from backend.core.logging import get_logger

if TYPE_CHECKING:
    from prometheus_client import Counter, Histogram

logger = get_logger(__name__)

# Lazy singletons; safe to access after setup_telemetry() when enabled.
_metrics_enabled = False


def setup_telemetry(settings: Settings) -> None:
    """Initialize OpenTelemetry tracing + Prometheus metrics if enabled.

    Args:
        settings: Application settings controlling telemetry flags.
    """
    global _metrics_enabled
    _metrics_enabled = True

    if settings.otel_enabled:
        try:
            from opentelemetry import trace
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.trace import TracerProvider
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            resource = Resource.create({"service.name": settings.app_name})
            provider = TracerProvider(resource=resource)
            provider.add_span_processor(
                BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint))
            )
            trace.set_tracer_provider(provider)

            # Optional auto-instrumentation of FastAPI and SQLAlchemy.
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor  # type: ignore

            _instrument_later = FastAPIInstrumentor
            logger.info(
                "opentelemetry_tracing_enabled", endpoint=settings.otel_exporter_otlp_endpoint
            )
        except Exception as exc:  # pragma: no cover - optional dependency
            logger.warning("opentelemetry_setup_failed", error=str(exc))


def instrument_app(app) -> None:
    """Attach FastAPI instrumentation to an existing ASGI app (best-effort)."""
    if not _metrics_enabled:
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        FastAPIInstrumentor.instrument_app(app)
    except Exception as exc:  # pragma: no cover
        logger.warning("fastapi_instrumentation_failed", error=str(exc))


def _get_metrics():
    """Return the shared prometheus metrics objects (created lazily)."""
    from prometheus_client import Counter, Gauge, Histogram

    class _Metrics:
        def __init__(self) -> None:
            self.queries_total: Counter = Counter(
                "agent_queries_total", "Total agent queries processed", ["datasource", "outcome"]
            )
            self.query_duration: Histogram = Histogram(
                "agent_query_duration_seconds", "Agent query duration in seconds", ["stage"]
            )
            self.sql_retries: Counter = Counter(
                "agent_sql_retries_total", "SQL regeneration retries"
            )
            self.tokens_used: Counter = Counter(
                "agent_tokens_total", "LLM tokens consumed", ["type"]
            )
            self.active_requests: Gauge = Gauge("agent_active_requests", "In-flight agent requests")

    return _Metrics()


_metrics: object | None = None


def get_metrics():
    """Return the process-wide metrics registry (initialized on first call)."""
    global _metrics
    if _metrics is None:
        _metrics = _get_metrics()
    return _metrics
