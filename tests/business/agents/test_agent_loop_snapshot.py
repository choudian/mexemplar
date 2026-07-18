"""
032 T003: AgentLoop LLM 消息快照生命周期(行为契约)。

- LLM 响应路径:工具批次执行期间快照可见,位置/role/content 与本轮送入 LLM
  的 messages 一致,但不共享可变引用。
- run 返回后快照清除。
- pending tool calls 恢复路径:无快照(委派 fail-closed 的边界)。
- initial_tool_calls 程序注入路径:无快照。
"""

import json
import uuid
from unittest.mock import MagicMock

import pytest

from src.business.agents import run_context
from src.business.agents.agent_loop import AgentLoop, _serialize_tool_calls
from src.business.agents.config import (
    AgentConfig,
    AgentType,
    ToolDefinition,
)
from src.business.agents.delegation_context import get_llm_messages_snapshot
from src.business.ai.llm_client import LLMResponse, ToolCallInfo


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


def _assistant_config(max_iterations=5) -> AgentConfig:
    return AgentConfig(
        agent_type=AgentType.ASSISTANT,
        system_prompt="a",
        max_iterations=max_iterations,
        text_as_user_input=True,
    )


def _capture_tool(captured: dict) -> ToolDefinition:
    def handler(**kw):
        captured["snapshot"] = get_llm_messages_snapshot()
        return json.dumps({"ok": True})

    return ToolDefinition(
        name="capture",
        schema={"type": "object", "properties": {}},
        handler=handler,
    )


def _delegation_tool(kind: str, session_id: str, callback) -> ToolDefinition:
    from src.business.agents.tools.assistant_tools import (
        DELEGATE_TO_SPECIALIST_SCHEMA,
        DELEGATE_TO_SUBAGENT_SCHEMA,
        create_delegate_to_specialist_handler,
        create_delegate_to_subagent_handler,
    )

    if kind == "subagent":
        return ToolDefinition(
            name="delegate_to_subagent",
            schema=DELEGATE_TO_SUBAGENT_SCHEMA,
            handler=create_delegate_to_subagent_handler(
                session_id,
                dispatch_callback=callback,
            ),
        )
    return ToolDefinition(
        name="delegate_to_specialist",
        schema=DELEGATE_TO_SPECIALIST_SCHEMA,
        handler=create_delegate_to_specialist_handler(
            session_id,
            dispatch_callback=callback,
        ),
    )


def _tool_result_contents(session_id: str) -> list[str]:
    from src.data.repositories import MessageRepository

    return [
        message.content
        for message in MessageRepository().get_context(session_id)
        if message.role == "tool"
    ]


@pytest.fixture(autouse=True)
def _clean_run_context():
    run_context.reset_for_tests()
    yield
    run_context.reset_for_tests()


class TestSnapshotOnLlmPath:
    def test_tool_batch_sees_exact_llm_messages(self, mock_config, in_memory_db):
        sid = _new_session(AgentType.ASSISTANT)
        captured: dict = {}
        sent: dict = {}
        llm = MagicMock()

        def chat(messages, tools, **kw):
            if "first" not in sent:
                sent["first"] = messages
                return LLMResponse(
                    content=None,
                    tool_calls=[ToolCallInfo(id="c1", name="capture", args={})],
                )
            return LLMResponse(content="done", tool_calls=[])

        llm.chat_with_tools.side_effect = chat
        loop = AgentLoop(_assistant_config(), llm, mock_config)
        loop.run(sid, user_input="go", tools=[_capture_tool(captured)])

        snapshot = captured["snapshot"]
        assert snapshot is not None
        assert [(message.role, message.content) for message in snapshot] == [
            (str(message.get("role") or "?"), message.get("content")) for message in sent["first"]
        ]

    def test_snapshot_cleared_after_run(self, mock_config, in_memory_db):
        sid = _new_session(AgentType.ASSISTANT)
        captured: dict = {}
        llm = MagicMock()
        llm.chat_with_tools.side_effect = [
            LLMResponse(
                content=None,
                tool_calls=[ToolCallInfo(id="c1", name="capture", args={})],
            ),
            LLMResponse(content="done", tool_calls=[]),
        ]
        loop = AgentLoop(_assistant_config(), llm, mock_config)
        loop.run(sid, user_input="go", tools=[_capture_tool(captured)])

        assert captured["snapshot"] is not None
        assert get_llm_messages_snapshot() is None


