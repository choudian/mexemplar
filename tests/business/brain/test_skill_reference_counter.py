from __future__ import annotations

import logging

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
    repo: SkillRepository,
    *,
    skill_id: str,
    chain_root_id: str | None = None,
    status: str = "active",
):
    skill = repo.create_skill(
        skill_id=skill_id,
        chain_root_id=chain_root_id,
        name=f"方法论 {skill_id}",
        description="测试方法论",
        trigger_conditions=["需要处理同类任务时"],
        required_tools=[],
        body_markdown="正文",
        origin="assistant_tool_call",
    )
    skill.status = status
    repo.session.commit()
    return skill


def test_reference_counter_normalizes_to_active_chain_root_once() -> None:
    session = _session()
    repo = SkillRepository(session=session)
    old = _skill(repo, skill_id="old")
    repo.mark_superseded("old", "new", commit=False)
    new = _skill(repo, skill_id="new", chain_root_id=old.chain_root_id)

    updated = SkillReferenceCounterService(repo=repo).process_reply_metadata(
        ["old", "new", old.chain_root_id]
    )

    session.refresh(new)
    assert updated == 1
    assert new.referenced_count == 1


def test_reference_counter_skips_bad_metadata_and_missing_or_inactive_skills() -> None:
    session = _session()
    repo = SkillRepository(session=session)
    inactive = _skill(repo, skill_id="inactive", status="soft_deleted")

    service = SkillReferenceCounterService(repo=repo)

    assert service.process_reply_metadata("inactive") == 0
    assert service.process_reply_metadata([None, "", 42, inactive.skill_id, "missing"]) == 0


def test_loaded_count_failure_is_logged_and_does_not_escape(monkeypatch, caplog) -> None:
    repo = SkillRepository(session=_session())
    monkeypatch.setattr(
        repo,
        "increment_loaded_count",
        lambda _skill_id: (_ for _ in ()).throw(RuntimeError("db unavailable")),
    )

    with caplog.at_level(logging.WARNING):
        assert SkillReferenceCounterService(repo=repo).increment_loaded_count("skill-1") is False

    assert "跳过方法论加载计数更新" in caplog.text
