"""Tests for dispatcher scheduler_callback wiring (024 C4)."""

from __future__ import annotations

from src.business.task_collaboration.dispatcher import TaskDispatcher
from src.business.task_collaboration.service import TaskCollaborationService
from src.data.repos import AssistantTaskRepository


class _Config:
    def get_assistant_tasks_dispatch_max_workers(self) -> int:
        return 2

    def get_assistant_tasks_attempt_lease_seconds(self) -> int:
        return 60


class _Guard:
    def assert_can_dispatch(self) -> None:
        return None


def _patch_dispatch_config(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.business.task_collaboration.dispatcher.get_unified_config",
        lambda: _Config(),
    )


class TestSchedulerCallbackWiring:
    """C4: dispatcher attempt outcome triggers scheduler_callback."""

    def test_scheduler_callback_called_on_attempt_completion(self, monkeypatch) -> None:
        """Successful attempt outcome notifies scheduler_callback with (graph_id, task_id)."""
        _patch_dispatch_config(monkeypatch)
        service = TaskCollaborationService()
        graph_id = service.create_root_graph(
            session_id="sched_cb_ok",
            title="root",
            description="root task",
        )
        task_repo = AssistantTaskRepository()
        root = task_repo.list_graph_tasks(graph_id)[0]
        child_id = service.create_child_task(
            graph_id=graph_id,
            session_id="sched_cb_ok",
            parent_task_id=root.task_id,
            title="child",
            description="child",
            assignee_type="ephemeral_subagent",
            assignee_id="sub_1",
        )

        scheduler_calls: list[tuple[str, str]] = []
        dispatcher = TaskDispatcher(
            cutover_guard=_Guard(),
            executor_callback=lambda attempt_id: {"safe_summary": "done"},
            scheduler_callback=lambda gid, tid: scheduler_calls.append((gid, tid)),
        )
        try:
            future = dispatcher.start_attempt_async(
                task_id=child_id,
                executor_type="ephemeral_subagent",
                executor_id="sub_1",
                lease_owner="worker_1",
            )
            assert future is not None
            payload = future.result(timeout=5)

            assert payload["accepted"] is True
            assert len(scheduler_calls) == 1
            assert scheduler_calls[0] == (graph_id, child_id)
        finally:
            task_repo.close()
            dispatcher.shutdown(wait=True)

    def test_scheduler_callback_called_on_attempt_failure(self, monkeypatch) -> None:
        """Failed attempt outcome also notifies scheduler_callback."""
        _patch_dispatch_config(monkeypatch)
        service = TaskCollaborationService()
        graph_id = service.create_root_graph(
            session_id="sched_cb_fail",
            title="root",
            description="root task",
        )
        task_repo = AssistantTaskRepository()
        root = task_repo.list_graph_tasks(graph_id)[0]
        child_id = service.create_child_task(
            graph_id=graph_id,
            session_id="sched_cb_fail",
            parent_task_id=root.task_id,
            title="child",
            description="child",
            assignee_type="ephemeral_subagent",
            assignee_id="sub_1",
        )

        scheduler_calls: list[tuple[str, str]] = []
        dispatcher = TaskDispatcher(
            cutover_guard=_Guard(),
            executor_callback=lambda attempt_id: (_ for _ in ()).throw(RuntimeError("boom")),
            scheduler_callback=lambda gid, tid: scheduler_calls.append((gid, tid)),
        )
        try:
            future = dispatcher.start_attempt_async(
                task_id=child_id,
                executor_type="ephemeral_subagent",
                executor_id="sub_1",
                lease_owner="worker_1",
            )
            assert future is not None
            payload = future.result(timeout=5)

            # Executor failed, so delivered_status is stuck, but scheduler still notified
            assert payload["accepted"] is True
            assert payload["deliveredStatus"] == "stuck"
            assert len(scheduler_calls) == 1
            assert scheduler_calls[0] == (graph_id, child_id)
        finally:
            task_repo.close()
            dispatcher.shutdown(wait=True)

    def test_scheduler_callback_exception_is_caught_and_logged(self, monkeypatch) -> None:
        """Exception from scheduler_callback must be caught and logged, not propagated."""
        _patch_dispatch_config(monkeypatch)
        service = TaskCollaborationService()
        graph_id = service.create_root_graph(
            session_id="sched_cb_exc",
            title="root",
            description="root task",
        )
        task_repo = AssistantTaskRepository()
        root = task_repo.list_graph_tasks(graph_id)[0]
        child_id = service.create_child_task(
            graph_id=graph_id,
            session_id="sched_cb_exc",
            parent_task_id=root.task_id,
            title="child",
            description="child",
            assignee_type="ephemeral_subagent",
            assignee_id="sub_1",
        )

        def _failing_callback(gid: str, tid: str) -> None:
            raise RuntimeError("scheduler callback exploded")

        dispatcher = TaskDispatcher(
            cutover_guard=_Guard(),
            executor_callback=lambda attempt_id: {"safe_summary": "done"},
            scheduler_callback=_failing_callback,
        )
        try:
            future = dispatcher.start_attempt_async(
                task_id=child_id,
                executor_type="ephemeral_subagent",
                executor_id="sub_1",
                lease_owner="worker_1",
            )
            assert future is not None
            # Must not raise — the exception is caught and logged
            payload = future.result(timeout=5)

            assert payload["accepted"] is True
        finally:
            task_repo.close()
            dispatcher.shutdown(wait=True)

    def test_no_scheduler_callback_does_not_error(self, monkeypatch) -> None:
        """When no scheduler_callback is provided, completion still succeeds."""
        _patch_dispatch_config(monkeypatch)
        service = TaskCollaborationService()
        graph_id = service.create_root_graph(
            session_id="sched_cb_none",
            title="root",
            description="root task",
        )
        task_repo = AssistantTaskRepository()
        root = task_repo.list_graph_tasks(graph_id)[0]
        child_id = service.create_child_task(
            graph_id=graph_id,
            session_id="sched_cb_none",
            parent_task_id=root.task_id,
            title="child",
            description="child",
            assignee_type="ephemeral_subagent",
            assignee_id="sub_1",
        )

        dispatcher = TaskDispatcher(
            cutover_guard=_Guard(),
            executor_callback=lambda attempt_id: {"safe_summary": "done"},
            # no scheduler_callback
        )
        try:
            future = dispatcher.start_attempt_async(
                task_id=child_id,
                executor_type="ephemeral_subagent",
                executor_id="sub_1",
                lease_owner="worker_1",
            )
            assert future is not None
            payload = future.result(timeout=5)

            assert payload["accepted"] is True
        finally:
            task_repo.close()
            dispatcher.shutdown(wait=True)
