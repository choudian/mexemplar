from __future__ import annotations

from typing import Any

from src.business.services.skill_composition.service import SkillCompositionService
from src.business.services.skill_composition.types import SkillCompositionError


class UiAdapter:
    """DTO adapter over SkillCompositionService for the desktop API."""

    def __init__(self, service: SkillCompositionService | None = None) -> None:
        self._service = service or SkillCompositionService()

    def list_compositions(self) -> list[dict[str, Any]]:
        return [self._composition_to_summary(item) for item in self._service.list_compositions()]

    def create(self, payload: dict[str, Any]) -> dict[str, Any]:
        composition = self._service.create_composition(
            composition_name=payload.get("name") or "",
            description=payload.get("description") or "",
            applicability=payload.get("applicability") or "",
            mode=payload.get("mode") or "range",
            members=self._members_from_payload(payload.get("members") or []),
            assistant_enabled=bool(payload.get("assistantEnabled", True)),
            recommend_order=bool(payload.get("recommendOrder", False)),
        )
        return self._composition_to_summary(composition)

    def update(self, composition_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        composition = self._service.update_composition(
            composition_id=composition_id,
            composition_name=payload.get("name") or "",
            description=payload.get("description") or "",
            applicability=payload.get("applicability") or "",
            mode=payload.get("mode") or "range",
            members=self._members_from_payload(payload.get("members") or []),
            assistant_enabled=bool(payload.get("assistantEnabled", True)),
            recommend_order=bool(payload.get("recommendOrder", False)),
        )
        return self._composition_to_summary(composition)

    def publish(self, composition_id: str) -> dict[str, Any]:
        return self._composition_to_summary(self._service.publish_composition(composition_id))

    def generate_applicability(self, payload: dict[str, Any]) -> str:
        return self._service.generate_applicability(
            composition_name=payload.get("name") or "",
            description=payload.get("description") or "",
            mode=payload.get("mode") or "range",
            members=self._members_from_payload(payload.get("members") or []),
        )

    def recommend_order(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._service.recommend_execution_order(
            composition_name=payload.get("name") or "",
            description=payload.get("description") or "",
            applicability=payload.get("applicability") or "",
            members=self._members_from_payload(payload.get("members") or []),
        )

    def start_trial(self, composition_id: str) -> dict[str, Any]:
        result = self._service.start_trial_session(composition_id)
        return {
            "accepted": True,
            "compositionId": result.composition_id,
            "name": result.composition_name,
            "sessionId": result.session_id,
        }

    @staticmethod
    def _members_from_payload(members: list[Any]) -> list[dict[str, Any]]:
        result = []
        for index, member in enumerate(members, start=1):
            if hasattr(member, "model_dump"):
                member = member.model_dump()
            result.append(
                {
                    "tool_id": member.get("toolId") or member.get("tool_id"),
                    "selected_order": (
                        member["selectedOrder"]
                        if "selectedOrder" in member
                        else member.get("selected_order", index)
                    ),
                    "execution_order": (
                        member["executionOrder"]
                        if "executionOrder" in member
                        else member.get("execution_order")
                    ),
                }
            )
        return result

    @staticmethod
    def _composition_to_summary(composition) -> dict[str, Any]:
        display_status = "needs_review" if composition.needs_review else composition.status
        return {
            "compositionId": composition.composition_id,
            "name": composition.composition_name,
            "description": composition.description or "",
            "mode": composition.mode,
            "status": composition.status,
            "displayStatus": display_status,
            "needsReview": bool(composition.needs_review),
            "assistantEnabled": bool(composition.assistant_enabled),
            "applicability": composition.applicability or "",
            "isBuiltin": bool(getattr(composition, "is_builtin", False)),
            "readOnly": bool(getattr(composition, "is_read_only", False)),
            "trialSupported": bool(getattr(composition, "trial_supported", True)),
            "members": [
                {
                    "memberId": member.member_id,
                    "toolId": member.tool_id,
                    "name": member.tool.tool_name if member.tool else member.tool_id,
                    "description": (member.tool.description or "") if member.tool else "",
                    "selectedOrder": member.selected_order,
                    "executionOrder": member.execution_order,
                }
                for member in composition.members
            ],
        }


__all__ = ["SkillCompositionError", "UiAdapter"]
