from __future__ import annotations

from src.data.models_sqlite import Tool
from src.data.repositories import SkillCompositionRepository, ToolRepository
from src.desktop_api.routers import compositions as compositions_router


def seed_published_tool(tool_id: str, name: str) -> None:
    ToolRepository().create(
        Tool(
            tool_id=tool_id,
            tool_name=name,
            description=f"{name} description",
            status="published",
            source="intent",
            workflow_id=f"wf_{tool_id}",
        )
    )


def composition_payload(name: str = "Monthly close"):
    return {
        "name": name,
        "description": "Close finance tasks",
        "mode": "ordered",
        "applicability": "Use when closing a monthly finance package.",
        "members": [
            {"toolId": "tool_a", "selectedOrder": 1, "executionOrder": 1},
            {"toolId": "tool_b", "selectedOrder": 2, "executionOrder": 2},
        ],
    }


def test_composition_create_update_publish_and_needs_review(desktop_api_client):
    seed_published_tool("tool_a", "Collect invoices")
    seed_published_tool("tool_b", "Prepare report")

    created = desktop_api_client.post("/api/compositions", json=composition_payload())
    assert created.status_code == 200
    composition_id = created.json()["compositionId"]
    assert created.json()["members"][0]["toolId"] == "tool_a"

    updated_payload = composition_payload("Monthly close updated")
    updated_payload["mode"] = "range"
    updated_payload["members"] = [
        {"toolId": "tool_a", "selectedOrder": 1},
        {"toolId": "tool_b", "selectedOrder": 2},
    ]
    updated = desktop_api_client.put(f"/api/compositions/{composition_id}", json=updated_payload)
    assert updated.status_code == 200
    assert updated.json()["name"] == "Monthly close updated"
    assert updated.json()["mode"] == "range"

    published = desktop_api_client.post(f"/api/compositions/{composition_id}/publish")
    assert published.status_code == 200
    assert published.json()["status"] == "published"

    SkillCompositionRepository().mark_needs_review_by_tool("tool_a")
    listed = desktop_api_client.get("/api/compositions")
    assert listed.status_code == 200
    item = listed.json()["items"][0]
    assert item["needsReview"] is True
    assert item["status"] == "published"
    assert item["displayStatus"] == "needs_review"


def test_composition_create_rejects_empty_members_at_api_boundary(desktop_api_client):
    payload = composition_payload()
    payload["members"] = []

    response = desktop_api_client.post("/api/compositions", json=payload)

    assert response.status_code == 422


class FakeCompositionAdapter:
    def generate_applicability(self, payload):
        assert payload["name"] == "Draft"
        return "Use for draft workflows."

    def recommend_order(self, payload):
        assert payload["members"][0]["toolId"] == "tool_a"
        return {
            "members": [{"toolId": "tool_a", "executionOrder": 1}],
            "reason": "Only one member.",
        }

    def start_trial(self, composition_id: str):
        return {
            "accepted": True,
            "compositionId": composition_id,
            "name": "Draft",
            "sessionId": "sess_1",
        }


def test_composition_ai_helpers_and_trial_are_routed_through_adapter(desktop_api_client):
    desktop_api_client.app.dependency_overrides[compositions_router.get_composition_adapter] = (
        lambda: FakeCompositionAdapter()
    )
    try:
        applicability = desktop_api_client.post(
            "/api/compositions/comp_1/generate-applicability",
            json={
                "name": "Draft",
                "description": "",
                "mode": "range",
                "members": [{"toolId": "tool_a", "selectedOrder": 1}],
            },
        )
        order = desktop_api_client.post(
            "/api/compositions/comp_1/recommend-order",
            json={
                "name": "Draft",
                "description": "",
                "mode": "ordered",
                "applicability": "Use for draft workflows.",
                "members": [{"toolId": "tool_a", "selectedOrder": 1, "executionOrder": 1}],
            },
        )
        trial = desktop_api_client.post("/api/compositions/comp_1/trial", json={"task": "try it"})
    finally:
        desktop_api_client.app.dependency_overrides.clear()

    assert applicability.status_code == 200
    assert applicability.json()["applicability"] == "Use for draft workflows."
    assert order.status_code == 200
    assert order.json()["members"] == [{"toolId": "tool_a", "executionOrder": 1}]
    assert trial.status_code == 200
    assert trial.json()["sessionId"] == "sess_1"
