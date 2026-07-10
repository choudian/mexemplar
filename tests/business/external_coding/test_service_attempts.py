from pathlib import Path

from src.business.external_coding.models import (
    AttemptStatus,
    ErrorCategory,
    ExternalCodingTool,
    ProcessStartResult,
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
        return True

    def get_external_coding_claude_command(self):
        return "claude"

    def get_external_coding_codex_command(self):
        return "codex"


class FakeGit:
    def head(self, worktree, ref="HEAD"):
        return "a" * 40

    def create_worktree(self, *, target_worktree, worktree_path, branch_name):
        worktree_path.mkdir(parents=True, exist_ok=True)

    def changed_files_against(self, *, worktree, base_ref="HEAD"):
        return []


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


class FailingAdapter:
    def start(self, **_kwargs):
        return ProcessStartResult(
            status=AttemptStatus.FAILED,
            command_summary="claude -p <prompt>",
            error_category=ErrorCategory.LOGIN_REQUIRED,
            error_message="login required",
        )


class NoArtifactAdapter:
    def start(self, **_kwargs):
        return ProcessStartResult(
            status=AttemptStatus.SUCCEEDED,
            command_summary="claude -p <prompt>",
        )


def test_failed_headless_attempt_marks_session_interrupted(tmp_path) -> None:
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
            owner_id="tsk_test",
            objective="实现 feature",
            target_worktree_path=str(tmp_path),
        )

        assert created["status"] == "interrupted"
        assert created["lastErrorCategory"] == "login_required"
        assert created["attempts"][0]["status"] == "failed"
    finally:
        service.close()


def test_finished_attempt_without_plan_artifact_marks_session_interrupted(tmp_path) -> None:
    service = ExternalCodingSessionService(
        config=FakeConfig(tmp_path),
        git_ops=FakeGit(),
        quota_probe=FakeQuota(),
        adapter_factory=lambda: NoArtifactAdapter(),
    )
    try:
        created = service.start_session(
            session_id="sess_test",
            owner_type="task",
            owner_id="tsk_test",
            objective="实现 feature",
            target_worktree_path=str(tmp_path),
        )
        refreshed = service.refresh_session(created["codingSessionId"])

        assert refreshed["status"] == "interrupted"
        assert refreshed["lastErrorCategory"] == "missing_artifact"
        assert refreshed["attempts"][0]["status"] == "interrupted"
    finally:
        service.close()


class ModelUnavailableAdapter:
    """Adapter that fails with model_unavailable to test D7 (no downgrade)."""

    def start(self, **_kwargs):
        return ProcessStartResult(
            status=AttemptStatus.FAILED,
            command_summary="claude --effort max -p <prompt>",
            error_category=ErrorCategory.MODEL_UNAVAILABLE,
            error_message="max effort tier not available",
        )


def test_model_unavailable_interrupts_without_downgrade(tmp_path) -> None:
    """D7: Highest effort unavailable = interrupted, not downgraded."""
    service = ExternalCodingSessionService(
        config=FakeConfig(tmp_path),
        git_ops=FakeGit(),
        quota_probe=FakeQuota(),
        adapter_factory=lambda: ModelUnavailableAdapter(),
    )
    try:
        created = service.start_session(
            session_id="sess_test",
            owner_type="task",
            owner_id="tsk_model_unavail_test",
            objective="实现 feature",
            target_worktree_path=str(tmp_path),
        )

        assert created["status"] == "interrupted"
        assert created["lastErrorCategory"] == "model_unavailable"
        # No downgrade: session stays on same tool, no second attempt
        assert created["tool"] == "claude_code"
        assert len(created["attempts"]) == 1
        assert created["attempts"][0]["errorCategory"] == "model_unavailable"
    finally:
        service.close()


class DirtyPlanFakeGit:
    """Git that reports dirty files during plan phase (protocol violation)."""

    def head(self, worktree, ref="HEAD"):
        return "a" * 40

    def create_worktree(self, *, target_worktree, worktree_path, branch_name):
        worktree_path.mkdir(parents=True, exist_ok=True)

    def changed_files_against(self, *, worktree, base_ref="HEAD"):
        return ["src/secret_change.py"]


def test_plan_phase_dirty_worktree_marks_protocol_violation(tmp_path) -> None:
    """US1-AS5: Plan-phase file mutation = protocol violation."""
    service = ExternalCodingSessionService(
        config=FakeConfig(tmp_path),
        git_ops=DirtyPlanFakeGit(),
        quota_probe=FakeQuota(),
        adapter_factory=lambda: NoArtifactAdapter(),
    )
    try:
        created = service.start_session(
            session_id="sess_test",
            owner_type="task",
            owner_id="tsk_protocol_test",
            objective="实现 feature",
            target_worktree_path=str(tmp_path),
        )
        refreshed = service.refresh_session(created["codingSessionId"])

        assert refreshed["status"] == "interrupted"
        assert refreshed["lastErrorCategory"] == "protocol_violation"
        assert "secret_change" in (refreshed["lastErrorMessage"] or "")
    finally:
        service.close()


