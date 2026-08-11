"""Scheduled run 收尾判定的行为契约。

回归的是一条真实生产链路：定时任务跑完、主助理用 ``reply_to_user`` 汇报结果，
这一轮却被记成 ``waiting_user``——运行记录永远不结束，占住 per-task active 槽位，
后续每一轮到点都被 ``has_active_run`` 判定为 reentry 而静默 skipped。

两个叠加缺陷各由一组用例守：

1. **收尾方式不分来源**：``reply_to_user``（汇报）与 ``ask_user_question``（提问）
   都让 AgentLoop 返回 ``NEEDS_USER_INPUT``，runtime 不看 ``signal_tool`` 就一律
   落 ``waiting_user``。汇报必须走完成判定，提问才等接管。
2. **追踪记录被误认成任务图**：simple 委派同步路径有意不建图，但会建一条
   ``parent_task_id is None`` 的 task 行做执行追踪。它不带 ``user_message_sequence``，
   于是 ``resolve_graph_id_for_run`` 把它当成"身份不明的图"并 fail-closed，
   判定永远走不到图终态那一步。

定时任务多是简单重复活，主助理会稳定判 simple 走同步路径，所以两个缺陷对
scheduled 会话是必然而非偶发。
"""

from __future__ import annotations

import queue
from types import SimpleNamespace

import pytest

from src.business.agents.config import AgentResult, AgentType, ResultType
from src.data.models_sqlite import Message, Session
from src.data.repos import MessageRepository, SessionRepository
from src.data.repos.assistant_task_repository import AssistantTaskRepository
from src.data.repos.scheduled_task_run_repository import ScheduledTaskRunRepository
from src.desktop_api.assistant_runtime import AssistantRuntime
from src.desktop_api.events import event_queue

SESSION_ID = "ast_sched_done"
TASK_ID = "sch_done"
# run 水位线：Repository 约束 trigger == baseline + 1，launch 时按空会话预留。
BASELINE_SEQUENCE = 0
TRIGGER_SEQUENCE = 1
# 实际落库位置：首轮 AgentLoop 先写 system prompt 占 1，调度指令顺延到 2。
# 预留水位线与真实位置的这处错位是生产现状，图的归属编号取的是真实位置。
USER_MESSAGE_SEQUENCE = 2


class _ResultOrchestrator:
    """返回预设 AgentResult 的编排器（不触发任何模型调用）。"""

    task_worker = SimpleNamespace(start=lambda: None)

    def __init__(self, result: AgentResult) -> None:
        self._result = result

    def set_parent_reentry_callback(self, callback) -> None:
        self.parent_reentry_callback = callback

    def run_agent(self, *_args, **_kwargs) -> AgentResult:
        return self._result


class _FakeChatService:
    def get_latest_display_sequence(self, session_id: str) -> int:
        return 0

    def get_display_messages_after(self, session_id: str, after_sequence: int) -> list:
        return []


def _drain_events() -> None:
    while True:
        try:
            event_queue.queue.get_nowait()
        except queue.Empty:
            return


def _signal(tool_name: str) -> AgentResult:
    """构造"中断型工具收尾"的 AgentResult，与 AgentLoop._handle_tool_result 同构。"""
    return AgentResult(
        result_type=ResultType.NEEDS_USER_INPUT,
        question="榜单已整理完毕",
        signal_tool=SimpleNamespace(name=tool_name, args={}, display_text="榜单已整理完毕"),
    )


@pytest.fixture
def scheduled_run():
    """一条 running 的 scheduled run + 已收尾的同步委派追踪记录。

    追踪记录带 ``user_message_sequence``——这是修复后 ``_start_sync_attempt``
    应有的行为，由 ``test_sync_delegation_row_carries_user_message_sequence`` 单独守。
    """
    SessionRepository().create(
        Session(
            session_id=SESSION_ID,
            workflow_id=None,
            agent_type=AgentType.ASSISTANT,
            status="active",
        )
    )
    with MessageRepository() as messages:
        messages.create(
            Message(
                message_id="msg_sched_sys",
                session_id=SESSION_ID,
                sequence=1,
                role="system",
                content="system prompt",
            )
        )
        messages.create(
            Message(
                message_id="msg_sched_trigger",
                session_id=SESSION_ID,
                sequence=USER_MESSAGE_SEQUENCE,
                role="user",
                content="[系统调度触发：立即执行]",
            )
        )
    with ScheduledTaskRunRepository() as runs:
        run = runs.create(
            scheduled_task_id=TASK_ID,
            session_id=SESSION_ID,
            baseline_message_sequence=BASELINE_SEQUENCE,
            trigger_message_sequence=TRIGGER_SEQUENCE,
        )
    with AssistantTaskRepository() as tasks:
        tasks.create_task(
            graph_id="tg_sync_track",
            session_id=SESSION_ID,
            task_id="tsk_sync_track",
            root_task_id="tsk_sync_track",
            parent_task_id=None,
            title="查询 GitHub Trending 榜单",
            description="查询 GitHub Trending 榜单",
            owner_session_id=SESSION_ID,
            assignee_type=AgentType.EPHEMERAL_SUBAGENT.value,
            assignee_id=AgentType.EPHEMERAL_SUBAGENT.value,
            user_message_sequence=USER_MESSAGE_SEQUENCE,
            status="done",
        )
    return run


