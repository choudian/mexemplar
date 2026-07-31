"""T022: RunCompletionMonitor 完成判定三条件测试（033 US1）。

验证 FR-012 静默三条件（worker 退出 ∧ 无 pending 回流 ∧ 图全终态）：

1. **首轮 durable accepted 不误报完成**：run running + worker 仍活跃 → 不置终态；
   worker 退出但图未全终态 → 仍不置终态（必须等真正静默）。
2. **含失败/取消图不漏报**（不依赖 root=completed）：执行节点有 failed/cancelled
   时 all_terminal=True / all_completed=False → run → failed（而不是看 root status）。
3. **回流续跑轮后置终态**：waiting_user 接管回 running 后，需等下一轮静默才置终态。

用 ``compute_graph_terminal_state`` + 注入 mock callbacks 驱动 evaluate_session。
"""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace

import pytest

from src.business.task_collaboration.graph_terminal import compute_graph_terminal_state
from src.business.task_collaboration.models import TERMINAL_TASK_STATUSES, TaskStatus

# 终态集合与完成态字符串（与 monitor 内部使用一致）
_TERM = TERMINAL_TASK_STATUSES
_DONE = str(TaskStatus.COMPLETED)


def _executor(task_id, status, parent_id="root"):
    """构造一个执行节点（parent_task_id 非 None）。"""
    return SimpleNamespace(task_id=task_id, parent_task_id=parent_id, status=status)


def _root(status="pending_dispatch"):
    """根容器节点（parent_task_id is None）—— 不参与终态统计。"""
    return SimpleNamespace(task_id="root", parent_task_id=None, status=status)


# ---------------------------------------------------------------------------
# 纯函数层：compute_graph_terminal_state 的三条件语义
# ---------------------------------------------------------------------------


def test_graph_all_completed_returns_terminal_and_completed():
    tasks = [
        _root(),
        _executor("t1", "completed"),
        _executor("t2", "completed"),
    ]
    all_terminal, all_completed = compute_graph_terminal_state(
        tasks, terminal_statuses=_TERM, completed_status=_DONE
    )
    assert all_terminal is True
    assert all_completed is True


def test_graph_with_failed_executor_terminal_but_not_completed():
    """含 failed 执行节点：all_terminal=True 但 all_completed=False（不依赖 root=completed）。"""
    tasks = [
        _root(status="completed"),  # 即使 root completed，含 failed 子节点也不算全成功
        _executor("t1", "completed"),
        _executor("t2", "abandoned"),
    ]
    all_terminal, all_completed = compute_graph_terminal_state(
        tasks, terminal_statuses=_TERM, completed_status=_DONE
    )
    assert all_terminal is True
    assert all_completed is False


def test_graph_with_cancelled_executor_terminal_but_not_completed():
    tasks = [
        _root(),
        _executor("t1", "cancelled"),
    ]
    all_terminal, all_completed = compute_graph_terminal_state(
        tasks, terminal_statuses=_TERM, completed_status=_DONE
    )
    assert all_terminal is True
    assert all_completed is False


def test_graph_non_terminal_running_does_not_qualify():
    """首轮 durable accepted：还有 running 执行节点 → all_terminal=False（不误报完成）。"""
    tasks = [
        _root(),
        _executor("t1", "completed"),
        _executor("t2", "in_progress"),  # 仍在跑
    ]
    all_terminal, all_completed = compute_graph_terminal_state(
        tasks, terminal_statuses=_TERM, completed_status=_DONE
    )
    assert all_terminal is False
    assert all_completed is False


def test_graph_root_only_degenerates_to_terminal_completed():
    """无执行节点（退化 root-only 图）→ (True, True)，与 all([]) 语义一致。"""
    tasks = [_root()]
    all_terminal, all_completed = compute_graph_terminal_state(
        tasks, terminal_statuses=_TERM, completed_status=_DONE
    )
    assert all_terminal is True
    assert all_completed is True


# ---------------------------------------------------------------------------
# Monitor 行为层：evaluate_session 三条件
# ---------------------------------------------------------------------------


def _make_monitor(
    *,
    has_active_worker,
    has_pending_reentry,
    snapshot_tasks,
    run_repo,
    message_repo=None,
):
    """构造 monitor（注入全部 callback，避开 desktop_api 依赖）。"""
    from src.business.scheduling.run_completion_monitor import RunCompletionMonitor

    snapshot = SimpleNamespace(tasks=snapshot_tasks) if snapshot_tasks is not None else None

    def _get_snapshot(_session_id):
        return snapshot

    monitor = RunCompletionMonitor(
        has_active_worker=has_active_worker,
        has_pending_reentry=has_pending_reentry,
        get_graph_snapshot=_get_snapshot,
        run_repo=run_repo,
        message_repo=message_repo,
    )
    return monitor


def _seed_run(run_repo, *, run_id="schr_x", session_id="ast_x", task_id="sch_x", status="running"):
    from src.data.repos.scheduled_task_run_repository import ScheduledTaskRunRepository
    from src.utils.timezone import utc_now_naive

    assert isinstance(run_repo, ScheduledTaskRunRepository)
    run = run_repo.create(
        scheduled_task_id=task_id, session_id=session_id, started_at=utc_now_naive()
    )
    if status != "running":
        run_repo.cas_transition(run.run_id, from_status="running", to_status=status)
    return run


