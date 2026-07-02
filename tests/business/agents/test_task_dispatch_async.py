from __future__ import annotations

import threading
from datetime import datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.business.agents import run_context
from src.business.task_collaboration.dispatcher import TaskDispatcher
from src.business.task_collaboration.dispatcher import graph_cancel_key
from src.business.task_collaboration.service import TaskCollaborationService
from src.data.models_sqlite import Base
from src.data.repos import AssistantTaskAdjudicationRepository, AssistantTaskRepository
from src.data.repos import AssistantTaskAttemptRepository
from src.utils.timezone import utc_now_naive


class _Config:
    def get_assistant_tasks_dispatch_max_workers(self) -> int:
        return 2

    def get_assistant_tasks_attempt_lease_seconds(self) -> int:
        return 60

    def get_assistant_tasks_board_fallback_seconds(self) -> int:
        return 10

    def get_assistant_tasks_board_capacity(self) -> int:
        return 10

    def get_assistant_tasks_recruitment_min_fallback_count(self) -> int:
        return 1


class _Guard:
    def assert_can_dispatch(self) -> None:
        return None


def _patch_dispatch_config(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.business.task_collaboration.dispatcher.get_unified_config",
        lambda: _Config(),
    )
    monkeypatch.setattr(
        "src.business.task_collaboration.board.get_unified_config",
        lambda: _Config(),
    )
    monkeypatch.setattr(
        "src.business.task_collaboration.board._record_fallback_recruitment_signal",
        lambda task: None,
    )


def test_dispatcher_returns_accepted_task_id_without_waiting(monkeypatch) -> None:
    _patch_dispatch_config(monkeypatch)
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        task_repo = AssistantTaskRepository(session)
        service = TaskCollaborationService(
            task_repo=task_repo,
            adjudication_repo=AssistantTaskAdjudicationRepository(session),
        )
        graph_id = service.create_root_graph(
            session_id="ast_1",
            title="root",
            description="root task",
        )
        root = task_repo.list_graph_tasks(graph_id)[0]
        dispatcher = TaskDispatcher(cutover_guard=_Guard())

        result = dispatcher.delegate_task(
            service=service,
            graph_id=graph_id,
            session_id="ast_1",
            parent_task_id=root.task_id,
            task="child",
            context="child context",
            assignee_type="ephemeral_subagent",
            assignee_id="sub_1",
        )

        assert result["accepted"] is True
        assert result["graphId"] == graph_id
        assert result["assignment"] == "directed"
        assert task_repo.get_task(result["taskId"]) is not None
        dispatcher.shutdown()
    finally:
        session.close()
        engine.dispose()


def test_dispatcher_async_attempt_completion_creates_parent_adjudication(monkeypatch) -> None:
    _patch_dispatch_config(monkeypatch)
    service = TaskCollaborationService()
    graph_id = service.create_root_graph(
        session_id="ast_async",
        title="root",
        description="root task",
    )
    task_repo = AssistantTaskRepository()
    root = task_repo.list_graph_tasks(graph_id)[0]
    reentries: list[dict] = []
    dispatcher = TaskDispatcher(
        cutover_guard=_Guard(),
        executor_callback=lambda attempt_id: {
            "safe_summary": f"attempt {attempt_id} finished",
            "result_text": "子代理最终交付物",
        },
        parent_reentry_callback=reentries.append,
    )
    try:
        result = dispatcher.delegate_task(
            service=service,
            graph_id=graph_id,
            session_id="ast_async",
            parent_task_id=root.task_id,
            task="child",
            context="child context",
            assignee_type="ephemeral_subagent",
            assignee_id="sub_1",
        )
        future = dispatcher.start_attempt_async(
            task_id=result["taskId"],
            executor_type="ephemeral_subagent",
            executor_id="sub_1",
            lease_owner="worker_1",
        )

        assert future is not None
        payload = future.result(timeout=5)

        assert payload["accepted"] is True
        assert payload["taskId"] == result["taskId"]
        assert payload["deliverablePreview"] == "子代理最终交付物"
        assert payload["deliverableTruncated"] is False
        assert reentries == [payload]
        adjudication = AssistantTaskAdjudicationRepository().get_pending_for_task(result["taskId"])
        assert adjudication is not None
        assert adjudication.delivered_status == "done"
        assert payload["resultReferenceId"] == adjudication.adjudication_id
        assert adjudication.raw_result_ref == "子代理最终交付物"
    finally:
        task_repo.close()
        dispatcher.shutdown(wait=True)


