from __future__ import annotations

from src.data.models_sqlite import TeachingFailureRecord, Tool
from src.data.repositories import TeachingFailureRepository, ToolRepository
from src.desktop_api.routers import skills as skills_router


def seed_tool(tool_id: str, name: str, status: str, source: str = "intent") -> None:
    ToolRepository().create(
        Tool(
            tool_id=tool_id,
            tool_name=name,
            description=f"{name} description",
            source=source,
            status=status,
            workflow_id=f"wf_{tool_id}",
            trial_success_count=1 if status == "published" else 0,
        )
    )


def test_skills_categories_metadata_trial_and_delete(desktop_api_client):
    seed_tool("tool_pending", "Pending Skill", "pending")
    seed_tool("tool_published", "Published Skill", "published")
    trial_calls: list[tuple[str, str]] = []

    class FakeRuntime:
        def start_tool_trial(self, tool_id: str, workflow_id: str) -> bool:
            trial_calls.append((tool_id, workflow_id))
            return True

        def continue_tool_trial(self, workflow_id: str, content: str) -> bool:
            return True

        def get_trial_history(self, workflow_id: str) -> list[dict]:
            return []

        def retry_teaching_failure(self, workflow_id: str) -> bool:
            return True

    desktop_api_client.app.dependency_overrides[skills_router.get_desktop_agent_runtime] = (
        lambda: FakeRuntime()
    )

    try:
        pending = desktop_api_client.get("/api/skills?category=pending")
        assert pending.status_code == 200
        assert pending.json()["items"][0]["name"] == "Pending Skill"

        published = desktop_api_client.get("/api/skills?category=published")
        assert published.status_code == 200
        published_items = published.json()["items"]
        assert published_items[0]["toolId"] == "web_search"
        assert published_items[0]["is_builtin"] is True
        assert any(item["toolId"] == "tool_published" for item in published_items)

        trial = desktop_api_client.post("/api/skills/tool_published/trial")
        assert trial.status_code == 200
        assert trial.json()["workflowId"] == "wf_tool_published"
    finally:
        desktop_api_client.app.dependency_overrides.clear()
    assert trial_calls == [("tool_published", "wf_tool_published")]

    updated = desktop_api_client.patch(
        "/api/skills/tool_published",
        json={"name": "Updated Skill", "description": "New description"},
    )
    assert updated.status_code == 200
    assert ToolRepository().get_by_id("tool_published").tool_name == "Updated Skill"

    deleted = desktop_api_client.delete("/api/skills/tool_published")
    assert deleted.status_code == 200
    assert ToolRepository().get_by_id("tool_published") is None


def test_failure_retry_and_dismiss(desktop_api_client):
    retry_calls: list[str] = []

    class FakeRuntime:
        def start_tool_trial(self, tool_id: str, workflow_id: str) -> bool:
            return True

        def continue_tool_trial(self, workflow_id: str, content: str) -> bool:
            return True

        def get_trial_history(self, workflow_id: str) -> list[dict]:
            return []

        def retry_teaching_failure(self, workflow_id: str) -> bool:
            retry_calls.append(workflow_id)
            return True

    desktop_api_client.app.dependency_overrides[skills_router.get_desktop_agent_runtime] = (
        lambda: FakeRuntime()
    )
    TeachingFailureRepository().create(
        TeachingFailureRecord(
            record_id="failure_1",
            workflow_id="wf_failure",
            tool_name="Broken Skill",
            failed_stage="programmer",
            error_summary="syntax error",
            error_type="syntax",
            status="active",
        )
    )

    try:
        failed = desktop_api_client.get("/api/skills?category=failed")
        assert failed.status_code == 200
        assert failed.json()["items"][0]["workflowId"] == "wf_failure"

        retry = desktop_api_client.post("/api/skills/failures/wf_failure/retry")
        assert retry.status_code == 200
        assert retry_calls == ["wf_failure"]
        assert TeachingFailureRepository().get_by_workflow_id("wf_failure").status == "active"

        dismiss = desktop_api_client.post("/api/skills/failures/wf_failure/dismiss")
        assert dismiss.status_code == 200
        assert TeachingFailureRepository().get_by_workflow_id("wf_failure").status == "dismissed"
    finally:
        desktop_api_client.app.dependency_overrides.clear()
