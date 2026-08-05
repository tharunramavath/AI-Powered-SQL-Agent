# ai-sql-agent Helm Chart

Deploys the AI SQL Agent backend (FastAPI + LangGraph) and the React frontend
(nginx) to Kubernetes, with optional Postgres, Redis, and Qdrant dependencies.

## Install

```bash
helm install ai-sql-agent ./ai-sql-agent \
  --set-string secret.groqApiKey=YOUR_GROQ_KEY \
  --set datasource.url="postgresql+psycopg://user:pass@pg-host:5432/db"
```

Enable ingress and provide a host:

```bash
helm install ai-sql-agent ./ai-sql-agent \
  --set ingress.enabled=true \
  --set ingress.hosts[0].host=sql-agent.example.com \
  --set ingress.className=nginx
```

## Configuration

The main settings are documented in `values.yaml` and mirror
`backend/core/config.py`. Secrets (`GROQ_API_KEY`, `API_KEYS`,
`LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`) are stored in a Kubernetes
Secret referenced via `secretKeyRef` in the deployment.

Managed Postgres/Redis/Qdrant services can be used by pointing the `datasource`
and `dependencies.*.url` values at them instead of running in-cluster.