def test_dispatcher_attempt_worker_registers_graph_cancel_key(monkeypatch) -> None:
    _patch_dispatch_config(monkeypatch)
    run_context.reset_for_tests()
    service = TaskCollaborationService()
    graph_id = service.create_root_graph(
        session_id="ast_cancel_key",
        title="root",
        description="root task",
    )
    task_repo = AssistantTaskRepository()
    root = task_repo.list_graph_tasks(graph_id)[0]
    seen: dict[str, object] = {}

    def executor_callback(attempt_id: str) -> dict:
        ctx = run_context.get_current()
        seen["attempt_id"] = attempt_id
        seen["cancel_keys"] = ctx.cancel_keys if ctx is not None else ()
        seen["cancelled"] = run_context.request_cancel_key(graph_cancel_key(graph_id))
        seen["event_set"] = bool(ctx and ctx.cancel_event.is_set())
        return {"safe_summary": "attempt observed cancellation key"}

    dispatcher = TaskDispatcher(
        cutover_guard=_Guard(),
        executor_callback=executor_callback,
    )
    try:
        result = dispatcher.delegate_task(
            service=service,
            graph_id=graph_id,
            session_id="ast_cancel_key",
            parent_task_id=root.task_id,
            task="child",
            context="child context",
            assignee_type="ephemeral_subagent",
            assignee_id="sub_cancel",
        )
        future = dispatcher.start_attempt_async(
            task_id=result["taskId"],
            executor_type="ephemeral_subagent",
            executor_id="sub_cancel",
            lease_owner="worker_1",
        )

        assert future is not None
        assert future.result(timeout=5)["accepted"] is True
        assert graph_cancel_key(graph_id) in seen["cancel_keys"]
        assert seen["cancelled"] is True
        assert seen["event_set"] is True
        assert run_context.request_cancel_key(graph_cancel_key(graph_id)) is False
    finally:
        task_repo.close()
        dispatcher.shutdown(wait=True)
        run_context.reset_for_tests()


def test_dispatcher_start_pending_graph_tasks_reuses_latest_checkpoint(monkeypatch) -> None:
    _patch_dispatch_config(monkeypatch)
    service = TaskCollaborationService()
    graph_id = service.create_root_graph(
        session_id="ast_continue_dispatch",
        title="root",
        description="root task",
    )
    task_repo = AssistantTaskRepository()
    root = task_repo.list_graph_tasks(graph_id)[0]
    child_id = service.create_child_task(
        graph_id=graph_id,
        session_id="ast_continue_dispatch",
        parent_task_id=root.task_id,
        title="child",
        description="child",
        assignee_type="specialist",
        assignee_id="sp_resume",
    )
    checkpoint_ref = '{"subagent_id":"child_resume"}'
    attempt_repo = AssistantTaskAttemptRepository()
    old_attempt = attempt_repo.start_attempt(
        task_id=child_id,
        executor_type="specialist",
        executor_id="sp_resume",
        lease_owner="worker_old",
        lease_expires_at=datetime.now() + timedelta(minutes=5),
        checkpoint_ref=checkpoint_ref,
    )
    assert old_attempt is not None
    attempt_repo.pause_if_current(
        attempt_id=old_attempt.attempt_id,
        fence_token=old_attempt.fence_token,
        result_ref="fallback-result-ref",
    )
    observed = {}
    callback_done = threading.Event()

    def executor_callback(attempt_id: str) -> dict:
        row = AssistantTaskAttemptRepository().get_by_id(attempt_id)
        observed["checkpoint_ref"] = row.checkpoint_ref if row is not None else None
        callback_done.set()
        return {"safe_summary": "resumed"}

    dispatcher = TaskDispatcher(
        cutover_guard=_Guard(),
        executor_callback=executor_callback,
    )
    try:
        started = dispatcher.start_pending_graph_tasks(
            session_id="ast_continue_dispatch",
            graph_id=graph_id,
        )

        assert started == 1
        assert callback_done.wait(timeout=5) is True
        dispatcher.shutdown(wait=True)
        assert observed["checkpoint_ref"] == checkpoint_ref
    finally:
        attempt_repo.close()
        task_repo.close()
        dispatcher.shutdown(wait=True)


