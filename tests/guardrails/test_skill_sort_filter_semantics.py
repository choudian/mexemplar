from __future__ import annotations

from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from src.business.brain.skill_reference_counter import SkillReferenceCounterService
from src.business.brain.skill_equipment_service import SkillEquipmentService
from src.business.agents.tools.skill_methodology_tools import create_load_skill_methodology_handler
from src.data.models_sqlite import BrainMemoryEntry
from src.data.repos.skill_equipment_repository import SkillEquipmentRepository
from src.data.repos.skill_repository import SkillRepository
from src.desktop_api.app import SESSION_HEADER, create_app
from src.utils.timezone import utc_now_naive


def _client() -> TestClient:
    token = "test-token"
    return TestClient(create_app(token), headers={SESSION_HEADER: token})


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


def _skill(repo: SkillRepository, skill_id: str, *, name: str | None = None):
    return repo.create_skill(
        skill_id=skill_id,
        name=name or f"方法论 {skill_id}",
        description="测试",
        trigger_conditions=["触发"],
        required_tools=[],
        body_markdown="正文",
        origin="assistant_tool_call",
    )


def test_list_sort_keys_return_card_count_fields(in_memory_db) -> None:
    with in_memory_db.get_session() as session:
        repo = SkillRepository(session=session)
        _skill(repo, "sort-a")
        skill_b = _skill(repo, "sort-b")
        SkillEquipmentRepository(session=session).equip(
            entity_type="assistant",
            entity_id="_assistant",
            skill_id=skill_b.skill_id,
        )
        repo.increment_loaded_count(skill_b.skill_id)
        repo.increment_referenced_count(skill_b.skill_id)

    for sort_key in ["recently_changed", "loaded_count", "referenced_count", "equipped_count"]:
        response = _client().get(f"/api/skills/methodology?sort={sort_key}")
        assert response.status_code == 200
        target = next(item for item in response.json()["items"] if item["skill_id"] == "sort-b")
        assert {"loaded_count", "equipped_count", "referenced_count", "created_at"}.issubset(
            target.keys()
        )


def test_recent_change_uses_active_version_created_at_not_usage_or_equipment(in_memory_db) -> None:
    with in_memory_db.get_session() as session:
        repo = SkillRepository(session=session)
        root = _skill(repo, "recent-root", name="最近变更测试")
        repo.mark_superseded(root.skill_id, "recent-v2")
        active = repo.create_skill(
            skill_id="recent-v2",
            name="最近变更测试",
            description="v2",
            trigger_conditions=["触发"],
            required_tools=[],
            body_markdown="v2",
            origin="user_edit",
            parent_skill_id=root.skill_id,
            chain_root_id=root.chain_root_id,
            version=2,
        )
        fixed_created_at = datetime(2026, 1, 2, 3, 4, 5)
        active.created_at = fixed_created_at
        session.commit()
        equipment_service = SkillEquipmentService(session=session)
        equipment_service.equip(entity_id="_assistant", skill_id=active.skill_id)
        equipment_service.unequip(entity_id="_assistant", skill_id=active.skill_id)
        equipment_service.equip(entity_id="_assistant", skill_id=active.skill_id)
        create_load_skill_methodology_handler(
            caller_type="assistant",
            caller_id="_assistant",
            session=session,
        )(active.skill_id)
        SkillReferenceCounterService(repo=repo).process_reply_metadata([active.skill_id])

    response = _client().get("/api/skills/methodology?sort=recently_changed")

    assert response.status_code == 200
    target = next(item for item in response.json()["items"] if item["skill_id"] == "recent-v2")
    assert target["created_at"].startswith("2026-01-02T03:04:05")
    assert target["loaded_count"] == 1
    assert target["referenced_count"] == 1


def test_not_referenced_30d_filter_is_independent_from_recent_change_time(in_memory_db) -> None:
    old_reference_time = utc_now_naive() - timedelta(days=35)
    with in_memory_db.get_session() as session:
        repo = SkillRepository(session=session)
        root = repo.create_skill(
            skill_id="filter-root",
            name="筛选测试",
            description="v1",
            trigger_conditions=["触发"],
            required_tools=[],
            body_markdown="v1",
            origin="assistant_tool_call",
            referenced_count=1,
            last_referenced_at=old_reference_time,
        )
        repo.mark_superseded(root.skill_id, "filter-v2")
        repo.create_skill(
            skill_id="filter-v2",
            name="筛选测试",
            description="v2",
            trigger_conditions=["触发"],
            required_tools=[],
            body_markdown="v2",
            origin="user_edit",
            parent_skill_id=root.skill_id,
            chain_root_id=root.chain_root_id,
            version=2,
            referenced_count=1,
            last_referenced_at=old_reference_time,
        )

    response = _client().get("/api/skills/methodology?filter=not_referenced_30d")

    assert response.status_code == 200
    skill_ids = {item["skill_id"] for item in response.json()["items"]}
    assert "filter-v2" in skill_ids
