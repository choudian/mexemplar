from __future__ import annotations

from src.business.brain.background_worker import BrainBackgroundWorker
from src.data.repos.execution_review_repository import ExecutionReviewRepository


class _Config:
    def get_self_improvement_execution_review_enabled(self) -> bool:
        return True


class _LLM:
    model = "review-model"


class _Service:
    def review(self, skeleton, llm_client):
        return {
            "verdict": "重复抓取",
            "findings": [{"type": "效率", "what": "重复抓取"}],
            "advisory": True,
        }


def test_job_processes_pending_review(in_memory_db):
    repo = ExecutionReviewRepository()
    review_id = repo.enqueue("ast_x", priority=1)
    repo.close()

    worker = BrainBackgroundWorker(
        config=_Config(),
        execution_review_service=_Service(),
        execution_review_llm_client=_LLM(),
    )
    worker._run_execution_review()

    repo = ExecutionReviewRepository()
    recent = repo.list_recent(10)
    repo.close()

    assert recent[0].id == review_id
    assert recent[0].verdict == "重复抓取"
