"""执行节点变化 → 用户任务 progress_changed 事件（卡片实时刷新的后端一半）。

背景：用户任务卡片展示的是"底下卡在谁手上"，随执行节点变化；而
``user_task_changed`` 原本只在用户任务自身状态（几天一次）变化时才发，
卡片因此永远停在挂载那一刻的快照上。
"""

from __future__ import annotations

import pytest

from src.business.agents.config import AgentType
from src.business.task_collaboration.models import TaskStatus
from src.business.task_collaboration.service import TaskCollaborationService
from src.data.models_sqlite import Session as SessionModel
from src.data.repos import AssistantTaskRepository, SessionRepository, UserTaskRepository
from src.utils.events import connect, disconnect


@pytest.fixture
def captured_events():
    """订阅 user_task_changed，收集本次测试期间发出的事件。"""
    received: list[dict] = []

    def _handler(sender, **payload):
        received.append(payload)

    # weak=False：本地函数在 blinker 弱引用下会被立即回收，收不到事件
    connect("user_task_changed", _handler, weak=False)
    try:
        yield received
    finally:
        disconnect("user_task_changed", _handler)


def _seed(session_id: str, graph_id: str, task_id: str, *, with_user_task: bool = True) -> str | None:
    SessionRepository().create(
        SessionModel(
            session_id=session_id, workflow_id=None,
            agent_type=AgentType.ASSISTANT, status="active",
        )
    )
    user_task_id = None
    if with_user_task:
        with UserTaskRepository() as repo:
            user_task_id = repo.create(session_id=session_id, title="季度报告", description="d").task_id
    with AssistantTaskRepository() as tasks:
        tasks.create_task(
            graph_id=graph_id, session_id=session_id, task_id=task_id,
            title="整理明细", description="d",
            assignee_type="ephemeral_subagent", assignee_id="exec_1",
            status="running", user_task_id=user_task_id,
        )
    return user_task_id


def test_node_status_change_emits_progress_changed(captured_events):
    """执行节点跑完 → 发 progress_changed，卡片才能知道进度变了。"""
    user_task_id = _seed("s_p1", "g_p1", "t_p1")
    with TaskCollaborationService() as svc:
        svc.update_task_status(task_id="t_p1", status=TaskStatus.COMPLETED)

    progress = [e for e in captured_events if e.get("change_type") == "progress_changed"]
    assert len(progress) == 1, f"应发一条 progress_changed，实际 {captured_events}"
    assert progress[0]["user_task_id"] == user_task_id
    assert progress[0]["session_id"] == "s_p1"


def test_suspend_also_emits_progress_changed(captured_events):
    """节点暂停（等用户/撞缺陷）同样要通知——继续按钮的显示依赖它。"""
    _seed("s_p2", "g_p2", "t_p2")
    with TaskCollaborationService() as svc:
        svc.update_task_status(
            task_id="t_p2", status=TaskStatus.SUSPENDED, suspend_reason="user_stop",
        )
    assert [e["change_type"] for e in captured_events] == ["progress_changed"]


def test_stop_graph_emits_progress_for_each_node(captured_events):
    """批量转换（停止整张图）逐节点通知，不能只发图级事件。"""
    _seed("s_p3", "g_p3", "t_p3")
    with TaskCollaborationService() as svc:
        svc.stop_graph(session_id="s_p3", graph_id="g_p3")
    progress = [e for e in captured_events if e.get("change_type") == "progress_changed"]
    assert len(progress) == 1


def test_node_without_user_task_emits_nothing(captured_events):
    """没挂用户任务的节点（系统内部任务）不发事件，也不报错。"""
    _seed("s_p4", "g_p4", "t_p4", with_user_task=False)
    with TaskCollaborationService() as svc:
        svc.update_task_status(task_id="t_p4", status=TaskStatus.COMPLETED)
    assert captured_events == []


def test_progress_notify_failure_does_not_break_status_write(captured_events, monkeypatch):
    """通知失败不能连累状态落库——业务事实已提交，通知只是尽力而为。"""
    _seed("s_p5", "g_p5", "t_p5")

    def _boom(*args, **kwargs):
        raise RuntimeError("event bus down")

    monkeypatch.setattr(
        "src.business.user_tasks.service.emit_user_task_changed", _boom
    )
    with TaskCollaborationService() as svc:
        updated = svc.update_task_status(task_id="t_p5", status=TaskStatus.COMPLETED)
    assert updated is not None
    with AssistantTaskRepository() as tasks:
        assert tasks.get_task("t_p5").status == "done"
