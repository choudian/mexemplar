"""执行体归属判定：谁有资格代表一个任务说话。

``ask_parent`` / ``todo_update`` 都需要回答同一个问题——"你是不是此刻正在干这活的
执行体"。这个问题的权威答案在执行记录里：每个任务同时至多一条 active attempt
（partial unique index 焊死），它绑定的会话就是当前唯一的执行现场。

历史上两个守卫比对的是 ``assistant_tasks`` 的 ``assignee_type``/``assignee_id``。
那两列表达的是"预先点名指派"，而系统实际走认领制——``build_task_graph`` 建出的
节点两列恒为空，于是图节点上的执行体永远通不过校验，求助与列计划这两条路整体作废。
"""

from __future__ import annotations

from typing import Protocol


class _ActiveAttemptSessions(Protocol):
    def active_attempt_session(self, task_id: str) -> str | None: ...


def executor_session_owns_task(
    attempts: _ActiveAttemptSessions,
    task_id: str,
    executor_session_id: str | None,
) -> bool:
    """执行体会话是否等于该任务当前 active attempt 绑定的会话。

    未提供会话、任务没有 active attempt、或 attempt 尚未绑定会话时一律返回 False——
    调用方据此回落到显式指派判断，缺失的接线不会变成一道敞开的门。
    """
    if not executor_session_id:
        return False
    bound = attempts.active_attempt_session(task_id)
    return bound is not None and bound == executor_session_id
