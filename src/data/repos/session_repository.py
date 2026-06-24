"""
SessionRepository -- 会话 Repository
"""

import logging
from datetime import datetime
from typing import List, Optional

from ..models_sqlite import Session
from .base_repository import BaseRepository
from src.data.helpers import build_like_pattern

logger = logging.getLogger(__name__)

SESSION_STATUSES = frozenset({"active", "suspended", "completed", "failed", "archived"})


class SessionRepository(BaseRepository):
    """会话 Repository"""

    def create(self, model: Session) -> Session:
        """创建会话"""
        if model.status not in SESSION_STATUSES:
            raise ValueError(f"invalid session status: {model.status}")
        try:
            self.session.add(model)
            self.session.commit()
            self.session.refresh(model)
            logger.info(f"会话已创建: {model.session_id}")
            return model
        except Exception as e:
            self.session.rollback()
            logger.error(f"创建会话失败: {e}")
            raise

    def get_by_id(self, session_id: str) -> Optional[Session]:
        """根据 ID 获取会话"""
        return self.session.query(Session).filter(Session.session_id == session_id).first()

    def get_by_ids(self, session_ids: List[str]) -> List[Session]:
        """批量按 ID 获取会话（无序，调用方按需索引），避免逐条 N 次查询。"""
        if not session_ids:
            return []
        return self.session.query(Session).filter(Session.session_id.in_(session_ids)).all()

    def list_ids_by_prefix(
        self,
        prefix: str,
        *,
        agent_type: Optional[str] = None,
        limit: int = 10,
    ) -> List[str]:
        """Return session ids whose id starts with prefix.

        This keeps prefix ownership checks inside the repository boundary instead
        of making orchestration code reach into SQLAlchemy models directly.
        """
        prefix = str(prefix or "")
        if not prefix:
            return []
        pattern = build_like_pattern(prefix, contains=False)
        query = self.session.query(Session.session_id).filter(
            Session.session_id.like(pattern, escape="\\")
        )
        if agent_type:
            query = query.filter(Session.agent_type == agent_type)
        rows = query.order_by(Session.created_at.asc()).limit(max(1, int(limit))).all()
        return [row[0] for row in rows]

    def get_by_workflow(
        self,
        workflow_id: str,
        agent_type: Optional[str] = None,
        order_by: Optional[str] = None,
    ) -> List[Session]:
        """获取指定工作流的所有会话"""
        query = self.session.query(Session).filter(Session.workflow_id == workflow_id)
        if agent_type:
            query = query.filter(Session.agent_type == agent_type)
        if order_by == "created_at_desc":
            query = query.order_by(Session.created_at.desc())
        else:
            query = query.order_by(Session.created_at)
        return query.all()

    def update_status(self, session_id: str, status: str):
        """更新会话状态"""
        if status not in SESSION_STATUSES:
            raise ValueError(f"invalid session status: {status}")
        model = self.session.query(Session).filter(Session.session_id == session_id).first()
        if model:
            model.status = status
            model.updated_at = datetime.now()
            self.session.commit()
            logger.debug(f"会话 {session_id} 状态更新为 {status}")

    def update_title(self, session_id: str, title: str) -> Optional[Session]:
        """更新会话标题。"""
        model = self.session.query(Session).filter(Session.session_id == session_id).first()
        if not model:
            return None
        model.title = title
        model.updated_at = datetime.now()
        self.session.commit()
        self.session.refresh(model)
        logger.debug("会话 %s 标题已更新", session_id)
        return model

    def get_status(self, session_id: str) -> Optional[str]:
        """获取会话状态"""
        model = self.get_by_id(session_id)
        return model.status if model else None

    def get_by_agent_type(
        self,
        agent_type: str,
        limit: int = 50,
        statuses: Optional[list[str]] = None,
    ) -> List[Session]:
        """获取指定 agent_type 的会话列表，按最近更新排序"""
        query = self.session.query(Session).filter(Session.agent_type == agent_type)
        if statuses is not None:
            query = query.filter(Session.status.in_(statuses))
        return query.order_by(Session.updated_at.desc()).limit(limit).all()
