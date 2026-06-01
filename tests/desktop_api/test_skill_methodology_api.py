from __future__ import annotations

import queue

from src.business.brain.skill_bootstrap_service import SkillBootstrapService
from src.business.brain.skill_equipment_service import SkillEquipmentService
from src.business.brain.skill_service import SkillService
from src.data.models_sqlite import (
    BrainMemoryEntry,
    BrainSkill,
    BrainSkillEquipment,
    BrainSpecialist,
)
from src.data.repos.skill_equipment_repository import SkillEquipmentRepository
from src.data.repos.skill_repository import SkillRepository
from src.desktop_api.events import event_queue


def _drain_events() -> None:
    event_queue.reset_for_tests()
    while True:
        try:
            event_queue.queue.get_nowait()
        except queue.Empty:
            return


def _source_entry(session, segment_id: str = "seg-1") -> None:
    session.add(
        BrainMemoryEntry(
            entry_id=f"entry-{segment_id}",
            zone="archive",
            content="可作为方法论素材的归档片段",
            status="active",
            origin="distillation",
            reason="test",
            source_segment_id=segment_id,
            relevance_score=1.0,
        )
    )
    session.commit()


def _specialist(session, specialist_id: str = "sp-1", whitelist: str = "[]") -> None:
    session.add(
        BrainSpecialist(
            specialist_id=specialist_id,
            name=f"专员 {specialist_id}",
            description="测试专员",
            role_definition="执行测试",
            tool_whitelist=whitelist,
            origin="user_management_ui",
            reason="test",
            is_active=True,
        )
    )
    session.commit()


def _skill(
    session,
    skill_id: str,
    *,
    name: str | None = None,
    origin: str = "assistant_tool_call",
    required_tools: list[str] | None = None,
    source_segment_id: str | None = None,
) -> BrainSkill:
    source_segments = (
        [{"segment_id": source_segment_id, "source_zone": "archive"}] if source_segment_id else []
    )
    return SkillRepository(session=session).create_skill(
        skill_id=skill_id,
        name=name or f"方法论 {skill_id}",
        description="测试方法论",
        trigger_conditions=["需要测试时"],
        required_tools=required_tools or [],
        body_markdown=f"# {skill_id}\n\n测试正文",
        origin=origin,
        source_segments=source_segments,
    )


def test_methodology_list_detail_and_equipped_count_include_assistant(
    desktop_api_client, in_memory_db
):
    status = desktop_api_client.get("/api/skills/methodology/bootstrap-status")
    assert status.status_code == 200
    bootstrap_id = status.json()["bootstrap_active_skill_id"]

    listed = desktop_api_client.get("/api/skills/methodology?sort=equipped_count")
    assert listed.status_code == 200
    item = next(item for item in listed.json()["items"] if item["skill_id"] == bootstrap_id)
    assert item["equipped_count"] == 1
    assert item["is_protected"] is True

    detail = desktop_api_client.get(f"/api/skills/methodology/{bootstrap_id}")
    assert detail.status_code == 200
    assert detail.json()["body_markdown"]


def test_methodology_edit_emits_safe_skill_changed_event(desktop_api_client, in_memory_db):
    with in_memory_db.get_session() as session:
        _source_entry(session, "seg-edit")
        _skill(session, "skill-edit", name="旧名称", source_segment_id="seg-edit")
    _drain_events()

    response = desktop_api_client.put(
        "/api/skills/methodology/skill-edit",
        json={
            "name": "新名称",
            "description": "更新后的描述",
            "trigger_conditions": ["场景更新"],
            "required_tools": [],
            "body_markdown": "更新后的正文",
            "change_reason": "API 测试编辑",
        },
    )

    assert response.status_code == 200
    assert response.json()["name"] == "新名称"
    events = []
    while True:
        try:
            events.append(event_queue.queue.get_nowait())
        except queue.Empty:
            break
    skill_changed = next(event for event in events if event.type == "skill.changed")
    assert skill_changed.payload["reason"] == "user_edit"
    assert skill_changed.payload["skillId"] == response.json()["skill_id"]
    assert "body_markdown" not in skill_changed.payload
    assert "bodyMarkdown" not in skill_changed.payload


def test_methodology_soft_delete_prunes_equipment_after_confirmation(
    desktop_api_client,
    in_memory_db,
    monkeypatch,
):
    monkeypatch.setattr(
        "src.desktop_api.routers.skills_methodology.request_high_risk_confirmation",
        lambda *_args, **_kwargs: True,
    )
    with in_memory_db.get_session() as session:
        _specialist(session, "sp-1")
        _skill(session, "skill-delete")
        SkillEquipmentRepository(session=session).equip(
            entity_type="specialist",
            entity_id="sp-1",
            skill_id="skill-delete",
        )

    response = desktop_api_client.post("/api/skills/methodology/skill-delete/soft-delete")

    assert response.status_code == 200
    assert response.json()["pruned_equipment_count"] == 1
    with in_memory_db.get_session() as session:
        assert session.get(BrainSkill, "skill-delete").status == "soft_deleted"
        equipment = (
            session.query(BrainSkillEquipment)
            .filter(BrainSkillEquipment.skill_id == "skill-delete")
            .one()
        )
        assert equipment.status == "unequipped"
        assert equipment.unequipped_reason == "force_remove_on_soft_delete"


