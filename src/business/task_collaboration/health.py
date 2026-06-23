"""Lightweight runtime counters for Assistant task collaboration."""

from __future__ import annotations

from collections import Counter
from threading import Lock

_COUNTERS: Counter[str] = Counter()
_LOCK = Lock()

_KNOWN_COUNTERS = frozenset(
    {
        "task_created",
        "attempt_started",
        "attempt_fenced",
        "late_result_rejected",
        "claim_conflict",
        "adjudication_decided",
        "graph_stopped",
        "graph_cancelled",
        "root_graph_failed",
        "root_failure_bridge_failed",
        "fallback_executor_started",
    }
)


def increment_task_collaboration_counter(name: str, value: int = 1) -> None:
    """Increment a known collaboration counter.

    Counters are process-local telemetry for health endpoints/logging; durable
    state remains in the task graph tables.
    """
    if name not in _KNOWN_COUNTERS or value <= 0:
        return
    with _LOCK:
        _COUNTERS[name] += value


def get_task_collaboration_counters() -> dict[str, int]:
    with _LOCK:
        return {name: _COUNTERS.get(name, 0) for name in sorted(_KNOWN_COUNTERS)}


def reset_task_collaboration_counters() -> None:
    """Testing hook."""
    with _LOCK:
        _COUNTERS.clear()
