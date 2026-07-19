"""
ChatService — 助理聊天业务服务

封装 AssistantScreen / desktop API 所需的全部聊天数据读写操作，UI 层不再直接访问 Repository。
"""

import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional, overload

from src.business.agents.config import AgentType
from src.business.services.assistant_failure_service import (
    AssistantFailureService,
    AssistantFailureSummary,
)
from src.business.services.session_lifecycle import AssistantSessionLifecycle
from src.data.models_sqlite import Session
from src.data.repositories import AssistantProfileRepository, MessageRepository, SessionRepository
from src.data.scheduling_types import SessionSource
from src.utils.timezone import format_local

logger = logging.getLogger(__name__)

_VISIBLE_SESSION_STATUSES = ("active", "suspended", "completed", "failed")


@dataclass
class DisplayChatMessage:
    sequence: int
    role: str
    content: str
    created_at: datetime | None = None
    failure: AssistantFailureSummary | None = None


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
            exclude_sources=["scheduled"],
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
        failures = AssistantFailureService().get_summaries(
            session_id,
            [m.sequence for m in rows if m.role == "user"],
        )

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
                failure=failures.get(m.sequence),
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
        failures = AssistantFailureService().get_summaries(
            session_id,
            [m.sequence for m in rows if m.role == "user"],
        )
        return [
            DisplayChatMessage(
                sequence=m.sequence,
                role=m.role,
                content=m.content or "",
                created_at=m.created_at,
                failure=failures.get(m.sequence),
            )
            for m in rows
        ]

    def get_display_message(
        self,
        session_id: str,
        sequence: int,
    ) -> DisplayChatMessage | None:
        row = MessageRepository().get_by_sequence(session_id, sequence)
        if (
            row is None
            or row.role not in ("user", "assistant")
            or not row.content
            or row.message_type not in ("normal", None)
        ):
            return None
        failures = AssistantFailureService().get_summaries(
            session_id,
            [sequence] if row.role == "user" else [],
        )
        return DisplayChatMessage(
            sequence=row.sequence,
            role=row.role,
            content=row.content,
            created_at=row.created_at,
            failure=failures.get(sequence),
        )

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

    @overload
    def create_session(
        self,
        tool_ids: Optional[list] = None,
        title: Optional[str] = None,
        *,
        source: Literal["user"] = "user",
        scheduled_task_id: None = None,
        session_id: Optional[str] = None,
    ) -> str: ...

    @overload
    def create_session(
        self,
        tool_ids: Optional[list] = None,
        title: Optional[str] = None,
        *,
        source: Literal["scheduled"],
        scheduled_task_id: str,
        session_id: Optional[str] = None,
    ) -> str: ...

    def create_session(
        self,
        tool_ids: Optional[list] = None,
        title: Optional[str] = None,
        *,
        source: str | SessionSource = SessionSource.USER,
        scheduled_task_id: Optional[str] = None,
        session_id: Optional[str] = None,
    ) -> str:
        """
        创建一个新的 assistant 会话。

        Args:
            tool_ids: 限定可用工具 ID 列表；None 表示全部工具。
            source: 会话来源（033）—— ``user``（默认，用户手动开）或 ``scheduled``
                （定时任务触发）。``scheduled`` 会话从聊天屏列表排除、不沉淀 Segment。
            scheduled_task_id: ``source='scheduled'`` 时关联的定时任务 id。
            session_id: 可选预分配 id；调度启动器用它先原子占用 active-run 槽，再创建会话。

        Returns:
            新会话的 session_id。
        """
        model = self._build_session_model(
            tool_ids=tool_ids,
            title=title,
            source=source,
            scheduled_task_id=scheduled_task_id,
            session_id=session_id,
        )
        resolved_source = SessionSource(model.source)
        # 只有用户显式新开聊天才重置进程级确认状态。scheduled 后台会话与正在聊的
        # 用户会话必须严格隔离（033 FR-024 / CC-005），不得清空全局 auto-approve
        # 或 fail-close 用户当前 pending 的高危确认。
        if resolved_source is SessionSource.USER:
            AssistantSessionLifecycle().reset_confirmation_state_for_new_chat()
        SessionRepository().create(model)
        logger.info(
            "创建助理会话: %s, tool_ids=%s, source=%s",
            model.session_id,
            tool_ids,
            resolved_source,
        )
        return model.session_id

    def _build_session_model(
        self,
        *,
        tool_ids: Optional[list],
        title: Optional[str],
        source: str | SessionSource,
        scheduled_task_id: Optional[str],
        session_id: Optional[str],
    ) -> Session:
        """Validate and build a detached assistant session model."""
        try:
            resolved_source = SessionSource(source)
        except (TypeError, ValueError) as exc:
            raise ValueError("source must be 'user' or 'scheduled'") from exc
        normalized_task_id = (
            (scheduled_task_id or "").strip() if scheduled_task_id is not None else None
        )
        if resolved_source is SessionSource.SCHEDULED and not normalized_task_id:
            raise ValueError("scheduled sessions require scheduled_task_id")
        if resolved_source is SessionSource.USER and scheduled_task_id is not None:
            raise ValueError("user sessions must not have scheduled_task_id")

        resolved_session_id = session_id or self.generate_session_id()
        tool_ids_str = json.dumps(tool_ids) if tool_ids is not None else None
        normalized_title = self._normalize_title(title) if title is not None else None
        if title is not None and not normalized_title:
            raise ValueError("title must not be empty")
        return Session(
            session_id=resolved_session_id,
            workflow_id=None,
            agent_type=AgentType.ASSISTANT,
            status="active",
            title=normalized_title,
            tool_ids=tool_ids_str,
            source=str(resolved_source),
            scheduled_task_id=normalized_task_id,
            is_scheduled=1 if resolved_source is SessionSource.SCHEDULED else 0,
        )

    def build_scheduled_session(
        self,
        scheduled_task_id: str,
        tool_ids: Optional[list] = None,
        title: Optional[str] = None,
        *,
        session_id: Optional[str] = None,
    ) -> Session:
        """Build, but do not persist, a relation-complete scheduled session.

        ``SessionLauncher`` hands this model to the run Repository so the session
        and run can be committed atomically.
        """
        return self._build_session_model(
            tool_ids=tool_ids,
            title=title,
            source=SessionSource.SCHEDULED,
            scheduled_task_id=scheduled_task_id,
            session_id=session_id,
        )

    def create_scheduled_session(
        self,
        scheduled_task_id: str,
        tool_ids: Optional[list] = None,
        title: Optional[str] = None,
        *,
        session_id: Optional[str] = None,
    ) -> str:
        """创建关系完整的 scheduled 会话；供调度启动器使用。"""
        return self.create_session(
            tool_ids,
            title,
            source="scheduled",
            scheduled_task_id=scheduled_task_id,
            session_id=session_id,
        )

    def ensure_scheduled_takeover_session(
        self,
        scheduled_task_id: str,
        *,
        session_id: str,
        title: str,
    ) -> bool:
        """Repair a legacy missing scheduled session and report whether draft context is needed.

        Returns ``True`` when the session has no persisted user message, allowing
        the caller to return the task instruction as an editable recovery draft
        without writing a synthetic message ahead of the system prompt.
        """
        session_repo = SessionRepository()
        session = session_repo.get_by_id(session_id)
        if session is None:
            try:
                self.create_scheduled_session(
                    scheduled_task_id,
                    title=title,
                    session_id=session_id,
                )
            except Exception:
                # A concurrent takeover may have won the create race.
                session = session_repo.get_by_id(session_id)
                if session is None:
                    raise
            else:
                session = session_repo.get_by_id(session_id)

        if (
            session is None
            or session.agent_type != AgentType.ASSISTANT
            or SessionSource(session.source) is not SessionSource.SCHEDULED
            or session.scheduled_task_id != scheduled_task_id
            or session.is_scheduled not in (1, True)
        ):
            raise ValueError("scheduled takeover session relationship is invalid")
        if session.status == "archived":
            session_repo.update_status(session_id, "active")
        return not bool(MessageRepository().get_first_user_message(session_id).strip())

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
