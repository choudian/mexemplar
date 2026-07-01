"""
US4: Prediction generation and verification worker tests.
"""

import threading
from unittest.mock import MagicMock

import pytest

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


def _prediction_response(content: str) -> "LLMResponse":
    return LLMResponse(
        content=None,
        tool_calls=[
            ToolCallInfo(
                id="pred",
                name="prediction_generation_output",
                args={
                    "prediction_zone": [
                        {
                            "content": content,
                            "verification_checkpoint": "下次对话时",
                            "reason": "预算审核最近反复出现",
                        }
                    ]
                },
            )
        ],
    )


def _completed_segment_with_hot(repo, segment_id: str, content: str) -> str:
    """创建一个 completed Segment 并写入一条 active hot 条目（带 source_segment_id），
    模拟一次真实蒸馏的产出，用于驱动按段身份去重的 prediction/subconscious 任务。"""
    seg = repo.create_segment(
        session_id="sess-dedup",
        boundary_reason="idle",
        message_id_start="m1",
        message_id_end="m2",
        segment_id=segment_id,
    )
    sid = str(seg)
    repo.transition_segment(sid, from_status="pending", to_status="distilling")
    repo.complete_segment_with_entries(
        sid,
        [
            {
                "zone": Zone.HOT.value,
                "content": content,
                "reason": "近期重复话题",
                "origin": "distillation",
                "entry_type": "event",
                "source_segment_id": sid,
            }
        ],
    )
    return sid


def test_generate_predictions_skips_when_segment_already_processed():
    from src.business.brain.prediction_service import PredictionService
    from src.data.repos.brain_repository import BrainRepository

    repo = BrainRepository()
    _completed_segment_with_hot(repo, "seg-1", "用户最近多次提到预算审核")
    service = PredictionService(repo=repo)

    first = service.generate_predictions(_MockLLM([_prediction_response("第一次猜测")]))
    assert len(first) == 1
    assert repo.get_entry(first[0]).source_segment_id == "seg-1"

    guard_llm = MagicMock()
    assert service.generate_predictions(guard_llm) == []
    guard_llm.chat_with_tools.assert_not_called()


def test_generate_predictions_runs_again_after_new_segment():
    from src.business.brain.prediction_service import PredictionService
    from src.data.repos.brain_repository import BrainRepository

    repo = BrainRepository()
    _completed_segment_with_hot(repo, "seg-1", "用户最近多次提到预算审核")
    service = PredictionService(repo=repo)

    first = service.generate_predictions(_MockLLM([_prediction_response("第一次猜测")]))
    assert len(first) == 1

    # 新完成的 Segment 带来新的 hot 材料 → 段标记前移，应再次生成。
    _completed_segment_with_hot(repo, "seg-2", "用户开始关注季度报表")

    second = service.generate_predictions(_MockLLM([_prediction_response("第二次猜测")]))
    assert len(second) == 1
    assert repo.get_entry(second[0]).source_segment_id == "seg-2"


def test_generate_predictions_runs_without_segment_info():
    """没有任何带 source_segment_id 的蒸馏条目时（如裸 hot 条目）保守运行，绝不漏蒸馏。"""
    from src.business.brain.prediction_service import PredictionService
    from src.data.repos.brain_repository import BrainRepository

    repo = BrainRepository()
    repo.create_entry(
        zone=Zone.HOT.value,
        content="用户最近多次提到预算审核",
        origin="distillation",
        reason="近期重复话题",
    )
    service = PredictionService(repo=repo)

    created = service.generate_predictions(_MockLLM([_prediction_response("猜测")]))
    assert len(created) == 1


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
    assert entry.status == "fading"
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
    verified = repo.get_entry(prediction_id)
    assert verified.verification_status == "hit"
    assert verified.status == "fading"


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
    assert entry.status == "fading"
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


def test_prediction_verification_is_skipped_when_generation_fails():
    from src.business.brain.background_worker import BrainBackgroundWorker

    prediction_service = MagicMock()
    prediction_service.generate_predictions.side_effect = RuntimeError("bad generation")
    prediction_service.verify_predictions.return_value = 1
    llm = object()

    worker = BrainBackgroundWorker(prediction_service=prediction_service, llm_client=llm)

    with pytest.raises(RuntimeError, match="prediction jobs failed"):
        worker._run_prediction_jobs()

    prediction_service.generate_predictions.assert_called_once_with(llm)
    prediction_service.verify_predictions.assert_not_called()


def test_prediction_job_error_message_includes_failure_detail():
    from src.business.brain.background_worker import BrainBackgroundWorker

    prediction_service = MagicMock()
    prediction_service.generate_predictions.return_value = []
    prediction_service.verify_predictions.side_effect = RuntimeError("bad verification")
    llm = object()

    worker = BrainBackgroundWorker(prediction_service=prediction_service, llm_client=llm)

    with pytest.raises(RuntimeError, match="RuntimeError: bad verification"):
        worker._run_prediction_jobs()


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


def _subconscious_response(content: str) -> "LLMResponse":
    return LLMResponse(
        content=None,
        tool_calls=[
            ToolCallInfo(
                id="sub",
                name="subconscious_distillation_output",
                args={
                    "subconscious_zone": [
                        {
                            "content": content,
                            "reason": "多次要求先给结论",
                            "scope": "沟通风格",
                        }
                    ]
                },
            )
        ],
    )