class TestSnapshotAbsentOnNonLlmPaths:
    def test_pending_recovery_path_has_no_snapshot(self, mock_config, in_memory_db):
        sid = _new_session(AgentType.ASSISTANT)
        captured: dict = {}
        llm = MagicMock()
        llm.chat_with_tools.return_value = LLMResponse(content="done", tool_calls=[])
        loop = AgentLoop(_assistant_config(), llm, mock_config)

        # 模拟崩溃遗留:assistant(tool_calls) 已存但无 tool result
        ctx = loop._get_context_manager(sid)
        ctx.save_message(role="user", content="go")
        ctx.save_assistant_message(
            content="",
            tool_calls=_serialize_tool_calls([ToolCallInfo(id="c9", name="capture", args={})]),
        )
        assert ctx.get_pending_tool_calls()

        loop.run(sid, tools=[_capture_tool(captured)])

        assert "snapshot" in captured
        assert captured["snapshot"] is None

    def test_initial_tool_calls_path_has_no_snapshot(self, mock_config, in_memory_db):
        sid = _new_session(AgentType.ASSISTANT)
        captured: dict = {}
        llm = MagicMock()
        llm.chat_with_tools.return_value = LLMResponse(content="done", tool_calls=[])
        loop = AgentLoop(_assistant_config(), llm, mock_config)

        loop.run(
            sid,
            user_input="go",
            tools=[_capture_tool(captured)],
            initial_tool_calls=[ToolCallInfo(id="c2", name="capture", args={})],
        )

        assert "snapshot" in captured
        assert captured["snapshot"] is None

    def test_pending_delegation_retains_indexes_and_fails_closed(
        self,
        mock_config,
        in_memory_db,
    ):
        """崩溃恢复保留真实参数，但没有本轮 LLM 快照时禁止委派。"""
        sid = _new_session(AgentType.ASSISTANT)
        callback = MagicMock()
        llm = MagicMock()
        llm.chat_with_tools.return_value = LLMResponse(content="done", tool_calls=[])
        loop = AgentLoop(_assistant_config(), llm, mock_config)
        ctx = loop._get_context_manager(sid)
        ctx.save_message(role="user", content="go")
        ctx.save_assistant_message(
            content="",
            tool_calls=_serialize_tool_calls(
                [
                    ToolCallInfo(
                        id="delegate-pending",
                        name="delegate_to_subagent",
                        args={
                            "task_description": "执行历史方案",
                            "context_message_indexes": [1],
                        },
                    )
                ]
            ),
        )

        loop.run(sid, tools=[_delegation_tool("subagent", sid, callback)])

        callback.assert_not_called()
        persisted = "\n".join(_tool_result_contents(sid))
        assert '"success": false' in persisted
        assert "execution_context" in persisted

    def test_initial_specialist_delegation_retains_indexes_and_fails_closed(
        self,
        mock_config,
        in_memory_db,
    ):
        """程序注入的真实专员委派参数同样不能绕过快照边界。"""
        sid = _new_session(AgentType.ASSISTANT)
        callback = MagicMock()
        llm = MagicMock()
        llm.chat_with_tools.return_value = LLMResponse(content="done", tool_calls=[])
        loop = AgentLoop(_assistant_config(), llm, mock_config)

        loop.run(
            sid,
            user_input="go",
            tools=[_delegation_tool("specialist", sid, callback)],
            initial_tool_calls=[
                ToolCallInfo(
                    id="delegate-initial",
                    name="delegate_to_specialist",
                    args={
                        "specialist_name": "文档专员",
                        "task": "执行历史方案",
                        "context_message_indexes": [1],
                    },
                )
            ],
        )

        callback.assert_not_called()
        persisted = "\n".join(_tool_result_contents(sid))
        assert '"success": false' in persisted
        assert "execution_context" in persisted
