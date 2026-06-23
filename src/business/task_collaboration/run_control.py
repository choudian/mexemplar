"""Process-local run-control keys for unified task execution."""

from __future__ import annotations


def graph_cancel_key(graph_id: str) -> str:
    return f"assistant_task_graph:{graph_id}"


def task_cancel_key(task_id: str) -> str:
    return f"assistant_task:{task_id}"


def attempt_cancel_key(attempt_id: str) -> str:
    return f"assistant_task_attempt:{attempt_id}"
