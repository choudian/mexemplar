import json
from pathlib import Path

import pytest

from src.business.external_coding import service as external_coding_service
from src.business.external_coding.cli_adapters import CliExternalCodingAdapter
from src.business.external_coding.models import (
    AttemptStatus,
    ErrorCategory,
    ExternalCodingTool,
    ProcessStartResult,
    QuotaSignal,
    QuotaState,
)
from src.business.external_coding.service import ExternalCodingSessionService
from src.data.repos.external_coding_session_repository import ExternalCodingSessionRepository
from src.execution.external_coding_process import ExternalProcessTerminationOutcome
from src.execution import external_coding_process
from src.execution.external_coding_process import ExternalCodingProcessRunner


def _remove_registered_pid(pid: int) -> None:
    for managed in list(ExternalCodingProcessRunner._registry.values()):
        if managed.process.pid == pid:
            ExternalCodingProcessRunner._remove_managed(managed)


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

    def get_external_coding_claude_effort(self):
        return "max"

    def get_external_coding_codex_reasoning_effort(self):
        return "xhigh"

    def get_external_coding_plan_timeout_seconds(self):
        return 30

    def get_external_coding_run_timeout_seconds(self):
        return 60


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


class NeverStartAdapter:
    def __init__(self) -> None:
        self.start_calls = 0

    def start(self, **_kwargs):
        self.start_calls += 1
        raise AssertionError("process start must not be reached")


def test_prompt_write_failure_closes_reserved_attempt_before_process_start(
    tmp_path, monkeypatch
) -> None:
    repo = ExternalCodingSessionRepository()
    adapter = NeverStartAdapter()
    service = ExternalCodingSessionService(
        repo=repo,
        config=FakeConfig(tmp_path),
        git_ops=FakeGit(),
        quota_probe=FakeQuota(),
        adapter_factory=lambda: adapter,
    )
    monkeypatch.setattr(
        external_coding_service,
        "write_attempt_prompt",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )

    try:
        created = service.start_session(
            session_id="sess_test",
            owner_type="task",
            owner_id="tsk_prompt_failure",
            objective="实现 feature",
            target_worktree_path=str(tmp_path),
        )

        assert adapter.start_calls == 0
        assert created["status"] == "interrupted"
        assert created["attempts"][0]["status"] == "failed"
        assert created["lastErrorMessage"] == "external coding attempt prompt could not be created"
    finally:
        repo.close()


def test_prompt_failure_reservation_close_can_recover_on_refresh(tmp_path, monkeypatch) -> None:
    repo = ExternalCodingSessionRepository()
    adapter = NeverStartAdapter()
    service = ExternalCodingSessionService(
        repo=repo,
        config=FakeConfig(tmp_path),
        git_ops=FakeGit(),
        quota_probe=FakeQuota(),
        adapter_factory=lambda: adapter,
    )
    monkeypatch.setattr(
        external_coding_service,
        "write_attempt_prompt",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )
    original_project = repo.update_session_and_attempt
    fail_once = True

    def _fail_first_projection(**kwargs):
        nonlocal fail_once
        if fail_once:
            fail_once = False
            raise RuntimeError("sqlite commit failed")
        return original_project(**kwargs)

    monkeypatch.setattr(repo, "update_session_and_attempt", _fail_first_projection)

    try:
        with pytest.raises(RuntimeError, match="prompt creation failed"):
            service.start_session(
                session_id="sess_test",
                owner_type="task",
                owner_id="tsk_prompt_close_recovery",
                objective="实现 feature",
                target_worktree_path=str(tmp_path),
            )

        row = repo.list_for_owner("task", "tsk_prompt_close_recovery")[0]
        reserved = repo.get_active_attempt(row.coding_session_id)
        assert reserved is not None
        assert reserved.launch_started is False
        assert adapter.start_calls == 0

        refreshed = service.refresh_session(row.coding_session_id)

        assert refreshed["status"] == "interrupted"
        assert refreshed["attempts"][0]["status"] == "failed"
        assert repo.get_active_attempt(row.coding_session_id) is None
    finally:
        repo.close()


