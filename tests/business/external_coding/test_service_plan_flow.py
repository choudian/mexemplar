import pytest
from pathlib import Path

from src.business.external_coding.models import (
    AttemptStatus,
    CodingPhase,
    ErrorCategory,
    ExternalCodingTool,
    ProcessStartResult,
    QuotaSignal,
    QuotaState,
)
from src.business.external_coding.service import (
    ExternalCodingSessionService,
    _validate_branch_name,
)


class FakeConfig:
    def __init__(self, root: Path) -> None:
        self.root = root

    def get_external_coding_enabled(self):
        return True

    def get_external_coding_default_launch_mode(self):
        return "headless"

    def get_external_coding_preferred_tool(self):
        return "auto"

    def get_external_coding_artifact_root(self):
        return str(self.root / "data" / "coding_sessions")

    def get_external_coding_worktree_root(self):
        return str(self.root / ".worktrees" / "coding")

    def get_external_coding_log_tail_chars(self):
        return 8000

    def get_external_coding_quota_probe_enabled(self):
        return True

    def get_external_coding_autostart_enabled(self):
        return True

    def get_external_coding_claude_command(self):
        return "claude"

    def get_external_coding_codex_command(self):
        return "codex"

    def get_external_coding_claude_effort(self):
        return "max"

    def get_external_coding_codex_reasoning_effort(self):
        return "xhigh"


class FakeGit:
    def __init__(self) -> None:
        self.plan_changes: list[str] = []

    def head(self, worktree, ref="HEAD"):
        return "a" * 40

    def create_worktree(self, *, target_worktree, worktree_path, branch_name):
        worktree_path.mkdir(parents=True, exist_ok=True)

    def changed_files_against(self, *, worktree, base_ref="HEAD"):
        assert base_ref == "a" * 40
        return self.plan_changes


class FakeQuota:
    def probe_all(self):
        return {
            ExternalCodingTool.CLAUDE_CODE: QuotaSignal(
                tool=ExternalCodingTool.CLAUDE_CODE,
                state=QuotaState.AVAILABLE,
                source="test",
                confidence=1.0,
                checked_at="2026-07-09T00:00:00",
            ),
            ExternalCodingTool.CODEX_CLI: QuotaSignal(
                tool=ExternalCodingTool.CODEX_CLI,
                state=QuotaState.EXHAUSTED,
                source="test",
                confidence=1.0,
                checked_at="2026-07-09T00:00:00",
            ),
        }


class FakeAdapter:
    def __init__(self):
        self.calls = []

    def start(
        self,
        *,
        tool,
        phase,
        prompt_path,
        worktree_path,
        artifact_dir,
        log_path,
        launch_mode,
        external_session_ref,
    ):
        self.calls.append(
            {
                "phase": phase,
                "prompt": prompt_path.read_text(encoding="utf-8"),
                "external_session_ref": external_session_ref,
                "launch_mode": launch_mode,
            }
        )
        if phase == CodingPhase.PLAN:
            (artifact_dir / "PLAN.md").write_text(
                """
                目标：完成测试 feature。
                计划改动：更新 service 和 API。
                影响范围：src 与 frontend files。
                假设/非目标：不调用真实 CLI。
                风险：无。
                测试计划：pytest。
                待确认问题：无。
                建议：继续。
                """,
                encoding="utf-8",
            )
        else:
            (artifact_dir / "RESULT.md").write_text(
                """
                状态 status：completed。
                总结 summary：已实现。
                改动文件 changed files：src/example.py。
                计划偏差 deviations：无。
                测试 tests：pytest passed。
                测试结果 test results：全部 passed。
                风险 risks：无。
                后续 follow ups：无。
                完成备注 completion notes：无额外说明。
                """,
                encoding="utf-8",
            )
        return ProcessStartResult(
            status=AttemptStatus.SUCCEEDED,
            command_summary=f"fake {phase.value}",
            external_session_ref="external-thread-1",
        )


class FailingAdapter:
    """Adapter that always fails with login_required, used for FR-020 and D7 tests."""

    def start(self, **_kwargs):
        return ProcessStartResult(
            status=AttemptStatus.FAILED,
            command_summary="claude -p <prompt>",
            error_category=ErrorCategory.LOGIN_REQUIRED,
            error_message="login required",
        )


