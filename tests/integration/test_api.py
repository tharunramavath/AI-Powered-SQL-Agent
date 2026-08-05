"""API integration tests using FastAPI TestClient with a fake LLM.

Builds the app with an injected fake LLM and an SQLite datasource so the
entire HTTP surface can be exercised without external services.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from backend.app import create_app
from backend.core.config import Settings
from backend.core.container import Container
from backend.models.datasource import DatasourceConfig

from .test_agent_flow import FakeLLM


def _build_test_app(db_path: Path) -> TestClient:
    """Build an app wired to a fake LLM and a file-backed SQLite database."""
    # Seed the file-backed database with the shared schema.
    from tests.conftest import SCHEMA_SQL

    engine = create_engine(f"sqlite:///{db_path}")
    with engine.begin() as conn:
        for stmt in SCHEMA_SQL.split(";"):
            if stmt.strip():
                conn.execute(text(stmt))
    engine.dispose()

    settings = Settings(
        env="test",
        api_keys="test-key",
        cors_origins="http://localhost:5173",
        groq_api_key="fake",
        max_sql_retries=3,
    )
    config = DatasourceConfig(id="test", url=f"sqlite:///{db_path}", dialect="sqlite")
    container = Container(settings=settings, datasources=[config], llm_provider=FakeLLM())
    app = create_app(settings=settings, container=container)
    return TestClient(app)


@pytest.fixture()
def client(tmp_path) -> TestClient:
    """Return a TestClient backed by a seeded file-based SQLite database."""
    return _build_test_app(tmp_path / "test.db")


class TestHealth:
    """Health endpoint."""

    def test_health(self, client):
        resp = client.get("/api/v1/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


class TestAuth:
    """Bearer-token auth."""

    def test_missing_key_rejected(self, client):
        resp = client.post("/api/v1/query", json={"query": "List products"})
        assert resp.status_code == 401

    def test_invalid_key_rejected(self, client):
        resp = client.post(
            "/api/v1/query",
            json={"query": "List products"},
            headers={"Authorization": "Bearer wrong"},
        )
        assert resp.status_code == 401

    def test_valid_key_accepted(self, client):
        resp = client.post(
            "/api/v1/query",
            json={"query": "List products", "datasource_id": "test"},
            headers={"Authorization": "Bearer test-key"},
        )
        assert resp.status_code == 200


class TestQuery:
    """The main query endpoint."""

    def test_end_to_end(self, client):
        resp = client.post(
            "/api/v1/query",
            json={"query": "List products", "datasource_id": "test"},
            headers={"Authorization": "Bearer test-key"},
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["error"] is None
        assert len(payload["rows"]) == 3
        assert payload["sql"].upper().startswith("SELECT")
        assert payload["charts"]

    def test_unknown_datasource(self, client):
        resp = client.post(
            "/api/v1/query",
            json={"query": "List products", "datasource_id": "nope"},
            headers={"Authorization": "Bearer test-key"},
        )
        assert resp.status_code == 404


class TestDatasources:
    """Datasource listing."""

    def test_lists_datasources(self, client):
        resp = client.get(
            "/api/v1/datasources",
            headers={"Authorization": "Bearer test-key"},
        )
        assert resp.status_code == 200
        payload = resp.json()
        assert any(ds["id"] == "test" for ds in payload)


class TestStream:
    """SSE streaming endpoint."""

    def test_streams_result_event(self, client):
        resp = client.post(
            "/api/v1/query/stream",
            json={"query": "List products", "datasource_id": "test"},
            headers={"Authorization": "Bearer test-key"},
        )
        assert resp.status_code == 200
        body = resp.text
        assert "event: result" in body
        assert '"sql"' in body
