"""SessionLauncher 投递失败必须显式终结 run，不能静默悬挂。"""

from __future__ import annotations

import threading
import uuid

import pytest

import src.data.sqlalchemy_manager as sm_module
from src.business.agents.config import AgentType
from src.business.scheduling.session_launcher import (
    ScheduledRunAlreadyActive,
    SessionLauncher,
)
from src.data.models_sqlite import Session
from src.data.models_sqlite import Message
from src.data.repos.message_repository import MessageRepository
from src.data.repos.scheduled_task_repository import ScheduledTaskRepository
from src.data.repos.scheduled_task_run_repository import ScheduledTaskRunRepository
from src.data.repos.session_repository import SessionRepository
from src.data.sqlalchemy_manager import SQLAlchemyManager


class _ChatService:
    @staticmethod
    def generate_session_id():
        return "ast_dispatch_test"

    def build_scheduled_session(self, scheduled_task_id, **kwargs):
        return Session(
            session_id=kwargs["session_id"],
            workflow_id=None,
            agent_type=AgentType.ASSISTANT,
            status="active",
            title=kwargs.get("title"),
            source="scheduled",
            scheduled_task_id=scheduled_task_id,
            is_scheduled=1,
        )


class _FailingChatService(_ChatService):
    def build_scheduled_session(self, _scheduled_task_id, **_kwargs):
        raise RuntimeError("database unavailable")


def _create_task() -> str:
    with ScheduledTaskRepository() as repo:
        row = repo.create(
            source_type="direct",
            source_ref="执行任务",
            title="复用测试",
            instruction="执行任务",
            schedule_kind="recurring",
            schedule_payload={"interval_seconds": 60},
        )
        return row.scheduled_task_id


def test_false_dispatch_marks_run_failed():
    task_id = _create_task()
    with ScheduledTaskRunRepository() as run_repo:
        launcher = SessionLauncher(
            dispatch_callback=lambda *_args: False,
            run_repo=run_repo,
            chat_service=_ChatService(),
        )

        run_id = launcher.launch(
            scheduled_task_id=task_id,
            instruction="执行任务",
        )

        run = run_repo.get(run_id)
        assert run.status == "failed"
        assert run.finished_at is not None
        assert run.failure_reason == "scheduled session could not be started"


def test_dispatch_failure_without_message_does_not_brick_reused_session() -> None:
    task_id = _create_task()
    attempts = 0

    def dispatch(*_args):
        nonlocal attempts
        attempts += 1
        return attempts > 1

    with ScheduledTaskRunRepository() as run_repo:
        launcher = SessionLauncher(
            dispatch_callback=dispatch,
            run_repo=run_repo,
            chat_service=_ChatService(),
        )

        first_id = launcher.launch(
            scheduled_task_id=task_id,
            instruction="第一次启动失败",
        )
        second_id = launcher.launch(
            scheduled_task_id=task_id,
            instruction="重试同一会话",
        )

        first = run_repo.get_fresh(first_id)
        second = run_repo.get_fresh(second_id)

    assert first.status == "failed"
    assert first.trigger_message_sequence is None
    assert second.status == "running"
    assert second.session_id == first.session_id == "ast_dispatch_test"
    assert second.trigger_message_sequence == 1


def test_later_launch_reuses_the_task_current_session() -> None:
    task_id = _create_task()
    generated: list[str] = []
    dispatched: list[tuple[str, str]] = []

    class _RotatingChatService(_ChatService):
        @staticmethod
        def generate_session_id():
            session_id = f"ast_reuse_{len(generated) + 1}"
            generated.append(session_id)
            return session_id

    def dispatch(session_id, _message, run_id, _reservation_id):
        dispatched.append((session_id, run_id))
        with ScheduledTaskRunRepository() as runs:
            run = runs.get(run_id)
        MessageRepository().create(
            Message(
                message_id=f"msg_{uuid.uuid4().hex[:12]}",
                session_id=session_id,
                sequence=run.trigger_message_sequence,
                role="user",
                content="scheduled trigger",
            )
        )
        return True

    with ScheduledTaskRunRepository() as run_repo:
        launcher = SessionLauncher(
            dispatch_callback=dispatch,
            run_repo=run_repo,
            chat_service=_RotatingChatService(),
        )
        first_id = launcher.launch(
            scheduled_task_id=task_id,
            instruction="执行任务",
        )
        run_repo.cas_transition(first_id, from_status="running", to_status="succeeded")
        # AgentLoop 正常结束会把长生命周期 assistant session 标成 completed；
        # 下一次 scheduled run 必须复活并复用它，而不是把绑定判成损坏。
        SessionRepository().update_status("ast_reuse_1", "completed")
        second_id = launcher.launch(
            scheduled_task_id=task_id,
            instruction="再次执行",
        )

        first = run_repo.get(first_id)
        second = run_repo.get(second_id)

    assert generated == ["ast_reuse_1"]
    assert first.session_id == second.session_id == "ast_reuse_1"
    assert first.trigger_message_sequence == 1
    assert second.baseline_message_sequence == 1
    assert second.trigger_message_sequence == 2
    assert SessionRepository().get_by_id("ast_reuse_1").status == "active"
    assert [session_id for session_id, _ in dispatched] == [
        "ast_reuse_1",
        "ast_reuse_1",
    ]


