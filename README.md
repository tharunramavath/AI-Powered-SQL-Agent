# AI SQL Agent

Production-ready AI SQL Agent: ask questions in natural language and get
answers generated from SQL databases via a LangGraph agent — with a Streamlit
chat UI, streaming, charts, caching, vector retrieval, and observability.

## Features

- **Natural language → SQL → answer** — a LangGraph workflow loads the schema,
  plans the query, generates/validates SQL, executes it read-only, and
  summarizes results.
- **Multi-database** — PostgreSQL, MySQL, SQL Server, SQLite, Snowflake,
  BigQuery via SQLAlchemy (SQLGlot normalization).
- **LLM-agnostic** — Groq by default; OpenAI/Anthropic/Gemini swappable behind
  a `Protocol` interface.
- **Safe by default** — SELECT-only validator (blocks DML/DDL and prompt
  injection), row caps, timeouts, and human approval for expensive queries.
- **Guardrails** — an input gate blocks prompt-injection / unsafe requests
  before planning; an output gate verifies the answer is faithful to the
  returned rows and regenerates it when it is not.
- **Semantic layer** — business metrics/glossary injected into prompts.
- **Chat UI** — Streamlit SPA (`streamlit_app.py`) with live SSE progress,
  Vega-Lite charts, thread history, and a datasource switcher.
- **Caching & retrieval** — Redis result cache (normalized-SQL keys) and a
  Qdrant vector store for schema embeddings.
- **Observable** — LangFuse tracing (traces + LLM generations + eval scores),
  OpenTelemetry, Prometheus metrics.
- **Evaluated** — an eval harness with LLM-as-judge metrics (SQL semantic
  equivalence, answer faithfulness) pushed to LangFuse for comparison over time.
- **Production packaging** — Docker, docker-compose, Helm chart, eval harness.

## Quick start

```bash
cp .env.example .env      # set GROQ_API_KEY (+ DATASOURCE_URL)
uv sync --extra dev --extra ui
uv run ai-sql-agent                            # backend :8000
uv run streamlit run streamlit_app.py          # UI :8501
# open http://localhost:8501
```

Or run the full stack with Docker (deployment guide in docs/DEPLOYMENT.md):

```bash
docker compose up --build
```

## Layout

```
backend/         FastAPI + LangGraph agent (config, interfaces, providers, agents, ...)
streamlit_app.py Simple Streamlit UI (SSE streaming, charts, datasource switcher)
docker/          compose, otel collector, postgres/sqlite seed, Helm chart
tests/           unit, contract, integration (FakeLLM), eval harness + cases
docs/            ARCHITECTURE.md, DEPLOYMENT.md, SETUP_GUIDE.md
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md) — modules, graph, data flow, security.
- [Deployment](docs/DEPLOYMENT.md) — local, Docker, production, environment vars.
- [Setup guide](docs/SETUP_GUIDE.md) — step-by-step environment and install.
- [Project guide](PROJECT_GUIDE.html) — standalone cream/red walkthrough of the whole project (run, test, observe).

## Observability (LangFuse)

1. Create a project at https://cloud.langfuse.com and copy the public/secret keys.
2. Set in `.env`:
   ```
   LANGFUSE_ENABLED=true
   LANGFUSE_PUBLIC_KEY=pk-...
   LANGFUSE_SECRET_KEY=sk-...
   LANGFUSE_HOST=https://cloud.langfuse.com
   LANGFUSE_RELEASE=v0.1.0
   ```
3. Every `/query` run is traced (`sql-agent-run`) with LLM generations, SQL,
   validation/retries, execution stats, and the final result.

## Evaluation

```bash
# Live eval against the default datasource + Groq, pushed to LangFuse
python -m tests.eval.run_eval --datasource default

# A subset of cases
python -m tests.eval.run_eval --case product_count,us_customers
```

Each case is a `sql-agent-eval` trace scored on SQL validity, execution
accuracy, SQL semantic equivalence (LLM-as-judge) and answer faithfulness
(LLM-as-judge). Without LangFuse keys the run still prints a local report.
The same harness is available as `ai-sql-agent-eval` (entry script in
`pyproject.toml`).

## Testing

```bash
uv run pytest     # 88 tests: unit, contract, integration, eval, guardrails, tracing
uv run ruff check .
```
