"""Trial history facade for desktop API adapters."""

from __future__ import annotations

from src.business.orchestration.agent.agent_session_store import AgentSessionStore
from src.data.repos import MessageRepository, SessionRepository, WorkflowTransitionRepository


class TrialHistoryService:
    """Read trial messages through the business orchestration boundary."""

    def __init__(self, store: AgentSessionStore | None = None):
        self._store = store or AgentSessionStore(
            SessionRepository(),
            MessageRepository(),
            WorkflowTransitionRepository(),
        )

    def get_trial_history(self, workflow_id: str) -> list[dict]:
        return self._store.get_trial_messages(workflow_id)