def test_abandon_between_reservation_and_launch_prevents_process_start(
    tmp_path, monkeypatch
) -> None:
    repo = ExternalCodingSessionRepository()
    adapter = NeverStartAdapter()
    service = ExternalCodingSessionService(
        repo=repo,
        config=FakeConfig(tmp_path),
        git_ops=FakeGit(),
        quota_probe=FakeQuota(),
        adapter_factory=lambda: adapter,
    )
    original_write_prompt = external_coding_service.write_attempt_prompt

    def _abandon_after_prompt(artifact_dir, **kwargs):
        prompt_path = original_write_prompt(artifact_dir, **kwargs)
        service.abandon_session(
            coding_session_id=Path(artifact_dir).name,
            reason="concurrent abandon before launch",
        )
        return prompt_path

    monkeypatch.setattr(
        external_coding_service,
        "write_attempt_prompt",
        _abandon_after_prompt,
    )

    try:
        created = service.start_session(
            session_id="sess_test",
            owner_type="task",
            owner_id="tsk_launch_cas",
            objective="实现 feature",
            target_worktree_path=str(tmp_path),
        )

        assert created["status"] == "abandoned"
        assert created["attempts"][0]["status"] == "interrupted"
        assert adapter.start_calls == 0
        attempt = repo.get_attempt(created["attempts"][0]["attemptId"])
        assert attempt is not None
        assert attempt.launch_started is False
        assert attempt.pid is None
    finally:
        repo.close()


def test_adapter_factory_failure_closes_unlaunched_reservation(tmp_path) -> None:
    repo = ExternalCodingSessionRepository()
    factory_calls = 0

    def _broken_factory():
        nonlocal factory_calls
        factory_calls += 1
        raise RuntimeError("private adapter construction failure")

    service = ExternalCodingSessionService(
        repo=repo,
        config=FakeConfig(tmp_path),
        git_ops=FakeGit(),
        quota_probe=FakeQuota(),
        adapter_factory=_broken_factory,
    )

    try:
        created = service.start_session(
            session_id="sess_test",
            owner_type="task",
            owner_id="tsk_adapter_factory_failure",
            objective="实现 feature",
            target_worktree_path=str(tmp_path),
        )

        assert factory_calls == 1
        assert created["status"] == "interrupted"
        attempt = repo.list_attempts(created["codingSessionId"])[0]
        assert attempt.status == "failed"
        assert attempt.launch_started is False
        assert attempt.pid is None
        assert repo.get_active_attempt(created["codingSessionId"]) is None
        assert "private adapter construction failure" not in json.dumps(created)
    finally:
        repo.close()


def test_attempt_reservation_failure_never_starts_process(tmp_path, monkeypatch) -> None:
    repo = ExternalCodingSessionRepository()
    adapter = NeverStartAdapter()
    service = ExternalCodingSessionService(
        repo=repo,
        config=FakeConfig(tmp_path),
        git_ops=FakeGit(),
        quota_probe=FakeQuota(),
        adapter_factory=lambda: adapter,
    )
    monkeypatch.setattr(
        repo,
        "add_attempt",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("sqlite locked")),
    )

    try:
        created = service.start_session(
            session_id="sess_test",
            owner_type="task",
            owner_id="tsk_reservation_failure",
            objective="实现 feature",
            target_worktree_path=str(tmp_path),
        )

        assert adapter.start_calls == 0
        assert created["status"] == "interrupted"
        assert created["attempts"] == []
        assert created["lastErrorMessage"] == "external coding attempt could not be reserved"
    finally:
        repo.close()


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
            termination_unconfirmed=True,
        )

    def poll(self, *, pid, log_path, **_ownership):
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

    def stop(self, *, pid, log_path, reason, **_ownership):
        self.stop_calls.append((pid, reason))
        return ExternalProcessTerminationOutcome.CONFIRMED_STOPPED