class ManagedAdapter:
    def __init__(self, artifact_dir: Path) -> None:
        self.artifact_dir = artifact_dir
        self.stop_calls = []
        self.start_calls = []

    def start(self, **kwargs):
        self.start_calls.append(kwargs)
        return ProcessStartResult(
            status=AttemptStatus.RUNNING,
            command_summary="managed plan",
            pid=12345,
        )

    def poll(self, *, pid, log_path):
        self.artifact_dir.joinpath("PLAN.md").write_text(
            """
            目标：完成测试 feature。计划改动：service。影响范围：src。
            假设/非目标：无。风险：无。测试计划：pytest。
            待确认问题：无。建议：继续。
            """,
            encoding="utf-8",
        )
        return ProcessStartResult(
            status=AttemptStatus.SUCCEEDED,
            command_summary="managed plan",
            pid=pid,
            exit_code=0,
            external_session_ref="thread-managed",
            log_path=str(log_path),
            log_tail="done",
        )

    def stop(self, *, pid, log_path, reason):
        self.stop_calls.append((pid, reason))
        return True


def test_refresh_persists_managed_process_terminal_state(tmp_path) -> None:
    adapter = ManagedAdapter(tmp_path / "data" / "coding_sessions" / "placeholder")
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
            owner_id="tsk_managed",
            objective="实现 feature",
            target_worktree_path=str(tmp_path),
        )
        adapter.artifact_dir = Path(created["artifactDir"])

        refreshed = service.refresh_session(created["codingSessionId"])

        assert refreshed["status"] == "plan_ready"
        assert refreshed["attempts"][0]["status"] == "succeeded"
        assert refreshed["attempts"][0]["exitCode"] == 0
        assert refreshed["attempts"][0]["externalSessionRef"] == "thread-managed"
        assert (
            service._repo.get_session(created["codingSessionId"]).external_session_ref
            == "thread-managed"
        )
    finally:
        service.close()


def test_abandon_stops_running_managed_attempt(tmp_path) -> None:
    adapter = ManagedAdapter(tmp_path)
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
            owner_id="tsk_stop",
            objective="实现 feature",
            target_worktree_path=str(tmp_path),
        )

        abandoned = service.abandon_session(
            coding_session_id=created["codingSessionId"], reason="stop now"
        )

        assert abandoned["status"] == "abandoned"
        assert adapter.stop_calls == [(12345, "session abandoned")]
        assert abandoned["attempts"][0]["status"] == "interrupted"
    finally:
        service.close()


class StillRunningAdapter(ManagedAdapter):
    def poll(self, *, pid, log_path):
        return ProcessStartResult(
            status=AttemptStatus.RUNNING,
            command_summary="managed plan",
            pid=pid,
            log_path=str(log_path),
        )


def test_plan_protocol_violation_stops_running_attempt(tmp_path) -> None:
    adapter = StillRunningAdapter(tmp_path)
    service = ExternalCodingSessionService(
        config=FakeConfig(tmp_path),
        git_ops=DirtyPlanFakeGit(),
        quota_probe=FakeQuota(),
        adapter_factory=lambda: adapter,
    )
    try:
        created = service.start_session(
            session_id="sess_test",
            owner_type="task",
            owner_id="tsk_protocol_stop",
            objective="实现 feature",
            target_worktree_path=str(tmp_path),
        )

        refreshed = service.refresh_session(created["codingSessionId"])

        assert refreshed["status"] == "interrupted"
        assert refreshed["lastErrorCategory"] == "protocol_violation"
        assert adapter.stop_calls == [(12345, "plan phase protocol violation")]
        assert refreshed["attempts"][0]["status"] == "interrupted"
    finally:
        service.close()


def test_interactive_launch_uses_real_managed_adapter(tmp_path) -> None:
    adapter = StillRunningAdapter(tmp_path)
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
            owner_id="tsk_interactive",
            objective="实现 feature",
            launch_mode="interactive",
            target_worktree_path=str(tmp_path),
        )

        assert created["attempts"][0]["pid"] == 12345
        assert created["attempts"][0]["status"] == "running"
        assert adapter.start_calls[0]["launch_mode"].value == "interactive"
    finally:
        service.abandon_session(coding_session_id=created["codingSessionId"], reason="test cleanup")
        service.close()
