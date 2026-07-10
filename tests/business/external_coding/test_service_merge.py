import pytest
from pathlib import Path

from src.business.external_coding.models import (
    ConflictRisk,
    ExternalCodingTool,
    MergeAnalysis,
    QuotaSignal,
    QuotaState,
)
from src.business.external_coding.service import ExternalCodingSessionService


class FakeConfig:
    def __init__(self, root: Path) -> None:
        self.root = root

    def get_external_coding_enabled(self):
        return True

    def get_external_coding_default_launch_mode(self):
        return "headless"

    def get_external_coding_preferred_tool(self):
        return "claude_code"

    def get_external_coding_artifact_root(self):
        return str(self.root / "data" / "coding_sessions")

    def get_external_coding_worktree_root(self):
        return str(self.root / ".worktrees" / "coding")

    def get_external_coding_log_tail_chars(self):
        return 8000

    def get_external_coding_quota_probe_enabled(self):
        return True

    def get_external_coding_autostart_enabled(self):
        return False

    def get_external_coding_claude_command(self):
        return "claude"

    def get_external_coding_codex_command(self):
        return "codex"


class FakeQuota:
    def probe_all(self):
        return {
            ExternalCodingTool.CLAUDE_CODE: QuotaSignal(
                tool=ExternalCodingTool.CLAUDE_CODE,
                state=QuotaState.AVAILABLE,
                source="test",
                confidence=1.0,
                checked_at="2026-07-09T00:00:00",
            )
        }


class FakeGit:
    def __init__(self) -> None:
        self.target_head = "a" * 40
        self.coding_head = "b" * 40
        self.merge_commit = "c" * 40
        self.reverted_commit = None
        self.reverted_parent = None

    def head(self, worktree, ref="HEAD"):
        return self.target_head

    def create_worktree(self, *, target_worktree, worktree_path, branch_name):
        worktree_path.mkdir(parents=True, exist_ok=True)

    def merge_analysis(self, *, coding_worktree, coding_branch, target_worktree, target_branch):
        return MergeAnalysis(
            target_branch=target_branch,
            target_worktree_path=str(target_worktree),
            pre_merge_head=self.target_head,
            coding_branch_head=self.coding_head,
            dirty_files=[],
            changed_files=["src/a.py"],
            overlap_files=[],
            conflict_risk=ConflictRisk.LOW,
        )

    def merge(
        self,
        *,
        target_worktree,
        branch_name,
        expected_target_head,
        expected_coding_head,
        expected_changed_files,
    ):
        assert expected_target_head == self.target_head
        assert expected_coding_head == self.coding_head
        assert expected_changed_files == ["src/a.py"]
        self.target_head = self.merge_commit
        return self.merge_commit

    def verify_merge_result(
        self,
        *,
        target_worktree,
        merge_commit,
        expected_target_head,
        expected_coding_head,
        expected_changed_files,
    ):
        assert self.target_head == merge_commit
        assert merge_commit == self.merge_commit
        assert expected_target_head == "a" * 40
        assert expected_coding_head == self.coding_head
        assert expected_changed_files == ["src/a.py"]
        return ["src/a.py"]

    def revert_commit(self, *, target_worktree, commit, expected_parent, expected_branch):
        self.reverted_commit = commit
        self.reverted_parent = expected_parent
        assert expected_branch == "main"
        self.target_head = "d" * 40
        return self.target_head


def test_merge_analysis_and_merge_update_session_state(tmp_path) -> None:
    service = ExternalCodingSessionService(
        config=FakeConfig(tmp_path),
        git_ops=FakeGit(),
        quota_probe=FakeQuota(),
    )
    try:
        created = service.start_session(
            session_id="sess_test",
            owner_type="task",
            owner_id="tsk_merge",
            objective="实现 feature",
            target_worktree_path=str(tmp_path),
        )
        service._repo.update_session(created["codingSessionId"], status="completed", phase="done")

        merge = service.analyze_merge(
            coding_session_id=created["codingSessionId"],
            target_branch="main",
            target_worktree_path=str(tmp_path),
        )
        merged = service.merge_session(
            coding_session_id=created["codingSessionId"],
            merge_record_id=merge["mergeRecordId"],
            agent_decision="低风险自动合并",
        )
        detail = service.get_session(created["codingSessionId"])

        assert merge["conflictRisk"] == "low"
        assert merged["status"] == "merged"
        assert detail["status"] == "merged"
    finally:
        service.close()