class _MessageRepoStub:
    def __init__(self, messages, *, summary="执行回合已结束"):
        self._messages = messages
        self._summary = summary

    def get_all(self, _session_id):
        return self._messages

    def list_tool_messages_after(
        self,
        _session_id,
        *,
        after_sequence,
        tool_names,
    ):
        del after_sequence
        return [
            message
            for message in self._messages
            if getattr(message, "role", None) == "tool"
            and getattr(message, "tool_name", None) in tool_names
        ]

    def get_latest_assistant_text(
        self,
        _session_id,
        max_length=500,
        *,
        after_sequence=None,
    ):
        del after_sequence
        return self._summary[:max_length]


@pytest.mark.parametrize(
    ("event_name", "payload"),
    [
        (
            "graph_scheduler_terminal",
            {
                "graph_id": "tg_event_failure",
                "session_id": "ast_event_failure",
                "all_terminal": True,
                "all_completed": True,
            },
        ),
        (
            "assistant_task_root_failed",
            {
                "session_id": "ast_event_failure",
                "graph_id": "tg_event_failure",
                "task_id": "task_event_failure",
                "change_type": "failed",
                "status": "failed",
                "display_phase": "failed",
                "safe_explanation": "task failed",
            },
        ),
    ],
)
def test_event_receivers_isolate_completion_evaluation_failures(
    monkeypatch,
    caplog,
    event_name,
    payload,
):
    """同步 observer 失败不得反向打断 task collaboration 核心事件发送方。"""
    from src.business.scheduling.run_completion_monitor import RunCompletionMonitor
    from src.utils import events

    monitor = RunCompletionMonitor()
    monkeypatch.setattr(monitor, "retry_pending_terminal_events", lambda: 0)

    monkeypatch.setattr(
        monitor,
        "resolve_run_id_for_graph",
        lambda **_kwargs: "schr_event_failure",
    )

    def _raise(_run_id):
        raise RuntimeError("completion store unavailable")

    monkeypatch.setattr(monitor, "evaluate_run", _raise)
    monitor.connect()
    try:
        with caplog.at_level(
            logging.ERROR,
            logger="src.business.scheduling.run_completion_monitor",
        ):
            events.emit(event_name, object(), **payload)
    finally:
        monitor.disconnect()

    assert event_name in caplog.text
    assert "schr_event_failure" in caplog.text
    assert "completion store unavailable" in caplog.text


def test_evaluate_does_not_finalize_when_worker_still_active():
    """条件 1：worker 仍活跃 → 不置终态（首轮 durable accepted 不误报完成）。"""
    from src.data.repos.scheduled_task_run_repository import (
        ScheduledTaskRunRepository,
    )

    with ScheduledTaskRunRepository() as rr:
        _seed_run(rr, run_id="schr_active", session_id="ast_active")
        monitor = _make_monitor(
            has_active_worker=lambda sid: True,  # worker 仍在跑
            has_pending_reentry=lambda sid: False,
            snapshot_tasks=[_root(), _executor("t1", "completed")],
            run_repo=rr,
        )
        result = monitor.evaluate_session("ast_active")
        assert result is None  # 未静默，不写终态
        # run 仍 running
        refreshed = rr.get_by_session("ast_active")
        assert refreshed.status == "running"


def test_evaluate_does_not_finalize_when_graph_not_terminal():
    """条件 1：worker 退出但图未全终态 → 仍不置终态（等回流 / 续跑）。"""
    from src.data.repos.scheduled_task_run_repository import (
        ScheduledTaskRunRepository,
    )

    with ScheduledTaskRunRepository() as rr:
        _seed_run(rr, session_id="ast_graph_not_term")
        monitor = _make_monitor(
            has_active_worker=lambda sid: False,
            has_pending_reentry=lambda sid: False,
            snapshot_tasks=[
                _root(),
                _executor("t1", "completed"),
                _executor("t2", "in_progress"),  # 仍在跑
            ],
            run_repo=rr,
        )
        result = monitor.evaluate_session("ast_graph_not_term")
        assert result is None
        assert rr.get_by_session("ast_graph_not_term").status == "running"


def test_evaluate_marks_failed_when_graph_has_failed_executor():
    """条件 2：含 failed 执行节点（worker 退出 + 图全终态 + 非全 completed）→ failed。"""
    from src.data.repos.scheduled_task_run_repository import (
        ScheduledTaskRunRepository,
    )

    with ScheduledTaskRunRepository() as rr:
        _seed_run(rr, session_id="ast_failed")
        monitor = _make_monitor(
            has_active_worker=lambda sid: False,
            has_pending_reentry=lambda sid: False,
            snapshot_tasks=[
                _root(status="completed"),
                _executor("t1", "completed"),
                _executor("t2", "abandoned"),  # 含失败
            ],
            run_repo=rr,
        )
        result = monitor.evaluate_session("ast_failed")
        assert result is not None
        assert result["status"] == "failed"
        assert rr.get_by_session("ast_failed").status == "failed"


