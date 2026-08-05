# AI SQL Agent — Architecture

This document describes the system design, module boundaries, data flow, and
how each layer can be replaced without touching the rest of the codebase.

## High-level view

The agent answers natural-language questions with results from SQL databases.
The core is a **LangGraph workflow** that loads the schema, plans the query,
generates and validates SQL, executes it read-only, and formats an answer with
optional charts. Everything is built behind **interface contracts** so the LLM,
database, cache, vector store, and memory can be swapped independently.

```
                      ┌──────────────────────────────┐
  React SPA (chat)    │         FastAPI API           │
  ───────────────────►│  /query · /query/stream (SSE) │
      (proxy /api)    │  /query/approve · /datasources│
                      └──────────────┬───────────────┘
                                     │ QueryService (domain)
                                     ▼
                 ┌─────────────────────────────────────┐
                 │            Container (DI)            │
                 │  picks concrete adapters per env      │
                 └───────┬──────────┬──────────┬───────┘
                         │          │          │
            ┌────────────▼───┐ ┌────▼──────┐ ┌─▼────────────────┐
            │ LangGraph agent │ │  Redis   │ │ Qdrant (schema   │
            │  (SQLAgent)     │ │  cache   │ │  embeddings)     │
            └───────┬─────────┘ └──────────┘ └──────────────────┘
                    │
        guardrails_in ─► load_schema ─► understand ─► generate_sql ─► validate
            (blocked) ───────────────► fail
           (retry) ◄──────────────── invalid ◄──────────┘
        execute ─► analyze ─► generate_response ─► guardrails_out ─► finalize
```

## Module boundaries (`backend/`)

| Module          | Responsibility                                              | Reusable/portable |
|-----------------|-------------------------------------------------------------|-------------------|
| `models/`       | Framework-agnostic Pydantic DTOs (the contract between layers) | Yes               |
| `interfaces/`   | `Protocol` definitions: `LLMProvider`, `DatabaseDialect`, `CacheBackend`, `VectorStore`, `MemoryBackend`, `PromptRenderer`, `ChartRecommender` | Yes |
| `providers/`    | Concrete adapters implementing the interfaces (Groq, SQLAlchemy, Redis, Qdrant, in-memory) | Yes |
| `database/`     | Dialect registry, schema reflection, read-only executor, optimizer | Yes |
| `prompts/`      | Prompt builders + Jinja templates + rules + semantic layer | Yes |
| `cache/`        | `ResultCache` facade (normalized SQL keys, TTL)             | Yes |
| `memory/`       | `ConversationMemory` facade over a `MemoryBackend`          | Yes |
| `vector/`       | `SchemaIndexer` embedding tables/columns for retrieval      | Yes |
| `agents/`       | LangGraph nodes, graph, validator, chart recommender        | Core |
| `tools/`        | LangChain tools (`ExecuteSqlTool`, `SchemaTool`)            | Yes |
| `core/`         | Config, DI container, logging, telemetry, security          | App-specific |
| `domain/`       | `QueryService` used by the API layer                        | App-specific |
| `app.py`/`api.py`| FastAPI factory + routes                                    | App-specific |

Every module imports interfaces, never other modules' internals, so a new LLM,
database, cache, or vector store is a new provider class registered in the
container.

## Agent graph

Built in `backend/agents/sql_agent.py` with `StateGraph`:

1. **InputGuardrailNode** — runs before any work. A regex pass blocks clear
   prompt-injection / system-prompt-exfiltration requests; an LLM verdict is
   only consulted for ambiguous input. Optional PII blocking is off by default.
2. **SchemaLoaderNode** — reflects the datasource schema (optionally boosted by
   vector-store retrieval of relevant tables).
3. **PlannerNode** — asks the LLM to structure the question (intent, tables,
   metrics, filters, joins) into a `SQLPlan`.
4. **SqlGeneratorNode** — generates SQL from the plan + schema + semantic layer.
   Increments the `attempts` counter.
5. **SqlValidator** — enforces read-only safety: SELECT-only, rejects DML/DDL,
   rejects hallucinated tables/columns, strips markdown fences. Invalid SQL or
   execution errors trigger regeneration up to `max_sql_retries`.
6. **ExecutorNode** — executes with a row cap, timeout, and an optional
   human-approval interrupt for expensive queries (estimated rows ≥ threshold).