def test_busy_session_is_rejected_before_run_or_binding_is_created() -> None:
    task_id = _create_task()
    launcher = SessionLauncher(
        dispatch_callback=lambda *_args: True,
        chat_service=_ChatService(),
        reserve_callback=lambda _session_id, _reservation_id: False,
        release_callback=lambda _session_id, _reservation_id: None,
    )

    with pytest.raises(ScheduledRunAlreadyActive):
        launcher.launch(
            scheduled_task_id=task_id,
            instruction="执行任务",
        )

    with ScheduledTaskRepository() as tasks:
        assert tasks.get(task_id).session_id is None
    with ScheduledTaskRunRepository() as runs:
        assert runs.list_by_task(task_id)[1] == 0
    with SessionRepository() as sessions:
        assert sessions.get_by_id("ast_dispatch_test") is None


def test_reused_session_waterline_is_read_after_runtime_reservation() -> None:
    task_id = _create_task()
    session_id = "ast_waterline_after_reservation"
    SessionRepository().create(
        Session(
            session_id=session_id,
            workflow_id=None,
            agent_type=AgentType.ASSISTANT,
            status="active",
            source="scheduled",
            scheduled_task_id=task_id,
            is_scheduled=1,
        )
    )
    with ScheduledTaskRepository() as tasks:
        tasks.cas_bind_session(task_id, session_id, expected_session_id=None)

    def reserve(_session_id: str, _reservation_id: str) -> bool:
        # Represents a previous worker's last durable message becoming visible
        # immediately before the reservation is granted.
        MessageRepository().create(
            Message(
                message_id="msg_before_reservation_grant",
                session_id=session_id,
                sequence=1,
                role="assistant",
                content="previous run finished",
            )
        )
        return True

    with ScheduledTaskRunRepository() as runs:
        launcher = SessionLauncher(
            dispatch_callback=lambda *_args: True,
            run_repo=runs,
            chat_service=_ChatService(),
            reserve_callback=reserve,
            release_callback=lambda *_args: None,
        )

        run_id = launcher.launch(
            scheduled_task_id=task_id,
            instruction="执行下一轮",
        )

        run = runs.get_fresh(run_id)
        assert run.baseline_message_sequence == 1
        assert run.trigger_message_sequence == 2


def test_dispatch_wraps_instruction_as_an_existing_schedule_execution():
    task_id = _create_task()
    dispatched: list[tuple[str, str]] = []
    instruction = "每天下午 3 点执行：整理 GitHub Trending，并把报告写入知识库。"

    with ScheduledTaskRunRepository() as run_repo:
        launcher = SessionLauncher(
            dispatch_callback=lambda session_id, message, _run_id, _reservation_id: (
                dispatched.append((session_id, message)) or True
            ),
            run_repo=run_repo,
            chat_service=_ChatService(),
        )

        launcher.launch(
            scheduled_task_id=task_id,
            instruction=instruction,
        )

    assert len(dispatched) == 1
    session_id, dispatched_message = dispatched[0]
    assert session_id == "ast_dispatch_test"
    assert dispatched_message != instruction
    assert dispatched_message.count(instruction) == 1
    assert "已存在定时任务的一次到点执行" in dispatched_message
    assert "立即执行" in dispatched_message
    assert "不得再次创建、修改、暂停或删除定时任务" in dispatched_message


def test_dispatch_exception_marks_run_failed():
    task_id = _create_task()

    def _raise(*_args):
        raise RuntimeError("provider unavailable")

    with ScheduledTaskRunRepository() as run_repo:
        launcher = SessionLauncher(
            dispatch_callback=_raise,
            run_repo=run_repo,
            chat_service=_ChatService(),
        )

        run_id = launcher.launch(
            scheduled_task_id=task_id,
            instruction="执行任务",
        )

        run = run_repo.get(run_id)
        assert run.status == "failed"
        assert "provider" not in (run.failure_reason or "")


