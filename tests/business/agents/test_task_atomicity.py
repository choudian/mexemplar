"""跨 Repository 写入的原子性回归 + I4/I9/I10 修复的行为测试。

这些路径以前是"写 A 表 commit、再写 B 表 commit"，第二步失败会留下半完成状态。共享 session +
``_atomic`` 后，任一步失败必须整组回滚。下面用 monkeypatch 在第二步注入失败，断言第一步没有落库。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from src.business.agents.tools import assistant_tools
from src.business.task_collaboration.adjudication import TaskAdjudicationService
from src.business.task_collaboration.board import TaskBoardService
from src.business.task_collaboration.dispatcher import TaskDispatcher
from src.business.task_collaboration.meetings import TaskMeetingService
from src.business.task_collaboration.recovery import TaskRecoveryService
from src.business.task_collaboration.service import TaskCollaborationService
from src.business.task_collaboration.todos import TaskTodoService
from src.data.repos import (
    AssistantTaskAdjudicationRepository,
    AssistantTaskAttemptRepository,
    AssistantTaskClaimRepository,
    AssistantTaskRepository,
)


class _Guard:
    def assert_can_dispatch(self) -> None:
        return None


class _DispatchConfig:
    def get_assistant_tasks_dispatch_max_workers(self) -> int:
        return 2

    def get_assistant_tasks_attempt_lease_seconds(self) -> int:
        return 60


def _seed_task(task_id: str, *, session_id: str, status: str = "pending_dispatch"):
    return AssistantTaskRepository().create_task(
        graph_id=f"tg_{task_id}",
        session_id=session_id,
        task_id=task_id,
        title="t",
        description="t",
        owner_session_id=session_id,
        status=status,
    )


def _boom(*_args, **_kwargs):
    raise RuntimeError("second write failed")


# ============================ C1/C6 根任务自引用 ============================


def test_create_root_graph_sets_root_task_id_to_self_in_one_write() -> None:
    # 根任务的 root_task_id 在创建时一次写入指向自身，不再"先建后改"二次 commit。
    service = TaskCollaborationService()
    graph_id = service.create_root_graph(session_id="ast_root", title="r", description="r")
    root = AssistantTaskRepository().list_graph_tasks(graph_id)[0]
    assert root.parent_task_id is None
    assert root.root_task_id == root.task_id


# ============================ C2 看板认领原子 ============================


def test_claim_task_rolls_back_assign_when_claim_write_fails(monkeypatch) -> None:
    _seed_task("tsk_c2", session_id="ast_c2")
    service = TaskBoardService()
    monkeypatch.setattr(service._claims, "create_claim", _boom)

    with pytest.raises(RuntimeError):
        service.claim_task(
            task_id="tsk_c2",
            claimer_type="specialist",
            claimer_id="sp_a",
            lease_seconds=60,
        )

    refreshed = AssistantTaskRepository().get_task("tsk_c2")
    assert refreshed.assignee_type is None
    assert refreshed.assignee_id is None
    assert AssistantTaskClaimRepository().list_for_task("tsk_c2") == []


# ============================ C3 恢复 fence 原子 ============================


def test_recovery_rolls_back_fence_when_suspend_fails(monkeypatch) -> None:
    _seed_task("tsk_c3", session_id="ast_c3", status="running")
    attempt = AssistantTaskAttemptRepository().start_attempt(
        task_id="tsk_c3",
        executor_type="ephemeral_subagent",
        executor_id="sub",
        lease_owner="w",
        lease_expires_at=datetime.now() - timedelta(seconds=1),
    )
    service = TaskRecoveryService()
    monkeypatch.setattr(service._tasks, "update_status", _boom)

    # 单点失败用 try/except 隔离（#2），不再抛出中止整个恢复循环；但 fence 仍随
    # ``_atomic`` 回滚：attempt 仍 running，不会被标 fenced 后卡死。
    count = service.fence_expired_attempts(datetime.now())
    assert count == 0

    refreshed = AssistantTaskAttemptRepository().get_by_id(attempt.attempt_id)
    assert refreshed.status == "running"


# ============================ C4 派发 attempt 原子 ============================


def test_start_attempt_async_rolls_back_attempt_when_status_update_fails(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.business.task_collaboration.dispatcher.get_unified_config",
        lambda: _DispatchConfig(),
    )
    _seed_task("tsk_c4", session_id="ast_c4")
    monkeypatch.setattr(TaskCollaborationService, "update_task_status", _boom)

    dispatcher = TaskDispatcher(executor_callback=lambda _aid: "ok", cutover_guard=_Guard())
    try:
        with pytest.raises(RuntimeError):
            dispatcher.start_attempt_async(
                task_id="tsk_c4",
                executor_type="ephemeral_subagent",
                executor_id="sub",
                lease_owner="w",
            )
        # 任务置 running 失败时，attempt 创建必须回滚，不留下孤立的 running attempt。
        assert AssistantTaskAttemptRepository().list_for_task("tsk_c4") == []
    finally:
        dispatcher.shutdown()


# ============================ I1 裁定决策原子 ============================


def _make_pending_adjudication(session_id: str = "ast_i1"):
    service = TaskCollaborationService()
    graph_id = service.create_root_graph(session_id=session_id, title="r", description="r")
    root = AssistantTaskRepository().list_graph_tasks(graph_id)[0]
    task_id = service.create_child_task(
        graph_id=graph_id,
        session_id=session_id,
        parent_task_id=root.task_id,
        title="c",
        description="c",
    )
    service.update_task_status(task_id=task_id, status="running")
    adjudication = service.create_parent_adjudication(
        task_id=task_id, delivered_status="done", safe_summary="done"
    )
    return task_id, adjudication.adjudication_id


def test_adjudication_decide_rolls_back_when_status_update_fails(monkeypatch) -> None:
    _task_id, adjudication_id = _make_pending_adjudication()
    service = TaskAdjudicationService()
    monkeypatch.setattr(service._graph_service, "update_task_status", _boom)

    with pytest.raises(RuntimeError):
        service.decide(
            adjudication_id=adjudication_id,
            decision="accepted",
            session_id="ast_i1",
        )

    # 决策落库必须随状态翻转失败回滚：裁定仍 pending，可重试。
    assert AssistantTaskAdjudicationRepository().get_by_id(adjudication_id).status == "pending"


# ============================ I3 整图停止原子 ============================


def test_stop_graph_rolls_back_all_when_one_task_update_fails(monkeypatch) -> None:
    service = TaskCollaborationService()
    graph_id = service.create_root_graph(session_id="ast_i3", title="r", description="r")
    root = AssistantTaskRepository().list_graph_tasks(graph_id)[0]
    child_id = service.create_child_task(
        graph_id=graph_id,
        session_id="ast_i3",
        parent_task_id=root.task_id,
        title="c",
        description="c",
    )
    service.update_task_status(task_id=child_id, status="running")

    real_update = service._tasks.update_status
    calls = {"n": 0}

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] >= 2:
            raise RuntimeError("second task update failed")
        return real_update(*args, **kwargs)

    monkeypatch.setattr(service._tasks, "update_status", flaky)

    with pytest.raises(RuntimeError):
        service.stop_graph(session_id="ast_i3", graph_id=graph_id)

    tasks = {t.task_id: t for t in AssistantTaskRepository().list_graph_tasks(graph_id)}
    # 第一个任务的挂起必须随第二个任务失败一起回滚——整图停止要么全停要么不动。
    assert tasks[root.task_id].status == "pending_dispatch"
    assert tasks[child_id].status == "running"


# ============================ I4 工具错误不泄漏内部细节 ============================


def test_ask_parent_handler_surfaces_business_error_but_hides_internals(monkeypatch) -> None:
    handler = assistant_tools.create_ask_parent_handler("specialist", "sp_1")

    # 业务校验异常的文案是我们自己的安全字面量，可回给 LLM。
    business = json.loads(handler(taskId="missing", question="q", kind="clarification"))
    assert business["success"] is False
    assert "not found" in business["message"]

    # 内部异常（可能含 DB 错误/路径）只入日志，对 LLM 给通用文案。
    def leak(*_a, **_k):
        raise RuntimeError(r"connection failed at C:\\secret\\mexemplar.db")

    monkeypatch.setattr(
        "src.business.task_collaboration.questions.TaskQuestionService.ask_parent",
        leak,
    )
    internal = json.loads(handler(taskId="t", question="q", kind="clarification"))
    assert internal["success"] is False
    assert "secret" not in internal["message"]
    assert "内部错误" in internal["message"]


# ============================ I9 Todo 跨会话归属校验 ============================


def test_todo_service_rejects_cross_session_access() -> None:
    _seed_task("tsk_i9", session_id="ast_owner")
    service = TaskTodoService()

    # 同会话可读
    assert service.list_todos("tsk_i9", session_id="ast_owner") == []
    # 跨会话读被拒
    with pytest.raises(LookupError):
        service.list_todos("tsk_i9", session_id="ast_intruder")
    # 跨会话写被拒（在 executor 校验之前就挡住）
    with pytest.raises(LookupError):
        service.update_todos(
            task_id="tsk_i9",
            executor_type="specialist",
            executor_id="sp_x",
            items=[],
            session_id="ast_intruder",
        )


# ============================ I10 会议分页游标 ============================


class _StubChannel:
    channel_id = "ch_1"
    status = "open"
    participant_a_type = "specialist"
    participant_a_id = "sp_a"
    participant_b_type = "ephemeral_subagent"
    participant_b_id = "sub_b"
    turns_used = 0
    turn_budget = 10
    conclusion = None


class _StubMsg:
    def __init__(self, sequence: int) -> None:
        self.sequence = sequence
        self.sender_id = "sp_a"
        self.content = "hi"
        self.created_at = None


class _StubMeetings:
    def __init__(self, count: int) -> None:
        self._count = count

    def get_channel(self, _channel_id: str):
        return _StubChannel()

    def list_messages(self, _channel_id: str, *, after_sequence=None, limit=None):
        # 返回 min(count, limit) 条，模拟"满页/不满页"。
        n = min(self._count, limit)
        return [_StubMsg(i) for i in range(1, n + 1)]


class _StubLimitConfig:
    def get_assistant_tasks_api_default_limit(self) -> int:
        return 3


def _meeting_service_with(count: int) -> TaskMeetingService:
    service = TaskMeetingService(meeting_repo=_StubMeetings(count))
    service._config = _StubLimitConfig()
    return service


def test_transcript_marks_next_cursor_with_default_limit() -> None:
    # limit=None 时按默认 limit(3) 取数；满页必须给出 nextAfterSequence（修复前恒为 None）。
    full = _meeting_service_with(count=5).get_transcript("ch_1", limit=None)
    assert full["nextAfterSequence"] == 3

    # 不满页时游标为 None。
    partial = _meeting_service_with(count=2).get_transcript("ch_1", limit=None)
    assert partial["nextAfterSequence"] is None


# ============================ I11 _init_repos session 一致性守卫 ============================


def test_init_repos_rejects_partial_injection_that_would_split_sessions() -> None:
    """部分注入（一个注入、一个留 None）会让 None 的 repo 走 ``repo_cls()`` 自建独立
    session，而 ``_atomic`` 只 commit ``self._session`` 指向的第一个 repo 的 session，
    造成分裂写未受管理。``_init_repos`` 必须显式拒绝而非静默分裂。"""
    injected = AssistantTaskRepository()  # 持有自己的 session
    # adjudication_repo 留 None → 触发部分注入
    with pytest.raises(RuntimeError):
        TaskCollaborationService(task_repo=injected)
