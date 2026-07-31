"""端到端：统一任务派发执行链路接通 + 父侧回流（V-01）。

验证 ``TaskDispatcher.start_attempt_async`` 经 ``TaskExecutorAdapter`` 真正执行任务
（复用 Orchestrator 委派执行内核）、结果回流建父侧裁定、``ParentReentrySink`` 收到
payload 并触发续跑唤醒——即 V-01「执行链路接通」的核心闭环。

不依赖注入式 mock executor_callback：``TaskExecutorAdapter`` 是真实适配器，只把底层
Orchestrator 执行内核替换为一个返回预设结果的替身（避免真实 LLM/AgentLoop）。
"""

from __future__ import annotations

from datetime import timedelta
from threading import Barrier, BrokenBarrierError, Lock
from time import sleep

from src.business.orchestration.agent.task_executor_adapter import TaskExecutorAdapter
from src.business.task_collaboration.dispatcher import TaskDispatcher
from src.business.task_collaboration.parent_reentry_sink import ParentReentrySink
from src.business.task_collaboration.service import TaskCollaborationService
from src.data.repos import (
    AssistantTaskAdjudicationRepository,
    AssistantTaskAttemptRepository,
    AssistantTaskRepository,
)
from src.utils.timezone import utc_now_naive


class _Config:
    """最小 config stub：只满足 dispatcher 构造所需的两个 getter。"""

    def get_assistant_tasks_dispatch_max_workers(self) -> int:
        return 4

    def get_assistant_tasks_attempt_lease_seconds(self) -> int:
        return 60


class _AllowGuard:
    """cutover stub：测试直接构造 dispatcher，跳过 flag/legacy 判定。"""

    def assert_can_dispatch(self) -> None:
        return None


class _FakeOrchestrator:
    """替身 Orchestrator：记录调用并返回预设委派结果，避免真实 LLM/AgentLoop。

    adapter 经 ``orchestrator.delegation_orchestrator.run_*_via_delegated_executor`` 调委派
    执行内核，故 fake 暴露同名无下划线方法并把 ``delegation_orchestrator`` 指向自己。
    """

    def __init__(self, result: dict) -> None:
        self._result = result
        self.calls: list[dict] = []

    @property
    def delegation_orchestrator(self) -> "_FakeOrchestrator":
        return self

    def run_ephemeral_via_delegated_executor(
        self,
        *,
        parent_session_id,
        task,
        execution_context="",
        tool_whitelist=None,
        current_task_id=None,
        workspace_root=None,
    ) -> dict:
        self.calls.append(
            {
                "parent_session_id": parent_session_id,
                "task": task,
                "current_task_id": current_task_id,
                "workspace_root": workspace_root,
            }
        )
        return self._result

    def run_specialist_via_delegated_executor(self, **kwargs) -> dict:
        return self._result


def _patch_dispatch_config(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.business.task_collaboration.dispatcher.get_unified_config",
        lambda: _Config(),
    )


def _create_child_task(
    service: TaskCollaborationService, *, session_id: str, title: str
) -> tuple[str, str]:
    graph_id, root_id = service.get_or_create_request_graph_root(
        session_id=session_id,
        user_message_sequence=None,
        title="root",
        description="root",
    )
    task_id = service.create_child_task(
        graph_id=graph_id,
        session_id=session_id,
        parent_task_id=root_id,
        title=title,
        description=title,
        assignee_type="ephemeral_subagent",
        assignee_id="ephemeral_subagent",
        capability_scope="[]",
    )
    return graph_id, task_id


