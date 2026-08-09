import json
import logging
import hashlib
import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Callable, Dict, List, Optional, Union

from src.utils.events import emit
from src.data.repos.base_repository import ID_PREFIX_TASK, ID_PREFIX_GRAPH

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
from src.business.agents.delegation_context import normalize_delegated_execution_context
from src.business.agents.prompts.desktop_prompts import build_pm_prompt, build_programmer_prompt
from src.business.ai.llm_client import LangChainLLMClient, ToolCallInfo
from src.business.memory.compression_handler import CompressionHandler
from src.business.services import SkillCompositionService
from src.data.models_sqlite import Message
from src.data.recording_repository import RecordingRepository
from src.data.unified_config import UnifiedConfigManager
from src.recording.browser.recorder import RecordingMode

from ..llm_reviewer import LLMReviewer
from .agent_session_store import AgentSessionStore
from .subagent_scope import EffectiveSubagentScope
from .orchestrator_repos import OrchestratorRepos, default_orchestrator_repos
from .assistant_prompt_builder import AssistantPromptBuilder
from .assistant_task_worker import AssistantTaskWorker
from .delegation_orchestrator import DelegationOrchestrator
from .teaching_orchestrator import TeachingOrchestrator
from .teaching_failure_tracker import TeachingFailureTracker
from .tool_registry import ToolRegistry
from .workflow_retry_coordinator import WorkflowRetryCoordinator

if TYPE_CHECKING:
    from src.business.agents.tools.dynamic_tool_manager import DynamicToolManager

logger = logging.getLogger(__name__)

_SUBAGENT_WORK_RULES = (
    "工作规则（必须遵守）：\n"
    "1. 严格限定在任务范围内，不要做任务描述以外的事情。\n"
    "2. 每次工具返回结果后，先评估当前已有信息是否足以完成任务。"
    "如果足够，直接输出最终结果，不要为了更全面而继续调用工具。"
    "如果任务需要先规划再执行（多步复杂任务），可以先用 todo_update 列出计划再逐步执行。\n"
    "3. 多步任务中可以适度输出关键进度信息，帮助上级理解执行状态；"
    "简单任务仍静默使用工具，最后一次性报告结果。\n"
    "4. 不要闲聊、不要发表意见、不要建议下一步，只报告结构化的事实。\n"
    "5. 最终回复控制在 500 字以内，除非任务本身需要更长的输出。"
)

