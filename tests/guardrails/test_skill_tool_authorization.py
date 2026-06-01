from __future__ import annotations

import json

from src.business.agents.tools.skill_methodology_tools import (
    create_create_skill_methodology_handler,
)
from src.data.models_sqlite import BrainMemoryEntry, BrainSkill


def _source(in_memory_db, segment_id: str) -> list[dict[str, str]]:
    with in_memory_db.get_session() as session:
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
    return [{"segment_id": segment_id, "source_zone": "archive"}]


def _create_args(name: str, source_segments: list[dict[str, str]]) -> dict:
    return {
        "mode": "create",
        "name": name,
        "description": "测试方法论",
        "trigger_conditions": ["需要测试时"],
        "required_tools": [],
        "body_markdown": "正文",
        "source_segments": source_segments,
        "change_reason": "test",
    }


def test_specialist_without_tool_whitelist_cannot_create_methodology() -> None:
    handler = create_create_skill_methodology_handler(
        caller_type="specialist",
        caller_id="sp-1",
        tool_whitelist=[],
    )

    result = json.loads(
        handler(**_create_args("未授权方法论", [{"segment_id": "seg", "source_zone": "archive"}]))
    )

    assert result["success"] is False
    assert result["error"] == "unauthorized_tool_call"
    assert "无权限" in result["message"]


def test_assistant_default_authorization_can_create_methodology(in_memory_db) -> None:
    handler = create_create_skill_methodology_handler(
        caller_type="assistant", caller_id="_assistant"
    )

    result = json.loads(
        handler(**_create_args("助理创建方法论", _source(in_memory_db, "seg-assistant")))
    )

    assert result["success"] is True
    with in_memory_db.get_session() as session:
        skill = session.get(BrainSkill, result["skill_id"])
        assert skill is not None
        assert skill.origin == "assistant_tool_call"


def test_authorized_specialist_can_create_methodology(in_memory_db) -> None:
    handler = create_create_skill_methodology_handler(
        caller_type="specialist",
        caller_id="sp-1",
        tool_whitelist=["create_skill_methodology"],
    )

    result = json.loads(
        handler(**_create_args("专员创建方法论", _source(in_memory_db, "seg-specialist")))
    )

    assert result["success"] is True
    with in_memory_db.get_session() as session:
        skill = session.get(BrainSkill, result["skill_id"])
        assert skill is not None
        assert skill.origin == "specialist_tool_call"
