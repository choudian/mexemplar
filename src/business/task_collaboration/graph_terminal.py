"""任务协作图的公共终态判定。

该纯函数归属任务协作内核，由时间维度的 scheduling 模块单向复用。调用方注入状态常量，
避免模块级循环依赖。
"""

from __future__ import annotations

from typing import Container, Iterable


def compute_graph_terminal_state(
    tasks: Iterable,
    *,
    terminal_statuses: Container[str],
    completed_status: str,
) -> tuple[bool, bool]:
    """返回执行节点的 ``(all_terminal, all_completed)``，排除 root 容器节点。"""
    all_terminal = True
    all_completed = True
    for task in tasks:
        if getattr(task, "parent_task_id", None) is None:
            continue
        status = getattr(task, "status", None)
        if status not in terminal_statuses:
            all_terminal = False
        if status != completed_status:
            all_completed = False
    return all_terminal, all_completed
