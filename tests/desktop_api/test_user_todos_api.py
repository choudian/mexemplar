from __future__ import annotations


def test_user_todo_crud_api(desktop_api_client) -> None:
    created = desktop_api_client.post(
        "/api/user-todos",
        json={"title": "准备会议", "description": "整理议程", "priority": "high"},
    )
    assert created.status_code == 200
    todo_id = created.json()["todoId"]

    listed = desktop_api_client.get("/api/user-todos?status=open&sort=priority_desc")
    updated = desktop_api_client.put(
        f"/api/user-todos/{todo_id}",
        json={"status": "in_progress", "priority": "urgent"},
    )
    completed = desktop_api_client.post(f"/api/user-todos/{todo_id}/complete", json={"done": True})
    deleted = desktop_api_client.delete(f"/api/user-todos/{todo_id}")
    missing = desktop_api_client.put(f"/api/user-todos/{todo_id}", json={"title": "不存在"})

    assert listed.status_code == 200
    assert listed.json()["items"][0]["todoId"] == todo_id
    assert updated.status_code == 200
    assert updated.json()["status"] == "in_progress"
    assert updated.json()["priority"] == "urgent"
    assert completed.status_code == 200
    assert completed.json()["completedAt"] is not None
    assert deleted.status_code == 204
    assert missing.status_code == 404


def test_user_todo_api_rejects_blank_title(desktop_api_client) -> None:
    response = desktop_api_client.post("/api/user-todos", json={"title": "   "})

    assert response.status_code == 422
