import json
from types import SimpleNamespace

import pytest

from src.business.services import SkillCompositionError, SkillCompositionService
from src.business.services.skill_composition.composition_normalizer import (
    normalize_members,
)
from src.business.services.skill_composition.trial_snapshot_codec import (
    parse_trial_session_snapshot,
)
from src.data.models import Tool


class _FakeToolRepo:
    def __init__(self, tools):
        self._tools = {tool.tool_id: tool for tool in tools}

    def get_by_ids(self, tool_ids):
        return [self._tools[tool_id] for tool_id in tool_ids if tool_id in self._tools]


def test_normalize_members_sorts_selected_order_for_ordered_mode():
    repo = _FakeToolRepo(
        [
            Tool(tool_id="tool_a", tool_name="技能A", status="published"),
            Tool(tool_id="tool_b", tool_name="技能B", status="published"),
        ]
    )

    normalized = normalize_members(
        "ordered",
        [
            {"tool_id": "tool_b", "selected_order": 2, "execution_order": 2},
            {"tool_id": "tool_a", "selected_order": 1, "execution_order": 1},
        ],
        repo,
    )

    assert [member["tool_id"] for member in normalized] == ["tool_a", "tool_b"]
    assert [member["execution_order"] for member in normalized] == [1, 2]


def test_normalize_members_rejects_unpublished_tools():
    repo = _FakeToolRepo(
        [
            Tool(tool_id="tool_hidden", tool_name="隐藏技能", status="draft"),
            Tool(tool_id="tool_ok", tool_name="已掌握技能", status="published"),
        ]
    )

    with pytest.raises(SkillCompositionError, match="只能将已掌握技能加入技能组合"):
        normalize_members(
            "range",
            [
                {"tool_id": "tool_hidden", "selected_order": 1},
                {"tool_id": "tool_ok", "selected_order": 2},
            ],
            repo,
        )


def test_normalize_members_rejects_single_member():
    repo = _FakeToolRepo([Tool(tool_id="tool_a", tool_name="技能A", status="published")])

    with pytest.raises(SkillCompositionError, match="技能组合至少要包含两个技能"):
        normalize_members(
            "range",
            [{"tool_id": "tool_a", "selected_order": 1}],
            repo,
        )


def test_parse_trial_session_snapshot_supports_legacy_tool_id_list():
    snapshot = parse_trial_session_snapshot('["tool_a", "tool_b"]')

    assert snapshot == {"member_tool_ids": ["tool_a", "tool_b"]}


def test_parse_trial_session_snapshot_normalizes_member_payloads():
    raw_payload = json.dumps(
        {
            "composition_id": "comp_snapshot",
            "mode": "ordered",
            "members": [
                {
                    "member_id": "member_1",
                    "selected_order": "2",
                    "execution_order": "1",
                    "tool": {
                        "tool_id": "tool_nested",
                        "tool_name": "嵌套技能",
                        "status": "published",
                    },
                }
            ],
        },
        ensure_ascii=False,
    )

    snapshot = parse_trial_session_snapshot(raw_payload)

    assert snapshot["composition_id"] == "comp_snapshot"
    assert snapshot["member_tool_ids"] == ["tool_nested"]
    assert snapshot["members"] == [
        {
            "member_id": "member_1",
            "selected_order": 2,
            "execution_order": 1,
            "tool_id": "tool_nested",
            "tool": {
                "tool_id": "tool_nested",
                "tool_name": "嵌套技能",
                "status": "published",
            },
        }
    ]


def test_service_get_execution_snapshot_delegates_to_trial_runner():
    service = SkillCompositionService()
    captured = {}

    def fake_get_execution_snapshot(
        composition_id,
        require_published=True,
        require_assistant_enabled=True,
    ):
        captured["composition_id"] = composition_id
        captured["require_published"] = require_published
        captured["require_assistant_enabled"] = require_assistant_enabled
        return "snapshot"

    service._trial_sessions_instance = SimpleNamespace(
        get_execution_snapshot=fake_get_execution_snapshot
    )

    assert (
        service.get_execution_snapshot(
            "comp_split",
            require_published=False,
            require_assistant_enabled=False,
        )
        == "snapshot"
    )
    assert captured == {
        "composition_id": "comp_split",
        "require_published": False,
        "require_assistant_enabled": False,
    }
