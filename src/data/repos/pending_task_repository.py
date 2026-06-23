"""
PendingTaskRepository -- legacy 助理异步任务队列仓库。

该仓库继续服务 codify/bugfix 等后台队列；不要把它作为 Assistant Task 图事实源。
"""

import logging
from typing import List, Optional

from ..models_sqlite import PendingAssistantTask
from .base_repository import BaseRepository

logger = logging.getLogger(__name__)


class PendingTaskRepository(BaseRepository):
    """助理异步任务队列仓库"""

    def create(self, task: PendingAssistantTask) -> PendingAssistantTask:
        """创建任务"""
        try:
            self.session.add(task)
            self.session.commit()
            self.session.refresh(task)
            logger.info(f"待处理任务已创建: {task.task_id} ({task.task_type})")
            return task
        except Exception as e:
            self.session.rollback()
            logger.error(f"创建待处理任务失败: {e}")
            raise

    def get_by_id(self, task_id: str) -> Optional[PendingAssistantTask]:
        """根据 ID 获取任务"""
        return (
            self.session.query(PendingAssistantTask)
            .filter(PendingAssistantTask.task_id == task_id)
            .first()
        )

    def get_pending(self, task_type: Optional[str] = None) -> List[PendingAssistantTask]:
        """获取待处理任务"""
        q = self.session.query(PendingAssistantTask).filter(
            PendingAssistantTask.status == "pending"
        )
        if task_type:
            q = q.filter(PendingAssistantTask.task_type == task_type)
        return q.order_by(PendingAssistantTask.created_at).all()

    def update_status(self, task_id: str, status: str):
        """更新任务状态"""
        task = (
            self.session.query(PendingAssistantTask)
            .filter(PendingAssistantTask.task_id == task_id)
            .first()
        )
        if task:
            task.status = status
            self.session.commit()
