"""Delegation orchestration for assistant subagents and specialists."""

import logging
from datetime import timedelta
from typing import Any

from src.business.agents.config import AgentType
from src.business.brain.specialist_service import parse_composition_ids, parse_tool_whitelist
from src.business.orchestration.agent.subagent_scope import (
    EffectiveSubagentScope,
    ScopeCaptureState,
    resolve_effective_builtin_names,
)
from src.business.services.skill_composition.builtin_compositions import (
    EXTERNAL_CODING_COMPOSITION_ID,
)
from src.utils.timezone import utc_now_naive

logger = logging.getLogger(__name__)

# 同步委派的保守租约：同步路径调用方线程持有执行体，不会发生 lease 过期
# （dispatcher 的心跳机制不需要）。30 分钟给足任何同步委派跑完的余量；
# 万一真的超时，recovery 扫描会 fence 它，效果跟异步路径一致。
_SYNC_LEASE_TTL = timedelta(minutes=30)


def _validate_user_task_id(user_task_id: str | None) -> dict | None:
    """校验主助理传入的 taskId：非空、存在、状态仍在进行中（active/cooling）。

    返回 None 表示通过；返回 error dict 表示拒绝（与委派方法其他校验失败一致）。
    对齐旧聚焦守卫的严格度：不仅查"有没有传"，还查"传得对不对"。
    """
    tid = (user_task_id or "").strip()
    if not tid:
        return {
            "success": False,
            "message": "taskId 必填：请先 create_task 创建用户任务后再委派。",
        }
    from src.data.repos import UserTaskRepository

    task = UserTaskRepository().get(tid)
    if task is None:
        return {
            "success": False,
            "message": f"用户任务不存在: {tid}，请确认 taskId 正确或先 create_task。",
        }
    if task.status not in ("active", "cooling"):
        return {
            "success": False,
            "message": (
                f"用户任务「{task.title}」已{task.status}，不能在其底下新建委派。"
                "如需继续请 create_task 创建新任务。"
            ),
        }
    return None


def _start_sync_attempt(
    *,
    parent_session_id: str,
    task_title: str,
    task_description: str,
    executor_type: str,
    executor_id: str,
    user_task_id: str | None,
) -> str | None:
    """同步委派路径：建一条单节点 task 行 + active attempt，返回 task_id。

    同步路径不经 dispatcher 线程池，调用方线程同步持有执行体——不需要心跳续约，
    lease 给保守的 30 分钟余量。建的 task 行同时挂 user_task_id（解决同步委派归属缺口）。

    返回 task_id 供 ``_run_delegated_executor`` 的 ``current_task_id`` 参数使用，
    使 ``_bind_executor_session_to_attempt`` 能把 executor_session_id 绑到 attempt 上。
    任一步失败返回 None（不阻断委派本身——attempt 是追踪层，不是执行的前提）。
    """
    from src.data.repos import AssistantTaskAttemptRepository, AssistantTaskRepository
    from src.data.repos.base_repository import generate_id

    graph_id = generate_id("tg")
    task_id = generate_id("tsk")
    try:
        with AssistantTaskRepository() as tasks:
            tasks.create_task(
                graph_id=graph_id,
                session_id=parent_session_id,
                task_id=task_id,
                root_task_id=task_id,
                parent_task_id=None,
                title=task_title,
                description=task_description,
                owner_session_id=parent_session_id,
                user_task_id=user_task_id,
                assignee_type=executor_type,
                assignee_id=executor_id,
                status="running",
            )
        lease_expires = utc_now_naive() + _SYNC_LEASE_TTL
        with AssistantTaskAttemptRepository() as attempts:
            attempt = attempts.start_attempt(
                task_id=task_id,
                executor_type=executor_type,
                executor_id=executor_id,
                lease_owner="sync_delegation",
                lease_expires_at=lease_expires,
            )
            if attempt is None:
                logger.warning(
                    "[sync_delegation] start_attempt returned None (capacity conflict): "
                    "executor=%s task=%s",
                    executor_id,
                    task_id,
                )
                return None
    except Exception:
        logger.warning(
            "[sync_delegation] failed to create task+attempt for executor=%s",
            executor_id,
            exc_info=True,
        )
        return None
    return task_id