def test_started_process_is_stopped_when_attempt_result_persistence_fails(
    tmp_path, monkeypatch
) -> None:
    repo = ExternalCodingSessionRepository()
    adapter = ManagedAdapter(tmp_path)
    service = ExternalCodingSessionService(
        repo=repo,
        config=FakeConfig(tmp_path),
        git_ops=FakeGit(),
        quota_probe=FakeQuota(),
        adapter_factory=lambda: adapter,
    )
    original_update_attempt = repo.update_attempt
    failed_once = False

    def _fail_first_update(attempt_id, **fields):
        nonlocal failed_once
        if not failed_once and fields.get("pid") == 12345:
            failed_once = True
            raise RuntimeError("sqlite commit failed")
        return original_update_attempt(attempt_id, **fields)

    monkeypatch.setattr(repo, "update_attempt", _fail_first_update)

    try:
        created = service.start_session(
            session_id="sess_test",
            owner_type="task",
            owner_id="tsk_attempt_persistence",
            objective="实现 feature",
            target_worktree_path=str(tmp_path),
        )

        assert adapter.stop_calls == [(12345, "attempt state persistence failed")]
        assert created["status"] == "interrupted"
        assert created["attempts"][0]["status"] == "failed"
        assert created["lastErrorMessage"] == "external coding process state could not be persisted"
    finally:
        repo.close()


def test_status_and_marker_write_failure_persists_restart_safe_process_identity(
    tmp_path, monkeypatch
) -> None:
    class SurvivingProcess:
        pid = 48205

        def poll(self):
            return None

    process = SurvivingProcess()
    monkeypatch.setattr(
        external_coding_process.subprocess,
        "Popen",
        lambda *_args, **_kwargs: process,
    )
    monkeypatch.setattr(
        external_coding_process,
        "_process_create_time",
        lambda _pid: 1234.5,
    )
    monkeypatch.setattr(
        external_coding_process,
        "terminate_process_tree",
        lambda _process: False,
    )
    monkeypatch.setattr(
        external_coding_process,
        "_write_status",
        lambda *_args: (_ for _ in ()).throw(OSError("status storage unavailable")),
    )

    repo = ExternalCodingSessionRepository()
    runner = ExternalCodingProcessRunner()
    config = FakeConfig(tmp_path)
    adapter = CliExternalCodingAdapter(config=config, runner=runner)
    service = ExternalCodingSessionService(
        repo=repo,
        config=config,
        git_ops=FakeGit(),
        quota_probe=FakeQuota(),
        adapter_factory=lambda: adapter,
    )
    try:
        created = service.start_session(
            session_id="sess_test",
            owner_type="task",
            owner_id="tsk_restart_safe_ownership",
            objective="实现 feature",
            target_worktree_path=str(tmp_path),
        )

        attempt = repo.list_attempts(created["codingSessionId"])[0]
        assert attempt.status == "running"
        assert attempt.pid == process.pid
        assert attempt.process_create_time == 1234.5
        assert attempt.termination_unconfirmed is True

        _remove_registered_pid(process.pid)
        refreshed = service.refresh_session(created["codingSessionId"])
        assert refreshed["status"] == "planning"
        assert refreshed["attempts"][0]["status"] == "running"
        with pytest.raises(ValueError, match="active external coding attempt"):
            service.resume_session(coding_session_id=created["codingSessionId"])
    finally:
        _remove_registered_pid(process.pid)
        repo.close()


def test_restart_with_missing_create_time_does_not_accept_terminal_marker(tmp_path) -> None:
    repo = ExternalCodingSessionRepository()
    managed_adapter = ManagedAdapter(tmp_path)
    config = FakeConfig(tmp_path)
    service = ExternalCodingSessionService(
        repo=repo,
        config=config,
        git_ops=FakeGit(),
        quota_probe=FakeQuota(),
        adapter_factory=lambda: managed_adapter,
    )

    try:
        created = service.start_session(
            session_id="sess_test",
            owner_type="task",
            owner_id="tsk_missing_create_time",
            objective="实现 feature",
            target_worktree_path=str(tmp_path),
        )
        attempt = repo.list_attempts(created["codingSessionId"])[0]
        assert attempt.process_create_time is None
        repo.update_attempt(
            attempt.attempt_id,
            expected_status=AttemptStatus.RUNNING.value,
            termination_unconfirmed=True,
        )
        log_path = Path(attempt.log_path)
        status_path = external_coding_process._status_path(log_path)
        status_path.parent.mkdir(parents=True, exist_ok=True)
        status_path.write_text(
            json.dumps(
                {
                    "status": "succeeded",
                    "pid": attempt.pid,
                    "processCreateTime": 100.0,
                    "exitCode": 0,
                }
            ),
            encoding="utf-8",
        )
        runner = ExternalCodingProcessRunner()
        service._adapter_factory = lambda: CliExternalCodingAdapter(
            config=config,
            runner=runner,
        )

        refreshed = service.refresh_session(created["codingSessionId"])

        assert refreshed["status"] == "planning"
        assert refreshed["attempts"][0]["status"] == "running"
        current = repo.get_attempt(attempt.attempt_id)
        assert current is not None
        assert current.process_create_time is None
        assert current.termination_unconfirmed is True

        refreshed_again = service.refresh_session(created["codingSessionId"])
        assert refreshed_again["status"] == "planning"
        assert refreshed_again["attempts"][0]["status"] == "running"
        with pytest.raises(ValueError, match="active external coding attempt"):
            service.resume_session(coding_session_id=created["codingSessionId"])
    finally:
        repo.close()


