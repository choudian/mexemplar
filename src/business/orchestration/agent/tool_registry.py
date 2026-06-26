"""Tool registry for agent tool schemas and handler factories."""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any

from src.business.agents.config import AgentType, ToolDefinition
from src.business.agents.tools.desktop_tools import create_desktop_specific_tools
from src.business.agents.tools.pm_output_tools import report_code_issue, submit_requirements
from src.business.agents.tools.programmer_tools import submit_code, syntax_check
from src.business.agents.tools.recording_data_tools import create_recording_tools
from src.business.agents.tools.trial_tools import create_desktop_trial_tools, create_trial_tools
from src.data.repos.skill_equipment_repository import ASSISTANT_ENTITY_ID
from src.recording.browser.recorder import RecordingMode


class ToolRegistry:
    """Builds per-agent tool lists while Orchestrator owns runtime state."""

    def __init__(self, owner: Any) -> None:
        self._owner = owner

    def build_tools(
        self,
        agent_type: str,
        workflow_id: str | None = None,
        session_id: str | None = None,
    ) -> list[ToolDefinition] | Callable[[], list[ToolDefinition]]:
        if agent_type == AgentType.ASSISTANT:
            return self.build_assistant_tools(session_id or "")
        mode = self._owner._recording_mode(workflow_id)
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
        agent_type: str | None = None,
        executor_id: str | None = None,
        specialist_id: str | None = None,
        allowed_methodology_skill_ids: set[str] | None = None,
        current_task_id: str | None = None,
        parent_session_id: str | None = None,
        role_kind: str = "executor",
    ) -> Callable[[], list[ToolDefinition]]:
        """Build tools for delegated executors (specialists / ephemeral subagents).

        024 扩展：role_kind 参数控制工具分支。
        - 'executor'（默认）：拿 todo_update / ask_parent / meeting 等执行器工具
        - 'planner'：只拿 build_task_graph（规划变体），不拿执行器工具
        """
        from src.business.agents.tools.assistant_tools import (
            ASK_PARENT_SCHEMA,
            BUILD_TASK_GRAPH_SCHEMA,
            DELEGATE_TO_SUBAGENT_SCHEMA,
            MEETING_SEND_MESSAGE_SCHEMA,
            TODO_UPDATE_SCHEMA,
            create_ask_parent_handler,
            create_build_task_graph_handler,
            create_delegate_to_subagent_handler,
            create_meeting_send_message_handler,
            create_todo_update_handler,
        )
        from src.business.agents.tools.builtin_general_tools import BUILTIN_GENERAL_TOOLS
        from src.business.agents.tools.dynamic_tool_manager import (
            DynamicToolManager,
            create_assistant_search_tools,
        )

        dynamic_manager = DynamicToolManager(allowed_tool_ids=allowed_tool_ids)
        search_tools = create_assistant_search_tools(dynamic_manager)
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
        executor_collaboration_tools: list[ToolDefinition] = [
            *ask_parent_meeting_tools,
            ToolDefinition(
                name=todo_schema["function"]["name"],
                schema=todo_schema,
                handler=create_todo_update_handler(
                    executor_type=executor_type,
                    executor_id=todo_executor_id,
                    bound_task_id=current_task_id,
                ),
            ),
        ]

        specialist_subagent_tools: list[ToolDefinition] = []
        if agent_type == AgentType.SPECIALIST:
            spawned_state = {"used": False}

            def _specialist_subagent_callback(
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
                if spawned_state["used"]:
                    return {
                        "success": False,
                        "message": "专员至多只能起一个临时子代理用于隔离上下文，本次已用尽。",
                        "delegation_type": "ephemeral_subagent",
                    }
                spawned_state["used"] = True
                return self._owner._run_sync_ephemeral_subagent(
                    parent_session_id=parent_session_id,
                    task=task,
                    execution_context=execution_context,
                    tool_whitelist=tool_whitelist,
                )

            specialist_subagent_tools = [
                ToolDefinition(
                    name="delegate_to_subagent",
                    schema=DELEGATE_TO_SUBAGENT_SCHEMA,
                    handler=create_delegate_to_subagent_handler(
                        executor_id or "",
                        dispatch_callback=_specialist_subagent_callback,
                    ),
                )
            ]

        # 024: planner 角色分支——规划专员只拿 build_task_graph，不拿执行器工具
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
            ]

        def tool_factory() -> list[ToolDefinition]:
            if role_kind == "planner":
                # 规划专员：search + build_task_graph + load_skill + 通用工具
                return (
                    search_tools
                    + planner_tools
                    + [load_skill_tool]
                    + BUILTIN_GENERAL_TOOLS
                    + dynamic_manager.get_activated_tools()
                )
            return (
                search_tools
                + [*executor_collaboration_tools, load_skill_tool]
                + specialist_subagent_tools
                + BUILTIN_GENERAL_TOOLS
                + dynamic_manager.get_activated_tools()
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
            properties["taskId"]["description"] = (
                "可省略；统一任务执行器会自动使用当前任务 ID"
            )
        return cloned

    def build_assistant_tools(self, session_id: str) -> Callable[[], list[ToolDefinition]]:
        from src.business.agents.tools.assistant_tools import (
            ABANDON_REQUEST_GRAPH_SCHEMA,
            ANSWER_TASK_QUESTION_SCHEMA,
            ASK_USER_QUESTION_SCHEMA,
            BUILD_TASK_GRAPH_SCHEMA,
            CODIFY_AS_TOOL_SCHEMA,
            CONTINUE_SUBAGENT_SCHEMA,
            CREATE_SPECIALIST_SCHEMA,
            DECIDE_ADJUDICATION_SCHEMA,
            DELEGATE_TO_SPECIALIST_SCHEMA,
            DELEGATE_TO_SUBAGENT_SCHEMA,
            DISMISS_SUGGESTION,
            INSPECT_SUBAGENT_SCHEMA,
            INVALIDATE_MEMORY_ENTRY_SCHEMA,
            MUTATE_TASK_GRAPH_SCHEMA,
            OPEN_MEETING_CHANNEL_SCHEMA,
            REPLY_TO_USER_SCHEMA,
            REPORT_TOOL_BUG,
            RETRIEVE_ARCHIVE_SCHEMA,
            RETRIEVE_FAILURE_ZONE_SCHEMA,
            SAVE_PROFILE_SCHEMA,
            create_abandon_request_graph_handler,
            create_answer_task_question_handler,
            create_ask_user_question_handler,
            create_build_task_graph_handler,
            create_codify_as_tool_handler,
            create_continue_subagent_handler,
            create_create_specialist_handler,
            create_decide_task_adjudication_handler,
            create_delegate_to_specialist_handler,
            create_delegate_to_subagent_handler,
            create_inspect_subagent_handler,
            create_invalidate_memory_entry_handler,
            create_mutate_task_graph_handler,
            create_open_meeting_channel_handler,
            create_reply_to_user_handler,
            create_retrieve_archive_handler,
            create_retrieve_failure_zone_handler,
            create_save_profile_handler,
        )
        from src.business.agents.tools.builtin_general_tools import BUILTIN_GENERAL_TOOLS
        from src.business.agents.tools.dynamic_tool_manager import (
            DynamicToolManager,
            create_assistant_search_tools,
        )
        from src.business.agents.tools.skill_methodology_tools import (
            CREATE_SKILL_METHODOLOGY_SCHEMA,
            create_create_skill_methodology_handler,
        )
        from src.business.memory.assistant_memory import (
            MEMORY_SEARCH_SCHEMA,
            memory_search_handler,
        )

        session = self._owner._session_store.get_session(session_id)
        allowed_ids = session.get_tool_id_set() if session else None

        with self._owner._dynamic_managers_lock:
            if session_id in self._owner._dynamic_managers:
                self._owner._dynamic_managers.move_to_end(session_id)
            else:
                self._owner._dynamic_managers[session_id] = DynamicToolManager(allowed_ids)
                while len(self._owner._dynamic_managers) > self._owner._MAX_DYNAMIC_MANAGERS:
                    self._owner._dynamic_managers.popitem(last=False)
            dynamic_manager = self._owner._dynamic_managers[session_id]

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
                dispatch_callback=self._owner.delegation_orchestrator.delegate_to_subagent,
            ),
        )
        decide_task_adjudication_tool = ToolDefinition(
            name="decide_task_adjudication",
            schema=DECIDE_ADJUDICATION_SCHEMA,
            handler=create_decide_task_adjudication_handler(session_id),
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
                continue_callback=self._owner.delegation_orchestrator.continue_subagent,
            ),
        )
        inspect_subagent_tool = ToolDefinition(
            name="inspect_subagent",
            schema=INSPECT_SUBAGENT_SCHEMA,
            handler=create_inspect_subagent_handler(
                session_id,
                inspect_callback=self._owner.delegation_orchestrator.inspect_subagent,
            ),
        )
        delegate_to_specialist_tool = ToolDefinition(
            name="delegate_to_specialist",
            schema=DELEGATE_TO_SPECIALIST_SCHEMA,
            handler=create_delegate_to_specialist_handler(
                session_id,
                dispatch_callback=self._owner.delegation_orchestrator.delegate_to_specialist,
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
                redispatch_callback=self._owner._redispatch_answered_task
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
        mutate_task_graph_tool = ToolDefinition(
            name="mutate_task_graph",
            schema=MUTATE_TASK_GRAPH_SCHEMA,
            handler=create_mutate_task_graph_handler(session_id),
        )

        search_tools = create_assistant_search_tools(dynamic_manager)
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
            mutate_task_graph_tool,
        ] + BUILTIN_GENERAL_TOOLS

        def tool_factory() -> list[ToolDefinition]:
            return search_tools + static_tools + dynamic_manager.get_activated_tools()

        return tool_factory