@pytest.fixture
def installed_monitor():
    """安装 monitor 单例并注入静默 callback（业务层不 import desktop runtime）。"""
    from src.business.scheduling.run_completion_monitor import (
        install_run_completion_monitor,
        shutdown_run_completion_monitor,
    )

    install_run_completion_monitor(
        has_active_worker=lambda _sid: False,
        has_pending_reentry=lambda *_args: False,
    )
    yield
    shutdown_run_completion_monitor()


def _run_once(result: AgentResult, run_id: str) -> None:
    runtime = AssistantRuntime(
        orchestrator_factory=lambda: _ResultOrchestrator(result),
        chat_service=_FakeChatService(),
    )
    runtime._run_assistant(SESSION_ID, "指令", 0, scheduled_run_id=run_id)


def test_scheduled_run_succeeds_when_assistant_reports_result(
    scheduled_run, installed_monitor
) -> None:
    """主助理用 reply_to_user 汇报结果 = 这轮跑完了，不是在等用户回话。

    修复前：runtime 只看 NEEDS_USER_INPUT 就落 waiting_user，run 永不结束。
    """
    _drain_events()

    _run_once(_signal("reply_to_user"), scheduled_run.run_id)

    with ScheduledTaskRunRepository() as runs:
        row = runs.get_fresh(scheduled_run.run_id)
    assert row.status == "succeeded"
    assert row.finished_at is not None


def test_scheduled_run_waits_for_user_when_assistant_asks_question(
    scheduled_run, installed_monitor
) -> None:
    """真的提问仍然要等接管——修复不能把需要人介入的轮次一并吞成成功。"""
    _drain_events()

    _run_once(_signal("ask_user_question"), scheduled_run.run_id)

    with ScheduledTaskRunRepository() as runs:
        row = runs.get_fresh(scheduled_run.run_id)
    assert row.status == "waiting_user"


def test_scheduled_run_stays_running_while_delegated_work_is_pending(
    scheduled_run,
) -> None:
    """异步派活未回流时不得判成功：主助理歇了不等于活干完了。"""
    from src.business.scheduling.run_completion_monitor import (
        install_run_completion_monitor,
        shutdown_run_completion_monitor,
    )

    install_run_completion_monitor(
        has_active_worker=lambda _sid: False,
        has_pending_reentry=lambda *_args: True,
    )
    try:
        _drain_events()
        _run_once(_signal("reply_to_user"), scheduled_run.run_id)
        with ScheduledTaskRunRepository() as runs:
            row = runs.get_fresh(scheduled_run.run_id)
        assert row.status == "running"
    finally:
        shutdown_run_completion_monitor()


def test_sync_delegation_row_carries_user_message_sequence() -> None:
    """simple 同步委派的追踪记录必须带归属编号。

    不带编号时 ``resolve_graph_id_for_run`` 会把它当成"身份不明的图"并 fail-closed，
    完成判定永远走不到图终态那一步。
    """
    from src.business.orchestration.agent.delegation_orchestrator import _start_sync_attempt

    sid = "ast_sync_seq"
    SessionRepository().create(
        Session(session_id=sid, workflow_id=None, agent_type=AgentType.ASSISTANT, status="active")
    )
    with MessageRepository() as messages:
        messages.create(
            Message(
                message_id="msg_sync_sys",
                session_id=sid,
                sequence=1,
                role="system",
                content="system prompt",
            )
        )
        messages.create(
            Message(
                message_id="msg_sync_user",
                session_id=sid,
                sequence=2,
                role="user",
                content="帮我查个榜单",
            )
        )

    task_id = _start_sync_attempt(
        parent_session_id=sid,
        task_title="查榜单",
        task_description="查榜单",
        executor_type=AgentType.EPHEMERAL_SUBAGENT.value,
        executor_id=AgentType.EPHEMERAL_SUBAGENT.value,
        user_task_id=None,
    )

    assert task_id is not None
    with AssistantTaskRepository() as tasks:
        row = tasks.get_task(task_id)
    assert row.user_message_sequence == 2
