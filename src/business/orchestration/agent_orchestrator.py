"""
Agent 编排器

负责 Agent 会话生命周期管理、调度逻辑、业务事件发送。
Loop 不感知事件系统；所有事件由 Orchestrator 在 loop.run() 返回后发出。
"""

import json
import logging
import threading
import time
import uuid
from collections import OrderedDict
from typing import Callable, Dict, List, Optional, Union

from src.business.agents.agent_loop import AgentLoop
from src.business.agents.config import (
    AgentConfig,
    AgentResult,
    AgentType,
    ResultType,
    ToolDefinition,
    PM_CONFIG,
    PROGRAMMER_CONFIG,
    ASSISTANT_CONFIG,
)
from src.business.agents.tools import (
    create_recording_tools,
    create_trial_tools,
    submit_requirements,
    report_code_issue,
    syntax_check,
    submit_code,
)
from src.business.ai.llm_client import LangChainLLMClient
from src.data.models_sqlite import Session, WorkflowTransition
from src.data.repositories import SessionRepository, WorkflowTransitionRepository
from src.data.unified_config import UnifiedConfigManager
from src.utils.events import emit
from .llm_reviewer import LLMReviewer, ReviewResult

logger = logging.getLogger(__name__)


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
        self._transition_repo = WorkflowTransitionRepository()

        # Loop 实例缓存（按 agent_type）
        self._loops: Dict[str, AgentLoop] = {}

        # Review 重试计数（按 workflow_id）
        self._review_counts: Dict[str, int] = {}

        # DynamicToolManager 缓存（按 session_id，LRU 淘汰防泄漏）
        self._dynamic_managers: OrderedDict[str, "DynamicToolManager"] = OrderedDict()
        self._dynamic_managers_lock = threading.Lock()
        self._MAX_DYNAMIC_MANAGERS = 20

        # 后台队列 Worker：轮询 pending_assistant_tasks 表
        self._task_queue_event = threading.Event()  # 入队时唤醒
        self._task_worker_running = False

    # =========================================================================
    # 核心公共 API
    # =========================================================================

    def run_agent(
        self,
        agent_type: str,
        user_input: str,
        workflow_id: str = None,
        session_id: str = None,
    ) -> None:
        """
        运行 Agent

        PM/程序员/试用：传 workflow_id（现有逻辑不变）
        assistant：传 session_id（不传 workflow_id）

        1. 查询或创建会话
        2. 运行 Loop，获取 result
        3. 根据 result 发事件 + 调度下一步
        """
        if agent_type == AgentType.ASSISTANT:
            assert session_id, "assistant 类型必须传 session_id"
        else:
            session_id = self._get_or_create_session(workflow_id, agent_type)

        try:
            loop = self._get_loop(agent_type, workflow_id=workflow_id)
        except ValueError as e:
            logger.error(f"[Orchestrator] 无法创建 {agent_type} Loop: {e}")
            emit(
                "agent_error",
                sender=self,
                workflow_id=workflow_id or "",
                session_id=session_id,
                agent_type=agent_type,
                error=str(e),
                error_type="setup_error",
            )
            if workflow_id:
                self._transition_repo.create(
                    WorkflowTransition(
                        transition_id=str(uuid.uuid4()),
                        workflow_id=workflow_id,
                        event_type="agent_error",
                        from_session_id=session_id,
                        to_session_id=None,
                        payload=json.dumps({"error": str(e), "agent_type": agent_type}),
                    )
                )
            return

        logger.info(
            f"[Orchestrator] 启动 {agent_type} Agent: session={session_id}, workflow={workflow_id}"
        )

        tools = self._build_tools(agent_type, workflow_id=workflow_id, session_id=session_id)

        # 格式化系统提示（assistant 走独立路径）
        if agent_type == AgentType.ASSISTANT:
            formatted_prompt = self._format_assistant_prompt(session_id)
        else:
            formatted_prompt = loop.format_system_prompt(recording_id=workflow_id)

        result = loop.run(
            session_id,
            user_input,
            tools=tools,
            system_prompt_override=formatted_prompt,
        )

        if result.result_type == ResultType.COMPLETED:
            if agent_type != AgentType.ASSISTANT:
                self._dispatch_next(agent_type, result, session_id, workflow_id)

        elif result.result_type == ResultType.NEEDS_USER_INPUT:
            emit(
                "agent_needs_user_input",
                sender=self,
                workflow_id=workflow_id or "",
                session_id=session_id,
                agent_type=agent_type,
                question=result.question,
            )

        elif result.result_type in (ResultType.ERROR, ResultType.MAX_ITERATIONS_REACHED):
            emit(
                "agent_error",
                sender=self,
                workflow_id=workflow_id or "",
                session_id=session_id,
                agent_type=agent_type,
                error=result.error,
                error_type=result.result_type.value,
            )
            if workflow_id:
                self._transition_repo.create(
                    WorkflowTransition(
                        transition_id=str(uuid.uuid4()),
                        workflow_id=workflow_id,
                        event_type="agent_error",
                        from_session_id=session_id,
                        to_session_id=None,
                        payload=json.dumps({"error": result.error, "agent_type": agent_type}),
                    )
                )

    def start_analysis(self, recording_id: str, workflow_id: str) -> None:
        """
        启动 PM Agent 分析录制（首次分析入口）

        构造初始输入消息（pm_agent_design.md 5.3 节），
        由 Orchestrator 保证消息格式一致，调用方只需传 recording_id。
        """
        initial_input = (
            f"请分析录制 {recording_id} 的操作流程，" "理解用户想要自动化的任务，并与用户确认需求。"
        )
        self.run_agent("pm", initial_input, workflow_id)

    def start_trial(self, tool_id: str, user_input: str, workflow_id: str) -> None:
        """启动试用 Agent"""
        self.run_agent("trial", user_input, workflow_id)

    def handle_trial_result(
        self,
        tool_id: str,
        success: bool,
        workflow_id: str,
        session_id: str,
        user_feedback: str = "",
    ) -> None:
        """
        处理试用结果（由 UI 层在用户试用完工具后调用）

        成功：累加 trial_success_count，达 3 次发布
        失败：触发 PM 分诊
        """
        from src.data.repositories import ToolRepository

        tool_repo = ToolRepository()

        if success:
            tool = tool_repo.get_by_id(tool_id)
            if not tool:
                logger.error(f"[Orchestrator] handle_trial_result: tool {tool_id} 不存在")
                return

            new_count = (tool.trial_success_count or 0) + 1
            tool_repo.update_trial_success_count(tool_id, new_count)

            published = new_count >= 3
            if published:
                tool_repo.update_status(tool_id, "published")

            emit(
                "trial_success",
                sender=self,
                workflow_id=workflow_id,
                session_id=session_id,
                tool_id=tool_id,
                success_count=new_count,
                published=published,
            )
            self._transition_repo.create(
                WorkflowTransition(
                    transition_id=str(uuid.uuid4()),
                    workflow_id=workflow_id,
                    event_type="trial_success",
                    from_session_id=session_id,
                    to_session_id=None,
                    payload=json.dumps({"success_count": new_count, "published": published}),
                )
            )

            if published:
                # 3 次试用全部成功，发布工具
                logger.info(f"[Orchestrator] 工具已发布: tool_id={tool_id}")
                emit(
                    "tool_published",
                    sender=self,
                    workflow_id=workflow_id,
                    session_id=session_id,
                    tool_id=tool_id,
                )
            else:
                # 还需继续试用，在同一个 trial session 中继续
                remaining = 3 - new_count
                logger.info(
                    f"[Orchestrator] 试用成功 {new_count}/3，继续试用: workflow={workflow_id}"
                )
                self.run_agent(
                    "trial",
                    f"第 {new_count} 次试用成功（共需 3 次），还需再成功 {remaining} 次。"
                    "请引导用户用不同的参数再试一次。",
                    workflow_id,
                )

        else:
            pm_session_id = self._get_or_create_session(workflow_id, "pm")

            emit(
                "trial_failed",
                sender=self,
                workflow_id=workflow_id,
                session_id=session_id,
                tool_id=tool_id,
                user_feedback=user_feedback,
            )
            self._transition_repo.create(
                WorkflowTransition(
                    transition_id=str(uuid.uuid4()),
                    workflow_id=workflow_id,
                    event_type="trial_failed",
                    from_session_id=session_id,
                    to_session_id=pm_session_id,
                    payload=json.dumps({"tool_id": tool_id, "user_feedback": user_feedback}),
                )
            )

            self._start_triage(tool_id, user_feedback, workflow_id)

    # =========================================================================
    # 内部调度逻辑
    # =========================================================================

    def _dispatch_next(
        self,
        agent_type: str,
        result: AgentResult,
        session_id: str,
        workflow_id: str,
    ) -> None:
        """
        根据完成的 Agent 类型，调度下一步。
        所有 Agent 间衔接逻辑集中在此。
        """
        try:
            if agent_type == AgentType.PM:
                self._on_pm_completed(result, session_id, workflow_id)
            elif agent_type == AgentType.PROGRAMMER:
                self._on_programmer_completed(result, session_id, workflow_id)
            elif agent_type == AgentType.TRIAL:
                self._on_trial_completed(result, session_id, workflow_id)
        except Exception as e:
            logger.error(f"[Orchestrator] 调度失败: {e}", exc_info=True)
            emit(
                "agent_error",
                sender=self,
                workflow_id=workflow_id,
                session_id=session_id,
                agent_type=agent_type,
                error=f"调度失败: {str(e)}",
                error_type="dispatch_error",
            )

    def _on_pm_completed(self, result: AgentResult, session_id: str, workflow_id: str) -> None:
        """
        PM 完成 → 根据 signal_tool 路由

        两种场景通过 signal_tool.name 区分：
        - submit_requirements → 正常需求确认 → emit requirement_confirmed → 转给程序员
        - report_code_issue  → 分诊代码问题 → emit triage_completed → 转给程序员
        - None（自然结束，兜底）→ emit agent_error
        """
        if result.signal_tool and result.signal_tool.name == "submit_requirements":
            # 正常需求确认：结构化数据来自 signal_tool.args，由 FC schema 保证格式
            requirements = result.signal_tool.args
            programmer_session_id = self._get_or_create_session(workflow_id, "programmer")
            emit(
                "requirement_confirmed",
                sender=self,
                workflow_id=workflow_id,
                session_id=session_id,
                requirements_json=requirements,
            )
            self._transition_repo.create(
                WorkflowTransition(
                    transition_id=str(uuid.uuid4()),
                    workflow_id=workflow_id,
                    event_type="requirement_confirmed",
                    from_session_id=session_id,
                    to_session_id=programmer_session_id,
                    payload=json.dumps({"requirements": requirements}),
                )
            )
            # 将需求 JSON 转给程序员
            self.run_agent("programmer", json.dumps(requirements, ensure_ascii=False), workflow_id)

        elif result.signal_tool and result.signal_tool.name == "report_code_issue":
            # 分诊：PM 判定为代码问题，将用户反馈转交程序员
            feedback = result.signal_tool.args.get("feedback", "")
            programmer_session_id = self._get_or_create_session(workflow_id, "programmer")
            emit(
                "triage_completed",
                sender=self,
                workflow_id=workflow_id,
                session_id=session_id,
                triage_result="code_issue",
                feedback=feedback,
            )
            self._transition_repo.create(
                WorkflowTransition(
                    transition_id=str(uuid.uuid4()),
                    workflow_id=workflow_id,
                    event_type="triage_completed",
                    from_session_id=session_id,
                    to_session_id=programmer_session_id,
                    payload=json.dumps({"triage_result": "code_issue", "feedback": feedback}),
                )
            )
            self.run_agent("programmer", feedback, workflow_id)

        else:
            # 兜底：PM 自然结束但未调用 submit_requirements 或 report_code_issue
            # 视为异常情况（pm_agent_design.md 9.6 节）
            logger.warning(
                f"[Orchestrator] PM Agent 自然结束但未调用 signal 工具: session={session_id}"
            )
            emit(
                "agent_error",
                sender=self,
                workflow_id=workflow_id,
                session_id=session_id,
                agent_type="pm",
                error="PM Agent 未调用 submit_requirements 或 report_code_issue 即结束",
                error_type="missing_signal_tool",
            )
            self._transition_repo.create(
                WorkflowTransition(
                    transition_id=str(uuid.uuid4()),
                    workflow_id=workflow_id,
                    event_type="agent_error",
                    from_session_id=session_id,
                    to_session_id=None,
                    payload=json.dumps({"agent_type": "pm", "error": "missing_signal_tool"}),
                )
            )

    def _on_programmer_completed(
        self, result: AgentResult, session_id: str, workflow_id: str
    ) -> None:
        """程序员完成 → 从 signal_tool.args 获取结构化代码数据 → 启动 Review"""
        if not (result.signal_tool and result.signal_tool.name == "submit_code"):
            logger.warning(
                f"[Orchestrator] 程序员 Agent 未调用 submit_code 即结束: session={session_id}"
            )
            emit(
                "agent_error",
                sender=self,
                workflow_id=workflow_id,
                session_id=session_id,
                agent_type="programmer",
                error="程序员未通过 submit_code 提交代码",
                error_type="missing_signal_tool",
            )
            self._transition_repo.create(
                WorkflowTransition(
                    transition_id=str(uuid.uuid4()),
                    workflow_id=workflow_id,
                    event_type="agent_error",
                    from_session_id=session_id,
                    to_session_id=None,
                    payload=json.dumps(
                        {"agent_type": "programmer", "error": "missing_signal_tool"}
                    ),
                )
            )
            return

        code_data = result.signal_tool.args
        code = code_data["code"]

        emit(
            "code_completed", sender=self, workflow_id=workflow_id, session_id=session_id, code=code
        )
        self._transition_repo.create(
            WorkflowTransition(
                transition_id=str(uuid.uuid4()),
                workflow_id=workflow_id,
                event_type="code_completed",
                from_session_id=session_id,
                to_session_id=None,
                payload=json.dumps({"code_length": len(code)}),
            )
        )

        self._run_review(code_data, session_id, workflow_id)

    def _on_trial_completed(self, result: AgentResult, session_id: str, workflow_id: str) -> None:
        """试用 Agent 完成 → 从 signal_tool.args 获取 success/feedback → 路由到计数或 PM 分诊"""
        if result.signal_tool and result.signal_tool.name == "submit_trial_result":
            success = result.signal_tool.args["success"]
            feedback = result.signal_tool.args.get("feedback", "")

            from src.data.repositories import ToolRepository

            tool = ToolRepository().get_by_workflow_id(workflow_id)
            if not tool:
                emit(
                    "agent_error",
                    sender=self,
                    workflow_id=workflow_id,
                    session_id=session_id,
                    agent_type="trial",
                    error="未找到工具",
                    error_type="tool_not_found",
                )
                self._transition_repo.create(
                    WorkflowTransition(
                        transition_id=str(uuid.uuid4()),
                        workflow_id=workflow_id,
                        event_type="agent_error",
                        from_session_id=session_id,
                        to_session_id=None,
                        payload=json.dumps({"agent_type": "trial", "error": "tool_not_found"}),
                    )
                )
                return

            self.handle_trial_result(tool.tool_id, success, workflow_id, session_id, feedback)
        else:
            logger.warning(
                f"[Orchestrator] 试用 Agent 未调用 submit_trial_result 即结束: session={session_id}"
            )
            emit(
                "agent_error",
                sender=self,
                workflow_id=workflow_id,
                session_id=session_id,
                agent_type="trial",
                error="试用 Agent 未通过 submit_trial_result 结束",
                error_type="unexpected_completion",
            )
            self._transition_repo.create(
                WorkflowTransition(
                    transition_id=str(uuid.uuid4()),
                    workflow_id=workflow_id,
                    event_type="agent_error",
                    from_session_id=session_id,
                    to_session_id=None,
                    payload=json.dumps({"agent_type": "trial", "error": "unexpected_completion"}),
                )
            )

    def _run_review(self, code_data: dict, from_session_id: str, workflow_id: str) -> None:
        """
        运行 LLM Review

        通过/失败计数通过 self._review_counts[workflow_id] 追踪。
        失败 < 4 次：回传给程序员修改；≥ 4 次：强制入库（pending）。
        """
        code = code_data["code"]
        requirement = {
            "description": code_data.get("description", ""),
            "parameters": code_data.get("parameters", []),
        }
        retry_count = self._review_counts.get(workflow_id, 0)
        review_result: ReviewResult = self._llm_reviewer.review(code, requirement)

        if review_result.passed:
            emit(
                "review_passed",
                sender=self,
                workflow_id=workflow_id,
                session_id=from_session_id,
                code=code,
            )
            self._transition_repo.create(
                WorkflowTransition(
                    transition_id=str(uuid.uuid4()),
                    workflow_id=workflow_id,
                    event_type="review_passed",
                    from_session_id=from_session_id,
                    to_session_id=None,
                    payload=None,
                )
            )
            self._review_counts.pop(workflow_id, None)
            self._save_tool(code_data, workflow_id, from_session_id)

        else:
            retry_count += 1
            self._review_counts[workflow_id] = retry_count

            if retry_count < 4:
                programmer_session_id = self._get_or_create_session(workflow_id, "programmer")
                emit(
                    "review_failed",
                    sender=self,
                    workflow_id=workflow_id,
                    session_id=from_session_id,
                    code=code,
                    feedback=review_result.feedback,
                    retry_count=retry_count,
                    forced_save=False,
                )
                self._transition_repo.create(
                    WorkflowTransition(
                        transition_id=str(uuid.uuid4()),
                        workflow_id=workflow_id,
                        event_type="review_failed",
                        from_session_id=from_session_id,
                        to_session_id=programmer_session_id,
                        payload=json.dumps(
                            {"retry_count": retry_count, "feedback": review_result.feedback}
                        ),
                    )
                )
                self.run_agent(
                    "programmer",
                    f"[LLM Review 第 {retry_count} 次，共最多 3 次]\n\n审查意见：{review_result.feedback}",
                    workflow_id,
                )
            else:
                # 超过 3 次，强制入库（pending 状态）
                emit(
                    "review_failed",
                    sender=self,
                    workflow_id=workflow_id,
                    session_id=from_session_id,
                    code=code,
                    feedback=review_result.feedback,
                    retry_count=retry_count,
                    forced_save=True,
                )
                self._transition_repo.create(
                    WorkflowTransition(
                        transition_id=str(uuid.uuid4()),
                        workflow_id=workflow_id,
                        event_type="review_failed",
                        from_session_id=from_session_id,
                        to_session_id=None,
                        payload=json.dumps(
                            {"retry_count": retry_count, "forced_save": (retry_count >= 4)}
                        ),
                    )
                )
                self._review_counts.pop(workflow_id, None)
                self._save_tool(code_data, workflow_id, from_session_id)

    def _start_triage(self, tool_id: str, user_feedback: str, workflow_id: str) -> None:
        """
        启动 PM 分诊

        PM session 被 _get_or_create_session 自动复用（completed → 复用），
        PM 能看到完整的需求确认上下文。

        PM 分诊后两种路径：
        - 需求问题 → PM 调 talk_to_user 重新确认 → 正常 requirement_confirmed 流程
        - 代码问题 → PM 直接输出用户反馈 → _on_pm_completed 转给程序员
        """
        initial_input = (
            f"工具 {tool_id} 试用失败，用户反馈：{user_feedback}。"
            "请分析问题原因：如果是需求问题，请与用户重新确认需求；"
            "如果是代码问题，请直接输出用户反馈供程序员排查。"
        )
        self.run_agent("pm", initial_input, workflow_id)

    # =========================================================================
    # Session 管理
    # =========================================================================

    def _get_or_create_session(self, workflow_id: str, agent_type: str) -> str:
        """
        查询或创建会话（Session 复用原则）

        规则：
        - suspended / completed → 复用（review 打回、分诊回来等场景）
        - active → 复用（记 warning，不应并发但不阻断）
        - failed → 创建新会话（避免残留脏数据）
        - 不存在 → 创建新会话
        """
        sessions = self._session_repo.get_by_workflow(
            workflow_id, agent_type=agent_type, order_by="created_at_desc"
        )

        if sessions:
            latest = sessions[0]
            if latest.status == "failed":
                return self._create_session(workflow_id, agent_type)
            if latest.status == "active":
                logger.warning(
                    f"[Orchestrator] 会话 {latest.session_id} 仍在 active 状态，" "可能存在并发调用"
                )
            return latest.session_id

        return self._create_session(workflow_id, agent_type)

    def _create_session(self, workflow_id: str, agent_type: str) -> str:
        """创建新会话，返回 session_id"""
        model = Session(
            session_id=str(uuid.uuid4()),
            workflow_id=workflow_id,
            agent_type=agent_type,
            status="active",
        )
        session = self._session_repo.create(model)
        return session.session_id

    # =========================================================================
    # 辅助方法
    # =========================================================================

    def _build_tools(
        self,
        agent_type: str,
        workflow_id: str = None,
        session_id: str = None,
    ) -> Union[List[ToolDefinition], Callable[[], List[ToolDefinition]]]:
        """根据 agent_type 构建工具列表。assistant 返回 callable（工厂函数）。"""
        if agent_type == AgentType.PM:
            return create_recording_tools(workflow_id) + [submit_requirements, report_code_issue]
        elif agent_type == AgentType.PROGRAMMER:
            return create_recording_tools(workflow_id) + [syntax_check, submit_code]
        elif agent_type == AgentType.TRIAL:
            return create_trial_tools(workflow_id)
        elif agent_type == AgentType.ASSISTANT:
            return self._build_assistant_tools(session_id)
        return []

    def _build_assistant_tools(
        self, session_id: str
    ) -> Callable[[], List[ToolDefinition]]:
        """返回工厂函数，每轮迭代调用时拿到最新的已激活工具"""
        from src.business.agents.tools.dynamic_tool_manager import (
            DynamicToolManager,
            create_assistant_search_tools,
        )

        # 获取 session 的 tool_ids 限制
        session = self._session_repo.get_by_id(session_id)
        allowed_ids = session.get_tool_id_set() if session else None

        # 按 session_id 缓存 DynamicToolManager（OrderedDict LRU）
        with self._dynamic_managers_lock:
            if session_id in self._dynamic_managers:
                self._dynamic_managers.move_to_end(session_id)
            else:
                self._dynamic_managers[session_id] = DynamicToolManager(allowed_ids)
                while len(self._dynamic_managers) > self._MAX_DYNAMIC_MANAGERS:
                    self._dynamic_managers.popitem(last=False)
            dynamic_manager = self._dynamic_managers[session_id]

        from src.business.agents.tools.assistant_tools import (
            REPORT_TOOL_BUG, SAVE_PROFILE_SCHEMA, create_save_profile_handler, DISMISS_SUGGESTION,
            CODIFY_AS_TOOL_SCHEMA, create_codify_as_tool_handler,
        )
        from src.business.agents.tools.builtin_general_tools import BUILTIN_GENERAL_TOOLS
        from src.business.memory.assistant_memory import (
            MEMORY_SEARCH_SCHEMA, memory_search_handler,
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

        # 固定工具：搜索/懒加载辅助 + 业务工具 + 通用内置工具
        search_tools = create_assistant_search_tools(dynamic_manager)
        static_tools = (
            [REPORT_TOOL_BUG, save_profile_tool, codify_tool, DISMISS_SUGGESTION, memory_search_tool]
            + BUILTIN_GENERAL_TOOLS
        )

        def tool_factory() -> List[ToolDefinition]:
            return search_tools + static_tools + dynamic_manager.get_activated_tools()

        return tool_factory

    def _get_loop(self, agent_type: str, workflow_id: str = None) -> AgentLoop:
        """获取 Loop 实例。trial/assistant 不缓存（system prompt 含动态内容，每个会话不同）。"""
        if agent_type == AgentType.TRIAL:
            config = self._build_trial_config(workflow_id)
            return AgentLoop(config, self._llm, self._config)

        if agent_type == AgentType.ASSISTANT:
            return AgentLoop(ASSISTANT_CONFIG, self._llm, self._config)

        # pm / programmer 按 agent_type 缓存
        if agent_type not in self._loops:
            configs = {AgentType.PM: PM_CONFIG, AgentType.PROGRAMMER: PROGRAMMER_CONFIG}
            if agent_type not in configs:
                raise ValueError(f"[Orchestrator] 未知 Agent 类型: {agent_type}")
            self._loops[agent_type] = AgentLoop(configs[agent_type], self._llm, self._config)
        return self._loops[agent_type]

    # =========================================================================
    # 助理任务队列 Worker（后台轮询 pending_assistant_tasks）
    # =========================================================================

    def start_task_worker(self):
        """启动后台任务队列 Worker。由外部（如 MainWindow）在初始化完成后调用。"""
        if self._task_worker_running:
            return
        self._task_worker_running = True

        # 注入唤醒回调给 assistant_tools（handler 入队后调用以立即唤醒 Worker）
        from src.business.agents.tools.assistant_tools import register_task_worker_notify
        register_task_worker_notify(self.notify_task_enqueued)

        threading.Thread(target=self._task_worker_loop, daemon=True).start()
        logger.info("[Orchestrator] 后台任务队列 Worker 已启动")

    def notify_task_enqueued(self):
        """入队时调用，立即唤醒 Worker（避免等待轮询间隔）"""
        self._task_queue_event.set()

    def _task_worker_loop(self):
        """后台 Worker 主循环：轮询 pending_assistant_tasks 表"""
        POLL_INTERVAL = 5.0  # 默认轮询间隔（秒）
        while self._task_worker_running:
            try:
                self._process_pending_tasks()
            except Exception as e:
                logger.error(f"[TaskWorker] 处理异常: {e}", exc_info=True)
            # 等待唤醒或超时
            self._task_queue_event.clear()
            self._task_queue_event.wait(timeout=POLL_INTERVAL)

    def _process_pending_tasks(self):
        """取出并执行所有 pending 任务（串行，每次一个）"""
        from src.data.repositories import PendingTaskRepository
        repo = PendingTaskRepository()
        tasks = repo.get_pending()
        for task in tasks:
            try:
                repo.update_status(task.task_id, "processing")
                if task.task_type == "codify_tool":
                    self._process_codify_task(task)
                elif task.task_type == "fix_tool_bug":
                    self._process_bug_task(task)
                else:
                    logger.warning(f"[TaskWorker] 未知任务类型: {task.task_type}")
                    repo.update_status(task.task_id, "failed")
                    continue
                repo.update_status(task.task_id, "completed")
            except Exception as e:
                logger.error(f"[TaskWorker] 任务 {task.task_id} 处理失败: {e}", exc_info=True)
                repo.update_status(task.task_id, "failed")

    def _process_codify_task(self, task):
        """处理 codify_tool 任务：构造 PM 输入，启动 PM 分析"""
        payload = json.loads(task.payload or "{}")
        task_description = payload.get("task_description", "")
        execution_trace = payload.get("execution_trace", [])

        trace_text = "\n".join(
            f"- [{t['type']}] {t.get('name', '')}：{t.get('args', '') or t.get('content', '')[:200]}"
            for t in execution_trace[:20]
        )
        initial_input = (
            f"用户要求将以下任务做成可复用工具：\n\n"
            f"任务描述：{task_description}\n\n"
            f"执行记录：\n{trace_text}\n\n"
            "请基于执行记录分析任务逻辑，与用户确认工具的名称、参数和说明，然后生成代码。"
        )

        new_workflow_id = f"codify_{task.task_id[:8]}"
        self.run_agent("pm", initial_input, workflow_id=new_workflow_id)

    def _process_bug_task(self, task):
        """处理 fix_tool_bug 任务：找到 workflow_id，触发 PM 分诊"""
        payload = json.loads(task.payload or "{}")
        tool_id = payload.get("tool_id", "")
        error_message = payload.get("error_message", "")

        from src.data.repositories import ToolRepository
        tool = ToolRepository().get_by_id(tool_id)
        if not tool or not tool.workflow_id:
            logger.warning(f"[TaskWorker] fix_tool_bug: 找不到 workflow_id, tool_id={tool_id}")
            return

        self._start_triage(tool_id, error_message, tool.workflow_id)

    def _format_assistant_prompt(self, session_id: str) -> str:
        """格式化助理 Agent 的 system prompt（独立路径，不走 format_system_prompt）"""
        from src.business.agents.prompts.assistant_prompt import format_assistant_prompt
        from src.data.repositories import ToolRepository

        # 获取 profile
        profile = self._get_assistant_profile()

        # 获取用户工具列表（用于 system prompt 简表）
        session = self._session_repo.get_by_id(session_id)
        tool_repo = ToolRepository()
        allowed_tool_ids = session.get_tool_id_set() if session else None
        all_published = tool_repo.get_published()
        if allowed_tool_ids is not None:
            tools = [t for t in all_published if t.tool_id in allowed_tool_ids]
        else:
            tools = all_published

        tool_list = [{"name": t.tool_name, "description": t.description or ""} for t in tools]

        # 获取全局摘要
        try:
            from src.business.memory.assistant_memory import get_memory_manager
            memory_manager = get_memory_manager(llm_client=self._llm)
            memory_summary = memory_manager.get_global_summary()
        except Exception as e:
            logger.warning(f"[Orchestrator] 获取全局摘要失败: {e}")
            memory_summary = None

        return format_assistant_prompt(
            profile=profile,
            tools=tool_list if tool_list else None,
            memory_summary=memory_summary,
        )

    def _get_assistant_profile(self) -> Optional[dict]:
        """获取助理用户偏好档案"""
        try:
            from src.data.repositories import AssistantProfileRepository

            profile = AssistantProfileRepository().get_default()
            if profile:
                return {
                    "display_name": profile.display_name,
                    "style": profile.style,
                    "notes": profile.notes,
                }
        except Exception as e:
            logger.warning(f"[Orchestrator] 获取 assistant profile 失败: {e}")
        return None

    def _build_trial_config(self, workflow_id: str) -> AgentConfig:
        """构建包含工具信息的试用 Agent 配置。"""
        from src.data.repositories import ToolRepository
        from src.business.agents.prompts.trial_prompt import (
            TRIAL_SYSTEM_PROMPT_TEMPLATE,
            format_parameters_text,
        )

        tool = ToolRepository().get_by_workflow_id(workflow_id)
        if not tool:
            raise ValueError(f"未找到 workflow_id={workflow_id} 对应的工具")

        parameters_text = format_parameters_text(tool.parameters or [])
        # 用手动替换而非 str.format()，防止 tool_name/description 内容含花括号时触发 KeyError
        system_prompt = (
            TRIAL_SYSTEM_PROMPT_TEMPLATE.replace("{tool_name}", tool.tool_name)
            .replace("{description}", tool.description or "（无描述）")
            .replace("{parameters_text}", parameters_text)
        )
        return AgentConfig(
            agent_type=AgentType.TRIAL,
            system_prompt=system_prompt,
            max_iterations=20,
            text_as_user_input=True,
        )

    def _save_tool(
        self,
        code_data: dict,
        workflow_id: str,
        session_id: str,
        status: str = "pending",
    ) -> str:
        """
        保存工具到数据库

        按 workflow_id 查重：存在则更新代码并清零试用计数，不存在则创建。
        工具元数据直接从 submit_code 的结构化参数中获取（code_data dict）。
        """
        from src.data.repositories import ToolRepository
        from src.data.models_sqlite import Tool

        code = code_data["code"]
        tool_repo = ToolRepository()
        existing = tool_repo.get_by_workflow_id(workflow_id)

        if existing:
            tool_id = existing.tool_id
            existing.execution_code = code
            existing.tool_name = code_data["tool_name"]
            existing.description = code_data["description"]
            existing.parameters = code_data.get("parameters", [])
            existing.dependencies = code_data.get("dependencies", [])
            existing.trial_success_count = 0
            existing.source = "intent"
            existing.status = status
            tool_repo.update(existing)
        else:
            new_tool = Tool(
                tool_id=str(uuid.uuid4()),
                tool_name=code_data["tool_name"],
                description=code_data["description"],
                execution_code=code,
                parameters=code_data.get("parameters", []),
                dependencies=code_data.get("dependencies", []),
                steps=[],
                workflow_id=workflow_id,
                source="intent",
                status=status,
                trial_success_count=0,
            )
            created = tool_repo.create(new_tool)
            tool_id = created.tool_id

        # 判断是否从分诊修复而来（存在 trial session 说明工具已经被试用过）
        trial_sessions = self._session_repo.get_by_workflow(workflow_id, agent_type="trial")
        from_triage = bool(trial_sessions)

        emit(
            "tool_saved",
            sender=self,
            workflow_id=workflow_id,
            session_id=session_id,
            tool_id=tool_id,
            from_triage=from_triage,
        )
        self._transition_repo.create(
            WorkflowTransition(
                transition_id=str(uuid.uuid4()),
                workflow_id=workflow_id,
                event_type="tool_saved",
                from_session_id=session_id,
                to_session_id=None,
                payload=json.dumps({"tool_id": tool_id, "from_triage": from_triage}),
            )
        )

        if from_triage:
            logger.info(
                f"[Orchestrator] 分诊修复完成，自动重启 trial Agent: workflow={workflow_id}"
            )
            self.run_agent("trial", "代码已修复，请重新执行工具试用", workflow_id)

        return tool_id
