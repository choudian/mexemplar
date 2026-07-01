"""AgentLoop 独占工具（requires_exclusive_call）行为测试（019）。

覆盖：
- solo 独占工具阻塞执行后 loop 同回合续跑
- 独占工具与普通工具混批 -> 零执行、全部 invalid_model_output、完整配对
- 独占工具与中断型工具混批 -> 零执行、全部 invalid_model_output
"""

import json

import pytest

from src.business.agents.agent_loop import AgentLoop
from src.business.agents.config import (
    AgentConfig,
    AgentType,
    ResultType,
    ToolDefinition,
    ToolSignal,
)
from src.business.ai.llm_client import LLMResponse, ToolCallInfo
from tests.conftest import MockLLMClient


@pytest.fixture
def loop_config():
    return AgentConfig(
        agent_type=AgentType.ASSISTANT,
        system_prompt="You are a test agent.",
        max_iterations=10,
    )


def _exclusive_tool(handler):
    return ToolDefinition(
        name="ask_user_question",
        schema={"type": "object", "properties": {}},
        handler=handler,
        requires_exclusive_call=True,
        has_side_effects=False,
    )


def test_solo_exclusive_tool_executes_and_continues(loop_config, mock_config, in_memory_db):
    """solo 独占工具：handler 执行、结果落库、loop 同回合续跑到下一步。"""
    calls = {"n": 0}

    def _handler(**kwargs):
        calls["n"] += 1
        return json.dumps(
            {
                "status": "answered",
                "answers": [{"question": "X", "selectedLabels": ["A"], "otherText": None}],
            }
        )

    responses = [
        LLMResponse(
            content=None, tool_calls=[ToolCallInfo(id="c1", name="ask_user_question", args={})]
        ),
        LLMResponse(content="done", tool_calls=[]),
    ]
    loop = AgentLoop(loop_config, MockLLMClient(responses), mock_config)
    result = loop.run(session_id="excl-solo", user_input="t", tools=[_exclusive_tool(_handler)])

    assert result.result_type == ResultType.COMPLETED
    assert calls["n"] == 1
    ctx = loop._get_context_manager("excl-solo")
    messages = ctx._msg_repo.get_context("excl-solo")
    tool_results = [m for m in messages if m.role == "tool"]
    assert len(tool_results) == 1
    assert json.loads(tool_results[0].content)["status"] == "answered"


def test_exclusive_mixed_with_ordinary_zero_execution(loop_config, mock_config, in_memory_db):
    """独占工具与普通工具混批 -> 零执行、两条都 invalid_model_output、完整配对。"""
    calls = {"excl": 0, "ord": 0}

    def _excl(**kwargs):
        calls["excl"] += 1
        return json.dumps({"status": "answered", "answers": []})

    tools = [
        _exclusive_tool(_excl),
        ToolDefinition(
            name="tool_a",
            schema={"type": "object", "properties": {}},
            handler=lambda **kw: calls.__setitem__("ord", calls["ord"] + 1) or "ok",
        ),
    ]
    responses = [
        LLMResponse(
            content=None,
            tool_calls=[
                ToolCallInfo(id="c1", name="ask_user_question", args={}),
                ToolCallInfo(id="c2", name="tool_a", args={}),
            ],
        ),
        LLMResponse(content="replanned", tool_calls=[]),
    ]
    loop = AgentLoop(loop_config, MockLLMClient(responses), mock_config)
    loop.run(session_id="excl-mixed", user_input="t", tools=tools)

    assert calls == {"excl": 0, "ord": 0}
    ctx = loop._get_context_manager("excl-mixed")
    tool_results = [m for m in ctx._msg_repo.get_context("excl-mixed") if m.role == "tool"]
    assert len(tool_results) == 2
    for tr in tool_results:
        assert json.loads(tr.content)["error"] == "invalid_model_output"


def test_exclusive_mixed_with_interrupting_zero_execution(loop_config, mock_config, in_memory_db):
    """独占工具与中断型工具混批 -> 零执行、全部 invalid_model_output。"""
    calls = {"excl": 0, "reply": 0}

    def _reply(**kwargs):
        calls["reply"] += 1
        return ToolSignal(result_type=ResultType.NEEDS_USER_INPUT, display_text="hi")

    tools = [
        _exclusive_tool(lambda **kw: calls.__setitem__("excl", calls["excl"] + 1) or "{}"),
        ToolDefinition(
            name="reply_to_user",
            schema={"type": "object", "properties": {}},
            handler=_reply,
            is_interrupting=True,
        ),
    ]
    responses = [
        LLMResponse(
            content=None,
            tool_calls=[
                ToolCallInfo(id="c1", name="ask_user_question", args={}),
                ToolCallInfo(id="c2", name="reply_to_user", args={}),
            ],
        ),
        LLMResponse(content="replanned", tool_calls=[]),
    ]
    loop = AgentLoop(loop_config, MockLLMClient(responses), mock_config)
    loop.run(session_id="excl-interrupt", user_input="t", tools=tools)

    assert calls == {"excl": 0, "reply": 0}
    ctx = loop._get_context_manager("excl-interrupt")
    tool_results = [m for m in ctx._msg_repo.get_context("excl-interrupt") if m.role == "tool"]
    assert len(tool_results) == 2
    for tr in tool_results:
        assert json.loads(tr.content)["error"] == "invalid_model_output"
