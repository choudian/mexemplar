"""
SkillsService — 技能（工具）业务服务

封装 ToolsManagementUI 和 MainWindow 所需的工具/失败记录查询，
UI 层不再直接访问 Repository。
"""

import logging
from typing import Optional

from src.data.repositories import TeachingFailureRepository, ToolRepository

logger = logging.getLogger(__name__)


class SkillsService:
    """技能管理服务：工具列表分类 + 失败记录 + workflow_id 查询"""

    def get_tools(self) -> tuple[list, list]:
        """
        读取全部工具，按状态分为待考核和已掌握两组。

        Returns:
            (pending_tools, published_tools)
            pending_tools: list[PendingTool]（来自 intent 且未 published）
            published_tools: list[Tool]（status == "published"）
        """
        from src.business.tool_trial.trial_models import PendingTool, PendingToolStatus

        all_tools = ToolRepository().get_all()

        pending_tools: list[PendingTool] = []
        published_tools = []

        for tool in all_tools:
            if tool.status == "published":
                published_tools.append(tool)
            elif tool.source == "intent":
                pending_tools.append(
                    PendingTool(
                        pending_tool_id=tool.tool_id,
                        tool_name=tool.tool_name,
                        tool_description=tool.description,
                        execution_code=tool.execution_code,
                        execution_strategy=tool.execution_strategy,
                        parameters=tool.parameters if tool.parameters else [],
                        status=PendingToolStatus.PENDING_TRIAL,
                        trial_count=tool.trial_success_count,
                        max_trials=3,
                        created_at=tool.created_at,
                        updated_at=tool.updated_at,
                    )
                )

        return pending_tools, published_tools

    def get_active_failures(self) -> list:
        """读取当前活跃的教学失败记录"""
        return TeachingFailureRepository().get_active_failures()

    def get_tool_workflow_id(self, tool_id: str) -> Optional[str]:
        """
        按 tool_id 查询对应的 workflow_id。

        Returns:
            workflow_id 字符串，工具不存在或无 workflow_id 时返回 None。
        """
        tool = ToolRepository().get_by_id(tool_id)
        if tool is None:
            logger.error(f"找不到工具: {tool_id}")
            return None
        if not tool.workflow_id:
            logger.error(f"工具 {tool_id} 没有 workflow_id")
            return None
        return tool.workflow_id
