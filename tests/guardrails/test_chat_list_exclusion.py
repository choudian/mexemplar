"""Guard: 聊天屏列表排除 source=scheduled 会话（FR-021, 033）。

scheduled 会话只在调度中心历史可见，不混进 AI Assistant 聊天屏列表；其余会话读取
路径（不传 exclude_sources）仍能看到 scheduled 会话。
"""

from __future__ import annotations

from src.business.agents.config import AgentType
from src.business.services.chat_service import ChatService
from src.data.models_sqlite import Session
from src.data.repositories import SessionRepository
from tests.data.chat_history_test_helpers import create_assistant_session


def _create_scheduled_session(session_id: str, scheduled_task_id: str = "sch_x") -> str:
    SessionRepository().create(
        Session(
            session_id=session_id,
            workflow_id=None,
            agent_type=AgentType.ASSISTANT,
            status="active",
            source="scheduled",
            scheduled_task_id=scheduled_task_id,
            is_scheduled=1,
        )
    )
    return session_id


def test_chat_list_excludes_scheduled_sessions():
    user_sid = create_assistant_session()
    sch_sid = _create_scheduled_session("ast_scheduled_1")

    previews = ChatService().get_sessions_with_preview()
    ids = {p["session_id"] for p in previews}

    assert user_sid in ids
    assert sch_sid not in ids  # FR-021: scheduled 不进聊天屏


def test_other_read_paths_still_include_scheduled():
    """非聊天屏的读取路径（不传 exclude_sources）仍能看到 scheduled 会话。"""
    sch_sid = _create_scheduled_session("ast_scheduled_2")

    with SessionRepository() as sr:
        all_sessions = sr.get_by_agent_type(AgentType.ASSISTANT)

    ids = {s.session_id for s in all_sessions}
    assert sch_sid in ids  # exclude_sources 只作用于显式排除的调用
