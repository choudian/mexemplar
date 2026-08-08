"""014 US4: orchestrator 委派点发出子任务生命周期事件（started/finished/paused）。"""

from unittest.mock import MagicMock, patch

import pytest

from src.business.agents.config import AgentResult, ResultType
from src.business.orchestration.agent.orchestrator import AgentOrchestrator
from src.utils.events import clear_all, connect


@pytest.fixture
def orch(mock_config, in_memory_db):
    return AgentOrchestrator(MagicMock(), mock_config)


@pytest.fixture(autouse=True)
def _clean_signals():
    yield
    clear_all()


@pytest.fixture(autouse=True)
def _bypass_user_task_validation(monkeypatch):
    """这些测试验证委派生命周期事件，不关心 taskId 校验。"""
    monkeypatch.setattr(
        "src.business.orchestration.agent.delegation_orchestrator._validate_user_task_id",
        lambda _uid: None,
    )


def _capture(signal_name: str) -> list[dict]:
    events: list[dict] = []
    connect(signal_name, lambda sender, **kw: events.append(kw), weak=False)
    return events


def _patch_loop(orch, run_result):
    patches = [
        patch("src.business.orchestration.agent.orchestrator.AgentLoop"),
        patch.object(orch, "_build_delegated_executor_tools", return_value=[]),
        patch.object(orch, "_resolve_user_tool_ids", return_value=set()),
    ]
    started = [p.start() for p in patches]
    started[0].return_value.run.return_value = run_result
    return patches


def test_delegation_emits_started_and_finished(orch):
    started_events = _capture("assistant_subagent_started")
    finished_events = _capture("assistant_subagent_finished")
    patches = _patch_loop(orch, AgentResult(result_type=ResultType.COMPLETED))
    try:
        with (
            patch.object(orch, "_extract_latest_assistant_text", return_value="子任务结果"),
            patch.object(orch, "_record_delegation_signal"),
        ):
            res = orch._delegate_to_subagent(
                parent_session_id="parent-LE",
                task_description="查资料",
                user_task_id="utsk_test",
            )
    finally:
        for p in patches:
            p.stop()

    assert res["success"] is True
    # started：归属父会话、running、带 label/task
    assert len(started_events) == 1
    assert started_events[0]["session_id"] == "parent-LE"
    assert started_events[0]["status"] == "running"
    assert started_events[0]["label"] == "子助手"
    # finished：done + last_output
    assert len(finished_events) == 1
    assert finished_events[0]["status"] == "done"
    assert finished_events[0]["last_output"] == "子任务结果"
