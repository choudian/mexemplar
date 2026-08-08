"""
SessionRepository -- 会话 Repository
"""

import logging
from datetime import datetime

from src.utils.timezone import utc_now_naive
from typing import List, Optional

from src.data.scheduling_types import SessionSource

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
            source = SessionSource(model.source or SessionSource.USER)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid session source") from exc
        task_id = (
            (model.scheduled_task_id or "").strip() if model.scheduled_task_id is not None else None
        )
        if source is SessionSource.SCHEDULED:
            if not task_id:
                raise ValueError("scheduled sessions require scheduled_task_id")
            if model.is_scheduled not in (None, 1, True):
                raise ValueError("scheduled sessions require is_scheduled=1")
            model.scheduled_task_id = task_id
            model.is_scheduled = 1
        else:
            if model.scheduled_task_id is not None:
                raise ValueError("user sessions must not have scheduled_task_id")
            if model.is_scheduled not in (None, 0, False):
                raise ValueError("user sessions require is_scheduled=0")
            model.scheduled_task_id = None
            model.is_scheduled = 0
        model.source = str(source)
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

    def clear_all_active(self) -> int:
        """断电恢复：把所有 ``status='active'`` 的会话一次性翻成 ``suspended``。

        sidecar 重启后，上一代进程的执行体线程物理全死——任何 ``active`` 会话都是假的
        （执行体没走到正常出口，``update_session_status`` 一次没调用）。包括子代理 executor
        会话**和**主助理根会话（后者不挂在任何 attempt 的 ``executor_session_id`` 上，按 attempt
        绑定来清会漏掉它）。重启后没有任何执行体活着，所以所有 active 一律是假，一刀切最稳；
        用户下次发消息时 ``AgentLoop`` 会把 ``suspended`` 复活回 ``active``。

        返回受影响行数。幂等：无 active 行时返回 0。
        """
        from sqlalchemy import update

        now = datetime.now()
        result = self.session.execute(
            update(Session)
            .where(Session.status == "active")
            .values(status="suspended", updated_at=now)
        )
        self._commit()
        return result.rowcount or 0

    def get_by_agent_type(
        self,
        agent_type: str,
        limit: int = 50,
        statuses: Optional[list[str]] = None,
        exclude_sources: Optional[list[str]] = None,
    ) -> List[Session]:
        """获取指定 agent_type 的会话列表，按最近更新排序。

        ``exclude_sources``（033 调度中心）：排除指定来源的会话，聊天屏列表用
        ``exclude_sources=["scheduled"]`` 隔离定时任务会话（FR-021）。
        """
        query = self.session.query(Session).filter(Session.agent_type == agent_type)
        if statuses is not None:
            query = query.filter(Session.status.in_(statuses))
        if exclude_sources:
            query = query.filter(~Session.source.in_(exclude_sources))
        return query.order_by(Session.updated_at.desc()).limit(limit).all()
