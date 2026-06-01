from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from src.data.models_sqlite import Base, BrainSkill
from src.data.repos.skill_repository import SkillRepository


def _session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _repo():
    return SkillRepository(session=_session())


def test_create_get_and_list_active_skill() -> None:
    repo = _repo()

    skill = repo.create_skill(
        skill_id="skill-1",
        name="测试方法论",
        description="测试描述",
        trigger_conditions=["需要测试时"],
        required_tools=["tool-a"],
        body_markdown="正文",
        origin="assistant_tool_call",
    )

    assert repo.get_skill("skill-1").skill_id == skill.skill_id
    assert repo.get_active("skill-1").name == "测试方法论"
    assert [row.skill_id for row in repo.list_active()] == ["skill-1"]


def test_chain_root_queries_resolve_supersede_chain() -> None:
    repo = _repo()
    root = repo.create_skill(
        skill_id="skill-root",
        name="链根方法论",
        description="v1",
        trigger_conditions=["v1"],
        required_tools=[],
        body_markdown="v1",
        origin="assistant_tool_call",
    )
    repo.mark_superseded(root.skill_id, "skill-v2")
    v2 = repo.create_skill(
        skill_id="skill-v2",
        name="链根方法论",
        description="v2",
        trigger_conditions=["v2"],
        required_tools=[],
        body_markdown="v2",
        origin="user_edit",
        parent_skill_id=root.skill_id,
        chain_root_id=root.chain_root_id,
        version=2,
    )

    assert repo.resolve_chain_root(v2.skill_id) == root.skill_id
    assert repo.get_current_active_for_chain(root.skill_id).skill_id == v2.skill_id
    assert [row.skill_id for row in repo.get_chain(v2.skill_id)] == ["skill-root", "skill-v2"]


def test_same_name_active_check_rejects_duplicate_but_allows_excluded_self() -> None:
    repo = _repo()
    skill = repo.create_skill(
        skill_id="skill-1",
        name="唯一名称",
        description="测试",
        trigger_conditions=["触发"],
        required_tools=[],
        body_markdown="正文",
        origin="assistant_tool_call",
    )

    with pytest.raises(ValueError, match="skill_name_collision:skill-1"):
        repo.assert_no_same_name_active("唯一名称")

    repo.assert_no_same_name_active("唯一名称", excluding_skill_id=skill.skill_id)


def test_soft_delete_keeps_row_and_repository_exposes_no_physical_delete_method() -> None:
    repo = _repo()
    skill = repo.create_skill(
        skill_id="skill-1",
        name="待删除方法论",
        description="测试",
        trigger_conditions=["触发"],
        required_tools=[],
        body_markdown="正文",
        origin="assistant_tool_call",
    )

    assert not hasattr(repo, "delete")
    assert not hasattr(repo, "physical_delete")
    assert repo.mark_soft_deleted(skill.skill_id) is True

    retained = repo.session.get(BrainSkill, skill.skill_id)
    assert retained is not None
    assert retained.status == "soft_deleted"
    assert repo.get_active(skill.skill_id) is None


def test_skill_status_and_superseded_by_must_change_together() -> None:
    repo = _repo()
    skill = repo.create_skill(
        skill_id="skill-1",
        name="约束测试",
        description="测试",
        trigger_conditions=["触发"],
        required_tools=[],
        body_markdown="正文",
        origin="assistant_tool_call",
    )
    skill.superseded_by = "skill-v2"

    with pytest.raises(IntegrityError):
        repo.session.commit()