def test_adapter_executes_and_reentry_reaches_sink(monkeypatch):
    """delegate→start_attempt→adapter 执行→attempt done→adjudication→sink 收到 payload+kick。"""
    _patch_dispatch_config(monkeypatch)

    service = TaskCollaborationService()
    graph_id, task_id = _create_child_task(service, session_id="ast_reentry_a", title="整理报销")
    service.close()

    fake_orch = _FakeOrchestrator({"success": True, "result_text": "报销已整理完毕"})
    adapter = TaskExecutorAdapter(fake_orch)

    kicks: list[tuple[str, str]] = []
    sink = ParentReentrySink(
        has_active_worker=lambda session_id: False,
        kick_reentry_run=lambda session_id, graph_id: kicks.append((session_id, graph_id)) or True,
    )
    dispatcher = TaskDispatcher(
        cutover_guard=_AllowGuard(),
        executor_callback=adapter,
        parent_reentry_callback=sink.dispatch,
    )

    future = dispatcher.start_attempt_async(
        task_id=task_id,
        executor_type="ephemeral_subagent",
        executor_id=task_id,
        lease_owner="test",
    )
    assert future is not None
    payload = future.result(timeout=5)

    # 1. adapter 真的被 dispatcher 调用（执行链路接通，而非注入式 mock callback）
    assert len(fake_orch.calls) == 1
    assert fake_orch.calls[0]["task"] == "整理报销"
    assert fake_orch.calls[0]["current_task_id"] == task_id

    # 2. attempt 完成 + 父侧裁定 pending（done）
    with AssistantTaskAdjudicationRepository() as adjs:
        adj = adjs.get_pending_for_task(task_id)
    assert adj is not None
    assert adj.delivered_status == "done"

    # 3. 回流 payload 带足续跑所需信息（session/graph/结果）
    assert payload["accepted"] is True
    assert payload["deliveredStatus"] == "done"
    assert payload["sessionId"] == "ast_reentry_a"
    assert payload["graphId"] == graph_id

    # 4. sink 收到 payload 并 kick 了续跑 worker
    entries = sink.drain("ast_reentry_a")
    assert len(entries) == 1
    assert entries[0]["taskId"] == task_id
    assert kicks == [("ast_reentry_a", graph_id)]


def _paused_dispatcher(monkeypatch, *, session_id: str, title: str, result: dict):
    """搭一条真实的派发链，让执行体返回一个暂停结果。"""
    _patch_dispatch_config(monkeypatch)

    service = TaskCollaborationService()
    graph_id, task_id = _create_child_task(service, session_id=session_id, title=title)
    service.close()

    kicks: list[tuple[str, str]] = []
    sink = ParentReentrySink(
        has_active_worker=lambda sid: False,
        kick_reentry_run=lambda sid, gid: kicks.append((sid, gid)) or True,
    )
    dispatcher = TaskDispatcher(
        cutover_guard=_AllowGuard(),
        executor_callback=TaskExecutorAdapter(_FakeOrchestrator(result)),
        parent_reentry_callback=sink.dispatch,
    )
    future = dispatcher.start_attempt_async(
        task_id=task_id,
        executor_type="ephemeral_subagent",
        executor_id=task_id,
        lease_owner="test",
    )
    assert future is not None
    return graph_id, task_id, sink, kicks, future.result(timeout=5)


def test_budget_pause_wakes_the_parent(monkeypatch):
    """撞轮次预算暂停必须叫醒主助理——这条链此前是断的。

    7/29 实跑：执行体跑满 30 轮正常暂停、工作完整保留，task 与 attempt 状态**全部
    正确落库**，然后没有任何人被告知。主助理以为活还在跑，用户在等主助理"第一时间
    告知"，两边互等到用户自己发现不对。

    断点在于落库写的是 suspend_reason，而决定"要不要通知父侧"的代码查的是另一套
    reentry_type 白名单——两套独立判断对不上。现在通知只读刚写进库的 waiting_on。
    """
    graph_id, task_id, sink, kicks, payload = _paused_dispatcher(
        monkeypatch,
        session_id="ast_budget",
        title="实现 DAG viewer",
        result={
            "success": False,
            "paused": True,
            "pause_reason": "budget_exhausted",
            "iterations_used": 30,
            "max_iterations": 30,
            "message": "已达迭代上限（30 轮）",
            "subagent_id": "ast_child",
        },
    )

    # 1. 落库：停住了，而且记下了球在主助理手上
    with AssistantTaskRepository() as tasks:
        row = tasks.get_task(task_id)
    assert row.status == "suspended"
    assert row.suspend_reason == "budget_exhausted"
    assert row.waiting_on == "assistant"

    # 2. attempt 让出执行者槽
    with AssistantTaskAttemptRepository() as attempts:
        assert attempts.get_by_id(payload["attemptId"]).status == "paused"

    # 3. 主助理真的被叫醒了 —— 这一条是这一步存在的全部理由
    entries = sink.drain("ast_budget")
    assert len(entries) == 1
    assert entries[0]["eventType"] == "budget_exhausted"
    assert entries[0]["taskId"] == task_id
    assert entries[0]["iterationsUsed"] == 30
    assert entries[0]["maxIterations"] == 30
    assert entries[0]["safeSummary"]
    assert kicks == [("ast_budget", graph_id)]


