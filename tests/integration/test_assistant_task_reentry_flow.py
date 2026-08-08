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
from unittest.mock import MagicMock

from sqlalchemy.exc import IntegrityError

from src.business.agents.agent_loop import AgentLoop
from src.business.agents.config import AgentConfig, AgentResult, AgentType, ResultType
from src.business.orchestration.agent.task_executor_adapter import TaskExecutorAdapter
from src.business.orchestration.agent.orchestrator import AgentOrchestrator
from src.business.task_collaboration.dispatcher import TaskDispatcher
from src.business.task_collaboration.parent_reentry_sink import ParentReentrySink
from src.business.task_collaboration.service import TaskCollaborationService
from src.data.config_models import AiFailureRoutingConfig
from src.data.repos import (
    AssistantTaskAdjudicationRepository,
    AssistantTaskAttemptRepository,
    AssistantTaskRepository,
)
from src.desktop_api.schemas import AssistantTaskGraphSnapshot
from src.desktop_api.ui_event_projector import project_internal_event
from src.utils.events import connect, disconnect
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
        user_task_id=None,
        current_task_id=None,
        workspace_root=None,
        **_extra,
    ) -> dict:
        self.calls.append(
            {
                "parent_session_id": parent_session_id,
                "task": task,
                "user_task_id": user_task_id,
                "current_task_id": current_task_id,
                "workspace_root": workspace_root,
            }
        )
        return self._result

    def run_specialist_via_delegated_executor(self, **kwargs) -> dict:
        return self._result


class _AgentResultOrchestrator:
    """让真实 AgentResult 走生产 Orchestrator 的暂停 payload 映射。"""

    def __init__(self, result: AgentResult) -> None:
        self._result = result

    @property
    def delegation_orchestrator(self) -> "_AgentResultOrchestrator":
        return self

    def run_ephemeral_via_delegated_executor(self, **kwargs) -> dict:
        return AgentOrchestrator._build_delegated_pause_payload(
            self._result,
            session_id="ast_quota_child",
            workflow_id="wf_quota_child",
        )


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


def _paused_dispatcher(
    monkeypatch,
    *,
    session_id: str,
    title: str,
    result: dict | None = None,
    orchestrator=None,
):
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
        executor_callback=TaskExecutorAdapter(orchestrator or _FakeOrchestrator(result or {})),
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


def test_quota_pause_waits_for_user_without_waking_the_parent(monkeypatch, mock_config):
    """同一真实异常贯穿 AgentResult、派发、DB、DTO 与 UI，且不泄漏。"""
    sentinel = "sk-quota-route-must-not-leak"
    mock_config.get_ai_retry_max_retries.return_value = 0
    mock_config.get_ai_retry_delay.return_value = 0
    mock_config.get_ai_failure_routing.return_value = AiFailureRoutingConfig()

    session_store = AgentOrchestrator(MagicMock(), mock_config)._session_store
    agent_session_id = session_store.create_session("wf_quota_source", AgentType.EPHEMERAL_SUBAGENT)
    llm = MagicMock()
    llm.chat_with_tools.side_effect = RuntimeError(
        f"provider error: insufficient_quota account=private-user token={sentinel}"
    )
    agent_result = AgentLoop(
        AgentConfig(
            agent_type=AgentType.EPHEMERAL_SUBAGENT,
            system_prompt="sub",
            max_iterations=2,
            resumable_on_failure=True,
        ),
        llm,
        mock_config,
    ).run(agent_session_id, user_input="go", tools=[])
    assert agent_result.result_type == ResultType.PAUSED
    assert sentinel not in repr(agent_result)

    captured_events: list[dict] = []

    def capture_task_event(sender, **kwargs):
        if kwargs.get("session_id") == "ast_quota":
            captured_events.append(kwargs)

    connect("assistant_task_graph_changed", capture_task_event, weak=False)
    try:
        _, task_id, sink, kicks, payload = _paused_dispatcher(
            monkeypatch,
            session_id="ast_quota",
            title="调用模型完成分析",
            orchestrator=_AgentResultOrchestrator(agent_result),
        )
    finally:
        disconnect("assistant_task_graph_changed", capture_task_event)

    with AssistantTaskRepository() as tasks:
        row = tasks.get_task(task_id)
    assert row.status == "suspended"
    assert row.suspend_reason == "quota_exhausted"
    assert row.waiting_on == "user"
    assert sentinel not in repr(vars(row))

    with AssistantTaskAttemptRepository() as attempts:
        assert attempts.get_by_id(payload["attemptId"]).status == "paused"

    assert sentinel not in repr(payload)
    service = TaskCollaborationService()
    try:
        snapshot = service.get_graph_snapshot(session_id="ast_quota", graph_id=row.graph_id)
        dto = AssistantTaskGraphSnapshot.model_validate(service.snapshot_to_dict(snapshot))
    finally:
        service.close()
    assert sentinel not in dto.model_dump_json()

    suspended_event = next(
        event for event in captured_events if event.get("suspend_reason") == "quota_exhausted"
    )
    drafts = project_internal_event("assistant_task_graph_changed", suspended_event)
    assert drafts
    assert sentinel not in repr(drafts)

    assert sink.drain("ast_quota") == []
    assert kicks == []


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


