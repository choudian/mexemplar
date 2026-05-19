"""
SkillsService — 技能（工具）业务服务

封装 Skills screen / desktop API 所需的工具/失败记录查询，
UI 层不再直接访问 Repository。
"""

import logging
from collections.abc import Callable
from typing import Optional

from src.data.repositories import TeachingFailureRepository, ToolRepository
from src.utils.events import emit

logger = logging.getLogger(__name__)


class SkillsService:
    """技能管理服务：工具列表分类 + 失败记录 + workflow_id 查询"""

    def __init__(
        self,
        trial_starter: Callable[[str, str], bool | None] | None = None,
        trial_replier: Callable[[str, str], bool | None] | None = None,
        retry_starter: Callable[[str], bool | None] | None = None,
        trial_history_loader: Callable[[str], list[dict]] | None = None,
    ) -> None:
        self._trial_starter = trial_starter
        self._trial_replier = trial_replier
        self._retry_starter = retry_starter
        self._trial_history_loader = trial_history_loader

    def get_tools(self) -> tuple[list, list]:
        """读取全部工具，按状态分为待考核和已掌握两组。"""
        from src.business.tool_trial.trial_models import PendingTool, PendingToolStatus

        pending_tools: list[PendingTool] = []
        published_tools = []

        with ToolRepository() as repo:
            for tool in repo.get_all():
                if tool.status == "published":
                    published_tools.append(tool)
                elif tool.source == "intent":
                    pending_tools.append(
                        PendingTool(
                            pending_tool_id=tool.tool_id,
                            workflow_id=tool.workflow_id,
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

    def get_category(self, category: str) -> dict[str, object]:
        """返回 redesigned UI 使用的技能分类 DTO。"""
        if category == "pending":
            items = [self._pending_tool_to_summary(t) for t in self.get_tools()[0]]
        elif category == "published":
            items = [self._tool_to_summary(t, status="published") for t in self.get_tools()[1]]
        elif category == "failed":
            items = [self._failure_to_summary(r) for r in self.get_active_failures()]
        else:
            raise ValueError("技能分类无效")
        return {"category": category, "count": len(items), "items": items}

    def get_all_categories(self) -> list[dict[str, object]]:
        pending_tools, published_tools = self.get_tools()
        failures = self.get_active_failures()
        return [
            {
                "category": "pending",
                "count": len(pending_tools),
                "items": [self._pending_tool_to_summary(t) for t in pending_tools],
            },
            {
                "category": "published",
                "count": len(published_tools),
                "items": [self._tool_to_summary(t, status="published") for t in published_tools],
            },
            {
                "category": "failed",
                "count": len(failures),
                "items": [self._failure_to_summary(r) for r in failures],
            },
        ]

    def get_active_failures(self) -> list:
        """读取当前活跃的教学失败记录"""
        with TeachingFailureRepository() as repo:
            return repo.get_active_failures()

    def get_tool_workflow_id(self, tool_id: str) -> Optional[str]:
        with ToolRepository() as repo:
            tool = repo.get_by_id(tool_id)
            if tool is None:
                return None
            return tool.workflow_id or None

    def delete_tool(self, tool_id: str) -> None:
        """删除技能。被任意技能组合引用时不允许删除。"""
        from src.business.services.skill_composition_service import SkillCompositionService

        with ToolRepository() as repo:
            tool = repo.get_by_id(tool_id)
        if tool is None:
            raise ValueError("技能不存在")

        referenced = SkillCompositionService().get_referencing_compositions(tool_id)
        if referenced:
            names = "、".join(comp.composition_name for comp in referenced[:5])
            raise ValueError(f"该技能正在被技能组合引用，无法删除：{names}")

        with ToolRepository() as repo:
            repo.delete(tool_id)
        emit("skills_changed", sender=self, tool_id=tool_id, action="deleted")

    def update_tool_metadata(self, tool_id: str, name: str, description: str) -> list[str]:
        """更新技能名称与描述，返回引用它的组合名称列表。"""
        from src.business.services.skill_composition_service import SkillCompositionService

        clean_name = (name or "").strip()
        if not clean_name:
            raise ValueError("技能名称不能为空")

        with ToolRepository() as repo:
            tool = repo.get_by_id(tool_id)
            if tool is None:
                raise ValueError("技能不存在")

            tool.tool_name = clean_name
            tool.description = (description or "").strip() or None
            repo.update(tool)

        comp_service = SkillCompositionService()
        referenced = comp_service.get_referencing_compositions(tool_id)
        if referenced:
            comp_service.mark_needs_review_by_tool(tool_id)
            emit("composition_review_needed", sender=self, tool_id=tool_id)
        return [comp.composition_name for comp in referenced]

    def get_trial_history(self, tool_id: str) -> dict[str, object]:
        workflow_id = self.get_tool_workflow_id(tool_id)
        if not workflow_id or not self._trial_history_loader:
            return {"messages": [], "workflowId": None}
        messages = self._trial_history_loader(workflow_id)
        return {"messages": messages, "workflowId": workflow_id}

    def start_trial(self, tool_id: str) -> dict[str, object]:
        workflow_id = self.get_tool_workflow_id(tool_id)
        result = self._invoke_trial_action(
            tool_id,
            self._trial_starter,
            "技能试用执行器",
            workflow_id,
            tool_id,
            workflow_id,
        )
        if result.get("accepted"):
            emit("trial_requested", sender=self, tool_id=tool_id, workflow_id=result["workflowId"])
        return result

    def continue_trial(self, tool_id: str, content: str) -> dict[str, object]:
        workflow_id = self.get_tool_workflow_id(tool_id)
        return self._invoke_trial_action(
            tool_id,
            self._trial_replier,
            "技能试用回复器",
            workflow_id,
            workflow_id,
            content,
        )

    def _invoke_trial_action(
        self,
        tool_id: str,
        executor: Callable | None,
        label: str,
        workflow_id: str | None,
        *args: object,
    ) -> dict[str, object]:
        if not workflow_id:
            raise ValueError("技能不存在或缺少 workflow_id")
        if executor is None:
            raise ValueError(f"{label}不可用")
        accepted = executor(*args)
        if accepted is False:
            return {"accepted": False, "toolId": tool_id, "workflowId": workflow_id, "message": "技能试用已在运行"}
        return {"accepted": True, "toolId": tool_id, "workflowId": workflow_id}

    def _invoke_action(
        self, executor: Callable | None, label: str, busy_message: str, workflow_id: str, *args: object,
    ) -> dict[str, object]:
        if executor is None:
            raise ValueError(f"{label}不可用")
        accepted = executor(*args)
        if accepted is False:
            return {"accepted": False, "workflowId": workflow_id, "message": busy_message}
        return {"accepted": True, "workflowId": workflow_id}

    def retry_failure(self, workflow_id: str) -> dict[str, object]:
        with TeachingFailureRepository() as repo:
            record = repo.get_by_workflow_id(workflow_id)
            if record is None:
                raise ValueError("失败记录不存在")
            if record.status != "active":
                return {
                    "accepted": False,
                    "workflowId": workflow_id,
                    "message": "失败记录当前不可重试",
                }
        return self._invoke_action(
            self._retry_starter, "教学重试执行器", "教学重试已在运行", workflow_id, workflow_id,
        )

    def dismiss_failure(self, workflow_id: str) -> dict[str, object]:
        with TeachingFailureRepository() as repo:
            record = repo.get_by_workflow_id(workflow_id)
            if record is None:
                raise ValueError("失败记录不存在")
            record.status = "dismissed"
            repo.update(record)
        emit("teaching_failure_updated", sender=self, workflow_id=workflow_id, status="dismissed")
        return {"accepted": True, "workflowId": workflow_id}

    @staticmethod
    def _tool_to_summary(tool, status: str | None = None) -> dict[str, object]:
        return {
            "toolId": tool.tool_id,
            "name": tool.tool_name,
            "description": tool.description or "",
            "status": status or tool.status,
            "source": tool.source or "",
            "trialSuccessCount": tool.trial_success_count or 0,
            "workflowId": tool.workflow_id,
        }

    @staticmethod
    def _pending_tool_to_summary(tool) -> dict[str, object]:
        return {
            "toolId": tool.pending_tool_id,
            "name": tool.tool_name,
            "description": tool.tool_description or "",
            "status": "pending",
            "source": "intent",
            "trialSuccessCount": tool.trial_count or 0,
            "workflowId": tool.workflow_id,
        }

    @staticmethod
    def _failure_to_summary(record) -> dict[str, object]:
        stage = record.failed_stage or "未知阶段"
        return {
            "toolId": record.workflow_id,
            "name": record.tool_name or "教学失败",
            "description": f"教学在 {stage} 阶段失败",
            "status": "failed",
            "source": "teaching_failure",
            "trialSuccessCount": 0,
            "workflowId": record.workflow_id,
            "failureStage": record.failed_stage,
            "errorSummary": record.error_summary or "",
        }