@pytest.mark.parametrize(
    "name",
    ["-help", "../main", ".hidden", "feature//child", "feature.lock"],
)
def test_branch_name_validation_rejects_git_argument_and_ref_tricks(name) -> None:
    with pytest.raises(ValueError, match="invalid branch name"):
        _validate_branch_name(name)


def test_start_session_rejects_blank_objective(tmp_path) -> None:
    service = ExternalCodingSessionService(
        config=FakeConfig(tmp_path),
        git_ops=FakeGit(),
        quota_probe=FakeQuota(),
        adapter_factory=lambda: FakeAdapter(),
    )
    try:
        with pytest.raises(ValueError, match="objective is required"):
            service.start_session(
                session_id="sess_test",
                owner_type="task",
                owner_id="tsk_blank_objective",
                objective="   ",
                target_worktree_path=str(tmp_path),
            )
    finally:
        service.close()


def test_plan_approval_then_result_completion(tmp_path) -> None:
    adapter = FakeAdapter()
    service = ExternalCodingSessionService(
        config=FakeConfig(tmp_path),
        git_ops=FakeGit(),
        quota_probe=FakeQuota(),
        adapter_factory=lambda: adapter,
    )
    try:
        created = service.start_session(
            session_id="sess_test",
            owner_type="task",
            owner_id="tsk_external_coding_test",
            objective="实现测试 feature",
            target_worktree_path=str(tmp_path),
        )
        refreshed = service.refresh_session(created["codingSessionId"])

        assert refreshed["status"] == "plan_ready"
        assert refreshed["tool"] == "claude_code"

        approved = service.decide_plan(
            coding_session_id=created["codingSessionId"],
            decision="approved",
            feedback="继续",
        )
        completed = service.refresh_session(created["codingSessionId"])

        assert approved["phase"] == "implement"
        assert completed["status"] == "completed"
        assert completed["reviewRecommended"] is True
        assert "not independently verified" in completed["reviewSkippedReason"]
        assert adapter.calls[0]["phase"] == CodingPhase.PLAN
        assert "Do not modify files in the coding worktree" in adapter.calls[0]["prompt"]
        assert "AGENTS.md" in adapter.calls[0]["prompt"]
        assert adapter.calls[1]["phase"] == CodingPhase.IMPLEMENT
        assert "approved plan" in adapter.calls[1]["prompt"].lower()
        assert "PLAN.md" in adapter.calls[1]["prompt"]
        assert "AGENTS.md" in adapter.calls[1]["prompt"]
        assert "继续" in adapter.calls[1]["prompt"]
        assert adapter.calls[1]["external_session_ref"] == "external-thread-1"
        assert adapter.calls[0]["prompt"] != adapter.calls[1]["prompt"]
    finally:
        service.close()


def test_plan_rejection_stays_in_plan_phase_with_feedback(tmp_path) -> None:
    """US1-AS4: Plan rejection with feedback keeps session in plan phase."""
    service = ExternalCodingSessionService(
        config=FakeConfig(tmp_path),
        git_ops=FakeGit(),
        quota_probe=FakeQuota(),
        adapter_factory=lambda: FakeAdapter(),
    )
    try:
        created = service.start_session(
            session_id="sess_test",
            owner_type="task",
            owner_id="tsk_rejection_test",
            objective="实现测试 feature",
            target_worktree_path=str(tmp_path),
        )
        refreshed = service.refresh_session(created["codingSessionId"])
        assert refreshed["status"] == "plan_ready"

        rejected = service.decide_plan(
            coding_session_id=created["codingSessionId"],
            decision="rejected",
            feedback="计划缺少关键风险分析，请补充",
        )

        assert rejected["status"] == "plan_rejected"
        assert rejected["phase"] == "plan"
        assert "风险" in (rejected["lastErrorMessage"] or "")
    finally:
        service.close()


def test_plan_rejection_requires_feedback(tmp_path) -> None:
    service = ExternalCodingSessionService(
        config=FakeConfig(tmp_path),
        git_ops=FakeGit(),
        quota_probe=FakeQuota(),
        adapter_factory=lambda: FakeAdapter(),
    )
    try:
        created = service.start_session(
            session_id="sess_test",
            owner_type="task",
            owner_id="tsk_feedback_required",
            objective="实现测试 feature",
            target_worktree_path=str(tmp_path),
        )
        service.refresh_session(created["codingSessionId"])

        with pytest.raises(ValueError, match="feedback is required"):
            service.decide_plan(
                coding_session_id=created["codingSessionId"],
                decision="rejected",
                feedback="   ",
            )
    finally:
        service.close()


