"""Tool registry for agent tool schemas and handler factories."""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any, Protocol, TYPE_CHECKING

if TYPE_CHECKING:
    from src.business.agents.tools.dynamic_tool_manager import DynamicToolManager

from src.business.agents.config import AgentType, ToolDefinition
from src.business.agents.tools.desktop_tools import create_desktop_specific_tools
from src.business.agents.tools.pm_output_tools import report_code_issue, submit_requirements
from src.business.agents.tools.programmer_tools import submit_code, syntax_check
from src.business.agents.tools.recording_data_tools import create_recording_tools
from src.business.agents.tools.trial_tools import create_desktop_trial_tools, create_trial_tools
from src.business.orchestration.agent.subagent_scope import (
    EffectiveSubagentScope,
    SCOPE_SNAPSHOT_MISSING,
)
from src.data.repos.skill_equipment_repository import ASSISTANT_ENTITY_ID
from src.recording.browser.recorder import RecordingMode


class _SessionToolQuery(Protocol):
    def get_session(self, session_id: str) -> Any: ...


class _DynamicManagerCache(Protocol):
    def get_or_create_dynamic_manager(
        self,
        session_id: str,
        allowed_ids: set[str] | None,
        allowed_composition_ids: set[str] | None = None,
    ) -> DynamicToolManager: ...


class _DelegationFacade(Protocol):
    def delegate_to_subagent(
        self,
        *,
        parent_session_id: str,
        task_description: str,
        execution_context: str = "",
        tool_whitelist: list[str] | None = None,
        complexity: str = "complex",
    ) -> dict: ...

    def continue_subagent(
        self,
        *,
        parent_session_id: str,
        subagent_id: str,
        instruction: str = "",
        extra_iterations: int = 20,
        effective_scope: EffectiveSubagentScope | None = None,
    ) -> dict: ...

    def inspect_subagent(self, *, parent_session_id: str, subagent_id: str) -> dict: ...

    def delegate_to_specialist(
        self,
        *,
        parent_session_id: str,
        specialist_name: str,
        task: str,
        execution_context: str = "",
    ) -> dict: ...

    def run_sync_ephemeral_subagent(
        self,
        *,
        parent_session_id: str,
        task: str,
        execution_context: str = "",
        tool_whitelist: list[str] | None = None,
        workspace_root: str | None = None,
        effective_scope: EffectiveSubagentScope | None = None,
    ) -> dict: ...

    def prepare_specialist_subagent_scope(
        self,
        *,
        requested_tool_whitelist: list[str] | None,
        specialist_allowed_tool_ids: set[str] | None,
        specialist_builtin_names: set[str],
        specialist_allowed_composition_ids: set[str] | None,
        workspace_root: str | None,
    ) -> EffectiveSubagentScope: ...


# 规划专员不拿的 BUILTIN_GENERAL_TOOLS 工具（024 DEC-B 修订 2026-07-27）。
#
# 原 DEC-B 把 BUILTIN_GENERAL_TOOLS 整体挡在 planner 之外，规划专员连一个文件都
# 打不开，任务书里的指代（"复用现有 X"）无从核实，只能原样甩给下游执行体——同一批
# 信息被 N 个执行体各查一遍，还可能查出 N 种理解。修订后改为排除法：除下列几项外
# 都放行，planner 与 executor 的工具差别收敛为协作类工具。
#
# 仍然排除：
#   - write_file / edit_file / apply_patch —— 直接落盘的文件改写
#   - web_search / web_fetch —— 引入网络与外部内容，另行评估
#
# exec 与 process_* 已放行（用户决策 2026-07-27）：调研常需要 git log、npm ls 这类
# 命令，而 exec 支持 background，放行它就必须同时给 process_*，否则起了进程看不到
# 日志也停不掉，反而造成泄漏。代价是"只规划不执行"不再是工具层的硬边界——exec 可以
# 写文件，因此上面禁 write_file 只挡直接调用、挡不住绕道。实际约束由 exec 自身的
# 权限层承担（OS 系统路径硬拒、workspace 外操作走确认链、self-improvement worktree
# 守卫），而非本清单。
_PLANNER_DENIED_BUILTIN_TOOL_NAMES = frozenset(
    {
        "write_file",
        "edit_file",
        "apply_patch",
        "web_search",
        "web_fetch",
    }
)


