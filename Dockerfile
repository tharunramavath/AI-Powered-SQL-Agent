# ============================================================
# AI SQL Agent - multi-stage production image
# Stage 1: build wheel with uv
# Stage 2: slim runtime
# ============================================================

FROM ghcr.io/astral-sh/uv:0.5-python3.12 AS builder

WORKDIR /build

# Install project (build-time only deps)
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-install-project --no-dev

# Copy sources and build the wheel
COPY backend ./backend
RUN uv build --wheel --no-sources -o /dist

# ------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Runtime system packages (gcc for psycopg binary is not needed, but keep
# minimal set for common dialects; pyodbc needs unixodbc).
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        unixodbc \
        unixodbc-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy the built wheel and the uv-managed virtualenv from builder.
COPY --from=builder /dist /dist
COPY --from=builder /build/.venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Install the project wheel into the runtime venv.
RUN pip install --no-cache-dir /dist/ai_sql_agent-*.whl

# Config assets packaged with the module are copied via the wheel; ensure the
# default config dir exists so volume mounts can layer on top.
RUN mkdir -p /app/config /app/data

COPY backend/config ./config

# Healthcheck hits the FastAPI /healthz endpoint.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

EXPOSE 8000

USER 65534:65534

CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
