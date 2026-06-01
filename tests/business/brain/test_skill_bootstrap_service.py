from __future__ import annotations

import logging
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.business.brain.skill_bootstrap_service import SkillBootstrapService
from src.data.models_sqlite import Base, BrainSkill, BrainSkillEquipment


def _session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_bootstrap_equips_to_assistant_only(tmp_path):
    session = _session()
    seed_path = tmp_path / "missing-seed.md"

    result = SkillBootstrapService(
        session=session, seed_file_path=str(seed_path)
    ).bootstrap_missing_skill(
        session=session,
        use_unified_config=False,
    )

    assert result["bootstrap_active_skill_id"] == SkillBootstrapService.BOOTSTRAP_HOW_TO_SKILL_ID
    skill = session.get(BrainSkill, SkillBootstrapService.BOOTSTRAP_HOW_TO_SKILL_ID)
    assert skill is not None
    assert skill.origin == "system_bootstrap"
    assert skill.status == "active"

    equipment = session.query(BrainSkillEquipment).all()
    assert len(equipment) == 1
    assert equipment[0].equipped_entity_type == "assistant"
    assert equipment[0].equipped_entity_id == "_assistant"
    assert equipment[0].skill_id == SkillBootstrapService.BOOTSTRAP_HOW_TO_SKILL_ID
    assert equipment[0].status == "active"


def test_bootstrap_failure_is_logged(tmp_path, monkeypatch, caplog):
    from src.data.repos.skill_repository import SkillRepository

    session = _session()
    seed_path = tmp_path / "seed.md"
    seed_path.write_text("seed body", encoding="utf-8")

    def fail_create_skill(self, **_kwargs):
        raise RuntimeError("bootstrap write failed")

    monkeypatch.setattr(SkillRepository, "create_skill", fail_create_skill)

    with caplog.at_level(logging.ERROR):
        with pytest.raises(RuntimeError, match="bootstrap write failed"):
            SkillBootstrapService(
                session=session,
                seed_file_path=str(seed_path),
            ).bootstrap_missing_skill(
                session=session,
                use_unified_config=False,
            )

    assert "初始化内置方法论失败" in caplog.text