def test_started_process_is_stopped_when_session_reference_persistence_fails(
    tmp_path, monkeypatch
) -> None:
    class ReferenceAdapter(ManagedAdapter):
        def start(self, **kwargs):
            self.start_calls.append(kwargs)
            return ProcessStartResult(
                status=AttemptStatus.RUNNING,
                command_summary="managed plan",
                pid=12345,
                termination_unconfirmed=True,
                external_session_ref="thread-started",
            )

    repo = ExternalCodingSessionRepository()
    adapter = ReferenceAdapter(tmp_path)
    service = ExternalCodingSessionService(
        repo=repo,
        config=FakeConfig(tmp_path),
        git_ops=FakeGit(),
        quota_probe=FakeQuota(),
        adapter_factory=lambda: adapter,
    )
    original_project = repo.update_session_and_attempt
    failed_once = False

    def _fail_reference_update(**kwargs):
        nonlocal failed_once
        if not failed_once and set(kwargs["session_fields"]) == {"external_session_ref"}:
            failed_once = True
            raise RuntimeError("sqlite commit failed")
        return original_project(**kwargs)

    monkeypatch.setattr(repo, "update_session_and_attempt", _fail_reference_update)

    try:
        created = service.start_session(
            session_id="sess_test",
            owner_type="task",
            owner_id="tsk_reference_persistence",
            objective="实现 feature",
            target_worktree_path=str(tmp_path),
        )

        assert adapter.stop_calls == [(12345, "attempt state persistence failed")]
        assert created["status"] == "interrupted"
        assert created["attempts"][0]["status"] == "failed"
    finally:
        repo.close()


def test_unconfirmed_process_ownership_persistence_failure_is_explicit(
    tmp_path, monkeypatch
) -> None:
    class UnconfirmedStopAdapter(ManagedAdapter):
        def stop(self, *, pid, log_path, reason, **_ownership):
            self.stop_calls.append((pid, reason))
            if len(self.stop_calls) == 1:
                return ExternalProcessTerminationOutcome.UNCONFIRMED
            return ExternalProcessTerminationOutcome.CONFIRMED_STOPPED

        def poll(self, *, pid, log_path, **_ownership):
            return ProcessStartResult(
                status=AttemptStatus.RUNNING,
                command_summary="managed plan",
                pid=12345,
                termination_unconfirmed=True,
                log_path=str(log_path),
            )

    repo = ExternalCodingSessionRepository()
    adapter = UnconfirmedStopAdapter(tmp_path)
    service = ExternalCodingSessionService(
        repo=repo,
        config=FakeConfig(tmp_path),
        git_ops=FakeGit(),
        quota_probe=FakeQuota(),
        adapter_factory=lambda: adapter,
    )
    original_update_attempt = repo.update_attempt
    original_project = repo.update_session_and_attempt
    rejected_writes = 0

    def _reject_pid_persistence(attempt_id, **fields):
        nonlocal rejected_writes
        if fields.get("pid") == 12345 and rejected_writes < 2:
            rejected_writes += 1
            raise RuntimeError("sqlite commit failed")
        return original_update_attempt(attempt_id, **fields)

    monkeypatch.setattr(repo, "update_attempt", _reject_pid_persistence)

    def _reject_ownership_projection(**kwargs):
        nonlocal rejected_writes
        if kwargs["attempt_fields"].get("pid") == 12345 and rejected_writes < 2:
            rejected_writes += 1
            raise RuntimeError("sqlite commit failed")
        return original_project(**kwargs)

    monkeypatch.setattr(repo, "update_session_and_attempt", _reject_ownership_projection)

    try:
        with pytest.raises(
            RuntimeError, match="external coding process ownership could not be persisted"
        ) as caught:
            service.start_session(
                session_id="sess_test",
                owner_type="task",
                owner_id="tsk_ownership_persistence",
                objective="实现 feature",
                target_worktree_path=str(tmp_path),
            )
        assert "pid 12345" in str(caught.value)

        row = repo.list_for_owner("task", "tsk_ownership_persistence")[0]
        attempt = repo.list_attempts(row.coding_session_id)[0]
        assert attempt.status == "running"
        assert attempt.pid is None
        assert adapter.stop_calls == [(12345, "attempt state persistence failed")]

        abandoned = service.abandon_session(
            coding_session_id=row.coding_session_id,
            reason="recover after database outage",
        )
        assert abandoned["status"] == "abandoned"
        assert abandoned["attempts"][0]["status"] == "interrupted"
        assert adapter.stop_calls[-1] == (12345, "session abandoned")
    finally:
        repo.close()


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


