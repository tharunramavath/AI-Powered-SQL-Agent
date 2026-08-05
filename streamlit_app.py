"""Simple Streamlit UI for the AI SQL Agent.

Talks to the FastAPI backend over its HTTP API, consuming the live
Server-Sent Events stream from ``POST /api/v1/query/stream`` so the user
sees the agent progress (schema -> plan -> SQL -> execute -> answer) as it
happens, then renders the final SQL, charts, data table, and summary.

Usage (backend must already be running on :8000):
    uv run streamlit run streamlit_app.py      # open http://localhost:8501
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

import httpx
import streamlit as st

API_BASE = os.getenv("AI_SQL_AGENT_API", "http://localhost:8000/api/v1")
API_KEY = os.getenv("AI_SQL_AGENT_API_KEY", "")
MAX_TIMEOUT_SECONDS = 300

st.set_page_config(page_title="AI SQL Agent", page_icon=":database:", layout="wide")


# -- API helpers -----------------------------------------------------------

def _headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    api_key = st.session_state.get("api_key") or API_KEY
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


@st.cache_data(ttl=30, show_spinner=False)
def fetch_datasources(base_url: str) -> list[dict[str, Any]]:
    """Return the registered datasource summaries from the backend."""
    resp = httpx.get(f"{base_url}/datasources", timeout=10)
    resp.raise_for_status()
    return resp.json()


@st.cache_data(ttl=15, show_spinner=False)
def fetch_health(base_url: str) -> dict[str, Any] | None:
    """Return backend health info, or None when unreachable."""
    try:
        resp = httpx.get(f"{base_url}/health", timeout=5)
        resp.raise_for_status()
        return resp.json()
    except httpx.HTTPError:
        return None


def _stage_label(snapshot: dict[str, Any]) -> str:
    """Map the latest agent state snapshot to a human-readable stage label."""
    if "schema" in snapshot and "plan" not in snapshot:
        return "Loading database schema..."
    if "plan" in snapshot and "sql" not in snapshot:
        return "Understanding the question..."
    if "sql" in snapshot and "columns" not in snapshot:
        return "Generating & validating SQL..."
    if "rows" in snapshot:
        return "Executing query & formatting answer..."
    return "Working..."


def stream_query(
    question: str,
    datasource_id: str,
    thread_id: str,
    base_url: str,
    status: Any,
) -> dict[str, Any]:
    """Run one streaming query and return the final AgentResult dict.

    Args:
        question: The user's natural-language question.
        datasource_id: Datasource to query.
        thread_id: Conversation thread id (kept stable per browser session).
        base_url: Backend API base URL.
        status: An ``st.status`` container updated live with progress.

    Returns:
        The parsed ``AgentResult`` JSON dict.

    Raises:
        httpx.HTTPError: On transport-level failures.
        RuntimeError: When the backend reports an ``event: error``.
    """
    payload = {
        "query": question,
        "datasource_id": datasource_id,
        "thread_id": thread_id,
    }
    with httpx.stream(
        "POST",
        f"{base_url}/query/stream",
        json=payload,
        headers=_headers(),
        timeout=MAX_TIMEOUT_SECONDS,
    ) as resp:
        resp.raise_for_status()

        frame_lines: list[str] = []
        for line in resp.iter_lines():
            if line == "":
                event, data = _parse_frame(frame_lines)
                frame_lines = []
                if data is None:
                    continue
                if event == "result":
                    return json.loads(data)
                if event == "error":
                    detail = json.loads(data).get("detail", data)
                    raise RuntimeError(f"Backend error: {detail}")
                # A state snapshot (default event name).
                status.update(label=_stage_label(json.loads(data)))
            else:
                frame_lines.append(line)
        raise RuntimeError("Stream ended without a result event.")


def _parse_frame(lines: list[str]) -> tuple[str, str | None]:
    """Parse one SSE frame into (event_name, data_payload)."""
    event = "message"
    data_parts: list[str] = []
    for raw in lines:
        line = raw.rstrip("\r")
        if line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data_parts.append(line[5:].strip())
    return event, "\n".join(data_parts) if data_parts else None


# -- rendering -------------------------------------------------------------

def render_result(res: dict[str, Any]) -> None:
    """Render a full AgentResult dict (error, SQL, plan, charts, table, stats)."""
    if res.get("error"):
        st.error(res["error"])
        return

    if res.get("needs_approval"):
        st.warning("This query requires approval, which this simple UI does not support.")

    summary = res.get("summary")
    if summary:
        st.markdown(summary)

    sql = res.get("sql")
    if sql:
        with st.expander("Generated SQL", expanded=sql is not None):
            st.code(sql, language="sql")

    plan = res.get("plan")
    if plan:
        with st.expander("Agent plan"):
            st.write(f"**Intent:** {plan.get('intent', '') or '—'}")
            if plan.get("explanation"):
                st.write(plan["explanation"])
            cols = st.columns(2)
            cols[0].write(f"**Tables:** {', '.join(plan.get('tables') or []) or '—'}")
            cols[0].write(f"**Metrics:** {', '.join(plan.get('metrics') or []) or '—'}")
            cols[1].write(f"**Joins:** {', '.join(plan.get('joins') or []) or '—'}")
            cols[1].write(f"**Filters:** {', '.join(map(str, plan.get('filters') or [])) or '—'}")
            cols[0].write(f"**Confidence:** {plan.get('confidence', 0.0):.2f}")

    rows: list[dict[str, Any]] = res.get("rows") or []
    charts: list[dict[str, Any]] = res.get("charts") or []
    chart_specs = [c for c in charts if c.get("vega_lite")]
    if chart_specs:
        for i in range(0, len(chart_specs), 2):
            pair = chart_specs[i : i + 2]
            columns = st.columns(len(pair))
            for col, chart in zip(columns, pair, strict=True):
                with col:
                    if chart.get("title"):
                        st.caption(chart["title"])
                    st.vega_lite_chart(rows, spec=chart["vega_lite"], use_container_width=True)
                    if chart.get("rationale"):
                        st.caption(chart["rationale"])

    if rows and res.get("columns"):
        st.dataframe(rows, use_container_width=True)

    stats = res.get("execution_stats") or {}
    ms = stats.get("execution_time_ms", 0.0)
    parts = [f"{len(rows)} rows", f"{ms:.1f} ms"]
    if res.get("retries"):
        parts.append(f"{res['retries']} retries")
    if res.get("cached"):
        parts.append("cached")
    st.caption(" · ".join(parts))
    if res.get("data_truncated"):
        st.warning("Results were truncated at the configured row limit.")


def render_exchange(question: str, result: dict[str, Any] | None, error: str | None = None) -> None:
    """Render one question/answer exchange in the chat history."""
    st.markdown(f"**You:** {question}")
    if error:
        st.error(error)
    elif result is not None:
        render_result(result)


def run_query(question: str, datasource_id: str) -> None:
    """Stream one query, append the exchange to history, and refresh."""
    thread_id = st.session_state["thread_id"]
    try:
        with st.status("Running agent...", expanded=False) as status:
            result = stream_query(question, datasource_id, thread_id, st.session_state["base_url"], status)
        st.session_state["history"].append({"question": question, "result": result, "error": None})
    except httpx.HTTPError as exc:
        st.session_state["history"].append(
            {"question": question, "result": None, "error": f"Backend unreachable: {exc}"}
        )
    except (RuntimeError, ValueError) as exc:
        st.session_state["history"].append({"question": question, "result": None, "error": str(exc)})
    st.rerun()


# -- sidebar ---------------------------------------------------------------

with st.sidebar:
    st.header("Settings")
    base_url = st.text_input("API base URL", value=API_BASE)
    api_key = st.text_input("API key (optional)", value=API_KEY, type="password")
    health = fetch_health(base_url)
    if health:
        st.success(f"Backend healthy · {health.get('service', 'unknown')}")
    else:
        st.error("Backend unreachable — start it with `uv run ai-sql-agent`.")

    st.divider()
    datasources = []
    try:
        datasources = fetch_datasources(base_url)
    except httpx.HTTPError:
        st.warning("Could not load datasources.")
    if datasources:
        datasource_map = {f"{d['display_name']} ({d['id']})": d["id"] for d in datasources}
        selected = st.selectbox(
            "Datasource",
            options=list(datasource_map.keys()),
            index=0,
        )
        datasource_id = datasource_map[selected]
    else:
        datasource_id = "default"

st.session_state.setdefault("base_url", base_url)
st.session_state.setdefault("api_key", api_key)
st.session_state.setdefault("thread_id", uuid.uuid4().hex)
st.session_state.setdefault("history", [])

# -- main ------------------------------------------------------------------

st.title("AI SQL Agent")
st.caption("Ask questions in natural language; get answers from your SQL database.")

if st.sidebar.button("New conversation"):
    st.session_state["thread_id"] = uuid.uuid4().hex
    st.session_state["history"] = []
    st.rerun()

for item in st.session_state["history"]:
    render_exchange(item["question"], item["result"], item.get("error"))

with st.form("ask", clear_on_submit=True):
    question = st.text_area(
        "Your question",
        placeholder='e.g. "What is the total revenue by category?"',
        max_chars=4000,
    )
    submitted = st.form_submit_button("Ask", type="primary")

if submitted and question.strip():
    run_query(question.strip(), datasource_id)
elif submitted:
    st.toast("Please enter a question.")