def test_user_stop_does_not_wake_the_parent(monkeypatch):
    """对照：用户自己按停的活球在用户手上，不该去打扰主助理。"""
    _, task_id, sink, kicks, _ = _paused_dispatcher(
        monkeypatch,
        session_id="ast_user_stop",
        title="随便什么活",
        result={
            "success": False,
            "paused": True,
            "cancelled": True,
            "pause_reason": "budget_exhausted",
            "message": "用户已停止",
            "subagent_id": "ast_child",
        },
    )

    with AssistantTaskRepository() as tasks:
        row = tasks.get_task(task_id)
    assert row.suspend_reason == "user_stop"
    assert row.waiting_on == "user"

    assert sink.drain("ast_user_stop") == []
    assert kicks == []


def test_a_pause_whose_task_row_is_gone_notifies_nobody(monkeypatch):
    """attempt 指向的 task 不存在时：中止收尾、不动 attempt、不发通知。

    通知的前提是**状态已经落库**。若放行，主助理会被叫醒去查一个账上没有的活，
    而且 payload 里的 sessionId / graphId 全是空的——回流恰恰是按 sessionId 分队列
    投递的。所以必须在把 attempt 翻 paused 之前就中止，不留"attempt 已让出槽位、
    task 却没动"的半截状态。
    """
    _patch_dispatch_config(monkeypatch)

    service = TaskCollaborationService()
    _, task_id = _create_child_task(service, session_id="ast_gone", title="活")
    service.close()

    with AssistantTaskAttemptRepository() as attempts:
        attempt = attempts.start_attempt(
            task_id=task_id,
            executor_type="ephemeral_subagent",
            executor_id=task_id,
            lease_owner="test",
            lease_expires_at=utc_now_naive() + timedelta(seconds=60),
        )
        attempt_id = attempt.attempt_id
        fence_token = attempt.fence_token

    sink = ParentReentrySink(
        has_active_worker=lambda sid: False,
        kick_reentry_run=lambda sid, gid: True,
    )
    dispatcher = TaskDispatcher(
        cutover_guard=_AllowGuard(),
        parent_reentry_callback=sink.dispatch,
    )

    # 让这一次收尾看到「task 不存在」
    monkeypatch.setattr(TaskCollaborationService, "get_task", lambda self, _task_id: None)

    result = dispatcher._record_attempt_paused(
        attempt_id=attempt_id,
        fence_token=fence_token,
        suspend_reason="budget_exhausted",
        safe_summary="已达迭代上限",
        pause_result={
            "suspend_reason": "budget_exhausted",
            "reentry_type": "budget_exhausted",
        },
    )

    assert result["accepted"] is False
    assert result["taskMissing"] is True
    # 没有任何人被叫醒
    assert sink.drain("ast_gone") == []
    # attempt 仍占着执行者槽——没被翻成 paused
    with AssistantTaskAttemptRepository() as attempts:
        assert (
            attempts.get_by_id(attempt_id).status
            in AssistantTaskAttemptRepository.ACTIVE_STATUSES
        )


def test_adapter_maps_non_paused_failure_to_stuck(monkeypatch):
    """子代理 success=False 且非暂停 → adapter 抛异常 → dispatcher 记 stuck 交裁定。"""
    _patch_dispatch_config(monkeypatch)

    service = TaskCollaborationService()
    _, task_id = _create_child_task(service, session_id="ast_reentry_b", title="发邮件")
    service.close()

    fake_orch = _FakeOrchestrator({"success": False, "message": "邮件服务不可用"})
    adapter = TaskExecutorAdapter(fake_orch)
    sink = ParentReentrySink(
        has_active_worker=lambda session_id: False,
        kick_reentry_run=lambda session_id, graph_id: True,
    )
    dispatcher = TaskDispatcher(
        cutover_guard=_AllowGuard(),
        executor_callback=adapter,
        parent_reentry_callback=sink.dispatch,
    )

    future = dispatcher.start_attempt_async(
        task_id=task_id,
        executor_type="ephemeral_subagent",
        executor_id=task_id,
        lease_owner="test",
    )
    payload = future.result(timeout=5)

    assert payload["accepted"] is True
    assert payload["deliveredStatus"] == "stuck"
    with AssistantTaskAdjudicationRepository() as adjs:
        adj = adjs.get_pending_for_task(task_id)
    assert adj is not None
    assert adj.delivered_status == "stuck"