def test_evaluate_marks_succeeded_when_all_completed_and_quiescent():
    """happy path：全 completed + 静默 → succeeded（含 summary 抽取）。"""
    from src.data.repos.message_repository import MessageRepository
    from src.data.repos.scheduled_task_run_repository import (
        ScheduledTaskRunRepository,
    )
    from src.data.repos.session_repository import SessionRepository
    from src.data.models_sqlite import Message, Session
    from src.business.agents.config import AgentType

    with ScheduledTaskRunRepository() as rr, MessageRepository() as mr:
        # 建会话 + 一条 assistant 消息供 summary 抽取
        SessionRepository().create(
            Session(
                session_id="ast_ok",
                workflow_id=None,
                agent_type=AgentType.ASSISTANT,
                status="active",
            )
        )
        mr.session.add(
            Message(
                message_id="msg_1",
                session_id="ast_ok",
                role="assistant",
                content="已完成：竞品 A 价格 99 元",
                sequence=1,
            )
        )
        mr.session.commit()
        _seed_run(rr, session_id="ast_ok")
        monitor = _make_monitor(
            has_active_worker=lambda sid: False,
            has_pending_reentry=lambda sid: False,
            snapshot_tasks=[_root(), _executor("t1", "completed")],
            run_repo=rr,
            message_repo=mr,
        )
        result = monitor.evaluate_session("ast_ok")
        assert result is not None
        assert result["status"] == "succeeded"
        assert "99 元" in result["summary"]


def test_no_graph_without_successful_delegation_is_failed_not_false_success():
    """精确回归：只重复创建定时任务、未委派实际工作，不能记为 succeeded。"""
    from src.data.repos.scheduled_task_run_repository import (
        ScheduledTaskRunRepository,
    )

    message_repo = _MessageRepoStub(
        [
            SimpleNamespace(
                role="tool",
                tool_name="create_scheduled_task",
                content=json.dumps(
                    {
                        "schemaVersion": 1,
                        "tool": "create_scheduled_task",
                        "outcome": "success",
                        "payload": {"content": '{"success": true}'},
                    }
                ),
            )
        ],
        summary="已为你创建新的定时任务。",
    )
    with ScheduledTaskRunRepository() as rr:
        _seed_run(rr, session_id="ast_false_success")
        monitor = _make_monitor(
            has_active_worker=lambda _sid: False,
            has_pending_reentry=lambda _sid: False,
            snapshot_tasks=None,
            run_repo=rr,
            message_repo=message_repo,
        )

        result = monitor.evaluate_session("ast_false_success")

        assert result is not None
        assert result["status"] == "failed"
        assert rr.get_by_session("ast_false_success").status == "failed"


def test_no_graph_with_successful_sync_delegation_is_succeeded():
    """简单任务允许不建图，但必须有可审计的成功同步委派结果。"""
    from src.data.repos.scheduled_task_run_repository import (
        ScheduledTaskRunRepository,
    )

    message_repo = _MessageRepoStub(
        [
            SimpleNamespace(
                role="tool",
                tool_name="delegate_to_subagent",
                content=json.dumps(
                    {
                        "schemaVersion": 1,
                        "tool": "delegate_to_subagent",
                        "outcome": "success",
                        "payload": {"content": '{"success": true}'},
                    }
                ),
            )
        ],
        summary="报告已经写入知识库。",
    )
    with ScheduledTaskRunRepository() as rr:
        _seed_run(rr, session_id="ast_sync_delegated")
        monitor = _make_monitor(
            has_active_worker=lambda _sid: False,
            has_pending_reentry=lambda _sid: False,
            snapshot_tasks=None,
            run_repo=rr,
            message_repo=message_repo,
        )

        result = monitor.evaluate_session("ast_sync_delegated")

        assert result is not None
        assert result["status"] == "succeeded"
        assert result["summary"] == "报告已经写入知识库。"


def test_new_run_cannot_reuse_previous_run_delegation_evidence() -> None:
    from src.business.agents.config import AgentType
    from src.business.scheduling.run_completion_monitor import RunCompletionMonitor
    from src.data.models_sqlite import Message, Session
    from src.data.repos.message_repository import MessageRepository
    from src.data.repos.scheduled_task_run_repository import ScheduledTaskRunRepository
    from src.data.repos.session_repository import SessionRepository

    SessionRepository().create(
        Session(
            session_id="ast_reused_window",
            workflow_id=None,
            agent_type=AgentType.ASSISTANT,
            status="active",
        )
    )
    with MessageRepository() as messages:
        messages.create(
            Message(
                message_id="msg_old_trigger",
                session_id="ast_reused_window",
                sequence=1,
                role="user",
                content="old trigger",
            )
        )
        messages.create(
            Message(
                message_id="msg_old_delegate",
                session_id="ast_reused_window",
                sequence=2,
                role="tool",
                tool_name="delegate_to_subagent",
                content='{"success": true}',
            )
        )
    with ScheduledTaskRunRepository() as runs, MessageRepository() as messages:
        previous = runs.create(
            scheduled_task_id="sch_reused_window",
            session_id="ast_reused_window",
            baseline_message_sequence=0,
            trigger_message_sequence=1,
        )
        runs.cas_transition(previous.run_id, from_status="running", to_status="succeeded")
        current = runs.create(
            scheduled_task_id="sch_reused_window",
            session_id="ast_reused_window",
            baseline_message_sequence=2,
            trigger_message_sequence=3,
        )
        monitor = RunCompletionMonitor(
            has_active_worker=lambda _sid: False,
            has_pending_reentry=lambda _sid: False,
            get_graph_snapshot=lambda _sid: None,
            run_repo=runs,
            message_repo=messages,
        )

        result = monitor.evaluate_run(current.run_id)

        assert result is not None
        assert result["status"] == "failed"
        assert runs.get_fresh(current.run_id).status == "failed"


