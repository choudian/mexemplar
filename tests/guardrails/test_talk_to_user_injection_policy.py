"""Guardrail tests for the unified user-facing output policy.

talk_to_user has been removed entirely: the assistant replies via the explicit
reply_to_user tool, PM/Trial converse via text_as_user_input=True plain text,
and subagents/specialists escalate via ask_parent. These tests exercise the
REAL AgentLoop tool-schema assembly path (not a copy of the logic) by running
the loop with an LLM stub that records the schemas it receives.

Legacy display compatibility for historical talk_to_user tool_calls is covered
separately (format_messages_for_display reverse lookup).
"""

import uuid

import pytest

from src.business.agents.config import (
    ASSISTANT_CONFIG,
    PM_CONFIG,
    AgentConfig,
    AgentType,
)
from src.business.ai.llm_client import LLMResponse


class _SchemaRecordingLLM:
    """Returns a plain-text reply and records the tool schemas offered to it."""

    def __init__(self):
        self.seen_tool_names: list[set[str]] = []

    def chat_with_tools(self, messages, tools, **kwargs) -> LLMResponse:
        names = set()
        for schema in tools or []:
            function = schema.get("function") if isinstance(schema, dict) else None
            if isinstance(function, dict) and function.get("name"):
                names.add(function["name"])
        self.seen_tool_names.append(names)
        return LLMResponse(content="完成", tool_calls=[])


def _run_loop_and_capture_tools(config: AgentConfig, mock_config) -> set[str]:
    from src.business.agents.agent_loop import AgentLoop

    llm = _SchemaRecordingLLM()
    loop = AgentLoop(config, llm, mock_config)
    loop.run(
        session_id=f"guard_{uuid.uuid4().hex[:12]}",
        user_input="测试输入",
        tools=[],
    )
    assert llm.seen_tool_names, "loop 未到达 LLM 调用，测试路径失效"
    merged: set[str] = set()
    for names in llm.seen_tool_names:
        merged |= names
    return merged


@pytest.mark.usefixtures("in_memory_db")
class TestUserFacingOutputPolicy:
    """talk_to_user 不得再进入任何 Agent 的工具目录（真实组装路径验证）。"""

    @pytest.mark.parametrize(
        "agent_type,text_as_user_input",
        [
            (AgentType.ASSISTANT, False),
            (AgentType.PM, True),
            (AgentType.PROGRAMMER, False),
            (AgentType.TRIAL, True),
            (AgentType.EPHEMERAL_SUBAGENT, False),
            (AgentType.SPECIALIST, False),
        ],
    )
    def test_no_agent_receives_talk_to_user(self, mock_config, agent_type, text_as_user_input):
        config = AgentConfig(
            agent_type=agent_type,
            system_prompt="test",
            max_iterations=3,
            text_as_user_input=text_as_user_input,
        )
        names = _run_loop_and_capture_tools(config, mock_config)
        assert "talk_to_user" not in names
        # load_reference 仍是唯一的自动注入工具
        assert "load_reference" in names

    def test_builtin_tools_module_has_no_talk_to_user(self):
        """schema/handler 已从 builtin_tools 移除，防止回潮。"""
        import src.business.agents.builtin_tools as builtin_tools

        assert not hasattr(builtin_tools, "TALK_TO_USER_SCHEMA")
        assert not hasattr(builtin_tools, "talk_to_user")


@pytest.mark.usefixtures("in_memory_db")
class TestAssistantReplyChannelPolicy:
    """主助理回复通道统一为 reply_to_user（P1）。"""

    def test_assistant_config_text_as_user_input_is_false(self):
        assert ASSISTANT_CONFIG.text_as_user_input is False

    def test_pm_keeps_plain_text_dialogue(self):
        """PM 仍是纯文本对话型 Agent，行为不受 P1 影响。"""
        assert PM_CONFIG.text_as_user_input is True

    def test_assistant_bare_text_completes_and_persists(self, mock_config):
        """主助理纯文本输出：消息落库可展示，但按 COMPLETED 结束，不转 NEEDS_USER_INPUT。"""
        from src.business.agents.agent_loop import AgentLoop
        from src.business.agents.config import ResultType
        from src.data.repos.message_repository import MessageRepository
        from tests.conftest import MockLLMClient

        session_id = f"guard_{uuid.uuid4().hex[:12]}"
        config = AgentConfig(
            agent_type=AgentType.ASSISTANT,
            system_prompt="test",
            max_iterations=3,
            text_as_user_input=False,
        )
        loop = AgentLoop(
            config, MockLLMClient([LLMResponse(content="纯文本回复", tool_calls=[])]), mock_config
        )
        result = loop.run(session_id=session_id, user_input="你好", tools=[])

        assert result.result_type == ResultType.COMPLETED
        assert result.question is None
        messages = MessageRepository().get_all(session_id)
        assistant_contents = [m.content for m in messages if m.role == "assistant"]
        assert any("纯文本回复" in (c or "") for c in assistant_contents)

    def test_pm_bare_text_still_needs_user_input(self, mock_config):
        """对照组：text_as_user_input=True 的 PM 纯文本仍转 NEEDS_USER_INPUT。"""
        from src.business.agents.agent_loop import AgentLoop
        from src.business.agents.config import ResultType
        from tests.conftest import MockLLMClient

        config = AgentConfig(
            agent_type=AgentType.PM,
            system_prompt="test",
            max_iterations=3,
            text_as_user_input=True,
        )
        loop = AgentLoop(
            config, MockLLMClient([LLMResponse(content="请确认需求", tool_calls=[])]), mock_config
        )
        result = loop.run(
            session_id=f"guard_{uuid.uuid4().hex[:12]}",
            user_input="开始",
            tools=[],
        )
        assert result.result_type == ResultType.NEEDS_USER_INPUT
        assert result.question == "请确认需求"


@pytest.mark.usefixtures("in_memory_db")
class TestLegacyTalkToUserDisplayCompat:
    """历史会话中已存的 talk_to_user tool_calls 仍可反查为展示消息。"""

    def test_format_messages_extracts_legacy_talk_to_user(self):
        import json
        from types import SimpleNamespace

        from src.business.orchestration.agent.agent_session_store import (
            AgentSessionStore,
        )

        store = AgentSessionStore.__new__(AgentSessionStore)
        import logging

        store._logger = logging.getLogger("test")

        legacy_messages = [
            SimpleNamespace(role="user", content="旧会话用户消息", tool_calls=None),
            SimpleNamespace(
                role="assistant",
                content="",
                tool_calls=json.dumps(
                    [
                        {
                            "id": "tc-legacy",
                            "name": "talk_to_user",
                            "args": {"message": "这是历史确认问题"},
                        }
                    ]
                ),
            ),
        ]
        result = store.format_messages_for_display(legacy_messages, "legacy-session")
        assert {"role": "assistant", "content": "这是历史确认问题"} in result
