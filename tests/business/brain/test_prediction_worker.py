"""
US4: Prediction generation and verification worker tests.
"""

from unittest.mock import MagicMock

from src.business.ai.llm_client import LLMResponse, ToolCallInfo
from src.business.brain.models import Zone
from src.utils.events import clear_all


def teardown_function():
    clear_all()


class _MockLLM:
    def __init__(self, responses):
        self._responses = iter(responses)

    def chat_with_tools(self, *args, **kwargs):
        return next(self._responses)

    def chat(self, prompt: str):
        return next(self._responses)


def test_generate_predictions_writes_prediction_entries():
    from src.business.brain.prediction_service import PredictionService
    from src.data.repos.brain_repository import BrainRepository

    repo = BrainRepository()
    repo.create_entry(
        zone=Zone.HOT.value,
        content="用户最近多次提到预算审核",
        origin="distillation",
        reason="近期重复话题",
    )
    llm = _MockLLM(
        [
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallInfo(
                        id="pred-1",
                        name="prediction_generation_output",
                        args={
                            "prediction_zone": [
                                {
                                    "content": "用户下次可能继续询问预算审核。",
                                    "verification_checkpoint": "下次对话时",
                                    "reason": "预算审核最近反复出现",
                                }
                            ]
                        },
                    )
                ],
            )
        ]
    )

    created = PredictionService(repo=repo).generate_predictions(llm)

    assert len(created) == 1
    entry = repo.get_entry(created[0])
    assert entry.zone == Zone.PREDICTION.value
    assert entry.verification_checkpoint == "下次对话时"


def test_verify_predictions_updates_status_and_rationale():
    from src.business.brain.prediction_service import PredictionService
    from src.data.repos.brain_repository import BrainRepository

    repo = BrainRepository()
    entry_id = repo.create_prediction_entry(
        content="用户下次可能继续询问预算审核。",
        reason="预算审核最近反复出现",
        verification_checkpoint="下次对话时",
    )
    llm = _MockLLM(["hit: 用户确实再次询问了预算审核。"])

    count = PredictionService(repo=repo).verify_predictions(llm)

    entry = repo.get_entry(entry_id)
    assert count == 1
    assert entry.verification_status == "hit"
    assert "预算审核" in entry.verification_rationale


def test_verify_predictions_skips_future_iso_checkpoint():
    from src.business.brain.prediction_service import PredictionService
    from src.data.repos.brain_repository import BrainRepository

    repo = BrainRepository()
    entry_id = repo.create_prediction_entry(
        content="用户未来会继续预算审核。",
        reason="预算审核最近反复出现",
        verification_checkpoint="2999-01-01T00:00:00+00:00",
    )
    llm = MagicMock()

    count = PredictionService(repo=repo).verify_predictions(llm)

    assert count == 0
    assert repo.get_entry(entry_id).verification_status is None
    llm.chat.assert_not_called()


def test_verify_predictions_uses_distilled_memory_evidence():
    from src.business.brain.prediction_service import PredictionService
    from src.data.repos.brain_repository import BrainRepository

    repo = BrainRepository()
    prediction_id = repo.create_prediction_entry(
        content="用户下次可能继续询问预算审核。",
        reason="预算审核最近反复出现",
        verification_checkpoint="下次对话时",
    )
    repo.create_entry(
        zone=Zone.HOT.value,
        content="用户再次询问了预算审核。",
        origin="distillation",
        reason="验证期内发生的事件",
    )
    llm = MagicMock()
    llm.chat.return_value = "hit: 证据显示用户再次询问预算审核。"

    count = PredictionService(repo=repo).verify_predictions(llm)

    assert count == 1
    assert "用户再次询问了预算审核" in llm.chat.call_args.args[0]
    assert repo.get_entry(prediction_id).verification_status == "hit"


def test_verify_predictions_expires_after_failed_retry_budget():
    from src.business.brain.prediction_service import PredictionService
    from src.data.repos.brain_repository import BrainRepository

    repo = BrainRepository()
    entry_id = repo.create_prediction_entry(
        content="用户下次可能继续询问预算审核。",
        reason="预算审核最近反复出现",
        verification_checkpoint="下次对话时",
    )
    config = MagicMock()
    config.get_brain_worker_prediction_verification_retries.return_value = 1
    llm = MagicMock()
    llm.chat.side_effect = RuntimeError("timeout")

    count = PredictionService(repo=repo, config=config).verify_predictions(llm)

    entry = repo.get_entry(entry_id)
    assert count == 1
    assert entry.verification_status == "expired"
    assert "could not be assessed" in entry.verification_rationale


def test_background_worker_schedules_prediction_jobs():
    from src.business.brain.background_worker import BrainBackgroundWorker

    prediction_service = MagicMock()
    prediction_service.generate_predictions.return_value = ["prediction-1"]
    prediction_service.verify_predictions.return_value = 1
    llm = object()

    worker = BrainBackgroundWorker(prediction_service=prediction_service, llm_client=llm)
    worker._run_prediction_jobs()

    prediction_service.generate_predictions.assert_called_once_with(llm)
    prediction_service.verify_predictions.assert_called_once_with(llm)


def test_subconscious_distillation_writes_entries():
    from src.business.brain.distillation_service import DistillationService
    from src.data.repos.brain_repository import BrainRepository

    repo = BrainRepository()
    repo.create_entry(
        zone=Zone.HOT.value,
        content="用户多次要求先给结论再展开。",
        origin="distillation",
        reason="近期重复表达",
    )
    llm = _MockLLM(
        [
            LLMResponse(
                content=None,
                tool_calls=[
                    ToolCallInfo(
                        id="sub-1",
                        name="subconscious_distillation_output",
                        args={
                            "subconscious_zone": [
                                {
                                    "content": "用户偏好先结论后细节。",
                                    "reason": "多次要求先给结论",
                                    "scope": "沟通风格",
                                }
                            ]
                        },
                    )
                ],
            )
        ]
    )

    count = DistillationService(repo=repo).run_subconscious_distillation(llm)
    entries = repo.get_entries_by_zone(Zone.SUBCONSCIOUS.value, status="active")

    assert count == 1
    assert entries[0].content == "用户偏好先结论后细节。"


def test_invalidation_review_degrades_invalidated_entries():
    from src.business.brain.background_worker import BrainBackgroundWorker
    from src.data.repos.brain_repository import BrainRepository

    repo = BrainRepository()
    entry_id = repo.create_entry(
        zone=Zone.ARCHIVE.value,
        content="旧预算假设",
        origin="distillation",
        reason="测试",
        relevance_score=1.0,
    )
    repo.update_entry_status(entry_id, "invalidated")

    BrainBackgroundWorker()._run_invalidation_review()

    entry = repo.get_entry(entry_id)
    assert entry.status == "invalidated"
    assert entry.relevance_score < 1.0


def test_background_worker_keeps_pending_segments_when_llm_unavailable(in_memory_db):
    from src.business.brain.background_worker import BrainBackgroundWorker
    from src.data.repos.brain_repository import BrainRepository

    repo = BrainRepository()
    segment_id = repo.create_segment(
        session_id="sess-pending",
        boundary_reason="idle",
        message_id_start="msg-1",
        message_id_end="msg-2",
    )
    distillation_service = MagicMock()

    worker = BrainBackgroundWorker(distillation_service=distillation_service)
    worker._get_llm_client = MagicMock(return_value=None)
    worker._process_pending_segments()

    assert BrainRepository().get_segment_by_id(segment_id).status == "pending"
    distillation_service.distill_segment.assert_not_called()
