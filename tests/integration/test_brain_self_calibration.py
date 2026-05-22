"""
US4 integration: failure retrieval, prediction verification, and invalidation.
"""

from src.business.brain.models import Zone
from src.utils.events import clear_all


def teardown_function():
    clear_all()


def test_failure_retrieval_prediction_verification_and_invalidation_flow():
    from src.business.brain.prediction_service import PredictionService
    from src.business.brain.retrieval_service import RetrievalService
    from src.data.repos.brain_repository import BrainRepository

    repo = BrainRepository()
    failure_id = repo.create_entry(
        zone=Zone.FAILURE.value,
        content="直接删除预算配置曾导致恢复失败，必须先备份。",
        origin="distillation",
        reason="用户纠正过类似操作",
    )
    prediction_id = repo.create_prediction_entry(
        content="用户下次可能继续询问预算审核。",
        reason="预算审核最近反复出现",
        verification_checkpoint="下次对话时",
    )

    retrieval = RetrievalService(brain_repo=repo)
    failures = retrieval.retrieve_failure_zone("预算 配置")
    invalidation = retrieval.invalidate_memory_entry(
        failure_id,
        "用户确认这条避坑记忆过时",
        current_context_entry_ids=[failure_id],
    )

    class LLM:
        def chat(self, prompt: str):
            return "partial: 用户只询问了预算，但不是审核。"

    verified = PredictionService(repo=repo).verify_predictions(LLM())

    assert failures[0]["entry_id"] == failure_id
    assert invalidation["success"] is True
    assert repo.get_entry(failure_id).status == "invalidated"
    assert verified == 1
    assert repo.get_entry(prediction_id).verification_status == "partial"