def test_rollback_plan_requires_confirmation(tmp_path) -> None:
    """US3-AS5: Rollback plan creates proposed decision with requires_confirmation=True."""
    service = ExternalCodingSessionService(
        config=FakeConfig(tmp_path),
        git_ops=FakeGit(),
        quota_probe=FakeQuota(),
    )
    try:
        created = service.start_session(
            session_id="sess_test",
            owner_type="task",
            owner_id="tsk_rollback",
            objective="实现 feature",
            target_worktree_path=str(tmp_path),
        )
        # Complete and merge the session
        service._repo.update_session(created["codingSessionId"], status="completed", phase="done")
        merge = service.analyze_merge(
            coding_session_id=created["codingSessionId"],
            target_branch="main",
            target_worktree_path=str(tmp_path),
        )
        service.merge_session(
            coding_session_id=created["codingSessionId"],
            merge_record_id=merge["mergeRecordId"],
            agent_decision="auto merge",
        )

        # Create rollback plan
        rollback = service.create_rollback_plan(
            coding_session_id=created["codingSessionId"],
            intent_summary="用户想撤销这次 coding session 的改动",
        )

        assert rollback["requiresConfirmation"] is True
        assert rollback["status"] == "proposed"
        assert rollback["chosenStrategy"] == "revert_commit"

        detail = service.get_session(created["codingSessionId"])
        assert detail["status"] == "rollback_proposed"
    finally:
        service.close()


class HighRiskFakeGit(FakeGit):
    """Git that reports overlap conflict risk (non-LOW)."""

    def merge_analysis(self, *, coding_worktree, coding_branch, target_worktree, target_branch):
        return MergeAnalysis(
            target_branch=target_branch,
            target_worktree_path=str(target_worktree),
            pre_merge_head="a" * 40,
            coding_branch_head="b" * 40,
            dirty_files=[],
            changed_files=["src/a.py", "src/b.py"],
            overlap_files=["src/a.py"],
            conflict_risk=ConflictRisk.OVERLAP,
        )


def test_merge_session_non_low_risk_requires_agent_decision(tmp_path) -> None:
    """CRITICAL: merge_session with non-LOW conflict risk and empty agent_decision raises ValueError."""
    service = ExternalCodingSessionService(
        config=FakeConfig(tmp_path),
        git_ops=HighRiskFakeGit(),
        quota_probe=FakeQuota(),
    )
    try:
        created = service.start_session(
            session_id="sess_test",
            owner_type="task",
            owner_id="tsk_high_risk",
            objective="实现 feature",
            target_worktree_path=str(tmp_path),
        )
        service._repo.update_session(created["codingSessionId"], status="completed", phase="done")

        merge = service.analyze_merge(
            coding_session_id=created["codingSessionId"],
            target_branch="main",
            target_worktree_path=str(tmp_path),
        )
        assert merge["conflictRisk"] == "overlap"

        with pytest.raises(ValueError, match="agent decision is required"):
            service.merge_session(
                coding_session_id=created["codingSessionId"],
                merge_record_id=merge["mergeRecordId"],
                agent_decision="",
            )
    finally:
        service.close()


