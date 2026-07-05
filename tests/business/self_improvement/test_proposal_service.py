"""Tests for ProposalService — generation idempotency, dedup, approve/reject."""

from __future__ import annotations

from src.business.self_improvement.proposal_service import (
    ProposalService,
    sanitize_proposal_public_text,
)
from src.data.repos.improvement_proposal_repository import ImprovementProposalRepository

_WORTH_CHANGING = [
    {
        "type": "效率",
        "what": "重复抓取",
        "evidence": "两次同一URL",
        "severity": "med",
        "suggestion": "加缓存",
        "worth_changing": True,
    },
]
_NOT_WORTH_CHANGING = [
    {
        "type": "健壮性",
        "what": "无重试",
        "evidence": "网络超时无重试",
        "severity": "low",
        "suggestion": "加重试",
        "worth_changing": False,
    },
]


def test_generate_creates_proposals_for_worth_changing(in_memory_db):
    svc = ProposalService()
    findings = _WORTH_CHANGING + _NOT_WORTH_CHANGING
    count = svc.generate_from_review("rev_001", findings)
    assert count == 1

    proposals = svc.list_proposals()
    assert len(proposals) == 1
    assert proposals[0]["status"] == "pending_review"
    assert proposals[0]["what"] == "重复抓取"
    assert proposals[0]["sourceReviewId"] == "rev_001"


def test_generate_idempotent_same_review(in_memory_db):
    svc = ProposalService()
    svc.generate_from_review("rev_002", _WORTH_CHANGING)
    count2 = svc.generate_from_review("rev_002", _WORTH_CHANGING)
    assert count2 == 0  # 幂等：不重复生成


def test_generate_dedup_across_reviews(in_memory_db):
    """跨复盘同类提案抑制（FR-001a）。"""
    svc = ProposalService()
    svc.generate_from_review("rev_a", _WORTH_CHANGING)
    count2 = svc.generate_from_review("rev_b", _WORTH_CHANGING)
    assert count2 == 0  # 同 dedup_key，抑制


def test_approve_transitions_and_persists_supplement(in_memory_db):
    svc = ProposalService()
    svc.generate_from_review("rev_003", _WORTH_CHANGING)
    proposals = svc.list_proposals()
    pid = proposals[0]["id"]

    result = svc.approve(pid, supplement="优先改缓存层")
    assert result is not None
    assert result["status"] == "approved"
    assert result["userSupplement"] == "优先改缓存层"


def test_approve_non_pending_returns_none(in_memory_db):
    svc = ProposalService()
    svc.generate_from_review("rev_004", _WORTH_CHANGING)
    proposals = svc.list_proposals()
    pid = proposals[0]["id"]
    svc.approve(pid)
    result = svc.approve(pid)
    assert result is None


def test_reject_transitions_to_rejected(in_memory_db):
    svc = ProposalService()
    svc.generate_from_review("rev_005", _WORTH_CHANGING)
    proposals = svc.list_proposals()
    pid = proposals[0]["id"]

    result = svc.reject(pid)
    assert result is not None
    assert result["status"] == "rejected"


def test_approval_no_side_effects_before_approval(in_memory_db):
    """审批前零副作用（FR-008）：pending 提案无 graph_id / worktree_path / branch_name。"""
    svc = ProposalService()
    svc.generate_from_review("rev_006", _WORTH_CHANGING)
    proposals = svc.list_proposals()
    p = proposals[0]
    assert p["graphId"] is None
    assert "worktreePath" not in p  # spec api.md: DTO 不暴露 worktreePath,只用 worktreeAvailable
    assert p["worktreeAvailable"] is False
    assert p["branchName"] is None


def test_reject_failed_proposal_cleans_worktree(in_memory_db, tmp_path, monkeypatch):
    """用户弃用 failed 提案时清理隔离 worktree。"""
    svc = ProposalService()
    svc.generate_from_review("rev_007", _WORTH_CHANGING)
    pid = svc.list_proposals()[0]["id"]
    svc.approve(pid)
    with ImprovementProposalRepository() as repo:
        row = repo.mark_in_progress(
            pid,
            graph_id="tg_cleanup",
            worktree_path=str(tmp_path),
            branch_name=f"improvement/{pid}",
        )
        assert row is not None
        row = repo.mark_failed(pid, error="tests failed", tests_passed=False)
        assert row is not None

    removed: list[str] = []
    monkeypatch.setattr(
        "src.business.self_improvement.proposal_workspace.remove_worktree",
        lambda path: removed.append(str(path)),
    )

    result = svc.reject(pid)

    assert result is not None
    assert result["status"] == "rejected"
    assert removed == [str(tmp_path)]
    assert "worktreePath" not in svc.get_proposal(pid)  # spec api.md: DTO 不暴露 worktreePath
    assert svc.get_proposal(pid)["worktreeAvailable"] is False


