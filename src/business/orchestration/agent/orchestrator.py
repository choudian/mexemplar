import json
import logging
import hashlib
import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field, replace
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
    subagent_label,
)
from src.business.brain.specialist_service import parse_tool_whitelist
from src.business.agents.tools.pm_output_tools import report_code_issue, submit_requirements
from src.business.agents.prompts.desktop_prompts import build_pm_prompt, build_programmer_prompt
from src.business.agents.tools.desktop_tools import create_desktop_specific_tools
from src.business.agents.tools.programmer_tools import submit_code, syntax_check
from src.business.agents.tools.recording_data_tools import create_recording_tools
from src.business.agents.tools.trial_tools import create_desktop_trial_tools, create_trial_tools
from src.business.ai.llm_client import LangChainLLMClient, ToolCallInfo
from src.business.memory.compression_handler import CompressionHandler
from src.business.services import SkillCompositionService
from src.data.repos.skill_equipment_repository import ASSISTANT_ENTITY_ID
from src.data.repositories import (
    AssistantProfileRepository,
    MessageRepository,
    SessionRepository,
    TeachingFailureRepository,
    ToolRepository,
    WorkflowTransitionRepository,
)
from src.data.models_sqlite import Message
from src.data.recording_repository import RecordingRepository
from src.data.unified_config import UnifiedConfigManager
from src.recording.browser.recorder import RecordingMode
from src.utils.events import connect, emit

from ..llm_reviewer import LLMReviewer, ReviewResult
from .agent_session_store import AgentSessionStore
from .assistant_prompt_builder import AssistantPromptBuilder
from .assistant_task_worker import AssistantTaskWorker
from .desktop_syntax_gate import check_code, log_terminal_failure, should_retry
from .ports import AgentExecutionPort, AssistantTaskPort, EventBusPort, ReviewStatePort
from .teaching_failure_tracker import TeachingFailureTracker
from .workflow_retry_coordinator import WorkflowRetryCoordinator

if TYPE_CHECKING:
    from src.business.agents.tools.dynamic_tool_manager import DynamicToolManager

logger = logging.getLogger(__name__)

_SUBAGENT_WORK_RULES = (
    "工作规则（必须遵守）：\n"
    "1. 严格限定在任务范围内，不要做任务描述以外的事情。\n"
    "2. 每次工具返回结果后，先评估当前已有信息是否足以完成任务。"
    "如果足够，直接输出最终结果，不要为了更全面而继续调用工具。\n"
    "3. 工具调用之间不要输出中间文字，静默使用工具，最后一次性报告结果。\n"
    "4. 不要闲聊、不要发表意见、不要建议下一步，只报告结构化的事实。\n"
    "5. 最终回复控制在 500 字以内，除非任务本身需要更长的输出。"
)

_EPHEMERAL_SUBAGENT_PROMPT = (
    "你是一个临时子代理。根据任务描述完成指定工作，完成后直接返回结果。\n"
    "\n" + _SUBAGENT_WORK_RULES
)
_LEGACY_DELEGATION_PARENT_PREFIX_LENGTH = 12


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
        assistant_continue_intent: dict | None = None,
        assistant_reuse_user_message: bool = False,
    ) -> AgentResult | None:
        optional_args = {}
        if assistant_continue_intent is not None:
            optional_args["assistant_continue_intent"] = assistant_continue_intent
        if assistant_reuse_user_message:
            optional_args["assistant_reuse_user_message"] = True
        return self._run_agent(
            agent_type,
            user_input,
            workflow_id=workflow_id,
            session_id=session_id,
            **optional_args,
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
        assistant_continue_intent: dict | None = None,
        assistant_reuse_user_message: bool = False,
    ) -> None:
        optional_args = {}
        if assistant_continue_intent is not None:
            optional_args["assistant_continue_intent"] = assistant_continue_intent
        if assistant_reuse_user_message:
            optional_args["assistant_reuse_user_message"] = True
        self._run_agent(
            agent_type,
            user_input,
            workflow_id=workflow_id,
            session_id=session_id,
            **optional_args,
        )

    def start_triage(self, tool_id: str, user_feedback: str, workflow_id: str) -> None:
        self._start_triage(tool_id, user_feedback, workflow_id)


