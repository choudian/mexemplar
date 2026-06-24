import json
import logging
from typing import Callable, Dict, Optional

from src.business.agents.config import AgentType


class WorkflowRetryCoordinator:
    def __init__(
        self,
        failure_tracker,
        session_store,
        run_agent: Callable,
        start_analysis: Callable,
        review_counts: Dict[str, int],
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._failure_tracker = failure_tracker
        self._session_store = session_store
        self._run_agent = run_agent
        self._start_analysis = start_analysis
        self._review_counts = review_counts
        self._logger = logger or logging.getLogger(__name__)

    def retry_teaching(self, workflow_id: str) -> None:
        record = self._failure_tracker.mark_retrying(workflow_id)
        if not record:
            return

        failed_stage = record.failed_stage
        self._review_counts.pop(workflow_id, None)

        if failed_stage == AgentType.PM:
            self.retry_stage(
                workflow_id,
                record,
                AgentType.PM,
                fallback_action=lambda: self._start_analysis(workflow_id, workflow_id),
            )
            return

        if failed_stage == AgentType.PROGRAMMER:
            self.retry_stage(
                workflow_id,
                record,
                AgentType.PROGRAMMER,
                transition_event="requirement_confirmed",
                transition_key="requirements",
                fallback_stage=AgentType.PM,
            )
            return

        if failed_stage == AgentType.TRIAL:
            self.retry_stage(
                workflow_id,
                record,
                AgentType.TRIAL,
                fallback_stage=AgentType.PROGRAMMER,
            )
            return

        self._logger.warning(f"[Orchestrator] 未知失败阶段 {failed_stage}，降级为 PM 重启")
        self.fallback_to_stage(workflow_id, AgentType.PM)

    def retry_stage(
        self,
        workflow_id: str,
        record,
        stage: str,
        transition_event: str | None = None,
        transition_key: str | None = None,
        fallback_stage: str | None = None,
        fallback_action=None,
        *,
        _depth: int = 0,
    ) -> None:
        session_id = self._session_store.find_old_session(workflow_id, stage)
        if session_id:
            self._run_agent(
                stage,
                None,
                workflow_id,
                session_id=session_id,
            )
            return

        if transition_event and transition_key:
            payload = self._session_store.get_transition_payload(
                workflow_id,
                transition_event,
                transition_key,
            )
            if payload:
                user_input = (
                    json.dumps(payload, ensure_ascii=False)
                    if isinstance(payload, dict)
                    else str(payload)
                )
                self._run_agent(stage, user_input, workflow_id)
                return

        if _depth >= 3:
            self._logger.error(
                f"[Orchestrator] 降级链超过最大深度: {workflow_id}，走 start_analysis 兜底"
            )
            self._start_analysis(workflow_id, workflow_id)
            return

        if fallback_action:
            fallback_action()
            return

        if fallback_stage:
            self.fallback_to_stage(workflow_id, fallback_stage, _depth=_depth + 1)
            return

        self._logger.error(f"[Orchestrator] {stage} 重试失败且无降级路径: {workflow_id}")
        self._failure_tracker.reset_retrying_status(workflow_id)

    def fallback_to_stage(
        self,
        workflow_id: str,
        target_stage: str,
        *,
        _depth: int = 0,
    ) -> None:
        record = self._failure_tracker.set_failed_stage(workflow_id, target_stage)
        if not record:
            self._failure_tracker.reset_retrying_status(workflow_id)
            return

        self.retry_stage(
            workflow_id,
            record,
            target_stage,
            fallback_action=lambda: self._start_analysis(workflow_id, workflow_id),
            _depth=_depth + 1,
        )
