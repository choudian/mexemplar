import json
import uuid

from src.business.agents.agent_loop import AgentLoop
from src.business.agents.config import AgentConfig, AgentType, ResultType, ToolDefinition
from src.business.ai.llm_client import LLMResponse, ToolCallInfo
from src.data.repositories import MessageRepository
from tests.conftest import MockLLMClient


def _new_session(agent_type: AgentType) -> str:
    from src.business.orchestration.agent.agent_session_store import AgentSessionStore
    from src.data.repositories import (
        SessionRepository,
        WorkflowTransitionRepository,
    )

    store = AgentSessionStore(
        session_repo=SessionRepository(),
        message_repo=MessageRepository(),
        transition_repo=WorkflowTransitionRepository(),
    )
    return store.create_session(f"wf-{uuid.uuid4().hex[:8]}", agent_type)


def _assistant_config() -> AgentConfig:
    return AgentConfig(
        agent_type=AgentType.ASSISTANT,
        system_prompt="assistant",
        max_iterations=3,
        text_as_user_input=True,
    )


def _leaked_tool(name: str, calls: dict[str, int]) -> ToolDefinition:
    def handler(**kwargs):
        calls[name] = calls.get(name, 0) + 1
        return json.dumps({"ok": True})

    return ToolDefinition(
        name=name,
        schema={
            "type": "function",
            "function": {
                "name": name,
                "description": "leaked tool",
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        },
        handler=handler,
        has_side_effects=False,
    )


def _run_forbidden_call(mock_config, tool_name: str) -> tuple[dict[str, int], str]:
    sid = _new_session(AgentType.ASSISTANT)
    calls: dict[str, int] = {}
    llm = MockLLMClient(
        [
            LLMResponse(
                content=None,
                tool_calls=[ToolCallInfo(id="call_forbidden", name=tool_name, args={})],
            ),
            LLMResponse(content="done", tool_calls=[]),
        ]
    )
    loop = AgentLoop(_assistant_config(), llm, mock_config)

    result = loop.run(sid, "go", tools=[_leaked_tool(tool_name, calls)])

    assert result.result_type == ResultType.NEEDS_USER_INPUT
    tool_results = [
        message.content
        for message in MessageRepository().get_context(sid)
        if message.role == "tool"
    ]
    return calls, "\n".join(tool_results)


def test_assistant_rejects_leaked_builtin_read_tool(mock_config, in_memory_db):
    calls, persisted = _run_forbidden_call(mock_config, "read_file")

    assert calls == {}
    assert "assistant_tool_forbidden" in persisted
    assert "主助理不能直接调用工具 'read_file'" in persisted


def test_assistant_rejects_leaked_dynamic_execution_tool(mock_config, in_memory_db):
    calls, persisted = _run_forbidden_call(mock_config, "utool_abcdef12")

    assert calls == {}
    assert "assistant_tool_forbidden" in persisted
    assert "主助理不能直接调用动态执行工具 'utool_abcdef12'" in persisted


def test_assistant_forbidden_mixed_batch_pairs_every_tool_call(mock_config, in_memory_db):
    sid = _new_session(AgentType.ASSISTANT)
    calls: dict[str, int] = {}
    llm = MockLLMClient(
        [
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallInfo(id="call_forbidden", name="read_file", args={}),
                    ToolCallInfo(id="call_allowed", name="allowed_coordination", args={}),
                ],
            ),
            LLMResponse(content="done", tool_calls=[]),
        ]
    )
    loop = AgentLoop(_assistant_config(), llm, mock_config)

    result = loop.run(
        sid,
        "go",
        tools=[
            _leaked_tool("read_file", calls),
            _leaked_tool("allowed_coordination", calls),
        ],
    )

    assert result.result_type == ResultType.NEEDS_USER_INPUT
    assert calls == {}
    tool_results = [
        message for message in MessageRepository().get_context(sid) if message.role == "tool"
    ]
    assert [message.tool_call_id for message in tool_results] == [
        "call_forbidden",
        "call_allowed",
    ]
    persisted = "\n".join(message.content for message in tool_results)
    assert "assistant_tool_forbidden" in persisted
    assert "invalid_model_output" in persisted
