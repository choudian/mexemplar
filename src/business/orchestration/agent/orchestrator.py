import json
import logging
import threading
import uuid
from collections import OrderedDict
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Union

from src.business.agents.agent_loop import AgentLoop
from src.business.agents.config import (
    ASSISTANT_CONFIG,
    PM_CONFIG,
    PROGRAMMER_CONFIG,
    AgentResult,
    AgentType,
    ResultType,
    ToolDefinition,
)
from src.business.agents.tools.pm_output_tools import report_code_issue, submit_requirements
from src.business.agents.tools.programmer_tools import submit_code, syntax_check
from src.business.agents.tools.recording_data_tools import create_recording_tools
from src.business.agents.tools.trial_tools import create_trial_tools
from src.business.ai.llm_client import LangChainLLMClient
from src.data.repositories import (
    AssistantProfileRepository,
    MessageRepository,
    SessionRepository,
    TeachingFailureRepository,
    ToolRepository,
    WorkflowTransitionRepository,
)
from src.data.unified_config import UnifiedConfigManager
from src.utils.events import connect, emit

from ..llm_reviewer import LLMReviewer, ReviewResult
from .agent_session_store import AgentSessionStore
from .assistant_prompt_builder import AssistantPromptBuilder
from .assistant_task_worker import AssistantTaskWorker
from .ports import AgentExecutionPort, AssistantTaskPort, EventBusPort, ReviewStatePort
from .teaching_failure_tracker import TeachingFailureTracker
from .workflow_retry_coordinator import WorkflowRetryCoordinator

if TYPE_CHECKING:
    from src.business.agents.tools.dynamic_tool_manager import DynamicToolManager

logger = logging.getLogger(__name__)


class _EventBusAdapter(EventBusPort):
    def connect(self, event_name: str, handler):
        return connect(event_name, handler)

    def emit(self, event_name: str, sender=None, **payload) -> None:
        emit(event_name, sender=sender, **payload)


class _ReviewStateAdapter(ReviewStatePort):
    def __init__(self, review_counts: Dict[str, int]) -> None:
        self._review_counts = review_counts

    def get_retry_count(self, workflow_id: str) -> int:
        return self._review_counts.get(workflow_id, 0)

    def increment_retry_count(self, workflow_id: str) -> int:
        next_count = self._review_counts.get(workflow_id, 0) + 1
        self._review_counts[workflow_id] = next_count
        return next_count

    def clear_retry_count(self, workflow_id: str) -> None:
        self._review_counts.pop(workflow_id, None)


class _AgentExecutionAdapter(AgentExecutionPort):
    def __init__(self, run_agent: Callable, start_analysis: Callable) -> None:
        self._run_agent = run_agent
        self._start_analysis = start_analysis

    def run_agent(
        self,
        agent_type: str,
        user_input: Optional[Union[str, dict]],
        workflow_id: str = None,
        session_id: str = None,
    ) -> None:
        self._run_agent(
            agent_type,
            user_input,
            workflow_id=workflow_id,
            session_id=session_id,
        )

    def start_analysis(self, recording_id: str, workflow_id: str) -> None:
        self._start_analysis(recording_id, workflow_id)


class _AssistantTaskAdapter(AssistantTaskPort):
    def __init__(self, run_agent: Callable, start_triage: Callable) -> None:
        self._run_agent = run_agent
        self._start_triage = start_triage

    def run_agent(
        self,
        agent_type: str,
        user_input: Optional[Union[str, dict]],
        workflow_id: str = None,
        session_id: str = None,
    ) -> None:
        self._run_agent(
            agent_type,
            user_input,
            workflow_id=workflow_id,
            session_id=session_id,
        )

    def start_triage(self, tool_id: str, user_feedback: str, workflow_id: str) -> None:
        self._start_triage(tool_id, user_feedback, workflow_id)


