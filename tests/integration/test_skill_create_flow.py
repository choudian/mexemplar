from __future__ import annotations

import json
import time

from fastapi.testclient import TestClient

from src.business.agents.tools.skill_methodology_tools import (
    create_create_skill_methodology_handler,
)
from src.data.models_sqlite import BrainMemoryEntry, BrainSegment
from src.desktop_api.app import SESSION_HEADER, create_app


def _client() -> TestClient:
    token = "test-token"
    return TestClient(create_app(token), headers={SESSION_HEADER: token})


def _source(in_memory_db, segment_id: str, *, zone: str = "archive") -> list[dict[str, str]]:
    with in_memory_db.get_session() as session:
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
    return [{"segment_id": segment_id, "source_zone": zone}]


def test_skill_create_to_api_list_to_user_edit_flow(in_memory_db) -> None:
    client = _client()
    handler = create_create_skill_methodology_handler(
        caller_type="assistant", caller_id="_assistant"
    )

    start = time.monotonic()
    created = json.loads(
        handler(
            mode="create",
            name="集成方法论",
            description="集成测试创建",
            trigger_conditions=["执行集成测试时"],
            required_tools=[],
            body_markdown="v1 正文",
            source_segments=_source(in_memory_db, "seg-create"),
            change_reason="集成测试创建",
        )
    )
    listed = client.get("/api/skills/methodology")
    create_visible_elapsed = time.monotonic() - start

    assert created["success"] is True
    assert listed.status_code == 200
    assert created["skill_id"] in {item["skill_id"] for item in listed.json()["items"]}
    assert create_visible_elapsed <= 30

    edit_start = time.monotonic()
    edited = client.put(
        f"/api/skills/methodology/{created['skill_id']}",
        json={
            "name": "集成方法论",
            "description": "集成测试 v2",
            "trigger_conditions": ["执行集成测试时"],
            "required_tools": [],
            "body_markdown": "v2 正文",
            "change_reason": "集成测试编辑",
        },
    )
    history = client.get(f"/api/skills/methodology/{created['skill_id']}/history")
    audit = client.get(f"/api/skills/methodology/{edited.json()['skill_id']}/audit-equipment")
    edit_visible_elapsed = time.monotonic() - edit_start

    assert edited.status_code == 200
    assert edited.json()["version"] == 2
    assert history.status_code == 200
    assert [node["version"] for node in history.json()["nodes"]] == [1, 2]
    assert audit.status_code == 200
    assert edit_visible_elapsed <= 3


def test_create_tool_failure_returns_explicit_error(in_memory_db) -> None:
    handler = create_create_skill_methodology_handler(
        caller_type="assistant", caller_id="_assistant"
    )

    result = json.loads(
        handler(
            mode="create",
            name="错误方法论",
            description="错误路径",
            trigger_conditions=["执行集成测试时"],
            required_tools=[],
            body_markdown="正文",
            source_segments=_source(in_memory_db, "seg-hot", zone="hot"),
            change_reason="错误路径",
        )
    )

    assert result["success"] is False
    assert result["error"] == "skill_source_segment_wrong_zone"
    assert result["message"]


def test_create_tool_rejects_mismatched_existing_source_zone(in_memory_db) -> None:
    handler = create_create_skill_methodology_handler(
        caller_type="assistant", caller_id="_assistant"
    )
    _source(in_memory_db, "seg-mismatch", zone="hot")

    result = json.loads(
        handler(
            mode="create",
            name="Zone 不匹配方法论",
            description="错误路径",
            trigger_conditions=["执行集成测试时"],
            required_tools=[],
            body_markdown="正文",
            source_segments=[{"segment_id": "seg-mismatch", "source_zone": "archive"}],
            change_reason="错误路径",
        )
    )

    assert result["success"] is False
    assert result["error"] == "skill_source_segment_wrong_zone"


def test_create_tool_rejects_unknown_source_segment(in_memory_db) -> None:
    handler = create_create_skill_methodology_handler(
        caller_type="assistant", caller_id="_assistant"
    )

    result = json.loads(
        handler(
            mode="create",
            name="未知素材方法论",
            description="错误路径",
            trigger_conditions=["执行集成测试时"],
            required_tools=[],
            body_markdown="正文",
            source_segments=[{"segment_id": "seg-missing", "source_zone": "archive"}],
            change_reason="错误路径",
        )
    )

    assert result["success"] is False
    assert result["error"] == "skill_source_segment_wrong_zone"


def test_create_tool_allows_pending_source_segment_without_memory_entry(in_memory_db) -> None:
    handler = create_create_skill_methodology_handler(
        caller_type="assistant", caller_id="_assistant"
    )
    with in_memory_db.get_session() as session:
        session.add(
            BrainSegment(
                segment_id="seg-pending",
                session_id="sess-pending",
                status="pending",
                boundary_reason="idle",
            )
        )
        session.commit()

    result = json.loads(
        handler(
            mode="create",
            name="过渡态素材方法论",
            description="允许 pending segment",
            trigger_conditions=["执行集成测试时"],
            required_tools=[],
            body_markdown="正文",
            source_segments=[{"segment_id": "seg-pending", "source_zone": "archive"}],
            change_reason="过渡态素材",
        )
    )

    assert result["success"] is True
