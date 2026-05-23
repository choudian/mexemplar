import logging
from src.utils.timezone import utc_now_naive
from typing import Optional

from src.business.agents.config import AgentType

from .ports import EventBusPort


class TeachingFailureTracker:
    def __init__(
        self,
        failure_repo,
        event_bus: EventBusPort,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._failure_repo = failure_repo
        self._event_bus = event_bus
        self._logger = logger or logging.getLogger(__name__)

    def connect_signals(self) -> None:
        self._event_bus.connect("agent_error", self.on_agent_error_for_failure)

    def on_agent_error_for_failure(self, sender, **kwargs):
        del sender
        agent_type = kwargs.get("agent_type", "")
        workflow_id = kwargs.get("workflow_id", "")
        self._logger.info(
            f"[FailureTracker] 收到 agent_error: agent_type={agent_type}, workflow_id={workflow_id}"
        )
        if agent_type not in (AgentType.PM, AgentType.PROGRAMMER, AgentType.TRIAL):
            self._logger.debug(f"[FailureTracker] 跳过非教学 agent_type={agent_type}")
            return

        if not workflow_id:
            self._logger.warning("[FailureTracker] agent_error 缺少 workflow_id，跳过")
            return

        existing = self._failure_repo.get_by_workflow_id(workflow_id)
        if existing and existing.status == "retrying":
            existing.status = "active"
            existing.failed_stage = agent_type
            existing.error_summary = (kwargs.get("error", "") or "")[:500]
            existing.error_type = kwargs.get("error_type", "")
            existing.retry_count = (existing.retry_count or 0) + 1
            self._failure_repo.update(existing)
            self._event_bus.emit(
                "teaching_failure_updated",
                workflow_id=workflow_id,
                failed_stage=agent_type,
                error_type=existing.error_type,
            )
            self._logger.info(f"[FailureTracker] 更新 retrying 记录: workflow={workflow_id}")
            return

        self._logger.info(f"[FailureTracker] 新建失败记录: workflow={workflow_id}, stage={agent_type}")
        self.record_teaching_failure(
            workflow_id=workflow_id,
            failed_stage=agent_type,
            error_summary=kwargs.get("error", ""),
            error_type=kwargs.get("error_type", ""),
        )

    def record_teaching_failure(
        self,
        *,
        workflow_id: str,
        failed_stage: str,
        error_summary: str,
        error_type: str,
    ) -> None:
        is_new = self._failure_repo.upsert_by_workflow(
            workflow_id=workflow_id,
            failed_stage=failed_stage,
            error_summary=(error_summary or "")[:500],
            error_type=error_type,
        )
        self._event_bus.emit(
            "teaching_failure_updated",
            workflow_id=workflow_id,
            failed_stage=failed_stage,
            error_type=error_type,
            is_new=is_new,
        )

    def set_failure_status(self, workflow_id: str, new_status: str, event_name: str) -> None:
        record = self._failure_repo.get_by_workflow_id(workflow_id)
        if not record:
            return
        if record.status in ("resolved", "dismissed"):
            return

        record.status = new_status
        if new_status == "resolved":
            record.resolved_at = utc_now_naive()
        self._failure_repo.update(record)
        self._event_bus.emit(event_name, workflow_id=workflow_id)

    def resolve_failure_record(self, workflow_id: str) -> None:
        self.set_failure_status(workflow_id, "resolved", "teaching_failure_resolved")

    def try_resolve_failure(self, workflow_id: str) -> None:
        record = self._failure_repo.get_by_workflow_id(workflow_id)
        if record and record.status == "retrying":
            self.resolve_failure_record(workflow_id)

    def reset_retrying_status(self, workflow_id: str) -> None:
        record = self._failure_repo.get_by_workflow_id(workflow_id)
        if record and record.status == "retrying":
            record.status = "active"
            record.retry_count = (record.retry_count or 0) + 1
            self._failure_repo.update(record)
            self._event_bus.emit(
                "teaching_failure_updated",
                workflow_id=workflow_id,
                failed_stage=record.failed_stage,
                error_type=record.error_type or "",
            )

    def mark_retrying(self, workflow_id: str):
        record = self._failure_repo.get_by_workflow_id(workflow_id)
        if not record:
            self._logger.warning(
                f"[Orchestrator] 重试失败：找不到 workflow_id={workflow_id} 的失败记录"
            )
            self._event_bus.emit(
                "agent_error",
                workflow_id=workflow_id,
                agent_type=AgentType.TRIAL,
                error="重试失败：找不到对应的失败记录",
                error_type="retry_error",
            )
            return None

        if record.status != "active":
            self._logger.warning(
                f"[Orchestrator] 跳过重试：记录状态为 {record.status}，workflow_id={workflow_id}"
            )
            return None

        record.status = "retrying"
        self._failure_repo.update(record)
        self._event_bus.emit(
            "teaching_failure_retrying",
            workflow_id=workflow_id,
            failed_stage=record.failed_stage,
        )
        return record

    def set_failed_stage(self, workflow_id: str, target_stage: str):
        record = self._failure_repo.get_by_workflow_id(workflow_id)
        if not record:
            return None

        record.failed_stage = target_stage
        self._failure_repo.update(record)
        self._event_bus.emit(
            "teaching_failure_updated",
            workflow_id=workflow_id,
            failed_stage=target_stage,
            error_type=record.error_type or "",
        )
        return record
