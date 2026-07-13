import pytest

from src.business.agents.tools.dynamic_tool_manager import DynamicToolManager
from src.business.agents.tools.external_coding_tools import create_external_coding_tools
from src.business.services.skill_composition.builtin_compositions import (
    EXTERNAL_CODING_COMPOSITION_ID,
    EXTERNAL_CODING_TOOL_IDS,
)
from src.business.services.skill_composition_service import SkillCompositionService
from src.business.services.skill_composition.types import SkillCompositionError


def test_external_coding_is_exposed_as_a_builtin_range_composition() -> None:
    compositions = SkillCompositionService().list_compositions()

    external_coding = next(
        item for item in compositions if item.composition_id == "comp_builtin_external_coding"
    )

    assert external_coding.composition_name == "外部 Coding"
    assert external_coding.mode == "range"
    assert external_coding.status == "published"
    assert external_coding.is_builtin is True
    assert external_coding.is_read_only is True
    assert len(external_coding.members) == 11

    summary = next(
        item
        for item in SkillCompositionService().get_assistant_published_summaries()
        if item["composition_id"] == EXTERNAL_CODING_COMPOSITION_ID
    )
    assert summary["is_builtin"] is True
    assert summary["member_tool_ids"] == [member.tool_id for member in external_coding.members]


def test_builtin_external_coding_composition_is_read_only_and_not_trialable() -> None:
    service = SkillCompositionService()

    with pytest.raises(SkillCompositionError, match="系统内置技能组合不可修改"):
        service.publish_composition(EXTERNAL_CODING_COMPOSITION_ID)

    with pytest.raises(SkillCompositionError, match="仅供正式任务"):
        service.start_trial_session(EXTERNAL_CODING_COMPOSITION_ID)

    with pytest.raises(SkillCompositionError, match="名称已存在"):
        service.create_composition(
            composition_name=" 外部 coding ",
            description="duplicate",
            applicability="duplicate",
            mode="range",
            members=[],
        )


def test_assigned_external_coding_range_composition_activates_its_builtin_members() -> None:
    member_tools = create_external_coding_tools(
        session_id="session-parent",
        bound_task_id="task-coding",
    )
    manager = DynamicToolManager(
        allowed_tool_ids=set(),
        allowed_composition_ids={EXTERNAL_CODING_COMPOSITION_ID},
        builtin_tool_definitions={tool.name: tool for tool in member_tools},
    )

    detail = manager.get_tool_detail("技能组合:外部 Coding")
    assert "技能组合已激活" in detail

    composition_tool = next(
        tool for tool in manager.get_activated_tools() if tool.name.startswith("comp_")
    )
    composition_tool.handler(task="实现功能", context="在正式任务中执行")

    activated_names = {tool.name for tool in manager.get_activated_tools()}
    assert EXTERNAL_CODING_TOOL_IDS.issubset(activated_names)