_EPHEMERAL_SUBAGENT_PROMPT = (
    "你是一个临时子代理。根据任务描述完成指定工作，完成后直接返回结果。\n"
    "\n" + _SUBAGENT_WORK_RULES
)
_LEGACY_DELEGATION_PARENT_PREFIX_LENGTH = 12


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
        llm_client: Optional[LangChainLLMClient] = None,
        config: Optional[UnifiedConfigManager] = None,
        llm_reviewer: Optional[LLMReviewer] = None,
        repos: Optional[OrchestratorRepos] = None,
        recording_repo: Optional[RecordingRepository] = None,
    ):
        # ``llm_client`` 是可选注入覆盖：测试传 mock 时记住以便 AgentLoop 直接用；
        # 生产路径不传（或传 None），由 ``_make_llm()`` 在每个工作单元边界基于最新
        # 配置现组装，使 AI 配置变更无需重启 sidecar 即可热生效。
        # 为向后兼容既有调用（``AgentOrchestrator(mock_llm, mock_config)``），
        # ``llm_client`` 仍为第一个位置参数；生产构造走 keyword ``config=``。
        self._llm_override = llm_client
        self._config = config
        self._llm_reviewer = llm_reviewer or LLMReviewer()
        self._repos = repos or default_orchestrator_repos()
        self._session_repo = self._repos.session_repo
        self._message_repo = self._repos.message_repo
        self._transition_repo = self._repos.transition_repo
        self._failure_repo = self._repos.failure_repo
        self._tool_repo = self._repos.tool_repo
        self._task_repo = self._repos.task_repo
        self._brain_repo = self._repos.brain_repo
        self._recording_repo = recording_repo

        self._loops: Dict[str, AgentLoop] = {}
        self._review_counts: Dict[str, int] = {}
        self._dynamic_managers: OrderedDict[str, "DynamicToolManager"] = OrderedDict()
        self._dynamic_managers_lock = threading.Lock()
        self._MAX_DYNAMIC_MANAGERS = 20
        self._desktop_syntax_state: Dict[str, _DesktopSyntaxState] = {}
        self._mode_cache: Dict[str, str] = {}
        self._composition_service = SkillCompositionService()

        self._session_store = AgentSessionStore(
            self._session_repo,
            self._message_repo,
            self._transition_repo,
            logger=logger,
        )
        self._failure_tracker = TeachingFailureTracker(
            self._failure_repo,
            logger=logger,
        )
        self._retry_coordinator = WorkflowRetryCoordinator(
            self._failure_tracker,
            self._session_store,
            self.run_agent,
            self.start_analysis,
            self._review_counts,
            logger=logger,
        )
        self._task_worker = AssistantTaskWorker(
            self._tool_repo,
            self.run_agent,
            self._start_triage,
            logger=logger,
        )
        self._prompt_builder = AssistantPromptBuilder(
            None,
            self._session_store,
            self._tool_repo,
            self._composition_service,
            profile_repo=self._repos.profile_repo,
            logger=logger,
        )
        self._teaching_orchestrator = TeachingOrchestrator(self)
        self._delegation_orchestrator = DelegationOrchestrator(self)
        self._tool_registry = self._build_tool_registry()
        self._failure_tracker.connect_signals()

    def _make_llm(self) -> LangChainLLMClient:
        """基于当前主 ai 配置现组装一个 LLM 客户端（不缓存）。

        每个 AgentLoop 构造时调用一次、整轮复用，使配置（model/api_key/base_url 等）
        变更在下一个工作单元立即生效。测试注入路径（``__init__`` 传入 mock）会
        短路返回该 mock，不触发真实组装。
        """
        if self._llm_override is not None:
            return self._llm_override
        config = self._config
        return LangChainLLMClient(
            provider=config.get_ai_provider(),
            model=config.get_ai_model(),
            api_key=config.get_ai_api_key(),
            base_url=config.get_ai_base_url(),
            temperature=config.get_ai_temperature(),
            max_tokens=config.get_ai_max_tokens(),
            thinking_level=config.get_ai_thinking_level(),
            timeout=config.get_ai_request_timeout(),
        )

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
    def teaching_orchestrator(self) -> TeachingOrchestrator:
        return self._get_teaching_orchestrator()

    @property
    def tool_registry(self) -> ToolRegistry:
        return self._get_tool_registry()

    @property
    def delegation_orchestrator(self) -> DelegationOrchestrator:
        return self._get_delegation_orchestrator()

    @property
    def task_worker(self) -> AssistantTaskWorker:
        return self._task_worker

    def _get_teaching_orchestrator(self) -> TeachingOrchestrator:
        teaching = getattr(self, "_teaching_orchestrator", None)
        if teaching is None:
            teaching = TeachingOrchestrator(self)
            self._teaching_orchestrator = teaching
        return teaching

    def get_or_create_dynamic_manager(
        self,
        session_id: str,
        allowed_ids: set[str] | None,
        allowed_composition_ids: set[str] | None = None,
    ) -> "DynamicToolManager":
        """返回 session 级 DynamicToolManager(命中复用,LRU 容量淘汰)。

        缓存命中时比较授权集合：如果 allowed_ids 或 allowed_composition_ids
        与缓存 manager 不同，则更新 manager 的授权集合并重新校验已激活工具，
        确保 prompt catalog 与 runtime discovery 使用一致的授权事实。
        仅 miss 时新建 manager。threading.Lock 保护 OrderedDict,锁不可重入。
        """
        from src.business.agents.tools.dynamic_tool_manager import DynamicToolManager

        with self._dynamic_managers_lock:
            if session_id in self._dynamic_managers:
                self._dynamic_managers.move_to_end(session_id)
                manager = self._dynamic_managers[session_id]
                # 授权漂移修复：命中时比较并更新授权集合
                if manager.update_authorization(allowed_ids, allowed_composition_ids):
                    logger.info(
                        "[Orchestrator] Authorization drift detected for session %s; "
                        "updated dynamic manager (tool_ids=%s, composition_ids=%s)",
                        session_id,
                        "full" if allowed_ids is None else f"{len(allowed_ids)} items",
                        (
                            "full"
                            if allowed_composition_ids is None
                            else f"{len(allowed_composition_ids)} items"
                        ),
                    )
                    # 授权变更后重新校验已激活工具，移除不再授权的条目
                    manager.get_activated_tools()
            else:
                self._dynamic_managers[session_id] = DynamicToolManager(
                    allowed_ids,
                    allowed_composition_ids=allowed_composition_ids,
                )
                while len(self._dynamic_managers) > self._MAX_DYNAMIC_MANAGERS:
                    self._dynamic_managers.popitem(last=False)
            return self._dynamic_managers[session_id]

    def _build_tool_registry(self) -> ToolRegistry:
        return ToolRegistry(
            session_store=self._session_store,
            dynamic_manager_cache=self,
            delegation_orchestrator=self._get_delegation_orchestrator(),
            resolve_recording_mode=self._recording_mode,
            redispatch_answered_task=self._redispatch_answered_task,
        )

    def _get_tool_registry(self) -> ToolRegistry:
        registry = getattr(self, "_tool_registry", None)
        if registry is None:
            registry = self._build_tool_registry()
            self._tool_registry = registry
        return registry

    def _get_delegation_orchestrator(self) -> DelegationOrchestrator:
        delegation = getattr(self, "_delegation_orchestrator", None)
        if delegation is None:
            delegation = DelegationOrchestrator(self)
            self._delegation_orchestrator = delegation
        return delegation

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
                if isinstance(user_input, dict):
                    if not user_input.get("role") or not user_input.get("content"):
                        return AgentResult(
                            result_type=ResultType.ERROR,
                            error="assistant dict input must have 'role' and 'content'",
                        )
                elif not isinstance(user_input, str) or not user_input:
                    return AgentResult(
                        result_type=ResultType.ERROR,
                        error="assistant input must be non-empty text",
                    )
                else:
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
            self._maybe_enqueue_execution_review(agent_type, session_id, failed=False)
            if agent_type != AgentType.ASSISTANT:
                self._failure_tracker.try_resolve_failure(workflow_id)
                self.teaching_orchestrator.dispatch_next(
                    agent_type,
                    result,
                    session_id,
                    workflow_id,
                )
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
            self._maybe_enqueue_execution_review(agent_type, session_id, failed=False)
            return result

        if result.result_type in (ResultType.ERROR, ResultType.MAX_ITERATIONS_REACHED):
            self._maybe_enqueue_execution_review(agent_type, session_id, failed=True)
            self._emit_agent_error(
                workflow_id or "",
                session_id,
                agent_type,
                result.error,
                result.result_type.value,
            )
        return result

    def _maybe_enqueue_execution_review(
        self,
        agent_type: AgentType,
        session_id: str,
        *,
        failed: bool,
    ) -> None:
        if agent_type != AgentType.ASSISTANT:
            return
        try:
            from src.business.self_improvement.execution_review_trigger import (
                enqueue_from_session,
            )

            enqueue_from_session(session_id, failed=failed)
        except Exception:
            logger.warning("Execution review enqueue failed", exc_info=True)

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

    def _dispatch_task_via_unified_model(
        self,
        *,
        parent_session_id: str,
        task: str,
        context: str,
        assignee_type: str,
        assignee_id: str | None,
        capability_scope: list[str] | None = None,
        user_task_id: str | None = None,
    ) -> dict | None:
        """Durably enqueue an Assistant task when the v15 task model is explicitly enabled.

        Returns ``None`` on feature-flag off or on any infrastructure failure,
        so callers fall back to the stable sync delegation path.
        """
        config = getattr(self, "_config", None)
        if config is None or config.get_assistant_tasks_unified_dispatch_enabled() is not True:
            return None

        try:
            from src.business.task_collaboration.service import TaskCollaborationService

            service = TaskCollaborationService()
            try:
                # 任务图按当前用户请求（最新一条 user 消息的 sequence）隔离：同一次请求内的多次
                # 委派复用同一张图，新请求开新图，不把新任务粘到上一条消息的旧图上。
                message_repo = getattr(self, "_message_repo", None)
                request_sequence = (
                    message_repo.get_latest_user_message_sequence(parent_session_id)
                    if message_repo is not None
                    else None
                )
                graph_id, root_task_id = service.get_or_create_request_graph_root(
                    session_id=parent_session_id,
                    user_message_sequence=request_sequence,
                    title="Assistant request",
                    description=task,
                    user_task_id=user_task_id,
                )

                dispatcher = self._get_task_dispatcher()
                result = dispatcher.delegate_task(
                    service=service,
                    graph_id=graph_id,
                    session_id=parent_session_id,
                    parent_task_id=root_task_id,
                    task=task,
                    context=context,
                    assignee_type=assignee_type,
                    assignee_id=assignee_id,
                    capability_scope=json.dumps(capability_scope or [], ensure_ascii=False),
                )
            finally:
                service.close()
        except Exception:
            logger.error(
                "[_dispatch_task_via_unified_model] unified dispatch failed, falling back to sync",
                exc_info=True,
            )
            return None
        # 任务已 durable 入图。非阻塞派发执行：start_attempt_async 把 executor
        # （TaskExecutorAdapter → _run_delegated_executor）提交到 dispatcher 线程池，主助理
        # 线程不阻塞（FR-003 真并行 / FR-004 非阻塞回流）。start 失败不回退同步路径——任务已
        # 持久化为 pending_dispatch，由 background recovery 或后续 redispatch 兜底。
        try:
            self._start_unified_attempt(
                dispatcher,
                task_id=result["taskId"],
                assignee_type=assignee_type,
                assignee_id=assignee_id,
            )
        except Exception:
            logger.error(
                "[_dispatch_task_via_unified_model] start_attempt_async failed; task %s remains pending",
                result.get("taskId"),
                exc_info=True,
            )
        try:
            dispatcher.start_fallback_attempts(session_id=parent_session_id)
        except Exception:
            logger.error(
                "[_dispatch_task_via_unified_model] fallback dispatch scan failed",
                exc_info=True,
            )
        return {
            **result,
            "success": True,
            "message": (
                "任务已受理并异步执行。请用 reply_to_user 向用户说明正在处理并结束本轮；"
                "子代理结果完成后会自动回流，届时用 decide_task_adjudication 裁定。"
                "在结果回流前不要调用 continue_subagent/inspect_subagent。"
            ),
        }

    def _start_unified_attempt(
        self,
        dispatcher,
        *,
        task_id: str,
        assignee_type: str,
        assignee_id: str | None,
        checkpoint_ref: str | None = None,
    ) -> None:
        """非阻塞派发：建 attempt + 置 running + 提交 executor 到 dispatcher 线程池。

        executor_id 取 capacity=1 语义：specialist 用 specialist_id（同一专员串行），
        ephemeral 用 task_id（每任务一执行者，天然唯一、互不冲突）。
        """
        executor_id = (
            assignee_id if assignee_type == AgentType.SPECIALIST.value and assignee_id else task_id
        )
        dispatcher.start_attempt_async(
            task_id=task_id,
            executor_type=assignee_type,
            executor_id=executor_id,
            lease_owner="unified_dispatch",
            checkpoint_ref=checkpoint_ref,
        )

    def resume_pending_graph_tasks(self, *, session_id: str, graph_id: str) -> int:
        return self._get_task_dispatcher().start_pending_graph_tasks(
            session_id=session_id,
            graph_id=graph_id,
        )

    def resume_recovered_task(self, *, task_id: str, checkpoint_ref: str) -> bool:
        task = self._task_repo.get_task(task_id)
        if task is None or not task.assignee_type:
            return False
        try:
            self._start_unified_attempt(
                self._get_task_dispatcher(),
                task_id=task.task_id,
                assignee_type=task.assignee_type,
                assignee_id=task.assignee_id,
                checkpoint_ref=checkpoint_ref,
            )
        except Exception:
            logger.error("[Orchestrator] recovered task resume failed: %s", task_id, exc_info=True)
            return False
        return True

    def _redispatch_answered_task(self, task_id: str) -> bool:
        task = self._task_repo.get_task(task_id)
        if task is None or task.status != "pending_dispatch" or not task.assignee_type:
            return False
        try:
            self._start_unified_attempt(
                self._get_task_dispatcher(),
                task_id=task.task_id,
                assignee_type=task.assignee_type,
                assignee_id=task.assignee_id,
            )
        except Exception:
            logger.error(
                "[Orchestrator] answered task redispatch failed: %s", task_id, exc_info=True
            )
            return False
        return True

    def _get_task_dispatcher(self):
        """Return a cached TaskDispatcher wired with the unified-model executor and
        parent reentry callback.

        dispatcher 不持有 service/session（delegate_task 由调用方传入当次 service），
        因此跨请求复用安全——否则缓存会持有第一次注入、随后被 close 的 service，
        导致第二次起统一派发静默失败、回退同步路径。executor_callback /
        parent_reentry_callback 在首次构造时固化，故 ``set_parent_reentry_callback``
        必须在首次 unified dispatch 前调用（runtime 创建 orchestrator 后立即注入）。
        """
        dispatcher = getattr(self, "_task_dispatcher", None)
        if dispatcher is None:
            from src.business.orchestration.agent.task_executor_adapter import (
                TaskExecutorAdapter,
            )
            from src.business.task_collaboration.dispatcher import TaskDispatcher

            dispatcher = TaskDispatcher(
                executor_callback=TaskExecutorAdapter(
                    self,
                    orchestrator_factory=self._new_task_executor_orchestrator,
                ),
                parent_reentry_callback=getattr(self, "_parent_reentry_callback", None),
            )
            self._task_dispatcher = dispatcher
            self._wire_graph_scheduler(dispatcher)
        return dispatcher

    def _wire_graph_scheduler(self, dispatcher) -> None:
        """024: 装配 GraphScheduler 单例并注入 dispatcher 回调（FR-006 运行时推进）。

        scheduler 推进用临时 TaskCollaborationService（per-operation fresh session），
        dispatcher 长生命周期复用；reentry_sink 由 AssistantRuntime 经 ``set_reentry_sink``
        在 sink 安装后注入（runtime 装配早于首次 dispatch）。
        """
        from src.business.task_collaboration.graph_scheduler import (
            GraphScheduler,
            install_graph_scheduler_event_subscriptions,
            set_graph_scheduler,
        )

        scheduler = GraphScheduler(
            dispatcher=dispatcher,
            reentry_sink=getattr(self, "_reentry_sink", None),
        )
        dispatcher.set_scheduler_callback(scheduler.on_attempt_outcome)
        set_graph_scheduler(scheduler)
        install_graph_scheduler_event_subscriptions()

    def _new_task_executor_orchestrator(self) -> "AgentOrchestrator":
        """Create a per-attempt orchestrator so dispatcher workers do not share repo sessions."""
        orchestrator = type(self)(
            config=self._config,
            llm_client=self._llm_override,
            llm_reviewer=self._llm_reviewer,
        )
        callback = getattr(self, "_parent_reentry_callback", None)
        if callback is not None:
            orchestrator.set_parent_reentry_callback(callback)
        return orchestrator

    def set_parent_reentry_callback(self, callback) -> None:
        """注入父侧回流回调（``ParentReentrySink.dispatch``）。

        由 AssistantRuntime 在创建本 orchestrator 后立即调用；dispatcher 首次构造时读取
        此值并缓存，故必须在任何 unified dispatch 之前设置。
        """
        self._parent_reentry_callback = callback

    def set_reentry_sink(self, sink) -> None:
        """024: 注入 ParentReentrySink 对象（供 GraphScheduler 全图完成通知）。

        由 AssistantRuntime._install_reentry_sink 在建 sink 后调用；GraphScheduler 在
        首次 dispatcher 构造时读取此值。scheduler 已装配时同步注入。
        """
        self._reentry_sink = sink
        from src.business.task_collaboration.graph_scheduler import get_graph_scheduler

        scheduler = get_graph_scheduler()
        if scheduler is not None:
            scheduler.set_reentry_sink(sink)

    def _delegate_to_subagent(
        self,
        *,
        parent_session_id: str,
        task_description: str,
        user_task_id: str,
        execution_context: str = "",
        tool_whitelist: list[str] | None = None,
        complexity: str = "complex",
    ) -> dict:
        return self._get_delegation_orchestrator().delegate_to_subagent(
            parent_session_id=parent_session_id,
            task_description=task_description,
            execution_context=execution_context,
            tool_whitelist=tool_whitelist,
            complexity=complexity,
            user_task_id=user_task_id,
        )

    def _run_sync_ephemeral_subagent(
        self,
        *,
        parent_session_id: str,
        task: str,
        execution_context: str = "",
        tool_whitelist: list[str] | None = None,
        workspace_root: str | None = None,
        effective_scope: EffectiveSubagentScope | None = None,
    ) -> dict:
        return self._get_delegation_orchestrator().run_sync_ephemeral_subagent(
            parent_session_id=parent_session_id,
            task=task,
            execution_context=execution_context,
            tool_whitelist=tool_whitelist,
            workspace_root=workspace_root,
            effective_scope=effective_scope,
        )

    def _delegate_to_specialist(
        self,
        *,
        parent_session_id: str,
        specialist_name: str,
        task: str,
        user_task_id: str,
        execution_context: str = "",
    ) -> dict:
        return self._get_delegation_orchestrator().delegate_to_specialist(
            parent_session_id=parent_session_id,
            specialist_name=specialist_name,
            task=task,
            execution_context=execution_context,
            user_task_id=user_task_id,
        )

    @staticmethod
    def _bind_executor_session_to_attempt(current_task_id: str | None, session_id: str) -> None:
        """把执行体会话绑定到该任务当前 active attempt；无 task 时整体跳过。

        绑不上说明这个任务此刻已没有 active attempt（被围栏、已终态或图被取消）。
        这时执行体本就不该代表该任务说话，让归属校验按事实拒绝它即可——不在这里
        中止执行，避免把一个独立的生命周期问题混进委派路径。
        """
        if not current_task_id:
            return
        from src.data.repos import AssistantTaskAttemptRepository

        try:
            with AssistantTaskAttemptRepository() as attempts:
                bound = attempts.bind_session(
                    task_id=current_task_id, executor_session_id=session_id
                )
        except Exception:
            logger.warning(
                "[Orchestrator] 执行会话绑定失败: task=%s", current_task_id, exc_info=True
            )
            return
        if not bound:
            logger.warning(
                "[Orchestrator] 任务无 active attempt，执行会话未绑定: task=%s", current_task_id
            )

    @staticmethod
    def _is_executor_running(executor_session_id: str) -> bool:
        """查 attempt 表判断执行体当前是否在跑（status ∈ active）。

        替代旧的 ``session.status == "active"`` 判断——session.status 是持久化字符串，
        进程重启后可能是假的；attempt 有租约/心跳/唯一索引，是"在不在跑"的可靠信息源。
        """
        from src.data.repos import AssistantTaskAttemptRepository

        try:
            with AssistantTaskAttemptRepository() as attempts:
                latest = attempts.latest_attempt_for_session(executor_session_id)
            if latest is None:
                return False
            return latest.status in AssistantTaskAttemptRepository.ACTIVE_STATUSES
        except Exception:
            logger.warning(
                "[Orchestrator] 查执行体运行状态失败: session=%s", executor_session_id, exc_info=True
            )
            return False

    @staticmethod
    def _build_delegated_pause_payload(
        result: AgentResult,
        *,
        session_id: str,
        workflow_id: str,
    ) -> dict:
        """把结构化 Agent 暂停结果投影成委派执行边界的安全 payload。"""
        cancelled = result.result_type == ResultType.CANCELLED
        reason = "用户已停止" if cancelled else result.error
        message = (
            f"子代理已被停止（{reason}），可用 continue_subagent 唤回续跑"
            if cancelled
            else f"子代理已暂停（{reason}），可用 continue_subagent 唤回续跑"
        )
        payload = {
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
        # 结构化暂停原因随结果上行：父侧靠它区分“跑到预算了”（可追加轮次）、
        # “额度耗尽”（等用户充值）和其他外部恢复；仅凭 reason 文本无法可靠区分。
        if not cancelled and result.pause_reason:
            payload["pause_reason"] = result.pause_reason
            if result.iterations_used is not None:
                payload["iterations_used"] = result.iterations_used
            if result.max_iterations is not None:
                payload["max_iterations"] = result.max_iterations
        return payload

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
        tool_whitelist: list[str] | None = None,
        specialist_id: str | None = None,
        allowed_methodology_skill_ids: set[str] | None = None,
        methodology_equipment_snapshot: str = "",
        current_task_id: str | None = None,
        role_kind: str = "executor",
        workspace_root: str | None = None,
        allowed_composition_ids: set[str] | None = None,
        allowed_builtin_tool_names: set[str] | None = None,
        iteration_budget: int | None = None,
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

        # 派活先于执行体创建，attempt 的 executor_id 对临时子代理只能填任务 id 顶替，
        # "此刻谁在干这活"因此在库里不存在。在 loop 启动前把本会话绑上去——必须早于
        # 第一次工具调用，否则 ask_parent / todo_update 的归属校验仍然查无此人。
        self._bind_executor_session_to_attempt(current_task_id, session_id)

        try:
            loop = self._get_loop(
                agent_type,
                workflow_id=workflow_id,
                workspace_root=workspace_root,
                max_iterations_override=iteration_budget,
            )
            tools = self._build_delegated_executor_tools(
                allowed_tool_ids,
                tool_whitelist=tool_whitelist,
                agent_type=agent_type,
                executor_id=session_id,
                specialist_id=specialist_id,
                allowed_methodology_skill_ids=allowed_methodology_skill_ids,
                current_task_id=current_task_id,
                parent_session_id=parent_session_id,
                role_kind=role_kind,
                allowed_composition_ids=allowed_composition_ids,
                allowed_builtin_tool_names=allowed_builtin_tool_names,
                workspace_root=workspace_root,
            )
            # 消息水位线：记录跑之前的消息序号，续跑后交付物只取此线之后的（034 先例）。
            # 非续跑时 baseline=0，after_sequence=0 等价于"取全部"。
            baseline_sequence = self._message_repo.get_next_sequence(session_id) - 1
            result = loop.run(
                session_id,
                user_input,
                tools=tools,
                system_prompt_override=system_prompt,
            )
        except Exception as exc:
            # 这里是**唯一还握着执行体真异常**的地方：再往上一层，它会被重新包成一个
            # 通用 RuntimeError，类型信息就没了（UI 上那个只有一个词的 "RuntimeError"
            # 就是这么来的）。所以「这是不是代码缺陷」必须在这一层判，判完把结论作为
            # 字段带出去——下游只读结论，不再需要异常本身。
            from src.business.services.assistant_failure_classifier import (
                classify_assistant_failure,
            )

            classified = classify_assistant_failure(exception=exc)
            logger.error(
                "[Orchestrator] 委派执行失败 session=%s class=%s type=%s",
                session_id,
                classified.category,
                classified.exception_type,
                exc_info=True,
            )
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
                # 不再是一句写死的"内部错误…是否重试"——那句话对代码缺陷是假的，
                # 而主助理正是照着它重试了 7 次（7/28 实跑）。改成按分类给真话。
                "message": classified.message,
                "failure_class": classified.category,
                "failure_exception_type": classified.exception_type,
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
            return self._build_delegated_pause_payload(
                result,
                session_id=session_id,
                workflow_id=workflow_id,
            )

        if (
            result.result_type == ResultType.NEEDS_USER_INPUT
            and getattr(result.signal_tool, "name", None) == "ask_parent"
        ):
            reason = "等待派活方答复"
            signal_args = getattr(result.signal_tool, "args", {}) or {}
            try:
                signal_payload = json.loads(getattr(result.signal_tool, "display_text", "") or "{}")
            except (TypeError, ValueError):
                signal_payload = {}
            question_summary = str(signal_args.get("question") or "").strip()
            paused_transition_id = self._session_store.record_transition(
                workflow_id,
                event_type="assistant_delegation_paused",
                from_session_id=session_id,
                to_session_id=parent_session_id,
                payload=json.dumps(
                    {
                        "subagent_id": session_id,
                        "reason": reason,
                        "tool": "ask_parent",
                    },
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
                    "cancelled": False,
                    "resultType": result.result_type.value,
                    "reason": reason,
                    "tool": "ask_parent",
                },
            )
            self._emit_subagent_paused(
                parent_session_id=parent_session_id,
                subagent_id=session_id,
                reason=reason,
            )
            return {
                "success": False,
                "paused": True,
                "cancelled": False,
                "subagent_id": session_id,
                "message": "子代理已暂停，等待派活方答复。",
                "executor_session_id": session_id,
                "workflow_id": workflow_id,
                "result_type": result.result_type.value,
                "reason": reason,
                "suspend_reason": "waiting_system",
                "reentry_type": "task_question",
                "question_id": signal_payload.get("questionId"),
                "question_kind": signal_payload.get("kind") or signal_args.get("kind"),
                "safe_summary": question_summary or "子任务正在等待派活方答复。",
            }

        result_text = self._extract_latest_assistant_text(
            session_id, after_sequence=baseline_sequence
        )
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

    @staticmethod
    def _reject_async_task_id(subagent_id: str) -> dict | None:
        """异步委派返回的是 taskId/graphId（tsk_/tg_ 前缀），不是可唤回子代理的 session id。

        主助理若误把异步委派的 taskId 传给 continue/inspect，只会得到无意义的"未找到"，
        甚至误判子代理挂掉而自行重做。这里在归属校验之前直接拦截，给出明确指引：
        异步任务应等结果回流 + decide_task_adjudication，不要用这两个工具。
        """
        sid = (subagent_id or "").strip()
        if sid.startswith((ID_PREFIX_TASK, ID_PREFIX_GRAPH)):
            return {
                "success": False,
                "error": (
                    "传入的是任务ID（taskId/graphId），不是可唤回的子代理ID。"
                    "异步委派的子代理请等待结果回流提示，到达后用 decide_task_adjudication 裁定，"
                    "不要用本工具。"
                ),
            }
        return None

    # 可被 inspect/continue 的执行体类型。专员与临时子代理都由
    # ``_new_delegation_workflow_id`` 生成 ``dlg_<父会话哈希>_<随机>`` 形式的
    # workflow_id，故下方三层归属校验对两者同样成立，无需分叉。
    _RESUMABLE_EXECUTOR_TYPES = (
        AgentType.EPHEMERAL_SUBAGENT,
        AgentType.SPECIALIST,
    )

    def _resolve_subagent_session(self, parent_session_id: str, subagent_id: str):
        """归属校验：确认 subagent_id 是当前主代理派出的执行体 session。

        返回 Session（合法）或 None（不存在 / 类型不符 / 非本主代理派出），
        防止主代理传入任意 session_id 唤回或窥探他人会话。

        专员再派出的子代理归属于专员会话，主代理越级查看仍被拒——正是该校验要守的边界。
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
        if getattr(session, "agent_type", None) not in self._RESUMABLE_EXECUTOR_TYPES:
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
        workspace_root: str | None = None,
        effective_scope: EffectiveSubagentScope | None = None,
    ) -> dict:
        """唤回一个属于当前主代理的子代理续跑（从 DB 持久化历史恢复，跨进程重启亦可）。

        workspace_root 透传到续跑 AgentConfig：proposal executor 节点 suspended 后经
        checkpoint 续跑时必须沿用隔离 worktree，否则 agent_loop 回退 cwd 击穿沙箱。
        """
        rejection = self._reject_async_task_id(subagent_id)
        if rejection is not None:
            return rejection
        session = self._resolve_subagent_session(parent_session_id, subagent_id)
        if session is None:
            return {"success": False, "error": "未找到可唤回的子代理，请确认 subagent_id 正确"}
        # "在不在跑"查 attempt（有租约/唯一索引保证），不读 session.status（进程重启后是假的）。
        if self._is_executor_running(subagent_id):
            return {
                "success": False,
                "error": "该子代理仍在运行中，暂不可唤回",
                "subagent_id": subagent_id,
            }

        from pathlib import Path

        from src.business.agents.config import AgentConfig

        _MAX_EXTRA_ITERATIONS = 100
        try:
            extra = int(extra_iterations)
        except (TypeError, ValueError):
            extra = 20
        extra = min(max(1, extra), _MAX_EXTRA_ITERATIONS)
        if effective_scope is not None:
            # Same-run specialist continuation: the closure supplies the exact object
            # captured before first launch.  Revalidate publication/availability only
            # to tighten it; never reconstruct authority from the parent session.
            allowed_tool_ids = self._resolve_tool_ids_with_upper_bound(
                tool_whitelist=list(effective_scope.dynamic_tool_ids),
                upper_bound_ids=set(effective_scope.dynamic_tool_ids),
                materialize_snapshot=True,
            )
            allowed_composition_ids = self._resolve_available_composition_ids(
                set(effective_scope.composition_ids)
            )
            allowed_builtin_tool_names: set[str] | None = set(effective_scope.builtin_names)
            effective_workspace_root = effective_scope.workspace_root
        else:
            # Main-assistant continuation keeps its established cross-process behavior.
            allowed_tool_ids = self._resolve_user_tool_ids(
                parent_session_id=parent_session_id,
                tool_whitelist=None,
            )
            allowed_composition_ids = None
            allowed_builtin_tool_names = None
            effective_workspace_root = workspace_root

        config = AgentConfig(
            agent_type=AgentType.EPHEMERAL_SUBAGENT,
            system_prompt=_EPHEMERAL_SUBAGENT_PROMPT,
            max_iterations=max(1, extra),
            resumable_on_failure=True,
            workspace_root=(Path(effective_workspace_root) if effective_workspace_root else None),
        )
        loop = AgentLoop(config, self._make_llm(), self._config)
        tools = self._build_delegated_executor_tools(
            allowed_tool_ids,
            agent_type=AgentType.EPHEMERAL_SUBAGENT,
            executor_id=subagent_id,
            allowed_composition_ids=allowed_composition_ids,
            allowed_builtin_tool_names=allowed_builtin_tool_names,
            workspace_root=effective_workspace_root,
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
        rejection = self._reject_async_task_id(subagent_id)
        if rejection is not None:
            return rejection
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
        return ToolRegistry.make_load_skill_tool(
            caller_type=caller_type,
            caller_id=caller_id,
            allowed_skill_ids=allowed_skill_ids,
        )

    def _build_delegated_executor_tools(
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
    ) -> Callable[[], List[ToolDefinition]]:
        return self.tool_registry.build_delegated_executor_tools(
            allowed_tool_ids,
            tool_whitelist=tool_whitelist,
            agent_type=agent_type,
            executor_id=executor_id,
            specialist_id=specialist_id,
            allowed_methodology_skill_ids=allowed_methodology_skill_ids,
            current_task_id=current_task_id,
            parent_session_id=parent_session_id,
            role_kind=role_kind,
            allowed_composition_ids=allowed_composition_ids,
            allowed_builtin_tool_names=allowed_builtin_tool_names,
            workspace_root=workspace_root,
        )

    @staticmethod
    def _schema_with_bound_task_id(schema: dict) -> dict:
        return ToolRegistry.schema_with_bound_task_id(schema)

    def _resolve_user_tool_ids(
        self,
        *,
        parent_session_id: str,
        tool_whitelist: list[str] | None,
    ) -> set[str] | None:
        parent_session = self._session_store.get_session(parent_session_id)
        parent_allowed_ids = parent_session.get_tool_id_set() if parent_session else None
        return self._resolve_tool_ids_with_upper_bound(
            tool_whitelist=tool_whitelist,
            upper_bound_ids=parent_allowed_ids,
        )

    def _resolve_tool_ids_with_upper_bound(
        self,
        *,
        tool_whitelist: list[str] | None,
        upper_bound_ids: set[str] | None,
        materialize_snapshot: bool = False,
    ) -> set[str] | None:
        """Resolve published tools under an explicit authority ceiling."""

        if tool_whitelist is None:
            if upper_bound_ids is not None:
                if not materialize_snapshot:
                    return set(upper_bound_ids)
                # A specialist may launch its child long after its own scope was
                # resolved.  Materialized snapshots must therefore drop members
                # unpublished in that interval instead of copying stale IDs.
                tool_whitelist = list(upper_bound_ids)
            if not materialize_snapshot:
                return None
            if upper_bound_ids is None:
                return {tool.tool_id for tool in self._tool_repo.get_all_published()}
        resolved_ids: set[str] = set()
        for tool_identifier in tool_whitelist:
            if not isinstance(tool_identifier, str) or not tool_identifier.strip():
                continue
            identifier = tool_identifier.strip()
            tool = self._tool_repo.get_by_id(identifier) or self._tool_repo.get_by_name(identifier)
            if tool is None or getattr(tool, "status", None) != "published":
                continue
            if upper_bound_ids is not None and tool.tool_id not in upper_bound_ids:
                continue
            resolved_ids.add(tool.tool_id)
        return resolved_ids

    def _resolve_available_composition_ids(
        self,
        upper_bound_ids: set[str] | None,
    ) -> set[str]:
        """Materialize or tighten composition authority against current availability."""

        candidate_ids = (
            set(upper_bound_ids)
            if upper_bound_ids is not None
            else {
                composition.composition_id
                for composition in self._composition_service.list_compositions()
            }
        )
        return {
            composition_id
            for composition_id in candidate_ids
            if self._composition_service.get_execution_snapshot(composition_id) is not None
        }

    def _extract_latest_assistant_text(
        self, session_id: str, *, after_sequence: int | None = None
    ) -> str:
        return self._message_repo.get_latest_assistant_text(
            session_id, after_sequence=after_sequence
        )

    def _record_delegation_signal(
        self,
        *,
        parent_session_id: str,
        task_pattern: str,
        result_text: str,
    ) -> None:
        try:
            summary_parts = [task_pattern.strip()[:180]]
            if result_text.strip():
                summary_parts.append(result_text.strip()[:220])
            self._brain_repo.record_recruitment_signal(
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
        normalized_context = normalize_delegated_execution_context(execution_context)
        lines = [
            "主助理委派给你的任务如下：",
            "",
            task,
        ]
        if normalized_context:
            lines.extend(["", "补充上下文：", normalized_context])
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

        # 规划专员要为节点填 assigneeId，必须看得到可用专员目录。条目少时全量注入，
        # 超阈值只给发现说明、改由 list_specialists 查询。加载失败降级为提示文本，
        # 不中断委派——没有目录时规划仍可进行，只是所有节点退化成临时子代理。
        specialists_section = ""
        if (getattr(specialist, "role_kind", "executor") or "executor") == "planner":
            try:
                from src.business.brain.assistant_facades import AssistantSpecialistToolFacade
                from src.business.brain.context_builder import BrainContextBuilder

                catalog = AssistantSpecialistToolFacade().list_active(
                    exclude_specialist_id=getattr(specialist, "specialist_id", ""),
                    limit=1000,
                )
                specialists_section = "\n\n" + BrainContextBuilder.format_specialists_for_prompt(
                    catalog.get("specialists") or [],
                    exclude_specialist_id=getattr(specialist, "specialist_id", ""),
                )
            except Exception as exc:
                logger.warning("planner specialist catalog injection failed: %s", exc)
                specialists_section = (
                    "\n\n## 可用专员\n\n"
                    "专员目录暂时不可用；本轮不要假定专员清单完整，"
                    "可调用 `list_specialists` 重试，或把节点留给临时子代理执行。"
                )

        return (
            f"你是固定专员：{getattr(specialist, 'name', '')}\n"
            f"描述：{getattr(specialist, 'description', '') or '无'}\n\n"
            "角色定义：\n"
            f"{getattr(specialist, 'role_definition', '') or '按专员职责完成主助理委派的任务。'}\n\n"
            f"{capability_section}\n"
            "你只能处理主助理委派的任务；完成后直接输出最终结果。\n"
            "如需把会产生大量噪音的子工作（如批量读取、嘈杂检索）隔离出去，可用 "
            "delegate_to_subagent 起临时子代理代办、只取其干净结果。系统保证同一次专员运行内"
            "同时只会有一个临时子代理在跑；需要时可以先后起多个。临时子代理不能再向下委派或找平级。"
            f"{equipment_section}"
            f"{specialists_section}"
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
        return self.teaching_orchestrator.start_analysis(recording_id, workflow_id)

    def start_trial(self, tool_id: str, user_input: str, workflow_id: str) -> None:
        return self.teaching_orchestrator.start_trial(tool_id, user_input, workflow_id)

    def handle_trial_result(
        self,
        tool_id: str,
        success: bool,
        workflow_id: str,
        session_id: str,
        user_feedback: str = "",
    ) -> None:
        return self.teaching_orchestrator.handle_trial_result(
            tool_id,
            success,
            workflow_id,
            session_id,
            user_feedback,
        )

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
        return self.teaching_orchestrator.dispatch_next(
            agent_type,
            result,
            session_id,
            workflow_id,
        )

    def _on_pm_completed(self, result: AgentResult, session_id: str, workflow_id: str) -> None:
        return self.teaching_orchestrator.on_pm_completed(result, session_id, workflow_id)

    def _on_programmer_completed(
        self,
        result: AgentResult,
        session_id: str,
        workflow_id: str,
    ) -> None:
        return self.teaching_orchestrator.on_programmer_completed(
            result,
            session_id,
            workflow_id,
        )

    def _on_trial_completed(self, result: AgentResult, session_id: str, workflow_id: str) -> None:
        return self.teaching_orchestrator.on_trial_completed(result, session_id, workflow_id)

    def _run_review(self, code_data: dict, from_session_id: str, workflow_id: str) -> None:
        return self.teaching_orchestrator.run_review(code_data, from_session_id, workflow_id)

    def _start_triage(self, tool_id: str, user_feedback: str, workflow_id: str) -> None:
        return self.teaching_orchestrator.start_triage(tool_id, user_feedback, workflow_id)

    def _build_tools(
        self,
        agent_type: str,
        workflow_id: str = None,
        session_id: str = None,
    ) -> Union[List[ToolDefinition], Callable[[], List[ToolDefinition]]]:
        return self.tool_registry.build_tools(
            agent_type,
            workflow_id=workflow_id,
            session_id=session_id,
        )

    def _recording_mode(self, workflow_id: str | None) -> str:
        if not workflow_id:
            return RecordingMode.BROWSER
        cached = self._mode_cache.get(workflow_id)
        if cached is not None:
            return cached
        try:
            mode = (self._recording_repo or RecordingRepository()).get_recording_mode(workflow_id)
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
        return self.tool_registry.build_assistant_tools(session_id)

    def _get_loop(
        self,
        agent_type: str,
        workflow_id: str = None,
        workspace_root: str | None = None,
        max_iterations_override: int | None = None,
    ) -> AgentLoop:
        if agent_type == AgentType.TRIAL:
            config = self._prompt_builder.build_trial_config(workflow_id)
            return AgentLoop(config, self._make_llm(), self._config)

        if agent_type == AgentType.ASSISTANT:
            return AgentLoop(ASSISTANT_CONFIG, self._make_llm(), self._config)

        if agent_type == AgentType.EPHEMERAL_SUBAGENT:
            from pathlib import Path

            from src.business.agents.config import AgentConfig

            # 续跑时调用方可传 iteration_budget 追加轮数（与 _continue_subagent 的
            # extra_iterations 同语义），否则用默认 50。
            ephemeral_config = AgentConfig(
                agent_type=AgentType.EPHEMERAL_SUBAGENT,
                system_prompt=_EPHEMERAL_SUBAGENT_PROMPT,
                max_iterations=50 + (max_iterations_override or 0),
                resumable_on_failure=True,
                workspace_root=Path(workspace_root) if workspace_root else None,
            )
            return AgentLoop(ephemeral_config, self._make_llm(), self._config)

        if agent_type == AgentType.SPECIALIST:
            from pathlib import Path

            from src.business.agents.config import AgentConfig

            specialist_config = AgentConfig(
                agent_type=AgentType.SPECIALIST,
                system_prompt="你是一个固定专员。根据你的角色定义完成指定工作。",
                max_iterations=30 + (max_iterations_override or 0),
                # 撞轮次上限不是失败：工作历史完整保留，父侧可 continue_subagent 追加
                # 预算续跑。此前默认 False 让专员直接判 ERROR，30 轮做不完的任务全部作废。
                resumable_on_failure=True,
                workspace_root=Path(workspace_root) if workspace_root else None,
            )
            return AgentLoop(specialist_config, self._make_llm(), self._config)

        mode = self._recording_mode(workflow_id)
        if agent_type == AgentType.PM:
            config = replace(PM_CONFIG, system_prompt=build_pm_prompt(mode))
            return AgentLoop(config, self._make_llm(), self._config)
        if agent_type == AgentType.PROGRAMMER:
            config = replace(PROGRAMMER_CONFIG, system_prompt=build_programmer_prompt(mode))
            return AgentLoop(config, self._make_llm(), self._config)
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
