"""014 门卫：非助理 Agent（PM/Programmer/Trial）零 assistant_agent_step、行为零变化（E4/CC-005）。

这些 Agent 从不 begin run_context（ContextVar 空），AgentLoop 必须不 emit 任何活动事件，
且运行结果与未引入 014 前一致——一旦回归即提示活动事件门控破裂。
"""

import json
import uuid

import pytest

from src.business.agents import run_context
from src.business.agents.agent_loop import AgentLoop
from src.business.agents.config import AgentConfig, AgentType, ResultType, ToolDefinition
from src.business.ai.llm_client import LLMResponse, ToolCallInfo
from src.utils.events import clear_all, connect
from tests.conftest import MockLLMClient


def _noop_tool() -> ToolDefinition:
    return ToolDefinition(
        name="noop",
        schema={"type": "object", "properties": {}},
        handler=lambda **kw: json.dumps({"ok": True}),
    )


def _new_session(agent_type: AgentType) -> str:
    from src.business.orchestration.agent.agent_session_store import AgentSessionStore
    from src.data.repositories import (
        MessageRepository,
        SessionRepository,
        WorkflowTransitionRepository,
    )

    store = AgentSessionStore(
        session_repo=SessionRepository(),
        message_repo=MessageRepository(),
        transition_repo=WorkflowTransitionRepository(),
    )
    return store.create_session(f"wf-{uuid.uuid4().hex[:8]}", agent_type)


@pytest.fixture(autouse=True)
def _clean():
    run_context.reset_for_tests()
    yield
    clear_all()
    run_context.reset_for_tests()


def test_pm_agent_emits_zero_activity_and_behavior_unchanged(mock_config, in_memory_db):
    sid = _new_session(AgentType.PM)
    captured: list[dict] = []
    connect("assistant_agent_step", lambda sender, **kw: captured.append(kw), weak=False)

    # PM 从不 begin run_context（非助理执行链路）
    llm = MockLLMClient(
        [
            LLMResponse(content=None, tool_calls=[ToolCallInfo(id="c1", name="noop", args={})]),
            LLMResponse(content="需要确认需求？", tool_calls=[]),
        ]
    )
    config = AgentConfig(
        agent_type=AgentType.PM, system_prompt="pm", max_iterations=5, text_as_user_input=True
    )
    loop = AgentLoop(config, llm, mock_config)
    result = loop.run(sid, "go", tools=[_noop_tool()])

    assert captured == []  # 零活动事件
    assert result.result_type == ResultType.NEEDS_USER_INPUT  # 行为零变化
