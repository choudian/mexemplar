"""Shared blinker event emitters for task collaboration.

收敛 task graph / task board 两类重复的 emit 样板。调用方只提供事务内已 flush/refresh
的 task 行，由 helper 按公开事件契约发 typed envelope；display_phase 与字段映射只在此处
维护一次。
"""

from __future__ import annotations

from src.business.task_collaboration.health import increment_task_collaboration_counter
from src.business.task_collaboration.models import derive_display_phase
from src.utils.events import emit


def emit_task_updated(sender, task) -> None:
    """单条任务状态变更 → assistant_task_graph_changed(change_type=task_updated)。

    task 是事务内已 flush/refresh 的 AssistantTask 行；事务结束后读取其属性即可——
    共享 session 在 service 关闭前一直有效（CAS 冲突时调用方不会走到这里）。
    """
    emit(
        "assistant_task_graph_changed",
        sender=sender,
        session_id=task.session_id,
        graph_id=task.graph_id,
        task_id=task.task_id,
        status=task.status,
        change_type="task_updated",
        display_phase=derive_display_phase(task.status),
        suspend_reason=task.suspend_reason,
    )


def emit_board_changed(sender, task, *, change_type: str, claim_status: str) -> None:
    """看板认领状态变更 → assistant_task_board_changed。"""
    emit(
        "assistant_task_board_changed",
        sender=sender,
        change_type=change_type,
        claim_status=claim_status,
        session_id=task.session_id,
        graph_id=task.graph_id,
        task_id=task.task_id,
        updated_at=task.updated_at.isoformat() if task.updated_at else None,
    )


def emit_meeting_changed(
    sender,
    task,
    channel,
    *,
    change_type: str,
    status: str,
    sequence: int | None = None,
) -> None:
    """会议通道变更 → assistant_meeting_changed。

    task 是通道所属父任务行（可能为 None，session_id 退化为空串）；channel 是事务内
    已 flush 的会议通道行。graph_id/task_id 取自 channel（创建时与父任务一致）。
    """
    emit(
        "assistant_meeting_changed",
        sender=sender,
        session_id=task.session_id if task is not None else "",
        graph_id=channel.graph_id,
        task_id=channel.parent_task_id,
        channel_id=channel.channel_id,
        change_type=change_type,
        status=status,
        sequence=sequence,
    )


def emit_graph_changed(
    sender,
    *,
    session_id: str,
    graph_id: str,
    change_type: str,
    task_id: str | None = None,
    status: str | None = None,
    display_phase: str | None = None,
    requires_review: bool | None = None,
    safe_explanation: str | None = None,
    suspend_reason: str | None = None,
) -> None:
    """图级生命周期变更 → assistant_task_graph_changed。

    覆盖 graph_created / task_created / adjudication_created / graph_stopped /
    graph_continued / graph_cancelled：调用方按场景传相关字段，未用的字段省略（projector
    与 Registry 均按 ``.get`` 兼容缺失字段）。``display_phase`` 由调用方派生后传入——图级
    事件的派生输入随场景不同（adjudication_created 需 ``has_pending_adjudication=True``），
    不在 helper 内统一计算。
    """
    emit(
        "assistant_task_graph_changed",
        sender=sender,
        session_id=session_id,
        graph_id=graph_id,
        task_id=task_id,
        change_type=change_type,
        status=status,
        display_phase=display_phase,
        requires_review=requires_review,
        safe_explanation=safe_explanation,
        suspend_reason=suspend_reason,
    )
    if change_type in {"task_created", "graph_stopped", "graph_cancelled"}:
        increment_task_collaboration_counter(change_type)


def emit_question_changed(
    sender,
    *,
    session_id: str,
    graph_id: str,
    task_id: str,
    question_id: str,
    kind: str,
    status: str,
    change_type: str,
) -> None:
    """问答/资源请求路由变更 → assistant_task_question_changed。"""
    emit(
        "assistant_task_question_changed",
        sender=sender,
        session_id=session_id,
        graph_id=graph_id,
        task_id=task_id,
        question_id=question_id,
        kind=kind,
        status=status,
        change_type=change_type,
    )


def emit_todo_changed(
    sender,
    *,
    session_id: str,
    task_id: str,
    todo_id: str,
    change_type: str,
    status: str,
    sort_order: int,
) -> None:
    """executor 私人 Todo 变更 → assistant_todo_changed。"""
    emit(
        "assistant_todo_changed",
        sender=sender,
        session_id=session_id,
        task_id=task_id,
        todo_id=todo_id,
        change_type=change_type,
        status=status,
        sort_order=sort_order,
    )


def emit_adjudication_decided(
    sender,
    *,
    session_id: str,
    graph_id: str,
    task_id: str,
    status: str,
) -> None:
    """父侧裁定决策落定 → assistant_task_adjudication_changed(adjudication_decided)。

    决策后 ``requires_review`` 固定翻 False、``safe_explanation`` 清空；``display_phase``
    由 ``status`` 派生。
    """
    emit(
        "assistant_task_adjudication_changed",
        sender=sender,
        session_id=session_id,
        graph_id=graph_id,
        task_id=task_id,
        change_type="adjudication_decided",
        status=status,
        display_phase=derive_display_phase(status),
        requires_review=False,
        safe_explanation="",
    )
    increment_task_collaboration_counter("adjudication_decided")


def emit_root_failed(
    sender,
    *,
    session_id: str,
    graph_id: str,
    task_id: str,
    status: str,
    safe_explanation: str,
) -> None:
    """根任务失败 → assistant_task_root_failed。``display_phase`` 由 ``status`` 派生。"""
    emit(
        "assistant_task_root_failed",
        sender=sender,
        session_id=session_id,
        graph_id=graph_id,
        task_id=task_id,
        change_type="root_failed",
        status=status,
        display_phase=derive_display_phase(status),
        safe_explanation=safe_explanation,
    )
    increment_task_collaboration_counter("root_graph_failed")