def test_run_summary_uses_only_assistant_text_after_its_baseline() -> None:
    from src.business.agents.config import AgentType
    from src.business.scheduling.run_completion_monitor import RunCompletionMonitor
    from src.data.models_sqlite import Message, Session
    from src.data.repos.message_repository import MessageRepository
    from src.data.repos.scheduled_task_run_repository import ScheduledTaskRunRepository
    from src.data.repos.session_repository import SessionRepository

    SessionRepository().create(
        Session(
            session_id="ast_summary_window",
            workflow_id=None,
            agent_type=AgentType.ASSISTANT,
            status="active",
        )
    )
    with MessageRepository() as messages:
        for message in (
            Message(
                message_id="msg_old_summary",
                session_id="ast_summary_window",
                sequence=2,
                role="assistant",
                content="old summary",
            ),
            Message(
                message_id="msg_current_delegate",
                session_id="ast_summary_window",
                sequence=4,
                role="tool",
                tool_name="delegate_to_subagent",
                content='{"success": true}',
            ),
            Message(
                message_id="msg_current_summary",
                session_id="ast_summary_window",
                sequence=5,
                role="assistant",
                content="current summary",
            ),
        ):
            messages.create(message)
    with ScheduledTaskRunRepository() as runs, MessageRepository() as messages:
        run = runs.create(
            scheduled_task_id="sch_summary_window",
            session_id="ast_summary_window",
            baseline_message_sequence=2,
            trigger_message_sequence=3,
        )
        monitor = RunCompletionMonitor(
            has_active_worker=lambda _sid: False,
            has_pending_reentry=lambda _sid: False,
            get_graph_snapshot=lambda _sid: None,
            run_repo=runs,
            message_repo=messages,
        )

        result = monitor.evaluate_run(run.run_id)

    assert result is not None
    assert result["status"] == "succeeded"
    assert result["summary"] == "current summary"


def test_previous_run_graph_is_not_used_for_current_run() -> None:
    from src.business.agents.config import AgentType
    from src.business.scheduling.run_completion_monitor import RunCompletionMonitor
    from src.data.models_sqlite import Message, Session
    from src.data.repos.assistant_task_repository import AssistantTaskRepository
    from src.data.repos.message_repository import MessageRepository
    from src.data.repos.scheduled_task_run_repository import ScheduledTaskRunRepository
    from src.data.repos.session_repository import SessionRepository

    SessionRepository().create(
        Session(
            session_id="ast_graph_window",
            workflow_id=None,
            agent_type=AgentType.ASSISTANT,
            status="active",
        )
    )
    with AssistantTaskRepository() as tasks:
        tasks.create_task(
            graph_id="tg_previous",
            session_id="ast_graph_window",
            task_id="tsk_previous_root",
            title="old graph",
            description="old graph",
            user_message_sequence=1,
        )
    with MessageRepository() as messages:
        messages.create(
            Message(
                message_id="msg_graph_window_delegate",
                session_id="ast_graph_window",
                sequence=4,
                role="tool",
                tool_name="delegate_to_subagent",
                content='{"success": true}',
            )
        )
    with ScheduledTaskRunRepository() as runs, MessageRepository() as messages:
        run = runs.create(
            scheduled_task_id="sch_graph_window",
            session_id="ast_graph_window",
            baseline_message_sequence=2,
            trigger_message_sequence=3,
        )
        monitor = RunCompletionMonitor(
            has_active_worker=lambda _sid: False,
            has_pending_reentry=lambda _sid: False,
            run_repo=runs,
            message_repo=messages,
        )

        result = monitor.evaluate_run(run.run_id)

    assert result is not None
    assert result["status"] == "succeeded"


def test_unscoped_graph_created_during_run_defers_completion_fail_closed() -> None:
    from src.business.agents.config import AgentType
    from src.business.scheduling.run_completion_monitor import RunCompletionMonitor
    from src.data.models_sqlite import Message, Session
    from src.data.repos.assistant_task_repository import AssistantTaskRepository
    from src.data.repos.message_repository import MessageRepository
    from src.data.repos.scheduled_task_run_repository import ScheduledTaskRunRepository
    from src.data.repos.session_repository import SessionRepository

    SessionRepository().create(
        Session(
            session_id="ast_unscoped_graph",
            workflow_id=None,
            agent_type=AgentType.ASSISTANT,
            status="active",
        )
    )
    with ScheduledTaskRunRepository() as runs:
        run = runs.create(
            scheduled_task_id="sch_unscoped_graph",
            session_id="ast_unscoped_graph",
            baseline_message_sequence=0,
            trigger_message_sequence=1,
        )
    with AssistantTaskRepository() as tasks:
        tasks.create_task(
            graph_id="tg_unscoped",
            session_id="ast_unscoped_graph",
            task_id="tsk_unscoped_root",
            title="unknown graph",
            description="unknown graph",
            user_message_sequence=None,
        )
    with MessageRepository() as messages:
        messages.create(
            Message(
                message_id="msg_unscoped_delegate",
                session_id="ast_unscoped_graph",
                sequence=2,
                role="tool",
                tool_name="delegate_to_subagent",
                content='{"success": true}',
            )
        )
    with ScheduledTaskRunRepository() as runs, MessageRepository() as messages:
        monitor = RunCompletionMonitor(
            has_active_worker=lambda _sid: False,
            has_pending_reentry=lambda _sid: False,
            run_repo=runs,
            message_repo=messages,
        )

        result = monitor.evaluate_run(run.run_id)

        assert result is None
        assert runs.get_fresh(run.run_id).status == "running"


