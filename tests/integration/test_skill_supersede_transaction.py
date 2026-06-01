from __future__ import annotations

import threading
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.business.brain.skill_reference_counter import SkillReferenceCounterService
from src.business.brain.skill_service import SkillService
from src.data.models_sqlite import (
    Base,
    BrainMemoryEntry,
    BrainSkill,
    BrainSkillEquipment,
    BrainSpecialist,
)
from src.data.repos.skill_repository import SkillRepository


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


def _specialist(session) -> None:
    session.add(
        BrainSpecialist(
            specialist_id="sp-1",
            name="测试专员",
            description="测试",
            role_definition="测试",
            tool_whitelist="[]",
            origin="user_management_ui",
            reason="test",
            is_active=True,
        )
    )
    session.commit()


def _create(service: SkillService, session, *, name: str = "事务方法论") -> dict:
    return service.create(
        name=name,
        description="v1",
        trigger_conditions=["触发"],
        required_tools=[],
        body_markdown="v1",
        source_segments=[_source(session, "seg-create")],
        origin="assistant_tool_call",
        caller_type="assistant",
        caller_id="_assistant",
        change_reason="create reason",
    )


def _supersede(service: SkillService, session, target_skill_id: str, *, suffix: str, reason: str):
    return service.supersede(
        target_skill_id=target_skill_id,
        name="事务方法论",
        description=f"v {suffix}",
        trigger_conditions=["触发"],
        required_tools=[],
        body_markdown=f"body {suffix}",
        source_segments=[_source(session, f"seg-{suffix}")],
        origin="assistant_tool_call",
        caller_type="assistant",
        caller_id="_assistant",
        change_reason=reason,
    )


def test_supersede_switches_equipment_in_one_transaction() -> None:
    session = _session()
    _specialist(session)
    service = SkillService(session=session)
    created = _create(service, session)

    result = _supersede(
        service, session, created["skill_id"], suffix="v2", reason="assistant reason"
    )

    active_rows = (
        session.query(BrainSkillEquipment).filter(BrainSkillEquipment.status == "active").all()
    )
    assert {row.skill_id for row in active_rows} == {result["skill_id"]}
    old_rows = (
        session.query(BrainSkillEquipment)
        .filter(BrainSkillEquipment.skill_id == created["skill_id"])
        .all()
    )
    assert old_rows
    assert all(row.status == "unequipped" for row in old_rows)
    assert all(row.unequipped_reason == "supersede_transfer" for row in old_rows)