def test_dispatcher_starts_fallback_attempt_for_stale_open_board_task(monkeypatch) -> None:
    _patch_dispatch_config(monkeypatch)
    service = TaskCollaborationService()
    graph_id = service.create_root_graph(
        session_id="ast_fallback_dispatch",
        title="root",
        description="root task",
    )
    task_repo = AssistantTaskRepository()
    root = task_repo.list_graph_tasks(graph_id)[0]
    child_id = service.create_child_task(
        graph_id=graph_id,
        session_id="ast_fallback_dispatch",
        parent_task_id=root.task_id,
        title="open child",
        description="open child",
    )
    row = task_repo.get_task(child_id)
    row.updated_at = utc_now_naive() - timedelta(seconds=30)
    task_repo.session.commit()
    dispatcher = TaskDispatcher(
        cutover_guard=_Guard(),
        executor_callback=lambda attempt_id: {"safe_summary": f"{attempt_id} done"},
    )
    try:
        started = dispatcher.start_fallback_attempts(session_id="ast_fallback_dispatch")

        assert started == 1
        attempts = AssistantTaskAttemptRepository().list_for_task(child_id)
        assert len(attempts) == 1
        assert attempts[0].executor_type == "ephemeral_subagent"
        assert attempts[0].executor_id == child_id
    finally:
        task_repo.close()
        dispatcher.shutdown(wait=True)


def test_dispatcher_rejects_late_fenced_attempt_result(monkeypatch) -> None:
    _patch_dispatch_config(monkeypatch)
    service = TaskCollaborationService()
    graph_id = service.create_root_graph(
        session_id="ast_late",
        title="root",
        description="root task",
    )
    task_repo = AssistantTaskRepository()
    root = task_repo.list_graph_tasks(graph_id)[0]
    child_id = service.create_child_task(
        graph_id=graph_id,
        session_id="ast_late",
        parent_task_id=root.task_id,
        title="child",
        description="child",
        assignee_type="ephemeral_subagent",
        assignee_id="sub_1",
    )
    attempt_repo = AssistantTaskAttemptRepository()
    attempt = attempt_repo.start_attempt(
        task_id=child_id,
        executor_type="ephemeral_subagent",
        executor_id="sub_1",
        lease_owner="worker_1",
        lease_expires_at=datetime.now(),
    )
    assert attempt is not None
    fence_token = attempt.fence_token
    attempt_repo.fence(attempt.attempt_id)
    dispatcher = TaskDispatcher(cutover_guard=_Guard())
    try:
        payload = dispatcher._record_attempt_outcome(
            attempt_id=attempt.attempt_id,
            fence_token=fence_token,
            delivered_status="done",
            safe_summary="任务已回传结果，等待上级检查。",
            result_ref="late success",
        )

        assert payload == {
            "accepted": False,
            "attemptId": attempt.attempt_id,
            "lateResult": True,
        }
        assert AssistantTaskAdjudicationRepository().get_pending_for_task(child_id) is None
    finally:
        attempt_repo.close()
        task_repo.close()
        dispatcher.shutdown()


