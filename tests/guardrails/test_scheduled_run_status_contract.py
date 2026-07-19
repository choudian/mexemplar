"""调度 run 状态集合的单一事实来源门卫（033 review remediation）。"""

from __future__ import annotations

import ast
from pathlib import Path

from src.data.scheduling_types import (
    RUN_ACTIVE_STATUSES,
    RUN_EVENT_DELIVERABLE_STATUSES,
    RUN_TAKEOVER_STATUSES,
    RUN_TERMINAL_STATUSES,
    RunStatus,
)

_ROOT = Path(__file__).resolve().parents[2]
_CONSUMERS = (
    "src/data/repos/scheduled_task_run_repository.py",
    "src/business/scheduling/terminal_event_delivery.py",
    "src/business/scheduling/run_completion_monitor.py",
    "src/business/scheduling/scheduler_service.py",
)
_RUN_STATUS_VALUES = {status.value for status in RunStatus}


def test_run_status_contract_partitions_lifecycle_and_delivery_states():
    assert RUN_ACTIVE_STATUSES.isdisjoint(RUN_TERMINAL_STATUSES)
    assert RUN_ACTIVE_STATUSES | RUN_TERMINAL_STATUSES == frozenset(RunStatus)
    assert RUN_EVENT_DELIVERABLE_STATUSES == frozenset(
        {
            RunStatus.SUCCEEDED,
            RunStatus.FAILED,
            RunStatus.WAITING_USER,
        }
    )
    assert RUN_TAKEOVER_STATUSES == frozenset(
        {
            RunStatus.WAITING_USER,
            RunStatus.FAILED,
        }
    )


def test_run_status_consumers_do_not_redeclare_status_bundles():
    """消费者不得用字符串集合复制 data-boundary 生命周期契约。"""
    offenders: list[str] = []
    for relative_path in _CONSUMERS:
        path = _ROOT / relative_path
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.List, ast.Set, ast.Tuple)):
                continue
            values = [
                item.value
                for item in node.elts
                if isinstance(item, ast.Constant) and isinstance(item.value, str)
            ]
            if (
                len(values) == len(node.elts)
                and len(values) >= 2
                and set(values).issubset(_RUN_STATUS_VALUES)
            ):
                offenders.append(f"{relative_path}:{node.lineno} -> {sorted(values)!r}")

    assert offenders == [], "run status bundles must come from scheduling_types:\n" + "\n".join(
        offenders
    )
