"""In-process registry for DB connection credentials, kept deliberately OUT of
the LangGraph checkpointed state (architecture.md §14: secrets are never
stored in state or logs). The Discover node reads a job's connection configs
exactly once, right after the job is created -- if the process restarts
before Discover runs, the job must be recreated (acceptable: Discover is the
very first phase, before any human-review pause).
"""

from __future__ import annotations

import threading
from typing import Any, Optional

_lock = threading.Lock()
_connections: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}


def register(
    job_id: str, source_connection: dict[str, Any], target_connection: dict[str, Any]
) -> None:
    with _lock:
        _connections[job_id] = (source_connection, target_connection)


def get(job_id: str) -> Optional[tuple[dict[str, Any], dict[str, Any]]]:
    with _lock:
        return _connections.get(job_id)


def discard(job_id: str) -> None:
    with _lock:
        _connections.pop(job_id, None)
