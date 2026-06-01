from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.business.brain.skill_bootstrap_service import SkillBootstrapService
from src.data.models_sqlite import Base, BrainSkill


def _session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_missing_seed_uses_fallback_and_bootstraps_skill(tmp_path) -> None:
    session = _session()
    missing = tmp_path / "missing.md"

    result = SkillBootstrapService(
        session=session, seed_file_path=str(missing)
    ).bootstrap_missing_skill(
        session=session,
        use_unified_config=False,
    )

    skill = session.get(BrainSkill, SkillBootstrapService.BOOTSTRAP_HOW_TO_SKILL_ID)
    assert result["fallback_used"] is True
    assert skill is not None
    assert "系统应急 fallback" in skill.body_markdown


def test_empty_seed_uses_fallback(tmp_path) -> None:
    seed = tmp_path / "empty.md"
    seed.write_text("   ", encoding="utf-8")

    result = SkillBootstrapService(seed_file_path=str(seed)).load_seed_or_fallback(
        use_unified_config=False
    )

    assert result.fallback_used is True
    assert result.reason == "seed_file_empty"


def test_seed_io_error_uses_fallback(monkeypatch, tmp_path) -> None:
    seed = tmp_path / "seed.md"
    seed.write_text("content", encoding="utf-8")

    def raise_os_error(*_args, **_kwargs):
        raise OSError("simulated")

    monkeypatch.setattr("pathlib.Path.read_text", raise_os_error)

    result = SkillBootstrapService(seed_file_path=str(seed)).load_seed_or_fallback(
        use_unified_config=False
    )

    assert result.fallback_used is True
    assert result.reason == "seed_file_io_error"


def test_restored_seed_self_heals_fallback_chain(tmp_path, monkeypatch) -> None:
    session = _session()
    seed = tmp_path / "seed.md"
    missing = tmp_path / "missing.md"
    service = SkillBootstrapService(session=session, seed_file_path=str(missing))
    service.bootstrap_missing_skill(session=session, use_unified_config=False)
    seed.write_text("# 真实 seed\n\n完整指引", encoding="utf-8")
    monkeypatch.setattr(
        "src.data.unified_config.get_unified_config",
        lambda: type("Config", (), {"get_brain_skill_seed_file_path": lambda self: str(seed)})(),
    )

    result = SkillBootstrapService(
        session=session, seed_file_path=str(seed)
    ).ensure_bootstrap_skill()

    assert result["fallback_used"] is False
    active = session.get(BrainSkill, result["bootstrap_active_skill_id"])
    root = session.get(BrainSkill, SkillBootstrapService.BOOTSTRAP_HOW_TO_SKILL_ID)
    assert active.body_markdown == "# 真实 seed\n\n完整指引"
    assert active.version == 2
    assert root.status == "superseded"
