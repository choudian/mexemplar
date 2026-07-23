"""Specialists are long-lived executors and must be resumable like subagents (1.2).

They previously died outright at the turn limit while ephemeral subagents — the
throwaway ones — could be paused and resumed. The ownership checks already work
for both, because both get their workflow_id from the same generator.
"""

from __future__ import annotations

from src.business.agents.config import AgentType
from src.business.orchestration.agent.orchestrator import AgentOrchestrator


class _Session:
    def __init__(self, agent_type, workflow_id):
        self.agent_type = agent_type
        self.workflow_id = workflow_id


class _Store:
    def __init__(self, session):
        self._session = session

    def get_session(self, _sid):
        return self._session


def _orchestrator_with(session):
    orch = object.__new__(AgentOrchestrator)
    orch._session_store = _Store(session)
    # Force the workflow-hash branch: no transition rows exist in this fixture.
    orch._subagent_transition_belongs_to_parent = lambda *_a, **_k: False
    return orch


def _resolve(session, parent_id, subagent_id="ast_child"):
    orch = _orchestrator_with(session)
    return AgentOrchestrator._resolve_subagent_session(orch, parent_id, subagent_id)


def test_specialist_sessions_are_now_resolvable():
    parent = "ast_parent_session"
    workflow_id = AgentOrchestrator._new_delegation_workflow_id(parent)

    resolved = _resolve(_Session(AgentType.SPECIALIST, workflow_id), parent)

    assert resolved is not None


def test_ephemeral_subagents_keep_working():
    parent = "ast_parent_session"
    workflow_id = AgentOrchestrator._new_delegation_workflow_id(parent)

    resolved = _resolve(_Session(AgentType.EPHEMERAL_SUBAGENT, workflow_id), parent)

    assert resolved is not None


def test_a_different_parent_is_still_refused():
    workflow_id = AgentOrchestrator._new_delegation_workflow_id("ast_someone_else")

    resolved = _resolve(_Session(AgentType.SPECIALIST, workflow_id), "ast_parent_session")

    assert resolved is None


def test_other_agent_types_remain_out_of_reach():
    parent = "ast_parent_session"
    workflow_id = AgentOrchestrator._new_delegation_workflow_id(parent)

    for agent_type in (AgentType.ASSISTANT, AgentType.PM, AgentType.PROGRAMMER):
        assert _resolve(_Session(agent_type, workflow_id), parent) is None


def test_blank_identifiers_are_refused():
    parent = "ast_parent_session"
    workflow_id = AgentOrchestrator._new_delegation_workflow_id(parent)
    session = _Session(AgentType.SPECIALIST, workflow_id)

    assert _resolve(session, "", "ast_child") is None
    assert _resolve(session, parent, "") is None