def _finalize_sync_attempt(
    task_id: str | None,
    result: dict,
) -> None:
    """同步委派路径：执行完后把 attempt 映射到终态。

    映射逻辑与 ``TaskExecutorAdapter._map_to_outcome`` 对齐：
    success → succeeded，paused/code_defect → paused，其余 → failed。
    task_id 为 None（建 attempt 失败）时整体跳过。
    """
    if not task_id:
        return
    from src.data.repos import AssistantTaskAttemptRepository

    try:
        with AssistantTaskAttemptRepository() as attempts:
            latest = attempts.latest_attempt_for_task(task_id)
            if latest is None:
                return
            if latest.status not in AssistantTaskAttemptRepository.ACTIVE_STATUSES:
                return  # 已终态（recovery fence 或并发终态写过）
            if result.get("success"):
                attempts.complete_if_current(
                    attempt_id=latest.attempt_id,
                    fence_token=latest.fence_token,
                    result_ref=str(result.get("result_text") or "")[:500] or None,
                )
            elif result.get("paused"):
                attempts.pause_if_current(
                    attempt_id=latest.attempt_id,
                    fence_token=latest.fence_token,
                    result_ref=result.get("subagent_id"),
                )
            elif result.get("failure_class") == "code_defect":
                # code_defect 暂停而非失败——代码不改，换执行体重试也是同一个错。
                # 与 TaskExecutorAdapter._map_to_outcome 的 BLOCKED_BY_DEFECT 映射对齐。
                attempts.pause_if_current(
                    attempt_id=latest.attempt_id,
                    fence_token=latest.fence_token,
                    result_ref=result.get("failure_exception_type"),
                )
            else:
                attempts.fail_if_current(
                    attempt_id=latest.attempt_id,
                    fence_token=latest.fence_token,
                    error_category=result.get("failure_class") or "unknown",
                )
    except Exception:
        logger.warning(
            "[sync_delegation] failed to finalize attempt for task=%s", task_id, exc_info=True
        )