def test_dispatch_failure_event_is_durable_and_retryable(monkeypatch):
    from src.business.scheduling.terminal_event_delivery import (
        retry_pending_terminal_events,
    )
    from src.utils import events

    attempts = 0

    def fail_once(*_args, **_kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("event queue unavailable")

    monkeypatch.setattr(events, "emit", fail_once)

    task_id = _create_task()
    with ScheduledTaskRunRepository() as run_repo:
        launcher = SessionLauncher(
            dispatch_callback=lambda *_args: False,
            run_repo=run_repo,
            chat_service=_ChatService(),
        )
        run_id = launcher.launch(
            scheduled_task_id=task_id,
            instruction="执行任务",
        )

        assert run_repo.get_fresh(run_id).terminal_event_delivered_at is None
        assert retry_pending_terminal_events(run_repo=run_repo) == 1
        assert run_repo.get_fresh(run_id).terminal_event_delivered_at is not None

    assert attempts == 2


def test_session_creation_failure_leaves_neither_run_nor_phantom_session():
    task_id = _create_task()
    with ScheduledTaskRunRepository() as run_repo:
        launcher = SessionLauncher(
            dispatch_callback=lambda *_args: True,
            run_repo=run_repo,
            chat_service=_FailingChatService(),
        )

        with pytest.raises(RuntimeError):
            launcher.launch(
                scheduled_task_id=task_id,
                instruction="执行任务",
            )

        runs, total = run_repo.list_by_task(task_id)
        assert runs == []
        assert total == 0
        assert SessionRepository().get_by_id("ast_dispatch_test") is None


def test_transient_failure_transition_is_retried_with_explicit_terminal_state(
    monkeypatch,
):
    task_id = _create_task()
    with ScheduledTaskRunRepository() as run_repo:
        original_transition = run_repo.cas_transition
        attempts = 0

        def fail_once(*args, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("database temporarily busy")
            return original_transition(*args, **kwargs)

        monkeypatch.setattr(run_repo, "cas_transition", fail_once)
        launcher = SessionLauncher(
            dispatch_callback=lambda *_args: False,
            run_repo=run_repo,
            chat_service=_ChatService(),
        )

        run_id = launcher.launch(
            scheduled_task_id=task_id,
            instruction="执行任务",
        )

        assert attempts == 2
        assert run_repo.get(run_id).status == "failed"


def test_active_slot_conflict_does_not_create_second_session():
    task_id = _create_task()
    chat_service = _ChatService()
    with ScheduledTaskRunRepository() as run_repo:
        run_repo.create(
            scheduled_task_id=task_id,
            session_id="ast_existing",
        )
        launcher = SessionLauncher(
            dispatch_callback=lambda *_args: True,
            run_repo=run_repo,
            chat_service=chat_service,
        )

        with pytest.raises(ScheduledRunAlreadyActive):
            launcher.launch(
                scheduled_task_id=task_id,
                instruction="执行任务",
            )

        assert SessionRepository().get_by_id("ast_dispatch_test") is None


def test_concurrent_launchers_share_one_database_active_slot(tmp_path):
    """两个独立连接同时 launch 时，唯一索引只允许一个会话/active run。"""
    original = sm_module._sqlalchemy_instance
    manager = SQLAlchemyManager(str(tmp_path / "scheduled-run-race.db"))
    manager.initialize()
    sm_module._sqlalchemy_instance = manager
    task_id = _create_task()
    barrier = threading.Barrier(2, timeout=10)
    result_lock = threading.Lock()
    results: list[str] = []
    conflicts: list[str] = []
    failures: list[str] = []
    dispatched_sessions: list[str] = []

    class _ConcurrentChatService:
        def __init__(self, session_id: str):
            self.session_id = session_id

        def generate_session_id(self) -> str:
            barrier.wait()
            return self.session_id

        def build_scheduled_session(self, scheduled_task_id: str, **kwargs) -> Session:
            return Session(
                session_id=kwargs["session_id"],
                workflow_id=None,
                agent_type=AgentType.ASSISTANT,
                status="active",
                source="scheduled",
                scheduled_task_id=scheduled_task_id,
                is_scheduled=1,
            )

    def launch(session_id: str) -> None:
        try:
            with ScheduledTaskRunRepository() as run_repo:
                launcher = SessionLauncher(
                    dispatch_callback=lambda sid, _instruction, _run_id, _reservation_id: (
                        dispatched_sessions.append(sid) or True
                    ),
                    run_repo=run_repo,
                    chat_service=_ConcurrentChatService(session_id),
                )
                run_id = launcher.launch(
                    scheduled_task_id=task_id,
                    instruction="只允许执行一次",
                )
            with result_lock:
                results.append(run_id)
        except ScheduledRunAlreadyActive:
            with result_lock:
                conflicts.append(session_id)
        except Exception as exc:  # pragma: no cover - 断言输出并发异常细节
            with result_lock:
                failures.append(repr(exc))

    threads = [
        threading.Thread(target=launch, args=("ast_race_a",)),
        threading.Thread(target=launch, args=("ast_race_b",)),
    ]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=15)

        assert not any(thread.is_alive() for thread in threads)
        assert failures == []
        assert len(results) == 1
        assert len(conflicts) == 1
        assert len(dispatched_sessions) == 1
        with ScheduledTaskRunRepository() as repo:
            runs, total = repo.list_by_task(task_id)
        assert total == 1
        assert runs[0].run_id == results[0]
        assert runs[0].status == "running"
        persisted = SessionRepository().get_by_id(runs[0].session_id)
        assert persisted is not None
        assert persisted.scheduled_task_id == task_id
    finally:
        manager.close()
        sm_module._sqlalchemy_instance = original
