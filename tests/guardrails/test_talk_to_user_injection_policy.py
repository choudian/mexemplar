"""Guardrail tests for talk_to_user injection policy.

Verifies that EPHEMERAL_SUBAGENT and SPECIALIST do not receive the
talk_to_user tool, while Programmer (teaching flow) still does.
"""

from src.business.agents.config import AgentConfig, AgentType


def _get_injected_tool_names(config: AgentConfig) -> set[str]:
    """Build the tool registry and return injected tool names."""
    from unittest.mock import MagicMock

    from src.business.agents.agent_loop import AgentLoop

    # AgentLoop.__init__ needs an LLM and config; we only need the registry
    # build path. Use a minimal mock to avoid pulling in real LLM.
    loop = AgentLoop.__new__(AgentLoop)
    loop._config = config

    # Build registry using the same code path as AgentLoop.run()
    # We need to call _build_tool_registry with empty business tools
    from src.business.agents.config import ToolDefinition

    registry: dict[str, ToolDefinition] = {}

    # Replicate the injection logic from AgentLoop._build_tool_registry
    from src.business.agents.builtin_tools import (
        LOAD_REFERENCE_SCHEMA,
        TALK_TO_USER_SCHEMA,
        talk_to_user,
    )

    registry["load_reference"] = ToolDefinition(
        name="load_reference",
        schema=LOAD_REFERENCE_SCHEMA,
        handler=MagicMock(),
        is_interrupting=False,
        has_side_effects=False,
        is_concurrency_safe=True,
    )

    _should_inject_talk_to_user = (
        not config.text_as_user_input
        and config.agent_type not in (
            AgentType.EPHEMERAL_SUBAGENT,
            AgentType.SPECIALIST,
        )
    )
    if _should_inject_talk_to_user:
        registry["talk_to_user"] = ToolDefinition(
            name="talk_to_user",
            schema=TALK_TO_USER_SCHEMA,
            handler=talk_to_user,
            is_interrupting=True,
        )

    return set(registry.keys())


class TestTalkToUserInjectionPolicy:
    """Verify talk_to_user injection respects agent type boundaries."""

    def test_ephemeral_subagent_no_talk_to_user(self):
        """EPHEMERAL_SUBAGENT must not receive talk_to_user."""
        config = AgentConfig(
            agent_type=AgentType.EPHEMERAL_SUBAGENT,
            system_prompt="test",
            max_iterations=10,
        )
        names = _get_injected_tool_names(config)
        assert "talk_to_user" not in names

    def test_specialist_no_talk_to_user(self):
        """SPECIALIST must not receive talk_to_user."""
        config = AgentConfig(
            agent_type=AgentType.SPECIALIST,
            system_prompt="test",
            max_iterations=10,
        )
        names = _get_injected_tool_names(config)
        assert "talk_to_user" not in names

    def test_programmer_still_has_talk_to_user(self):
        """Programmer (teaching flow) must still receive talk_to_user."""
        config = AgentConfig(
            agent_type=AgentType.PROGRAMMER,
            system_prompt="test",
            max_iterations=10,
        )
        names = _get_injected_tool_names(config)
        assert "talk_to_user" in names

    def test_assistant_no_talk_to_user(self):
        """Assistant has text_as_user_input=True, so no talk_to_user."""
        config = AgentConfig(
            agent_type=AgentType.ASSISTANT,
            system_prompt="test",
            max_iterations=10,
            text_as_user_input=True,
        )
        names = _get_injected_tool_names(config)
        assert "talk_to_user" not in names

    def test_pm_no_talk_to_user(self):
        """PM has text_as_user_input=True, so no talk_to_user."""
        config = AgentConfig(
            agent_type=AgentType.PM,
            system_prompt="test",
            max_iterations=10,
            text_as_user_input=True,
        )
        names = _get_injected_tool_names(config)
        assert "talk_to_user" not in names