def test_abandon_projection_failure_keeps_session_and_attempt_retryable(
    tmp_path, monkeypatch
) -> None:
    repo = ExternalCodingSessionRepository()
    adapter = ManagedAdapter(tmp_path)
    service = ExternalCodingSessionService(
        repo=repo,
        config=FakeConfig(tmp_path),
        git_ops=FakeGit(),
        quota_probe=FakeQuota(),
        adapter_factory=lambda: adapter,
    )
    original_project = repo.update_session_and_attempt
    fail_once = True

    def _fail_first_abandon(**kwargs):
        nonlocal fail_once
        if fail_once and kwargs["session_fields"].get("status") == "abandoned":
            fail_once = False
            raise RuntimeError("sqlite commit failed")
        return original_project(**kwargs)

    monkeypatch.setattr(repo, "update_session_and_attempt", _fail_first_abandon)

    try:
        created = service.start_session(
            session_id="sess_test",
            owner_type="task",
            owner_id="tsk_abandon_atomic",
            objective="实现 feature",
            target_worktree_path=str(tmp_path),
        )
        attempt_id = created["attempts"][0]["attemptId"]

        with pytest.raises(RuntimeError, match="sqlite commit failed"):
            service.abandon_session(
                coding_session_id=created["codingSessionId"],
                reason="stop atomically",
            )

        session_after_failure = repo.get_session(created["codingSessionId"])
        attempt_after_failure = repo.get_attempt(attempt_id)
        assert session_after_failure is not None
        assert session_after_failure.status == "planning"
        assert attempt_after_failure is not None
        assert attempt_after_failure.status == "running"

        abandoned = service.abandon_session(
            coding_session_id=created["codingSessionId"],
            reason="retry stop",
        )
        assert abandoned["status"] == "abandoned"
        assert abandoned["attempts"][0]["status"] == "interrupted"
        assert len(adapter.stop_calls) == 2
    finally:
        repo.close()


class StillRunningAdapter(ManagedAdapter):
    def poll(self, *, pid, log_path, **_ownership):
        return ProcessStartResult(
            status=AttemptStatus.RUNNING,
            command_summary="managed plan",
            pid=pid,
            termination_unconfirmed=True,
            log_path=str(log_path),
        )


def test_poll_failure_preserves_running_state_and_blocks_duplicate_resume(tmp_path) -> None:
    class PollFailureAdapter(ManagedAdapter):
        def poll(self, *, pid, log_path, **_ownership):
            raise OSError("status metadata is temporarily unavailable")

    adapter = PollFailureAdapter(tmp_path)
    service = ExternalCodingSessionService(
        config=FakeConfig(tmp_path),
        git_ops=FakeGit(),
        quota_probe=FakeQuota(),
        adapter_factory=lambda: adapter,
    )
    created = None
    try:
        created = service.start_session(
            session_id="sess_test",
            owner_type="task",
            owner_id="tsk_poll_failure",
            objective="实现 feature",
            target_worktree_path=str(tmp_path),
        )

        refreshed = service.refresh_session(created["codingSessionId"])

        assert refreshed["status"] == "planning"
        assert refreshed["attempts"][0]["status"] == "running"
        assert refreshed["attempts"][0]["errorCategory"] == "process_error"
        assert adapter.stop_calls == []
        with pytest.raises(ValueError, match="active external coding attempt"):
            service.resume_session(coding_session_id=created["codingSessionId"])
    finally:
        if created is not None:
            service.abandon_session(
                coding_session_id=created["codingSessionId"], reason="test cleanup"
            )
        service.close()