def test_subconscious_distillation_skips_when_segment_already_processed():
    from src.business.brain.distillation_service import DistillationService
    from src.data.repos.brain_repository import BrainRepository

    repo = BrainRepository()
    _completed_segment_with_hot(repo, "seg-1", "用户多次要求先给结论再展开。")
    service = DistillationService(repo=repo)

    assert (
        service.run_subconscious_distillation(_MockLLM([_subconscious_response("先结论后细节")]))
        == 1
    )
    produced = repo.get_entries_by_zone(Zone.SUBCONSCIOUS.value, status="active")
    assert produced[0].source_segment_id == "seg-1"

    guard_llm = MagicMock()
    assert service.run_subconscious_distillation(guard_llm) == 0
    guard_llm.chat_with_tools.assert_not_called()


def test_subconscious_distillation_runs_again_after_new_segment():
    from src.business.brain.distillation_service import DistillationService
    from src.data.repos.brain_repository import BrainRepository

    repo = BrainRepository()
    _completed_segment_with_hot(repo, "seg-1", "用户多次要求先给结论再展开。")
    service = DistillationService(repo=repo)

    assert (
        service.run_subconscious_distillation(_MockLLM([_subconscious_response("先结论后细节")]))
        == 1
    )

    _completed_segment_with_hot(repo, "seg-2", "用户开始强调可执行步骤。")

    assert (
        service.run_subconscious_distillation(_MockLLM([_subconscious_response("强调步骤")])) == 1
    )


def test_subconscious_distillation_rolls_back_partial_batch(monkeypatch):
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
                                },
                                {
                                    "content": "用户偏好短句。",
                                    "reason": "多次要求简洁",
                                },
                            ]
                        },
                    )
                ],
            )
        ]
    )
    original_create_entry = repo.create_entry
    calls = 0

    def failing_create_entry(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("insert failed")
        return original_create_entry(*args, **kwargs)

    monkeypatch.setattr(repo, "create_entry", failing_create_entry)

    with pytest.raises(RuntimeError, match="insert failed"):
        DistillationService(repo=repo).run_subconscious_distillation(llm)

    assert repo.get_entries_by_zone(Zone.SUBCONSCIOUS.value, status="active") == []


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


def test_background_worker_unhandled_distillation_failure_consumes_retry_budget(in_memory_db):
    from src.business.brain.background_worker import BrainBackgroundWorker
    from src.data.repos.brain_repository import BrainRepository

    repo = BrainRepository()
    segment_id = repo.create_segment(
        session_id="sess-retry",
        boundary_reason="idle",
        message_id_start="msg-1",
        message_id_end="msg-2",
    )
    config = MagicMock()
    config.get_brain_segment_max_distillation_retries.return_value = 2
    distillation_service = MagicMock()
    distillation_service.distill_segment.side_effect = RuntimeError("provider failed")
    worker = BrainBackgroundWorker(
        config=config,
        distillation_service=distillation_service,
        llm_client=object(),
    )

    worker._process_pending_segments()
    after_first = BrainRepository().get_segment_by_id(segment_id)
    assert after_first.status == "pending"
    assert after_first.retry_count == 1

    worker._process_pending_segments()
    after_second = BrainRepository().get_segment_by_id(segment_id)
    assert after_second.status == "failed"


def test_background_worker_recover_crashed_segments_resets_distilling_segments(in_memory_db):
    from datetime import timedelta

    from src.business.brain.background_worker import BrainBackgroundWorker
    from src.business.brain.models import SegmentStatus
    from src.data.repos.brain_repository import BrainRepository
    from src.utils.timezone import utc_now_naive

    class _FastConfig:
        # tick_interval=20s → threshold=max(60,60)=60s，远低于 2 小时，确保恢复触发
        def get_brain_worker_tick_interval(self) -> float:
            return 20.0

    repo = BrainRepository()
    segment_id = repo.create_segment(
        session_id="sess-crashed",
        boundary_reason="idle",
        message_id_start="msg-1",
        message_id_end="msg-2",
    )
    assert repo.transition_segment_status(
        segment_id,
        from_status=SegmentStatus.PENDING.value,
        to_status=SegmentStatus.DISTILLING.value,
    )
    # 手动将 distilling_started_at 设为 2 小时前，使其超过崩溃恢复阈值
    seg = repo.get_segment_by_id(segment_id)
    seg.distilling_started_at = utc_now_naive() - timedelta(hours=2)
    repo.session.commit()

    BrainBackgroundWorker(config=_FastConfig())._recover_crashed_segments()

    assert BrainRepository().get_segment_by_id(segment_id).status == SegmentStatus.PENDING.value


def test_background_worker_initializes_consecutive_tick_errors():
    from src.business.brain.background_worker import BrainBackgroundWorker

    assert BrainBackgroundWorker()._consecutive_tick_errors == 0


def test_background_worker_does_not_restart_before_stopping_thread_exits():
    from src.business.brain.background_worker import BrainBackgroundWorker

    config = MagicMock()
    config.get_brain_worker_tick_interval.return_value = 60
    entered = threading.Event()
    release = threading.Event()
    first = BrainBackgroundWorker(config=config)

    def block_first_tick():
        entered.set()
        release.wait(timeout=2)

    first._process_pending_segments = block_first_tick
    for method_name in (
        "_recover_crashed_segments",
        "_run_decay_sweep",
        "_run_archive_layering",
        "_run_prediction_jobs",
        "_run_subconscious_distillation",
        "_run_invalidation_review",
        "_run_recruitment_scan",
        "_run_execution_review",
    ):
        setattr(first, method_name, MagicMock())

    first.start()
    assert entered.wait(timeout=1)
    stopper = threading.Thread(target=first.stop)
    stopper.start()
    assert first._stop_event.wait(timeout=1)

    second = BrainBackgroundWorker(config=config)
    second.start()
    assert second._thread is None

    release.set()
    stopper.join(timeout=2)
    assert not stopper.is_alive()