class AgentOrchestrator:
    """
    Agent 编排器

    核心设计原则：
    - workflow_id = recording_id，一个录制对应一个工具
    - UI 只传 workflow_id，不需要保存 session_id
    - 显式调度：根据 loop.run() 返回值通过 _dispatch_next 决定下一步
    - 事件只通知不调度：事件发给 UI/日志/transition，不通过事件监听器调度
    """

    def __init__(
        self,
        llm_client: LangChainLLMClient,
        config: UnifiedConfigManager,
        llm_reviewer: Optional[LLMReviewer] = None,
    ):
        self._llm = llm_client
        self._config = config
        self._llm_reviewer = llm_reviewer or LLMReviewer(llm_client)
        self._session_repo = SessionRepository()
        self._message_repo = MessageRepository()
        self._transition_repo = WorkflowTransitionRepository()
        self._failure_repo = TeachingFailureRepository()
        self._tool_repo = ToolRepository()

        self._loops: Dict[str, AgentLoop] = {}
        self._review_counts: Dict[str, int] = {}
        self._dynamic_managers: OrderedDict[str, "DynamicToolManager"] = OrderedDict()
        self._dynamic_managers_lock = threading.Lock()
        self._MAX_DYNAMIC_MANAGERS = 20
        from src.business.services import SkillCompositionService
        self._composition_service = SkillCompositionService()

        self._event_bus = _EventBusAdapter()
        self._review_state = _ReviewStateAdapter(self._review_counts)
        self._session_store = AgentSessionStore(
            self._session_repo,
            self._message_repo,
            self._transition_repo,
            logger=logger,
        )
        self._failure_tracker = TeachingFailureTracker(
            self._failure_repo,
            self._event_bus,
            logger=logger,
        )
        self._retry_coordinator = WorkflowRetryCoordinator(
            self._failure_tracker,
            self._session_store,
            _AgentExecutionAdapter(self.run_agent, self.start_analysis),
            self._review_state,
            logger=logger,
        )
        self._task_worker = AssistantTaskWorker(
            self._tool_repo,
            _AssistantTaskAdapter(self.run_agent, self._start_triage),
            logger=logger,
        )
        self._prompt_builder = AssistantPromptBuilder(
            self._llm,
            self._session_store,
            self._tool_repo,
            self._composition_service,
            profile_repo=AssistantProfileRepository(),
            logger=logger,
        )
        self._failure_tracker.connect_signals()

    # --- Public sub-component accessors ---

    @property
    def failure_tracker(self) -> TeachingFailureTracker:
        return self._failure_tracker

    @property
    def session_store(self) -> AgentSessionStore:
        return self._session_store

    @property
    def retry_coordinator(self) -> WorkflowRetryCoordinator:
        return self._retry_coordinator

    @property
    def task_worker(self) -> AssistantTaskWorker:
        return self._task_worker

    def run_agent(
        self,
        agent_type: str,
        user_input: Optional[Union[str, dict]],
        workflow_id: str = None,
        session_id: str = None,
    ) -> None:
        if agent_type == AgentType.ASSISTANT:
            assert session_id, "assistant 类型必须传 session_id"
        elif not session_id:
            session_id = self._session_store.get_or_create_session(workflow_id, agent_type)

        try:
            loop = self._get_loop(agent_type, workflow_id=workflow_id)
        except ValueError as exc:
            logger.error(f"[Orchestrator] 无法创建 {agent_type} Loop: {exc}")
            self._emit_agent_error(
                workflow_id or "",
                session_id,
                agent_type,
                str(exc),
                "setup_error",
            )
            return

        logger.info(
            f"[Orchestrator] 启动 {agent_type} Agent: session={session_id}, workflow={workflow_id}"
        )

        tools = self._build_tools(agent_type, workflow_id=workflow_id, session_id=session_id)
        formatted_prompt = (
            self._prompt_builder.format_assistant_prompt(session_id)
            if agent_type == AgentType.ASSISTANT
            else loop.format_system_prompt(recording_id=workflow_id)
        )

        result = loop.run(
            session_id,
            user_input,
            tools=tools,
            system_prompt_override=formatted_prompt,
        )

        if result.result_type == ResultType.COMPLETED:
            if agent_type != AgentType.ASSISTANT:
                self._failure_tracker.try_resolve_failure(workflow_id)
                self._dispatch_next(agent_type, result, session_id, workflow_id)
            return

        if result.result_type == ResultType.NEEDS_USER_INPUT:
            emit(
                "agent_needs_user_input",
                sender=self,
                workflow_id=workflow_id or "",
                session_id=session_id,
                agent_type=agent_type,
                question=result.question,
            )
            return

        if result.result_type in (ResultType.ERROR, ResultType.MAX_ITERATIONS_REACHED):
            self._emit_agent_error(
                workflow_id or "",
                session_id,
                agent_type,
                result.error,
                result.result_type.value,
            )

    def start_analysis(self, recording_id: str, workflow_id: str) -> None:
        initial_input = (
            f"请分析录制 {recording_id} 的操作流程，理解用户想要自动化的任务，并与用户确认需求。"
        )
        self.run_agent(AgentType.PM, initial_input, workflow_id)

    def start_trial(self, tool_id: str, user_input: str, workflow_id: str) -> None:
        del tool_id
        self.run_agent(AgentType.TRIAL, user_input, workflow_id)

    def handle_trial_result(
        self,
        tool_id: str,
        success: bool,
        workflow_id: str,
        session_id: str,
        user_feedback: str = "",
    ) -> None:
        if success:
            tool = self._tool_repo.get_by_id(tool_id)
            if not tool:
                logger.error(f"[Orchestrator] handle_trial_result: tool {tool_id} 不存在")
                return

            new_count = (tool.trial_success_count or 0) + 1
            self._tool_repo.update_trial_success_count(tool_id, new_count)

            published = new_count >= 3
            if published:
                self._tool_repo.update_status(tool_id, "published")

            self._emit_and_log(
                event_name="trial_success",
                workflow_id=workflow_id,
                transition_data={
                    "event_type": "trial_success",
                    "from_session_id": session_id,
                    "to_session_id": None,
                    "payload": json.dumps({"success_count": new_count, "published": published}),
                },
                session_id=session_id,
                tool_id=tool_id,
                success_count=new_count,
                published=published,
            )

            if published:
                logger.info(f"[Orchestrator] 工具已发布: tool_id={tool_id}")
                emit(
                    "tool_published",
                    sender=self,
                    workflow_id=workflow_id,
                    session_id=session_id,
                    tool_id=tool_id,
                )
            else:
                remaining = 3 - new_count
                logger.info(f"[Orchestrator] 试用成功 {new_count}/3，继续试用: workflow={workflow_id}")
                self.run_agent(
                    AgentType.TRIAL,
                    f"第 {new_count} 次试用成功（共需 3 次），还需再成功 {remaining} 次。"
                    "请引导用户用不同的参数再试一次。",
                    workflow_id,
                )
            return

        pm_session_id = self._session_store.get_or_create_session(workflow_id, AgentType.PM)
        self._emit_and_log(
            event_name="trial_failed",
            workflow_id=workflow_id,
            transition_data={
                "event_type": "trial_failed",
                "from_session_id": session_id,
                "to_session_id": pm_session_id,
                "payload": json.dumps({"tool_id": tool_id, "user_feedback": user_feedback}),
            },
            session_id=session_id,
            tool_id=tool_id,
            user_feedback=user_feedback,
        )
        self._start_triage(tool_id, user_feedback, workflow_id)

    def _emit_agent_error(
        self,
        workflow_id: str,
        session_id: str,
        agent_type: str,
        error: str,
        error_type: str,
    ):
        self._emit_and_log(
            event_name="agent_error",
            workflow_id=workflow_id,
            transition_data={
                "event_type": "agent_error",
                "from_session_id": session_id,
                "to_session_id": None,
                "payload": json.dumps(
                    {"agent_type": agent_type, "error": error, "error_type": error_type}
                ),
            },
            session_id=session_id,
            agent_type=agent_type,
            error=error,
            error_type=error_type,
        )

    def _emit_and_log(
        self,
        event_name: str,
        workflow_id: str,
        transition_data: dict,
        **kwargs,
    ):
        emit(event_name, sender=self, workflow_id=workflow_id, **kwargs)
        self._session_store.record_transition(
            workflow_id,
            event_type=transition_data["event_type"],
            from_session_id=transition_data["from_session_id"],
            to_session_id=transition_data.get("to_session_id"),
            payload=transition_data.get("payload"),
        )

    def _dispatch_next(
        self,
        agent_type: str,
        result: AgentResult,
        session_id: str,
        workflow_id: str,
    ) -> None:
        try:
            if agent_type == AgentType.PM:
                self._on_pm_completed(result, session_id, workflow_id)
            elif agent_type == AgentType.PROGRAMMER:
                self._on_programmer_completed(result, session_id, workflow_id)
            elif agent_type == AgentType.TRIAL:
                self._on_trial_completed(result, session_id, workflow_id)
        except Exception as exc:
            logger.error(f"[Orchestrator] 调度失败: {exc}", exc_info=True)
            self._emit_agent_error(
                workflow_id,
                session_id,
                agent_type,
                f"调度失败: {str(exc)}",
                "dispatch_error",
            )

    def _on_pm_completed(self, result: AgentResult, session_id: str, workflow_id: str) -> None:
        if result.signal_tool and result.signal_tool.name == "submit_requirements":
            requirements = result.signal_tool.args
            programmer_session_id = self._session_store.get_or_create_session(workflow_id, AgentType.PROGRAMMER)
            self._emit_and_log(
                event_name="requirement_confirmed",
                workflow_id=workflow_id,
                transition_data={
                    "event_type": "requirement_confirmed",
                    "from_session_id": session_id,
                    "to_session_id": programmer_session_id,
                    "payload": json.dumps({"requirements": requirements}),
                },
                session_id=session_id,
                requirements_json=requirements,
            )
            self.run_agent(AgentType.PROGRAMMER, json.dumps(requirements, ensure_ascii=False), workflow_id)
            return

        if result.signal_tool and result.signal_tool.name == "report_code_issue":
            feedback = result.signal_tool.args.get("feedback", "")
            programmer_session_id = self._session_store.get_or_create_session(workflow_id, AgentType.PROGRAMMER)
            self._emit_and_log(
                event_name="triage_completed",
                workflow_id=workflow_id,
                transition_data={
                    "event_type": "triage_completed",
                    "from_session_id": session_id,
                    "to_session_id": programmer_session_id,
                    "payload": json.dumps({"triage_result": "code_issue", "feedback": feedback}),
                },
                session_id=session_id,
                triage_result="code_issue",
                feedback=feedback,
            )
            self.run_agent(AgentType.PROGRAMMER, feedback, workflow_id)
            return

        logger.warning(f"[Orchestrator] PM Agent 自然结束但未调用 signal 工具: session={session_id}")
        self._emit_agent_error(
            workflow_id,
            session_id,
            AgentType.PM,
            "PM Agent 未调用 submit_requirements 或 report_code_issue 即结束",
            "missing_signal_tool",
        )

    def _on_programmer_completed(
        self,
        result: AgentResult,
        session_id: str,
        workflow_id: str,
    ) -> None:
        if not (result.signal_tool and result.signal_tool.name == "submit_code"):
            logger.warning(f"[Orchestrator] 程序员 Agent 未调用 submit_code 即结束: session={session_id}")
            self._emit_agent_error(
                workflow_id,
                session_id,
                AgentType.PROGRAMMER,
                "程序员未通过 submit_code 提交代码",
                "missing_signal_tool",
            )
            return

        code_data = result.signal_tool.args
        code = code_data["code"]
        self._emit_and_log(
            event_name="code_completed",
            workflow_id=workflow_id,
            transition_data={
                "event_type": "code_completed",
                "from_session_id": session_id,
                "to_session_id": None,
                "payload": json.dumps({"code_length": len(code)}),
            },
            session_id=session_id,
            code=code,
        )
        self._run_review(code_data, session_id, workflow_id)

    def _on_trial_completed(self, result: AgentResult, session_id: str, workflow_id: str) -> None:
        signal_tool = result.signal_tool
        if signal_tool and signal_tool.name == "submit_trial_result":
            success = signal_tool.args["success"]
            feedback = signal_tool.args.get("feedback", "")
        else:
            logger.warning(
                f"[Orchestrator] 试用 Agent 未调用 submit_trial_result 即结束: session={session_id}"
            )
            self._emit_agent_error(
                workflow_id,
                session_id,
                AgentType.TRIAL,
                "试用 Agent 未通过 submit_trial_result 结束",
                "unexpected_completion",
            )
            return

        tool = self._tool_repo.get_by_workflow_id(workflow_id)
        if not tool:
            self._emit_agent_error(
                workflow_id,
                session_id,
                AgentType.TRIAL,
                "未找到工具",
                "tool_not_found",
            )
            return

        self.handle_trial_result(tool.tool_id, success, workflow_id, session_id, feedback)

    def _run_review(self, code_data: dict, from_session_id: str, workflow_id: str) -> None:
        code = code_data["code"]
        requirement = {
            "description": code_data.get("description", ""),
            "parameters": code_data.get("parameters", []),
        }
        retry_count = self._review_state.get_retry_count(workflow_id)
        review_result: ReviewResult = self._llm_reviewer.review(code, requirement)

        if review_result.passed:
            self._emit_and_log(
                event_name="review_passed",
                workflow_id=workflow_id,
                transition_data={
                    "event_type": "review_passed",
                    "from_session_id": from_session_id,
                    "to_session_id": None,
                    "payload": None,
                },
                session_id=from_session_id,
                code=code,
            )
            self._review_state.clear_retry_count(workflow_id)
            self._save_tool(code_data, workflow_id, from_session_id)
            return

        retry_count = self._review_state.increment_retry_count(workflow_id)
        if retry_count < 4:
            programmer_session_id = self._session_store.get_or_create_session(workflow_id, AgentType.PROGRAMMER)
            self._emit_and_log(
                event_name="review_failed",
                workflow_id=workflow_id,
                transition_data={
                    "event_type": "review_failed",
                    "from_session_id": from_session_id,
                    "to_session_id": programmer_session_id,
                    "payload": json.dumps(
                        {"retry_count": retry_count, "feedback": review_result.feedback}
                    ),
                },
                session_id=from_session_id,
                code=code,
                feedback=review_result.feedback,
                retry_count=retry_count,
                forced_save=False,
            )
            self.run_agent(
                AgentType.PROGRAMMER,
                f"[LLM Review 第 {retry_count} 次，共最多 3 次]\n\n审查意见：{review_result.feedback}",
                workflow_id,
            )
            return

        self._emit_and_log(
            event_name="review_failed",
            workflow_id=workflow_id,
            transition_data={
                "event_type": "review_failed",
                "from_session_id": from_session_id,
                "to_session_id": None,
                "payload": json.dumps(
                    {"retry_count": retry_count, "forced_save": (retry_count >= 4)}
                ),
            },
            session_id=from_session_id,
            code=code,
            feedback=review_result.feedback,
            retry_count=retry_count,
            forced_save=True,
        )
        self._review_state.clear_retry_count(workflow_id)
        self._save_tool(code_data, workflow_id, from_session_id)

    def _start_triage(self, tool_id: str, user_feedback: str, workflow_id: str) -> None:
        failure_context = (
            f"用户反馈：{user_feedback}" if user_feedback else "工具执行报错（错误详情见试用会话历史）"
        )
        initial_input = (
            f"工具 {tool_id} 试用失败，{failure_context}。"
            "请分析问题原因：如果是需求问题，请与用户重新确认需求；"
            "如果是代码问题，请直接输出用户反馈供程序员排查。"
        )
        self.run_agent(AgentType.PM, initial_input, workflow_id)


    def _build_tools(
        self,
        agent_type: str,
        workflow_id: str = None,
        session_id: str = None,
    ) -> Union[List[ToolDefinition], Callable[[], List[ToolDefinition]]]:
        if agent_type == AgentType.PM:
            return create_recording_tools(workflow_id) + [submit_requirements, report_code_issue]
        if agent_type == AgentType.PROGRAMMER:
            return create_recording_tools(workflow_id) + [syntax_check, submit_code]
        if agent_type == AgentType.TRIAL:
            return create_trial_tools(workflow_id)
        if agent_type == AgentType.ASSISTANT:
            return self._build_assistant_tools(session_id)
        return []

    def _build_assistant_tools(self, session_id: str) -> Callable[[], List[ToolDefinition]]:
        from src.business.agents.tools.assistant_tools import (
            CODIFY_AS_TOOL_SCHEMA,
            DISMISS_SUGGESTION,
            REPORT_TOOL_BUG,
            SAVE_PROFILE_SCHEMA,
            create_codify_as_tool_handler,
            create_save_profile_handler,
        )
        from src.business.agents.tools.builtin_general_tools import BUILTIN_GENERAL_TOOLS
        from src.business.agents.tools.dynamic_tool_manager import (
            DynamicToolManager,
            create_assistant_search_tools,
        )
        from src.business.memory.assistant_memory import (
            MEMORY_SEARCH_SCHEMA,
            memory_search_handler,
        )

        session = self._session_store.get_session(session_id)
        allowed_ids = session.get_tool_id_set() if session else None

        with self._dynamic_managers_lock:
            if session_id in self._dynamic_managers:
                self._dynamic_managers.move_to_end(session_id)
            else:
                self._dynamic_managers[session_id] = DynamicToolManager(allowed_ids)
                while len(self._dynamic_managers) > self._MAX_DYNAMIC_MANAGERS:
                    self._dynamic_managers.popitem(last=False)
            dynamic_manager = self._dynamic_managers[session_id]

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

        search_tools = create_assistant_search_tools(dynamic_manager)
        static_tools = [
            REPORT_TOOL_BUG,
            save_profile_tool,
            codify_tool,
            DISMISS_SUGGESTION,
            memory_search_tool,
        ] + BUILTIN_GENERAL_TOOLS

        def tool_factory() -> List[ToolDefinition]:
            return search_tools + static_tools + dynamic_manager.get_activated_tools()

        return tool_factory

    def _get_loop(self, agent_type: str, workflow_id: str = None) -> AgentLoop:
        if agent_type == AgentType.TRIAL:
            config = self._prompt_builder.build_trial_config(workflow_id)
            return AgentLoop(config, self._llm, self._config)

        if agent_type == AgentType.ASSISTANT:
            return AgentLoop(ASSISTANT_CONFIG, self._llm, self._config)

        if agent_type not in self._loops:
            configs = {AgentType.PM: PM_CONFIG, AgentType.PROGRAMMER: PROGRAMMER_CONFIG}
            if agent_type not in configs:
                raise ValueError(f"[Orchestrator] 未知 Agent 类型: {agent_type}")
            self._loops[agent_type] = AgentLoop(configs[agent_type], self._llm, self._config)
        return self._loops[agent_type]


    def _save_tool(
        self,
        code_data: dict,
        workflow_id: str,
        session_id: str,
        status: str = "pending",
    ) -> str:
        from src.data.models_sqlite import Tool

        code = code_data["code"]
        existing = self._tool_repo.get_by_workflow_id(workflow_id)
        needs_review_update = False

        if existing:
            tool_id = existing.tool_id
            old_code = existing.execution_code
            old_parameters = existing.parameters or []
            old_strategy = existing.execution_strategy
            old_status = existing.status
            existing.execution_code = code
            existing.tool_name = code_data["tool_name"]
            existing.description = code_data["description"]
            existing.parameters = code_data.get("parameters", [])
            existing.execution_strategy = code_data.get("execution_strategy")
            existing.dependencies = []
            existing.trial_success_count = 0
            existing.source = "intent"
            existing.status = status
            self._tool_repo.update(existing)
            needs_review_update = (
                old_code != existing.execution_code
                or old_parameters != (existing.parameters or [])
                or old_strategy != existing.execution_strategy
                or old_status != existing.status
            )
        else:
            new_tool = Tool(
                tool_id=str(uuid.uuid4()),
                tool_name=code_data["tool_name"],
                description=code_data["description"],
                execution_code=code,
                parameters=code_data.get("parameters", []),
                dependencies=[],
                steps=[],
                workflow_id=workflow_id,
                source="intent",
                status=status,
                trial_success_count=0,
                execution_strategy=code_data.get("execution_strategy"),
            )
            created = self._tool_repo.create(new_tool)
            tool_id = created.tool_id

        if needs_review_update:
            try:
                self._composition_service.mark_needs_review_by_tool(tool_id)
            except Exception as exc:
                logger.warning(f"[Orchestrator] 标记技能组合待复核失败: tool_id={tool_id}, error={exc}")

        trial_sessions = self._session_store.get_sessions_by_workflow(
            workflow_id,
            agent_type=AgentType.TRIAL,
        )
        from_triage = bool(trial_sessions)

        self._emit_and_log(
            event_name="tool_saved",
            workflow_id=workflow_id,
            transition_data={
                "event_type": "tool_saved",
                "from_session_id": session_id,
                "to_session_id": None,
                "payload": json.dumps({"tool_id": tool_id, "from_triage": from_triage}),
            },
            session_id=session_id,
            tool_id=tool_id,
            from_triage=from_triage,
        )

        if from_triage:
            latest_trial_session_id = trial_sessions[0].session_id if trial_sessions else None
            if latest_trial_session_id:
                self.run_agent(
                    AgentType.TRIAL,
                    "工具代码已修复，请重新执行工具试用。",
                    workflow_id=workflow_id,
                    session_id=latest_trial_session_id,
                )

        return tool_id
