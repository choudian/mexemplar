"""
MessageRepository -- 消息 Repository
"""

import logging
from typing import List, Optional

from sqlalchemy import and_, func

from ..models_sqlite import Message
from .base_repository import BaseRepository

logger = logging.getLogger(__name__)


class MessageRepository(BaseRepository):
    """消息 Repository"""

    def create(self, model: Message) -> Message:
        """创建消息"""
        try:
            self.session.add(model)
            self.session.commit()
            self.session.refresh(model)
            logger.debug(f"消息已创建: {model.message_id}")
            return model
        except Exception as e:
            self.session.rollback()
            logger.error(f"创建消息失败: {e}")
            raise

    def get_by_id(self, message_id: str) -> Optional[Message]:
        """根据 ID 获取消息"""
        return self.session.query(Message).filter(Message.message_id == message_id).first()

    def get_first(self, session_id: str) -> Optional[Message]:
        """获取会话的第一条消息（最小序列号）"""
        return (
            self.session.query(Message)
            .filter(Message.session_id == session_id)
            .order_by(Message.sequence.asc())
            .first()
        )

    def get_last(self, session_id: str, non_archived: bool = True) -> Optional[Message]:
        """获取会话的最后一条消息（最大序列号）"""
        query = self.session.query(Message).filter(Message.session_id == session_id)
        if non_archived:
            query = query.filter(Message.is_archived.is_(False))
        return query.order_by(Message.sequence.desc()).first()

    def get_first_user_message(self, session_id: str) -> str:
        """返回会话中第一条非空 user 消息的 content，不存在时返回空字符串。"""
        row = (
            self.session.query(Message.content)
            .filter(
                Message.session_id == session_id,
                Message.role == "user",
                Message.content != "",
                Message.content.isnot(None),
            )
            .order_by(Message.sequence.asc())
            .limit(1)
            .first()
        )
        return row[0] if row else ""

    def get_first_user_messages(self, session_ids: list[str]) -> dict[str, str]:
        """批量返回多个会话中第一条非空 user 消息的 content。"""
        if not session_ids:
            return {}
        sub = (
            self.session.query(
                Message.session_id,
                func.min(Message.sequence).label("min_seq"),
            )
            .filter(
                Message.session_id.in_(session_ids),
                Message.role == "user",
                Message.content != "",
                Message.content.isnot(None),
            )
            .group_by(Message.session_id)
            .subquery()
        )
        rows = (
            self.session.query(Message.session_id, Message.content)
            .join(
                sub,
                and_(
                    Message.session_id == sub.c.session_id,
                    Message.sequence == sub.c.min_seq,
                ),
            )
            .all()
        )
        result: dict[str, str] = {sid: "" for sid in session_ids}
        for sid, content in rows:
            result[sid] = content
        return result

    def get_context(self, session_id: str) -> List[Message]:
        """获取会话上下文（非归档消息，按序列排序）"""
        return (
            self.session.query(Message)
            .filter(and_(Message.session_id == session_id, Message.is_archived.is_(False)))
            .order_by(Message.sequence)
            .all()
        )

    def get_all(self, session_id: str) -> List[Message]:
        """获取会话的所有消息"""
        return (
            self.session.query(Message)
            .filter(Message.session_id == session_id)
            .order_by(Message.sequence)
            .all()
        )

    # 别名：外部模块（chat_widget, assistant_memory, assistant_tools）统一使用此名称
    get_by_session = get_all

    def get_next_sequence(self, session_id: str) -> int:
        """获取下一条消息的序列号"""
        max_seq = (
            self.session.query(func.max(Message.sequence))
            .filter(Message.session_id == session_id)
            .scalar()
        )
        return (max_seq or 0) + 1

    def mark_archived(self, session_id: str, from_seq: int, to_seq: int):
        """归档指定范围的消息"""
        self.session.query(Message).filter(
            and_(
                Message.session_id == session_id,
                Message.sequence >= from_seq,
                Message.sequence <= to_seq,
            )
        ).update({"is_archived": True}, synchronize_session=False)
        self.session.commit()
        logger.debug(f"会话 {session_id} 消息 {from_seq}-{to_seq} 已归档")

    def update_content(self, message_id: str, content: str):
        """更新消息内容"""
        msg = self.get_by_id(message_id)
        if msg:
            msg.content = content
            self.session.commit()

    def _display_filter(self, query):
        return query.filter(
            and_(
                Message.role.in_(["user", "assistant"]),
                Message.content != "",
                Message.content.isnot(None),
                Message.message_type != "compressed",
            ),
        )

    def get_display_page(
        self,
        session_id: str,
        limit: int = 10,
        before_sequence: Optional[int] = None,
    ) -> List[Message]:
        if limit <= 0:
            raise ValueError(f"limit must be positive, got {limit}")

        sub = self.session.query(Message).filter(Message.session_id == session_id)
        sub = self._display_filter(sub)

        if before_sequence is not None:
            sub = sub.filter(Message.sequence < before_sequence)

        sub = sub.order_by(Message.sequence.desc()).limit(limit)

        return list(reversed(sub.all()))

    def get_display_after(self, session_id: str, after_sequence: int = 0) -> List[Message]:
        query = self.session.query(Message).filter(
            Message.session_id == session_id,
            Message.sequence > after_sequence,
        )
        query = self._display_filter(query)
        return query.order_by(Message.sequence.asc()).all()

    def has_more_before(self, session_id: str, before_sequence: int) -> bool:
        exists = (
            self.session.query(Message.message_id)
            .filter(Message.session_id == session_id)
            .filter(Message.sequence < before_sequence)
        )
        exists = self._display_filter(exists)
        return exists.first() is not None

    def get_max_display_sequence(self, session_id: str) -> int:
        """返回会话中展示消息的最大 sequence，无展示消息时返回 0。"""
        row = self.session.query(func.max(Message.sequence)).filter(
            Message.session_id == session_id,
        )
        row = self._display_filter(row)
        return row.scalar() or 0