def test_a_code_defect_stops_the_task_and_offers_no_retry(monkeypatch):
    """撞上确定性代码缺陷：活停下、主助理被叫醒，而它拿到的选项里**没有重试**。

    7/28 实跑：写库撞 CHECK 约束（板上钉钉的代码缺陷）被包装成"内部错误，需上级
    检查后决定是否重试"。主助理照建议重试了 7 次，每次崩在同一个地方——1 小时
    13 分钟、0 产出。它没做错任何事，是那句话在骗它。

    所以这里的定义性验收不是"文案改好了"（那靠模型读懂），是**动作候选集里
    根本没有 retry**——它想重试也没这个选项。
    """
    graph_id, task_id, sink, kicks, payload = _paused_dispatcher(
        monkeypatch,
        session_id="ast_defect",
        title="写后端 DTO",
        result={
            "success": False,
            "message": "这一步撞上程序缺陷，重试不会改变结果。",
            "failure_class": "code_defect",
            "failure_exception_type": "IntegrityError",
            "executor_session_id": "ast_child",
        },
    )

    # 1. 活停着、保留着，而且记下了球在主助理手上
    with AssistantTaskRepository() as tasks:
        row = tasks.get_task(task_id)
    assert row.status == "suspended"
    assert row.suspend_reason == "blocked_by_defect"
    assert row.waiting_on == "assistant"

    # 2. 主助理被叫醒 —— 用户处理不了，只有它能做绕行决定
    entries = sink.drain("ast_defect")
    assert len(entries) == 1
    assert entries[0]["eventType"] == "blocked_by_defect"
    assert kicks == [("ast_defect", graph_id)]

    # 3. 给它的动作里没有重试，但也不能空着——得告诉它能做什么
    actions = entries[0].get("healingActions") or []
    assert actions, "缺陷节点也要给出可选动作，否则主助理不知道能做什么"
    assert "retry" not in actions
    assert "swap_executor" not in actions, "换个执行体也是同一个错"
    assert "adjust_input" not in actions, "改输入也绕不开代码里的那个 bug"

    # 4. 用户那边：卡片上要说人话。用户处理不了缺陷，但他有权知道这一步做不了了
    service = TaskCollaborationService()
    try:
        snapshot = service.get_graph_snapshot(session_id="ast_defect", graph_id=graph_id)
    finally:
        service.close()
    node = next(t for t in snapshot.tasks if t.task_id == task_id)
    assert node.safe_explanation, "停在缺陷上的活必须给用户一句说明，不能只是「暂停」"
    assert "程序" in node.safe_explanation
    # 内部术语不进 UI：用户不需要知道 defect / exception / IntegrityError 是什么
    for internal_word in ("defect", "exception", "IntegrityError", "blocked_by"):
        assert internal_word not in node.safe_explanation


def test_a_crash_while_recording_the_outcome_does_not_leave_the_attempt_running(monkeypatch):
    """记账崩溃此前会被线程池整个吞掉，然后无限重派。

    执行体跑完了 → 系统把结果记进账本 → 记账时崩了（写了不合法的值）
      → worker 线程整个崩溃，而没有人去接它的结果（Future 无人 .result()）
      → 只剩一行日志，活停在「运行中」
      → 两分钟租约过期 → 系统以为它失联 → 重新派一个 → 再跑一遍 → 记账时再崩
      → 无限循环

    7/28 那 7 次重试是主助理照着假建议做的；**这一类连主助理都不知道**，
    是系统自己在转圈。所以这条的定义性验收是：attempt 不许停在活跃状态。
    """
    _patch_dispatch_config(monkeypatch)

    service = TaskCollaborationService()
    _, task_id = _create_child_task(service, session_id="ast_crash", title="写后端 DTO")
    service.close()

    def _boom(self, **kwargs):
        raise IntegrityError(
            "UPDATE assistant_tasks SET suspend_reason=?",
            {},
            Exception("CHECK constraint failed: ck_assistant_tasks_suspend_reason"),
        )

    monkeypatch.setattr(TaskDispatcher, "_record_attempt_paused", _boom)

    sink = ParentReentrySink(
        has_active_worker=lambda sid: False,
        kick_reentry_run=lambda sid, gid: True,
    )
    dispatcher = TaskDispatcher(
        cutover_guard=_AllowGuard(),
        executor_callback=TaskExecutorAdapter(
            _FakeOrchestrator(
                {
                    "success": False,
                    "paused": True,
                    "pause_reason": "budget_exhausted",
                    "message": "已达迭代上限（30 轮）",
                    "subagent_id": "ast_child",
                }
            )
        ),
        parent_reentry_callback=sink.dispatch,
    )
    future = dispatcher.start_attempt_async(
        task_id=task_id,
        executor_type="ephemeral_subagent",
        executor_id=task_id,
        lease_owner="test",
    )
    assert future is not None

    # 1. 不再往线程池里抛——worker 返回一个明确结果，而不是消失
    payload = future.result(timeout=5)
    assert payload["accepted"] is False
    assert payload.get("recordingFailed") is True

    # 2. attempt 让出执行者槽。这条是「无限重派」的定义性验收：
    #    停在活跃状态的话，租约一过期就会被当成失联重派，然后再撞同一个约束。
    with AssistantTaskAttemptRepository() as attempts:
        status = attempts.get_by_id(payload["attemptId"]).status
    assert status not in AssistantTaskAttemptRepository.ACTIVE_STATUSES, (
        f"attempt 停在 {status}，租约过期后会被重派，再撞同一个缺陷——无限循环"
    )


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
                user_task_id=None,
                current_task_id=None,
                workspace_root=None,
                **_extra,
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
