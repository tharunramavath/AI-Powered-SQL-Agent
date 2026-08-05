"""FastAPI application factory and entry point.

Builds the ASGI app, wires the container, applies CORS/telemetry, and mounts
the API router. The entry point script runs the app with uvicorn.
"""

from __future__ import annotations

import contextlib
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api import router
from backend.core.config import Settings, get_settings
from backend.core.container import Container
from backend.core.logging import configure_logging, get_logger
from backend.core.telemetry import instrument_app, setup_telemetry

logger = get_logger(__name__)


def create_app(settings: Settings | None = None, container: Container | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        settings: Application settings; defaults to cached settings.
        container: A pre-built container (mainly for tests); otherwise a new
            container is created from settings.

    Returns:
        The configured FastAPI app.
    """
    settings = settings or get_settings()
    configure_logging(settings.log_level, json_logs=settings.env.value == "prod")
    setup_telemetry(settings)

    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        """App lifespan: initialize instrumentation and clean up on shutdown."""
        instrument_app(app)
        yield
        with contextlib.suppress(Exception):
            app.state.container.close()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description="Natural language to SQL agent API.",
        lifespan=_lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Wire dependencies and attach to app state for endpoint access.
    app.state.container = container or Container(settings=settings)
    app.state.settings = settings

    app.include_router(router, prefix="/api/v1")

    return app


app = create_app()


def main() -> None:
    """Run the uvicorn server when invoked as ``ai-sql-agent``."""
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "backend.app:app",
        host=settings.host,
        port=settings.port,
        reload=os.getenv("ENV") == "dev",
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()
