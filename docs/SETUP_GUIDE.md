# Setup Guide — Credentials & Environment

This guide walks you through everything you need to get the AI SQL Agent
running end-to-end. You only strictly need **two things** to start asking
questions:

1. **Groq API key** (to power the LLM that generates SQL)
2. **A database connection string** (to query against)

Everything else (Redis, Qdrant, LangFuse) is optional and covered at the end.

---

## 1. Groq API Key (REQUIRED — powers the AI)

Groq provides fast, free-tier LLM inference. This is the model that turns your
natural-language question into SQL.

### Steps

1. Go to **https://console.groq.com**
2. Click **"Sign up"** (top-right). You can sign up with Google, GitHub, or email.
3. After logging in, open **https://console.groq.com/keys**
   (or click **API Keys** in the left sidebar).
4. Click **"Create API Key"**.
5. Give it a name (e.g. `ai-sql-agent`) and click **Create**.
6. **Copy the key immediately** — it is shown only once.
   It looks like: `gsk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx`

### Where it goes

Open `.env` (already created from the template) and paste it:

```ini
GROQ_API_KEY=gsk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

**Do not share this key or commit it to git** — `.env` is already in
`.gitignore`.

---

## 2. Database Connection (REQUIRED — the data to query)

The agent queries whatever database you point it at. Pick **one** of the
options below. Option A is the easiest.

### Option A — Postgres via Docker (recommended, ~2 min)

If you have Docker Desktop installed:

1. The project already includes a Postgres service in `docker-compose.yml`
   with a seeded sample schema (`docker/postgres/init.sql`).
2. Just start the database containers:

   ```bash
   docker compose up -d postgres redis
   ```

3. Your connection string is then:

   ```ini
   DATASOURCE_URL=postgresql+psycopg://agent:agent@localhost:5432/agent
   ```

   That connects as user `agent` / password `agent` to database `agent` on your
   local machine. It already contains sample e-commerce tables
   (`products`, `customers`, `orders`).

**No Docker?** Install PostgreSQL locally from https://www.postgresql.org/
then create a database and user, or use Option B/C below.

### Option B — Cloud Postgres (free tier)

Free hosted Postgres you can reach from anywhere:

- **Neon** — https://neon.tech → create a free project, copy the connection
  string ("Connection string" → `psql` tab).
- **Supabase** — https://supabase.com → new project → Settings → Database →
  Connection string.

Both give you a URL like:

```
postgresql://USER:PASSWORD@host/dbname?sslmode=require
```

Paste it into `.env`:

```ini
DATASOURCE_URL=postgresql://USER:PASSWORD@host/dbname?sslmode=require
```

> Note: with a fresh cloud DB the tables are empty, so questions would return
> "no rows". Use Option A to get sample data, or run the seed SQL from
> `docker/postgres/init.sql` against your cloud DB.

### Option C — SQLite (zero setup, for testing only)

If you just want to confirm the pipeline works with no database server at all,
SQLite works with zero install. Create a seeded test database using the bundled
sample schema:

```bash
# from the project root
python -c "import sqlite3; sqlite3.connect('data.db').executescript(open('docker/sqlite/init.sql', encoding='utf-8').read())"
```

Then:

```ini
DATASOURCE_URL=sqlite:///./data.db
```

The seed creates `products`, `customers`, and `orders` tables with a small
e-commerce dataset, so the agent has something to answer.

> SQLite is fine for a quick demo but not recommended for production.

---

## 3. Optional Services (add if you want these features)

Each is controlled by a flag in `.env`. Leave them **disabled** (`false`) to
start; enable later.

### Redis — query result caching

Speeds up repeated questions. Run locally:

```bash
docker compose up -d redis
```

```ini
CACHE_ENABLED=true
REDIS_URL=redis://localhost:6379/0
```

### Qdrant — schema vector retrieval

Helps the agent find the right tables for large schemas. Requires a Python
embedding model on first use (downloads ~80 MB).

```bash
docker compose up -d qdrant
```

```ini
VECTOR_ENABLED=true
QDRANT_URL=http://localhost:6333
```

### LangFuse — run tracing / evaluation

Optional observability. Create a project at https://cloud.langfuse.com,
then copy the public/secret keys:

```ini
LANGFUSE_ENABLED=true
LANGFUSE_PUBLIC_KEY=pk-xxxxxxxxxxxxxxxxxxxxxxxx
LANGFUSE_SECRET_KEY=sk-xxxxxxxxxxxxxxxxxxxxxxxx
LANGFUSE_HOST=https://cloud.langfuse.com
```

Every agent run is then traced (`sql-agent-run`), and the eval harness scores
cases into the same project (`sql-agent-eval`): `python -m tests.eval.run_eval`.

---

## 4. Security settings (optional)

- **`API_KEYS`** — comma-separated bearer tokens. Leave empty for local dev
  (auth disabled); set real tokens in shared/prod environments.
- **`REQUIRE_APPROVAL`** — set `true` to force a human-approval step on every
  query (useful for shared environments).

---

## 5. Verify & Run

After editing `.env`, verify the backend can read everything:

```bash
uv run python -c "from backend.core.config import get_settings; s=get_settings(); print('Groq key set:', bool(s.groq_api_key)); print('Datasource:', s.datasource_url or '(none)')"
```

Then start the backend:

```bash
uv run ai-sql-agent
```

You should see uvicorn on `http://0.0.0.0:8000`. Then start the Streamlit UI
and it will show your database in the switcher, and chat will work:

```bash
uv run streamlit run streamlit_app.py
# open http://localhost:8501
```

### Smoke test the API

```bash
curl http://localhost:8000/api/v1/health
# {"status":"ok","service":"ai-sql-agent"}
```

---

## Restart the session (pick up where you left off)

### Resume this opencode coding session

From the **project root**, run:

```bash
# Resume the most recent opencode session (same conversation)
opencode --continue

# Or use the short flag
opencode -c

# Or resume a specific session by ID
opencode --session <session-id>
```

To find your previous session IDs:

```bash
opencode session list
```

Then ask the agent to start the app stack with the commands below.

### Start the app stack

Run these from the **project root** to bring the whole stack back up:

```bash
# 1. Start infra (Postgres, Redis, Qdrant) in the background
docker compose up -d postgres redis qdrant

# 2. Start the backend API on :8000 (leave this terminal open)
uv run ai-sql-agent

# 3. In a second terminal, start the Streamlit UI on :8501
uv run streamlit run streamlit_app.py
```

Then open **http://localhost:8501** and continue chatting. Verify the backend
is healthy with:

```bash
curl http://localhost:8000/api/v1/health
# {"status":"ok","service":"ai-sql-agent"}
```

> The Streamlit app calls the backend API directly (`http://localhost:8000`),
> so no proxy config is needed. To stop everything later: `docker compose down`
> (add `-v` only if you also want to delete the seeded data).

---

## Checklist

| Item                          | Required | Where to get it                          | Env var              |
|-------------------------------|----------|------------------------------------------|----------------------|
| Groq API key                  | Yes      | https://console.groq.com/keys            | `GROQ_API_KEY`       |
| Database connection string    | Yes      | Docker (Option A), Neon/Supabase (B), SQLite (C) | `DATASOURCE_URL` |
| Redis URL                     | Optional | `docker compose up -d redis`             | `REDIS_URL` + `CACHE_ENABLED=true` |
| Qdrant URL                    | Optional | `docker compose up -d qdrant`            | `QDRANT_URL` + `VECTOR_ENABLED=true` |
| LangFuse keys                 | Optional | https://cloud.langfuse.com               | `LANGFUSE_PUBLIC_KEY` + `LANGFUSE_SECRET_KEY` |

Once Groq + database are set, tell the assistant and it will start the backend
for you.



 Session   Build production AI SQL agent
  Continue  opencode -s ses_046595f2bfferqOC4Shyjyqgej