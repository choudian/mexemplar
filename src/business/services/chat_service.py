"""
ChatService — 助理聊天业务服务

封装 ChatWidget 所需的全部数据读写操作，UI 层不再直接访问 Repository。
"""

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from src.business.agents.config import AgentType
from src.data.models_sqlite import Message, Session
from src.data.repositories import AssistantProfileRepository, MessageRepository, SessionRepository
from src.utils.timezone import format_local

logger = logging.getLogger(__name__)


@dataclass
class DisplayChatMessage:
    sequence: int
    role: str
    content: str
    created_at: Optional[datetime] = None


@dataclass
class ChatHistoryPage:
    messages: list[DisplayChatMessage] = field(default_factory=list)
    has_more_before: bool = False
    next_before_sequence: Optional[int] = None


class ChatService:
    """助理聊天服务：会话管理 + 消息查询 + 用户档案"""

    # ------------------------------------------------------------------
    # 会话列表
    # ------------------------------------------------------------------

    def get_sessions_with_preview(self, limit: int = 200) -> list[dict]:
        """
        读取 assistant 会话列表，并附上标题和预览文本。

        Returns:
            list of dicts with keys:
                session_id, title, preview, date, date_str
        """
        session_repo = SessionRepository()
        msg_repo = MessageRepository()
        sessions = session_repo.get_by_agent_type(AgentType.ASSISTANT, limit=limit)

        result = []
        for s in sessions:
            messages = msg_repo.get_context(s.session_id)
            first_user_msg = next(
                (m.content for m in messages if m.role == "user" and m.content),
                "",
            )
            result.append(
                {
                    "session_id": s.session_id,
                    "title": first_user_msg[:50] if first_user_msg else "新对话",
                    "preview": first_user_msg[:120] if first_user_msg else "",
                    "date": s.created_at,
                    "date_str": format_local(s.created_at),
                }
            )
        return result

    # ------------------------------------------------------------------
    # 消息历史
    # ------------------------------------------------------------------

    def get_session_messages(self, session_id: str) -> list[Message]:
        """返回会话的非归档消息列表（供 UI 渲染历史记录）"""
        return MessageRepository().get_context(session_id)

    def get_display_messages(
        self,
        session_id: str,
        limit: int = 10,
        before_sequence: Optional[int] = None,
    ) -> ChatHistoryPage:
        """返回用户可见的展示消息分页，不含内部状态字段。"""
        repo = MessageRepository()
        rows = repo.get_display_page(session_id, limit=limit, before_sequence=before_sequence)

        if before_sequence is not None:
            has_more = repo.has_more_before(session_id, before_sequence=before_sequence)
        else:
            oldest_seq = rows[0].sequence if rows else 0
            has_more = repo.has_more_before(session_id, before_sequence=oldest_seq) if rows else False

        messages = [
            DisplayChatMessage(
                sequence=m.sequence,
                role=m.role,
                content=m.content,
                created_at=m.created_at,
            )
            for m in rows
        ]

        return ChatHistoryPage(
            messages=messages,
            has_more_before=has_more,
            next_before_sequence=messages[0].sequence if messages else None,
        )

    # ------------------------------------------------------------------
    # 用户档案
    # ------------------------------------------------------------------

    def get_display_name(self) -> str:
        """从用户偏好档案读取称呼，无档案时返回空字符串"""
        try:
            profile = AssistantProfileRepository().get_default()
            return profile.display_name if profile and profile.display_name else ""
        except Exception:
            return ""

    # ------------------------------------------------------------------
    # 会话创建
    # ------------------------------------------------------------------

    @staticmethod
    def generate_session_id() -> str:
        return f"ast_{uuid.uuid4().hex[:12]}"

    def create_session(self, tool_ids: Optional[list] = None) -> str:
        """
        创建一个新的 assistant 会话。

        Args:
            tool_ids: 限定可用工具 ID 列表；None 表示全部工具。

        Returns:
            新会话的 session_id。
        """
        session_id = self.generate_session_id()
        tool_ids_str = json.dumps(tool_ids) if tool_ids is not None else None
        SessionRepository().create(
            Session(
                session_id=session_id,
                workflow_id=None,
                agent_type=AgentType.ASSISTANT,
                status="active",
                tool_ids=tool_ids_str,
            )
        )
        logger.info(f"创建助理会话: {session_id}, tool_ids={tool_ids}")
        return session_id