def test_adapter_maps_paused_result_to_suspended_task_without_adjudication(monkeypatch):
    """子代理 paused/cancelled 是可续挂起，不是 done，也不应生成父侧裁定。"""
    _patch_dispatch_config(monkeypatch)

    service = TaskCollaborationService()
    _, task_id = _create_child_task(service, session_id="ast_reentry_pause", title="等系统恢复")
    service.close()

    fake_orch = _FakeOrchestrator(
        {
            "success": False,
            "paused": True,
            "cancelled": False,
            "message": "模型限流，稍后可继续",
            "result_type": "paused",
        }
    )
    adapter = TaskExecutorAdapter(fake_orch)
    dispatcher = TaskDispatcher(
        cutover_guard=_AllowGuard(),
        executor_callback=adapter,
    )

    future = dispatcher.start_attempt_async(
        task_id=task_id,
        executor_type="ephemeral_subagent",
        executor_id=task_id,
        lease_owner="test",
    )
    assert future is not None
    payload = future.result(timeout=5)

    assert payload["accepted"] is True
    assert payload["taskStatus"] == "suspended"
    assert payload["suspendReason"] == "waiting_system"
    with AssistantTaskRepository() as tasks:
        task = tasks.get_task(task_id)
        assert task.status == "suspended"
        assert task.suspend_reason == "waiting_system"
    with AssistantTaskAttemptRepository() as attempts:
        attempt = attempts.list_for_task(task_id)[0]
        assert attempt.status == "paused"
    with AssistantTaskAdjudicationRepository() as adjs:
        assert adjs.get_pending_for_task(task_id) is None


def test_question_pause_reentry_reaches_parent_sink(monkeypatch):
    _patch_dispatch_config(monkeypatch)

    service = TaskCollaborationService()
    graph_id, task_id = _create_child_task(
        service,
        session_id="ast_reentry_question",
        title="需要上级答复",
    )
    service.close()

    fake_orch = _FakeOrchestrator(
        {
            "success": False,
            "paused": True,
            "cancelled": False,
            "message": "子代理已暂停，等待派活方答复。",
            "result_type": "needs_user_input",
            "suspend_reason": "waiting_system",
            "reentry_type": "task_question",
            "question_id": "qst_1",
            "question_kind": "clarification",
            "safe_summary": "Need parent input.",
        }
    )
    adapter = TaskExecutorAdapter(fake_orch)
    kicks: list[tuple[str, str]] = []
    sink = ParentReentrySink(
        has_active_worker=lambda session_id: False,
        kick_reentry_run=lambda session_id, graph_id: kicks.append((session_id, graph_id)) or True,
    )
    dispatcher = TaskDispatcher(
        cutover_guard=_AllowGuard(),
        executor_callback=adapter,
        parent_reentry_callback=sink.dispatch,
    )

    future = dispatcher.start_attempt_async(
        task_id=task_id,
        executor_type="ephemeral_subagent",
        executor_id=task_id,
        lease_owner="test",
    )
    assert future is not None
    payload = future.result(timeout=5)

    assert payload["accepted"] is True
    assert payload["eventType"] == "task_question"
    assert payload["questionId"] == "qst_1"
    entries = sink.drain("ast_reentry_question")
    assert entries == [payload]
    assert kicks == [("ast_reentry_question", graph_id)]


