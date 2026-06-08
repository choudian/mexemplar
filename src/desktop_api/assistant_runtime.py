from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Optional

from src.business.agents import run_context
from src.business.agents.config import AgentType, ResultType
from src.business.orchestration.agent import AgentOrchestrator
from src.business.services.chat_service import ChatService
from src.desktop_api.confirmations import (
    clear_confirmation_session_context,
    fail_closed_confirmations_for_session,
    install_confirmation_signal,
    set_confirmation_session_context,
)
from src.desktop_api.events import event_queue
from src.desktop_api.orchestrator_runtime import build_default_orchestrator

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ContinueSubagentDirective:
    subagent_id: str
    supplemental: str = ""
    initial_return_transition_count: int = 0


class AssistantRuntime:
    """Background dispatch adapter for assistant messages in the desktop sidecar."""

    def __init__(
        self,
        orchestrator_factory: Callable[[], AgentOrchestrator] = build_default_orchestrator,
        chat_service: Optional[ChatService] = None,
    ) -> None:
        self._orchestrator_factory = orchestrator_factory
        self._chat_service = chat_service or ChatService()
        self._orchestrator: AgentOrchestrator | None = None
        self._orchestrator_lock = threading.Lock()
        self._workers: dict[str, threading.Thread] = {}
        self._workers_lock = threading.Lock()
        self._observability: Optional["AssistantObservability"] = None
        install_confirmation_signal()

    @property
    def _obs(self) -> "AssistantObservability":
        """延迟初始化的可观测读模型单例——避免每次调用重复创建 Repository 实例。"""
        if self._observability is None:
            from src.business.agents.observability import AssistantObservability

            self._observability = AssistantObservability()
        return self._observability

    def _get_orchestrator(self) -> AgentOrchestrator:
        with self._orchestrator_lock:
            if self._orchestrator is None:
                self._orchestrator = self._orchestrator_factory()
                self._orchestrator.task_worker.start()
            return self._orchestrator

    def dispatch_message(
        self,
        session_id: str,
        content: str,
        continue_subagent: dict | None = None,
    ) -> bool:
        content = content.strip()
        if not content:
            raise ValueError("content must not be empty")
        continue_directive = self._validate_continue_subagent_directive(
            session_id,
            continue_subagent,
        )

        with self._workers_lock:
            existing = self._workers.get(session_id)
            if existing is not None and existing.is_alive():
                return False

            after_sequence = self._chat_service.get_latest_display_sequence(session_id)
            worker = threading.Thread(
                target=self._run_assistant,
                args=(session_id, content, after_sequence, continue_directive),
                name=f"AssistantRuntime-{session_id}",
                daemon=True,
            )
            self._workers[session_id] = worker
            try:
                worker.start()
            except Exception:
                self._workers.pop(session_id, None)
                raise
        return True

    def _validate_continue_subagent_directive(
        self,
        session_id: str,
        raw: dict | None,
    ) -> ContinueSubagentDirective | None:
        if raw is None:
            return None
        subagent_id = str(raw.get("subagentId") or "").strip()
        if not subagent_id:
            raise ValueError("continueSubagent.subagentId must not be empty")
        supplemental = str(raw.get("supplemental") or "").strip()

        observability = self._obs
        summary = observability.find_subagent_summary(session_id, subagent_id)
        if summary is None:
            raise ValueError("找不到属于当前对话的暂停子任务")
        if summary.status == "running":
            raise ValueError("该子任务仍在运行中，不能重复继续")
        if summary.status != "suspended":
            raise ValueError("只有已暂停的子任务可以继续")
        return ContinueSubagentDirective(
            subagent_id=subagent_id,
            supplemental=supplemental,
            initial_return_transition_count=observability.count_subagent_return_transitions(
                session_id,
                subagent_id,
            ),
        )

    def cancel_session(self, session_id: str, run_id: str | None = None) -> bool:
        """对会话发出协作式停止信号（014）。

        返回 accepted：是否对一个运行中的回合发出了取消（true）/ 当前无运行回合（false）。
        深度穿透由 run_context 的 ContextVar 在同线程同步子 loop 内生效，停止一次父子皆停。
        run_id 来自 assistant.progress 的当前运行令牌；带令牌时拒绝迟到的旧停止请求误停新运行。
        """
        sid = (session_id or "").strip()
        if not sid:
            return False
        expected_run_id = (run_id or "").strip() or None
        accepted = run_context.request_cancel(sid, expected_run_id=expected_run_id)
        if not accepted:
            with self._workers_lock:
                worker = self._workers.get(sid)
                has_worker = worker is not None and worker.is_alive()
            if has_worker and expected_run_id is None:
                # 停止早于 begin() 登记 Event（早停竞态 C2-E3）：记待停止意图，begin 命中即取消。
                run_context.mark_pending_cancel(sid)
                accepted = True
        # 若回合此刻阻塞在 pending 高危确认等待中，fail-closed 当拒绝并唤醒回合到下一取消检查点
        # （FR-006b / C2-X1）；CC-001 同步确认协议 first-decision-wins / expires_at 不被破坏。
        if accepted:
            fail_closed_confirmations_for_session(sid)
        return accepted

    def get_transcript(
        self,
        session_id: str,
        subagent_id: str | None = None,
        *,
        after_sequence: int | None = None,
        before_sequence: int | None = None,
    ) -> dict:
        """过程时间线读模型 facade（014）：subagent_id 给定则取该子任务自身过程，否则取主助理过程。

        router 经此 facade 调业务读模型，不直连 Repository。
        """
        observability = self._obs
        target = (subagent_id or "").strip()
        if target:
            summary = observability.find_subagent_summary(session_id, target)
            if summary is None:
                raise LookupError("subagent transcript not found for this session")
        else:
            target = session_id
        result = observability.build_transcript(
            target,
            after_sequence=after_sequence,
            before_sequence=before_sequence,
        )
        return {
            "steps": [
                {
                    "kind": step.kind,
                    "toolName": step.tool_name,
                    "text": step.text,
                    "seq": step.seq,
                    "redacted": step.redacted,
                }
                for step in result.steps
            ],
            "compressed": result.compressed,
        }

    def list_subagents(self, session_id: str) -> dict:
        """子任务权威列表读模型 facade（014）：重连/重开会话兜底与卡片渲染。"""
        items = self._obs.build_subagent_list(session_id)
        return {
            "items": [
                {
                    "subagentId": item.subagent_id,
                    "label": item.label,
                    "task": item.task,
                    "status": item.status,
                    "lastOutput": item.last_output,
                    "turnStartSequence": item.turn_start_sequence,
                }
                for item in items
            ]
        }

    def _publish_display_messages(self, session_id: str, after_sequence: int) -> None:
        """把回合新增的可展示消息按序补发到前端（停止/完成/反问后保证已产内容不丢）。"""
        for message in self._chat_service.get_display_messages_after(session_id, after_sequence):
            event_queue.publish_nowait(
                "assistant.message",
                {
                    "sequence": message.sequence,
                    "role": message.role,
                    "content": message.content,
                    "createdAt": (message.created_at.isoformat() if message.created_at else None),
                    "rendering": (
                        "safe_markdown"
                        if message.role in ("assistant", "summary")
                        else "plain_text"
                    ),
                },
                {"sessionId": session_id},
            )

    def _publish_continue_fallback_if_needed(
        self,
        session_id: str,
        directive: ContinueSubagentDirective | None,
    ) -> None:
        if directive is None:
            return
        started = self._obs.continue_subagent_started(
            session_id,
            directive.subagent_id,
            directive.initial_return_transition_count,
        )
        if started:
            return
        event_queue.publish_nowait(
            "assistant.error",
            {
                "message": "这次没有成功唤醒该子任务，请再次点击继续任务，或补充说明后重试。",
                "type": "continue_subagent_not_started",
            },
            {"sessionId": session_id},
        )

    def _run_assistant(
        self,
        session_id: str,
        content: str,
        after_sequence: int,
        continue_directive: ContinueSubagentDirective | None = None,
    ) -> None:
        set_confirmation_session_context(session_id)
        # 在 worker 线程入口登记取消上下文（ContextVar + session→Event）；同线程同步派出的
        # 子代理/专员子 loop 自动继承，深度取消生效。begin() 会命中早到的"待停止"意图（C2-E3）。
        run_ctx = run_context.begin(session_id)
        event_queue.publish_nowait(
            "assistant.progress",
            {"status": "running", "headline": "Assistant is working", "runId": run_ctx.run_id},
            {"sessionId": session_id},
        )
        try:
            result = self._get_orchestrator().run_agent(
                AgentType.ASSISTANT,
                content,
                session_id=session_id,
                assistant_continue_intent=(
                    {
                        "subagent_id": continue_directive.subagent_id,
                        "instruction": continue_directive.supplemental,
                    }
                    if continue_directive is not None
                    else None
                ),
            )
            if result is None or result.result_type == ResultType.MAX_ITERATIONS_REACHED:
                message = result.error if result is not None else "Assistant did not complete."
                event_queue.publish_nowait(
                    "assistant.progress",
                    {"status": "failed", "headline": message},
                    {"sessionId": session_id},
                )
                self._publish_continue_fallback_if_needed(session_id, continue_directive)
                return
            if result.result_type == ResultType.ERROR:
                event_queue.publish_nowait(
                    "assistant.progress",
                    {"status": "failed", "headline": result.error or "Assistant failed."},
                    {"sessionId": session_id},
                )
                self._publish_continue_fallback_if_needed(session_id, continue_directive)
                return
            if result.result_type == ResultType.CANCELLED:
                # 用户主动停止（014）：flush 已产增量消息（已产内容不丢，FR-008），发"已停止"进度。
                self._publish_display_messages(session_id, after_sequence)
                event_queue.publish_nowait(
                    "assistant.progress",
                    {"status": "cancelled", "headline": "已停止"},
                    {"sessionId": session_id},
                )
                return
            if result.result_type == ResultType.NEEDS_USER_INPUT:
                self._publish_display_messages(session_id, after_sequence)
                event_queue.publish_nowait(
                    "assistant.progress",
                    {"status": "waiting_for_user", "headline": result.question or ""},
                    {"sessionId": session_id},
                )
                self._publish_continue_fallback_if_needed(session_id, continue_directive)
                return
            self._publish_display_messages(session_id, after_sequence)
            event_queue.publish_nowait(
                "assistant.progress",
                {"status": "succeeded", "headline": "Assistant response ready"},
                {"sessionId": session_id},
            )
            self._publish_continue_fallback_if_needed(session_id, continue_directive)
        except Exception as exc:
            logger.error(
                "Assistant runtime failed for session %s: %s", session_id, exc, exc_info=True
            )
            event_queue.publish_nowait(
                "assistant.progress",
                {"status": "failed", "headline": "Assistant failed to complete the request."},
                {"sessionId": session_id},
            )
            event_queue.publish_nowait(
                "assistant.error",
                {
                    "message": "Assistant failed to complete the request.",
                    "type": type(exc).__name__,
                },
                {"sessionId": session_id},
            )
        finally:
            run_context.end()
            clear_confirmation_session_context()
            with self._workers_lock:
                if self._workers.get(session_id) is threading.current_thread():
                    self._workers.pop(session_id, None)
