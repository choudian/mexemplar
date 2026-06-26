"""
TeachingFailureRepository -- 技能教学失败记录仓库
"""

import logging
from typing import List, Optional
import uuid

from ..models_sqlite import TeachingFailureRecord
from .base_repository import BaseRepository

logger = logging.getLogger(__name__)


class TeachingFailureRepository(BaseRepository):
    """技能教学失败记录仓库"""

    def create(self, record: TeachingFailureRecord) -> TeachingFailureRecord:
        try:
            self.session.add(record)
            self.session.commit()
            self.session.refresh(record)
            logger.info(f"失败记录已创建: {record.workflow_id}")
            return record
        except Exception as e:
            self.session.rollback()
            logger.error(f"创建失败记录失败: {e}")
            raise

    def get_by_id(self, record_id: str) -> Optional[TeachingFailureRecord]:
        return (
            self.session.query(TeachingFailureRecord)
            .filter(TeachingFailureRecord.record_id == record_id)
            .first()
        )

    def get_by_workflow_id(self, workflow_id: str) -> Optional[TeachingFailureRecord]:
        return (
            self.session.query(TeachingFailureRecord)
            .filter(TeachingFailureRecord.workflow_id == workflow_id)
            .first()
        )

    def update(self, record: TeachingFailureRecord) -> TeachingFailureRecord:
        try:
            self.session.commit()
            self.session.refresh(record)
            return record
        except Exception as e:
            self.session.rollback()
            logger.error(f"更新失败记录失败: {e}")
            raise

    def get_active_failures(self) -> List[TeachingFailureRecord]:
        """返回所有 active / retrying 状态的记录，按 updated_at DESC 排序"""
        return (
            self.session.query(TeachingFailureRecord)
            .filter(TeachingFailureRecord.status.in_(["active", "retrying"]))
            .order_by(TeachingFailureRecord.updated_at.desc())
            .all()
        )

    def upsert_by_workflow(
        self,
        workflow_id: str,
        failed_stage: str,
        error_summary: str,
        error_type: str,
        tool_name: Optional[str] = None,
    ) -> bool:
        """
        按 workflow_id upsert 失败记录。

        Returns:
            True = 新建，False = 更新或终态跳过
        """
        existing = self.get_by_workflow_id(workflow_id)

        # 终态保护
        if existing and existing.status in ("resolved", "dismissed"):
            return False

        if not existing:
            record = TeachingFailureRecord(
                record_id=str(uuid.uuid4()),
                workflow_id=workflow_id,
                tool_name=tool_name,
                failed_stage=failed_stage,
                error_summary=error_summary,
                error_type=error_type,
                status="active",
                retry_count=1,
            )
            self.create(record)
            return True

        # 更新已有记录
        existing.failed_stage = failed_stage
        existing.error_summary = error_summary
        existing.error_type = error_type
        existing.status = "active"
        existing.retry_count = (existing.retry_count or 0) + 1
        if tool_name is not None:
            existing.tool_name = tool_name
        self.session.commit()
        return False