def test_sanitize_public_text_redacts_secrets_paths_and_truncates():
    """DTO 边界脱敏单元：密钥/路径/密钥文件名必须被替换，超长截断。"""
    assert sanitize_proposal_public_text(None) is None
    assert sanitize_proposal_public_text("") == ""

    cleaned = sanitize_proposal_public_text(
        "auth sk-abcdefghijklmnopqrstuvwxyz fail at C:\\Users\\pan\\secrets.env "
        "token bearer abc123_xyz slack xoxb-1234567890-abcdefgh"
    )
    assert "sk-abcdefgh" not in cleaned
    assert "C:\\Users" not in cleaned
    assert "secrets.env" not in cleaned
    assert ".env" not in cleaned
    assert "bearer abc123" not in cleaned
    assert "xoxb-" not in cleaned
    assert "***REDACTED***" in cleaned

    assert len(sanitize_proposal_public_text("x" * 600)) == 500


def test_to_dict_redacts_error_via_dto_boundary(in_memory_db):
    """DTO 边界不变量：mark_failed 写入脏 error，list/get 返回的 DTO 必须已脱敏。

    CLAUDE.md: secret 不得进入明文 DTO；data-model 标注 error 为"脱敏安全原因"。
    """
    svc = ProposalService()
    svc.generate_from_review("rev_err", _WORTH_CHANGING)
    pid = svc.list_proposals()[0]["id"]
    svc.approve(pid)
    dirty = "provider 401 key=sk-abcdefghijklmnopqrstuvwxyz ref C:\\Users\\pan\\app\\config.pem"
    with ImprovementProposalRepository() as repo:
        assert repo.mark_failed(pid, error=dirty, tests_passed=False) is not None

    proposal = svc.get_proposal(pid)
    assert proposal is not None
    err = proposal["error"]
    assert "sk-abcdefgh" not in err
    assert "C:\\Users" not in err
    assert "config.pem" not in err
    assert "***REDACTED***" in err


def test_to_dict_redacts_result_summary_via_dto_boundary(in_memory_db):
    """resultSummary 也会展示到 BrainScreen，DTO 边界必须同 error 一样脱敏。"""
    svc = ProposalService()
    svc.generate_from_review("rev_summary", _WORTH_CHANGING)
    pid = svc.list_proposals()[0]["id"]
    svc.approve(pid)
    dirty = "tests passed with sk-abcdefghijklmnopqrstuvwxyz at C:\\Users\\pan\\app\\secret.env"
    with ImprovementProposalRepository() as repo:
        assert (
            repo.mark_in_progress(
                pid,
                graph_id="tg_summary",
                worktree_path="/tmp/worktree",
                branch_name=f"improvement/{pid}",
            )
            is not None
        )
        assert repo.mark_done(pid, tests_passed=True, summary=dirty) is not None

    proposal = svc.get_proposal(pid)
    assert proposal is not None
    assert "worktreePath" not in proposal  # spec api.md: DTO 不暴露 worktreePath
    assert proposal["worktreeAvailable"] is True
    summary = proposal["resultSummary"]
    assert "sk-abcdefgh" not in summary
    assert "C:\\Users" not in summary
    assert ".env" not in summary
    assert "***REDACTED***" in summary


def test_sanitize_redacts_additional_provider_secret_shapes():
    """denylist 覆盖 026 review HIGH-1 点名的漏网形态:Stripe live key、Google API
    key、JWT、URL 内嵌凭证不得原样进 DTO error/summary。denylist 是纵深防御的一层
    (服务端日志另存完整诊断),但已知 secret 形态必须命中。"""
    samples = [
        ("stripe key " + "sk_live_" + "abcdefghijklmnopqrstuvwxyz leaked", "sk_live_"),
        ("google AIzaSyA1234567890XYZabcd in log", "AIzaSyA"),
        ("jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ4In0.sig leaked", "eyJhbGci"),
        ("db url postgres://uploader:p4ssw0rd@db.host:5432/app", "p4ssw0rd"),
    ]
    for dirty, needle in samples:
        cleaned = sanitize_proposal_public_text(dirty)
        assert cleaned is not None
        assert needle not in cleaned, f"{needle!r} not redacted: {cleaned!r}"


def test_to_dict_falls_back_when_sanitizer_raises(in_memory_db, monkeypatch):
    """DTO 边界脱敏自身故障时 fail-safe 到固定串,不冒泡成 FastAPI 500(026 MEDIUM-9)。

    与 proposal_bridge._safe_public_text 的 fail-safe 回退对齐:所有面向前端的
    error/summary 出口都不得因 sanitizer bug 把异常透到 HTTP 层。
    """
    svc = ProposalService()
    svc.generate_from_review("rev_safe", _WORTH_CHANGING)
    pid = svc.list_proposals()[0]["id"]
    svc.approve(pid)
    with ImprovementProposalRepository() as repo:
        assert repo.mark_failed(pid, error="dirty diagnostic", tests_passed=False) is not None

    def boom(_):
        raise RuntimeError("regex engine exploded")

    monkeypatch.setattr(
        "src.business.self_improvement.proposal_service.sanitize_proposal_public_text", boom
    )

    proposal = svc.get_proposal(pid)  # 不得抛
    assert proposal is not None
    assert proposal["error"]  # 回退为非空固定串
    assert proposal["error"] != "dirty diagnostic"  # 原始脏值未透出
