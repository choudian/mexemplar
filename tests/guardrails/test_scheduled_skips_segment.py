"""Guard: scheduled 会话不参与 brain Segment 沉淀（CC-006, 033）。

周期任务大量重复会话会污染大脑记忆与招募信号；segment_service.seal_segment 对
is_scheduled=1 的会话单点 early-return None。
"""

from __future__ import annotations

from src.business.agents.config import AgentType
from src.business.brain.segment_service import SegmentService
from src.data.models_sqlite import Session
from src.data.repositories import SessionRepository
from tests.data.chat_history_test_helpers import seed_message


def _create_session(source: str, session_id: str) -> str:
    SessionRepository().create(
        Session(
            session_id=session_id,
            workflow_id=None,
            agent_type=AgentType.ASSISTANT,
            status="active",
            source=source,
            scheduled_task_id=f"sch_for_{session_id}" if source == "scheduled" else None,
            is_scheduled=1 if source == "scheduled" else 0,
        )
    )
    return session_id


def test_scheduled_session_skips_segment_even_with_messages():
    """scheduled 会话即使有消息也 early-return None（CC-006 opt-out）。"""
    sid = _create_session("scheduled", "ast_sch_seg")
    seed_message(sid, sequence=1, role="user", content="run job")
    seed_message(sid, sequence=2, role="assistant", content="done")

    assert SegmentService().seal_segment(sid, boundary_reason="idle") is None


def test_user_session_not_subject_to_scheduled_optout():
    """user 会话不被 scheduled opt-out 拦截——有消息时正常封存（返回 segment_id）。"""
    sid = _create_session("user", "ast_user_seg")
    seed_message(sid, sequence=1, role="user", content="hi")
    seed_message(sid, sequence=2, role="assistant", content="hello")

    result = SegmentService().seal_segment(sid, boundary_reason="idle")
    assert result is not None  # user 会话正常进入封存流程