def test_rejected_plan_cannot_resume_directly_to_implementation(tmp_path) -> None:
    service = ExternalCodingSessionService(
        config=FakeConfig(tmp_path),
        git_ops=FakeGit(),
        quota_probe=FakeQuota(),
        adapter_factory=lambda: FakeAdapter(),
    )
    try:
        created = service.start_session(
            session_id="sess_test",
            owner_type="task",
            owner_id="tsk_no_approval_bypass",
            objective="实现测试 feature",
            target_worktree_path=str(tmp_path),
        )
        service.refresh_session(created["codingSessionId"])
        service.decide_plan(
            coding_session_id=created["codingSessionId"],
            decision="rejected",
            feedback="需要补充风险分析",
        )

        with pytest.raises(ValueError, match="before plan approval"):
            service.resume_session(
                coding_session_id=created["codingSessionId"],
                phase="implement",
            )
    finally:
        service.close()


def test_plan_phase_detects_changes_committed_after_worktree_baseline(tmp_path) -> None:
    git = FakeGit()
    service = ExternalCodingSessionService(
        config=FakeConfig(tmp_path),
        git_ops=git,
        quota_probe=FakeQuota(),
        adapter_factory=lambda: FakeAdapter(),
    )
    try:
        created = service.start_session(
            session_id="sess_test",
            owner_type="task",
            owner_id="tsk_committed_plan_write",
            objective="实现测试 feature",
            target_worktree_path=str(tmp_path),
        )
        git.plan_changes = ["src/committed_during_plan.py"]

        refreshed = service.refresh_session(created["codingSessionId"])

        assert refreshed["status"] == "interrupted"
        assert refreshed["lastErrorCategory"] == "protocol_violation"
        assert "committed_during_plan.py" in refreshed["lastErrorMessage"]
    finally:
        service.close()


def test_review_outcome_records_skips_and_clears_after_independent_checks(tmp_path) -> None:
    service = ExternalCodingSessionService(
        config=FakeConfig(tmp_path),
        git_ops=FakeGit(),
        quota_probe=FakeQuota(),
        adapter_factory=lambda: FakeAdapter(),
    )
    try:
        created = service.start_session(
            session_id="sess_test",
            owner_type="task",
            owner_id="tsk_review_outcome",
            objective="实现测试 feature",
            target_worktree_path=str(tmp_path),
        )
        coding_session_id = created["codingSessionId"]
        service._repo.update_session(
            coding_session_id,
            status="completed",
            phase="done",
        )

        with pytest.raises(ValueError, match="skippedReason"):
            service.record_review_outcome(
                coding_session_id=coding_session_id,
                independently_reviewed=True,
                independently_tested=False,
            )
        skipped = service.record_review_outcome(
            coding_session_id=coding_session_id,
            independently_reviewed=True,
            independently_tested=False,
            skipped_reason="没有可用的集成测试环境",
        )
        complete = service.record_review_outcome(
            coding_session_id=coding_session_id,
            independently_reviewed=True,
            independently_tested=True,
        )

        assert skipped["reviewRecommended"] is True
        assert skipped["reviewSkippedReason"] == "没有可用的集成测试环境"
        assert complete["reviewRecommended"] is False
        assert complete["reviewSkippedReason"] is None
    finally:
        service.close()


def test_rejected_plan_resume_prompt_includes_feedback_and_instruction(tmp_path) -> None:
    adapter = FakeAdapter()
    service = ExternalCodingSessionService(
        config=FakeConfig(tmp_path),
        git_ops=FakeGit(),
        quota_probe=FakeQuota(),
        adapter_factory=lambda: adapter,
    )
    try:
        created = service.start_session(
            session_id="sess_test",
            owner_type="task",
            owner_id="tsk_prompt_resume",
            objective="实现测试 feature",
            target_worktree_path=str(tmp_path),
        )
        service.refresh_session(created["codingSessionId"])
        service.decide_plan(
            coding_session_id=created["codingSessionId"],
            decision="rejected",
            feedback="补充数据库回滚风险",
        )

        service.resume_session(
            coding_session_id=created["codingSessionId"],
            instruction="只修改计划，不要实现",
            phase="plan",
        )

        resumed_prompt = adapter.calls[-1]["prompt"]
        assert "补充数据库回滚风险" in resumed_prompt
        assert "只修改计划，不要实现" in resumed_prompt
    finally:
        service.close()


