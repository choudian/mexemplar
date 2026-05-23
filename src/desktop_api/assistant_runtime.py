from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Optional

from src.business.agents.config import AgentType, ResultType
from src.business.agents.tools.builtin_general_tools import register_confirm_mechanism
from src.business.orchestration.agent import AgentOrchestrator
from src.business.services.chat_service import ChatService
from src.desktop_api.confirmations import (
    clear_confirmation_session_context,
    confirmation_event_payload,
    set_confirmation_session_context,
)
from src.desktop_api.events import event_queue
from src.desktop_api.orchestrator_runtime import build_default_orchestrator

logger = logging.getLogger(__name__)


class _SidecarConfirmationSignal:
    """Small signal shim matching the builtin high-risk confirmation protocol."""

    def emit(self, request_id: str, _message: str) -> None:
        payload = confirmation_event_payload(request_id)
        session_id = str(payload.get("sessionId") or "")
        event_queue.publish_nowait(
            "assistant.confirmation",
            payload,
            {"sessionId": session_id} if session_id else None,
        )


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
        register_confirm_mechanism(_SidecarConfirmationSignal())

    def _get_orchestrator(self) -> AgentOrchestrator:
        with self._orchestrator_lock:
            if self._orchestrator is None:
                self._orchestrator = self._orchestrator_factory()
                self._orchestrator.task_worker.start()
            return self._orchestrator

    def dispatch_message(self, session_id: str, content: str) -> bool:
        content = content.strip()
        if not content:
            raise ValueError("content must not be empty")

        existing = self._workers.get(session_id)
        if existing is not None and existing.is_alive():
            return False

        after_sequence = self._chat_service.get_latest_display_sequence(session_id)
        worker = threading.Thread(
            target=self._run_assistant,
            args=(session_id, content, after_sequence),
            name=f"AssistantRuntime-{session_id}",
            daemon=True,
        )
        self._workers[session_id] = worker
        worker.start()
        return True

    def _run_assistant(self, session_id: str, content: str, after_sequence: int) -> None:
        event_queue.publish_nowait(
            "assistant.progress",
            {"status": "running", "headline": "Assistant is working"},
            {"sessionId": session_id},
        )
        set_confirmation_session_context(session_id)
        try:
            result = self._get_orchestrator().run_agent(
                AgentType.ASSISTANT,
                content,
                session_id=session_id,
            )
            if result is None or result.result_type in (
                ResultType.ERROR,
                ResultType.MAX_ITERATIONS_REACHED,
            ):
                message = result.error if result is not None else "Assistant did not complete."
                event_queue.publish_nowait(
                    "assistant.progress",
                    {"status": "failed", "headline": message},
                    {"sessionId": session_id},
                )
                return
            if result.result_type == ResultType.NEEDS_USER_INPUT:
                for message in self._chat_service.get_display_messages_after(
                    session_id, after_sequence
                ):
                    event_queue.publish_nowait(
                        "assistant.message",
                        {
                            "sequence": message.sequence,
                            "role": message.role,
                            "content": message.content,
                            "createdAt": message.created_at.isoformat() if message.created_at else None,
                            "rendering": (
                                "safe_markdown" if message.role in ("assistant", "summary") else "plain_text"
                            ),
                        },
                        {"sessionId": session_id},
                    )
                event_queue.publish_nowait(
                    "assistant.progress",
                    {"status": "waiting_for_user", "headline": result.question or ""},
                    {"sessionId": session_id},
                )
                return
            for message in self._chat_service.get_display_messages_after(
                session_id, after_sequence
            ):
                event_queue.publish_nowait(
                    "assistant.message",
                    {
                        "sequence": message.sequence,
                        "role": message.role,
                        "content": message.content,
                        "createdAt": message.created_at.isoformat() if message.created_at else None,
                        "rendering": (
                            "safe_markdown" if message.role in ("assistant", "summary") else "plain_text"
                        ),
                    },
                    {"sessionId": session_id},
                )
            event_queue.publish_nowait(
                "assistant.progress",
                {"status": "succeeded", "headline": "Assistant response ready"},
                {"sessionId": session_id},
            )
        except Exception as exc:
            logger.error(
                "Assistant runtime failed for session %s: %s", session_id, exc, exc_info=True
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
            clear_confirmation_session_context()
            self._workers.pop(session_id, None)
