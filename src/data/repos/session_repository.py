"""
SessionRepository -- 会话 Repository
"""

import logging
from typing import List, Optional

from ..models_sqlite import Session
from .base_repository import BaseRepository

logger = logging.getLogger(__name__)


class SessionRepository(BaseRepository):
    """会话 Repository"""

    def create(self, model: Session) -> Session:
        """创建会话"""
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
        model = self.session.query(Session).filter(Session.session_id == session_id).first()
        if model:
            model.status = status
            self.session.commit()
            logger.debug(f"会话 {session_id} 状态更新为 {status}")

    def get_status(self, session_id: str) -> Optional[str]:
        """获取会话状态"""
        model = self.get_by_id(session_id)
        return model.status if model else None

    def get_by_agent_type(self, agent_type: str, limit: int = 50) -> List[Session]:
        """获取指定 agent_type 的会话列表，按最近更新排序"""
        return (
            self.session.query(Session)
            .filter(Session.agent_type == agent_type)
            .order_by(Session.updated_at.desc())
            .limit(limit)
            .all()
        )