def test_confirm_rollback_reset_hard_unsupported_in_v1(tmp_path) -> None:
    """V1 guard: reset_hard rollback is never supported and always raises NotImplementedError."""
    service = ExternalCodingSessionService(
        config=FakeConfig(tmp_path),
        git_ops=FakeGit(),
        quota_probe=FakeQuota(),
    )
    try:
        created = service.start_session(
            session_id="sess_test",
            owner_type="task",
            owner_id="tsk_reset_hard",
            objective="实现 feature",
            target_worktree_path=str(tmp_path),
        )
        # Complete and merge the session
        service._repo.update_session(created["codingSessionId"], status="completed", phase="done")
        merge = service.analyze_merge(
            coding_session_id=created["codingSessionId"],
            target_branch="main",
            target_worktree_path=str(tmp_path),
        )
        service.merge_session(
            coding_session_id=created["codingSessionId"],
            merge_record_id=merge["mergeRecordId"],
            agent_decision="auto merge",
        )

        # Create rollback plan, then manually change strategy to reset_hard
        rollback = service.create_rollback_plan(
            coding_session_id=created["codingSessionId"],
            intent_summary="test reset_hard guard",
        )
        # Patch the rollback decision to use reset_hard strategy
        rollback_decisions = service._repo.list_rollback_decisions(created["codingSessionId"])
        target_rb = next(r for r in rollback_decisions if r.rollback_id == rollback["rollbackId"])
        target_rb.chosen_strategy = "reset_hard"
        service._repo.session.commit()

        with pytest.raises(NotImplementedError, match="reset_hard rollback is not supported in V1"):
            service.confirm_rollback(
                coding_session_id=created["codingSessionId"],
                rollback_id=rollback["rollbackId"],
                confirmed_by="user",
            )
    finally:
        service.close()


def test_analyze_merge_not_completed(tmp_path) -> None:
    """HIGH: analyze_merge when session is not completed raises ValueError."""
    service = ExternalCodingSessionService(
        config=FakeConfig(tmp_path),
        git_ops=FakeGit(),
        quota_probe=FakeQuota(),
    )
    try:
        created = service.start_session(
            session_id="sess_test",
            owner_type="task",
            owner_id="tsk_merge_not_completed",
            objective="实现 feature",
            target_worktree_path=str(tmp_path),
        )
        # Session is in "planning" status, not completed
        with pytest.raises(ValueError, match="session must be completed before merge analysis"):
            service.analyze_merge(
                coding_session_id=created["codingSessionId"],
                target_branch="main",
                target_worktree_path=str(tmp_path),
            )
    finally:
        service.close()


def test_merge_session_wrong_merge_record_id(tmp_path) -> None:
    """HIGH: merge_session with merge_record_id from a different session raises LookupError."""
    service = ExternalCodingSessionService(
        config=FakeConfig(tmp_path),
        git_ops=FakeGit(),
        quota_probe=FakeQuota(),
    )
    try:
        # Create two sessions
        created_a = service.start_session(
            session_id="sess_a",
            owner_type="task",
            owner_id="tsk_merge_a",
            objective="实现 feature A",
            target_worktree_path=str(tmp_path),
        )
        created_b = service.start_session(
            session_id="sess_b",
            owner_type="task",
            owner_id="tsk_merge_b",
            objective="实现 feature B",
            target_worktree_path=str(tmp_path),
        )
        # Complete both and create merge analysis for session B
        service._repo.update_session(created_a["codingSessionId"], status="completed", phase="done")
        service._repo.update_session(created_b["codingSessionId"], status="completed", phase="done")

        merge_b = service.analyze_merge(
            coding_session_id=created_b["codingSessionId"],
            target_branch="main",
            target_worktree_path=str(tmp_path),
        )

        # Try to merge session A using session B's merge record
        with pytest.raises(LookupError, match="merge record not found"):
            service.merge_session(
                coding_session_id=created_a["codingSessionId"],
                merge_record_id=merge_b["mergeRecordId"],
                agent_decision="auto merge",
            )
    finally:
        service.close()


class MergeFailingGit(FakeGit):
    """Git whose merge() always raises."""

    def merge(self, **kwargs):
        raise RuntimeError("git merge failed: conflict")


