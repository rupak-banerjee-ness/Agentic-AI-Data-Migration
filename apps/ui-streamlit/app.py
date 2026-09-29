"""Streamlit UI: job creation, progress view, and Approve/Reject/Modify review screens.

Phase 1 scope: talks to the FastAPI gateway (apps/api-fastapi) over plain REST
polling (the gateway also exposes a WebSocket for other clients — Streamlit
doesn't have first-class websocket support, so REST polling is simpler here).
"""

from __future__ import annotations

import os
import time
from typing import Any, Optional

import requests
import streamlit as st

API_BASE_URL = os.getenv("MIGRATION_API_BASE_URL", "http://localhost:8000")
API_KEY = os.getenv("AUTH_API_KEY")
SUPPORTED_DIALECTS = ["oracle", "mysql", "postgresql"]

# Pre-fill connection forms with this repo's local docker-compose sample DBs
# (infra/docker/*-sample-init.sql) so the happy path needs zero typing.
_SAMPLE_DEFAULTS: dict[str, dict[str, Any]] = {
    "postgresql": {
        "host": "localhost",
        "port": 5433,
        "username": "postgres",
        "password": "postgres_dev_password",
        "database": "sample_source",
        "schema_name": "sample",
    },
    "mysql": {
        "host": "localhost",
        "port": 3306,
        "username": "appuser",
        "password": "mysql_dev_password",
        "database": "sample_source",
        "schema_name": "",
    },
    "oracle": {
        "host": "localhost",
        "port": 1521,
        "username": "sample_user",
        "password": "oracle_dev_password",
        "database": "XEPDB1",
        "schema_name": "",
    },
}

st.set_page_config(page_title="Agentic Migration Platform", layout="centered")


def _headers() -> dict[str, str]:
    return {"X-API-Key": API_KEY} if API_KEY else {}


def _get_job(job_id: str) -> Optional[dict[str, Any]]:
    resp = requests.get(f"{API_BASE_URL}/jobs/{job_id}", headers=_headers(), timeout=10)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


def _create_job(
    source_dialect: str,
    target_dialect: str,
    source_connection: dict[str, Any],
    target_connection: dict[str, Any],
) -> str:
    resp = requests.post(
        f"{API_BASE_URL}/jobs",
        json={
            "source_dialect": source_dialect,
            "target_dialect": target_dialect,
            "source_connection": source_connection,
            "target_connection": target_connection,
        },
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["job_id"]


def _submit_review(job_id: str, decision: str, reviewer: str, comment: str) -> None:
    resp = requests.post(
        f"{API_BASE_URL}/jobs/{job_id}/review",
        json={"decision": decision, "reviewer": reviewer, "comment": comment or None},
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()


def _connection_form(label: str, dialect: str, key_prefix: str) -> dict[str, Any]:
    defaults = _SAMPLE_DEFAULTS.get(dialect, {})
    st.markdown(f"**{label} connection** ({dialect})")
    c1, c2 = st.columns(2)
    host = c1.text_input("Host", value=defaults.get("host", "localhost"), key=f"{key_prefix}_host")
    port = c2.number_input(
        "Port", value=defaults.get("port", 5432), step=1, key=f"{key_prefix}_port"
    )
    username = c1.text_input("Username", value=defaults.get("username", ""), key=f"{key_prefix}_user")
    password = c2.text_input(
        "Password", value=defaults.get("password", ""), type="password", key=f"{key_prefix}_pw"
    )
    database = c1.text_input(
        "Database / service name", value=defaults.get("database", ""), key=f"{key_prefix}_db"
    )
    schema_name = c2.text_input(
        "Schema (Postgres only, optional)",
        value=defaults.get("schema_name", ""),
        key=f"{key_prefix}_schema",
    )
    return {
        "host": host,
        "port": int(port),
        "username": username,
        "password": password,
        "database": database,
        "schema_name": schema_name or None,
    }


st.title("Agentic AI-Powered Database Migration Platform")

with st.expander("Create a new migration job", expanded="job_id" not in st.session_state):
    col1, col2 = st.columns(2)
    source_dialect = col1.selectbox("Source dialect", SUPPORTED_DIALECTS, key="source_dialect")
    target_dialect = col2.selectbox(
        "Target dialect", SUPPORTED_DIALECTS, index=2, key="target_dialect"
    )

    st.divider()
    source_connection = _connection_form("Source", source_dialect, "src")
    st.divider()
    target_connection = _connection_form("Target", target_dialect, "tgt")

    if st.button("Create job", type="primary"):
        if source_dialect == target_dialect:
            st.warning("Source and target dialect are the same — proceeding anyway.")
        try:
            st.session_state["job_id"] = _create_job(
                source_dialect, target_dialect, source_connection, target_connection
            )
            st.rerun()
        except requests.RequestException as exc:
            st.error(f"Failed to create job: {exc}")

job_id = st.session_state.get("job_id")
if not job_id:
    st.info("Create a job above to see progress here.")
    st.stop()

st.subheader(f"Job `{job_id}`")

try:
    job = _get_job(job_id)
except requests.RequestException as exc:
    st.error(f"Failed to fetch job status: {exc}")
    st.stop()

if job is None:
    st.error("Job not found.")
    st.stop()

st.metric("Current phase", job["current_phase"])
st.metric("Status", job["status"])
st.progress(min(job["retry_count"] / max(job.get("retry_count", 0) or 1, 1), 1.0))

if job["approvals"]:
    st.write("**Approval history**")
    st.table(job["approvals"])

interrupt = job.get("interrupt")
if interrupt:
    st.divider()
    st.subheader(f"Review required: {interrupt.get('phase', interrupt.get('type', 'unknown'))}")
    st.write(interrupt.get("prompt", ""))
    with st.expander("Details", expanded=True):
        st.json({k: v for k, v in interrupt.items() if k not in {"prompt", "phase", "type"}})

    reviewer = st.text_input("Reviewer name")
    comment = st.text_area("Comment (optional)")
    decision_options = (
        ["retry", "abort"]
        if interrupt.get("type") == "HumanReviewFailure"
        else ["approve", "modify", "reject"]
    )
    cols = st.columns(len(decision_options))
    for col, decision in zip(cols, decision_options):
        if col.button(decision.capitalize(), disabled=not reviewer):
            try:
                _submit_review(job_id, decision, reviewer, comment)
                st.success(f"Submitted decision: {decision}")
                time.sleep(1)
                st.rerun()
            except requests.RequestException as exc:
                st.error(f"Failed to submit review: {exc}")
    if not reviewer:
        st.caption("Enter a reviewer name to enable the decision buttons.")
else:
    st.caption("No review currently pending for this job.")

if st.button("Refresh"):
    st.rerun()

auto_refresh = st.checkbox(
    "Auto-refresh every 2s", value=job["status"] not in {"DONE", "ABORTED", "ROLLED_BACK"}
)
if auto_refresh and job["status"] not in {"DONE", "ABORTED", "ROLLED_BACK"}:
    time.sleep(2)
    st.rerun()