class DelegationOrchestrator:
    """Runs assistant delegation workflows behind a small dispatch interface."""

    def __init__(self, owner: Any) -> None:
        self._owner = owner

    def delegate_to_subagent(
        self,
        *,
        parent_session_id: str,
        task_description: str,
        user_task_id: str,
        execution_context: str = "",
        tool_whitelist: list[str] | None = None,
        complexity: str = "complex",
    ) -> dict:
        # 用户任务层硬保证：taskId 必须存在且仍在进行中（active/cooling）。
        validated = _validate_user_task_id(user_task_id)
        if validated is not None:
            return validated
        task = (task_description or "").strip()
        if not task:
            return {
                "success": False,
                "message": "task_description must not be empty",
                "delegation_type": "ephemeral_subagent",
            }

        if complexity == "simple":
            # 简单任务（1-2 步单领域）：直接走同步委派路径，不建任务图。
            # 与 FR-398 "快速委派路径" 一致，崩溃恢复由 resumable_on_failure 覆盖。
            return self.run_sync_ephemeral_subagent(
                parent_session_id=parent_session_id,
                task=task,
                execution_context=execution_context,
                tool_whitelist=tool_whitelist,
                user_task_id=user_task_id,
            )

        # 复杂任务：走统一模型（建图 + durable accepted）
        unified = self._owner._dispatch_task_via_unified_model(
            parent_session_id=parent_session_id,
            task=task,
            context=execution_context or task,
            assignee_type=AgentType.EPHEMERAL_SUBAGENT.value,
            assignee_id=AgentType.EPHEMERAL_SUBAGENT.value,
            capability_scope=tool_whitelist,
            user_task_id=user_task_id,
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
            user_task_id=user_task_id,
        )

    def run_sync_ephemeral_subagent(
        self,
        *,
        parent_session_id: str,
        task: str,
        execution_context: str = "",
        tool_whitelist: list[str] | None = None,
        user_task_id: str | None = None,
        workspace_root: str | None = None,
        effective_scope: EffectiveSubagentScope | None = None,
    ) -> dict:
        """同步起一个临时子代理并返回结果（上下文隔离助手）。

        主助理委派的临时子代理走此同步路径；专员的上下文隔离子代理也复用它。同一次
        专员运行内的 child 启动调用由同步 handler 与 AgentLoop 工具串行分区保证不重叠，
        但可以先后启动多个。临时子代理领到的工具集（``_build_delegated_executor_tools``
        的 ephemeral 分支）不含 ``delegate_to_subagent``，因此结构上不能再向下委派或找平级。
        """
        result = self.run_ephemeral_via_delegated_executor(
            parent_session_id=parent_session_id,
            task=task,
            execution_context=execution_context,
            tool_whitelist=tool_whitelist,
            user_task_id=user_task_id,
            workspace_root=workspace_root,
            effective_scope=effective_scope,
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
        user_task_id: str | None = None,
        current_task_id: str | None = None,
        workspace_root: str | None = None,
        effective_scope: EffectiveSubagentScope | None = None,
        resume_session_id: str | None = None,
        iteration_budget: int | None = None,
    ) -> dict:
        """临时子代理的纯执行核心：resolve tools → build prompt → create session →
        ``_run_delegated_executor``。同步委派与 ``TaskExecutorAdapter``（统一任务派发的
        异步执行器）共用此方法，避免两处复制 session/prompt 构建逻辑。
        """
        allowed_builtin_tool_names: set[str] | None = None
        if effective_scope is not None:
            # 专员嵌套子代理在首次 launch 前已物化有效权限；这里消费同一个不可变对象，
            # 不再从 parent session 或模型原始 whitelist 二次推导。
            allowed_tool_ids = set(effective_scope.dynamic_tool_ids)
            allowed_composition_ids: set[str] | None = set(effective_scope.composition_ids)
            allowed_builtin_tool_names = set(effective_scope.builtin_names)
            workspace_root = effective_scope.workspace_root
        else:
            allowed_tool_ids = self._owner._resolve_user_tool_ids(
                parent_session_id=parent_session_id,
                tool_whitelist=tool_whitelist,
            )
            # 从父会话解析 composition_ids，传递给执行体以保持组合授权限制
            allowed_composition_ids = None
            try:
                parent_session = self._owner._session_store.get_session(parent_session_id)
                if parent_session is not None:
                    _, allowed_composition_ids = parent_session.parse_tool_ids()
            except Exception:
                logger.debug(
                    "composition_ids resolution skipped for parent=%s",
                    parent_session_id,
                    exc_info=True,
                )
        capability_catalog_section = self._owner._prompt_builder.format_capability_catalog(
            allowed_tool_ids,
            allowed_composition_ids=allowed_composition_ids,
            agent_type=AgentType.EPHEMERAL_SUBAGENT.value,
            include_descriptions=True,
        )
        system_prompt = self._owner._build_ephemeral_subagent_prompt(
            tool_whitelist,
            capability_catalog_section=capability_catalog_section,
        )
        # 续跑时复用已有会话（跳过 create_session），否则新建。workflow_id 从被复用的
        # session 记录读出（参照 _continue_subagent :1357），保证 transition/归属校验一致。
        if resume_session_id:
            existing = self._owner._session_store.get_session(resume_session_id)
            if existing is None:
                return {"success": False, "message": "续跑会话不存在"}
            child_session_id = existing.session_id
            workflow_id = getattr(existing, "workflow_id", "") or ""
        else:
            workflow_id = self._owner._new_delegation_workflow_id(parent_session_id)
            child_session_id = self._owner._session_store.create_session(
                workflow_id,
                AgentType.EPHEMERAL_SUBAGENT,
                user_task_id=user_task_id,
            )
        user_input = self._owner._format_delegated_task_input(task, execution_context)
        # 同步委派（current_task_id is None 且非续跑）建 task + attempt，
        # 让"执行体在不在跑"有 attempt 可查，同时挂 user_task_id 归属。
        sync_task_id = None
        if current_task_id is None and not resume_session_id:
            sync_task_id = _start_sync_attempt(
                parent_session_id=parent_session_id,
                task_title=task,
                task_description=execution_context or task,
                executor_type=AgentType.EPHEMERAL_SUBAGENT.value,
                executor_id=AgentType.EPHEMERAL_SUBAGENT.value,
                user_task_id=user_task_id,
            )
            current_task_id = sync_task_id or current_task_id
        result = self._owner._run_delegated_executor(
            agent_type=AgentType.EPHEMERAL_SUBAGENT,
            session_id=child_session_id,
            workflow_id=workflow_id,
            parent_session_id=parent_session_id,
            user_input=user_input,
            system_prompt=system_prompt,
            allowed_tool_ids=allowed_tool_ids,
            tool_whitelist=tool_whitelist,
            current_task_id=current_task_id,
            workspace_root=workspace_root,
            allowed_composition_ids=allowed_composition_ids,
            allowed_builtin_tool_names=allowed_builtin_tool_names,
            iteration_budget=iteration_budget,
        )
        _finalize_sync_attempt(sync_task_id, result)
        if result.get("success"):
            self._owner._record_delegation_signal(
                parent_session_id=parent_session_id,
                task_pattern=task,
                result_text=str(result.get("result_text") or ""),
            )
        return result

    def prepare_specialist_subagent_scope(
        self,
        *,
        requested_tool_whitelist: list[str] | None,
        specialist_allowed_tool_ids: set[str] | None,
        specialist_builtin_names: set[str],
        specialist_allowed_composition_ids: set[str] | None,
        workspace_root: str | None,
    ) -> EffectiveSubagentScope:
        """Capture one concrete, non-expanding authority object before first launch."""

        from src.business.agents.tools.builtin_general_tools import BUILTIN_GENERAL_TOOLS

        dynamic_tool_ids = self._owner._resolve_tool_ids_with_upper_bound(
            tool_whitelist=requested_tool_whitelist,
            upper_bound_ids=specialist_allowed_tool_ids,
            materialize_snapshot=True,
        )
        if requested_tool_whitelist is None:
            requested_composition_ids = specialist_allowed_composition_ids
        else:
            requested_identifiers = {
                item.strip()
                for item in requested_tool_whitelist
                if isinstance(item, str) and item.strip()
            }
            requested_composition_ids = (
                requested_identifiers
                if specialist_allowed_composition_ids is None
                else requested_identifiers.intersection(specialist_allowed_composition_ids)
            )
        composition_ids = self._owner._resolve_available_composition_ids(requested_composition_ids)
        unrestricted_at_capture = (
            specialist_allowed_tool_ids is None and requested_tool_whitelist is None
        ) or (specialist_allowed_composition_ids is None and requested_tool_whitelist is None)
        return EffectiveSubagentScope(
            dynamic_tool_ids=frozenset(dynamic_tool_ids or set()),
            builtin_names=resolve_effective_builtin_names(
                requested_tool_whitelist=requested_tool_whitelist,
                specialist_builtin_names=specialist_builtin_names,
                all_builtin_names={tool.name for tool in BUILTIN_GENERAL_TOOLS},
            ),
            composition_ids=frozenset(composition_ids),
            workspace_root=workspace_root,
            capture_state=(
                ScopeCaptureState.UNRESTRICTED_AT_CAPTURE
                if unrestricted_at_capture
                else ScopeCaptureState.BOUNDED
            ),
        )

    def delegate_to_specialist(
        self,
        *,
        parent_session_id: str,
        specialist_name: str,
        task: str,
        user_task_id: str,
        execution_context: str = "",
    ) -> dict:
        # 用户任务层硬保证：taskId 必须存在且仍在进行中（active/cooling）。
        validated = _validate_user_task_id(user_task_id)
        if validated is not None:
            return validated
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
            context=execution_context or task_text,
            assignee_type=AgentType.SPECIALIST.value,
            assignee_id=specialist.specialist_id,
            capability_scope=whitelist,
            user_task_id=user_task_id,
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
            execution_context=execution_context,
            tool_whitelist=whitelist,
            user_task_id=user_task_id,
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
        workspace_root: str | None = None,
        effective_scope: EffectiveSubagentScope | None = None,
    ) -> dict:
        return self._owner._continue_subagent(
            parent_session_id=parent_session_id,
            subagent_id=subagent_id,
            instruction=instruction,
            extra_iterations=extra_iterations,
            workspace_root=workspace_root,
            effective_scope=effective_scope,
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
        execution_context: str = "",
        tool_whitelist: list[str] | None = None,
        user_task_id: str | None = None,
        current_task_id: str | None = None,
        workspace_root: str | None = None,
        resume_session_id: str | None = None,
        iteration_budget: int | None = None,
    ) -> dict:
        """专员委派的纯执行核心：resolve tools → equipped skills → build prompt →
        create session → ``_run_delegated_executor``。同步委派与 ``TaskExecutorAdapter``
        （统一任务派发的异步执行器）共用此方法。装备/提示词构建异常返回 success=False
        dict，不抛异常（让 dispatcher 把"没干完"记为 stuck 交父侧裁定）。
        """
        effective_whitelist = (
            tool_whitelist
            if tool_whitelist is not None
            else parse_tool_whitelist(getattr(specialist, "tool_whitelist", "[]"))
        )
        # 同步委派（current_task_id is None 且非续跑）建 task + attempt，
        # 让"执行体在不在跑"有 attempt 可查，同时挂 user_task_id 归属。
        # 放在 composition gate 之前——同步委派的专员跟建图路径一样是正式执行，
        # current_task_id 有值后外部 Coding 组合正常授权。
        sync_task_id = None
        if current_task_id is None and not resume_session_id:
            sync_task_id = _start_sync_attempt(
                parent_session_id=parent_session_id,
                task_title=task,
                task_description=execution_context or task,
                executor_type=AgentType.SPECIALIST.value,
                executor_id=specialist.specialist_id,
                user_task_id=user_task_id,
            )
            current_task_id = sync_task_id or current_task_id
        allowed_tool_ids = self._owner._resolve_user_tool_ids(
            parent_session_id=parent_session_id,
            tool_whitelist=effective_whitelist,
        )
        parent_composition_ids: set[str] | None = None
        try:
            parent_session = self._owner._session_store.get_session(parent_session_id)
            if parent_session is not None:
                _, parent_composition_ids = parent_session.parse_tool_ids()
        except Exception:
            logger.debug(
                "composition_ids resolution skipped for parent=%s",
                parent_session_id,
                exc_info=True,
            )

        assigned_composition_ids = set(
            parse_composition_ids(getattr(specialist, "composition_ids", "[]"))
        )
        allowed_composition_ids: set[str] = set()
        role_kind = getattr(specialist, "role_kind", "executor") or "executor"
        effective_composition_ids = assigned_composition_ids if role_kind == "executor" else set()
        for composition_id in effective_composition_ids:
            composition = self._owner._composition_service.get_execution_snapshot(composition_id)
            if composition is None:
                continue
            if getattr(composition, "is_builtin", False):
                if (
                    composition_id == EXTERNAL_CODING_COMPOSITION_ID
                    and current_task_id
                    and role_kind == "executor"
                ):
                    allowed_composition_ids.add(composition_id)
                continue
            if parent_composition_ids is not None and composition_id not in parent_composition_ids:
                continue
            member_tool_ids = {member.tool_id for member in composition.members}
            resolved_member_ids = self._owner._resolve_user_tool_ids(
                parent_session_id=parent_session_id,
                tool_whitelist=list(member_tool_ids),
            )
            if resolved_member_ids is None or not member_tool_ids.issubset(resolved_member_ids):
                continue
            allowed_composition_ids.add(composition_id)
            if allowed_tool_ids is not None:
                allowed_tool_ids.update(resolved_member_ids)
        try:
            equipped_skills_snapshot = self._owner._specialist_equipped_skills_snapshot(specialist)
        except RuntimeError as exc:
            logger.error("[Orchestrator] 专员方法论装备快照加载失败: %s", exc, exc_info=True)
            _finalize_sync_attempt(sync_task_id, {"success": False, "message": str(exc)})
            return {"success": False, "message": "专员方法论装备加载失败，已取消委派。"}
        try:
            capability_catalog_section = self._owner._prompt_builder.format_capability_catalog(
                allowed_tool_ids,
                allowed_composition_ids=allowed_composition_ids,
                agent_type=AgentType.SPECIALIST.value,
                include_descriptions=True,
            )
            system_prompt = self._owner._build_specialist_prompt(
                specialist,
                effective_whitelist,
                equipped_skills=equipped_skills_snapshot,
                capability_catalog_section=capability_catalog_section,
            )
        except RuntimeError as exc:
            logger.error("[Orchestrator] 专员方法论提示词构建失败: %s", exc, exc_info=True)
            _finalize_sync_attempt(sync_task_id, {"success": False, "message": str(exc)})
            return {"success": False, "message": "专员方法论提示词构建失败，已取消委派。"}
        # 续跑时复用已有会话（跳过 create_session），否则新建。
        if resume_session_id:
            existing = self._owner._session_store.get_session(resume_session_id)
            if existing is None:
                return {"success": False, "message": "续跑会话不存在"}
            child_session_id = existing.session_id
            workflow_id = getattr(existing, "workflow_id", "") or ""
        else:
            workflow_id = self._owner._new_delegation_workflow_id(parent_session_id)
            child_session_id = self._owner._session_store.create_session(
                workflow_id, AgentType.SPECIALIST, user_task_id=user_task_id
            )
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
            user_input=self._owner._format_delegated_task_input(task, execution_context),
            system_prompt=system_prompt,
            allowed_tool_ids=allowed_tool_ids,
            tool_whitelist=effective_whitelist,
            specialist_id=specialist.specialist_id,
            allowed_methodology_skill_ids=allowed_methodology_skill_ids,
            methodology_equipment_snapshot=methodology_snapshot,
            current_task_id=current_task_id,
            # 024 C4: 透传 specialist.role_kind，planner 拿 build_task_graph 不拿执行器工具
            role_kind=role_kind,
            workspace_root=workspace_root,
            allowed_composition_ids=allowed_composition_ids,
            iteration_budget=iteration_budget,
        )
        _finalize_sync_attempt(sync_task_id, result)
        return result
