"""T024: guard — 5 个调度中心工具名 ∈ build_assistant_tools 且 ∉ build_delegated_executor_tools。

CC-006：调度工具是主助理独占（用户在对话里说「帮我定时做 X」时主助理创建），不进
delegated executor（专员/子代理不应能创建定时任务）。
"""

from __future__ import annotations

from types import SimpleNamespace

from src.business.agents.config import AgentType
from src.business.orchestration.agent import AgentOrchestrator

SCHEDULED_TOOL_NAMES = {
    "create_scheduled_task",
    "list_scheduled_tasks",
    "update_scheduled_task",
    "pause_scheduled_task",
    "delete_scheduled_task",
}


def _build_assistant_tool_names(
    orchestrator: AgentOrchestrator,
    session_id: str = "ast_test_boundaries",
) -> set[str]:
    factory = orchestrator.tool_registry.build_assistant_tools(session_id)
    return {t.name for t in factory()}


def _build_executor_tool_names(
    orchestrator: AgentOrchestrator, *, agent_type: AgentType
) -> set[str]:
    factory = orchestrator.tool_registry.build_delegated_executor_tools(
        allowed_tool_ids=None,
        agent_type=agent_type,
        executor_id="exec_test",
        role_kind="executor",
    )
    return {t.name for t in factory()}


def test_scheduled_tools_in_assistant_tools(orchestrator: AgentOrchestrator):
    names = _build_assistant_tool_names(orchestrator)
    missing = SCHEDULED_TOOL_NAMES - names
    assert not missing, f"missing scheduled tools from assistant: {missing}"


def test_scheduled_tools_not_available_inside_triggered_scheduled_session(
    orchestrator: AgentOrchestrator,
    monkeypatch,
):
    scheduled_session = SimpleNamespace(
        is_scheduled=1,
        parse_tool_ids=lambda: (None, None),
    )
    monkeypatch.setattr(
        orchestrator.tool_registry._session_store,
        "get_session",
        lambda _session_id: scheduled_session,
    )

    names = _build_assistant_tool_names(orchestrator, "ast_scheduled_execution")

    leaked = SCHEDULED_TOOL_NAMES & names
    assert not leaked, f"scheduled tools leaked into triggered scheduled session: {leaked}"


def test_scheduled_tools_not_in_ephemeral_subagent(orchestrator: AgentOrchestrator):
    names = _build_executor_tool_names(orchestrator, agent_type=AgentType.EPHEMERAL_SUBAGENT)
    leaked = SCHEDULED_TOOL_NAMES & names
    assert not leaked, f"scheduled tools leaked into ephemeral subagent: {leaked}"


def test_scheduled_tools_not_in_specialist(orchestrator: AgentOrchestrator):
    names = _build_executor_tool_names(orchestrator, agent_type=AgentType.SPECIALIST)
    leaked = SCHEDULED_TOOL_NAMES & names
    assert not leaked, f"scheduled tools leaked into specialist: {leaked}"