def test_graph_event_maps_to_run_by_graph_message_sequence() -> None:
    from src.business.scheduling.run_completion_monitor import RunCompletionMonitor
    from src.data.repos.assistant_task_repository import AssistantTaskRepository
    from src.data.repos.scheduled_task_run_repository import ScheduledTaskRunRepository

    with ScheduledTaskRunRepository() as runs:
        previous = runs.create(
            scheduled_task_id="sch_graph_owner",
            session_id="ast_graph_owner",
            baseline_message_sequence=0,
            trigger_message_sequence=1,
        )
        runs.cas_transition(previous.run_id, from_status="running", to_status="succeeded")
        current = runs.create(
            scheduled_task_id="sch_graph_owner",
            session_id="ast_graph_owner",
            baseline_message_sequence=5,
            trigger_message_sequence=6,
        )
    with AssistantTaskRepository() as tasks:
        tasks.create_task(
            graph_id="tg_current_owner",
            session_id="ast_graph_owner",
            task_id="tsk_current_owner_root",
            title="current",
            description="current",
            user_message_sequence=6,
        )
    monitor = RunCompletionMonitor()

    assert (
        monitor.resolve_run_id_for_graph(
            session_id="ast_graph_owner",
            graph_id="tg_current_owner",
        )
        == current.run_id
    )


def test_evaluate_reads_graph_snapshot_only_once() -> None:
    """同一次静默落账必须复用图状态，不能在判静默后再次读取权威快照。"""
    from src.business.scheduling.run_completion_monitor import RunCompletionMonitor
    from src.data.repos.scheduled_task_run_repository import ScheduledTaskRunRepository

    snapshot_reads: list[str] = []
    snapshot = SimpleNamespace(tasks=[_root(), _executor("t1", "completed")])

    def get_snapshot(session_id: str):
        snapshot_reads.append(session_id)
        return snapshot

    with ScheduledTaskRunRepository() as rr:
        _seed_run(rr, session_id="ast_single_snapshot")
        monitor = RunCompletionMonitor(
            has_active_worker=lambda _sid: False,
            has_pending_reentry=lambda _sid: False,
            get_graph_snapshot=get_snapshot,
            run_repo=rr,
        )

        result = monitor.evaluate_session("ast_single_snapshot")

    assert result is not None
    assert result["status"] == "succeeded"
    assert snapshot_reads == ["ast_single_snapshot"]


def test_evaluate_defers_when_pending_reentry():
    """回流续跑轮：有 pending 回流 → 不置终态（等 drain briefing 续跑）。"""
    from src.data.repos.scheduled_task_run_repository import (
        ScheduledTaskRunRepository,
    )

    with ScheduledTaskRunRepository() as rr:
        _seed_run(rr, session_id="ast_reentry")
        monitor = _make_monitor(
            has_active_worker=lambda sid: False,
            has_pending_reentry=lambda sid: True,  # 有 pending 回流
            snapshot_tasks=[_root(), _executor("t1", "completed")],
            run_repo=rr,
        )
        result = monitor.evaluate_session("ast_reentry")
        assert result is None
        assert rr.get_by_session("ast_reentry").status == "running"


def test_evaluate_skips_already_terminal_run():
    """已终态 run 不再推进（幂等）。"""
    from src.data.repos.scheduled_task_run_repository import (
        ScheduledTaskRunRepository,
    )

    with ScheduledTaskRunRepository() as rr:
        run = _seed_run(rr, session_id="ast_done")
        rr.cas_transition(run.run_id, from_status="running", to_status="succeeded", summary="ok")
        monitor = _make_monitor(
            has_active_worker=lambda sid: False,
            has_pending_reentry=lambda sid: False,
            snapshot_tasks=[_root(), _executor("t1", "completed")],
            run_repo=rr,
        )
        result = monitor.evaluate_session("ast_done")
        assert result is None


def test_terminal_event_failure_remains_pending_and_next_evaluation_retries(
    monkeypatch,
):
    """业务终态已提交但 emit 失败时，后续评估必须补投且确认后不重复。"""
    from src.business.scheduling.run_completion_monitor import RunCompletionMonitor
    from src.data.repos.scheduled_task_run_repository import ScheduledTaskRunRepository
    from src.utils import events

    attempts = 0
    delivered: list[dict] = []

    def fail_once(event_name, _sender, **payload):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("projector temporarily unavailable")
        delivered.append({"event_name": event_name, **payload})

    monkeypatch.setattr(events, "emit", fail_once)

    with ScheduledTaskRunRepository() as rr:
        _seed_run(rr, session_id="ast_retry_terminal")
        monitor = RunCompletionMonitor(
            has_active_worker=lambda _sid: False,
            has_pending_reentry=lambda _sid: False,
            get_graph_snapshot=lambda _sid: SimpleNamespace(
                tasks=[_root(), _executor("t1", "completed")]
            ),
            run_repo=rr,
        )

        first = monitor.evaluate_session("ast_retry_terminal")
        pending = rr.get_fresh(first["runId"])
        assert first["status"] == "succeeded"
        assert pending.terminal_event_delivered_at is None

        assert monitor.evaluate_session("ast_retry_terminal") is None
        acknowledged = rr.get_fresh(first["runId"])
        assert acknowledged.terminal_event_delivered_at is not None

        assert monitor.evaluate_session("ast_retry_terminal") is None

    assert attempts == 2
    assert [item["status"] for item in delivered] == ["succeeded"]


