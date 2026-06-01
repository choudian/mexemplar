from __future__ import annotations

import logging
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.business.brain.skill_service import SkillService
from src.data.models_sqlite import Base, BrainMemoryEntry, BrainSkill


def _session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _source(session, segment_id: str, *, zone: str = "archive") -> dict[str, str]:
    session.add(
        BrainMemoryEntry(
            entry_id=f"entry-{segment_id}",
            zone=zone,
            content=f"{zone} 素材",
            status="active",
            origin="distillation",
            reason="test",
            source_segment_id=segment_id,
            relevance_score=1.0,
        )
    )
    session.commit()
    return {"segment_id": segment_id, "source_zone": zone}


def _create(service: SkillService, session, *, name: str = "方法论") -> dict:
    return service.create(
        name=name,
        description="测试方法论",
        trigger_conditions=["需要处理同类任务时"],
        required_tools=[],
        body_markdown="执行步骤正文",
        source_segments=[_source(session, f"seg-{name}")],
        origin="assistant_tool_call",
        caller_type="assistant",
        caller_id="_assistant",
        change_reason="unit test",
    )


def test_skill_service_create_persists_active_skill_and_summary_fields() -> None:
    session = _session()
    service = SkillService(session=session)

    created = _create(service, session, name="创建方法论")
    listed = service.list_active()

    assert created["success"] is True
    assert [item["skill_id"] for item in listed] == [created["skill_id"]]
    assert listed[0]["trigger_conditions"] == ["需要处理同类任务时"]
    assert listed[0]["loaded_count"] == 0
    assert listed[0]["referenced_count"] == 0


def test_skill_service_source_validation_rejects_wrong_zone() -> None:
    session = _session()
    service = SkillService(session=session)

    with pytest.raises(ValueError, match="skill_source_segment_wrong_zone"):
        service.create(
            name="错误来源方法论",
            description="测试方法论",
            trigger_conditions=["需要处理同类任务时"],
            required_tools=[],
            body_markdown="执行步骤正文",
            source_segments=[_source(session, "seg-hot", zone="hot")],
            origin="assistant_tool_call",
            caller_type="assistant",
            caller_id="_assistant",
            change_reason="unit test",
        )


def test_skill_service_soft_delete_keeps_row_and_removes_from_active_list() -> None:
    session = _session()
    service = SkillService(session=session)
    created = _create(service, session, name="待删除方法论")

    result = service.force_soft_delete(created["skill_id"])
    persisted = session.get(BrainSkill, created["skill_id"])

    assert result["deleted_skill_id"] == created["skill_id"]
    assert persisted.status == "soft_deleted"
    assert service.list_active() == []


def test_force_soft_delete_rejects_system_bootstrap_chain() -> None:
    session = _session()
    service = SkillService(session=session)
    created = service.create(
        name="内置方法论",
        description="测试方法论",
        trigger_conditions=["需要处理同类任务时"],
        required_tools=[],
        body_markdown="执行步骤正文",
        source_segments=[_source(session, "seg-bootstrap")],
        origin="system_bootstrap",
        caller_type="system",
        caller_id="_system",
        change_reason="bootstrap",
    )

    with pytest.raises(PermissionError, match="bootstrap_skill_not_softdeletable"):
        service.force_soft_delete(created["skill_id"])

    assert session.get(BrainSkill, created["skill_id"]).status == "active"


def test_skill_service_create_failure_is_logged(caplog) -> None:
    session = _session()
    service = SkillService(session=session)

    def fail_create_skill(**_kwargs):
        raise RuntimeError("write failed")

    service._skill_repo.create_skill = fail_create_skill

    with caplog.at_level(logging.ERROR):
        with pytest.raises(RuntimeError, match="write failed"):
            service.create(
                name="失败方法论",
                description="测试方法论",
                trigger_conditions=["需要处理同类任务时"],
                required_tools=[],
                body_markdown="执行步骤正文",
                source_segments=[_source(session, "seg-fail")],
                origin="assistant_tool_call",
                caller_type="assistant",
                caller_id="_assistant",
                change_reason="unit test",
            )

    assert "创建方法论失败" in caplog.text


def test_list_active_uses_batch_summary_lookups(monkeypatch) -> None:
    session = _session()
    service = SkillService(session=session)
    first = _create(service, session, name="批量列表一")
    second = _create(service, session, name="批量列表二")
    calls: list[tuple[str, list[str]]] = []

    monkeypatch.setattr(
        service._skill_repo,
        "system_bootstrap_chain_roots",
        lambda ids: calls.append(("protected", ids)) or set(),
    )
    monkeypatch.setattr(
        service._equipment_repo,
        "active_counts_for_skills",
        lambda ids: calls.append(("equipment", ids)) or {skill_id: 1 for skill_id in ids},
    )
    monkeypatch.setattr(
        service,
        "is_system_bootstrap_chain",
        lambda _skill_id: (_ for _ in ()).throw(AssertionError("per-skill protected query")),
    )
    monkeypatch.setattr(
        service._equipment_repo,
        "active_count_for_skill",
        lambda _skill_id: (_ for _ in ()).throw(AssertionError("per-skill equipment query")),
    )

    listed = service.list_active()

    assert {item["skill_id"] for item in listed} == {first["skill_id"], second["skill_id"]}
    assert all(item["equipped_count"] == 1 for item in listed)
    assert [name for name, _ids in calls] == ["protected", "equipment"]