def test_terminal_attempt_and_session_projection_roll_back_together(tmp_path, monkeypatch) -> None:
    class TerminalFailureAdapter(ManagedAdapter):
        def poll(self, *, pid, log_path, **_ownership):
            return ProcessStartResult(
                status=AttemptStatus.FAILED,
                command_summary="managed plan",
                pid=pid,
                exit_code=1,
                error_category=ErrorCategory.PROCESS_ERROR,
                error_message="external process failed",
            )

    repo = ExternalCodingSessionRepository()
    adapter = TerminalFailureAdapter(tmp_path)
    service = ExternalCodingSessionService(
        repo=repo,
        config=FakeConfig(tmp_path),
        git_ops=FakeGit(),
        quota_probe=FakeQuota(),
        adapter_factory=lambda: adapter,
    )
    original_project = repo.update_session_and_attempt
    fail_terminal_projection = True

    def _fail_first_terminal_projection(**kwargs):
        nonlocal fail_terminal_projection
        if fail_terminal_projection and kwargs["session_fields"].get("status") == "interrupted":
            fail_terminal_projection = False
            raise RuntimeError("sqlite commit failed")
        return original_project(**kwargs)

    monkeypatch.setattr(repo, "update_session_and_attempt", _fail_first_terminal_projection)

    try:
        created = service.start_session(
            session_id="sess_test",
            owner_type="task",
            owner_id="tsk_terminal_projection",
            objective="实现 feature",
            target_worktree_path=str(tmp_path),
        )

        first = service.refresh_session(created["codingSessionId"])
        assert first["status"] == "planning"
        assert first["attempts"][0]["status"] == "running"
        with pytest.raises(ValueError, match="active external coding attempt"):
            service.resume_session(coding_session_id=created["codingSessionId"])

        second = service.refresh_session(created["codingSessionId"])
        assert second["status"] == "interrupted"
        assert second["attempts"][0]["status"] == "failed"
        assert second["lastErrorCategory"] == "process_error"
    finally:
        repo.close()


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


def test_protocol_violation_projection_failure_keeps_rows_retryable(tmp_path, monkeypatch) -> None:
    repo = ExternalCodingSessionRepository()
    adapter = StillRunningAdapter(tmp_path)
    service = ExternalCodingSessionService(
        repo=repo,
        config=FakeConfig(tmp_path),
        git_ops=DirtyPlanFakeGit(),
        quota_probe=FakeQuota(),
        adapter_factory=lambda: adapter,
    )
    original_project = repo.update_session_and_attempt
    fail_once = True

    def _fail_first_protocol_projection(**kwargs):
        nonlocal fail_once
        if (
            fail_once
            and kwargs["session_fields"].get("last_error_category") == "protocol_violation"
        ):
            fail_once = False
            raise RuntimeError("sqlite commit failed")
        return original_project(**kwargs)

    monkeypatch.setattr(
        repo,
        "update_session_and_attempt",
        _fail_first_protocol_projection,
    )

    try:
        created = service.start_session(
            session_id="sess_test",
            owner_type="task",
            owner_id="tsk_protocol_atomic",
            objective="实现 feature",
            target_worktree_path=str(tmp_path),
        )
        attempt_id = created["attempts"][0]["attemptId"]

        with pytest.raises(RuntimeError, match="sqlite commit failed"):
            service.refresh_session(created["codingSessionId"])

        session_after_failure = repo.get_session(created["codingSessionId"])
        attempt_after_failure = repo.get_attempt(attempt_id)
        assert session_after_failure is not None
        assert session_after_failure.status == "planning"
        assert attempt_after_failure is not None
        assert attempt_after_failure.status == "running"

        refreshed = service.refresh_session(created["codingSessionId"])
        assert refreshed["status"] == "interrupted"
        assert refreshed["lastErrorCategory"] == "protocol_violation"
        assert refreshed["attempts"][0]["status"] == "interrupted"
        assert len(adapter.stop_calls) == 2
    finally:
        repo.close()


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