@dataclass
class _DesktopSyntaxState:
    retry_count: int = 0
    attempts: list[str] = field(default_factory=list)
    feedbacks: list[str] = field(default_factory=list)

    def clear(self) -> None:
        self.retry_count = 0
        self.attempts.clear()
        self.feedbacks.clear()


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
        self._desktop_syntax_state: Dict[str, _DesktopSyntaxState] = {}
        self._mode_cache: Dict[str, str] = {}
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

    def _persist_assistant_input(
        self,
        session_id: str,
        user_input: str,
        *,
        system_prompt: str | None = None,
    ) -> None:
        """Persist the recoverable user turn before fallible Assistant setup continues."""
        if system_prompt is not None:
            has_system = any(
                message.role == "system" for message in self._message_repo.get_all(session_id)
            )
            if not has_system:
                self._message_repo.create(
                    Message(
                        message_id=str(uuid.uuid4()),
                        session_id=session_id,
                        sequence=self._message_repo.get_next_sequence(session_id),
                        role="system",
                        content=system_prompt,
                    )
                )
        self._message_repo.create(
            Message(
                message_id=str(uuid.uuid4()),
                session_id=session_id,
                sequence=self._message_repo.get_next_sequence(session_id),
                role="user",
                content=user_input,
            )
        )

    def run_agent(
        self,
        agent_type: str,
        user_input: Optional[Union[str, dict]],
        workflow_id: str = None,
        session_id: str = None,
        assistant_continue_intent: dict | None = None,
        assistant_reuse_user_message: bool = False,
    ) -> AgentResult | None:
        assistant_input_persisted = False
        assistant_should_persist = False
        if agent_type == AgentType.ASSISTANT:
            assert session_id, "assistant 类型必须传 session_id"
            if user_input is not None and not assistant_reuse_user_message:
                if not isinstance(user_input, str) or not user_input:
                    return AgentResult(
                        result_type=ResultType.ERROR,
                        error="assistant input must be non-empty text",
                    )
                assistant_should_persist = True
        elif not session_id:
            session_id = self._session_store.get_or_create_session(workflow_id, agent_type)

        try:
            loop = self._get_loop(agent_type, workflow_id=workflow_id)
        except Exception as exc:
            if assistant_should_persist:
                self._persist_assistant_input(session_id, user_input)
                assistant_input_persisted = True
            message = f"无法创建 {agent_type} Loop"
            logger.error("[Orchestrator] %s: %s", message, exc, exc_info=True)
            self._emit_agent_error(
                workflow_id or "",
                session_id,
                agent_type,
                message,
                "setup_error",
            )
            return AgentResult(result_type=ResultType.ERROR, error=message)

        logger.info(
            f"[Orchestrator] 启动 {agent_type} Agent: session={session_id}, workflow={workflow_id}"
        )

        try:
            formatted_prompt = (
                self._prompt_builder.format_assistant_prompt(session_id)
                if agent_type == AgentType.ASSISTANT
                else loop.format_system_prompt(recording_id=workflow_id)
            )
            if assistant_should_persist:
                self._persist_assistant_input(
                    session_id,
                    user_input,
                    system_prompt=formatted_prompt,
                )
                assistant_input_persisted = True
            tools = self._build_tools(agent_type, workflow_id=workflow_id, session_id=session_id)

            if agent_type == AgentType.ASSISTANT:
                self._seal_assistant_segment_at_memory_limit(session_id)
        except Exception as exc:
            if assistant_should_persist and not assistant_input_persisted:
                self._persist_assistant_input(session_id, user_input)
                assistant_input_persisted = True
            message = f"无法准备 {agent_type} Agent"
            logger.error("[Orchestrator] %s: %s", message, exc, exc_info=True)
            self._emit_agent_error(
                workflow_id or "",
                session_id,
                agent_type,
                message,
                "setup_error",
            )
            return AgentResult(result_type=ResultType.ERROR, error=message)

        try:
            initial_tool_calls = (
                [self._build_continue_subagent_tool_call(assistant_continue_intent)]
                if agent_type == AgentType.ASSISTANT and assistant_continue_intent
                else None
            )
            result = loop.run(
                session_id,
                user_input,
                tools=tools,
                system_prompt_override=formatted_prompt,
                initial_tool_calls=initial_tool_calls,
                resume_existing_turn=(assistant_reuse_user_message or assistant_input_persisted),
            )
        except Exception as exc:
            message = f"{agent_type} Agent 执行失败"
            logger.error("[Orchestrator] %s: %s", message, exc, exc_info=True)
            self._emit_agent_error(
                workflow_id or "",
                session_id,
                agent_type,
                message,
                "runtime_error",
            )
            return AgentResult(result_type=ResultType.ERROR, error=message)

        if result.result_type == ResultType.COMPLETED:
            if agent_type != AgentType.ASSISTANT:
                self._failure_tracker.try_resolve_failure(workflow_id)
                self._dispatch_next(agent_type, result, session_id, workflow_id)
            return result

        if result.result_type == ResultType.NEEDS_USER_INPUT:
            emit(
                "agent_needs_user_input",
                sender=self,
                workflow_id=workflow_id or "",
                session_id=session_id,
                agent_type=agent_type,
                question=result.question,
            )
            return result

        if result.result_type == ResultType.CANCELLED:
            # 用户主动停止（014）：可恢复暂停，不是错误。已产内容已落库，直接正常返回，不发 agent_error。
            logger.info("[Orchestrator] %s Agent 被用户停止: session=%s", agent_type, session_id)
            return result

        if result.result_type in (ResultType.ERROR, ResultType.MAX_ITERATIONS_REACHED):
            self._emit_agent_error(
                workflow_id or "",
                session_id,
                agent_type,
                result.error,
                result.result_type.value,
            )
        return result

    def _build_continue_subagent_tool_call(self, intent: dict) -> ToolCallInfo:
        subagent_id = str(intent.get("subagent_id") or "").strip()
        if not subagent_id:
            raise ValueError("continueSubagent.subagentId must not be empty")
        instruction = str(intent.get("instruction") or "").strip()
        args: dict[str, object] = {
            "subagent_id": subagent_id,
            "extra_iterations": int(intent.get("extra_iterations") or 20),
        }
        if instruction:
            args["instruction"] = instruction
        return ToolCallInfo(
            id=f"continue_subagent_{uuid.uuid4().hex[:12]}",
            name="continue_subagent",
            args=args,
        )

    def _seal_assistant_segment_at_memory_limit(self, session_id: str) -> Optional[str]:
        """Seal accumulated assistant messages when configured memory limits are reached."""
        try:
            messages = self._message_repo.get_context(session_id)
            if not messages or not CompressionHandler(self._config).should_compress(messages):
                return None

            from src.business.agents.tools.assistant_tools import cleanup_retrieved_context
            from src.business.brain.segment_service import SegmentService

            sealed_id = SegmentService().seal_segment(
                session_id,
                boundary_reason="token_limit",
            )
            if sealed_id:
                cleanup_retrieved_context(session_id)
                logger.info(
                    "Segment sealed via memory limit: session=%s, message_count=%d",
                    session_id,
                    len(messages),
                )
            return sealed_id
        except Exception as seg_exc:
            logger.warning("Memory-limit segment boundary check failed: %s", seg_exc)
            return None

    def _delegate_to_subagent(
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

        allowed_tool_ids = self._resolve_user_tool_ids(
            parent_session_id=parent_session_id,
            tool_whitelist=tool_whitelist,
        )
        capability_catalog_section = self._prompt_builder.format_capability_catalog(
            allowed_tool_ids,
            agent_type=AgentType.EPHEMERAL_SUBAGENT.value,
            include_descriptions=True,
        )
        system_prompt = self._build_ephemeral_subagent_prompt(
            tool_whitelist,
            capability_catalog_section=capability_catalog_section,
        )
        workflow_id = self._new_delegation_workflow_id(parent_session_id)
        child_session_id = self._session_store.create_session(
            workflow_id,
            AgentType.EPHEMERAL_SUBAGENT,
        )
        user_input = self._format_delegated_task_input(task, execution_context)
        result = self._run_delegated_executor(
            agent_type=AgentType.EPHEMERAL_SUBAGENT,
            session_id=child_session_id,
            workflow_id=workflow_id,
            parent_session_id=parent_session_id,
            user_input=user_input,
            system_prompt=system_prompt,
            allowed_tool_ids=allowed_tool_ids,
        )
        result["delegation_type"] = "ephemeral_subagent"
        result["task_description"] = task
        if result.get("success"):
            self._record_delegation_signal(
                parent_session_id=parent_session_id,
                task_pattern=task,
                result_text=str(result.get("result_text") or ""),
            )
        return result

    def _delegate_to_specialist(
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
        allowed_tool_ids = self._resolve_user_tool_ids(
            parent_session_id=parent_session_id,
            tool_whitelist=whitelist,
        )
        try:
            equipped_skills_snapshot = self._specialist_equipped_skills_snapshot(specialist)
        except RuntimeError as exc:
            logger.error("[Orchestrator] 专员方法论装备快照加载失败: %s", exc, exc_info=True)
            return {
                "success": False,
                "message": "专员方法论装备加载失败，已取消委派。",
                "delegation_type": "specialist",
                "specialist_id": specialist.specialist_id,
                "specialist_name": name,
            }
        try:
            capability_catalog_section = self._prompt_builder.format_capability_catalog(
                allowed_tool_ids,
                agent_type=AgentType.SPECIALIST.value,
                include_descriptions=True,
            )
            system_prompt = self._build_specialist_prompt(
                specialist,
                whitelist,
                equipped_skills=equipped_skills_snapshot,
                capability_catalog_section=capability_catalog_section,
            )
        except RuntimeError as exc:
            logger.error("[Orchestrator] 专员方法论提示词构建失败: %s", exc, exc_info=True)
            return {
                "success": False,
                "message": "专员方法论提示词构建失败，已取消委派。",
                "delegation_type": "specialist",
                "specialist_id": specialist.specialist_id,
                "specialist_name": name,
            }
        workflow_id = self._new_delegation_workflow_id(parent_session_id)
        child_session_id = self._session_store.create_session(workflow_id, AgentType.SPECIALIST)
        allowed_methodology_skill_ids = {
            str(item.get("skill_id") or "")
            for item in equipped_skills_snapshot
            if str(item.get("skill_id") or "")
        }
        methodology_snapshot = self._extract_methodology_equipment_snapshot(system_prompt)
        result = self._run_delegated_executor(
            agent_type=AgentType.SPECIALIST,
            session_id=child_session_id,
            workflow_id=workflow_id,
            parent_session_id=parent_session_id,
            user_input=self._format_delegated_task_input(task_text),
            system_prompt=system_prompt,
            allowed_tool_ids=allowed_tool_ids,
            specialist_id=specialist.specialist_id,
            allowed_methodology_skill_ids=allowed_methodology_skill_ids,
            methodology_equipment_snapshot=methodology_snapshot,
        )
        result["delegation_type"] = "specialist"
        result["specialist_id"] = specialist.specialist_id
        result["specialist_name"] = name
        result["task"] = task_text
        return result

    def _run_delegated_executor(
        self,
        *,
        agent_type: str,
        session_id: str,
        workflow_id: str,
        parent_session_id: str,
        user_input: str,
        system_prompt: str,
        allowed_tool_ids: set[str] | None,
        specialist_id: str | None = None,
        allowed_methodology_skill_ids: set[str] | None = None,
        methodology_equipment_snapshot: str = "",
    ) -> dict:
        start_transition_id = self._session_store.record_transition(
            workflow_id,
            event_type="assistant_delegation_started",
            from_session_id=parent_session_id,
            to_session_id=session_id,
            payload=json.dumps({"agent_type": str(agent_type)}, ensure_ascii=False),
        )
        self._capture_delegation_debug_detail(
            workflow_id=workflow_id,
            transition_id=start_transition_id,
            input_detail={
                "parentSessionId": parent_session_id,
                "executorSessionId": session_id,
                "task": user_input,
                "allowedToolCount": len(allowed_tool_ids) if allowed_tool_ids is not None else None,
                "methodologyEquipmentPromptSnapshot": methodology_equipment_snapshot,
            },
        )
        # 子任务卡片壳 + running 状态（014 US4）：归属父会话
        self._emit_subagent_started(
            parent_session_id=parent_session_id,
            subagent_id=session_id,
            agent_type=str(agent_type),
            task=user_input,
        )

        try:
            loop = self._get_loop(agent_type, workflow_id=workflow_id)
            tools = self._build_delegated_executor_tools(
                allowed_tool_ids,
                agent_type=agent_type,
                specialist_id=specialist_id,
                allowed_methodology_skill_ids=allowed_methodology_skill_ids,
            )
            result = loop.run(
                session_id,
                user_input,
                tools=tools,
                system_prompt_override=system_prompt,
            )
        except Exception as exc:
            logger.error("[Orchestrator] 委派执行失败: %s", exc, exc_info=True)
            # 将孤立 session 标记为 failed，避免 _continue_subagent 因 status=="active" 拒绝唤回。
            self._session_repo.update_status(session_id, "failed")
            failed_transition_id = self._session_store.record_transition(
                workflow_id,
                event_type="assistant_delegation_failed",
                from_session_id=session_id,
                to_session_id=parent_session_id,
                payload=json.dumps({"error": "委派执行内部错误"}, ensure_ascii=False),
            )
            self._capture_delegation_debug_detail(
                workflow_id=workflow_id,
                transition_id=failed_transition_id,
                input_detail={
                    "parentSessionId": parent_session_id,
                    "executorSessionId": session_id,
                },
                output_detail={"success": False, "error": str(exc)},
            )
            self._emit_subagent_finished(
                parent_session_id=parent_session_id,
                subagent_id=session_id,
                status="failed",
            )
            return {
                "success": False,
                "message": "委派执行内部错误，已记录详情",
                "executor_session_id": session_id,
                "workflow_id": workflow_id,
            }

        if result.result_type in (ResultType.PAUSED, ResultType.CANCELLED):
            # 子代理被迫中断（迭代超限 / LLM 失败 = PAUSED）或被用户停止（CANCELLED）但工作已保活：
            # 记暂停流转并返回可唤回句柄。该 dict 作为委派工具结果落库（含"可 continue_subagent 续跑"
            # 线索），父 loop 在下一取消检查点退出前已持久化，为"继续任务"留线索。
            cancelled = result.result_type == ResultType.CANCELLED
            reason = "用户已停止" if cancelled else result.error
            paused_transition_id = self._session_store.record_transition(
                workflow_id,
                event_type="assistant_delegation_paused",
                from_session_id=session_id,
                to_session_id=parent_session_id,
                payload=json.dumps(
                    {"subagent_id": session_id, "reason": reason},
                    ensure_ascii=False,
                ),
            )
            self._capture_delegation_debug_detail(
                workflow_id=workflow_id,
                transition_id=paused_transition_id,
                input_detail={
                    "parentSessionId": parent_session_id,
                    "executorSessionId": session_id,
                },
                output_detail={
                    "success": False,
                    "paused": True,
                    "cancelled": cancelled,
                    "resultType": result.result_type.value,
                    "reason": reason,
                },
            )
            self._emit_subagent_paused(
                parent_session_id=parent_session_id,
                subagent_id=session_id,
                reason=reason,
            )
            message = (
                f"子代理已被停止（{reason}），可用 continue_subagent 唤回续跑"
                if cancelled
                else f"子代理已暂停（{reason}），可用 continue_subagent 唤回续跑"
            )
            return {
                "success": False,
                "paused": True,
                "cancelled": cancelled,
                "subagent_id": session_id,
                "message": message,
                "executor_session_id": session_id,
                "workflow_id": workflow_id,
                "result_type": result.result_type.value,
                "reason": reason,
            }

        result_text = self._extract_latest_assistant_text(session_id)
        success = result.result_type == ResultType.COMPLETED and bool(result_text)
        payload = {
            "result_type": result.result_type.value,
            "success": success,
        }
        if result.error:
            payload["error"] = result.error
        complete_transition_id = self._session_store.record_transition(
            workflow_id,
            event_type=(
                "assistant_delegation_completed" if success else "assistant_delegation_failed"
            ),
            from_session_id=session_id,
            to_session_id=parent_session_id,
            payload=json.dumps(payload, ensure_ascii=False),
        )
        self._capture_delegation_debug_detail(
            workflow_id=workflow_id,
            transition_id=complete_transition_id,
            input_detail={"parentSessionId": parent_session_id, "executorSessionId": session_id},
            output_detail={
                "success": success,
                "resultType": result.result_type.value,
                "resultText": result_text,
                "error": result.error,
            },
        )
        self._emit_subagent_finished(
            parent_session_id=parent_session_id,
            subagent_id=session_id,
            status="done" if success else "failed",
            last_output=result_text,
        )

        response = {
            "success": success,
            "subagent_id": session_id,
            "message": "委派执行完成" if success else (result.error or "委派执行未返回可用结果"),
            "executor_session_id": session_id,
            "workflow_id": workflow_id,
            "result_type": result.result_type.value,
            "result_text": result_text,
        }
        if result.error:
            response["error"] = result.error
        return response

    def _resolve_subagent_session(self, parent_session_id: str, subagent_id: str):
        """归属校验：确认 subagent_id 是当前主代理派出的临时子代理 session。

        返回 Session（合法）或 None（不存在 / 类型不符 / 非本主代理派出），
        防止主代理传入任意 session_id 唤回或窥探他人会话。
        """
        parent_id = parent_session_id.strip() if isinstance(parent_session_id, str) else ""
        if not parent_id:
            return None
        sid = (subagent_id or "").strip()
        if not sid:
            return None
        session = self._session_store.get_session(sid)
        if session is None:
            return None
        if getattr(session, "agent_type", None) != AgentType.EPHEMERAL_SUBAGENT:
            return None
        workflow_id = getattr(session, "workflow_id", "") or ""
        transition_match = self._subagent_transition_belongs_to_parent(workflow_id, parent_id, sid)
        if transition_match is True:
            return session
        if transition_match is None:
            return None
        if self._delegation_workflow_belongs_to_parent_hash(workflow_id, parent_id):
            return session
        if self._legacy_delegation_workflow_belongs_to_unique_parent(workflow_id, parent_id):
            return session
        return None

    def _subagent_transition_belongs_to_parent(
        self,
        workflow_id: str,
        parent_session_id: str,
        subagent_id: str,
    ) -> bool | None:
        if not workflow_id:
            return False
        try:
            transitions = self._transition_repo.get_by_workflow(workflow_id)
        except Exception as exc:
            logger.warning("Subagent ownership transition lookup failed: %s", exc)
            return None
        return any(
            getattr(transition, "event_type", "") == "assistant_delegation_started"
            and getattr(transition, "from_session_id", None) == parent_session_id
            and getattr(transition, "to_session_id", None) == subagent_id
            for transition in transitions
        )

    @classmethod
    def _delegation_workflow_belongs_to_parent_hash(
        cls,
        workflow_id: str,
        parent_session_id: str,
    ) -> bool:
        try:
            parent_hash = cls._delegation_parent_hash(parent_session_id)
        except ValueError:
            return False
        return workflow_id.startswith(f"dlg_{parent_hash}_")

    def _legacy_delegation_workflow_belongs_to_unique_parent(
        self,
        workflow_id: str,
        parent_session_id: str,
    ) -> bool:
        """Compatibility for old dlg_{parent[:12]} ids without transition rows.

        The legacy prefix is ambiguous, so it is accepted only when exactly one
        stored assistant session has that prefix and it is the current parent.
        """
        legacy_prefix = parent_session_id[:_LEGACY_DELEGATION_PARENT_PREFIX_LENGTH]
        if len(legacy_prefix) < _LEGACY_DELEGATION_PARENT_PREFIX_LENGTH:
            return False
        if not workflow_id.startswith(f"dlg_{legacy_prefix}_"):
            return False
        parent_ids = self._session_store.list_session_ids_by_prefix(
            legacy_prefix,
            agent_type=AgentType.ASSISTANT,
            limit=2,
        )
        return parent_ids == [parent_session_id]

    def _continue_subagent(
        self,
        *,
        parent_session_id: str,
        subagent_id: str,
        instruction: str = "",
        extra_iterations: int = 20,
    ) -> dict:
        """唤回一个属于当前主代理的子代理续跑（从 DB 持久化历史恢复，跨进程重启亦可）。"""
        session = self._resolve_subagent_session(parent_session_id, subagent_id)
        if session is None:
            return {"success": False, "error": "未找到可唤回的子代理，请确认 subagent_id 正确"}
        if getattr(session, "status", None) == "active":
            return {
                "success": False,
                "error": "该子代理仍在运行中，暂不可唤回",
                "subagent_id": subagent_id,
            }

        from src.business.agents.config import AgentConfig

        _MAX_EXTRA_ITERATIONS = 100
        try:
            extra = int(extra_iterations)
        except (TypeError, ValueError):
            extra = 20
        extra = min(max(1, extra), _MAX_EXTRA_ITERATIONS)
        config = AgentConfig(
            agent_type=AgentType.EPHEMERAL_SUBAGENT,
            system_prompt=_EPHEMERAL_SUBAGENT_PROMPT,
            max_iterations=max(1, extra),
            resumable_on_failure=True,
        )
        loop = AgentLoop(config, self._llm, self._config)
        # 用主代理当前可用工具池重建（不强制还原原始白名单——当前可用范围对续跑同样合理）
        allowed_tool_ids = self._resolve_user_tool_ids(
            parent_session_id=parent_session_id,
            tool_whitelist=None,
        )
        tools = self._build_delegated_executor_tools(
            allowed_tool_ids,
            agent_type=AgentType.EPHEMERAL_SUBAGENT,
        )
        user_input = instruction.strip() if (instruction or "").strip() else None
        workflow_id = getattr(session, "workflow_id", "") or ""
        self._emit_subagent_started(
            parent_session_id=parent_session_id,
            subagent_id=subagent_id,
            agent_type=AgentType.EPHEMERAL_SUBAGENT,
            task=self._message_repo.get_first_user_message(subagent_id) or "继续任务",
        )
        try:
            # user_input=None 时复用 _initialize_session 的 suspended/completed → active 恢复
            result = loop.run(subagent_id, user_input, tools=tools)
        except Exception as exc:
            logger.error("[Orchestrator] 子代理续跑失败: %s", exc, exc_info=True)
            self._emit_subagent_finished(
                parent_session_id=parent_session_id,
                subagent_id=subagent_id,
                status="failed",
            )
            return {
                "success": False,
                "error": "续跑执行内部错误，已记录详情",
                "subagent_id": subagent_id,
            }

        result_text = self._extract_latest_assistant_text(subagent_id)
        if result.result_type in (ResultType.PAUSED, ResultType.CANCELLED):
            # 再次中断 / 用户停止 → 仍可重复唤回；CANCELLED 是可恢复暂停，不是失败。
            cancelled = result.result_type == ResultType.CANCELLED
            reason = "用户已停止" if cancelled else result.error
            self._session_store.record_transition(
                workflow_id,
                event_type="assistant_delegation_paused",
                from_session_id=subagent_id,
                to_session_id=parent_session_id,
                payload=json.dumps(
                    {"subagent_id": subagent_id, "reason": reason},
                    ensure_ascii=False,
                ),
            )
            self._emit_subagent_paused(
                parent_session_id=parent_session_id,
                subagent_id=subagent_id,
                reason=reason,
            )
            return {
                "success": False,
                "paused": True,
                "cancelled": cancelled,
                "subagent_id": subagent_id,
                "message": (
                    f"子代理已被停止（{reason}），可继续 continue_subagent"
                    if cancelled
                    else f"子代理再次暂停（{reason}），可继续 continue_subagent"
                ),
                "executor_session_id": subagent_id,
                "result_type": result.result_type.value,
                "reason": reason,
            }

        if result.result_type == ResultType.NEEDS_USER_INPUT:
            # 对已完成态子代理不带 instruction 唤回时，loop 立即回 NEEDS_USER_INPUT（无模型调用）。
            # 没有新指令就无从"接着跑"，给主代理明确可操作的提示而非含糊的失败。
            self._session_store.record_transition(
                workflow_id,
                event_type="assistant_delegation_resumed",
                from_session_id=subagent_id,
                to_session_id=parent_session_id,
                payload=json.dumps(
                    {"subagent_id": subagent_id, "result_type": result.result_type.value},
                    ensure_ascii=False,
                ),
            )
            self._emit_subagent_paused(
                parent_session_id=parent_session_id,
                subagent_id=subagent_id,
                reason="等待追加指令",
            )
            return {
                "success": False,
                "subagent_id": subagent_id,
                "message": (
                    "子代理已是完成态，没有追加指令无法续跑；"
                    "如需返工请用 instruction 说明要补齐/修正什么。"
                ),
                "executor_session_id": subagent_id,
                "result_type": result.result_type.value,
                "result_text": result_text,
            }

        success = result.result_type == ResultType.COMPLETED and bool(result_text)
        self._session_store.record_transition(
            workflow_id,
            event_type=(
                "assistant_delegation_completed" if success else "assistant_delegation_failed"
            ),
            from_session_id=subagent_id,
            to_session_id=parent_session_id,
            payload=json.dumps(
                {
                    "subagent_id": subagent_id,
                    "success": success,
                    "result_type": result.result_type.value,
                },
                ensure_ascii=False,
            ),
        )
        response = {
            "success": success,
            "subagent_id": subagent_id,
            "message": "子代理续跑完成" if success else (result.error or "续跑未返回可用结果"),
            "executor_session_id": subagent_id,
            "result_type": result.result_type.value,
            "result_text": result_text,
        }
        if result.error:
            response["error"] = result.error
        self._emit_subagent_finished(
            parent_session_id=parent_session_id,
            subagent_id=subagent_id,
            status="done" if success else "failed",
            last_output=result_text,
        )
        return response

    def _inspect_subagent(self, *, parent_session_id: str, subagent_id: str) -> dict:
        """返回子代理工作概览（机械统计，不触发任何模型调用）。"""
        session = self._resolve_subagent_session(parent_session_id, subagent_id)
        if session is None:
            return {"success": False, "error": "未找到可查看的子代理，请确认 subagent_id 正确"}

        messages = self._message_repo.get_context(subagent_id)
        assistant_turns = 0
        tool_call_counts: dict[str, int] = {}
        call_fingerprints: dict[tuple[str, str], int] = {}
        for msg in messages:
            if getattr(msg, "role", None) != "assistant":
                continue
            assistant_turns += 1
            raw = getattr(msg, "tool_calls", None)
            if not raw:
                continue
            try:
                for tc in json.loads(raw):
                    name = tc.get("name") if isinstance(tc, dict) else None
                    if not name:
                        continue
                    tool_call_counts[name] = tool_call_counts.get(name, 0) + 1
                    key = (name, self._fingerprint_call_args(tc.get("args")))
                    call_fingerprints[key] = call_fingerprints.get(key, 0) + 1
            except (ValueError, TypeError) as exc:
                logger.warning(
                    "[inspect_subagent] malformed tool_calls JSON: session=%s error=%s",
                    subagent_id,
                    exc,
                )
                continue

        # 同一工具被几乎相同的参数反复调用 = 原地打转的信号，用于和"调用次数多但
        # 在处理不同目标"（正常推进）区分。只回计数、不回参数明文，避免把可能含
        # 敏感内容的参数注入 assistant 上下文。
        repeated_calls = [
            {"tool": name, "count": count}
            for (name, _fp), count in sorted(
                call_fingerprints.items(), key=lambda kv: kv[1], reverse=True
            )
            if count >= 2
        ]

        return {
            "success": True,
            "subagent_id": subagent_id,
            "status": getattr(session, "status", None),
            "assistant_turns": assistant_turns,
            "tool_call_counts": tool_call_counts,
            "repeated_calls": repeated_calls,
            "last_output": self._extract_latest_assistant_text(subagent_id),
        }

    @staticmethod
    def _fingerprint_call_args(args) -> str:
        """对工具调用参数做稳定指纹，用于识别"几乎相同的参数反复调用"。

        相同参数（如反复抓同一个 URL）产生相同指纹；不同参数（抓不同目标）
        产生不同指纹。仅用于 _inspect_subagent 的重复度统计，不外泄参数明文。
        """
        try:
            return json.dumps(args, sort_keys=True, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return repr(args)

    def _capture_delegation_debug_detail(
        self,
        *,
        workflow_id: str,
        transition_id: str | None,
        input_detail: dict,
        output_detail: dict | None = None,
    ) -> None:
        try:
            from src.business.debug.service import get_debug_service

            get_debug_service().capture_delegation_detail(
                transition_id=transition_id,
                workflow_id=workflow_id,
                input_detail=input_detail,
                output_detail=output_detail,
            )
        except Exception:
            logger.debug("debug delegation detail capture failed", exc_info=True)

    @staticmethod
    def _make_load_skill_tool(
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

    def _build_delegated_executor_tools(
        self,
        allowed_tool_ids: set[str] | None,
        *,
        agent_type: str | None = None,
        specialist_id: str | None = None,
        allowed_methodology_skill_ids: set[str] | None = None,
    ) -> Callable[[], List[ToolDefinition]]:
        from src.business.agents.tools.builtin_general_tools import BUILTIN_GENERAL_TOOLS
        from src.business.agents.tools.dynamic_tool_manager import (
            DynamicToolManager,
            create_assistant_search_tools,
        )

        dynamic_manager = DynamicToolManager(allowed_tool_ids=allowed_tool_ids)
        search_tools = create_assistant_search_tools(dynamic_manager)
        load_skill_tool = self._make_load_skill_tool(
            caller_type="specialist" if agent_type == AgentType.SPECIALIST else "assistant",
            caller_id=specialist_id or ASSISTANT_ENTITY_ID,
            allowed_skill_ids=allowed_methodology_skill_ids,
        )

        def tool_factory() -> List[ToolDefinition]:
            return (
                search_tools
                + [load_skill_tool]
                + BUILTIN_GENERAL_TOOLS
                + dynamic_manager.get_activated_tools()
            )

        return tool_factory

    def _resolve_user_tool_ids(
        self,
        *,
        parent_session_id: str,
        tool_whitelist: list[str] | None,
    ) -> set[str] | None:
        parent_session = self._session_store.get_session(parent_session_id)
        parent_allowed_ids = parent_session.get_tool_id_set() if parent_session else None
        if tool_whitelist is None:
            return parent_allowed_ids

        resolved_ids: set[str] = set()
        for tool_identifier in tool_whitelist:
            if not isinstance(tool_identifier, str) or not tool_identifier.strip():
                continue
            identifier = tool_identifier.strip()
            tool = self._tool_repo.get_by_id(identifier) or self._tool_repo.get_by_name(identifier)
            if tool is None or getattr(tool, "status", None) != "published":
                continue
            if parent_allowed_ids is not None and tool.tool_id not in parent_allowed_ids:
                continue
            resolved_ids.add(tool.tool_id)
        return resolved_ids

    def _extract_latest_assistant_text(self, session_id: str) -> str:
        return self._message_repo.get_latest_assistant_text(session_id)

    @staticmethod
    def _record_delegation_signal(
        *,
        parent_session_id: str,
        task_pattern: str,
        result_text: str,
    ) -> None:
        try:
            from src.data.repos.brain_repository import BrainRepository

            summary_parts = [task_pattern.strip()[:180]]
            if result_text.strip():
                summary_parts.append(result_text.strip()[:220])
            with BrainRepository() as repo:
                repo.record_recruitment_signal(
                    task_pattern=task_pattern,
                    session_id=parent_session_id,
                    delegation_summary=" -> ".join(part for part in summary_parts if part),
                )
        except Exception as exc:
            logger.warning("Failed to record delegation recruitment signal: %s", exc)

    @staticmethod
    def _new_delegation_workflow_id(parent_session_id: str) -> str:
        return f"dlg_{AgentOrchestrator._delegation_parent_hash(parent_session_id)}_{uuid.uuid4().hex[:16]}"

    @staticmethod
    def _delegation_parent_hash(parent_session_id: str) -> str:
        parent_id = parent_session_id.strip() if isinstance(parent_session_id, str) else ""
        if not parent_id:
            raise ValueError("parent_session_id is required")
        return hashlib.sha256(parent_id.encode("utf-8")).hexdigest()[:20]

    @staticmethod
    def _format_delegated_task_input(task: str, execution_context: str = "") -> str:
        lines = [
            "主助理委派给你的任务如下：",
            "",
            task,
        ]
        if execution_context.strip():
            lines.extend(["", "补充上下文：", execution_context.strip()])
        lines.extend(
            [
                "",
                "请完成任务，并返回可以交给用户的最终结果。"
                "如果信息不足，请明确说明缺口和你已经完成的部分。",
            ]
        )
        return "\n".join(lines)

    @staticmethod
    def _build_ephemeral_subagent_prompt(
        tool_whitelist: list[str] | None,
        capability_catalog_section: str | None = None,
    ) -> str:
        whitelist_text = "、".join(tool_whitelist) if tool_whitelist else "继承主助理当前可用技能池"
        capability_section = capability_catalog_section or f"用户技能白名单：{whitelist_text}"
        return (
            "你是一个临时子代理，只为当前一次委派任务服务。\n"
            "你可以使用被授予的工具完成任务，但不要再委派给其他 Agent。\n"
            f"{capability_section}\n"
            "\n" + _SUBAGENT_WORK_RULES
        )

    @staticmethod
    def _build_specialist_prompt(
        specialist,
        whitelist: list[str],
        equipped_skills: list[dict] | None = None,
        capability_catalog_section: str | None = None,
    ) -> str:
        whitelist_text = "、".join(whitelist) if whitelist else "无用户技能白名单"
        capability_section = capability_catalog_section or f"用户技能白名单：{whitelist_text}"
        equipment_section = ""
        try:
            from src.business.brain.context_builder import BrainContextBuilder

            if equipped_skills is None:
                equipped_skills = BrainContextBuilder().equipped_skills_for_entity(
                    getattr(specialist, "specialist_id", "")
                )
            if equipped_skills:
                equipment_section = "\n\n" + BrainContextBuilder.format_equipped_skills_for_prompt(
                    equipped_skills
                )
        except Exception as exc:
            logger.error(
                "specialist methodology equipment prompt injection failed: %s", exc, exc_info=True
            )
            raise RuntimeError("specialist_methodology_equipment_prompt_unavailable") from exc
        return (
            f"你是固定专员：{getattr(specialist, 'name', '')}\n"
            f"描述：{getattr(specialist, 'description', '') or '无'}\n\n"
            "角色定义：\n"
            f"{getattr(specialist, 'role_definition', '') or '按专员职责完成主助理委派的任务。'}\n\n"
            f"{capability_section}\n"
            "你只能处理主助理委派的任务；完成后直接输出最终结果。"
            f"{equipment_section}"
        )

    @staticmethod
    def _specialist_equipped_skills_snapshot(specialist) -> list[dict]:
        try:
            from src.business.brain.context_builder import BrainContextBuilder

            return BrainContextBuilder().equipped_skills_for_entity(
                getattr(specialist, "specialist_id", "")
            )
        except Exception as exc:
            logger.error("specialist methodology equipment snapshot failed: %s", exc, exc_info=True)
            raise RuntimeError("specialist_methodology_equipment_snapshot_unavailable") from exc

    @staticmethod
    def _extract_methodology_equipment_snapshot(prompt: str) -> str:
        marker = "## 你已装备的方法论清单"
        marker_index = str(prompt or "").find(marker)
        return str(prompt or "")[marker_index:] if marker_index >= 0 else ""

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
                logger.info(
                    f"[Orchestrator] 试用成功 {new_count}/3，继续试用: workflow={workflow_id}"
                )
                self.run_agent(
                    AgentType.TRIAL,
                    {
                        "role": "program",
                        "content": (
                            f"第 {new_count} 次试用成功（共需 3 次），还需再成功 {remaining} 次。"
                            "请引导用户用不同的参数再试一次。"
                        ),
                    },
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

    def _emit_subagent_started(
        self,
        *,
        parent_session_id: str,
        subagent_id: str,
        agent_type: str,
        task: str,
    ) -> None:
        """发出子任务开始生命周期事件（014，best-effort）：卡片壳 + running 状态。"""
        emit(
            "assistant_subagent_started",
            sender=self,
            session_id=parent_session_id,
            subagent_id=subagent_id,
            label=subagent_label(agent_type),
            task=task,
            status="running",
        )

    def _emit_subagent_finished(
        self,
        *,
        parent_session_id: str,
        subagent_id: str,
        status: str,
        last_output: str | None = None,
    ) -> None:
        """发出子任务结束生命周期事件（014，best-effort）：status∈{done,failed}。"""
        emit(
            "assistant_subagent_finished",
            sender=self,
            session_id=parent_session_id,
            subagent_id=subagent_id,
            status=status,
            last_output=last_output,
        )

    def _emit_subagent_paused(
        self,
        *,
        parent_session_id: str,
        subagent_id: str,
        reason: str | None = None,
    ) -> None:
        """发出子任务暂停生命周期事件（014，best-effort）。

        session_id 取父助理会话（卡片归属父对话）；经 ui_event_projector 投影为 assistant.subagent。
        """
        emit(
            "assistant_subagent_paused",
            sender=self,
            session_id=parent_session_id,
            subagent_id=subagent_id,
            status="suspended",
            reason=reason,
        )

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
            programmer_session_id = self._session_store.get_or_create_session(
                workflow_id, AgentType.PROGRAMMER
            )
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
            self.run_agent(
                AgentType.PROGRAMMER, json.dumps(requirements, ensure_ascii=False), workflow_id
            )
            return

        if result.signal_tool and result.signal_tool.name == "report_code_issue":
            feedback = result.signal_tool.args.get("feedback", "")
            programmer_session_id = self._session_store.get_or_create_session(
                workflow_id, AgentType.PROGRAMMER
            )
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

        logger.warning(
            f"[Orchestrator] PM Agent 自然结束但未调用 signal 工具: session={session_id}"
        )
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
            logger.warning(
                f"[Orchestrator] 程序员 Agent 未调用 submit_code 即结束: session={session_id}"
            )
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
        if self._recording_mode(workflow_id) == RecordingMode.DESKTOP:
            syntax_result = check_code(code)
            if not syntax_result.ok:
                state = self._desktop_syntax_state.setdefault(workflow_id, _DesktopSyntaxState())
                state.retry_count += 1
                state.attempts.append(code)
                if syntax_result.feedback:
                    state.feedbacks.append(syntax_result.feedback)
                if should_retry(state.retry_count):
                    self.run_agent(
                        AgentType.PROGRAMMER,
                        (
                            f"[桌面语法门卫第 {state.retry_count} 次反馈]\n\n"
                            f"{syntax_result.feedback}"
                        ),
                        workflow_id,
                    )
                    return
                log_terminal_failure(
                    workflow_id,
                    state.attempts,
                    state.feedbacks,
                )
                emit(
                    "desktop_syntax_gate_retry_failed",
                    sender=self,
                    workflow_id=workflow_id,
                    session_id=session_id,
                    feedback=syntax_result.feedback,
                    lineno=syntax_result.lineno,
                    message=syntax_result.message,
                )
                self._desktop_syntax_state.pop(workflow_id, None)
                self._emit_agent_error(
                    workflow_id,
                    session_id,
                    AgentType.PROGRAMMER,
                    "Programmer 输出代码持续语法错误",
                    "desktop_syntax_error",
                )
                return
            self._desktop_syntax_state.pop(workflow_id, None)
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
        try:
            review_result: ReviewResult = self._llm_reviewer.review(code, requirement)
        except Exception as exc:
            logger.error("LLM review failed for workflow %s: %s", workflow_id, exc, exc_info=True)
            self._emit_agent_error(
                workflow_id,
                from_session_id,
                AgentType.PROGRAMMER,
                "LLM Review 调用失败",
                "review_error",
            )
            return

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
            programmer_session_id = self._session_store.get_or_create_session(
                workflow_id, AgentType.PROGRAMMER
            )
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
            f"用户反馈：{user_feedback}"
            if user_feedback
            else "工具执行报错（错误详情见试用会话历史）"
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
        if agent_type == AgentType.ASSISTANT:
            return self._build_assistant_tools(session_id)
        mode = self._recording_mode(workflow_id)
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

    def _recording_mode(self, workflow_id: str | None) -> str:
        if not workflow_id:
            return RecordingMode.BROWSER
        cached = self._mode_cache.get(workflow_id)
        if cached is not None:
            return cached
        try:
            mode = RecordingRepository().get_recording_mode(workflow_id)
        except ValueError as exc:
            logger.error(
                "[Orchestrator] 录制不存在或模式不可用: workflow_id=%s, error=%s",
                workflow_id,
                exc,
            )
            raise
        except Exception as exc:
            logger.error(
                "[Orchestrator] 读取录制模式失败: workflow_id=%s, error=%s",
                workflow_id,
                exc,
                exc_info=True,
            )
            raise RuntimeError(f"无法读取录制模式: {workflow_id}") from exc
        self._mode_cache[workflow_id] = mode
        if len(self._mode_cache) > self._MAX_DYNAMIC_MANAGERS:
            oldest = next(iter(self._mode_cache))
            del self._mode_cache[oldest]
            self._desktop_syntax_state.pop(oldest, None)
        return mode

    def _build_assistant_tools(self, session_id: str) -> Callable[[], List[ToolDefinition]]:
        from src.business.agents.tools.assistant_tools import (
            CODIFY_AS_TOOL_SCHEMA,
            CREATE_SPECIALIST_SCHEMA,
            DELEGATE_TO_SPECIALIST_SCHEMA,
            DELEGATE_TO_SUBAGENT_SCHEMA,
            CONTINUE_SUBAGENT_SCHEMA,
            INSPECT_SUBAGENT_SCHEMA,
            DISMISS_SUGGESTION,
            INVALIDATE_MEMORY_ENTRY_SCHEMA,
            REPORT_TOOL_BUG,
            REPLY_TO_USER_SCHEMA,
            RETRIEVE_ARCHIVE_SCHEMA,
            RETRIEVE_FAILURE_ZONE_SCHEMA,
            SAVE_PROFILE_SCHEMA,
            ASK_USER_QUESTION_SCHEMA,
            create_ask_user_question_handler,
            create_codify_as_tool_handler,
            create_create_specialist_handler,
            create_delegate_to_specialist_handler,
            create_delegate_to_subagent_handler,
            create_continue_subagent_handler,
            create_inspect_subagent_handler,
            create_invalidate_memory_entry_handler,
            create_reply_to_user_handler,
            create_retrieve_archive_handler,
            create_retrieve_failure_zone_handler,
            create_save_profile_handler,
        )
        from src.business.agents.tools.skill_methodology_tools import (
            CREATE_SKILL_METHODOLOGY_SCHEMA,
            create_create_skill_methodology_handler,
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
                dispatch_callback=self._delegate_to_subagent,
            ),
        )
        continue_subagent_tool = ToolDefinition(
            name="continue_subagent",
            schema=CONTINUE_SUBAGENT_SCHEMA,
            handler=create_continue_subagent_handler(
                session_id,
                continue_callback=self._continue_subagent,
            ),
        )
        inspect_subagent_tool = ToolDefinition(
            name="inspect_subagent",
            schema=INSPECT_SUBAGENT_SCHEMA,
            handler=create_inspect_subagent_handler(
                session_id,
                inspect_callback=self._inspect_subagent,
            ),
        )
        delegate_to_specialist_tool = ToolDefinition(
            name="delegate_to_specialist",
            schema=DELEGATE_TO_SPECIALIST_SCHEMA,
            handler=create_delegate_to_specialist_handler(
                session_id,
                dispatch_callback=self._delegate_to_specialist,
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
            # 需独占调用：与其他工具同批 → 全批 invalid_model_output；非中断，拿到答案同回合续跑。
            requires_exclusive_call=True,
            has_side_effects=False,
        )
        create_skill_methodology_tool = ToolDefinition(
            name="create_skill_methodology",
            schema=CREATE_SKILL_METHODOLOGY_SCHEMA,
            handler=create_create_skill_methodology_handler(
                caller_type="assistant",
                caller_id=ASSISTANT_ENTITY_ID,
            ),
        )
        load_skill_methodology_tool = self._make_load_skill_tool(
            caller_type="assistant",
            caller_id=ASSISTANT_ENTITY_ID,
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
            continue_subagent_tool,
            inspect_subagent_tool,
            delegate_to_specialist_tool,
            create_specialist_tool,
            create_skill_methodology_tool,
            load_skill_methodology_tool,
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

        if agent_type == AgentType.EPHEMERAL_SUBAGENT:
            from src.business.agents.config import AgentConfig

            ephemeral_config = AgentConfig(
                agent_type=AgentType.EPHEMERAL_SUBAGENT,
                system_prompt=_EPHEMERAL_SUBAGENT_PROMPT,
                max_iterations=50,
                resumable_on_failure=True,
            )
            return AgentLoop(ephemeral_config, self._llm, self._config)

        if agent_type == AgentType.SPECIALIST:
            from src.business.agents.config import AgentConfig

            specialist_config = AgentConfig(
                agent_type=AgentType.SPECIALIST,
                system_prompt="你是一个固定专员。根据你的角色定义完成指定工作。",
                max_iterations=30,
            )
            return AgentLoop(specialist_config, self._llm, self._config)

        mode = self._recording_mode(workflow_id)
        if agent_type == AgentType.PM:
            config = replace(PM_CONFIG, system_prompt=build_pm_prompt(mode))
            return AgentLoop(config, self._llm, self._config)
        if agent_type == AgentType.PROGRAMMER:
            config = replace(PROGRAMMER_CONFIG, system_prompt=build_programmer_prompt(mode))
            return AgentLoop(config, self._llm, self._config)
        raise ValueError(f"[Orchestrator] 未知 Agent 类型: {agent_type}")

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
                logger.warning(
                    f"[Orchestrator] 标记技能组合待复核失败: tool_id={tool_id}, error={exc}"
                )

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
