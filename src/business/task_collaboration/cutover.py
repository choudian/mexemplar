"""Clean-start cutover guard for Assistant task collaboration."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.data.repos.workflow_transition_repository import WorkflowTransitionRepository
from src.data.unified_config import get_unified_config

logger = logging.getLogger(__name__)

LEGACY_ACTIVE_DELEGATION_EVENTS = frozenset(
    {
        "assistant_delegation_started",
        "assistant_subagent_started",
        "subagent_started",
    }
)


@dataclass(frozen=True)
class CutoverState:
    enabled: bool
    reason: str = ""


class TaskCollaborationCutoverGuard:
    """Decides whether unified task dispatch may start for a clean graph."""

    def __init__(self, transition_repo: WorkflowTransitionRepository | None = None):
        self._transition_repo = transition_repo or WorkflowTransitionRepository()
        self._config = get_unified_config()

    def evaluate(self) -> CutoverState:
        config = self._config
        if not config.get_assistant_tasks_unified_dispatch_enabled():
            return CutoverState(False, "unified_dispatch_disabled")
        if not config.get_assistant_tasks_clean_start_guard_enabled():
            return CutoverState(True, "clean_start_guard_disabled")
        if self._has_legacy_active_delegation():
            return CutoverState(False, "legacy_active_delegation")
        return CutoverState(True, "")

    def assert_can_dispatch(self) -> None:
        state = self.evaluate()
        if not state.enabled:
            raise RuntimeError(state.reason or "assistant_task_dispatch_disabled")

    def _has_legacy_active_delegation(self) -> bool:
        try:
            return self._transition_repo.has_recent_event_types(
                LEGACY_ACTIVE_DELEGATION_EVENTS
            )
        except Exception:
            # Cutover guard 读不到 legacy transition 时 fail-closed：无法确认旧委派是否
            # 仍在运行，就当作存在并阻止新统一派发，避免新旧两条链路同时驱动同一任务。
            logger.warning(
                "cutover guard could not read legacy transitions; assuming legacy active",
                exc_info=True,
            )
            return True