def test_merge_session_git_failure(tmp_path) -> None:
    """HIGH: merge_session when git.merge raises, returns failed merge record and session becomes merge_blocked."""
    service = ExternalCodingSessionService(
        config=FakeConfig(tmp_path),
        git_ops=MergeFailingGit(),
        quota_probe=FakeQuota(),
    )
    try:
        created = service.start_session(
            session_id="sess_test",
            owner_type="task",
            owner_id="tsk_merge_fail",
            objective="实现 feature",
            target_worktree_path=str(tmp_path),
        )
        service._repo.update_session(created["codingSessionId"], status="completed", phase="done")

        merge = service.analyze_merge(
            coding_session_id=created["codingSessionId"],
            target_branch="main",
            target_worktree_path=str(tmp_path),
        )

        result = service.merge_session(
            coding_session_id=created["codingSessionId"],
            merge_record_id=merge["mergeRecordId"],
            agent_decision="auto merge",
        )

        assert result["status"] == "failed"
        detail = service.get_session(created["codingSessionId"])
        assert detail["status"] == "merge_blocked"
    finally:
        service.close()


class RevertFailingGit(FakeGit):
    """Git whose revert_commit() always raises."""

    def revert_commit(self, *, target_worktree, commit, expected_parent, expected_branch):
        raise RuntimeError("git revert failed: cannot revert")


def test_confirm_rollback_git_failure(tmp_path) -> None:
    """HIGH: confirm_rollback when git.revert_commit raises, rollback status is "failed" and ValueError is raised."""
    service = ExternalCodingSessionService(
        config=FakeConfig(tmp_path),
        git_ops=RevertFailingGit(),
        quota_probe=FakeQuota(),
    )
    try:
        created = service.start_session(
            session_id="sess_test",
            owner_type="task",
            owner_id="tsk_rollback_fail",
            objective="实现 feature",
            target_worktree_path=str(tmp_path),
        )
        # Complete and merge the session
        service._repo.update_session(created["codingSessionId"], status="completed", phase="done")
        merge = service.analyze_merge(
            coding_session_id=created["codingSessionId"] if False else created["codingSessionId"],
            target_branch="main",
            target_worktree_path=str(tmp_path),
        )
        service.merge_session(
            coding_session_id=created["codingSessionId"],
            merge_record_id=merge["mergeRecordId"],
            agent_decision="auto merge",
        )

        # Create rollback plan
        rollback = service.create_rollback_plan(
            coding_session_id=created["codingSessionId"],
            intent_summary="test rollback git failure",
        )

        with pytest.raises(ValueError, match="rollback git operation failed"):
            service.confirm_rollback(
                coding_session_id=created["codingSessionId"],
                rollback_id=rollback["rollbackId"],
                confirmed_by="user",
            )

        # Verify rollback status is "failed"
        rollback_decisions = service._repo.list_rollback_decisions(created["codingSessionId"])
        target_rb = next(r for r in rollback_decisions if r.rollback_id == rollback["rollbackId"])
        assert target_rb.status == "failed"
    finally:
        service.close()


def test_create_rollback_plan_not_merged(tmp_path) -> None:
    """HIGH: create_rollback_plan when session is not merged raises ValueError."""
    service = ExternalCodingSessionService(
        config=FakeConfig(tmp_path),
        git_ops=FakeGit(),
        quota_probe=FakeQuota(),
    )
    try:
        created = service.start_session(
            session_id="sess_test",
            owner_type="task",
            owner_id="tsk_rollback_not_merged",
            objective="实现 feature",
            target_worktree_path=str(tmp_path),
        )
        # Session is in "planning" status, not merged
        with pytest.raises(ValueError, match="only merged sessions can be rolled back"):
            service.create_rollback_plan(
                coding_session_id=created["codingSessionId"],
                intent_summary="should not work",
            )
    finally:
        service.close()


class StaleAnalysisGit(FakeGit):
    def __init__(self) -> None:
        super().__init__()
        self.analysis_count = 0
        self.merge_called = False

    def merge_analysis(self, **kwargs):
        self.analysis_count += 1
        if self.analysis_count == 2:
            self.target_head = "d" * 40
        return super().merge_analysis(**kwargs)

    def merge(self, **kwargs):
        self.merge_called = True
        return super().merge(**kwargs)


