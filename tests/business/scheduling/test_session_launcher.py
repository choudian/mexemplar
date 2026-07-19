"""SessionLauncher 投递失败必须显式终结 run，不能静默悬挂。"""

from __future__ import annotations

import threading

import pytest

import src.data.sqlalchemy_manager as sm_module
from src.business.agents.config import AgentType
from src.business.scheduling.session_launcher import (
    ScheduledRunAlreadyActive,
    SessionLauncher,
)
from src.data.models_sqlite import Session
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


def test_false_dispatch_marks_run_failed():
    with ScheduledTaskRunRepository() as run_repo:
        launcher = SessionLauncher(
            dispatch_callback=lambda _session_id, _instruction: False,
            run_repo=run_repo,
            chat_service=_ChatService(),
        )

        run_id = launcher.launch(
            scheduled_task_id="sch_dispatch_false",
            instruction="执行任务",
        )

        run = run_repo.get(run_id)
        assert run.status == "failed"
        assert run.finished_at is not None
        assert run.failure_reason == "scheduled session could not be started"


def test_dispatch_exception_marks_run_failed():
    def _raise(_session_id, _instruction):
        raise RuntimeError("provider unavailable")

    with ScheduledTaskRunRepository() as run_repo:
        launcher = SessionLauncher(
            dispatch_callback=_raise,
            run_repo=run_repo,
            chat_service=_ChatService(),
        )

        run_id = launcher.launch(
            scheduled_task_id="sch_dispatch_error",
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

    with ScheduledTaskRunRepository() as run_repo:
        launcher = SessionLauncher(
            dispatch_callback=lambda _session_id, _instruction: False,
            run_repo=run_repo,
            chat_service=_ChatService(),
        )
        run_id = launcher.launch(
            scheduled_task_id="sch_dispatch_retry_event",
            instruction="执行任务",
        )

        assert run_repo.get_fresh(run_id).terminal_event_delivered_at is None
        assert retry_pending_terminal_events(run_repo=run_repo) == 1
        assert run_repo.get_fresh(run_id).terminal_event_delivered_at is not None

    assert attempts == 2


def test_session_creation_failure_leaves_neither_run_nor_phantom_session():
    with ScheduledTaskRunRepository() as run_repo:
        launcher = SessionLauncher(
            dispatch_callback=lambda _session_id, _instruction: True,
            run_repo=run_repo,
            chat_service=_FailingChatService(),
        )

        with pytest.raises(RuntimeError):
            launcher.launch(
                scheduled_task_id="sch_session_create_error",
                instruction="执行任务",
            )

        runs, total = run_repo.list_by_task("sch_session_create_error")
        assert runs == []
        assert total == 0
        assert SessionRepository().get_by_id("ast_dispatch_test") is None


def test_transient_failure_transition_is_retried_with_explicit_terminal_state(
    monkeypatch,
):
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
            dispatch_callback=lambda _session_id, _instruction: False,
            run_repo=run_repo,
            chat_service=_ChatService(),
        )

        run_id = launcher.launch(
            scheduled_task_id="sch_retry_failed_transition",
            instruction="执行任务",
        )

        assert attempts == 2
        assert run_repo.get(run_id).status == "failed"


def test_active_slot_conflict_does_not_create_second_session():
    chat_service = _ChatService()
    with ScheduledTaskRunRepository() as run_repo:
        run_repo.create(
            scheduled_task_id="sch_atomic_conflict",
            session_id="ast_existing",
        )
        launcher = SessionLauncher(
            dispatch_callback=lambda _session_id, _instruction: True,
            run_repo=run_repo,
            chat_service=chat_service,
        )

        with pytest.raises(ScheduledRunAlreadyActive):
            launcher.launch(
                scheduled_task_id="sch_atomic_conflict",
                instruction="执行任务",
            )

        assert SessionRepository().get_by_id("ast_dispatch_test") is None


def test_concurrent_launchers_share_one_database_active_slot(tmp_path):
    """两个独立连接同时 launch 时，唯一索引只允许一个会话/active run。"""
    original = sm_module._sqlalchemy_instance
    manager = SQLAlchemyManager(str(tmp_path / "scheduled-run-race.db"))
    manager.initialize()
    sm_module._sqlalchemy_instance = manager
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
                    dispatch_callback=lambda sid, _instruction: (
                        dispatched_sessions.append(sid) or True
                    ),
                    run_repo=run_repo,
                    chat_service=_ConcurrentChatService(session_id),
                )
                run_id = launcher.launch(
                    scheduled_task_id="sch_concurrent_slot",
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
            runs, total = repo.list_by_task("sch_concurrent_slot")
        assert total == 1
        assert runs[0].run_id == results[0]
        assert runs[0].status == "running"
        persisted = SessionRepository().get_by_id(runs[0].session_id)
        assert persisted is not None
        assert persisted.scheduled_task_id == "sch_concurrent_slot"
    finally:
        manager.close()
        sm_module._sqlalchemy_instance = original
