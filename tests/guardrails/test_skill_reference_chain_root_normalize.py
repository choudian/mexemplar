from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.business.brain.skill_reference_counter import SkillReferenceCounterService
from src.data.models_sqlite import Base
from src.data.repos.skill_repository import SkillRepository


def _session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _skill(
    repo: SkillRepository, skill_id: str, *, chain_root_id: str | None = None, version: int = 1
):
    return repo.create_skill(
        skill_id=skill_id,
        name=f"方法论 {skill_id}",
        description="测试",
        trigger_conditions=["触发"],
        required_tools=[],
        body_markdown="正文",
        origin="assistant_tool_call",
        chain_root_id=chain_root_id,
        version=version,
    )


def test_superseded_skill_id_normalizes_to_current_active_once_per_reply() -> None:
    session = _session()
    repo = SkillRepository(session=session)
    root = _skill(repo, "root")
    repo.mark_superseded(root.skill_id, "v2")
    active = _skill(repo, "v2", chain_root_id=root.chain_root_id, version=2)

    updated = SkillReferenceCounterService(repo=repo).process_reply_metadata(["root", "root", "v2"])

    session.refresh(active)
    assert updated == 1
    assert active.referenced_count == 1


def test_soft_deleted_chain_is_silently_skipped() -> None:
    session = _session()
    repo = SkillRepository(session=session)
    skill = _skill(repo, "soft")
    repo.mark_soft_deleted(skill.skill_id)

    updated = SkillReferenceCounterService(repo=repo).process_reply_metadata(["soft"])

    assert updated == 0
    assert repo.get_skill("soft").referenced_count == 0


def test_bad_metadata_shape_is_silently_skipped() -> None:
    session = _session()
    repo = SkillRepository(session=session)
    _skill(repo, "skill-1")

    assert SkillReferenceCounterService(repo=repo).process_reply_metadata("skill-1") == 0
    assert SkillReferenceCounterService(repo=repo).process_reply_metadata([None, "", 42]) == 0
