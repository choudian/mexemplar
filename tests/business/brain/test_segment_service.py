from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.business.brain.segment_service import SegmentService


def test_seal_segment_creates_segment_and_emits_boundary_event() -> None:
    repo = MagicMock()
    repo.create_segment.return_value = SimpleNamespace(segment_id="seg-1")

    with patch("src.business.brain.segment_service.emit") as emit:
        segment_id = SegmentService(repo=repo).seal_segment(
            "sess-1",
            "idle",
            message_id_start="msg-1",
            message_id_end="msg-2",
        )

    assert segment_id == "seg-1"
    repo.create_segment.assert_called_once_with(
        session_id="sess-1",
        boundary_reason="idle",
        message_id_start="msg-1",
        message_id_end="msg-2",
    )
    emit.assert_called_once_with(
        "segment_boundary_triggered",
        session_id="sess-1",
        segment_id="seg-1",
        reason="idle",
    )


def test_seal_segment_skips_when_no_message_range_can_be_inferred() -> None:
    repo = MagicMock()
    service = SegmentService(repo=repo)

    with (
        patch.object(service, "_infer_message_range", return_value=(None, None)),
        patch("src.business.brain.segment_service.emit") as emit,
    ):
        segment_id = service.seal_segment("sess-1", "idle")

    assert segment_id is None
    repo.create_segment.assert_not_called()
    emit.assert_not_called()


def test_handle_idle_trigger_defers_when_session_has_active_subagent() -> None:
    repo = MagicMock()
    service = SegmentService(repo=repo)

    with (
        patch.object(service, "_has_active_subagent", return_value=True),
        patch("src.business.brain.segment_service.emit") as emit,
    ):
        result = service.handle_idle_trigger("sess-1")

    assert result is None
    repo.create_segment.assert_not_called()
    emit.assert_not_called()


def test_handle_idle_trigger_seals_when_no_active_subagent() -> None:
    repo = MagicMock()
    repo.create_segment.return_value = SimpleNamespace(segment_id="seg-1")
    service = SegmentService(repo=repo)

    with (
        patch.object(service, "_has_active_subagent", return_value=False),
        patch.object(service, "_infer_message_range", return_value=("msg-1", "msg-2")),
        patch("src.business.brain.segment_service.emit") as emit,
    ):
        result = service.handle_idle_trigger("sess-1")

    assert result == "seg-1"
    repo.create_segment.assert_called_once()
    emit.assert_any_call("segment_idle_trigger", session_id="sess-1")


def _seed_delegation(parent_id: str, child_id: str, child_status: str) -> None:
    from src.data.models_sqlite import Session as SessionModel
    from src.data.models_sqlite import WorkflowTransition
    from src.data.repos import AssistantTaskRepository
    from src.data.repos.assistant_task_attempt_repository import (
        AssistantTaskAttemptRepository,
    )
    from src.data.repos.session_repository import SessionRepository
    from src.data.repos.workflow_transition_repository import WorkflowTransitionRepository

    SessionRepository().create(
        SessionModel(
            session_id=child_id,
            workflow_id="dlg_child",
            agent_type="ephemeral_subagent",
            status=child_status,
        )
    )
    WorkflowTransitionRepository().create(
        WorkflowTransition(
            transition_id=f"t_{child_id}",
            workflow_id="dlg_child",
            event_type="assistant_delegation_started",
            from_session_id=parent_id,
            to_session_id=child_id,
            payload=None,
        )
    )
    # "在不在跑"现在查 attempt：active child 需要对应一条 active attempt
    if child_status == "active":
        from datetime import timedelta

        from src.utils.timezone import utc_now_naive

        with AssistantTaskRepository() as tasks:
            task_id = tasks.create_task(
                graph_id=f"tg_{child_id}",
                session_id=parent_id,
                title="测试",
                description="d",
                assignee_type="ephemeral_subagent",
                assignee_id=child_id,
                status="running",
            ).task_id
        with AssistantTaskAttemptRepository() as attempts:
            attempts.start_attempt(
                task_id=task_id,
                executor_type="ephemeral_subagent",
                executor_id=child_id,
                lease_owner="test",
                lease_expires_at=utc_now_naive() + timedelta(minutes=30),
            )
            attempts.bind_session(task_id=task_id, executor_session_id=child_id)


def test_has_active_subagent_detects_running_child_session() -> None:
    _seed_delegation("parent-1", "child-1", child_status="active")

    assert SegmentService()._has_active_subagent("parent-1") is True


def test_has_active_subagent_false_when_child_session_completed() -> None:
    _seed_delegation("parent-1", "child-1", child_status="completed")

    assert SegmentService()._has_active_subagent("parent-1") is False


def test_has_active_subagent_false_without_delegation() -> None:
    assert SegmentService()._has_active_subagent("parent-without-children") is False


def test_crash_reset_stale_segments_resets_only_distilling_segments_past_threshold() -> None:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    stale = SimpleNamespace(segment_id="stale", distilling_started_at=now - timedelta(seconds=120))
    recent = SimpleNamespace(segment_id="recent", distilling_started_at=now - timedelta(seconds=5))
    missing_started_at = SimpleNamespace(segment_id="missing", distilling_started_at=None)
    repo = MagicMock()
    repo.get_segments_by_status.return_value = [stale, recent, missing_started_at]
    repo.transition_segment_status.return_value = True

    reset_count = SegmentService(repo=repo).crash_reset_stale_segments(threshold_seconds=60)

    assert reset_count == 1
    repo.get_segments_by_status.assert_called_once_with("distilling")
    repo.transition_segment_status.assert_called_once_with(
        "stale",
        from_status="distilling",
        to_status="pending",
    )
