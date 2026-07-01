"""Teaching workflow orchestration for PM -> Programmer -> Trial."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

from src.business.agents.config import AgentResult, AgentType
from src.recording.browser.recorder import RecordingMode
from src.utils.events import emit

from .desktop_syntax_gate import check_code, log_terminal_failure, should_retry

logger = logging.getLogger(__name__)


@dataclass
class DesktopSyntaxState:
    retry_count: int = 0
    attempts: list[str] = field(default_factory=list)
    feedbacks: list[str] = field(default_factory=list)


class TeachingOrchestrator:
    """Owns the teaching state machine and review retry counters."""

    def __init__(self, owner: Any) -> None:
        self._owner = owner

    def start_analysis(self, recording_id: str, workflow_id: str) -> None:
        initial_input = (
            f"请分析录制 {recording_id} 的操作流程，理解用户想要自动化的任务，并与用户确认需求。"
        )
        self._owner.run_agent(AgentType.PM, initial_input, workflow_id)

    def start_trial(self, tool_id: str, user_input: str, workflow_id: str) -> None:
        del tool_id
        self._owner.run_agent(AgentType.TRIAL, user_input, workflow_id)

    def handle_trial_result(
        self,
        tool_id: str,
        success: bool,
        workflow_id: str,
        session_id: str,
        user_feedback: str = "",
    ) -> None:
        if success:
            tool = self._owner._tool_repo.get_by_id(tool_id)
            if not tool:
                logger.error("[Orchestrator] handle_trial_result: tool %s 不存在", tool_id)
                return

            new_count = (tool.trial_success_count or 0) + 1
            self._owner._tool_repo.update_trial_success_count(tool_id, new_count)

            published = new_count >= 3
            if published:
                self._owner._tool_repo.update_status(tool_id, "published")

            self._owner._emit_and_log(
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
                logger.info("[Orchestrator] 工具已发布: tool_id=%s", tool_id)
                emit(
                    "tool_published",
                    sender=self._owner,
                    workflow_id=workflow_id,
                    session_id=session_id,
                    tool_id=tool_id,
                )
            else:
                remaining = 3 - new_count
                logger.info(
                    "[Orchestrator] 试用成功 %s/3，继续试用: workflow=%s",
                    new_count,
                    workflow_id,
                )
                self._owner.run_agent(
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

        pm_session_id = self._owner._session_store.get_or_create_session(workflow_id, AgentType.PM)
        self._owner._emit_and_log(
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
        self.start_triage(tool_id, user_feedback, workflow_id)

    def dispatch_next(
        self,
        agent_type: str,
        result: AgentResult,
        session_id: str,
        workflow_id: str,
    ) -> None:
        try:
            if agent_type == AgentType.PM:
                self.on_pm_completed(result, session_id, workflow_id)
            elif agent_type == AgentType.PROGRAMMER:
                self.on_programmer_completed(result, session_id, workflow_id)
            elif agent_type == AgentType.TRIAL:
                self.on_trial_completed(result, session_id, workflow_id)
        except Exception as exc:
            logger.error("[Orchestrator] 调度失败: %s", exc, exc_info=True)
            self._owner._emit_agent_error(
                workflow_id,
                session_id,
                agent_type,
                f"调度失败: {str(exc)}",
                "dispatch_error",
            )

    def on_pm_completed(self, result: AgentResult, session_id: str, workflow_id: str) -> None:
        if result.signal_tool and result.signal_tool.name == "submit_requirements":
            requirements = result.signal_tool.args
            programmer_session_id = self._owner._session_store.get_or_create_session(
                workflow_id, AgentType.PROGRAMMER
            )
            self._owner._emit_and_log(
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
            self._owner.run_agent(
                AgentType.PROGRAMMER,
                json.dumps(requirements, ensure_ascii=False),
                workflow_id,
            )
            return

        if result.signal_tool and result.signal_tool.name == "report_code_issue":
            feedback = result.signal_tool.args.get("feedback", "")
            programmer_session_id = self._owner._session_store.get_or_create_session(
                workflow_id, AgentType.PROGRAMMER
            )
            self._owner._emit_and_log(
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
            self._owner.run_agent(AgentType.PROGRAMMER, feedback, workflow_id)
            return

        logger.warning(
            "[Orchestrator] PM Agent 自然结束但未调用 signal 工具: session=%s", session_id
        )
        self._owner._emit_agent_error(
            workflow_id,
            session_id,
            AgentType.PM,
            "PM Agent 未调用 submit_requirements 或 report_code_issue 即结束",
            "missing_signal_tool",
        )

    def on_programmer_completed(
        self,
        result: AgentResult,
        session_id: str,
        workflow_id: str,
    ) -> None:
        if not (result.signal_tool and result.signal_tool.name == "submit_code"):
            logger.warning(
                "[Orchestrator] 程序员 Agent 未调用 submit_code 即结束: session=%s", session_id
            )
            self._owner._emit_agent_error(
                workflow_id,
                session_id,
                AgentType.PROGRAMMER,
                "程序员未通过 submit_code 提交代码",
                "missing_signal_tool",
            )
            return

        code_data = result.signal_tool.args
        code = code_data["code"]
        if self._owner._recording_mode(workflow_id) == RecordingMode.DESKTOP:
            syntax_result = check_code(code)
            if not syntax_result.ok:
                state = self._owner._desktop_syntax_state.setdefault(
                    workflow_id,
                    DesktopSyntaxState(),
                )
                state.retry_count += 1
                state.attempts.append(code)
                if syntax_result.feedback:
                    state.feedbacks.append(syntax_result.feedback)
                if should_retry(state.retry_count):
                    self._owner.run_agent(
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
                    sender=self._owner,
                    workflow_id=workflow_id,
                    session_id=session_id,
                    feedback=syntax_result.feedback,
                    lineno=syntax_result.lineno,
                    message=syntax_result.message,
                )
                self._owner._desktop_syntax_state.pop(workflow_id, None)
                self._owner._emit_agent_error(
                    workflow_id,
                    session_id,
                    AgentType.PROGRAMMER,
                    "Programmer 输出代码持续语法错误",
                    "desktop_syntax_error",
                )
                return
            self._owner._desktop_syntax_state.pop(workflow_id, None)
        self._owner._emit_and_log(
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
        self.run_review(code_data, session_id, workflow_id)

    def on_trial_completed(self, result: AgentResult, session_id: str, workflow_id: str) -> None:
        signal_tool = result.signal_tool
        if signal_tool and signal_tool.name == "submit_trial_result":
            success = signal_tool.args["success"]
            feedback = signal_tool.args.get("feedback", "")
        else:
            logger.warning(
                "[Orchestrator] 试用 Agent 未调用 submit_trial_result 即结束: session=%s",
                session_id,
            )
            self._owner._emit_agent_error(
                workflow_id,
                session_id,
                AgentType.TRIAL,
                "试用 Agent 未通过 submit_trial_result 结束",
                "unexpected_completion",
            )
            return

        tool = self._owner._tool_repo.get_by_workflow_id(workflow_id)
        if not tool:
            self._owner._emit_agent_error(
                workflow_id,
                session_id,
                AgentType.TRIAL,
                "未找到工具",
                "tool_not_found",
            )
            return

        self.handle_trial_result(tool.tool_id, success, workflow_id, session_id, feedback)

    def run_review(self, code_data: dict, from_session_id: str, workflow_id: str) -> None:
        code = code_data["code"]
        requirement = {
            "description": code_data.get("description", ""),
            "parameters": code_data.get("parameters", []),
        }
        retry_count = self._owner._review_counts.get(workflow_id, 0)
        try:
            review_result = self._owner._llm_reviewer.review(code, requirement)
        except Exception as exc:
            logger.error("LLM review failed for workflow %s: %s", workflow_id, exc, exc_info=True)
            self._owner._emit_agent_error(
                workflow_id,
                from_session_id,
                AgentType.PROGRAMMER,
                "LLM Review 调用失败",
                "review_error",
            )
            return

        if review_result.passed:
            self._owner._emit_and_log(
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
            self._owner._review_counts.pop(workflow_id, None)
            self._owner._save_tool(code_data, workflow_id, from_session_id)
            return

        retry_count += 1
        self._owner._review_counts[workflow_id] = retry_count
        if retry_count < 4:
            programmer_session_id = self._owner._session_store.get_or_create_session(
                workflow_id, AgentType.PROGRAMMER
            )
            self._owner._emit_and_log(
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
            self._owner.run_agent(
                AgentType.PROGRAMMER,
                f"[LLM Review 第 {retry_count} 次，共最多 3 次]\n\n审查意见：{review_result.feedback}",
                workflow_id,
            )
            return

        self._owner._emit_and_log(
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
        self._owner._review_counts.pop(workflow_id, None)
        self._owner._save_tool(code_data, workflow_id, from_session_id)

    def start_triage(self, tool_id: str, user_feedback: str, workflow_id: str) -> None:
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
        self._owner.run_agent(AgentType.PM, initial_input, workflow_id)