def test_waiting_user_takeover_resets_delivery_ack_for_next_terminal_event(
    monkeypatch,
):
    """waiting_user 通知已确认后，接管续跑必须为下一终态开启新的投影周期。"""
    from src.business.scheduling.run_completion_monitor import RunCompletionMonitor
    from src.data.repos.scheduled_task_run_repository import ScheduledTaskRunRepository
    from src.utils import events

    emitted: list[str] = []
    monkeypatch.setattr(
        events,
        "emit",
        lambda _event_name, _sender, **payload: emitted.append(payload["status"]),
    )

    with ScheduledTaskRunRepository() as rr:
        run = _seed_run(rr, session_id="ast_delivery_cycle")
        monitor = RunCompletionMonitor(run_repo=rr)

        monitor.mark_waiting_user(run.run_id)
        waiting = rr.get_fresh(run.run_id)
        assert waiting.terminal_event_delivered_at is not None
        assert waiting.terminal_event_version == 1

        resumed = rr.cas_transition(
            run.run_id,
            from_status="waiting_user",
            to_status="running",
        )
        assert resumed.terminal_event_delivered_at is None
        assert resumed.terminal_event_version == 1
        finished = rr.cas_transition(
            run.run_id,
            from_status="running",
            to_status="failed",
            failure_reason="safe failure",
        )
        assert finished.terminal_event_delivered_at is None
        assert finished.terminal_event_version == 2

        assert monitor.retry_pending_terminal_events() == 1
        assert rr.get_fresh(run.run_id).terminal_event_delivered_at is not None

    assert emitted == ["waiting_user", "failed"]


def test_stale_terminal_ack_cannot_swallow_newer_terminal_generation(monkeypatch):
    """emit 与 ack 之间状态变化时，旧代次不得确认掉新的终态通知。"""
    from src.business.scheduling.terminal_event_delivery import deliver_terminal_event
    from src.data.repos.scheduled_task_run_repository import ScheduledTaskRunRepository
    from src.utils import events

    emitted: list[str] = []

    with ScheduledTaskRunRepository() as rr:
        run = _seed_run(rr, session_id="ast_generation_race")
        waiting = rr.cas_transition(
            run.run_id,
            from_status="running",
            to_status="waiting_user",
        )
        assert waiting.terminal_event_version == 1

        def transition_during_first_emit(_event_name, _sender, **payload):
            emitted.append(payload["status"])
            if payload["status"] != "waiting_user":
                return
            resumed = rr.cas_transition(
                run.run_id,
                from_status="waiting_user",
                to_status="running",
            )
            assert resumed is not None
            finished = rr.cas_transition(
                run.run_id,
                from_status="running",
                to_status="failed",
                failure_reason="safe failure",
            )
            assert finished is not None

        monkeypatch.setattr(events, "emit", transition_during_first_emit)

        assert deliver_terminal_event(run.run_id, run_repo=rr) is False
        pending = rr.get_fresh(run.run_id)
        assert pending.status == "failed"
        assert pending.terminal_event_version == 2
        assert pending.terminal_event_delivered_at is None

        assert deliver_terminal_event(run.run_id, run_repo=rr) is True
        acknowledged = rr.get_fresh(run.run_id)
        assert acknowledged.terminal_event_version == 2
        assert acknowledged.terminal_event_delivered_at is not None

    assert emitted == ["waiting_user", "failed"]


def test_evaluate_marks_succeeded_after_takeover_round():
    """条件 3：waiting_user 接管回 running 后，下一轮静默才置 succeeded（后置终态）。"""
    from src.data.repos.scheduled_task_run_repository import (
        ScheduledTaskRunRepository,
    )

    with ScheduledTaskRunRepository() as rr:
        run = _seed_run(rr, session_id="ast_takeover")
        # 落 waiting_user（反问）
        rr.cas_transition(run.run_id, from_status="running", to_status="waiting_user")
        monitor_for_waiting = _make_monitor(
            has_active_worker=lambda sid: False,
            has_pending_reentry=lambda sid: False,
            snapshot_tasks=[_root(), _executor("t1", "in_progress")],
            run_repo=rr,
        )
        # waiting_user 状态：evaluate 不覆盖（emit needs_takeover 由 projector 处理）
        assert monitor_for_waiting.evaluate_session("ast_takeover") is None
        # 接管 → 回 running
        rr.cas_transition(run.run_id, from_status="waiting_user", to_status="running")
        # 续跑轮：图仍 in_progress → 不置终态
        monitor_inprogress = _make_monitor(
            has_active_worker=lambda sid: False,
            has_pending_reentry=lambda sid: False,
            snapshot_tasks=[_root(), _executor("t1", "in_progress")],
            run_repo=rr,
        )
        assert monitor_inprogress.evaluate_session("ast_takeover") is None
        # 下一轮：图全 completed + 静默 → succeeded
        monitor_final = _make_monitor(
            has_active_worker=lambda sid: False,
            has_pending_reentry=lambda sid: False,
            snapshot_tasks=[_root(), _executor("t1", "completed")],
            run_repo=rr,
        )
        result = monitor_final.evaluate_session("ast_takeover")
        assert result is not None
        assert result["status"] == "succeeded"


