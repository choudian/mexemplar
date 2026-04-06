"""
ToolSuggestionRepository -- 工具化建议历史仓库（重复模式检测）
"""

import logging
from typing import Optional

from ..models_sqlite import ToolSuggestionHistory
from .base_repository import BaseRepository

logger = logging.getLogger(__name__)


class ToolSuggestionRepository(BaseRepository):
    """工具化建议历史仓库（重复模式检测）"""

    def get_by_pattern(self, task_pattern: str) -> Optional[ToolSuggestionHistory]:
        """按任务模式查询"""
        return (
            self.session.query(ToolSuggestionHistory)
            .filter(ToolSuggestionHistory.task_pattern == task_pattern)
            .first()
        )

    def create(self, task_pattern: str) -> ToolSuggestionHistory:
        """创建新的建议历史记录"""
        import uuid as _uuid

        record = ToolSuggestionHistory(
            suggestion_id=str(_uuid.uuid4()),
            task_pattern=task_pattern,
            times_seen=1,
        )
        try:
            self.session.add(record)
            self.session.commit()
            self.session.refresh(record)
            return record
        except Exception:
            self.session.rollback()
            raise

    def increment(self, record: ToolSuggestionHistory):
        """执行次数 +1"""
        record.times_seen += 1
        self.session.commit()

    def mark_rejected(self, record: ToolSuggestionHistory):
        """记录拒绝状态，重置次数进入冷却"""
        record.accepted = False
        record.times_seen = 0
        self.session.commit()

    def reset_accepted(self, record: ToolSuggestionHistory):
        """冷却期结束，重置拒绝状态"""
        record.accepted = None
        self.session.commit()
