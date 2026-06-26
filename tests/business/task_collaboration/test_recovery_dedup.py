"""I18-6: Recovery _notify_scheduler_recovered graph deduplication.

When two tasks in the same graph both have expired attempts, the scheduler's
on_executor_recovered should be called exactly once for the shared graph_id,
not twice. This tests the dedup logic in TaskRecoveryService._notify_scheduler_recovered.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from src.business.task_collaboration.graph_scheduler import set_graph_scheduler
from src.business.task_collaboration.recovery import TaskRecoveryService
from src.business.task_collaboration.service import TaskCollaborationService
from src.data.repos import AssistantTaskAttemptRepository
from src.data.repos.base_repository import generate_id
from src.utils.timezone import utc_now_naive


def _build_graph_with_two_nodes():
    """Build a graph with 2 nodes; return (graph_id, task_ids, session_id)."""
    session_id = generate_id("sess")
    with TaskCollaborationService() as svc:
        result = svc.build_task_graph(
            session_id=session_id,
            nodes=[
                {"nodeId": "n1", "title": "Node A", "description": "First"},
                {"nodeId": "n2", "title": "Node B", "description": "Second"},
            ],
        )
    return result["graphId"], [result["nodeTaskIds"]["n1"], result["nodeTaskIds"]["n2"]], session_id


def _start_expired_attempts(task_ids: list[str]) -> None:
    """Create expired attempts for all given tasks."""
    for task_id in task_ids:
        with TaskCollaborationService() as svc:
            svc.update_task_status(task_id=task_id, status="running")
        with AssistantTaskAttemptRepository() as attempts:
            attempts.start_attempt(
                task_id=task_id,
                executor_type="ephemeral_subagent",
                executor_id=task_id,
                lease_owner="test",
                lease_expires_at=utc_now_naive(),  # already expired
            )


class TestRecoveryGraphDeduplication:
    def test_scheduler_called_once_for_shared_graph(self, in_memory_db):
        """Two tasks in same graph with expired attempts → on_executor_recovered called once for that graph."""
        graph_id, task_ids, session_id = _build_graph_with_two_nodes()
        _start_expired_attempts(task_ids)

        scheduler_callback = MagicMock()
        set_graph_scheduler(scheduler_callback)
        try:
            recovery = TaskRecoveryService()
            recovery.fence_expired_attempts(now=utc_now_naive())
        finally:
            set_graph_scheduler(None)

        # on_executor_recovered should be called exactly once for the shared graph_id
        assert scheduler_callback.on_executor_recovered.call_count == 1
        call_args = scheduler_callback.on_executor_recovered.call_args
        assert call_args[0][0] == graph_id

    def test_scheduler_not_called_when_not_assembled(self, in_memory_db):
        """No scheduler assembled → recovery runs without error, no callback."""
        graph_id, task_ids, session_id = _build_graph_with_two_nodes()
        _start_expired_attempts(task_ids)

        set_graph_scheduler(None)
        recovery = TaskRecoveryService()
        # Must not raise even though scheduler is None
        count = recovery.fence_expired_attempts(now=utc_now_naive())
        assert count == 2  # Both tasks recovered

    def test_two_graphs_each_called_once(self, in_memory_db):
        """Tasks in two different graphs → on_executor_recovered called once per graph."""
        # Graph 1
        graph_id_1, task_ids_1, _ = _build_graph_with_two_nodes()
        _start_expired_attempts(task_ids_1)

        # Graph 2
        graph_id_2, task_ids_2, _ = _build_graph_with_two_nodes()
        _start_expired_attempts(task_ids_2)

        scheduler_callback = MagicMock()
        set_graph_scheduler(scheduler_callback)
        try:
            recovery = TaskRecoveryService()
            recovery.fence_expired_attempts(now=utc_now_naive())
        finally:
            set_graph_scheduler(None)

        # Called once for each graph (2 total)
        assert scheduler_callback.on_executor_recovered.call_count == 2
        called_graph_ids = {
            call[0][0] for call in scheduler_callback.on_executor_recovered.call_args_list
        }
        assert graph_id_1 in called_graph_ids
        assert graph_id_2 in called_graph_ids
