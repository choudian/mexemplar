from __future__ import annotations

from src.data.repos.execution_review_repository import ExecutionReviewRepository


def test_list_execution_reviews(desktop_api_client, in_memory_db):
    repo = ExecutionReviewRepository()
    review_id = repo.enqueue("ast_x", priority=1)
    repo.claim_pending(1)
    repo.save_result(
        review_id,
        verdict="重复抓取",
        findings=[{"type": "效率", "what": "同一 URL 重复抓取"}],
        model_used="review-model",
    )
    repo.close()

    response = desktop_api_client.get("/api/execution-reviews?limit=10")

    assert response.status_code == 200
    data = response.json()
    assert data["reviews"][0]["id"] == review_id
    assert data["reviews"][0]["verdict"] == "重复抓取"