def test_bootstrap_status_contract(desktop_api_client):
    response = desktop_api_client.get("/api/skills/methodology/bootstrap-status")

    assert response.status_code == 200
    data = response.json()
    assert data["bootstrap_active_skill_id"]
    assert isinstance(data["fallback_used"], bool)
    assert data["seed_file_path"]
    assert data["last_seed_check_at"]


def test_bootstrap_edit_requests_high_risk_confirmation(
    desktop_api_client,
    monkeypatch,
):
    confirmations = []
    monkeypatch.setattr(
        "src.desktop_api.routers.skills_methodology.request_high_risk_confirmation",
        lambda action_type, *_args, **_kwargs: confirmations.append(action_type) or True,
    )
    bootstrap_id = desktop_api_client.get("/api/skills/methodology/bootstrap-status").json()[
        "bootstrap_active_skill_id"
    ]
    detail = desktop_api_client.get(f"/api/skills/methodology/{bootstrap_id}").json()

    response = desktop_api_client.put(
        f"/api/skills/methodology/{bootstrap_id}",
        json={
            "name": detail["name"],
            "description": detail["description"],
            "trigger_conditions": detail["trigger_conditions"],
            "required_tools": detail["required_tools"],
            "body_markdown": f"{detail['body_markdown']}\n\n用户修订",
            "change_reason": "API 保护链编辑测试",
        },
    )

    assert response.status_code == 200
    assert confirmations == ["skill.edit_protected"]
    assert response.json()["origin"] == "user_edit"
    assert response.json()["source_segments"] == []


def test_methodology_edit_maps_supersede_conflict_to_409(
    desktop_api_client,
    in_memory_db,
    monkeypatch,
):
    with in_memory_db.get_session() as session:
        _skill(session, "skill-conflict")
    monkeypatch.setattr(
        SkillService,
        "user_edit_supersede",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("skill_supersede_conflict")),
    )

    response = desktop_api_client.put(
        "/api/skills/methodology/skill-conflict",
        json={
            "name": "冲突方法论",
            "description": "测试",
            "trigger_conditions": ["触发"],
            "required_tools": [],
            "body_markdown": "正文",
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["error"] == "skill_supersede_conflict"


def test_bootstrap_status_maps_failure_to_structured_error(desktop_api_client, monkeypatch):
    monkeypatch.setattr(
        SkillBootstrapService,
        "bootstrap_status",
        lambda _self: (_ for _ in ()).throw(RuntimeError("bootstrap unavailable")),
    )

    response = desktop_api_client.get("/api/skills/methodology/bootstrap-status")

    assert response.status_code == 500
    assert response.json()["detail"]["error"] == "skill_bootstrap_failed"


def test_equipment_get_and_put_contract(desktop_api_client, in_memory_db):
    with in_memory_db.get_session() as session:
        _specialist(session, "sp-1", whitelist='["available_tool"]')
        _skill(session, "skill-1", required_tools=["available_tool"])
        _skill(session, "skill-2", required_tools=["missing_tool"])
        SkillEquipmentService(session=session).equip(entity_id="sp-1", skill_id="skill-1")

    current = desktop_api_client.get("/api/specialists/sp-1/equipment")
    assert current.status_code == 200
    assert current.json()["active_equipment"][0]["skill_id"] == "skill-1"
    assert current.json()["active_equipment"][0]["missing_required_tools"] == []
    assert current.json()["token_budget_thresholds"]["warn_threshold"] == 4096

    updated = desktop_api_client.put(
        "/api/specialists/sp-1/equipment",
        json={"skills": [{"skill_id": "skill-2", "equipped_order": 0}]},
    )

    assert updated.status_code == 200
    assert updated.json()["newly_equipped"] == ["skill-2"]
    assert updated.json()["newly_unequipped"] == ["skill-1"]
    after = desktop_api_client.get("/api/specialists/sp-1/equipment")
    assert after.status_code == 200
    assert after.json()["active_equipment"][0]["skill_id"] == "skill-2"
    assert after.json()["active_equipment"][0]["missing_required_tools"] == ["missing_tool"]


def test_equipment_endpoint_rejects_non_active_skill(desktop_api_client, in_memory_db):
    with in_memory_db.get_session() as session:
        _specialist(session, "sp-1")
        skill = _skill(session, "inactive")
        skill.status = "soft_deleted"
        session.commit()

    response = desktop_api_client.put(
        "/api/specialists/sp-1/equipment",
        json={"skills": [{"skill_id": "inactive", "equipped_order": 0}]},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["error"] == "skill_equipment_skill_not_active"