def test_evaluate_fails_closed_when_pending_reentry_callback_is_missing():
    """缺失 pending-reentry 权威查询时，不能把未知状态当作静默成功。"""
    from src.business.scheduling.run_completion_monitor import RunCompletionMonitor
    from src.data.repos.scheduled_task_run_repository import ScheduledTaskRunRepository

    with ScheduledTaskRunRepository() as rr:
        _seed_run(rr, session_id="ast_pending_unknown")
        monitor = RunCompletionMonitor(
            has_active_worker=lambda _sid: False,
            get_graph_snapshot=lambda _sid: None,
            run_repo=rr,
        )

        assert monitor.evaluate_session("ast_pending_unknown") is None
        assert rr.get_by_session("ast_pending_unknown").status == "running"


def test_evaluate_checks_pending_reentry_for_the_current_graph_only() -> None:
    from src.business.scheduling.run_completion_monitor import RunCompletionMonitor
    from src.data.repos.scheduled_task_run_repository import ScheduledTaskRunRepository

    pending_queries: list[tuple[str, str | None]] = []
    snapshot = SimpleNamespace(
        graph_id="tg_current_pending_scope",
        tasks=[_root(), _executor("t1", "completed")],
    )

    def has_pending(session_id: str, graph_id: str | None = None) -> bool:
        pending_queries.append((session_id, graph_id))
        return graph_id == "tg_old_pending_scope"

    with ScheduledTaskRunRepository() as rr:
        run = _seed_run(rr, session_id="ast_pending_scope")
        monitor = RunCompletionMonitor(
            has_active_worker=lambda _sid: False,
            has_pending_reentry=has_pending,
            get_graph_snapshot=lambda _sid: snapshot,
            run_repo=rr,
        )

        result = monitor.evaluate_run(run.run_id)

        assert result is not None and result["status"] == "succeeded"
        assert pending_queries == [("ast_pending_scope", "tg_current_pending_scope")]


def test_evaluate_fails_closed_when_graph_snapshot_query_raises():
    """图查询异常与权威“无图”不同：未知时不得误报简单会话成功。"""
    from src.business.scheduling.run_completion_monitor import RunCompletionMonitor
    from src.data.repos.scheduled_task_run_repository import ScheduledTaskRunRepository

    def _raise(_session_id):
        raise RuntimeError("graph database unavailable")

    with ScheduledTaskRunRepository() as rr:
        _seed_run(rr, session_id="ast_graph_unknown")
        monitor = RunCompletionMonitor(
            has_active_worker=lambda _sid: False,
            has_pending_reentry=lambda _sid: False,
            get_graph_snapshot=_raise,
            run_repo=rr,
        )

        assert monitor.evaluate_session("ast_graph_unknown") is None
        assert rr.get_by_session("ast_graph_unknown").status == "running"


def test_mark_waiting_user_is_atomic_and_emits_once(monkeypatch):
    from src.business.scheduling.run_completion_monitor import RunCompletionMonitor
    from src.data.repos.scheduled_task_run_repository import ScheduledTaskRunRepository
    from src.utils import events

    emitted: list[dict] = []
    monkeypatch.setattr(
        events,
        "emit",
        lambda event_name, _sender, **payload: emitted.append(
            {"event_name": event_name, **payload}
        ),
    )

    with ScheduledTaskRunRepository() as rr:
        run = _seed_run(rr, session_id="ast_needs_user")
        monitor = RunCompletionMonitor(run_repo=rr)

        result = monitor.mark_waiting_user(run.run_id)
        duplicate = monitor.mark_waiting_user(run.run_id)

        assert result is not None
        assert result["status"] == "waiting_user"
        assert duplicate is None
        assert rr.get_by_session("ast_needs_user").status == "waiting_user"
        assert [item["status"] for item in emitted] == ["waiting_user"]


def test_mark_waiting_user_targets_run_id_not_latest_run_by_session() -> None:
    from src.business.scheduling.run_completion_monitor import RunCompletionMonitor
    from src.data.repos.scheduled_task_run_repository import ScheduledTaskRunRepository

    with ScheduledTaskRunRepository() as runs:
        previous = runs.create(
            scheduled_task_id="sch_run_owned",
            session_id="ast_run_owned",
            baseline_message_sequence=0,
            trigger_message_sequence=1,
        )
        runs.cas_transition(previous.run_id, from_status="running", to_status="succeeded")
        current = runs.create(
            scheduled_task_id="sch_run_owned",
            session_id="ast_run_owned",
            baseline_message_sequence=2,
            trigger_message_sequence=3,
        )
        monitor = RunCompletionMonitor(run_repo=runs)

        result = monitor.mark_waiting_user(current.run_id)

        assert result is not None
        assert result["runId"] == current.run_id
        assert runs.get_fresh(current.run_id).status == "waiting_user"
        assert runs.get_fresh(previous.run_id).status == "succeeded"