def test_dispatcher_rejects_success_for_cancelled_task(monkeypatch) -> None:
    """C2: Late success result for a cancelled task MUST be rejected."""
    _patch_dispatch_config(monkeypatch)
    service = TaskCollaborationService()
    graph_id = service.create_root_graph(
        session_id="ast_cancel_late",
        title="root",
        description="root task",
    )
    task_repo = AssistantTaskRepository()
    root = task_repo.list_graph_tasks(graph_id)[0]
    child_id = service.create_child_task(
        graph_id=graph_id,
        session_id="ast_cancel_late",
        parent_task_id=root.task_id,
        title="child",
        description="child",
        assignee_type="ephemeral_subagent",
        assignee_id="sub_1",
    )
    attempt_repo = AssistantTaskAttemptRepository()
    attempt = attempt_repo.start_attempt(
        task_id=child_id,
        executor_type="ephemeral_subagent",
        executor_id="sub_1",
        lease_owner="worker_1",
        lease_expires_at=datetime.now(),
    )
    assert attempt is not None
    fence_token = attempt.fence_token
    # Cancel the task while the attempt is still running
    service.cancel_graph(session_id="ast_cancel_late", graph_id=graph_id)
    dispatcher = TaskDispatcher(cutover_guard=_Guard())
    try:
        payload = dispatcher._record_attempt_outcome(
            attempt_id=attempt.attempt_id,
            fence_token=fence_token,
            delivered_status="done",
            safe_summary="任务已回传结果，等待上级检查。",
            result_ref="late success after cancel",
        )

        assert payload["accepted"] is False
        assert payload["lateResult"] is True
        assert payload["taskTerminal"] == "cancelled"
        # No adjudication should be created for a cancelled task
        assert AssistantTaskAdjudicationRepository().get_pending_for_task(child_id) is None
    finally:
        attempt_repo.close()
        task_repo.close()
        dispatcher.shutdown()


def test_dispatcher_rejects_failure_for_cancelled_task(monkeypatch) -> None:
    """C2: Late failure result for a cancelled task MUST also be rejected."""
    _patch_dispatch_config(monkeypatch)
    service = TaskCollaborationService()
    graph_id = service.create_root_graph(
        session_id="ast_cancel_late_fail",
        title="root",
        description="root task",
    )
    task_repo = AssistantTaskRepository()
    root = task_repo.list_graph_tasks(graph_id)[0]
    child_id = service.create_child_task(
        graph_id=graph_id,
        session_id="ast_cancel_late_fail",
        parent_task_id=root.task_id,
        title="child",
        description="child",
        assignee_type="ephemeral_subagent",
        assignee_id="sub_1",
    )
    attempt_repo = AssistantTaskAttemptRepository()
    attempt = attempt_repo.start_attempt(
        task_id=child_id,
        executor_type="ephemeral_subagent",
        executor_id="sub_1",
        lease_owner="worker_1",
        lease_expires_at=datetime.now(),
    )
    assert attempt is not None
    fence_token = attempt.fence_token
    service.cancel_graph(session_id="ast_cancel_late_fail", graph_id=graph_id)
    dispatcher = TaskDispatcher(cutover_guard=_Guard())
    try:
        payload = dispatcher._record_attempt_outcome(
            attempt_id=attempt.attempt_id,
            fence_token=fence_token,
            delivered_status="stuck",
            safe_summary="late failure after cancel",
        )

        assert payload["accepted"] is False
        assert payload["lateResult"] is True
        assert payload["taskTerminal"] == "cancelled"
        assert AssistantTaskAdjudicationRepository().get_pending_for_task(child_id) is None
    finally:
        attempt_repo.close()
        task_repo.close()
        dispatcher.shutdown()
