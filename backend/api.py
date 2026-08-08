"""FastAPI routes for the AI SQL Agent.

Keeps the HTTP layer thin: every endpoint delegates to the domain
:class:`QueryService`. Streaming responses use SSE so the frontend can
receive agent progress tokens.
"""

from __future__ import annotations

import asyncio
import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from backend.core.container import Container
from backend.core.security import validate_api_key
from backend.domain.services import QueryService
from backend.models.schemas import AgentResult, QueryRequest

router = APIRouter()
bearer = HTTPBearer(auto_error=False)


def _get_service(request: Request) -> QueryService:
    """Resolve the QueryService from the app state (FastAPI dependency)."""
    container: Container = request.app.state.container
    return QueryService(container)


def _require_auth(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    request: Request,
) -> None:
    """Reject requests when API keys are configured and none is provided.

    Args:
        credentials: The bearer token, if any.
        request: The incoming request.

    Raises:
        HTTPException: 401 when a valid token is required but absent/invalid.
    """
    container: Container = request.app.state.container
    valid_keys = container.settings.api_key_list
    if not valid_keys:
        return  # auth disabled in dev
    if credentials is None or validate_api_key(credentials.credentials, valid_keys) is None:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    """Liveness/readiness probe.

    Args:
        request: Incoming request.

    Returns:
        Service name and status.
    """
    return {"status": "ok", "service": request.app.state.container.settings.app_name}


@router.get("/metrics")
async def metrics() -> Response:
    """Prometheus-format metrics endpoint.

    Returns:
        Metrics in text exposition format.
    """
    from prometheus_client import generate_latest

    return Response(
        content=generate_latest(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@router.get("/datasources", dependencies=[Depends(_require_auth)])
async def list_datasources(request: Request) -> list[dict[str, Any]]:
    """List registered datasources (secrets redacted).

    Args:
        request: Incoming request.

    Returns:
        List of datasource metadata.
    """
    return _get_service(request).list_datasources()


@router.post("/query", dependencies=[Depends(_require_auth)])
async def run_query(request: Request, query: QueryRequest) -> AgentResult:
    """Run a natural-language query against the target datasource.

    Args:
        request: Incoming request.
        query: The query request body.

    Returns:
        The structured AgentResult.

    Raises:
        HTTPException: 404 for unknown datasources, 500 for agent failures.
    """
    service = _get_service(request)
    try:
        return await asyncio.to_thread(service.run, query)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/query/approve", dependencies=[Depends(_require_auth)])
async def approve_query(
    request: Request,
    payload: dict[str, Any],
) -> AgentResult:
    """Resume an interrupted run after a human approval decision.

    Args:
        request: Incoming request.
        payload: Dict with thread_id, datasource_id, and approved flag.

    Returns:
        The final AgentResult.

    Raises:
        HTTPException: On missing/invalid approval payload.
    """
    thread_id = payload.get("thread_id")
    datasource_id = payload.get("datasource_id", "default")
    approved = bool(payload.get("approved", False))
    if not thread_id:
        raise HTTPException(status_code=400, detail="thread_id is required to resume a query")
    service = _get_service(request)
    try:
        return await asyncio.to_thread(
            service.resume,
            thread_id=thread_id,
            datasource_id=datasource_id,
            approved=approved,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/query/stream", dependencies=[Depends(_require_auth)])
async def stream_query(request: Request, query: QueryRequest):
    """Stream an agent run over Server-Sent Events.

    Args:
        request: Incoming request.
        query: The query request body.

    Yields:
        SSE ``data`` events for each graph state snapshot and a final
        ``result`` event carrying the complete AgentResult.
    """
    from fastapi.responses import StreamingResponse

    service = _get_service(request)

    async def _event_stream():
        last_result = None
        try:
            async for snapshot in service.stream(query):
                if snapshot.get("result") is not None:
                    last_result = snapshot["result"]
                yield f"data: {json.dumps(snapshot, default=str)}\n\n"
                await asyncio.sleep(0)
        except KeyError as exc:
            yield f"event: error\ndata: {json.dumps({'detail': str(exc)})}\n\n"
            return
        except Exception as exc:  # pragma: no cover
            yield f"event: error\ndata: {json.dumps({'detail': str(exc)})}\n\n"
            return

        if last_result is None:
            yield f"event: error\ndata: {json.dumps({'detail': 'Agent finished without a result.'})}\n\n"
            return
        yield f"event: result\ndata: {last_result.model_dump_json()}\n\n"

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
