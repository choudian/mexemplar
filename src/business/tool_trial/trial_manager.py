"""
TrialManager - 试用管理器

负责管理待试用工具的生命周期和试用流程
"""

import logging
from typing import Dict, List, Any, Optional
from datetime import datetime

from src.data.database import DatabaseManager
from src.business.intent.intent_models import Intent
from src.business.intent.intent_repository import IntentRepository
from src.business.tool_trial.trial_models import (
    PendingTool,
    PendingToolStatus,
    ToolTrial,
    TrialStatus,
)
from src.business.tool_trial.trial_repository import (
    PendingToolRepository,
    ToolTrialRepository,
)
from src.business.tool_trial.trial_data_template_repository import (
    TrialDataTemplateRepository,
)
from src.business.tool_trial.trial_models import TrialDataTemplate
from src.data.models import Tool
from src.data.repositories import ToolRepository

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
            db_manager: 数据库管理器
        """
        self.db_manager = db_manager
        self.intent_repo = IntentRepository(db_manager)
        self.pending_tool_repo = PendingToolRepository(db_manager)
        self.tool_trial_repo = ToolTrialRepository(db_manager)
        self.tool_repo = ToolRepository(db_manager)
        self.template_repo = TrialDataTemplateRepository(db_manager)

    # ===== PendingTool 管理 =====

    def create_pending_tool(
        self,
        intent_id: str,
        tool_code: str,
        tool_name: str,
        tool_description: Optional[str] = None,
        execution_strategy: Optional[str] = None,
        parameters: Optional[List[Dict[str, Any]]] = None,
    ) -> PendingTool:
        """
        创建待试用工具

        Args:
            intent_id: 关联的意图 ID
            tool_code: 执行代码
            tool_name: 工具名称
            tool_description: 工具描述
            execution_strategy: 执行策略（api, browser, hybrid）
            parameters: 参数定义列表

        Returns:
            创建的待试用工具

        Raises:
            ValueError: 如果 intent_id 无效
        """
        # 验证 intent 存在
        intent = self.intent_repo.get_by_id(intent_id)
        if not intent:
            raise ValueError(f"Intent not found: {intent_id}")

        # 创建待试用工具
        pending_tool = PendingTool(
            intent_id=intent_id,
            tool_name=tool_name,
            tool_description=tool_description,
            execution_code=tool_code,
            execution_strategy=execution_strategy,
            parameters=parameters or [],
            status=PendingToolStatus.PENDING_TRIAL,
        )

        created = self.pending_tool_repo.create(pending_tool)
        logger.info(f"创建待试用工具: {created.tool_name} ({created.pending_tool_id})")

        return created

    def get_pending_tool(self, pending_tool_id: str) -> Optional[PendingTool]:
        """
        获取待试用工具

        Args:
            pending_tool_id: 待试用工具 ID

        Returns:
            待试用工具，如果不存在则返回 None
        """
        return self.pending_tool_repo.get_by_id(pending_tool_id)

    def get_pending_tools_by_intent(
        self, intent_id: str
    ) -> List[PendingTool]:
        """
        获取指定意图的所有待试用工具

        Args:
            intent_id: 意图 ID

        Returns:
            待试用工具列表
        """
        return self.pending_tool_repo.get_by_intent_id(intent_id)

    def get_pending_tools_by_status(
        self, status: PendingToolStatus
    ) -> List[PendingTool]:
        """
        根据状态获取待试用工具列表

        Args:
            status: 待试用工具状态

        Returns:
            待试用工具列表
        """
        return self.pending_tool_repo.get_by_status(status)

    def get_all_pending_tools(self, limit: int = 100) -> List[PendingTool]:
        """
        获取所有待试用工具

        Args:
            limit: 最大返回数量

        Returns:
            待试用工具列表
        """
        return self.pending_tool_repo.get_all(limit=limit)

    def update_pending_tool(self, pending_tool: PendingTool) -> PendingTool:
        """
        更新待试用工具

        Args:
            pending_tool: 待试用工具

        Returns:
            更新后的待试用工具
        """
        return self.pending_tool_repo.update(pending_tool)

    def delete_pending_tool(self, pending_tool_id: str) -> bool:
        """
        删除待试用工具

        Args:
            pending_tool_id: 待试用工具 ID

        Returns:
            是否删除成功
        """
        return self.pending_tool_repo.delete(pending_tool_id)

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

    def get_trials_by_pending_tool(
        self, pending_tool_id: str, limit: int = 10
    ) -> List[ToolTrial]:
        """
        获取待试用工具的所有试用记录

        Args:
            pending_tool_id: 待试用工具 ID
            limit: 最大返回数量

        Returns:
            试用记录列表
        """
        return self.tool_trial_repo.get_by_pending_tool_id(
            pending_tool_id, limit=limit
        )

    def get_trials_by_status(
        self, status: TrialStatus, limit: int = 100
    ) -> List[ToolTrial]:
        """
        根据状态获取试用记录列表

        Args:
            status: 试用状态
            limit: 最大返回数量

        Returns:
            试用记录列表
        """
        return self.tool_trial_repo.get_by_status(status, limit=limit)

    # ===== 提升为正式工具 =====

    def promote_to_tool_set(self, pending_tool_id: str) -> Tool:
        """
        将待试用工具提升为正式工具

        Args:
            pending_tool_id: 待试用工具 ID

        Returns:
            创建的正式工具

        Raises:
            ValueError: 如果 pending_tool_id 无效
        """
        # 获取待试用工具
        pending_tool = self.pending_tool_repo.get_by_id(pending_tool_id)
        if not pending_tool:
            raise ValueError(f"Pending tool not found: {pending_tool_id}")

        # 获取关联的 Intent
        intent = self.intent_repo.get_by_id(pending_tool.intent_id)
        if not intent:
            logger.warning(f"Intent not found for pending tool: {pending_tool_id}")

        # 创建正式工具
        tool = Tool(
            tool_name=pending_tool.tool_name,
            description=pending_tool.tool_description,
            execution_code=pending_tool.execution_code,
            code_language=pending_tool.code_language,
            execution_strategy=pending_tool.execution_strategy,
            parameters=pending_tool.parameters,
            steps=[],  # 从代码生成，暂时为空
            source="trial",
            source_intent_id=pending_tool.intent_id,
            trial_count=pending_tool.trial_count,
            pending_tool_id=pending_tool.pending_tool_id,
        )

        created_tool = self.tool_repo.create(tool)

        # 更新待试用工具状态
        pending_tool.promote()
        self.pending_tool_repo.update(pending_tool)

        logger.info(
            f"提升为正式工具: {created_tool.tool_name} ({created_tool.tool_id}), "
            f"from pending tool: {pending_tool_id}"
        )

        return created_tool

    # ===== 自动修复（占位符，后续实现）=====

    def auto_fix_tool(self, pending_tool_id: str, error: str) -> bool:
        """
        自动修复工具（占位符）

        Args:
            pending_tool_id: 待试用工具 ID
            error: 错误信息

        Returns:
            是否修复成功

        Note:
            此功能将在任务 2.3 中实现
        """
        logger.warning(f"auto_fix_tool not implemented yet: {pending_tool_id}")
        return False

    # ===== 试用数据模板管理 =====

    def save_trial_data_template(
        self,
        pending_tool_id: str,
        template_data: Dict[str, Any],
        template_name: Optional[str] = None,
        is_real_data: bool = False,
        description: Optional[str] = None,
        data_source: Optional[str] = None,
    ) -> TrialDataTemplate:
        """
        保存试用数据模板

        Args:
            pending_tool_id: 待试用工具 ID
            template_data: 模板数据
            template_name: 模板名称
            is_real_data: 是否为真实数据
            description: 模板描述
            data_source: 数据来源(user_generated, ai_generated, recording)

        Returns:
            创建的试用数据模板

        Raises:
            ValueError: 如果 pending_tool_id 无效
        """
        # 验证 pending_tool 存在
        pending_tool = self.pending_tool_repo.get_by_id(pending_tool_id)
        if not pending_tool:
            raise ValueError(f"Pending tool not found: {pending_tool_id}")

        # 创建数据模板
        template = TrialDataTemplate(
            pending_tool_id=pending_tool_id,
            template_name=template_name,
            template_data=template_data,
            is_real_data=is_real_data,
            description=description,
            data_source=data_source,
        )

        created_template = self.template_repo.create(template)
        logger.info(
            f"保存试用数据模板: {created_template.template_id} "
            f"for pending tool: {pending_tool_id}"
        )

        return created_template

    def get_trial_data_templates(
        self, pending_tool_id: str, only_real_data: bool = False
    ) -> List[TrialDataTemplate]:
        """
        获取指定待试用工具的数据模板

        Args:
            pending_tool_id: 待试用工具 ID
            only_real_data: 是否只获取真实数据模板

        Returns:
            试用数据模板列表
        """
        if only_real_data:
            return self.template_repo.get_real_data_templates(pending_tool_id)
        else:
            return self.template_repo.get_by_pending_tool_id(pending_tool_id)

    def get_trial_data_template(self, template_id: str) -> Optional[TrialDataTemplate]:
        """
        获取试用数据模板

        Args:
            template_id: 模板 ID

        Returns:
            试用数据模板，如果不存在则返回 None
        """
        return self.template_repo.get_by_id(template_id)

    def update_trial_data_template(self, template: TrialDataTemplate) -> TrialDataTemplate:
        """
        更新试用数据模板

        Args:
            template: 试用数据模板

        Returns:
            更新后的试用数据模板
        """
        return self.template_repo.update(template)

    def delete_trial_data_template(self, template_id: str) -> bool:
        """
        删除试用数据模板

        Args:
            template_id: 模板 ID

        Returns:
            是否删除成功
        """
        return self.template_repo.delete(template_id)

    def get_available_trial_data(self, pending_tool_id: str) -> Optional[Dict[str, Any]]:
        """
        获取可用的试用数据（优先使用真实数据）

        Args:
            pending_tool_id: 待试用工具 ID

        Returns:
            可用的试用数据，如果没有可用数据则返回 None
        """
        templates = self.template_repo.get_real_data_templates(pending_tool_id)

        if templates:
            # 优先使用最新的真实数据
            return templates[0].template_data

        # 如果没有真实数据，尝试使用模拟数据
        all_templates = self.template_repo.get_by_pending_tool_id(
            pending_tool_id, limit=1
        )
        if all_templates:
            return all_templates[0].template_data

        return None
