"""
Segment 状态机、边界源和委托事件测试 (T022, T023, T024)

覆盖：
- T022: 合法状态转换、非法转换拒绝、崩溃重置
- T023: 边界源 (window_close, idle, new_session, token_limit)
- T024: 委托事件不触发 Segment 封存
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

from src.business.brain.models import (
    SegmentStatus,
    BoundaryReason,
    VALID_TRANSITIONS,
)
from src.utils.events import clear_all, emit, connect


@pytest.fixture(autouse=True)
def _cleanup_events():
    yield
    clear_all()


# ═══════════════════════════════════════════════
# T022: Segment 状态机测试
# ═══════════════════════════════════════════════


class TestSegmentStateMachine:
    """验证 VALID_TRANSITIONS 定义的状态机规则。"""

    def test_valid_transitions_definition(self):
        """确认 VALID_TRANSITIONS 定义了正确的状态图。"""
        assert SegmentStatus.PENDING in VALID_TRANSITIONS
        assert SegmentStatus.DISTILLING in VALID_TRANSITIONS
        assert SegmentStatus.FAILED in VALID_TRANSITIONS
        assert SegmentStatus.COMPLETED in VALID_TRANSITIONS

        # pending -> distilling
        assert SegmentStatus.DISTILLING in VALID_TRANSITIONS[SegmentStatus.PENDING]
        # distilling -> completed, distilling -> failed, distilling -> pending (crash reset)
        assert SegmentStatus.COMPLETED in VALID_TRANSITIONS[SegmentStatus.DISTILLING]
        assert SegmentStatus.FAILED in VALID_TRANSITIONS[SegmentStatus.DISTILLING]
        assert SegmentStatus.PENDING in VALID_TRANSITIONS[SegmentStatus.DISTILLING]
        # failed -> pending
        assert SegmentStatus.PENDING in VALID_TRANSITIONS[SegmentStatus.FAILED]
        # completed -> nowhere
        assert len(VALID_TRANSITIONS[SegmentStatus.COMPLETED]) == 0

    def test_pending_to_distilling_is_valid(self):
        """pending -> distilling 是合法的。"""
        allowed = VALID_TRANSITIONS[SegmentStatus.PENDING]
        assert SegmentStatus.DISTILLING in allowed

    def test_distilling_to_completed_is_valid(self):
        """distilling -> completed 是合法的。"""
        allowed = VALID_TRANSITIONS[SegmentStatus.DISTILLING]
        assert SegmentStatus.COMPLETED in allowed

    def test_distilling_to_failed_is_valid(self):
        """distilling -> failed 是合法的。"""
        allowed = VALID_TRANSITIONS[SegmentStatus.DISTILLING]
        assert SegmentStatus.FAILED in allowed

    def test_failed_to_pending_is_valid(self):
        """failed -> pending 是合法的（手动重试或自动恢复）。"""
        allowed = VALID_TRANSITIONS[SegmentStatus.FAILED]
        assert SegmentStatus.PENDING in allowed

    def test_distilling_to_pending_is_valid_for_crash_reset(self):
        """distilling -> pending 是合法的（崩溃恢复重置）。"""
        allowed = VALID_TRANSITIONS[SegmentStatus.DISTILLING]
        assert SegmentStatus.PENDING in allowed

    def test_completed_has_no_transitions(self):
        """completed 是终态，不可转换。"""
        assert len(VALID_TRANSITIONS[SegmentStatus.COMPLETED]) == 0


class TestInvalidTransitions:
    """验证非法状态转换被拒绝。"""

    @pytest.mark.parametrize(
        "from_status, to_status",
        [
            (SegmentStatus.PENDING, SegmentStatus.COMPLETED),
            (SegmentStatus.PENDING, SegmentStatus.FAILED),
            (SegmentStatus.PENDING, SegmentStatus.PENDING),
            (SegmentStatus.COMPLETED, SegmentStatus.PENDING),
            (SegmentStatus.COMPLETED, SegmentStatus.DISTILLING),
            (SegmentStatus.COMPLETED, SegmentStatus.FAILED),
            (SegmentStatus.FAILED, SegmentStatus.DISTILLING),
            (SegmentStatus.FAILED, SegmentStatus.COMPLETED),
            (SegmentStatus.FAILED, SegmentStatus.FAILED),
            (SegmentStatus.DISTILLING, SegmentStatus.DISTILLING),
        ],
    )
    def test_invalid_transition_rejected(self, from_status, to_status):
        """所有不在 VALID_TRANSITIONS 中的转换都应被拒绝。"""
        allowed = VALID_TRANSITIONS.get(from_status, set())
        assert to_status not in allowed


class TestCrashReset:
    """验证崩溃重置逻辑：扫描超时的 distilling segment 并重置为 pending。"""

    def test_crash_reset_scans_old_distilling_segments(self):
        """超过阈值的 distilling segment 应被重置为 pending。"""
        from src.business.brain.segment_service import SegmentService

        # 使用 mock 的 repo 验证交互
        mock_repo = MagicMock()
        stale_segment = MagicMock()
        stale_segment.segment_id = "stale-1"
        stale_segment.status = "distilling"
        stale_segment.distilling_started_at = datetime.now() - timedelta(hours=2)
        mock_repo.get_segments_by_status.return_value = [stale_segment]
        mock_repo.transition_segment_status.return_value = True

        service = SegmentService()
        service._repo = mock_repo

        service.crash_reset_stale_segments(threshold_seconds=300)

        mock_repo.get_segments_by_status.assert_called_once_with("distilling")
        mock_repo.transition_segment_status.assert_called_once_with(
            "stale-1",
            from_status="distilling",
            to_status="pending",
        )

    def test_crash_reset_skips_recent_distilling_segments(self):
        """未超时的 distilling segment 不应被重置。"""
        from src.business.brain.segment_service import SegmentService

        mock_repo = MagicMock()
        recent_segment = MagicMock()
        recent_segment.segment_id = "recent-1"
        recent_segment.status = "distilling"
        recent_segment.distilling_started_at = datetime.now() - timedelta(seconds=10)
        mock_repo.get_segments_by_status.return_value = [recent_segment]

        service = SegmentService()
        service._repo = mock_repo

        service.crash_reset_stale_segments(threshold_seconds=300)

        mock_repo.transition_segment_status.assert_not_called()

    def test_crash_reset_empty_when_no_distilling_segments(self):
        """没有 distilling segment 时不应报错。"""
        from src.business.brain.segment_service import SegmentService

        mock_repo = MagicMock()
        mock_repo.get_segments_by_status.return_value = []

        service = SegmentService()
        service._repo = mock_repo

        # 不应抛异常
        service.crash_reset_stale_segments(threshold_seconds=300)

        mock_repo.transition_segment_status.assert_not_called()


# ═══════════════════════════════════════════════
# T023: Segment 边界源测试
# ═══════════════════════════════════════════════


class TestBoundarySources:
    """验证不同边界源触发 Segment 封存。"""

    def test_window_close_boundary(self):
        """window_close 边界触发封存。"""
        from src.business.brain.segment_service import SegmentService

        mock_repo = MagicMock()
        segment_id = uuid4().hex[:50]
        mock_segment = MagicMock()
        mock_segment.segment_id = segment_id
        mock_segment.status = "pending"
        mock_repo.create_segment.return_value = mock_segment

        service = SegmentService()
        service._repo = mock_repo

        captured = {}

        def on_boundary(sender, **kwargs):
            captured.update(kwargs)

        connect("segment_boundary_triggered", on_boundary, weak=False)

        result = service.seal_segment(
            session_id="sess-1",
            boundary_reason=BoundaryReason.WINDOW_CLOSE.value,
            message_id_start="msg-1",
            message_id_end="msg-10",
        )

        assert result is not None
        assert captured.get("reason") == BoundaryReason.WINDOW_CLOSE.value
        assert captured.get("session_id") == "sess-1"

    def test_idle_boundary(self):
        """idle 边界触发封存。"""
        from src.business.brain.segment_service import SegmentService

        mock_repo = MagicMock()
        segment_id = uuid4().hex[:50]
        mock_segment = MagicMock()
        mock_segment.segment_id = segment_id
        mock_segment.status = "pending"
        mock_repo.create_segment.return_value = mock_segment

        service = SegmentService()
        service._repo = mock_repo
        service._infer_message_range = MagicMock(return_value=("msg-1", "msg-2"))

        captured = {}

        def on_boundary(sender, **kwargs):
            captured.update(kwargs)

        connect("segment_boundary_triggered", on_boundary, weak=False)

        result = service.seal_segment(
            session_id="sess-2",
            boundary_reason=BoundaryReason.IDLE.value,
        )

        assert result is not None
        assert captured.get("reason") == BoundaryReason.IDLE.value

    def test_new_session_boundary(self):
        """new_session 边界触发封存。"""
        from src.business.brain.segment_service import SegmentService

        mock_repo = MagicMock()
        segment_id = uuid4().hex[:50]
        mock_segment = MagicMock()
        mock_segment.segment_id = segment_id
        mock_repo.create_segment.return_value = mock_segment

        service = SegmentService()
        service._repo = mock_repo
        service._infer_message_range = MagicMock(return_value=("msg-1", "msg-2"))

        captured = {}

        def on_boundary(sender, **kwargs):
            captured.update(kwargs)

        connect("segment_boundary_triggered", on_boundary, weak=False)

        result = service.seal_segment(
            session_id="sess-3",
            boundary_reason=BoundaryReason.NEW_SESSION.value,
        )

        assert result is not None
        assert captured.get("reason") == BoundaryReason.NEW_SESSION.value

    def test_token_limit_boundary(self):
        """token_limit 边界触发封存。"""
        from src.business.brain.segment_service import SegmentService

        mock_repo = MagicMock()
        segment_id = uuid4().hex[:50]
        mock_segment = MagicMock()
        mock_segment.segment_id = segment_id
        mock_repo.create_segment.return_value = mock_segment

        service = SegmentService()
        service._repo = mock_repo
        service._infer_message_range = MagicMock(return_value=("msg-1", "msg-2"))

        captured = {}

        def on_boundary(sender, **kwargs):
            captured.update(kwargs)

        connect("segment_boundary_triggered", on_boundary, weak=False)

        result = service.seal_segment(
            session_id="sess-4",
            boundary_reason=BoundaryReason.TOKEN_LIMIT.value,
        )

        assert result is not None
        assert captured.get("reason") == BoundaryReason.TOKEN_LIMIT.value

    def test_all_boundary_reasons_are_enum_members(self):
        """确认 BoundaryReason 包含所有预期边界源。"""
        expected = {"window_close", "idle", "new_session", "token_limit"}
        actual = {e.value for e in BoundaryReason}
        assert expected == actual


class TestIdleTrigger:
    """验证 SegmentService.handle_idle_trigger() 正确处理空闲触发。"""

    def test_handle_idle_trigger_seals_segment(self):
        from src.business.brain.segment_service import SegmentService

        mock_repo = MagicMock()
        segment_id = uuid4().hex[:50]
        mock_segment = MagicMock()
        mock_segment.segment_id = segment_id
        mock_repo.create_segment.return_value = mock_segment

        service = SegmentService()
        service._repo = mock_repo
        service._infer_message_range = MagicMock(return_value=("msg-1", "msg-2"))

        captured_idle = {}
        captured_boundary = {}

        def on_idle(sender, **kwargs):
            captured_idle.update(kwargs)

        def on_boundary(sender, **kwargs):
            captured_boundary.update(kwargs)

        connect("segment_idle_trigger", on_idle, weak=False)
        connect("segment_boundary_triggered", on_boundary, weak=False)

        result = service.handle_idle_trigger(session_id="sess-idle")

        assert result is not None
        assert captured_idle.get("session_id") == "sess-idle"
        assert captured_boundary.get("reason") == BoundaryReason.IDLE.value

    def test_idle_trigger_skips_when_no_new_display_messages(self):
        from src.business.brain.segment_service import SegmentService

        mock_repo = MagicMock()
        service = SegmentService()
        service._repo = mock_repo
        service._infer_message_range = MagicMock(return_value=(None, None))

        boundary_events = []

        def on_boundary(sender, **kwargs):
            boundary_events.append(kwargs)

        connect("segment_boundary_triggered", on_boundary, weak=False)

        result = service.handle_idle_trigger(session_id="sess-empty")

        assert result is None
        assert boundary_events == []
        mock_repo.create_segment.assert_not_called()

    def test_seal_segment_infers_unsealed_message_range(self, in_memory_db):
        from src.business.brain.segment_service import SegmentService
        from src.data.models_sqlite import Message
        from src.data.repositories import MessageRepository

        session_id = "sess-infer"
        msg_repo = MessageRepository()
        msg_repo.create(
            Message(
                message_id="msg-1", session_id=session_id, sequence=1, role="user", content="第一条"
            )
        )
        msg_repo.create(
            Message(
                message_id="msg-2",
                session_id=session_id,
                sequence=2,
                role="assistant",
                content="回复",
            )
        )

        service = SegmentService()
        first_segment_id = service.seal_segment(
            session_id=session_id, boundary_reason=BoundaryReason.IDLE.value
        )
        assert first_segment_id is not None

        repo = service._get_repo()
        first_segment = repo.get_segment_by_id(first_segment_id)
        assert first_segment.message_id_start == "msg-1"
        assert first_segment.message_id_end == "msg-2"

        assert (
            service.seal_segment(session_id=session_id, boundary_reason=BoundaryReason.IDLE.value)
            is None
        )

        msg_repo.create(
            Message(
                message_id="msg-3", session_id=session_id, sequence=3, role="user", content="追加"
            )
        )
        second_segment_id = service.seal_segment(
            session_id=session_id, boundary_reason=BoundaryReason.IDLE.value
        )

        second_segment = repo.get_segment_by_id(second_segment_id)
        assert second_segment.message_id_start == "msg-3"
        assert second_segment.message_id_end == "msg-3"


# ═══════════════════════════════════════════════
# T024: 委托事件不触发 Segment 封存
# ═══════════════════════════════════════════════


class TestDelegationEventsDoNotSealSegments:
    """回归测试：委托事件不应触发 Segment 边界。"""

    def test_delegation_event_does_not_trigger_boundary(self):
        """发送委托相关事件不应产生 segment_boundary_triggered。"""
        boundary_events = []

        def on_boundary(sender, **kwargs):
            boundary_events.append(kwargs)

        connect("segment_boundary_triggered", on_boundary, weak=False)

        # 模拟一些非边界事件
        emit("agent_needs_user_input", session_id="sess-1")
        emit("code_completed", session_id="sess-1")
        emit("tool_saved", tool_id="tool-1")

        assert len(boundary_events) == 0

    def test_specialist_delegation_does_not_seal_segment(self):
        """专员委托操作不应触发 Segment 封存。"""
        from src.business.brain.segment_service import SegmentService

        mock_repo = MagicMock()
        service = SegmentService()
        service._repo = mock_repo
        service._infer_message_range = MagicMock(return_value=("msg-1", "msg-2"))

        boundary_events = []

        def on_boundary(sender, **kwargs):
            boundary_events.append(kwargs)

        connect("segment_boundary_triggered", on_boundary, weak=False)

        # 模拟专员委托事件（不应触发封存）
        emit("brain_specialist_changed", specialist_id="spec-1")

        assert len(boundary_events) == 0
        mock_repo.create_segment.assert_not_called()

    def test_brain_zone_changed_does_not_seal_segment(self):
        """分区变更事件不应触发 Segment 封存。"""
        boundary_events = []

        def on_boundary(sender, **kwargs):
            boundary_events.append(kwargs)

        connect("segment_boundary_triggered", on_boundary, weak=False)

        emit("brain_zone_changed", zone="hot", entry_id="e-1")

        assert len(boundary_events) == 0

    def test_only_explicit_boundaries_trigger_seal(self):
        """只有显式调用 seal_segment 才产生边界事件。"""
        from src.business.brain.segment_service import SegmentService

        mock_repo = MagicMock()
        mock_segment = MagicMock()
        mock_segment.segment_id = "seg-1"
        mock_repo.create_segment.return_value = mock_segment

        service = SegmentService()
        service._repo = mock_repo
        service._infer_message_range = MagicMock(return_value=("msg-1", "msg-2"))

        boundary_events = []

        def on_boundary(sender, **kwargs):
            boundary_events.append(kwargs)

        connect("segment_boundary_triggered", on_boundary, weak=False)

        # 先发送一些无关事件
        emit("brain_zone_changed", zone="hot")
        emit("brain_specialist_changed", specialist_id="spec-1")
        emit("settings_changed", key="brain.segment.idle_threshold_seconds")

        assert len(boundary_events) == 0

        # 显式封存
        service.seal_segment(session_id="sess-1", boundary_reason="idle")

        assert len(boundary_events) == 1
        assert boundary_events[0]["reason"] == "idle"
