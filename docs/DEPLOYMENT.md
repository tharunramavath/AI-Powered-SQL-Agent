# AI SQL Agent — Deployment

## Local development

### Backend

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --extra dev
cp .env.example .env      # add GROQ_API_KEY, DATASOURCE_URL as needed
uv run ai-sql-agent       # uvicorn on :8000
```

Run tests and lint:

```bash
uv run pytest
uv run ruff check .
```

### Frontend

Requires Node 22+.

```bash
cd frontend
npm install
npm run dev               # Vite dev server on :5173, proxies /api to :8000
```

The chat UI, SSE streaming, Vega-Lite charts, approval modal, thread sidebar,
and datasource switcher all run against the local API.

## Docker Compose (recommended)

`docker-compose.yml` starts the full stack:

| Service           | Purpose                          | Port   |
|-------------------|----------------------------------|--------|
| `frontend`        | nginx serving the React SPA      | 8080   |
| `app`             | FastAPI backend                  | 8000   |
| `postgres`        | primary datasource (sample data) | 5432   |
| `redis`           | query-result cache               | 6379   |
| `qdrant`          | vector store for schema retrieval| 6333   |
| `otel-collector`  | OTLP traces/metrics              | 4318   |

```bash
cp .env.example .env        # set GROQ_API_KEY
docker compose up --build
```

Then open http://localhost:8080. The app connects to the compose Postgres
(seeded with a small e-commerce schema in `docker/postgres/init.sql`).

## Production (Docker)

Two images are built:

- `ai-sql-agent:latest` (root `Dockerfile`) — the Python API.
- `ai-sql-agent-frontend:latest` (`frontend/Dockerfile`) — nginx + static SPA,
  proxying `/api` to the `app` service (SSE-friendly: buffering disabled).

Recommended deployment:

- Put nginx/frontend behind a TLS-terminating load balancer or ingress.
- Use a managed Postgres/Redis/Qdrant instead of compose containers.
- Set `REQUIRE_APPROVAL=true` for expensive queries in shared environments.
- Set `API_KEYS` to enable bearer auth; the frontend sends
  `Authorization: Bearer` when `VITE_API_KEY` is set at build time.
- Point `OTEL_EXPORTER_OTLP_ENDPOINT` at your tracing backend and set the
  `LANGFUSE_*` variables (Cloud keys or a self-hosted LangFuse host).

## Kubernetes (Helm)

See `docker/helm/ai-sql-agent/` for a chart that deploys the app, frontend,
and optional dependencies (Postgres/Redis/Qdrant) with configurable resources,
secrets, and an ingress.

## Environment reference

See `.env.example` for the full list. Key variables:

| Variable                      | Purpose                                  |
|-------------------------------|------------------------------------------|
| `GROQ_API_KEY`                | LLM provider key (Groq)                  |
| `DATASOURCE_URL`              | default datasource SQLAlchemy URL        |
| `CACHE_ENABLED` / `REDIS_URL` | result caching                           |
| `VECTOR_ENABLED` / `QDRANT_URL`| schema embedding/retrieval               |
| `REQUIRE_APPROVAL`            | force human approval on all queries      |
| `EXPENSIVE_QUERY_THRESHOLD`   | row-scan threshold triggering approval   |
| `INPUT_GUARDRAILS_ENABLED`    | block prompt-injection before planning   |
| `OUTPUT_GUARDRAILS_ENABLED`   | verify summary faithfulness to the rows  |
| `GUARDRAIL_PII_BLOCK`         | also block PII/sensitive-data requests   |
| `OTEL_ENABLED`                | OpenTelemetry export                     |
| `LANGFUSE_ENABLED`            | enable LangFuse tracing + eval scoring   |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | LangFuse Cloud auth        |
| `LANGFUSE_HOST`               | LangFuse host (default Cloud)            |
