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


def _source(session, segment_id: str) -> dict[str, str]:
    session.add(
        BrainMemoryEntry(
            entry_id=f"entry-{segment_id}",
            zone="archive",
            content="素材",
            status="active",
            origin="distillation",
            reason="test",
            source_segment_id=segment_id,
            relevance_score=1.0,
        )
    )
    session.commit()
    return {"segment_id": segment_id, "source_zone": "archive"}


def _create(service: SkillService, name: str, source: dict[str, str]):
    return service.create(
        name=name,
        description="测试方法论",
        trigger_conditions=["需要测试时"],
        required_tools=[],
        body_markdown="正文",
        source_segments=[source],
        origin="assistant_tool_call",
        caller_type="assistant",
        caller_id="_assistant",
        change_reason="test",
    )


def test_create_mode_rejects_same_name_active_skill() -> None:
    session = _session()
    service = SkillService(session=session)
    _create(service, "唯一名称", _source(session, "seg-1"))

    with pytest.raises(ValueError, match="skill_name_collision"):
        _create(service, "唯一名称", _source(session, "seg-2"))


def test_supersede_allows_same_name_for_current_chain() -> None:
    session = _session()
    service = SkillService(session=session)
    created = _create(service, "可接力名称", _source(session, "seg-1"))

    result = service.supersede(
        target_skill_id=created["skill_id"],
        name="可接力名称",
        description="v2",
        trigger_conditions=["需要测试时"],
        required_tools=[],
        body_markdown="v2 正文",
        source_segments=[_source(session, "seg-2")],
        origin="assistant_tool_call",
        caller_type="assistant",
        caller_id="_assistant",
        change_reason="supersede",
    )

    assert result["version"] == 2


def test_user_edit_rename_collision_is_rejected() -> None:
    session = _session()
    service = SkillService(session=session)
    first = _create(service, "已占用名称", _source(session, "seg-1"))
    second = _create(service, "待改名", _source(session, "seg-2"))

    with pytest.raises(ValueError, match=f"skill_name_collision:{first['skill_id']}"):
        service.user_edit_supersede(
            second["skill_id"],
            {
                "name": "已占用名称",
                "description": "撞名",
                "trigger_conditions": ["需要测试时"],
                "required_tools": [],
                "body_markdown": "正文",
                "change_reason": "撞名测试",
            },
        )
