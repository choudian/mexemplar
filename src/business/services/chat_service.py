"""
ChatService — 助理聊天业务服务

封装 AssistantScreen / desktop API 所需的全部聊天数据读写操作，UI 层不再直接访问 Repository。
"""

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from src.business.agents.config import AgentType
from src.business.agents.tools.builtin_general_tools import (
    CONFIRM_SOURCE_NEW_CHAT_RESET,
    reset_auto_approve,
    settle_pending_confirmations,
)
from src.data.models_sqlite import Session
from src.data.repositories import AssistantProfileRepository, MessageRepository, SessionRepository
from src.utils.timezone import format_local

logger = logging.getLogger(__name__)

_VISIBLE_SESSION_STATUSES = ("active", "suspended", "completed", "failed")


@dataclass
class DisplayChatMessage:
    sequence: int
    role: str
    content: str
    created_at: datetime | None = None


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

    def get_sessions_with_preview(
        self,
        limit: int = 200,
        query: str = "",
        include_archived: bool = False,
    ) -> list[dict]:
        """
        读取 assistant 会话列表，并附上标题和预览文本。

        Returns:
            list of dicts with keys:
                session_id, title, preview, date, date_str
        """
        session_repo = SessionRepository()
        msg_repo = MessageRepository()
        statuses = None if include_archived else list(_VISIBLE_SESSION_STATUSES)
        sessions = session_repo.get_by_agent_type(
            AgentType.ASSISTANT,
            limit=limit,
            statuses=statuses,
        )

        result = []
        query_text = query.strip().lower()
        first_messages = msg_repo.get_first_user_messages([s.session_id for s in sessions])
        for s in sessions:
            first_user_msg = first_messages.get(s.session_id, "")
            item = self._build_session_preview(s, first_user_msg)
            if (
                query_text
                and query_text not in item["title"].lower()
                and query_text not in item["preview"].lower()
            ):
                continue
            result.append(item)
        return result

    def rename_session(self, session_id: str, title: str) -> dict:
        """重命名 assistant 会话并返回新的展示 DTO。"""
        title = self._normalize_title(title)
        if not title:
            raise ValueError("title must not be empty")

        repo = SessionRepository()
        session = repo.get_by_id(session_id)
        if session is None or session.agent_type != AgentType.ASSISTANT:
            raise KeyError(session_id)
        repo.update_title(session_id, title)
        return self.get_session_preview(session_id)

    def archive_session(self, session_id: str) -> bool:
        """按业务语义归档 assistant 会话，保留本地历史数据。"""
        repo = SessionRepository()
        session = repo.get_by_id(session_id)
        if session is None or session.agent_type != AgentType.ASSISTANT:
            return False
        repo.update_status(session_id, "archived")
        return True

    def get_session_preview(self, session_id: str) -> dict:
        """返回单个会话展示 DTO。"""
        session = SessionRepository().get_by_id(session_id)
        if session is None or session.agent_type != AgentType.ASSISTANT:
            raise KeyError(session_id)

        first_user_msg = MessageRepository().get_first_user_message(session_id)
        return self._build_session_preview(session, first_user_msg)

    # ------------------------------------------------------------------
    # 消息历史
    # ------------------------------------------------------------------

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
            has_more = (
                repo.has_more_before(session_id, before_sequence=oldest_seq) if rows else False
            )

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

    def get_display_messages_after(
        self, session_id: str, after_sequence: int = 0
    ) -> list[DisplayChatMessage]:
        """返回指定 sequence 之后新增的用户可见消息。"""
        rows = MessageRepository().get_display_after(session_id, after_sequence=after_sequence)
        return [
            DisplayChatMessage(
                sequence=m.sequence,
                role=m.role,
                content=m.content or "",
                created_at=m.created_at,
            )
            for m in rows
        ]

    def get_latest_display_sequence(self, session_id: str) -> int:
        """返回当前最新展示消息 sequence，无展示消息时返回 0。"""
        return MessageRepository().get_max_display_sequence(session_id)

    # ------------------------------------------------------------------
    # 用户档案
    # ------------------------------------------------------------------

    def get_display_name(self) -> str:
        """从用户偏好档案读取称呼，无档案时返回空字符串"""
        try:
            profile = AssistantProfileRepository().get_default()
            return profile.display_name if profile and profile.display_name else ""
        except Exception as exc:
            logger.warning("读取用户显示名称失败: %s", exc, exc_info=True)
            return ""

    # ------------------------------------------------------------------
    # 会话创建
    # ------------------------------------------------------------------

    @staticmethod
    def generate_session_id() -> str:
        return f"ast_{uuid.uuid4().hex[:12]}"

    def create_session(self, tool_ids: Optional[list] = None, title: Optional[str] = None) -> str:
        """
        创建一个新的 assistant 会话。

        Args:
            tool_ids: 限定可用工具 ID 列表；None 表示全部工具。

        Returns:
            新会话的 session_id。
        """
        session_id = self.generate_session_id()
        tool_ids_str = json.dumps(tool_ids) if tool_ids is not None else None
        reset_cutoff = time.monotonic()
        normalized_title = self._normalize_title(title) if title is not None else None
        if title is not None and not normalized_title:
            raise ValueError("title must not be empty")
        reset_auto_approve(CONFIRM_SOURCE_NEW_CHAT_RESET)
        settle_pending_confirmations(
            False,
            CONFIRM_SOURCE_NEW_CHAT_RESET,
            created_before=reset_cutoff,
        )
        SessionRepository().create(
            Session(
                session_id=session_id,
                workflow_id=None,
                agent_type=AgentType.ASSISTANT,
                status="active",
                title=normalized_title,
                tool_ids=tool_ids_str,
            )
        )
        logger.info(f"创建助理会话: {session_id}, tool_ids={tool_ids}")
        return session_id

    @staticmethod
    def _normalize_title(title: str) -> str:
        normalized = " ".join(title.split())
        if len(normalized) > 120:
            raise ValueError("title must be 120 characters or fewer")
        return normalized

    @staticmethod
    def _build_session_preview(session: Session, first_user_msg: str) -> dict:
        title = (session.title or "").strip() or (
            first_user_msg[:50] if first_user_msg else "新对话"
        )
        return {
            "session_id": session.session_id,
            "title": title,
            "preview": first_user_msg[:120] if first_user_msg else "",
            "status": session.status,
            "date": session.created_at,
            "updated_at": session.updated_at,
            "date_str": format_local(session.created_at),
        }
