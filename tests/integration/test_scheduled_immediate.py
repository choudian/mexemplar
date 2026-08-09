"""T045: 端到端冒烟 — 立即任务 创建 → 触发 → 执行 → 完成静默判定 → 历史 succeeded。

US1 MVP 闭环验证（轻量 mock 版，避开完整 FastAPI lifespan / 真实 LLM）：

1. 创建经确认卡：``SchedulingConfirmationManager.create`` → ``submit_decision(confirm)``
   → task 落库 + ``scheduler_task_changed`` 事件。
2. 触发：``SchedulerService.fire_now`` → ``SessionLauncher.launch``（mock dispatch_callback）
   → ``source=scheduled`` 会话建立 + run 账目建立。
3. 完成静默判定：``RunCompletionMonitor.evaluate_session``（注入 mock callbacks 模拟静默）
   → run → ``succeeded`` + ``scheduler_run_terminal`` 事件。
4. 历史可见：``SchedulerService.list_runs`` 返回 ``succeeded`` run。
5. 聊天屏不可见：``ChatService.get_sessions_with_preview`` 排除 ``source=scheduled`` 会话。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from src.business.agents.config import AgentType
from src.business.scheduling.run_completion_monitor import RunCompletionMonitor
from src.business.scheduling.scheduler_service import SchedulerService
from src.business.scheduling.scheduling_confirmation_manager import (
    SchedulingConfirmationManager,
    reset_state_for_tests as reset_confirmation_state,
)
from src.business.scheduling.session_launcher import SessionLauncher
from src.business.services.chat_service import ChatService
from src.data.models_sqlite import Message, Session
from src.data.repos.message_repository import MessageRepository
from src.data.repos.scheduled_task_run_repository import ScheduledTaskRunRepository
from src.data.repos.scheduled_task_repository import ScheduledTaskRepository
from src.data.repos.session_repository import SessionRepository


@pytest.fixture(autouse=True)
def _reset_confirmation():
    reset_confirmation_state()
    yield
    reset_confirmation_state()


def _capture_events(*names):
    """捕获 blinker 事件（强引用 callback 防 GC）。"""
    from src.utils.events import connect

    captured: dict[str, list[dict]] = {n: [] for n in names}
    refs = []

    def make_handler(name):
        def handler(sender, **kwargs):
            captured[name].append(kwargs)

        return handler

    for name in names:
        h = make_handler(name)
        refs.append(h)
        connect(name, h, weak=False)
    return captured, refs


def _create_user_session(session_id: str = "ast_user_chat") -> str:
    """建一条普通用户会话（聊天屏应可见）。"""
    SessionRepository().create(
        Session(
            session_id=session_id,
            workflow_id=None,
            agent_type=AgentType.ASSISTANT,
            status="active",
        )
    )
    return session_id


def test_scheduled_immediate_full_flow():
    """US1 立即触发 MVP 全链路（mock LLM / mock dispatch）。"""
    captured, _refs = _capture_events(
        "scheduler_task_changed",
        "scheduler_run_terminal",
        "scheduling_confirmation_requested",
        "scheduling_confirmation_resolved",
    )

    # ---- 1. 创建经确认卡：draft → confirm → task 落库 ----
    draft = {
        "source_type": "direct",
        "schedule_kind": "one_shot",
        "schedule_payload": {"run_at": "2026-07-19T10:00:00", "tz": "Asia/Shanghai"},
        "instruction": "帮我查一下竞品 X 的最新价格",
        "title": "查竞品价格",
        "source_ref": "帮我查一下竞品 X 的最新价格",
    }
    manager = SchedulingConfirmationManager()
    request_id = manager.create(draft, session_id="ast_user_main")
    # 确认卡 requested 事件
    assert len(captured["scheduling_confirmation_requested"]) == 1
    requested = captured["scheduling_confirmation_requested"][0]
    assert requested["request_id"] == request_id
    expires_at = datetime.fromisoformat(requested["expires_at"])
    assert expires_at.tzinfo is not None
    assert expires_at.utcoffset() == timedelta(0)

    # mock dispatch_callback：记录调用、返回 True
    dispatched: list[tuple[str, str]] = []

    def _dispatch(
        session_id: str,
        instruction: str,
        _run_id: str,
        _reservation_id: str,
    ) -> bool:
        dispatched.append((session_id, instruction))
        return True

    # service_factory 注入带 launcher 的 SchedulerService
    launcher = SessionLauncher(dispatch_callback=_dispatch)
    with SchedulerService(launcher=launcher) as service:
        # confirm 决策落库
        task = manager.submit_decision(
            request_id,
            "confirm",
            None,
            False,
            service_factory=lambda: service,
        )
        assert task is not None
        assert task["scheduledTaskId"].startswith("sch_")
        assert task["status"] == "active"
        task_id = task["scheduledTaskId"]
        # scheduler_task_changed(created) + confirmation_resolved(confirmed)
        assert any(e.get("change_type") == "created" for e in captured["scheduler_task_changed"])
        assert any(
            e.get("status") == "confirmed" for e in captured["scheduling_confirmation_resolved"]
        )

        # ---- 2. 触发：fire_now → launcher 启动 scheduled 会话 + 建 run ----
        run = service.fire_now(task_id)
        assert run["status"] == "running"
        run_id = run["runId"]
        session_id = run["sessionId"]
        assert session_id.startswith("ast_")
        # dispatch_callback 被调用
        assert len(dispatched) == 1
        assert dispatched[0][0] == session_id
        assert "竞品" in dispatched[0][1]

        # ---- 3. 验证：scheduled 会话从聊天屏排除 ----
        _create_user_session("ast_user_visible")
        chat_service = ChatService()
        previews = chat_service.get_sessions_with_preview()
        chat_session_ids = {p["session_id"] for p in previews}
        assert "ast_user_visible" in chat_session_ids  # 用户会话可见
        assert session_id not in chat_session_ids  # scheduled 会话不可见（FR-021）

        # ---- 4. 完成静默判定：注入 mock callbacks 模拟静默 ----
        # 给 scheduled 会话塞一条 assistant 消息（summary 抽取用）
        with MessageRepository() as mr:
            mr.session.add(
                Message(
                    message_id=f"msg_{session_id}",
                    session_id=session_id,
                    role="assistant",
                    content="已完成：竞品 X 最新价格 129 元",
                    sequence=1,
                )
            )
            mr.session.commit()

        # 构造一个全 completed 的图 snapshot（模拟主助理委派完成）
        completed_snapshot = SimpleNamespace(
            tasks=[
                SimpleNamespace(task_id="root", parent_task_id=None, status="done"),
                SimpleNamespace(task_id="t1", parent_task_id="root", status="done"),
            ]
        )

        with ScheduledTaskRunRepository() as rr:
            monitor = RunCompletionMonitor(
                has_active_worker=lambda sid: False,  # worker 已退出
                has_pending_reentry=lambda sid: False,  # 无 pending 回流
                get_graph_snapshot=lambda sid: completed_snapshot,
                run_repo=rr,
            )
            result = monitor.evaluate_session(session_id)
            assert result is not None
            assert result["status"] == "succeeded"
            assert "129 元" in result["summary"]

        # scheduler_run_terminal 事件
        terminal_events = [
            e for e in captured["scheduler_run_terminal"] if e.get("status") == "succeeded"
        ]
        assert len(terminal_events) == 1
        assert terminal_events[0]["run_id"] == run_id

        # ---- 5. 历史可见：list_runs 返回 succeeded run ----
        runs, total = service.list_runs(task_id)
        assert total >= 1
        succeeded_runs = [r for r in runs if r["status"] == "succeeded"]
        assert len(succeeded_runs) == 1
        assert succeeded_runs[0]["runId"] == run_id
        assert "129 元" in succeeded_runs[0]["summary"]


@pytest.mark.parametrize(
    # 两列是**两个状态机**：node_status 是任务节点的状态，expected_outcome 是这一轮
    # 调度 run 的结局。任务被"放弃"，而这轮调度的结局仍然是"没成"——词不同，因为
    # 说的不是一件事。
    ("node_status", "expected_outcome"),
    [
        ("done", "succeeded"),
        ("abandoned", "failed"),
    ],
)
def test_graph_terminal_event_reaches_connected_completion_monitor(
    node_status: str,
    expected_outcome: str,
):
    """真实 blinker 接线把终态图推进为单次 run 终态，不靠直接调用 monitor。"""
    from src.utils.events import connect, disconnect, emit
    from src.data.repos.assistant_task_repository import AssistantTaskRepository

    session_id = f"ast_graph_event_{expected_outcome}"
    graph_id = f"graph_{expected_outcome}"
    with ScheduledTaskRepository() as task_repo:
        task = task_repo.create(
            source_type="direct",
            source_ref="graph event wiring",
            title="图终态接线",
            schedule_kind="one_shot",
            schedule_payload={"run_at": "2026-07-19T10:00:00"},
        )
    snapshot = SimpleNamespace(
        tasks=[
            SimpleNamespace(
                task_id="root",
                parent_task_id=None,
                status="pending_dispatch",
            ),
            SimpleNamespace(
                task_id="executor",
                parent_task_id="root",
                status=node_status,
            ),
        ]
    )
    terminal_events: list[dict] = []

    def _capture_terminal(_sender, **kwargs):
        terminal_events.append(kwargs)

    with ScheduledTaskRunRepository() as run_repo:
        run = run_repo.create(
            scheduled_task_id=task.scheduled_task_id,
            session_id=session_id,
            baseline_message_sequence=0,
            trigger_message_sequence=1,
        )
        with AssistantTaskRepository() as graph_repo:
            graph_repo.create_task(
                graph_id=graph_id,
                session_id=session_id,
                task_id=f"tsk_root_{expected_outcome}",
                title="root",
                description="root",
                user_message_sequence=1,
            )
        monitor = RunCompletionMonitor(
            has_active_worker=lambda _sid: False,
            has_pending_reentry=lambda _sid: False,
            get_graph_snapshot=lambda _sid: snapshot,
            run_repo=run_repo,
        )
        connect("scheduler_run_terminal", _capture_terminal, weak=False)
        monitor.connect()
        try:
            for _ in range(2):
                emit(
                    "graph_scheduler_terminal",
                    None,
                    graph_id=graph_id,
                    session_id=session_id,
                    all_terminal=True,
                    all_completed=expected_outcome == "succeeded",
                )
            persisted = run_repo.get(run.run_id)
            assert persisted is not None
            assert persisted.status == expected_outcome
        finally:
            monitor.disconnect()
            disconnect("scheduler_run_terminal", _capture_terminal)

    matching = [
        event
        for event in terminal_events
        if event.get("run_id") == run.run_id and event.get("status") == expected_outcome
    ]
    assert len(matching) == 1


def test_scheduled_immediate_reentry_skip():
    """US1 reentry：同任务有活跃 run 时，fire_now 记 skipped 不并发。"""
    captured, _refs = _capture_events("scheduler_run_terminal")
    dispatched: list = []

    launcher = SessionLauncher(
        dispatch_callback=lambda sid, instr, _run_id, _reservation_id: (
            dispatched.append((sid, instr)) or True
        )
    )
    with SchedulerService(launcher=launcher) as service:
        from src.data.repos.scheduled_task_repository import ScheduledTaskRepository

        with ScheduledTaskRepository() as r:
            task = r.create(
                source_type="direct",
                source_ref="reentry 测试",
                title="reentry",
                schedule_kind="one_shot",
                schedule_payload={"run_at": "2026-07-19T10:00:00"},
            )
            task_id = task.scheduled_task_id

        # 第一次 fire → 正常启动 run
        run1 = service.fire_now(task_id)
        assert run1["status"] == "running"
        assert len(dispatched) == 1

        # 第二次 fire → reentry skip（同任务有活跃 run）
        run2 = service.fire_now(task_id)
        assert run2["status"] == "skipped"
        # 第二次不应 dispatch（skipped 不启动会话）
        assert len(dispatched) == 1

        # skipped run 事件
        skipped_events = [
            e for e in captured["scheduler_run_terminal"] if e.get("status") == "skipped"
        ]
        assert len(skipped_events) == 1

        # 历史：一条 running + 一条 skipped
        runs, _ = service.list_runs(task_id)
        statuses = [r["status"] for r in runs]
        assert "running" in statuses
        assert "skipped" in statuses


def test_scheduled_immediate_confirmation_cancel():
    """US1 确认卡 cancel 路径：不落库、emit resolved(cancelled)。"""
    captured, _refs = _capture_events(
        "scheduling_confirmation_resolved",
        "scheduler_task_changed",
    )
    manager = SchedulingConfirmationManager()
    request_id = manager.create(
        {
            "source_type": "direct",
            "schedule_kind": "one_shot",
            "schedule_payload": {"run_at": "2026-07-19T10:00:00"},
            "instruction": "取消测试",
            "title": "取消",
            "source_ref": "取消测试",
        },
        "ast_cancel_session",
    )
    result = manager.submit_decision(request_id, "cancel")
    assert result == {}
    # resolved(cancelled)
    assert any(e.get("status") == "cancelled" for e in captured["scheduling_confirmation_resolved"])
    # 不落库 = 无 scheduler_task_changed(created) 事件
    created_events = [
        e for e in captured["scheduler_task_changed"] if e.get("change_type") == "created"
    ]
    assert len(created_events) == 0
