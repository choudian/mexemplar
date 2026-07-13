from types import SimpleNamespace

import pytest

from src.business.agents.config import AgentType
from src.business.agents.tools.dynamic_tool_manager import DynamicToolManager
from src.business.orchestration.agent.tool_registry import ToolRegistry
from src.business.services.skill_composition.builtin_compositions import (
    EXTERNAL_CODING_COMPOSITION_ID,
    EXTERNAL_CODING_TOOL_IDS,
)


class _DynamicManagerCache:
    def get_or_create_dynamic_manager(self, session_id, allowed_ids, allowed_composition_ids=None):
        return DynamicToolManager(
            allowed_tool_ids=allowed_ids,
            allowed_composition_ids=allowed_composition_ids,
        )


def _registry() -> ToolRegistry:
    return ToolRegistry(
        session_store=SimpleNamespace(get_session=lambda _session_id: None),
        dynamic_manager_cache=_DynamicManagerCache(),
        delegation_orchestrator=SimpleNamespace(
            delegate_to_subagent=lambda **_: {},
            continue_subagent=lambda **_: {},
            inspect_subagent=lambda **_: {},
            delegate_to_specialist=lambda **_: {},
            run_sync_ephemeral_subagent=lambda **_: {},
        ),
        resolve_recording_mode=lambda _workflow_id: "browser",
        redispatch_answered_task=lambda _task_id: False,
    )


@pytest.mark.parametrize(
    ("agent_type", "specialist_id"),
    [
        (AgentType.EPHEMERAL_SUBAGENT, None),
        (AgentType.SPECIALIST, "specialist_without_composition"),
    ],
)
def test_unassigned_delegated_executors_do_not_receive_external_coding_members(
    agent_type: AgentType,
    specialist_id: str | None,
) -> None:
    tools = _registry().build_delegated_executor_tools(
        None,
        agent_type=agent_type,
        executor_id="executor_1",
        specialist_id=specialist_id,
        current_task_id="task_1",
        parent_session_id="assistant_1",
        allowed_composition_ids=set(),
    )()

    assert EXTERNAL_CODING_TOOL_IDS.isdisjoint(tool.name for tool in tools)


def test_assigned_task_bound_specialist_activates_external_coding_through_the_composition() -> None:
    factory = _registry().build_delegated_executor_tools(
        None,
        agent_type=AgentType.SPECIALIST,
        executor_id="executor_1",
        specialist_id="coding_specialist",
        current_task_id="task_1",
        parent_session_id="assistant_1",
        allowed_composition_ids={EXTERNAL_CODING_COMPOSITION_ID},
    )

    initial_tools = factory()
    assert EXTERNAL_CODING_TOOL_IDS.isdisjoint(tool.name for tool in initial_tools)

    get_detail = next(tool for tool in initial_tools if tool.name == "get_tool_detail")
    detail = get_detail.handler(tool_name="技能组合:外部 Coding")
    assert "技能组合已激活" in detail

    composition_tool = next(tool for tool in factory() if tool.name.startswith("comp_"))
    composition_tool.handler(task="实现功能", context="正式编码任务")

    assert EXTERNAL_CODING_TOOL_IDS.issubset(tool.name for tool in factory())


def test_ephemeral_executor_cannot_reveal_builtin_composition_even_if_id_is_injected() -> None:
    tools = _registry().build_delegated_executor_tools(
        None,
        agent_type=AgentType.EPHEMERAL_SUBAGENT,
        executor_id="ephemeral_1",
        current_task_id="task_1",
        parent_session_id="assistant_1",
        allowed_composition_ids={EXTERNAL_CODING_COMPOSITION_ID},
    )()

    get_detail = next(tool for tool in tools if tool.name == "get_tool_detail")
    assert "不存在或当前不可用" in get_detail.handler(tool_name="技能组合:外部 Coding")
    assert EXTERNAL_CODING_TOOL_IDS.isdisjoint(tool.name for tool in tools)


def test_guessed_composition_id_without_fixed_specialist_identity_cannot_reveal_members() -> None:
    tools = _registry().build_delegated_executor_tools(
        None,
        agent_type=AgentType.SPECIALIST,
        executor_id="specialist_session_without_identity",
        specialist_id=None,
        current_task_id="task_1",
        parent_session_id="assistant_1",
        role_kind="executor",
        allowed_composition_ids={EXTERNAL_CODING_COMPOSITION_ID},
    )()

    get_detail = next(tool for tool in tools if tool.name == "get_tool_detail")
    assert "不存在或当前不可用" in get_detail.handler(tool_name="技能组合:外部 Coding")
    assert EXTERNAL_CODING_TOOL_IDS.isdisjoint(tool.name for tool in tools)
