from __future__ import annotations

import inspect

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from src.business.agents.tools import skill_methodology_tools
from src.data.models_sqlite import Base, BrainSkill
from src.data.repos.skill_repository import SKILL_ORIGINS, SkillRepository
from src.desktop_api.routers import skills_methodology


def _session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_skill_origin_repository_accepts_only_closed_enum_values() -> None:
    assert SKILL_ORIGINS == {
        "system_bootstrap",
        "user_edit",
        "assistant_tool_call",
        "specialist_tool_call",
        "external_import",
    }
    session = _session()
    repo = SkillRepository(session=session)

    for origin in sorted(SKILL_ORIGINS):
        repo.create_skill(
            skill_id=f"skill-{origin}",
            name=f"方法论 {origin}",
            description="测试",
            trigger_conditions=["触发"],
            required_tools=[],
            body_markdown="正文",
            origin=origin,
        )

    with pytest.raises(ValueError, match="invalid skill origin"):
        repo.create_skill(
            skill_id="skill-invalid",
            name="非法来源",
            description="测试",
            trigger_conditions=["触发"],
            required_tools=[],
            body_markdown="正文",
            origin="invalid_origin",
        )


def test_database_rejects_unknown_origin_even_on_direct_insert() -> None:
    session = _session()
    session.add(
        BrainSkill(
            skill_id="skill-invalid",
            name="非法来源",
            description="测试",
            trigger_conditions='["触发"]',
            required_tools="[]",
            body_markdown="正文",
            status="active",
            origin="invalid_origin",
            chain_root_id="skill-invalid",
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_external_import_is_schema_anchor_not_desktop_api_surface() -> None:
    router_source = inspect.getsource(skills_methodology)
    tool_source = inspect.getsource(skill_methodology_tools)

    assert "external_import" not in router_source
    assert "external_import" not in tool_source
    properties = skill_methodology_tools.CREATE_SKILL_METHODOLOGY_SCHEMA["function"]["parameters"][
        "properties"
    ]
    assert "origin" not in properties
