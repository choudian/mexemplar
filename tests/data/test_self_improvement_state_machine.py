"""ToolFixProposal / ToolGapReport 状态机 from-status 守卫（026 类型审查 I1）。

修复前 ``transition_fix_proposal`` / ``resolve_gap_report`` / ``fail_gap_report``
接受任意 ``new_status`` 直接赋值，可从终态或非法源跳转，与同 feature
``ImprovementProposalRepository._cas_transition`` 的严谨 CAS 不一致。修复后用
条件 UPDATE + 合法源集合：非法转换返回 None 且不改变持久状态。
"""

from __future__ import annotations

from src.data.models_sqlite import ToolFixProposal, ToolGapReport
from src.data.repos.self_improvement_repository import SelfImprovementRepository


def _make_fix_proposal(repo: SelfImprovementRepository, *, tool_id: str = "t1") -> ToolFixProposal:
    return repo.create_fix_proposal(
        tool_id=tool_id,
        gap_report_id=None,
        proposed_code="def f(): pass",
        rationale="r",
        before_code=None,
    )


def _make_gap_report(
    repo: SelfImprovementRepository, *, signature: str = "bug:t:abc"
) -> ToolGapReport:
    return repo.create_gap_report(
        gap_type="bug_pattern",
        tool_name="t",
        pattern_signature=signature,
        evidence={"sample": "e"},
    )


# --- ToolFixProposal 合法路径（回归保护，修复后应仍通过） ---


def test_fix_proposal_proposed_to_trial_pending(in_memory_db) -> None:
    with SelfImprovementRepository() as repo:
        created = _make_fix_proposal(repo)
        result = repo.transition_fix_proposal(created.proposal_id, "trial_pending")
    assert result is not None
    assert result.status == "trial_pending"


def test_fix_proposal_full_legal_path_to_applied(in_memory_db) -> None:
    with SelfImprovementRepository() as repo:
        created = _make_fix_proposal(repo)
        repo.transition_fix_proposal(created.proposal_id, "trial_pending")
        result = repo.transition_fix_proposal(
            created.proposal_id, "applied", trial_result={"ok": True}
        )
    assert result is not None
    assert result.status == "applied"
    assert result.applied_at is not None
    assert result.trial_result == {"ok": True}


def test_fix_proposal_reject_from_proposed(in_memory_db) -> None:
    """proposed -> rejected 合法（manual review 未试直接拒绝）。"""
    with SelfImprovementRepository() as repo:
        created = _make_fix_proposal(repo)
        result = repo.transition_fix_proposal(
            created.proposal_id, "rejected", trial_result={"rejection_reason": "manual"}
        )
    assert result is not None
    assert result.status == "rejected"


def test_fix_proposal_reject_from_trial_pending(in_memory_db) -> None:
    """trial_pending -> rejected 合法（试了失败）。"""
    with SelfImprovementRepository() as repo:
        created = _make_fix_proposal(repo)
        repo.transition_fix_proposal(created.proposal_id, "trial_pending")
        result = repo.transition_fix_proposal(created.proposal_id, "rejected")
    assert result is not None
    assert result.status == "rejected"


# --- ToolFixProposal 非法转换（核心 RED） ---


def test_fix_proposal_cannot_skip_trial_pending_to_applied(in_memory_db) -> None:
    """proposed 直接 -> applied（跳过 trial_pending）必须被拒，返回 None 且状态不变。"""
    with SelfImprovementRepository() as repo:
        created = _make_fix_proposal(repo)
        result = repo.transition_fix_proposal(created.proposal_id, "applied")
        proposal_id = created.proposal_id
    assert result is None
    with SelfImprovementRepository() as repo:
        row = repo.session.get(ToolFixProposal, proposal_id)
        assert row.status == "proposed"


def test_fix_proposal_terminal_applied_cannot_reject(in_memory_db) -> None:
    """终态 applied 不可再转 rejected。"""
    with SelfImprovementRepository() as repo:
        created = _make_fix_proposal(repo)
        repo.transition_fix_proposal(created.proposal_id, "trial_pending")
        repo.transition_fix_proposal(created.proposal_id, "applied")
        result = repo.transition_fix_proposal(created.proposal_id, "rejected")
        proposal_id = created.proposal_id
    assert result is None
    with SelfImprovementRepository() as repo:
        row = repo.session.get(ToolFixProposal, proposal_id)
        assert row.status == "applied"


def test_fix_proposal_unknown_target_returns_none(in_memory_db) -> None:
    """非法目标态返回 None，不抛异常。"""
    with SelfImprovementRepository() as repo:
        created = _make_fix_proposal(repo)
        result = repo.transition_fix_proposal(created.proposal_id, "nonsense")
    assert result is None


def test_fix_proposal_transition_unknown_id_returns_none(in_memory_db) -> None:
    with SelfImprovementRepository() as repo:
        result = repo.transition_fix_proposal("nonexistent", "trial_pending")
    assert result is None


# --- ToolGapReport 状态机 ---


def test_gap_report_resolve_from_detected(in_memory_db) -> None:
    with SelfImprovementRepository() as repo:
        report = _make_gap_report(repo)
        result = repo.resolve_gap_report(report.report_id)
    assert result is not None
    assert result.status == "resolved"


def test_gap_report_fail_from_detected(in_memory_db) -> None:
    with SelfImprovementRepository() as repo:
        report = _make_gap_report(repo, signature="bug:t:fail")
        result = repo.fail_gap_report(report.report_id)
    assert result is not None
    assert result.status == "trial_failed"


def test_gap_report_resolve_from_trial_pending(in_memory_db) -> None:
    with SelfImprovementRepository() as repo:
        report = _make_gap_report(repo, signature="bug:t:tp")
        report.status = "trial_pending"
        repo.session.flush()
        result = repo.resolve_gap_report(report.report_id)
    assert result is not None
    assert result.status == "resolved"


def test_gap_report_resolve_idempotent_returns_none(in_memory_db) -> None:
    """已 resolved 的 gap report 再次 resolve 返回 None（不可重复 resolve）。"""
    with SelfImprovementRepository() as repo:
        report = _make_gap_report(repo, signature="bug:t:idem")
        repo.resolve_gap_report(report.report_id)
        result = repo.resolve_gap_report(report.report_id)
        report_id = report.report_id
    assert result is None
    with SelfImprovementRepository() as repo:
        row = repo.session.get(ToolGapReport, report_id)
        assert row.status == "resolved"


def test_gap_report_fail_after_resolved_returns_none(in_memory_db) -> None:
    """已 resolved 不能转 trial_failed。"""
    with SelfImprovementRepository() as repo:
        report = _make_gap_report(repo, signature="bug:t:failafter")
        repo.resolve_gap_report(report.report_id)
        result = repo.fail_gap_report(report.report_id)
        report_id = report.report_id
    assert result is None
    with SelfImprovementRepository() as repo:
        row = repo.session.get(ToolGapReport, report_id)
        assert row.status == "resolved"