def test_mark_failed_can_finish_waiting_user_run():
    from src.business.scheduling.run_completion_monitor import RunCompletionMonitor
    from src.data.repos.scheduled_task_run_repository import ScheduledTaskRunRepository

    with ScheduledTaskRunRepository() as rr:
        run = _seed_run(rr, session_id="ast_waiting_then_stopped")
        rr.cas_transition(run.run_id, from_status="running", to_status="waiting_user")
        monitor = RunCompletionMonitor(run_repo=rr)

        result = monitor.mark_failed(run.run_id)

        assert result is not None
        assert result["status"] == "failed"
        row = rr.get_by_session("ast_waiting_then_stopped")
        assert row.status == "failed"
        assert row.finished_at is not None


def test_mark_failed_releases_trigger_slot_when_user_message_never_persisted() -> None:
    from src.business.scheduling.run_completion_monitor import RunCompletionMonitor
    from src.data.repos.message_repository import MessageRepository
    from src.data.repos.scheduled_task_run_repository import ScheduledTaskRunRepository

    with ScheduledTaskRunRepository() as runs, MessageRepository() as messages:
        run = runs.create(
            scheduled_task_id="sch_pre_message_failure",
            session_id="ast_pre_message_failure",
            baseline_message_sequence=0,
            trigger_message_sequence=1,
        )
        monitor = RunCompletionMonitor(run_repo=runs, message_repo=messages)

        monitor.mark_failed(run.run_id)
        failed = runs.get_fresh(run.run_id)
        retry = runs.create(
            scheduled_task_id="sch_pre_message_failure",
            session_id="ast_pre_message_failure",
            baseline_message_sequence=0,
            trigger_message_sequence=1,
        )

        assert failed.trigger_message_sequence is None
        assert retry.status == "running"


def test_quiescent_failure_releases_trigger_slot_when_user_message_never_persisted() -> None:
    from src.business.scheduling.run_completion_monitor import RunCompletionMonitor
    from src.data.repos.message_repository import MessageRepository
    from src.data.repos.scheduled_task_run_repository import ScheduledTaskRunRepository

    with ScheduledTaskRunRepository() as runs, MessageRepository() as messages:
        run = runs.create(
            scheduled_task_id="sch_quiescent_pre_message_failure",
            session_id="ast_quiescent_pre_message_failure",
            baseline_message_sequence=0,
            trigger_message_sequence=1,
        )
        monitor = RunCompletionMonitor(
            has_active_worker=lambda _sid: False,
            has_pending_reentry=lambda _sid: False,
            get_graph_snapshot=lambda _sid: None,
            run_repo=runs,
            message_repo=messages,
        )

        result = monitor.evaluate_run(run.run_id)
        failed = runs.get_fresh(run.run_id)
        retry = runs.create(
            scheduled_task_id="sch_quiescent_pre_message_failure",
            session_id="ast_quiescent_pre_message_failure",
            baseline_message_sequence=0,
            trigger_message_sequence=1,
        )

        assert result is not None and result["status"] == "failed"
        assert failed.trigger_message_sequence is None
        assert retry.status == "running"


def test_mark_failed_keeps_missing_trigger_slot_when_a_graph_claims_it() -> None:
    from src.business.scheduling.run_completion_monitor import RunCompletionMonitor
    from src.data.repos.assistant_task_repository import AssistantTaskRepository
    from src.data.repos.message_repository import MessageRepository
    from src.data.repos.scheduled_task_run_repository import ScheduledTaskRunRepository

    with ScheduledTaskRunRepository() as runs, MessageRepository() as messages:
        run = runs.create(
            scheduled_task_id="sch_missing_message_with_graph",
            session_id="ast_missing_message_with_graph",
            baseline_message_sequence=0,
            trigger_message_sequence=1,
        )
        with AssistantTaskRepository() as tasks:
            tasks.create_task(
                graph_id="tg_missing_message_with_graph",
                session_id=run.session_id,
                task_id="tsk_missing_message_with_graph_root",
                title="graph root",
                description="graph root",
                user_message_sequence=1,
            )
        monitor = RunCompletionMonitor(run_repo=runs, message_repo=messages)

        monitor.mark_failed(run.run_id)

        assert runs.get_fresh(run.run_id).trigger_message_sequence == 1


def test_mark_failed_keeps_trigger_slot_when_user_message_exists() -> None:
    from src.business.scheduling.run_completion_monitor import RunCompletionMonitor
    from src.data.models_sqlite import Message
    from src.data.repos.message_repository import MessageRepository
    from src.data.repos.scheduled_task_run_repository import ScheduledTaskRunRepository

    with ScheduledTaskRunRepository() as runs, MessageRepository() as messages:
        run = runs.create(
            scheduled_task_id="sch_post_message_failure",
            session_id="ast_post_message_failure",
            baseline_message_sequence=0,
            trigger_message_sequence=1,
        )
        messages.create(
            Message(
                message_id="msg_post_message_failure",
                session_id=run.session_id,
                sequence=1,
                role="user",
                content="scheduled trigger",
            )
        )
        monitor = RunCompletionMonitor(run_repo=runs, message_repo=messages)

        monitor.mark_failed(run.run_id)

        assert runs.get_fresh(run.run_id).trigger_message_sequence == 1