def test_adapter_uses_isolated_orchestrators_for_parallel_attempts(
    monkeypatch, tmp_path, in_memory_db
):
    """真实 adapter callback 支持跨 attempt 并行，不复用同一个 orchestrator repository session。"""
    _patch_dispatch_config(monkeypatch)

    # 该用例刻意跑真实 worker 线程；生产 SQLite 是文件库，每个 session 独立连接。
    # autouse 的 :memory: StaticPool 会让线程共享同一连接，容易测到 SQLite 测试替身竞态。
    import src.data.sqlalchemy_manager as sm_module
    from src.data.sqlalchemy_manager import SQLAlchemyManager

    previous_manager = sm_module._sqlalchemy_instance
    file_manager = SQLAlchemyManager(str(tmp_path / "parallel-attempts.db"))
    file_manager.initialize()
    sm_module._sqlalchemy_instance = file_manager

    try:
        service = TaskCollaborationService()
        _, task_a = _create_child_task(service, session_id="ast_parallel", title="任务 A")
        _, task_b = _create_child_task(service, session_id="ast_parallel", title="任务 B")
        service.close()

        calls: list[str] = []
        barrier_passed: list[str] = []
        calls_lock = Lock()
        executor_barrier = Barrier(2)

        class _SlowFakeOrchestrator(_FakeOrchestrator):
            def __init__(self) -> None:
                super().__init__({"success": True, "result_text": "done"})

            def run_ephemeral_via_delegated_executor(
                self,
                *,
                parent_session_id,
                task,
                execution_context="",
                tool_whitelist=None,
                current_task_id=None,
                workspace_root=None,
            ) -> dict:
                with calls_lock:
                    calls.append(task)
                try:
                    executor_barrier.wait(timeout=2)
                except BrokenBarrierError as exc:
                    raise AssertionError("attempt executors did not overlap") from exc
                with calls_lock:
                    barrier_passed.append(task)
                sleep(0.05)
                return {"success": True, "result_text": task}

        base = _SlowFakeOrchestrator()
        adapter = TaskExecutorAdapter(base, orchestrator_factory=_SlowFakeOrchestrator)
        dispatcher = TaskDispatcher(
            cutover_guard=_AllowGuard(),
            executor_callback=adapter,
        )

        future_a = dispatcher.start_attempt_async(
            task_id=task_a,
            executor_type="ephemeral_subagent",
            executor_id=task_a,
            lease_owner="test",
        )
        future_b = dispatcher.start_attempt_async(
            task_id=task_b,
            executor_type="ephemeral_subagent",
            executor_id=task_b,
            lease_owner="test",
        )
        assert future_a is not None
        assert future_b is not None
        future_a.result(timeout=5)
        future_b.result(timeout=5)

        assert sorted(calls) == ["任务 A", "任务 B"]
        assert sorted(barrier_passed) == ["任务 A", "任务 B"]
        dispatcher.shutdown(wait=True)
    finally:
        file_manager.close()
        sm_module._sqlalchemy_instance = previous_manager


def test_sink_does_not_kick_when_worker_active(monkeypatch):
    """回流到达时若父侧已有活跃 worker，sink 只入队不重复 kick（first-wins）。"""
    sink = ParentReentrySink(
        has_active_worker=lambda session_id: True,
        kick_reentry_run=lambda session_id, graph_id: False,
    )

    sink.dispatch(
        {
            "accepted": True,
            "taskId": "tsk_x",
            "adjudicationId": "adj_x",
            "deliveredStatus": "done",
            "safeSummary": "ok",
            "sessionId": "ast_active",
            "graphId": "graph_x",
        }
    )

    entries = sink.drain("ast_active")
    assert len(entries) == 1  # 入队
    # has_pending 仍可用于 worker 退出前 tail-kick 判定
    assert sink.has_pending("ast_active") is False


def test_sink_re_enqueues_drained_entries() -> None:
    # drain 是破坏性读取；run_agent 异常后 re_enqueue 把条目重新入队，防永久丢失。
    # 仅重新入队，不触发 kick（调用方决定是否重试，避免失败立即重试死循环）。
    sink = ParentReentrySink(
        has_active_worker=lambda session_id: False,
        kick_reentry_run=lambda session_id, graph_id: True,
    )
    sink.dispatch(
        {
            "accepted": True,
            "taskId": "tsk_re",
            "sessionId": "ast_re",
            "graphId": "g_re",
        }
    )
    drained = sink.drain("ast_re")
    assert len(drained) == 1
    assert sink.has_pending("ast_re") is False

    sink.re_enqueue("ast_re", drained)
    assert sink.has_pending("ast_re") is True
    assert [entry["taskId"] for entry in sink.drain("ast_re")] == ["tsk_re"]
