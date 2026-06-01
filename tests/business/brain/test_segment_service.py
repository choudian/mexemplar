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
