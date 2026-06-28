from __future__ import annotations

from src.data.repos.execution_review_repository import ExecutionReviewRepository


def test_enqueue_claim_save_roundtrip(in_memory_db):
    with in_memory_db.get_session() as session:
        repo = ExecutionReviewRepository(session=session)
        review_id = repo.enqueue("ast_x", priority=5)

        claimed = repo.claim_pending(limit=10)
        assert [item.id for item in claimed] == [review_id]
        assert claimed[0].status == "in_progress"
        assert repo.claim_pending(limit=10) == []

        repo.save_result(
            review_id,
            verdict="重复抓取",
            findings=[{"type": "效率", "what": "同一 URL 两次抓取"}],
            model_used="review-model",
        )

        recent = repo.list_recent(limit=10)
        assert recent[0].id == review_id
        assert recent[0].verdict == "重复抓取"
        assert recent[0].status == "completed"
        assert repo.count_session_today("ast_x") == 1
