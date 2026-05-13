"""Pure helpers for trial session snapshot serialization."""

import json
import re
from typing import Any, Optional

from src.data.models import SkillComposition, Tool, serialize_tool


def normalize_generated_text(content: str) -> str:
    cleaned = " ".join(line.strip() for line in (content or "").splitlines() if line.strip())
    cleaned = re.sub(r"^适用场景[:：]\s*", "", cleaned)
    return cleaned.strip().strip("\"'“”")


def coerce_snapshot_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def deserialize_trial_session_tool(payload: Any) -> Optional[Tool]:
    if not isinstance(payload, dict):
        return None
    tool_id = str(payload.get("tool_id") or "").strip()
    if not tool_id:
        return None
    return Tool(
        tool_id=tool_id,
        tool_name=str(payload.get("tool_name") or ""),
        description=payload.get("description"),
        parameters=list(payload.get("parameters") or []),
        steps=list(payload.get("steps") or []),
        execution_code=payload.get("execution_code"),
        code_language=str(payload.get("code_language") or "python"),
        code_version=str(payload.get("code_version") or "1.0"),
        execution_strategy=payload.get("execution_strategy"),
        dependencies=list(payload.get("dependencies") or []),
        source_intent_id=payload.get("source_intent_id"),
        source=str(payload.get("source") or "manual"),
        trial_count=coerce_snapshot_int(payload.get("trial_count"), 0),
        pending_tool_id=payload.get("pending_tool_id"),
        workflow_id=payload.get("workflow_id"),
        trial_success_count=coerce_snapshot_int(payload.get("trial_success_count"), 0),
        status=str(payload.get("status") or "pending"),
    )


def normalize_trial_session_member_snapshot(
    payload: Any,
    default_selected_order: int,
) -> Optional[dict]:
    if not isinstance(payload, dict):
        return None
    raw_tool = payload.get("tool")
    tool_payload = raw_tool if isinstance(raw_tool, dict) else None
    tool_id = str(
        payload.get("tool_id")
        or ((tool_payload or {}).get("tool_id") if tool_payload else "")
        or ""
    ).strip()
    if not tool_id:
        return None
    execution_order = payload.get("execution_order")
    normalized = dict(payload)
    normalized["tool_id"] = tool_id
    normalized["selected_order"] = coerce_snapshot_int(
        payload.get("selected_order"),
        default_selected_order,
    )
    normalized["execution_order"] = (
        coerce_snapshot_int(execution_order, default_selected_order)
        if execution_order not in (None, "")
        else None
    )
    normalized["tool"] = tool_payload
    return normalized


def build_trial_session_snapshot_payload(composition: SkillComposition) -> dict:
    return {
        "composition_id": composition.composition_id,
        "composition_name": composition.composition_name,
        "description": composition.description,
        "applicability": composition.applicability,
        "mode": composition.mode,
        "status": composition.status,
        "assistant_enabled": bool(composition.assistant_enabled),
        "recommend_order": bool(composition.recommend_order),
        "needs_review": bool(composition.needs_review),
        "member_tool_ids": [member.tool_id for member in composition.members],
        "members": [
            {
                "member_id": member.member_id,
                "tool_id": member.tool_id,
                "selected_order": member.selected_order,
                "execution_order": member.execution_order,
                "tool": serialize_tool(member.tool),
            }
            for member in composition.members
        ],
    }


def parse_trial_session_snapshot(raw_tool_ids: Optional[str]) -> dict:
    if not raw_tool_ids:
        return {}
    try:
        parsed = json.loads(raw_tool_ids)
    except (TypeError, ValueError):
        return {}

    if isinstance(parsed, list):
        return {
            "member_tool_ids": [str(tool_id).strip() for tool_id in parsed if str(tool_id).strip()]
        }

    if isinstance(parsed, dict):
        normalized_members = []
        raw_members = parsed.get("members") or []
        if isinstance(raw_members, list):
            for index, payload in enumerate(raw_members, start=1):
                normalized_member = normalize_trial_session_member_snapshot(payload, index)
                if normalized_member is not None:
                    normalized_members.append(normalized_member)
        member_tool_ids = parsed.get("member_tool_ids") or parsed.get("tool_ids") or []
        snapshot = dict(parsed)
        if normalized_members:
            snapshot["members"] = normalized_members
            if not member_tool_ids:
                member_tool_ids = [member["tool_id"] for member in normalized_members]
        snapshot["member_tool_ids"] = [
            str(tool_id).strip() for tool_id in member_tool_ids if str(tool_id).strip()
        ]
        return snapshot

    return {}
