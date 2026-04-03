"""
TrialManager - 试用管理器

负责管理待试用工具的生命周期和试用流程
"""

import logging
from typing import Dict, Any, Optional
from datetime import datetime

from src.data.database import DatabaseManager
from src.business.tool_trial.trial_models import (
    PendingToolStatus,
    ToolTrial,
    TrialStatus,
)
from src.business.tool_trial.trial_repository import (
    PendingToolRepository,
    ToolTrialRepository,
)

logger = logging.getLogger(__name__)


class TrialManager:
    """
    试用管理器

    负责管理待试用工具的创建、试用、提升等完整生命周期
    """

    def __init__(self, db_manager: DatabaseManager):
        """
        初始化试用管理器

        Args:
            db_manager: 数据库管理器（用于 Intent、PendingTool 等模块）
        """
        self.db_manager = db_manager
        self.pending_tool_repo = PendingToolRepository(db_manager)
        self.tool_trial_repo = ToolTrialRepository(db_manager)

    # ===== Trial 管理 =====

    def start_trial(
        self, pending_tool_id: str, trial_data: Dict[str, Any]
    ) -> ToolTrial:
        """
        开始试用

        Args:
            pending_tool_id: 待试用工具 ID
            trial_data: 试用数据

        Returns:
            创建的试用记录

        Raises:
            ValueError: 如果 pending_tool_id 无效
        """
        # 获取待试用工具
        pending_tool = self.pending_tool_repo.get_by_id(pending_tool_id)
        if not pending_tool:
            raise ValueError(f"Pending tool not found: {pending_tool_id}")

        # 检查是否可以试用
        if not pending_tool.can_trial():
            raise ValueError(
                f"Pending tool cannot be trialed: {pending_tool_id}, "
                f"status: {pending_tool.status}, trials: {pending_tool.trial_count}/{pending_tool.max_trials}"
            )

        # 创建试用记录
        trial = ToolTrial(
            pending_tool_id=pending_tool_id,
            trial_data=trial_data,
            status=TrialStatus.RUNNING,
            started_at=datetime.now(),
        )

        created_trial = self.tool_trial_repo.create(trial)

        # 更新待试用工具状态
        pending_tool.status = PendingToolStatus.TRIALING
        pending_tool.increment_trial_count()
        self.pending_tool_repo.update(pending_tool)

        logger.info(
            f"开始试用: {pending_tool.tool_name} "
            f"(trial {pending_tool.trial_count}/{pending_tool.max_trials})"
        )

        return created_trial

    def handle_trial_result(
        self,
        trial_id: str,
        success: bool,
        result: Optional[Dict[str, Any]] = None,
        error: Optional[str] = None,
        error_type: Optional[str] = None,
    ):
        """
        处理试用结果

        Args:
            trial_id: 试用记录 ID
            success: 是否成功
            result: 成功结果
            error: 错误信息
            error_type: 错误类型
        """
        # 获取试用记录
        trial = self.tool_trial_repo.get_by_id(trial_id)
        if not trial:
            raise ValueError(f"Trial not found: {trial_id}")

        # 更新试用记录
        if success:
            trial.mark_success(result or {})
            # 更新待试用工具状态
            pending_tool = self.pending_tool_repo.get_by_id(trial.pending_tool_id)
            if pending_tool:
                pending_tool.status = PendingToolStatus.TRIAL_SUCCESS
                pending_tool.last_trial_result = "Success"
                self.pending_tool_repo.update(pending_tool)
        else:
            trial.mark_failed(error or "Unknown error", error_type)
            # 更新待试用工具状态
            pending_tool = self.pending_tool_repo.get_by_id(trial.pending_tool_id)
            if pending_tool:
                pending_tool.status = PendingToolStatus.TRIAL_FAILED
                pending_tool.last_error = error
                self.pending_tool_repo.update(pending_tool)

        self.tool_trial_repo.update(trial)

        logger.info(
            f"试用完成: {trial_id}, success={success}, "
            f"status={trial.status}"
        )

    def get_trial(self, trial_id: str) -> Optional[ToolTrial]:
        """
        获取试用记录

        Args:
            trial_id: 试用记录 ID

        Returns:
            试用记录，如果不存在则返回 None
        """
        return self.tool_trial_repo.get_by_id(trial_id)