def _filter_builtin_tools(
    builtin_tools: list[ToolDefinition],
    tool_whitelist: list[str] | None,
) -> list[ToolDefinition]:
    """Restrict built-ins only when the whitelist explicitly names built-ins.

    Historical delegated tasks used ``tool_whitelist`` for user-published tools
    while still receiving the normal built-in workspace tools.  Proposal task
    graphs, however, pass built-in names in ``capabilityScope`` as the hard
    role boundary.  Filtering only in that explicit case preserves the legacy
    behavior while making proposal planner/test nodes genuinely least-privilege.
    """
    if not tool_whitelist:
        return builtin_tools
    builtin_names = {tool.name for tool in builtin_tools}
    allowed_builtin_names = {
        item.strip()
        for item in tool_whitelist
        if isinstance(item, str) and item.strip() in builtin_names
    }
    if not allowed_builtin_names:
        return builtin_tools
    return [tool for tool in builtin_tools if tool.name in allowed_builtin_names]


class ToolRegistry:
    """Builds per-agent tool lists from injected collaborators.

    依赖注入:不再持有 Orchestrator 引用,只依赖 5 个窄依赖(session 查询、动态
    管理器缓存、委派 facade、录制模式解析、任务重派)。生产由 AgentOrchestrator
    注入自身组件;测试可注入 fake 摆脱真 Orchestrator/SQLite。
    """

    def __init__(
        self,
        *,
        session_store: _SessionToolQuery,
        dynamic_manager_cache: _DynamicManagerCache,
        delegation_orchestrator: _DelegationFacade,
        resolve_recording_mode: Callable[[str | None], str],
        redispatch_answered_task: Callable[[str], bool],
    ) -> None:
        self._session_store = session_store
        self._dynamic_manager_cache = dynamic_manager_cache
        self._delegation = delegation_orchestrator
        self._resolve_recording_mode = resolve_recording_mode
        self._redispatch_answered_task = redispatch_answered_task

    def build_tools(
        self,
        agent_type: str,
        workflow_id: str | None = None,
        session_id: str | None = None,
    ) -> list[ToolDefinition] | Callable[[], list[ToolDefinition]]:
        if agent_type == AgentType.ASSISTANT:
            return self.build_assistant_tools(session_id or "")
        mode = self._resolve_recording_mode(workflow_id)
        recording_tools = create_recording_tools(workflow_id, mode)
        if mode == RecordingMode.DESKTOP:
            recording_tools = recording_tools + create_desktop_specific_tools(workflow_id)
        if agent_type == AgentType.PM:
            return recording_tools + [submit_requirements, report_code_issue]
        if agent_type == AgentType.PROGRAMMER:
            return recording_tools + [syntax_check, submit_code]
        if agent_type == AgentType.TRIAL:
            if mode == RecordingMode.DESKTOP:
                return recording_tools + create_desktop_trial_tools(workflow_id)
            return create_trial_tools(workflow_id)
        return []

    @staticmethod
    def make_load_skill_tool(
        caller_type: str,
        caller_id: str,
        allowed_skill_ids: set[str] | None = None,
    ) -> ToolDefinition:
        from src.business.agents.tools.skill_methodology_tools import (
            LOAD_SKILL_METHODOLOGY_SCHEMA,
            create_load_skill_methodology_handler,
        )

        return ToolDefinition(
            name="load_skill_methodology",
            schema=LOAD_SKILL_METHODOLOGY_SCHEMA,
            handler=create_load_skill_methodology_handler(
                caller_type=caller_type,
                caller_id=caller_id,
                allowed_skill_ids=allowed_skill_ids,
            ),
            has_side_effects=False,
        )

    def build_delegated_executor_tools(
        self,
        allowed_tool_ids: set[str] | None,
        *,
        tool_whitelist: list[str] | None = None,
        agent_type: str | None = None,
        executor_id: str | None = None,
        specialist_id: str | None = None,
        allowed_methodology_skill_ids: set[str] | None = None,
        current_task_id: str | None = None,
        parent_session_id: str | None = None,
        role_kind: str = "executor",
        allowed_composition_ids: set[str] | None = None,
        allowed_builtin_tool_names: set[str] | None = None,
        workspace_root: str | None = None,
    ) -> Callable[[], list[ToolDefinition]]:
        """Build tools for delegated executors (specialists / ephemeral subagents).

        024 扩展：role_kind 参数控制工具分支。
        - 'executor'（默认）：拿 todo_update / ask_parent / meeting 等执行器工具
        - 'planner'：只拿 build_task_graph（规划变体），不拿执行器工具
        """
        from src.business.agents.tools.assistant_tools import (
            ASK_PARENT_SCHEMA,
            BUILD_TASK_GRAPH_SCHEMA,
            COMPLETE_USER_TODO_SCHEMA,
            CREATE_USER_TODO_SCHEMA,
            DELETE_USER_TODO_SCHEMA,
            DELEGATE_TO_SUBAGENT_SCHEMA,
            CONTINUE_SUBAGENT_SCHEMA,
            INSPECT_SUBAGENT_SCHEMA,
            LIST_SPECIALISTS_SCHEMA,
            LIST_USER_TODOS_SCHEMA,
            MEETING_SEND_MESSAGE_SCHEMA,
            TODO_CREATE_SCHEMA,
            TODO_UPDATE_SCHEMA,
            UPDATE_USER_TODO_SCHEMA,
            create_ask_parent_handler,
            create_build_task_graph_handler,
            create_complete_user_todo_handler,
            create_continue_subagent_handler,
            create_delete_user_todo_handler,
            create_delegate_to_subagent_handler,
            create_inspect_subagent_handler,
            create_list_specialists_handler,
            create_list_user_todos_handler,
            create_meeting_send_message_handler,
            create_todo_handlers,
            create_update_user_todo_handler,
            create_user_todo_handler,
        )
        from src.business.agents.tools.builtin_general_tools import BUILTIN_GENERAL_TOOLS
        from src.business.agents.tools.dynamic_tool_manager import (
            DynamicToolManager,
        )
        from src.business.agents.tools.external_coding_tools import create_external_coding_tools
        from src.business.services.skill_composition.builtin_compositions import (
            EXTERNAL_CODING_COMPOSITION_ID,
        )

        builtin_composition_tools: dict[str, ToolDefinition] = {}
        if (
            agent_type == AgentType.SPECIALIST
            and role_kind == "executor"
            and bool(specialist_id)
            and current_task_id
            and allowed_composition_ids is not None
            and EXTERNAL_CODING_COMPOSITION_ID in allowed_composition_ids
        ):
            builtin_composition_tools = {
                tool.name: tool
                for tool in create_external_coding_tools(
                    session_id=parent_session_id or executor_id,
                    bound_task_id=current_task_id,
                )
            }
        dynamic_manager = DynamicToolManager(
            allowed_tool_ids=allowed_tool_ids,
            allowed_composition_ids=(set() if role_kind == "planner" else allowed_composition_ids),
            builtin_tool_definitions=builtin_composition_tools,
        )
        builtin_tools = _filter_builtin_tools(BUILTIN_GENERAL_TOOLS, tool_whitelist)
        if allowed_builtin_tool_names is not None:
            builtin_tools = [
                tool for tool in builtin_tools if tool.name in allowed_builtin_tool_names
            ]
        load_skill_tool = self.make_load_skill_tool(
            caller_type="specialist" if agent_type == AgentType.SPECIALIST else "assistant",
            caller_id=specialist_id or ASSISTANT_ENTITY_ID,
            allowed_skill_ids=allowed_methodology_skill_ids,
        )
        executor_type = (
            AgentType.SPECIALIST.value
            if agent_type == AgentType.SPECIALIST
            else AgentType.EPHEMERAL_SUBAGENT.value
        )
        resolved_executor_id = specialist_id or executor_id or executor_type
        ask_parent_schema = (
            self.schema_with_bound_task_id(ASK_PARENT_SCHEMA)
            if current_task_id
            else ASK_PARENT_SCHEMA
        )
        todo_create_schema = (
            self.schema_with_bound_task_id(TODO_CREATE_SCHEMA)
            if current_task_id
            else TODO_CREATE_SCHEMA
        )
        todo_schema = (
            self.schema_with_bound_task_id(TODO_UPDATE_SCHEMA)
            if current_task_id
            else TODO_UPDATE_SCHEMA
        )
        ask_parent_meeting_tools: list[ToolDefinition] = [
            ToolDefinition(
                name=ask_parent_schema["function"]["name"],
                schema=ask_parent_schema,
                handler=create_ask_parent_handler(
                    executor_type=executor_type,
                    executor_id=resolved_executor_id,
                    # 归属校验的权威依据：``executor_id`` 传进来的就是执行体自己的会话 id，
                    # 而 ``resolved_executor_id`` 对专员会被替换成专员身份，不能代表现场。
                    executor_session_id=executor_id,
                    bound_task_id=current_task_id,
                    interrupt=bool(current_task_id),
                ),
                is_interrupting=bool(current_task_id),
            ),
            ToolDefinition(
                name=MEETING_SEND_MESSAGE_SCHEMA["function"]["name"],
                schema=MEETING_SEND_MESSAGE_SCHEMA,
                handler=create_meeting_send_message_handler(
                    executor_type=executor_type,
                    executor_id=resolved_executor_id,
                ),
            ),
        ]
        todo_executor_id = specialist_id or executor_type
        _todo_create_handler, _todo_update_handler = create_todo_handlers(
            executor_type=executor_type,
            executor_id=todo_executor_id,
            executor_session_id=executor_id,
            bound_task_id=current_task_id,
        )
        executor_collaboration_tools: list[ToolDefinition] = [
            *ask_parent_meeting_tools,
            ToolDefinition(
                name=todo_create_schema["function"]["name"],
                schema=todo_create_schema,
                handler=_todo_create_handler,
            ),
            ToolDefinition(
                name=todo_schema["function"]["name"],
                schema=todo_schema,
                handler=_todo_update_handler,
            ),
            ToolDefinition(
                name="create_user_todo",
                schema=CREATE_USER_TODO_SCHEMA,
                handler=create_user_todo_handler(),
            ),
            ToolDefinition(
                name="list_user_todos",
                schema=LIST_USER_TODOS_SCHEMA,
                handler=create_list_user_todos_handler(),
                has_side_effects=False,
            ),
            ToolDefinition(
                name="update_user_todo",
                schema=UPDATE_USER_TODO_SCHEMA,
                handler=create_update_user_todo_handler(),
            ),
            ToolDefinition(
                name="complete_user_todo",
                schema=COMPLETE_USER_TODO_SCHEMA,
                handler=create_complete_user_todo_handler(),
            ),
            ToolDefinition(
                name="delete_user_todo",
                schema=DELETE_USER_TODO_SCHEMA,
                handler=create_delete_user_todo_handler(),
            ),
        ]

        specialist_subagent_tools: list[ToolDefinition] = []
        if agent_type == AgentType.SPECIALIST:
            scope_by_subagent_id: dict[str, EffectiveSubagentScope] = {}

            specialist_continue_schema = copy.deepcopy(CONTINUE_SUBAGENT_SCHEMA)
            specialist_continue_schema["function"]["description"] = (
                "继续执行你自己起的那个已暂停隔离子代理，从原会话历史断点接着跑；"
                "也可追加指令纠偏。pause_reason=quota_exhausted 时不要盲目立即重试，"
                "应等待配额恢复或用 ask_parent 升级。"
            )
            specialist_continue_schema["function"]["parameters"]["properties"]["subagent_id"][
                "description"
            ] = "你自己的 delegate_to_subagent 返回的 subagent_id"
            specialist_inspect_schema = copy.deepcopy(INSPECT_SUBAGENT_SCHEMA)
            specialist_inspect_schema["function"]["description"] = (
                "查看你自己起的那个隔离子代理的工作概览，用于判断是续跑、追加指令纠偏，"
                "还是用 ask_parent 升级。只读，不消耗额外模型调用。"
            )
            specialist_inspect_schema["function"]["parameters"]["properties"]["subagent_id"][
                "description"
            ] = "你自己的 delegate_to_subagent 返回的 subagent_id"
            specialist_delegate_schema = copy.deepcopy(DELEGATE_TO_SUBAGENT_SCHEMA)
            specialist_delegate_schema["function"]["parameters"]["properties"]["tool_whitelist"][
                "description"
            ] = (
                "可选工具名称/ID或组合 ID 白名单；不传则继承当前专员实际权限。"
                "显式传入列表后，未列出的组合不会授予隔离子代理。"
            )

            def _specialist_subagent_callback(
                *,
                parent_session_id: str,
                task_description: str,
                execution_context: str = "",
                tool_whitelist: list[str] | None = None,
                complexity: str = "complex",
                user_task_id: str = "",
            ) -> dict:
                task = (task_description or "").strip()
                if not task:
                    return {
                        "success": False,
                        "message": "task_description must not be empty",
                        "delegation_type": "ephemeral_subagent",
                    }
                effective_scope = self._delegation.prepare_specialist_subagent_scope(
                    requested_tool_whitelist=tool_whitelist,
                    specialist_allowed_tool_ids=allowed_tool_ids,
                    specialist_builtin_names={tool.name for tool in builtin_tools},
                    specialist_allowed_composition_ids=allowed_composition_ids,
                    workspace_root=workspace_root,
                )
                result = self._delegation.run_sync_ephemeral_subagent(
                    parent_session_id=parent_session_id,
                    task=task,
                    execution_context=execution_context,
                    tool_whitelist=tool_whitelist,
                    user_task_id=user_task_id or None,
                    workspace_root=workspace_root,
                    effective_scope=effective_scope,
                )
                child_id = str(result.get("subagent_id") or "").strip()
                if child_id:
                    scope_by_subagent_id[child_id] = effective_scope
                return result

            def _specialist_continue_callback(
                *,
                parent_session_id: str,
                subagent_id: str,
                instruction: str = "",
                extra_iterations: int = 20,
            ) -> dict:
                scope = scope_by_subagent_id.get(subagent_id, SCOPE_SNAPSHOT_MISSING)
                if scope is SCOPE_SNAPSHOT_MISSING:
                    return {
                        "success": False,
                        "error": (
                            "未找到该隔离子代理的权限快照；V1 只支持同一次专员运行内续跑，"
                            "请用 ask_parent 升级处理。"
                        ),
                        "subagent_id": subagent_id,
                    }
                if not isinstance(scope, EffectiveSubagentScope):
                    return {
                        "success": False,
                        "error": "隔离子代理权限快照无效，请用 ask_parent 升级处理。",
                        "subagent_id": subagent_id,
                    }
                return self._delegation.continue_subagent(
                    parent_session_id=parent_session_id,
                    subagent_id=subagent_id,
                    instruction=instruction,
                    extra_iterations=extra_iterations,
                    effective_scope=scope,
                )

            specialist_subagent_tools = [
                ToolDefinition(
                    name="delegate_to_subagent",
                    schema=specialist_delegate_schema,
                    handler=create_delegate_to_subagent_handler(
                        executor_id or "",
                        dispatch_callback=_specialist_subagent_callback,
                    ),
                    has_side_effects=True,
                    is_concurrency_safe=False,
                ),
                ToolDefinition(
                    name="continue_subagent",
                    schema=specialist_continue_schema,
                    handler=create_continue_subagent_handler(
                        executor_id or "",
                        continue_callback=_specialist_continue_callback,
                    ),
                    has_side_effects=True,
                    is_concurrency_safe=False,
                ),
                ToolDefinition(
                    name="inspect_subagent",
                    schema=specialist_inspect_schema,
                    handler=create_inspect_subagent_handler(
                        executor_id or "",
                        inspect_callback=self._delegation.inspect_subagent,
                    ),
                    has_side_effects=False,
                ),
            ]

        # 024: planner 角色分支——规划专员只拿规划工具，不拿执行器工具
        planner_tools: list[ToolDefinition] = []
        if role_kind == "planner":
            graph_owner_session_id = parent_session_id or executor_id or ""
            planner_tools = [
                ToolDefinition(
                    name="build_task_graph",
                    schema=BUILD_TASK_GRAPH_SCHEMA,
                    handler=create_build_task_graph_handler(
                        graph_owner_session_id,
                    ),
                ),
                # build_task_graph 的 assigneeId 要求填具体 specialist id，规划专员必须
                # 能查到有哪些专员、各自什么工具，否则只能把所有节点退化成临时子代理。
                # 专员目录同时按阈值注入 prompt（见 _build_specialist_prompt）：条目少时
                # 直接展示，超阈值转本工具按需查询。
                ToolDefinition(
                    name="list_specialists",
                    schema=LIST_SPECIALISTS_SCHEMA,
                    handler=create_list_specialists_handler(specialist_id or ""),
                ),
            ]
            # 调研工具：规划前先核实任务书里的指代，别把调研甩给下游执行体。
            # 排除项与理由见 _PLANNER_DENIED_BUILTIN_TOOL_NAMES。
            planner_tools.extend(
                tool
                for tool in BUILTIN_GENERAL_TOOLS
                if tool.name not in _PLANNER_DENIED_BUILTIN_TOOL_NAMES
            )

        # 027: MCP 工具注入 — 预置全量 + 自定义激活
        from src.business.mcp import get_mcp_tool_registry

        mcp_registry = get_mcp_tool_registry()

        # 027-T029: MCP-aware search_tools（含 MCP kind 和 server_slug 过滤）
        from src.business.mcp.mcp_search_tools import create_mcp_aware_search_tools

        search_tools = create_mcp_aware_search_tools(dynamic_manager, mcp_registry)

        def tool_factory() -> list[ToolDefinition]:
            if role_kind == "planner":
                # 规划专员：search + 规划工具（build_task_graph / list_specialists /
                # 调研工具）+ load_skill。不拿执行器协作工具（todo_update / ask_parent /
                # meeting_* / delegate_to_subagent）——深度封顶仍然成立。
                return (
                    search_tools
                    + planner_tools
                    + [load_skill_tool]
                    + dynamic_manager.get_activated_tools()
                    + mcp_registry.get_preset_tools()  # 轨道 A
                    + mcp_registry.get_activated_custom_tools()  # 轨道 B
                )
            return (
                search_tools
                + [*executor_collaboration_tools, load_skill_tool]
                + specialist_subagent_tools
                + builtin_tools
                + dynamic_manager.get_activated_tools()
                + mcp_registry.get_preset_tools()  # 轨道 A
                + mcp_registry.get_activated_custom_tools()  # 轨道 B
            )

        return tool_factory

    @staticmethod
    def schema_with_bound_task_id(schema: dict) -> dict:
        """Make taskId optional when a tool is bound to the current Task row."""
        cloned = copy.deepcopy(schema)
        parameters = cloned.get("function", {}).get("parameters", {})
        required = parameters.get("required")
        if isinstance(required, list):
            parameters["required"] = [item for item in required if item != "taskId"]
        properties = parameters.get("properties")
        if isinstance(properties, dict) and isinstance(properties.get("taskId"), dict):
            properties["taskId"]["description"] = "可省略；统一任务执行器会自动使用当前任务 ID"
        return cloned

    def build_assistant_tools(self, session_id: str) -> Callable[[], list[ToolDefinition]]:
        from src.business.agents.tools.assistant_tools import (
            ABANDON_REQUEST_GRAPH_SCHEMA,
            ANSWER_TASK_QUESTION_SCHEMA,
            ASK_USER_QUESTION_SCHEMA,
            BUILD_TASK_GRAPH_SCHEMA,
            CODIFY_AS_TOOL_SCHEMA,
            CONTINUE_SUBAGENT_SCHEMA,
            CREATE_SCHEDULED_TASK_SCHEMA,
            CREATE_SPECIALIST_SCHEMA,
            CREATE_TASK_SCHEMA,
            DECIDE_ADJUDICATION_SCHEMA,
            DELETE_SCHEDULED_TASK_SCHEMA,
            DELEGATE_TO_SPECIALIST_SCHEMA,
            DELEGATE_TO_SUBAGENT_SCHEMA,
            DISMISS_SUGGESTION,
            INSPECT_SUBAGENT_SCHEMA,
            INVALIDATE_MEMORY_ENTRY_SCHEMA,
            LIST_SCHEDULED_TASKS_SCHEMA,
            LOAD_TASK_RESULT_SCHEMA,
            MUTATE_TASK_GRAPH_SCHEMA,
            OPEN_MEETING_CHANNEL_SCHEMA,
            PAUSE_SCHEDULED_TASK_SCHEMA,
            REPLY_TO_USER_SCHEMA,
            REPORT_TOOL_BUG,
            RETRIEVE_ARCHIVE_SCHEMA,
            RETRIEVE_FAILURE_ZONE_SCHEMA,
            SAVE_PROFILE_SCHEMA,
            UPDATE_SCHEDULED_TASK_SCHEMA,
            UPDATE_TASK_SCHEMA,
            create_abandon_request_graph_handler,
            create_answer_task_question_handler,
            create_ask_user_question_handler,
            create_build_task_graph_handler,
            create_codify_as_tool_handler,
            create_continue_subagent_handler,
            create_create_scheduled_task_handler,
            create_create_specialist_handler,
            create_create_task_handler,
            create_decide_task_adjudication_handler,
            create_delete_scheduled_task_handler,
            create_delegate_to_specialist_handler,
            create_delegate_to_subagent_handler,
            create_inspect_subagent_handler,
            create_invalidate_memory_entry_handler,
            create_list_scheduled_tasks_handler,
            create_load_task_result_handler,
            create_mutate_task_graph_handler,
            create_open_meeting_channel_handler,
            create_pause_scheduled_task_handler,
            create_reply_to_user_handler,
            create_retrieve_archive_handler,
            create_retrieve_failure_zone_handler,
            create_save_profile_handler,
            create_update_scheduled_task_handler,
            create_update_task_handler,
        )
        from src.business.agents.tools.proposal_source_tools import (
            create_inspect_proposal_source_tool,
            discussion_source_tool_available,
        )
        from src.business.agents.tools.skill_methodology_tools import (
            CREATE_SKILL_METHODOLOGY_SCHEMA,
            create_create_skill_methodology_handler,
        )
        from src.business.memory.assistant_memory import (
            MEMORY_SEARCH_SCHEMA,
            memory_search_handler,
        )

        session = self._session_store.get_session(session_id)
        if session is not None:
            allowed_ids, allowed_composition_ids = session.parse_tool_ids()
        else:
            allowed_ids, allowed_composition_ids = None, None
        is_scheduled_session = bool(session is not None and getattr(session, "is_scheduled", 0))

        dynamic_manager = self._dynamic_manager_cache.get_or_create_dynamic_manager(
            session_id, allowed_ids, allowed_composition_ids
        )
        codify_tool = ToolDefinition(
            name="codify_as_tool",
            schema=CODIFY_AS_TOOL_SCHEMA,
            handler=create_codify_as_tool_handler(session_id),
        )
        save_profile_tool = ToolDefinition(
            name="save_profile",
            schema=SAVE_PROFILE_SCHEMA,
            handler=create_save_profile_handler(session_id),
        )
        memory_search_tool = ToolDefinition(
            name="memory_search",
            schema=MEMORY_SEARCH_SCHEMA,
            handler=memory_search_handler,
        )
        retrieve_archive_tool = ToolDefinition(
            name="retrieve_archive",
            schema=RETRIEVE_ARCHIVE_SCHEMA,
            handler=create_retrieve_archive_handler(session_id),
        )
        retrieve_failure_zone_tool = ToolDefinition(
            name="retrieve_failure_zone",
            schema=RETRIEVE_FAILURE_ZONE_SCHEMA,
            handler=create_retrieve_failure_zone_handler(session_id),
        )
        reply_to_user_tool = ToolDefinition(
            name="reply_to_user",
            schema=REPLY_TO_USER_SCHEMA,
            handler=create_reply_to_user_handler(session_id),
            is_interrupting=True,
        )
        delegate_to_subagent_tool = ToolDefinition(
            name="delegate_to_subagent",
            schema=DELEGATE_TO_SUBAGENT_SCHEMA,
            handler=create_delegate_to_subagent_handler(
                session_id,
                dispatch_callback=self._delegation.delegate_to_subagent,
            ),
        )
        decide_task_adjudication_tool = ToolDefinition(
            name="decide_task_adjudication",
            schema=DECIDE_ADJUDICATION_SCHEMA,
            handler=create_decide_task_adjudication_handler(session_id),
        )
        load_task_result_tool = ToolDefinition(
            name="load_task_result",
            schema=LOAD_TASK_RESULT_SCHEMA,
            handler=create_load_task_result_handler(session_id),
            has_side_effects=False,
        )
        abandon_request_graph_tool = ToolDefinition(
            name="abandon_request_graph",
            schema=ABANDON_REQUEST_GRAPH_SCHEMA,
            handler=create_abandon_request_graph_handler(session_id),
        )
        continue_subagent_tool = ToolDefinition(
            name="continue_subagent",
            schema=CONTINUE_SUBAGENT_SCHEMA,
            handler=create_continue_subagent_handler(
                session_id,
                continue_callback=self._delegation.continue_subagent,
            ),
        )
        inspect_subagent_tool = ToolDefinition(
            name="inspect_subagent",
            schema=INSPECT_SUBAGENT_SCHEMA,
            handler=create_inspect_subagent_handler(
                session_id,
                inspect_callback=self._delegation.inspect_subagent,
            ),
            has_side_effects=False,
        )
        delegate_to_specialist_tool = ToolDefinition(
            name="delegate_to_specialist",
            schema=DELEGATE_TO_SPECIALIST_SCHEMA,
            handler=create_delegate_to_specialist_handler(
                session_id,
                dispatch_callback=self._delegation.delegate_to_specialist,
            ),
        )
        create_specialist_tool = ToolDefinition(
            name="create_specialist",
            schema=CREATE_SPECIALIST_SCHEMA,
            handler=create_create_specialist_handler(session_id),
        )
        invalidate_memory_entry_tool = ToolDefinition(
            name="invalidate_memory_entry",
            schema=INVALIDATE_MEMORY_ENTRY_SCHEMA,
            handler=create_invalidate_memory_entry_handler(session_id),
        )
        ask_user_question_tool = ToolDefinition(
            name="ask_user_question",
            schema=ASK_USER_QUESTION_SCHEMA,
            handler=create_ask_user_question_handler(session_id),
            requires_exclusive_call=True,
            has_side_effects=False,
        )
        answer_task_question_tool = ToolDefinition(
            name="answer_task_question",
            schema=ANSWER_TASK_QUESTION_SCHEMA,
            handler=create_answer_task_question_handler(
                redispatch_callback=self._redispatch_answered_task
            ),
        )
        open_meeting_channel_tool = ToolDefinition(
            name="open_meeting_channel",
            schema=OPEN_MEETING_CHANNEL_SCHEMA,
            handler=create_open_meeting_channel_handler(),
        )
        create_skill_methodology_tool = ToolDefinition(
            name="create_skill_methodology",
            schema=CREATE_SKILL_METHODOLOGY_SCHEMA,
            handler=create_create_skill_methodology_handler(
                caller_type="assistant",
                caller_id=ASSISTANT_ENTITY_ID,
            ),
        )
        load_skill_methodology_tool = self.make_load_skill_tool(
            caller_type="assistant",
            caller_id=ASSISTANT_ENTITY_ID,
        )

        # 024: build_task_graph + mutate_task_graph 工具
        # scheduler 已在 orchestrator init 时装配（runtime -> _get_task_dispatcher -> _wire_graph_scheduler），
        # 无需 per-call 重新确认。
        build_task_graph_tool = ToolDefinition(
            name="build_task_graph",
            schema=BUILD_TASK_GRAPH_SCHEMA,
            handler=create_build_task_graph_handler(session_id),
        )
        create_task_tool = ToolDefinition(
            name="create_task",
            schema=CREATE_TASK_SCHEMA,
            handler=create_create_task_handler(session_id),
        )
        update_task_tool = ToolDefinition(
            name="update_task",
            schema=UPDATE_TASK_SCHEMA,
            handler=create_update_task_handler(session_id),
        )
        mutate_task_graph_tool = ToolDefinition(
            name="mutate_task_graph",
            schema=MUTATE_TASK_GRAPH_SCHEMA,
            handler=create_mutate_task_graph_handler(session_id),
        )
        # 033 调度中心：5 个主助理独占工具（不进 delegated executor）
        create_scheduled_task_tool = ToolDefinition(
            name="create_scheduled_task",
            schema=CREATE_SCHEDULED_TASK_SCHEMA,
            handler=create_create_scheduled_task_handler(session_id),
        )
        list_scheduled_tasks_tool = ToolDefinition(
            name="list_scheduled_tasks",
            schema=LIST_SCHEDULED_TASKS_SCHEMA,
            handler=create_list_scheduled_tasks_handler(),
            has_side_effects=False,
        )
        update_scheduled_task_tool = ToolDefinition(
            name="update_scheduled_task",
            schema=UPDATE_SCHEDULED_TASK_SCHEMA,
            handler=create_update_scheduled_task_handler(),
        )
        pause_scheduled_task_tool = ToolDefinition(
            name="pause_scheduled_task",
            schema=PAUSE_SCHEDULED_TASK_SCHEMA,
            handler=create_pause_scheduled_task_handler(),
        )
        delete_scheduled_task_tool = ToolDefinition(
            name="delete_scheduled_task",
            schema=DELETE_SCHEDULED_TASK_SCHEMA,
            handler=create_delete_scheduled_task_handler(),
        )
        inspect_proposal_source_tool = create_inspect_proposal_source_tool(session_id)

        # 027: MCP 工具注入 — 预置全量 + 自定义激活
        from src.business.mcp import get_mcp_tool_registry

        mcp_registry = get_mcp_tool_registry()

        # 027-T029: MCP-aware search_tools（含 MCP kind 和 server_slug 过滤）
        from src.business.mcp.mcp_search_tools import create_mcp_aware_search_tools

        search_tools = create_mcp_aware_search_tools(dynamic_manager, mcp_registry)

        scheduled_management_tools = (
            []
            if is_scheduled_session
            else [
                create_scheduled_task_tool,
                list_scheduled_tasks_tool,
                update_scheduled_task_tool,
                pause_scheduled_task_tool,
                delete_scheduled_task_tool,
            ]
        )
        static_tools = [
            REPORT_TOOL_BUG,
            save_profile_tool,
            codify_tool,
            DISMISS_SUGGESTION,
            memory_search_tool,
            retrieve_archive_tool,
            retrieve_failure_zone_tool,
            invalidate_memory_entry_tool,
            ask_user_question_tool,
            reply_to_user_tool,
            delegate_to_subagent_tool,
            decide_task_adjudication_tool,
            load_task_result_tool,
            abandon_request_graph_tool,
            answer_task_question_tool,
            continue_subagent_tool,
            inspect_subagent_tool,
            delegate_to_specialist_tool,
            open_meeting_channel_tool,
            create_specialist_tool,
            create_skill_methodology_tool,
            load_skill_methodology_tool,
            build_task_graph_tool,
            create_task_tool,
            update_task_tool,
            mutate_task_graph_tool,
        ] + scheduled_management_tools

        def tool_factory() -> list[ToolDefinition]:
            proposal_discussion_tools = (
                [inspect_proposal_source_tool]
                if discussion_source_tool_available(session_id)
                else []
            )
            return (
                search_tools
                + static_tools
                + proposal_discussion_tools
                + dynamic_manager.get_activated_tools()
                + mcp_registry.get_preset_tools()  # 轨道 A：预置全量
                + mcp_registry.get_activated_custom_tools()  # 轨道 B：自定义激活
            )

        return tool_factory
