"""调度中心业务兼容 facade（033）。

持久枚举与合法转移的单一事实来源是 ``src.data.scheduling_types``，使 data
Repository 能在最终 mutation 边界自行守住状态机而不反向依赖 business。本模块保留
业务侧稳定导入面，并提供 ``is_run_terminal`` 小工具。
"""

from __future__ import annotations

from typing import Container

from src.data.scheduling_types import (
    RUN_TERMINAL_STATUSES,
    TASK_ACTIVE_STATUSES,
    RunStatus,
    ScheduleKind,
    ScheduledTaskSourceType,
    ScheduledTaskStatus,
    SessionSource,
    run_status_sources_for,
    task_status_sources_for,
)

__all__ = [
    "RUN_TERMINAL_STATUSES",
    "TASK_ACTIVE_STATUSES",
    "RunStatus",
    "ScheduleKind",
    "ScheduledTaskSourceType",
    "ScheduledTaskStatus",
    "SessionSource",
    "is_run_terminal",
    "run_status_sources_for",
    "task_status_sources_for",
]


def is_run_terminal(status: str | RunStatus, terminal: Container[str] | None = None) -> bool:
    """判断 run 状态是否终态。"""
    return str(status) in (terminal if terminal is not None else RUN_TERMINAL_STATUSES)
