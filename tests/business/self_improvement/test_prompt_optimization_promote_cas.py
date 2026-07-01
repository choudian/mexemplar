"""prompt_optimization_service promote CAS 失败处理（026 I7 follow-up）。

promote_supplement 在 CAS 失败（candidate 评估期间被 retract/并发改）时返回 None。
evaluate_candidates 必须判 None，不得假成功（append promoted + audit 误报）。
"""

from unittest.mock import MagicMock

from src.business.self_improvement.prompt_optimization_service import (
    PromptOptimizationService,
)
from src.data.repos.self_improvement_repository import SelfImprovementRepository


def test_evaluate_candidates_skips_promote_when_cas_lost(in_memory_db, monkeypatch) -> None:
    with SelfImprovementRepository() as repo:
        repo.create_supplement("sec", "content", "rationale", None, "hash_cand")

        service = PromptOptimizationService(
            si_repo=repo,
            tracker=MagicMock(),
            audit_service=MagicMock(),
            safety_governor=MagicMock(),
        )
        service._tracker.get_effectiveness_for_prompt.return_value = 0.8
        # 模拟 promote CAS 失败（返回 None）
        monkeypatch.setattr(repo, "promote_supplement", lambda *a, **kw: None)

        promoted = service.evaluate_candidates()

    assert promoted == []
    service._audit.log_action.assert_not_called()
