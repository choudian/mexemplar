from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.business.brain.skill_service import SkillService
from src.data.models_sqlite import Base, BrainMemoryEntry


def _session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _source(session) -> list[dict[str, str]]:
    session.add(
        BrainMemoryEntry(
            entry_id="entry-seg",
            zone="archive",
            content="素材",
            status="active",
            origin="distillation",
            reason="test",
            source_segment_id="seg",
            relevance_score=1.0,
        )
    )
    session.commit()
    return [{"segment_id": "seg", "source_zone": "archive"}]


@pytest.mark.parametrize("triggers", [[], ["", "   "]])
def test_trigger_conditions_must_have_at_least_one_non_blank_item(triggers: list[str]) -> None:
    session = _session()

    with pytest.raises(ValueError, match="trigger_conditions"):
        SkillService(session=session).create(
            name="触发条件测试",
            description="测试",
            trigger_conditions=triggers,
            required_tools=[],
            body_markdown="正文",
            source_segments=_source(session),
            origin="assistant_tool_call",
            caller_type="assistant",
            caller_id="_assistant",
            change_reason="test",
        )


def test_required_tools_can_be_empty() -> None:
    session = _session()

    result = SkillService(session=session).create(
        name="无工具要求方法论",
        description="测试",
        trigger_conditions=["需要测试时"],
        required_tools=[],
        body_markdown="正文",
        source_segments=_source(session),
        origin="assistant_tool_call",
        caller_type="assistant",
        caller_id="_assistant",
        change_reason="test",
    )

    assert result["success"] is True


def test_supersede_rejects_empty_trigger_conditions() -> None:
    session = _session()
    source_segments = _source(session)
    service = SkillService(session=session)
    created = service.create(
        name="接力触发条件测试",
        description="测试",
        trigger_conditions=["需要测试时"],
        required_tools=[],
        body_markdown="正文",
        source_segments=source_segments,
        origin="assistant_tool_call",
        caller_type="assistant",
        caller_id="_assistant",
        change_reason="create",
    )

    with pytest.raises(ValueError, match="trigger_conditions"):
        service.supersede(
            target_skill_id=created["skill_id"],
            name="接力触发条件测试",
            description="测试",
            trigger_conditions=[],
            required_tools=[],
            body_markdown="更新正文",
            source_segments=source_segments,
            origin="assistant_tool_call",
            caller_type="assistant",
            caller_id="_assistant",
            change_reason="supersede",
        )
