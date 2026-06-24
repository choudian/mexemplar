"""Delegation orchestration for assistant subagents and specialists."""

import logging
from typing import Any

from src.business.agents.config import AgentType
from src.business.brain.specialist_service import parse_tool_whitelist

logger = logging.getLogger(__name__)


class DelegationOrchestrator:
    """Runs assistant delegation workflows behind a small dispatch interface."""

    def __init__(self, owner: Any) -> None:
        self._owner = owner

    def delegate_to_subagent(
        self,
        *,
        parent_session_id: str,
        task_description: str,
        execution_context: str = "",
        tool_whitelist: list[str] | None = None,
    ) -> dict:
        task = (task_description or "").strip()
        if not task:
            return {
                "success": False,
                "message": "task_description must not be empty",
                "delegation_type": "ephemeral_subagent",
            }

        unified = self._owner._dispatch_task_via_unified_model(
            parent_session_id=parent_session_id,
            task=task,
            context=execution_context or task,
            assignee_type=AgentType.EPHEMERAL_SUBAGENT.value,
            assignee_id=AgentType.EPHEMERAL_SUBAGENT.value,
            capability_scope=tool_whitelist,
        )
        if unified is not None:
            return {
                **unified,
                "delegation_type": "ephemeral_subagent",
                "task_description": task,
            }

        return self.run_sync_ephemeral_subagent(
            parent_session_id=parent_session_id,
            task=task,
            execution_context=execution_context,
            tool_whitelist=tool_whitelist,
        )

    def run_sync_ephemeral_subagent(
        self,
        *,
        parent_session_id: str,
        task: str,
        execution_context: str = "",
        tool_whitelist: list[str] | None = None,
    ) -> dict:
        """同步起一个临时子代理并返回结果（上下文隔离助手）。

        主助理委派的临时子代理走此同步路径；专员的"至多一个"上下文隔离子代理（FR-019）
        也复用它。临时子代理领到的工具集（``_build_delegated_executor_tools`` 的
        ephemeral 分支）不含 ``delegate_to_subagent``，因此结构上不能再向下委派或找平级。
        """
        result = self.run_ephemeral_via_delegated_executor(
            parent_session_id=parent_session_id,
            task=task,
            execution_context=execution_context,
            tool_whitelist=tool_whitelist,
        )
        result["delegation_type"] = "ephemeral_subagent"
        result["task_description"] = task
        return result

    def run_ephemeral_via_delegated_executor(
        self,
        *,
        parent_session_id: str,
        task: str,
        execution_context: str = "",
        tool_whitelist: list[str] | None = None,
        current_task_id: str | None = None,
    ) -> dict:
        """临时子代理的纯执行核心：resolve tools → build prompt → create session →
        ``_run_delegated_executor``。同步委派与 ``TaskExecutorAdapter``（统一任务派发的
        异步执行器）共用此方法，避免两处复制 session/prompt 构建逻辑。
        """
        allowed_tool_ids = self._owner._resolve_user_tool_ids(
            parent_session_id=parent_session_id,
            tool_whitelist=tool_whitelist,
        )
        capability_catalog_section = self._owner._prompt_builder.format_capability_catalog(
            allowed_tool_ids,
            agent_type=AgentType.EPHEMERAL_SUBAGENT.value,
            include_descriptions=True,
        )
        system_prompt = self._owner._build_ephemeral_subagent_prompt(
            tool_whitelist,
            capability_catalog_section=capability_catalog_section,
        )
        workflow_id = self._owner._new_delegation_workflow_id(parent_session_id)
        child_session_id = self._owner._session_store.create_session(
            workflow_id,
            AgentType.EPHEMERAL_SUBAGENT,
        )
        user_input = self._owner._format_delegated_task_input(task, execution_context)
        result = self._owner._run_delegated_executor(
            agent_type=AgentType.EPHEMERAL_SUBAGENT,
            session_id=child_session_id,
            workflow_id=workflow_id,
            parent_session_id=parent_session_id,
            user_input=user_input,
            system_prompt=system_prompt,
            allowed_tool_ids=allowed_tool_ids,
            current_task_id=current_task_id,
        )
        if result.get("success"):
            self._owner._record_delegation_signal(
                parent_session_id=parent_session_id,
                task_pattern=task,
                result_text=str(result.get("result_text") or ""),
            )
        return result

    def delegate_to_specialist(
        self,
        *,
        parent_session_id: str,
        specialist_name: str,
        task: str,
    ) -> dict:
        name = (specialist_name or "").strip()
        task_text = (task or "").strip()
        if not name or not task_text:
            return {
                "success": False,
                "message": "specialist_name and task must not be empty",
                "delegation_type": "specialist",
            }

        from src.data.repos.specialist_repository import SpecialistRepository

        with SpecialistRepository() as repo:
            specialist = repo.get_specialist_by_name(name)
        if specialist is None:
            return {
                "success": False,
                "message": f"专员不存在: {name}",
                "delegation_type": "specialist",
            }
        if not getattr(specialist, "is_active", 1):
            return {
                "success": False,
                "message": f"专员已停用: {name}",
                "specialist_id": specialist.specialist_id,
                "delegation_type": "specialist",
            }

        whitelist = parse_tool_whitelist(getattr(specialist, "tool_whitelist", "[]"))
        unified = self._owner._dispatch_task_via_unified_model(
            parent_session_id=parent_session_id,
            task=task_text,
            context=task_text,
            assignee_type=AgentType.SPECIALIST.value,
            assignee_id=specialist.specialist_id,
            capability_scope=whitelist,
        )
        if unified is not None:
            return {
                **unified,
                "delegation_type": "specialist",
                "specialist_id": specialist.specialist_id,
                "specialist_name": name,
                "task": task_text,
            }

        result = self.run_specialist_via_delegated_executor(
            parent_session_id=parent_session_id,
            specialist=specialist,
            task=task_text,
            tool_whitelist=whitelist,
        )
        result["delegation_type"] = "specialist"
        result["specialist_id"] = specialist.specialist_id
        result["specialist_name"] = name
        result["task"] = task_text
        return result

    def continue_subagent(
        self,
        *,
        parent_session_id: str,
        subagent_id: str,
        instruction: str = "",
        extra_iterations: int = 20,
    ) -> dict:
        return self._owner._continue_subagent(
            parent_session_id=parent_session_id,
            subagent_id=subagent_id,
            instruction=instruction,
            extra_iterations=extra_iterations,
        )

    def inspect_subagent(self, *, parent_session_id: str, subagent_id: str) -> dict:
        return self._owner._inspect_subagent(
            parent_session_id=parent_session_id,
            subagent_id=subagent_id,
        )

    def run_specialist_via_delegated_executor(
        self,
        *,
        parent_session_id: str,
        specialist,
        task: str,
        tool_whitelist: list[str] | None = None,
        current_task_id: str | None = None,
    ) -> dict:
        """专员委派的纯执行核心：resolve tools → equipped skills → build prompt →
        create session → ``_run_delegated_executor``。同步委派与 ``TaskExecutorAdapter``
        （统一任务派发的异步执行器）共用此方法。装备/提示词构建异常返回 success=False
        dict，不抛异常（让 dispatcher 把"没干完"记为 stuck 交父侧裁定）。
        """
        allowed_tool_ids = self._owner._resolve_user_tool_ids(
            parent_session_id=parent_session_id,
            tool_whitelist=tool_whitelist,
        )
        try:
            equipped_skills_snapshot = self._owner._specialist_equipped_skills_snapshot(specialist)
        except RuntimeError as exc:
            logger.error("[Orchestrator] 专员方法论装备快照加载失败: %s", exc, exc_info=True)
            return {"success": False, "message": "专员方法论装备加载失败，已取消委派。"}
        try:
            capability_catalog_section = self._owner._prompt_builder.format_capability_catalog(
                allowed_tool_ids,
                agent_type=AgentType.SPECIALIST.value,
                include_descriptions=True,
            )
            system_prompt = self._owner._build_specialist_prompt(
                specialist,
                tool_whitelist,
                equipped_skills=equipped_skills_snapshot,
                capability_catalog_section=capability_catalog_section,
            )
        except RuntimeError as exc:
            logger.error("[Orchestrator] 专员方法论提示词构建失败: %s", exc, exc_info=True)
            return {"success": False, "message": "专员方法论提示词构建失败，已取消委派。"}
        workflow_id = self._owner._new_delegation_workflow_id(parent_session_id)
        child_session_id = self._owner._session_store.create_session(workflow_id, AgentType.SPECIALIST)
        allowed_methodology_skill_ids = {
            str(item.get("skill_id") or "")
            for item in equipped_skills_snapshot
            if str(item.get("skill_id") or "")
        }
        methodology_snapshot = self._owner._extract_methodology_equipment_snapshot(system_prompt)
        result = self._owner._run_delegated_executor(
            agent_type=AgentType.SPECIALIST,
            session_id=child_session_id,
            workflow_id=workflow_id,
            parent_session_id=parent_session_id,
            user_input=self._owner._format_delegated_task_input(task),
            system_prompt=system_prompt,
            allowed_tool_ids=allowed_tool_ids,
            specialist_id=specialist.specialist_id,
            allowed_methodology_skill_ids=allowed_methodology_skill_ids,
            methodology_equipment_snapshot=methodology_snapshot,
            current_task_id=current_task_id,
        )
        return result