def test_escalate_to_user_from_interrupted(tmp_path) -> None:
    """FR-020: Agent can escalate an interrupted session to waiting_user."""
    service = ExternalCodingSessionService(
        config=FakeConfig(tmp_path),
        git_ops=FakeGit(),
        quota_probe=FakeQuota(),
        adapter_factory=lambda: FailingAdapter(),
    )
    try:
        created = service.start_session(
            session_id="sess_test",
            owner_type="task",
            owner_id="tsk_escalate_test",
            objective="实现 feature",
            target_worktree_path=str(tmp_path),
        )
        assert created["status"] == "interrupted"

        escalated = service.escalate_to_user(
            coding_session_id=created["codingSessionId"],
            reason="无法自动恢复，需要用户重新登录 Claude Code",
        )

        assert escalated["status"] == "waiting_user"
        assert "登录" in (escalated["lastErrorMessage"] or "")
    finally:
        service.close()


def test_escalate_to_user_rejects_non_interrupted(tmp_path) -> None:
    """FR-020: Only interrupted sessions can be escalated to waiting_user."""
    service = ExternalCodingSessionService(
        config=FakeConfig(tmp_path),
        git_ops=FakeGit(),
        quota_probe=FakeQuota(),
        adapter_factory=lambda: FakeAdapter(),
    )
    try:
        created = service.start_session(
            session_id="sess_test",
            owner_type="task",
            owner_id="tsk_escalate_guard_test",
            objective="实现 feature",
            target_worktree_path=str(tmp_path),
        )

        import pytest

        with pytest.raises(ValueError, match="only interrupted"):
            service.escalate_to_user(
                coding_session_id=created["codingSessionId"],
                reason="should not work",
            )
    finally:
        service.close()


class DisabledConfig(FakeConfig):
    def get_external_coding_enabled(self):
        return False


def test_start_session_disabled(tmp_path) -> None:
    """CRITICAL: When config.get_external_coding_enabled() returns False, start_session raises ValueError."""
    service = ExternalCodingSessionService(
        config=DisabledConfig(tmp_path),
        git_ops=FakeGit(),
        quota_probe=FakeQuota(),
        adapter_factory=lambda: FakeAdapter(),
    )
    try:
        with pytest.raises(ValueError, match="external coding sessions are disabled"):
            service.start_session(
                session_id="sess_disabled",
                owner_type="task",
                owner_id="tsk_disabled",
                objective="should not start",
                target_worktree_path=str(tmp_path),
            )
    finally:
        service.close()


def test_start_session_invalid_owner_type(tmp_path) -> None:
    """CRITICAL: start_session with owner_type="invalid" raises ValueError."""
    service = ExternalCodingSessionService(
        config=FakeConfig(tmp_path),
        git_ops=FakeGit(),
        quota_probe=FakeQuota(),
        adapter_factory=lambda: FakeAdapter(),
    )
    try:
        with pytest.raises(ValueError, match="ownerType must be task or workflow"):
            service.start_session(
                session_id="sess_bad_owner",
                owner_type="invalid",
                owner_id="tsk_bad_owner",
                objective="should not start",
                target_worktree_path=str(tmp_path),
            )
    finally:
        service.close()


def test_decide_plan_not_plan_ready(tmp_path) -> None:
    """HIGH: decide_plan when session status != plan_ready raises ValueError."""
    service = ExternalCodingSessionService(
        config=FakeConfig(tmp_path),
        git_ops=FakeGit(),
        quota_probe=FakeQuota(),
        adapter_factory=lambda: FakeAdapter(),
    )
    try:
        created = service.start_session(
            session_id="sess_test",
            owner_type="task",
            owner_id="tsk_decide_not_ready",
            objective="实现 feature",
            target_worktree_path=str(tmp_path),
        )
        # Session is in "planning" status (not plan_ready) after start with autostart
        # Force it to a non-plan_ready status by updating directly
        service._repo.update_session(
            created["codingSessionId"], status="implementing", phase="implement"
        )

        with pytest.raises(ValueError, match="plan is not ready for decision"):
            service.decide_plan(
                coding_session_id=created["codingSessionId"],
                decision="approved",
            )
    finally:
        service.close()