7. **FormatterNode** — picks a chart (bar/line/pie/table) and produces a
   natural-language summary.
8. **OutputGuardrailNode** — LLM-judge verifies the summary is faithful to the
   returned rows; an unfaithful summary is regenerated once, then flagged.

A checkpointer (in-memory by default, Postgres optional) supports the approval
interrupt; a `thread_id` is auto-generated when absent.

## Data flow for one query

```
user question ─► QueryRequest (models) ─► QueryService.run()
  ─► agent.invoke(state) ─► nodes ─► AgentResult
     .sql, .columns, .rows, .charts, .summary, .execution_stats
```

Streaming uses `/query/stream` which yields SSE frames of graph state snapshots
and a final `result` event with the complete `AgentResult`.

## Security model

- **Read-only SQL**: the validator rejects any non-`SELECT`/`WITH` statement
  and any reference to unknown tables/columns (defends against prompt injection).
- **Input guardrails**: prompt-injection and system-prompt-exfiltration requests
  are blocked before schema reflection or LLM planning (`guardrails_in`).
- **Output guardrails**: summaries that contradict or invent data beyond the
  returned rows are regenerated, then flagged (`guardrails_out`).
- **Row caps & timeouts**: `MAX_ROWS` and `QUERY_TIMEOUT_SECONDS` bound every
  execution.
- **Human approval**: queries estimated to scan over
  `EXPENSIVE_QUERY_THRESHOLD` rows interrupt for approval.
- **API auth**: optional bearer tokens checked in constant time (`core/security.py`).
- **Secrets**: connection strings may reference env vars (`url_env`) and are
  never returned by `/datasources`.

## Configuration & DI

`core/config.py` uses pydantic-settings (defaults → `.env` → environment).
`core/container.py` maps settings to adapters, e.g.:

| Setting               | Chooses                                              |
|-----------------------|------------------------------------------------------|
| `GROQ_API_KEY`        | `GroqLLMProvider` via `providers/llms/factory.py`    |
| `REDIS_URL`+`CACHE_ENABLED` | `RedisCache`, else `InMemoryCache`           |
| `VECTOR_ENABLED`      | `QdrantStore` (server URL or embedded local path)    |
| `DATASOURCE_URL`      | default datasource merged into the YAML registry     |
| `LANGFUSE_ENABLED`    | `TracedLLMProvider` wrapper + `sql-agent-run` traces |
| `INPUT/OUTPUT_GUARDRAILS_ENABLED` | guardrail nodes in the graph            |

## Observability

- `core/observability.py` initializes the LangFuse client and a `TracingService`.
  `SQLAgent.invoke` records a `sql-agent-run` trace (session = thread_id) with
  LLM generations (via `TracedLLMProvider`), SQL, retries, execution stats, and
  the final result. All guardrail-enabled code degrades to no-ops when
  `LANGFUSE_ENABLED=false`.
- `core/telemetry.py` configures OpenTelemetry + Prometheus metrics
  (query counters, latency, cache hits) with lazy, guarded init.
- `docker/otel/otel-collector.yaml` provides a local OTLP collector.

## Evaluation

`tests/eval/evaluator.py` runs a suite of `(question, expected_sql,
expected_rows)` cases (see `tests/eval/cases.py`) against a live agent and LLM.
Deterministic metrics (SQL validity, exact SQL match, row count) are joined by
LLM-as-judge metrics (SQL semantic equivalence, answer faithfulness). When
LangFuse is enabled each case is logged as a `sql-agent-eval` trace with
scores, so runs can be compared over time in the LangFuse UI:

```bash
python -m tests.eval.run_eval --datasource default
```

## Testing strategy

| Layer     | What it covers                                              |
|-----------|-------------------------------------------------------------|
| unit      | validator, chart recommender, cache, memory, database, optimizer, guardrails, tracing |
| contract  | proves each adapter satisfies its `Protocol`               |
| integration| full agent flow with a `FakeLLM`, API (auth, SSE, approve) |
| eval      | `tests/eval/evaluator.py` measures SQL accuracy, execution accuracy, semantic match, faithfulness, latency, retries |

The `FakeLLM` in `tests/integration/test_agent_flow.py` stands in for Groq so
the whole pipeline runs without API keys.