def test_merge_session_rejects_stale_analysis_snapshot(tmp_path) -> None:
    git = StaleAnalysisGit()
    service = ExternalCodingSessionService(
        config=FakeConfig(tmp_path),
        git_ops=git,
        quota_probe=FakeQuota(),
    )
    try:
        created = service.start_session(
            session_id="sess_test",
            owner_type="task",
            owner_id="tsk_stale_merge",
            objective="实现 feature",
            target_worktree_path=str(tmp_path),
        )
        coding_session_id = created["codingSessionId"]
        service._repo.update_session(coding_session_id, status="completed", phase="done")
        merge = service.analyze_merge(
            coding_session_id=coding_session_id,
            target_branch="main",
            target_worktree_path=str(tmp_path),
        )

        with pytest.raises(ValueError, match="merge analysis is stale"):
            service.merge_session(
                coding_session_id=coding_session_id,
                merge_record_id=merge["mergeRecordId"],
                agent_decision="merge",
            )

        assert git.merge_called is False
        record = service._repo.get_merge_record(merge["mergeRecordId"])
        assert record.status == "blocked"
        assert service.get_session(coding_session_id)["status"] == "merge_blocked"

        refreshed = service.analyze_merge(
            coding_session_id=coding_session_id,
            target_branch="main",
            target_worktree_path=str(tmp_path),
        )
        assert refreshed["preMergeHead"] == "d" * 40
        assert refreshed["status"] == "analysis_ready"
    finally:
        service.close()


class NoOpMergeGit(FakeGit):
    def merge(self, **kwargs):
        return self.target_head


def test_merge_session_does_not_mark_no_op_as_merged(tmp_path) -> None:
    service = ExternalCodingSessionService(
        config=FakeConfig(tmp_path),
        git_ops=NoOpMergeGit(),
        quota_probe=FakeQuota(),
    )
    try:
        created = service.start_session(
            session_id="sess_test",
            owner_type="task",
            owner_id="tsk_no_op_merge",
            objective="实现 feature",
            target_worktree_path=str(tmp_path),
        )
        coding_session_id = created["codingSessionId"]
        service._repo.update_session(coding_session_id, status="completed", phase="done")
        merge = service.analyze_merge(
            coding_session_id=coding_session_id,
            target_branch="main",
            target_worktree_path=str(tmp_path),
        )

        result = service.merge_session(
            coding_session_id=coding_session_id,
            merge_record_id=merge["mergeRecordId"],
            agent_decision="merge",
        )

        assert result["status"] == "failed"
        assert result["mergeCommit"] is None
        assert service.get_session(coding_session_id)["status"] == "merge_blocked"
    finally:
        service.close()


def test_confirm_rollback_reverts_bound_merge_and_marks_record_rolled_back(tmp_path) -> None:
    git = FakeGit()
    service = ExternalCodingSessionService(
        config=FakeConfig(tmp_path),
        git_ops=git,
        quota_probe=FakeQuota(),
    )
    try:
        created = service.start_session(
            session_id="sess_test",
            owner_type="task",
            owner_id="tsk_exact_rollback",
            objective="实现 feature",
            target_worktree_path=str(tmp_path),
        )
        coding_session_id = created["codingSessionId"]
        service._repo.update_session(coding_session_id, status="completed", phase="done")
        merge = service.analyze_merge(
            coding_session_id=coding_session_id,
            target_branch="main",
            target_worktree_path=str(tmp_path),
        )
        merged = service.merge_session(
            coding_session_id=coding_session_id,
            merge_record_id=merge["mergeRecordId"],
            agent_decision="merge",
        )
        rollback = service.create_rollback_plan(
            coding_session_id=coding_session_id,
            intent_summary="撤销这次合并",
        )

        applied = service.confirm_rollback(
            coding_session_id=coding_session_id,
            rollback_id=rollback["rollbackId"],
            confirmed_by="user",
        )

        assert applied["status"] == "applied"
        assert git.reverted_commit == merged["mergeCommit"]
        assert git.reverted_parent == merge["preMergeHead"]
        merge_record = service._repo.get_merge_record(merge["mergeRecordId"])
        assert merge_record.status == "rolled_back"
        assert service.get_session(coding_session_id)["status"] == "rolled_back"
    finally:
        service.close()
