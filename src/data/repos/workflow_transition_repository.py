"""
WorkflowTransitionRepository -- 工作流交接 Repository
"""

import logging
from typing import List, Optional

from ..models_sqlite import WorkflowTransition
from .base_repository import BaseRepository

logger = logging.getLogger(__name__)


class WorkflowTransitionRepository(BaseRepository):
    """工作流交接 Repository"""

    def create(self, model: WorkflowTransition) -> WorkflowTransition:
        """创建交接记录"""
        try:
            self.session.add(model)
            self.session.commit()
            self.session.refresh(model)
            logger.debug(f"交接记录已创建: {model.transition_id}")
            return model
        except Exception as e:
            self.session.rollback()
            logger.error(f"创建交接记录失败: {e}")
            raise

    def get_by_id(self, transition_id: str) -> Optional[WorkflowTransition]:
        """根据 ID 获取交接记录"""
        return (
            self.session.query(WorkflowTransition)
            .filter(WorkflowTransition.transition_id == transition_id)
            .first()
        )

    def get_by_workflow(self, workflow_id: str) -> List[WorkflowTransition]:
        """获取指定工作流的所有交接记录"""
        return (
            self.session.query(WorkflowTransition)
            .filter(WorkflowTransition.workflow_id == workflow_id)
            .order_by(WorkflowTransition.created_at)
            .all()
        )

    def get_latest_by_workflow_and_event(
        self,
        workflow_id: str,
        event_type: str,
    ) -> Optional[WorkflowTransition]:
        """按 workflow_id 和 event_type 取最近一条交接记录"""
        return (
            self.session.query(WorkflowTransition)
            .filter(
                WorkflowTransition.workflow_id == workflow_id,
                WorkflowTransition.event_type == event_type,
            )
            .order_by(WorkflowTransition.created_at.desc())
            .first()
        )
