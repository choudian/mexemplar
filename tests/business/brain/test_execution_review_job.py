from __future__ import annotations

from src.business.brain.background_worker import BrainBackgroundWorker
from src.data.repos.execution_review_repository import ExecutionReviewRepository


class _Config:
    def get_self_improvement_execution_review_enabled(self) -> bool:
        return True

    def get_self_improvement_proposals_enabled(self) -> bool:
        return False


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


def test_proposal_generation_failure_does_not_break_review(in_memory_db, monkeypatch):
    """提案生成抛异常时，复盘仍应正确写回（生成失败不阻塞复盘写回）。"""
    from src.business.self_improvement import proposal_service as proposal_service_module

    class _BoomProposalService:
        def __init__(self, *args, **kwargs):
            pass

        def generate_from_review(self, *args, **kwargs):
            raise RuntimeError("proposal boom")

    monkeypatch.setattr(proposal_service_module, "ProposalService", _BoomProposalService)

    class _EnabledConfig:
        def get_self_improvement_execution_review_enabled(self) -> bool:
            return True

        def get_self_improvement_proposals_enabled(self) -> bool:
            return True

    repo = ExecutionReviewRepository()
    review_id = repo.enqueue("ast_y", priority=1)
    repo.close()

    worker = BrainBackgroundWorker(
        config=_EnabledConfig(),
        execution_review_service=_Service(),
        execution_review_llm_client=_LLM(),
    )
    worker._run_execution_review()

    repo = ExecutionReviewRepository()
    recent = repo.list_recent(10)
    repo.close()

    assert recent[0].id == review_id
    assert recent[0].verdict == "重复抓取"


def test_proposal_generation_retry_scan_recovers_after_transient_failure(
    in_memory_db,
    monkeypatch,
):
    """提案生成旁路失败后，下一轮 worker 会幂等重扫 completed review 补生成。"""
    from src.business.self_improvement import proposal_service as proposal_service_module
    from src.business.self_improvement.proposal_service import ProposalService

    class _WorthChangingService:
        def review(self, skeleton, llm_client):
            return {
                "verdict": "重复抓取",
                "findings": [
                    {
                        "type": "效率",
                        "what": "重试补生成",
                        "evidence": "第一次 proposal service 短暂失败",
                        "severity": "med",
                        "suggestion": "后台重扫",
                        "worth_changing": True,
                    }
                ],
                "advisory": True,
            }

    class _BoomProposalService:
        def generate_from_review(self, *args, **kwargs):
            raise RuntimeError("proposal boom")

    class _EnabledConfig:
        def get_self_improvement_execution_review_enabled(self) -> bool:
            return True

        def get_self_improvement_proposals_enabled(self) -> bool:
            return True

    monkeypatch.setattr(proposal_service_module, "ProposalService", _BoomProposalService)

    repo = ExecutionReviewRepository()
    review_id = repo.enqueue("ast_retry", priority=1)
    repo.close()

    worker = BrainBackgroundWorker(
        config=_EnabledConfig(),
        execution_review_service=_WorthChangingService(),
        execution_review_llm_client=_LLM(),
    )
    worker._run_execution_review()
    assert ProposalService().list_proposals() == []

    monkeypatch.setattr(proposal_service_module, "ProposalService", ProposalService)
    worker._run_execution_review()

    proposals = ProposalService().list_proposals()
    assert len(proposals) == 1
    assert proposals[0]["sourceReviewId"] == review_id
    assert proposals[0]["what"] == "重试补生成"


def test_retry_scan_short_circuits_when_proposals_disabled(in_memory_db, monkeypatch):
    """proposals.enabled=False 时 retry scan 必须在 list_recent 之前短路,不触库不生成。

    026 review CG-4:enabled 开关是 proposal 旁路的总门;关闭时 retry scan 不得做任何
    DB 工作或调 ProposalService(否则与用户"关闭自我改进"的意图相悖)。
    """
    from src.business.brain.background_worker import BrainBackgroundWorker
    from src.data.repos.execution_review_repository import ExecutionReviewRepository

    class _DisabledConfig:
        def get_self_improvement_proposals_enabled(self) -> bool:
            return False

    calls = {"list_recent": 0}
    original_list_recent = ExecutionReviewRepository.list_recent

    def _tracking_list_recent(self, limit):
        calls["list_recent"] += 1
        return original_list_recent(self, limit)

    monkeypatch.setattr(ExecutionReviewRepository, "list_recent", _tracking_list_recent)

    worker = BrainBackgroundWorker(config=_DisabledConfig())
    worker._retry_missing_proposals_for_recent_reviews()

    assert calls["list_recent"] == 0, "proposals.enabled=False 必须在 list_recent 前短路"


def test_review_wiring_generates_proposal_for_worth_changing_finding(in_memory_db):
    """真实接线契约（不 mock ProposalService）：复盘 worth_changing finding → 生成 pending_review 提案。

    回归 C1：``_maybe_generate_proposals`` 必须把已解析的 findings list 原样传给
    ``generate_from_review``。若多余地 ``json.dumps`` 成 str，``enumerate(str)`` 取到字符
    调 ``.get`` 抛 ``AttributeError``，被旁路 except 吞成 ERROR，提案永不生成——US1 MVP
    核心功能静默失效。此测试在 C1 修复前应失败（0 提案），修复后通过。
    """
    from src.business.self_improvement.proposal_service import ProposalService

    class _WorthChangingService:
        def review(self, skeleton, llm_client):
            return {
                "verdict": "重复抓取",
                "findings": [
                    {
                        "type": "效率",
                        "what": "重复抓取",
                        "evidence": "两次同一URL",
                        "severity": "med",
                        "suggestion": "加缓存",
                        "worth_changing": True,
                    }
                ],
                "advisory": True,
            }

    class _EnabledConfig:
        def get_self_improvement_execution_review_enabled(self) -> bool:
            return True

        def get_self_improvement_proposals_enabled(self) -> bool:
            return True

    repo = ExecutionReviewRepository()
    review_id = repo.enqueue("ast_wiring", priority=1)
    repo.close()

    worker = BrainBackgroundWorker(
        config=_EnabledConfig(),
        execution_review_service=_WorthChangingService(),
        execution_review_llm_client=_LLM(),
    )
    worker._run_execution_review()

    # 复盘写回正常（生成成功/失败都不应阻塞复盘）
    repo = ExecutionReviewRepository()
    recent = repo.list_recent(10)
    repo.close()
    assert recent[0].id == review_id

    # 真实接线：worth_changing finding 已落成 pending_review 提案（C1 修复前这里为 0）
    proposals = ProposalService().list_proposals()
    assert len(proposals) == 1
    assert proposals[0]["status"] == "pending_review"
    assert proposals[0]["sourceReviewId"] == review_id
    assert proposals[0]["what"] == "重复抓取"
