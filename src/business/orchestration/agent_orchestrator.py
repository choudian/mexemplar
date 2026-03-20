"""
Agent 编排器

负责 Agent 会话生命周期管理、调度逻辑、业务事件发送。
Loop 不感知事件系统；所有事件由 Orchestrator 在 loop.run() 返回后发出。
"""

import json
import logging
import uuid
from typing import Dict, List, Optional

from src.business.agents.agent_loop import AgentLoop
from src.business.agents.config import (
    AgentConfig,
    AgentResult,
    AgentType,
    ResultType,
    ToolDefinition,
    PM_CONFIG,
    PROGRAMMER_CONFIG,
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

    # =========================================================================
    # 核心公共 API
    # =========================================================================

    def run_agent(
        self,
        agent_type: str,
        user_input: str,
        workflow_id: str,
    ) -> None:
        """
        运行 Agent

        1. 查询或创建会话
        2. 运行 Loop，获取 result
        3. 根据 result 发事件 + 调度下一步
        """
        session_id = self._get_or_create_session(workflow_id, agent_type)
        try:
            loop = self._get_loop(agent_type, workflow_id=workflow_id)
        except ValueError as e:
            logger.error(f"[Orchestrator] 无法创建 {agent_type} Loop: {e}")
            emit(
                "agent_error",
                sender=self,
                workflow_id=workflow_id,
                session_id=session_id,
                agent_type=agent_type,
                error=str(e),
                error_type="setup_error",
            )
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

        tools = self._build_tools(agent_type, workflow_id)

        # 格式化系统提示中的 {recording_id} 模板变量（仅首次会话时生效）
        formatted_prompt = loop.format_system_prompt(recording_id=workflow_id)

        result = loop.run(
            session_id, user_input,
            tools=tools,
            system_prompt_override=formatted_prompt,
        )

        if result.result_type == ResultType.COMPLETED:
            self._dispatch_next(agent_type, result, session_id, workflow_id)

        elif result.result_type == ResultType.NEEDS_USER_INPUT:
            emit(
                "agent_needs_user_input",
                sender=self,
                workflow_id=workflow_id,
                session_id=session_id,
                agent_type=agent_type,
                question=result.question,
            )

        elif result.result_type in (ResultType.ERROR, ResultType.MAX_ITERATIONS_REACHED):
            emit(
                "agent_error",
                sender=self,
                workflow_id=workflow_id,
                session_id=session_id,
                agent_type=agent_type,
                error=result.error,
                error_type=result.result_type.value,
            )
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
            f"请分析录制 {recording_id} 的操作流程，"
            "理解用户想要自动化的任务，并与用户确认需求。"
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
            if agent_type == "pm":
                self._on_pm_completed(result, session_id, workflow_id)
            elif agent_type == "programmer":
                self._on_programmer_completed(result, session_id, workflow_id)
            elif agent_type == "trial":
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
                    payload=json.dumps({"agent_type": "programmer", "error": "missing_signal_tool"}),
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
                    payload=json.dumps(
                        {"agent_type": "trial", "error": "unexpected_completion"}
                    ),
                )
            )

    def _run_review(self, code_data: dict, from_session_id: str, workflow_id: str) -> None:
        """
        运行 LLM Review

        通过/失败计数通过 self._review_counts[workflow_id] 追踪。
        失败 < 3 次：回传给程序员修改；≥ 3 次：强制入库（pending）。
        """
        code = code_data["code"]
        retry_count = self._review_counts.get(workflow_id, 0)
        review_result: ReviewResult = self._llm_reviewer.review(code)

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

            if retry_count < 3:
                programmer_session_id = self._get_or_create_session(workflow_id, "programmer")
                emit(
                    "review_failed",
                    sender=self,
                    workflow_id=workflow_id,
                    session_id=from_session_id,
                    code=code,
                    feedback=review_result.feedback,
                    retry_count=retry_count,
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
                    f"Review 失败（第{retry_count}次），修改意见：{review_result.feedback}",
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
                )
                self._transition_repo.create(
                    WorkflowTransition(
                        transition_id=str(uuid.uuid4()),
                        workflow_id=workflow_id,
                        event_type="review_failed",
                        from_session_id=from_session_id,
                        to_session_id=None,
                        payload=json.dumps({"retry_count": retry_count, "forced_save": True}),
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

    def _build_tools(self, agent_type: str, workflow_id: str) -> List[ToolDefinition]:
        """根据 agent_type 和 workflow_id 构建工具列表（recording_id 通过闭包绑定）"""
        if agent_type == "pm":
            return create_recording_tools(workflow_id) + [submit_requirements, report_code_issue]
        elif agent_type == "programmer":
            return create_recording_tools(workflow_id) + [syntax_check, submit_code]
        elif agent_type == "trial":
            return create_trial_tools(workflow_id)
        return []

    def _get_loop(self, agent_type: str, workflow_id: str = None) -> AgentLoop:
        """获取 Loop 实例。trial agent 不缓存（system prompt 含工具信息，每个 workflow 不同）。"""
        if agent_type == "trial":
            config = self._build_trial_config(workflow_id)
            return AgentLoop(config, self._llm, self._config)

        # pm / programmer 按 agent_type 缓存
        if agent_type not in self._loops:
            configs = {"pm": PM_CONFIG, "programmer": PROGRAMMER_CONFIG}
            if agent_type not in configs:
                raise ValueError(f"[Orchestrator] 未知 Agent 类型: {agent_type}")
            self._loops[agent_type] = AgentLoop(configs[agent_type], self._llm, self._config)
        return self._loops[agent_type]

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
            TRIAL_SYSTEM_PROMPT_TEMPLATE
            .replace("{tool_name}", tool.tool_name)
            .replace("{description}", tool.description or "（无描述）")
            .replace("{parameters_text}", parameters_text)
        )
        return AgentConfig(
            agent_type=AgentType.TRIAL,
            system_prompt=system_prompt,
            max_iterations=20,
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
            existing.trial_success_count = 0
            existing.status = status
            tool_repo.update(existing)
        else:
            new_tool = Tool(
                tool_id=str(uuid.uuid4()),
                tool_name=code_data["tool_name"],
                description=code_data["description"],
                execution_code=code,
                parameters=code_data.get("parameters", []),
                workflow_id=workflow_id,
                status=status,
                trial_success_count=0,
            )
            created = tool_repo.create(new_tool)
            tool_id = created.tool_id

        emit(
            "tool_saved",
            sender=self,
            workflow_id=workflow_id,
            session_id=session_id,
            tool_id=tool_id,
        )
        self._transition_repo.create(
            WorkflowTransition(
                transition_id=str(uuid.uuid4()),
                workflow_id=workflow_id,
                event_type="tool_saved",
                from_session_id=session_id,
                to_session_id=None,
                payload=json.dumps({"tool_id": tool_id}),
            )
        )

        return tool_id