def test_supersede_rolls_back_skill_and_equipment_when_equipment_transfer_fails(
    monkeypatch,
) -> None:
    session = _session()
    service = SkillService(session=session)
    created = _create(service, session)

    def fail_transfer(*_args, **_kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(
        "src.business.brain.skill_equipment_service.SkillEquipmentService.supersede_equipment",
        fail_transfer,
    )

    with pytest.raises(RuntimeError, match="boom"):
        _supersede(service, session, created["skill_id"], suffix="rollback", reason="rollback")

    chain = SkillRepository(session=session).get_chain(created["skill_id"])
    assert [row.skill_id for row in chain] == [created["skill_id"]]
    assert chain[0].status == "active"


def test_late_supersede_uses_current_active_as_new_baseline() -> None:
    session = _session()
    service = SkillService(session=session)
    created = _create(service, session)

    v2 = _supersede(service, session, created["skill_id"], suffix="v2", reason="first writer")
    v3 = _supersede(service, session, created["skill_id"], suffix="v3", reason="late writer")

    chain = SkillRepository(session=session).get_chain(created["skill_id"])
    assert [row.skill_id for row in chain] == [created["skill_id"], v2["skill_id"], v3["skill_id"]]
    assert [row.version for row in chain] == [1, 2, 3]
    assert chain[1].superseded_by == v3["skill_id"]
    assert chain[2].parent_skill_id == v2["skill_id"]


def test_concurrent_supersede_serializes_without_version_fork(tmp_path) -> None:
    db_path = tmp_path / "skill-supersede.db"
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False, "timeout": 10},
        future=True,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    setup_session = Session()
    try:
        service = SkillService(session=setup_session)
        created = _create(service, setup_session)
    finally:
        setup_session.close()

    barrier = threading.Barrier(2)
    results: list[dict] = []
    errors: list[BaseException] = []
    results_lock = threading.Lock()

    def worker(suffix: str) -> None:
        session = Session()
        try:
            barrier.wait(timeout=5)
            result = _supersede(
                SkillService(session=session),
                session,
                created["skill_id"],
                suffix=suffix,
                reason=f"{suffix} writer",
            )
            with results_lock:
                results.append(result)
        except BaseException as exc:  # pragma: no cover - re-raised after threads join
            with results_lock:
                errors.append(exc)
        finally:
            session.close()

    threads = [threading.Thread(target=worker, args=(suffix,)) for suffix in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert not any(thread.is_alive() for thread in threads)
    assert errors == []
    assert len(results) == 2

    verify_session = Session()
    try:
        chain = SkillRepository(session=verify_session).get_chain(created["skill_id"])
        active = [row for row in chain if row.status == "active"]
        assert [row.version for row in chain] == [1, 2, 3]
        assert len(active) == 1
        assert chain[1].parent_skill_id == created["skill_id"]
        assert chain[2].parent_skill_id == chain[1].skill_id
        assert chain[0].superseded_by == chain[1].skill_id
        assert chain[1].superseded_by == chain[2].skill_id
    finally:
        verify_session.close()


def test_supersede_inherits_and_continues_counts() -> None:
    session = _session()
    service = SkillService(session=session)
    created = _create(service, session)
    original = session.get(BrainSkill, created["skill_id"])
    original.loaded_count = 4
    original.referenced_count = 2
    original.last_referenced_at = datetime(2026, 1, 1, 1, 2, 3)
    session.commit()

    result = _supersede(service, session, created["skill_id"], suffix="v2", reason="count inherit")

    active = session.get(BrainSkill, result["skill_id"])
    assert active.loaded_count == 4
    assert active.referenced_count == 2
    assert active.last_referenced_at == datetime(2026, 1, 1, 1, 2, 3)
    SkillRepository(session=session).increment_loaded_count(active.skill_id)
    SkillReferenceCounterService(repo=SkillRepository(session=session)).process_reply_metadata(
        [active.skill_id]
    )
    session.refresh(active)
    assert active.loaded_count == 5
    assert active.referenced_count == 3


def test_history_and_audit_include_change_reasons_for_user_and_assistant_supersede() -> None:
    session = _session()
    _specialist(session)
    service = SkillService(session=session)
    created = _create(service, session)
    assistant_v2 = _supersede(
        service, session, created["skill_id"], suffix="assistant", reason="assistant reason"
    )
    user_v3 = service.user_edit_supersede(
        assistant_v2["skill_id"],
        {
            "name": "事务方法论",
            "description": "user v3",
            "trigger_conditions": ["触发"],
            "required_tools": [],
            "body_markdown": "user body",
            "source_segments": [_source(session, "seg-user")],
            "change_reason": "user reason",
        },
    )

    history = service.get_history(user_v3["skill_id"])
    audit = service.get_equipment_audit(assistant_v2["skill_id"])

    assert [node["change_reason"] for node in history["nodes"]] == [
        "create reason",
        "assistant reason",
        "user reason",
    ]
    assert "-body assistant" in history["nodes"][2]["diff_from_previous"]
    assert "+user body" in history["nodes"][2]["diff_from_previous"]
    assert {row["skill_id"] for row in audit["rows"]} >= {
        created["skill_id"],
        assistant_v2["skill_id"],
        user_v3["skill_id"],
    }
    assert any(row["unequipped_reason"] == "supersede_transfer" for row in audit["rows"])