def test_decide_plan_invalid_decision(tmp_path) -> None:
    """HIGH: decide_plan with decision="maybe" raises ValueError."""
    service = ExternalCodingSessionService(
        config=FakeConfig(tmp_path),
        git_ops=FakeGit(),
        quota_probe=FakeQuota(),
        adapter_factory=lambda: FakeAdapter(),
    )
    try:
        created = service.start_session(
            session_id="sess_test",
            owner_type="task",
            owner_id="tsk_invalid_decision",
            objective="实现 feature",
            target_worktree_path=str(tmp_path),
        )
        # Advance to plan_ready
        refreshed = service.refresh_session(created["codingSessionId"])
        assert refreshed["status"] == "plan_ready"

        with pytest.raises(
            ValueError, match="decision must be approved, rejected or clarification_requested"
        ):
            service.decide_plan(
                coding_session_id=created["codingSessionId"],
                decision="maybe",
            )
    finally:
        service.close()


def test_resume_session_invalid_phase(tmp_path) -> None:
    """HIGH: resume_session with phase="merge" raises ValueError."""
    service = ExternalCodingSessionService(
        config=FakeConfig(tmp_path),
        git_ops=FakeGit(),
        quota_probe=FakeQuota(),
        adapter_factory=lambda: FailingAdapter(),
    )
    try:
        created = service.start_session(
            session_id="sess_test",
            owner_type="task",
            owner_id="tsk_resume_invalid_phase",
            objective="实现 feature",
            target_worktree_path=str(tmp_path),
        )
        # Session is interrupted due to FailingAdapter
        assert created["status"] == "interrupted"

        with pytest.raises(ValueError, match="only plan or implement phases can be resumed"):
            service.resume_session(
                coding_session_id=created["codingSessionId"],
                phase="merge",
            )
    finally:
        service.close()


def test_resume_session_non_resumable_status(tmp_path) -> None:
    """HIGH: resume_session when session is in completed/merged/abandoned status raises ValueError."""
    service = ExternalCodingSessionService(
        config=FakeConfig(tmp_path),
        git_ops=FakeGit(),
        quota_probe=FakeQuota(),
        adapter_factory=lambda: FakeAdapter(),
    )
    try:
        created = service.start_session(
            session_id="sess_test",
            owner_type="task",
            owner_id="tsk_resume_terminal",
            objective="实现 feature",
            target_worktree_path=str(tmp_path),
        )
        # Force session to completed status
        service._repo.update_session(created["codingSessionId"], status="completed", phase="done")

        with pytest.raises(ValueError, match="session in status completed cannot be resumed"):
            service.resume_session(
                coding_session_id=created["codingSessionId"],
            )
    finally:
        service.close()


def test_abandon_session_nonexistent(tmp_path) -> None:
    """HIGH: abandon_session with non-existent ID raises LookupError."""
    service = ExternalCodingSessionService(
        config=FakeConfig(tmp_path),
        git_ops=FakeGit(),
        quota_probe=FakeQuota(),
        adapter_factory=lambda: FakeAdapter(),
    )
    try:
        with pytest.raises(LookupError, match="external coding session not found"):
            service.abandon_session(
                coding_session_id="ecs_nonexistent",
                reason="should not work",
            )
    finally:
        service.close()


def test_abandon_session_terminal_status(tmp_path) -> None:
    """HIGH: abandon_session when session is merged/rolled_back/abandoned raises ValueError."""
    service = ExternalCodingSessionService(
        config=FakeConfig(tmp_path),
        git_ops=FakeGit(),
        quota_probe=FakeQuota(),
        adapter_factory=lambda: FakeAdapter(),
    )
    try:
        created = service.start_session(
            session_id="sess_test",
            owner_type="task",
            owner_id="tsk_abandon_terminal",
            objective="实现 feature",
            target_worktree_path=str(tmp_path),
        )
        # Force session to merged status
        service._repo.update_session(created["codingSessionId"], status="merged", phase="done")

        with pytest.raises(ValueError, match="session in status merged cannot be abandoned"):
            service.abandon_session(
                coding_session_id=created["codingSessionId"],
                reason="should not work",
            )
    finally:
        service.close()
