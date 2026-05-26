from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from src.business.ai.llm_client import LangChainLLMClient
from src.business.agents.config import AgentType
from src.business.orchestration.agent import AgentOrchestrator
from src.data.credential_resolver import (
    ReadOnlyCredentialResolver,
    get_real_tour_credential_resolver,
    is_real_tour_runtime,
)
from src.data.unified_config import get_unified_config
from src.desktop_api.events import event_queue

logger = logging.getLogger(__name__)


def build_default_orchestrator(
    credential_resolver: ReadOnlyCredentialResolver | None = None,
) -> AgentOrchestrator:
    config = get_unified_config()
    resolver = credential_resolver or (
        get_real_tour_credential_resolver() if is_real_tour_runtime() else None
    )
    api_key = resolver.get_ai_api_key() if resolver is not None else config.get_ai_api_key()
    llm_client = LangChainLLMClient(
        provider=config.get_ai_provider(),
        model=config.get_ai_model(),
        api_key=api_key,
        base_url=config.get_ai_base_url(),
        temperature=0.7,
        thinking_level=config.get_ai_thinking_level(),
        timeout=config.get_ai_request_timeout(),
    )
    return AgentOrchestrator(llm_client=llm_client, config=config)


class DesktopAgentRuntime:
    """Runs long-lived AgentOrchestrator work outside request handlers."""

    def __init__(
        self,
        orchestrator_factory: Callable[[], AgentOrchestrator] = build_default_orchestrator,
    ) -> None:
        self._orchestrator_factory = orchestrator_factory
        self._orchestrator: AgentOrchestrator | None = None
        self._orchestrator_lock = threading.Lock()
        self._trial_history_service = None
        self._workers: dict[str, threading.Thread] = {}
        self._workers_lock = threading.Lock()

    def _get_orchestrator(self) -> AgentOrchestrator:
        with self._orchestrator_lock:
            if self._orchestrator is None:
                self._orchestrator = self._orchestrator_factory()
                self._orchestrator.task_worker.start()
            return self._orchestrator

    def start_learning(self, workflow_id: str, _mode: str) -> bool:
        return self._start_worker(
            f"learning:{workflow_id}",
            self._run_learning,
            workflow_id,
        )

    def continue_learning(self, workflow_id: str, user_reply: str) -> bool:
        return self._start_worker(
            f"learning:{workflow_id}",
            self._run_continue_learning,
            workflow_id,
            user_reply,
        )

    def start_tool_trial(self, tool_id: str, workflow_id: str) -> bool:
        return self._start_worker(
            f"trial:{workflow_id}",
            self._run_tool_trial,
            tool_id,
            workflow_id,
        )

    def continue_tool_trial(self, workflow_id: str, user_reply: str) -> bool:
        return self._start_worker(
            f"trial:{workflow_id}",
            self._run_continue_trial,
            workflow_id,
            user_reply,
        )

    def get_trial_history(self, workflow_id: str) -> list[dict]:
        from src.business.orchestration.agent.trial_history_service import TrialHistoryService

        if self._trial_history_service is None:
            self._trial_history_service = TrialHistoryService()
        return self._trial_history_service.get_trial_history(workflow_id)

    def retry_teaching_failure(self, workflow_id: str) -> bool:
        return self._start_worker(
            f"retry:{workflow_id}",
            self._run_teaching_retry,
            workflow_id,
        )

    def _start_worker(self, key: str, target: Callable[..., None], *args: object) -> bool:
        with self._workers_lock:
            existing = self._workers.get(key)
            if existing is not None and existing.is_alive():
                return False

            worker = threading.Thread(
                target=self._run_worker,
                args=(key, target, args),
                name=f"DesktopAgentRuntime-{key}",
                daemon=True,
            )
            self._workers[key] = worker
            worker.start()
            return True

    def _run_worker(self, key: str, target: Callable[..., None], args: tuple[object, ...]) -> None:
        try:
            target(*args)
        except Exception as exc:
            logger.error("Desktop agent runtime worker failed: %s", exc, exc_info=True)
            workflow_id = next((str(arg) for arg in reversed(args) if isinstance(arg, str)), "")
            event_type = "trial.progress" if key.startswith("trial:") else "teaching.progress"
            event_queue.publish_nowait(
                event_type,
                {
                    "status": "failed",
                    "headline": "Agent workflow failed to start",
                    "error": str(exc),
                    "type": type(exc).__name__,
                },
                {"workflowId": workflow_id} if workflow_id else None,
            )
        finally:
            with self._workers_lock:
                self._workers.pop(key, None)

    def _run_learning(self, workflow_id: str) -> None:
        event_queue.publish_nowait(
            "teaching.progress",
            {"status": "running", "headline": "Skill learning started"},
            {"workflowId": workflow_id},
        )
        self._get_orchestrator().start_analysis(workflow_id, workflow_id)

    def _run_continue_agent(self, agent_type: AgentType, workflow_id: str, user_reply: str) -> None:
        self._get_orchestrator().run_agent(agent_type, user_reply, workflow_id=workflow_id)

    def _run_continue_learning(self, workflow_id: str, user_reply: str) -> None:
        self._run_continue_agent(AgentType.PM, workflow_id, user_reply)

    def _run_tool_trial(self, tool_id: str, workflow_id: str) -> None:
        event_queue.publish_nowait(
            "trial.progress",
            {"status": "running", "headline": "Skill trial started", "toolId": tool_id},
            {"workflowId": workflow_id, "toolId": tool_id},
        )
        self._get_orchestrator().start_trial(
            tool_id,
            "开始试用",
            workflow_id,
        )

    def _run_continue_trial(self, workflow_id: str, user_reply: str) -> None:
        self._run_continue_agent(AgentType.TRIAL, workflow_id, user_reply)

    def _run_teaching_retry(self, workflow_id: str) -> None:
        event_queue.publish_nowait(
            "teaching.progress",
            {"status": "running", "headline": "Skill teaching retry started"},
            {"workflowId": workflow_id},
        )
        self._get_orchestrator().retry_coordinator.retry_teaching(workflow_id)


_runtime: DesktopAgentRuntime | None = None


def get_desktop_agent_runtime() -> DesktopAgentRuntime:
    global _runtime
    if _runtime is None:
        _runtime = DesktopAgentRuntime()
    return _runtime
