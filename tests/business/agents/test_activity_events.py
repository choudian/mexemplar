"""014 US3: AgentLoop 逐步活动事件（assistant_agent_step）行为契约。

覆盖：仅可观测运行时 emit、session_id=root、子代理带 subagent_id、kind 取值、
reasoning 仅随带 tool_calls 中间消息、seq 单调、单回合上限。
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


def _capture():
    events: list[dict] = []

    def handler(sender, **kw):
        events.append(kw)

    connect("assistant_agent_step", handler, weak=False)
    return events, handler


@pytest.fixture(autouse=True)
def _clean():
    run_context.reset_for_tests()
    yield
    clear_all()
    run_context.reset_for_tests()


def _assistant_config(max_iterations=5) -> AgentConfig:
    return AgentConfig(
        agent_type=AgentType.ASSISTANT,
        system_prompt="a",
        max_iterations=max_iterations,
        text_as_user_input=True,
    )


def test_main_assistant_emits_reasoning_tool_call_and_result(mock_config, in_memory_db):
    sid = _new_session(AgentType.ASSISTANT)
    run_context.begin(sid)
    events, _ = _capture()
    llm = MockLLMClient(
        [
            LLMResponse(
                content="我先查一下",
                tool_calls=[ToolCallInfo(id="c1", name="noop", args={"q": "x"})],
            ),
            LLMResponse(content="完成", tool_calls=[]),
        ]
    )
    loop = AgentLoop(_assistant_config(), llm, mock_config)
    result = loop.run(sid, "go", tools=[_noop_tool()])
    run_context.end()

    assert result.result_type == ResultType.NEEDS_USER_INPUT
    kinds = [e["kind"] for e in events]
    assert kinds == ["reasoning", "tool_call", "tool_result"]
    # session_id 取 root，主助理 subagent_id 为 None
    assert all(e["session_id"] == sid for e in events)
    assert all(e.get("subagent_id") is None for e in events)
    # seq 单调递增
    seqs = [e["seq"] for e in events]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    # 最终无工具调用的回复（"完成"）不进时间线
    assert "完成" not in [e.get("text") for e in events]


def test_reasoning_only_with_tool_calls_message(mock_config, in_memory_db):
    """纯文本中间回复不单独 emit reasoning（与历史重建口径一致，C2-E4）。"""
    sid = _new_session(AgentType.ASSISTANT)
    run_context.begin(sid)
    events, _ = _capture()
    llm = MockLLMClient([LLMResponse(content="只是想说句话", tool_calls=[])])
    loop = AgentLoop(_assistant_config(), llm, mock_config)
    loop.run(sid, "go", tools=[_noop_tool()])
    run_context.end()
    assert events == []


def test_subagent_steps_carry_subagent_id(mock_config, in_memory_db):
    parent = _new_session(AgentType.ASSISTANT)
    child = _new_session(AgentType.EPHEMERAL_SUBAGENT)
    run_context.begin(parent)
    events, _ = _capture()
    child_llm = MockLLMClient(
        [
            LLMResponse(content="子推理", tool_calls=[ToolCallInfo(id="c1", name="noop", args={})]),
            LLMResponse(content="子完成", tool_calls=[]),
        ]
    )
    child_config = AgentConfig(
        agent_type=AgentType.EPHEMERAL_SUBAGENT, system_prompt="c", max_iterations=5
    )
    child_loop = AgentLoop(child_config, child_llm, mock_config)
    child_loop.run(child, "subtask", tools=[_noop_tool()])
    run_context.end()

    assert events
    # 子代理活动归到父会话，带自身 subagent_id
    assert all(e["session_id"] == parent for e in events)
    assert all(e["subagent_id"] == child for e in events)
