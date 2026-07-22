import pytest
from sqlalchemy.exc import IntegrityError

from src.business.external_coding.serializers import attempt_to_dict
from src.data.repos.external_coding_session_repository import ExternalCodingSessionRepository


def test_external_coding_repository_persists_session_attempt_and_audit_rows() -> None:
    with ExternalCodingSessionRepository() as repo:
        session = repo.create_session(
            coding_session_id="ecs_test",
            session_id="sess_test",
            owner_type="task",
            owner_id="tsk_test",
            parent_session_id=None,
            tool="claude_code",
            launch_mode="headless",
            status="planning",
            phase="plan",
            selected_reason="test",
            quota_state="available",
            worktree_path="worktree",
            branch_name="coding/ecs_test",
            base_commit="a" * 40,
            artifact_dir="artifacts",
            handoff_path="artifacts/HANDOFF.md",
            plan_path="artifacts/PLAN.md",
            result_path="artifacts/RESULT.md",
        )
        repo.update_session(session.coding_session_id, status="plan_ready")
        attempt = repo.add_attempt(
            coding_session_id=session.coding_session_id,
            phase="plan",
            launch_mode="headless",
            status="running",
            command_summary="claude -p <prompt>",
            pid=42100,
            process_create_time=1234.5,
            termination_unconfirmed=True,
            launch_started=True,
        )
        repo.update_attempt(
            attempt.attempt_id,
            status="succeeded",
            termination_unconfirmed=False,
        )
        repo.add_quota_observation(
            tool="claude_code",
            state="available",
            source="test",
            confidence=1.0,
            safe_detail="ok",
        )
        merge = repo.add_merge_record(
            coding_session_id=session.coding_session_id,
            target_branch="main",
            target_worktree_path=".",
            pre_merge_head="a" * 40,
            coding_branch_head="b" * 40,
            dirty_files=["src/a.py"],
            changed_files=["src/a.py"],
            overlap_files=["src/a.py"],
            conflict_risk="overlap",
        )
        repo.add_rollback_decision(
            coding_session_id=session.coding_session_id,
            merge_record_id=merge.merge_record_id,
            intent_summary="用户认为偏离目标",
            chosen_strategy="revert_commit",
            requires_confirmation=True,
        )

        current = repo.get_session("ecs_test")
        assert current is not None
        assert current.status == "plan_ready"
        assert current.base_commit == "a" * 40
        assert repo.list_for_owner("task", "tsk_test")[0].coding_session_id == "ecs_test"
        assert (
            repo.list_for_owners("task", ["tsk_test", "tsk_missing"])[0].coding_session_id
            == "ecs_test"
        )
        stored_attempt = repo.list_attempts("ecs_test")[0]
        assert stored_attempt.status == "succeeded"
        assert stored_attempt.pid == 42100
        assert stored_attempt.process_create_time == 1234.5
        assert stored_attempt.termination_unconfirmed is False
        public_attempt = attempt_to_dict(stored_attempt)
        assert "processCreateTime" not in public_attempt
        assert "terminationUnconfirmed" not in public_attempt
        assert "launchStarted" not in public_attempt
        assert repo.latest_quota_by_tool()["claude_code"].safe_detail == "ok"
        assert repo.list_merge_records("ecs_test")[0].conflict_risk == "overlap"
        assert repo.list_rollback_decisions("ecs_test")[0].requires_confirmation is True


@pytest.mark.parametrize("plan_path,result_path", [("", "RESULT.md"), ("PLAN.md", "")])
def test_external_coding_repository_rejects_incomplete_artifact_paths(
    plan_path, result_path
) -> None:
    with ExternalCodingSessionRepository() as repo:
        with pytest.raises(ValueError, match="plan_path and result_path are required"):
            repo.create_session(
                coding_session_id="ecs_incomplete_paths",
                session_id="sess_test",
                owner_type="task",
                owner_id="tsk_test",
                parent_session_id=None,
                tool="claude_code",
                launch_mode="headless",
                status="planning",
                phase="plan",
                worktree_path="worktree",
                branch_name="coding/ecs_incomplete_paths",
                base_commit="a" * 40,
                artifact_dir="artifacts",
                handoff_path="artifacts/HANDOFF.md",
                plan_path=plan_path,
                result_path=result_path,
            )


def test_external_coding_repository_keeps_artifact_paths_immutable() -> None:
    with ExternalCodingSessionRepository() as repo:
        session = repo.create_session(
            coding_session_id="ecs_immutable_paths",
            session_id="sess_test",
            owner_type="task",
            owner_id="tsk_test",
            parent_session_id=None,
            tool="claude_code",
            launch_mode="headless",
            status="planning",
            phase="plan",
            worktree_path="worktree",
            branch_name="coding/ecs_immutable_paths",
            base_commit="a" * 40,
            artifact_dir="artifacts",
            handoff_path="artifacts/HANDOFF.md",
            plan_path="artifacts/PLAN.md",
            result_path="artifacts/RESULT.md",
        )

        with pytest.raises(ValueError, match="artifact paths are immutable"):
            repo.update_session(session.coding_session_id, plan_path=None)

        current = repo.get_session(session.coding_session_id)
        assert current is not None
        assert current.plan_path == "artifacts/PLAN.md"
        assert current.result_path == "artifacts/RESULT.md"


def test_external_coding_repository_projects_session_and_attempt_atomically(
    monkeypatch,
) -> None:
    with ExternalCodingSessionRepository() as repo:
        session = repo.create_session(
            coding_session_id="ecs_atomic",
            session_id="sess_atomic",
            owner_type="task",
            owner_id="tsk_atomic",
            parent_session_id=None,
            tool="claude_code",
            launch_mode="headless",
            status="planning",
            phase="plan",
            worktree_path="worktree",
            branch_name="coding/ecs_atomic",
            base_commit="a" * 40,
            artifact_dir="artifacts",
            handoff_path="artifacts/HANDOFF.md",
            plan_path="artifacts/PLAN.md",
            result_path="artifacts/RESULT.md",
        )
        attempt = repo.add_attempt(
            coding_session_id=session.coding_session_id,
            phase="plan",
            launch_mode="headless",
            status="running",
            termination_unconfirmed=True,
            launch_started=True,
        )

        def _fail_after_flush() -> None:
            repo.session.flush()
            raise RuntimeError("simulated commit failure")

        monkeypatch.setattr(repo, "_commit", _fail_after_flush)
        with pytest.raises(RuntimeError, match="simulated commit failure"):
            repo.update_session_and_attempt(
                coding_session_id=session.coding_session_id,
                attempt_id=attempt.attempt_id,
                session_fields={"status": "interrupted"},
                attempt_fields={"status": "failed", "termination_unconfirmed": False},
            )

        current_session = repo.get_session(session.coding_session_id)
        current_attempt = repo.get_attempt(attempt.attempt_id)
        assert current_session is not None and current_session.status == "planning"
        assert current_attempt is not None and current_attempt.status == "running"
        assert current_attempt.termination_unconfirmed is True


def test_external_coding_repository_allows_only_one_active_attempt_per_session() -> None:
    with ExternalCodingSessionRepository() as repo:
        session = repo.create_session(
            coding_session_id="ecs_one_active",
            session_id="sess_one_active",
            owner_type="task",
            owner_id="tsk_one_active",
            parent_session_id=None,
            tool="claude_code",
            launch_mode="headless",
            status="planning",
            phase="plan",
            worktree_path="worktree",
            branch_name="coding/ecs_one_active",
            base_commit="a" * 40,
            artifact_dir="artifacts",
            handoff_path="artifacts/HANDOFF.md",
            plan_path="artifacts/PLAN.md",
            result_path="artifacts/RESULT.md",
        )
        first = repo.add_attempt(
            coding_session_id=session.coding_session_id,
            phase="plan",
            launch_mode="headless",
            status="running",
            termination_unconfirmed=True,
        )

        with pytest.raises(IntegrityError):
            repo.add_attempt(
                coding_session_id=session.coding_session_id,
                phase="plan",
                launch_mode="headless",
                status="running",
                termination_unconfirmed=True,
            )

        assert repo.get_active_attempt(session.coding_session_id).attempt_id == first.attempt_id


def test_external_coding_repository_rejects_terminal_unconfirmed_state() -> None:
    with ExternalCodingSessionRepository() as repo:
        session = repo.create_session(
            coding_session_id="ecs_terminal_invariant",
            session_id="sess_terminal_invariant",
            owner_type="task",
            owner_id="tsk_terminal_invariant",
            parent_session_id=None,
            tool="claude_code",
            launch_mode="headless",
            status="planning",
            phase="plan",
            worktree_path="worktree",
            branch_name="coding/ecs_terminal_invariant",
            base_commit="a" * 40,
            artifact_dir="artifacts",
            handoff_path="artifacts/HANDOFF.md",
            plan_path="artifacts/PLAN.md",
            result_path="artifacts/RESULT.md",
        )
        attempt = repo.add_attempt(
            coding_session_id=session.coding_session_id,
            phase="plan",
            launch_mode="headless",
            status="running",
            termination_unconfirmed=True,
        )

        with pytest.raises(ValueError, match="cannot retain process ownership"):
            repo.update_session_and_attempt(
                coding_session_id=session.coding_session_id,
                attempt_id=attempt.attempt_id,
                session_fields={"status": "interrupted"},
                attempt_fields={
                    "status": "failed",
                    "termination_unconfirmed": True,
                },
            )

        current_session = repo.get_session(session.coding_session_id)
        current = repo.get_attempt(attempt.attempt_id)
        assert current_session is not None and current_session.status == "planning"
        assert current is not None and current.status == "running"


def test_external_coding_repository_enforces_spawn_and_ownership_state() -> None:
    with ExternalCodingSessionRepository() as repo:
        session = repo.create_session(
            coding_session_id="ecs_attempt_state",
            session_id="sess_attempt_state",
            owner_type="task",
            owner_id="tsk_attempt_state",
            parent_session_id=None,
            tool="claude_code",
            launch_mode="headless",
            status="planning",
            phase="plan",
            worktree_path="worktree",
            branch_name="coding/ecs_attempt_state",
            base_commit="a" * 40,
            artifact_dir="artifacts",
            handoff_path="artifacts/HANDOFF.md",
            plan_path="artifacts/PLAN.md",
            result_path="artifacts/RESULT.md",
        )

        with pytest.raises(ValueError, match="must retain process ownership"):
            repo.add_attempt(
                coding_session_id=session.coding_session_id,
                phase="plan",
                launch_mode="headless",
                status="running",
            )
        with pytest.raises(ValueError, match="unlaunched.*process identity"):
            repo.add_attempt(
                coding_session_id=session.coding_session_id,
                phase="plan",
                launch_mode="headless",
                status="running",
                pid=42110,
                process_create_time=100.0,
                termination_unconfirmed=True,
                launch_started=False,
            )

        reservation = repo.add_attempt(
            coding_session_id=session.coding_session_id,
            phase="plan",
            launch_mode="headless",
            status="running",
            termination_unconfirmed=True,
            launch_started=False,
        )
        with pytest.raises(ValueError, match="unlaunched.*process identity"):
            repo.update_attempt(
                reservation.attempt_id,
                pid=42110,
                process_create_time=100.0,
            )

        launched = repo.mark_attempt_launch_started(reservation.attempt_id)
        assert launched is not None and launched.launch_started is True
        assert repo.mark_attempt_launch_started(reservation.attempt_id) is None
        with pytest.raises(ValueError, match="unsupported.*launch_started"):
            repo.update_attempt(
                reservation.attempt_id,
                expected_status="running",
                launch_started=False,
            )
        with pytest.raises(ValueError, match="must retain process ownership"):
            repo.update_attempt(
                reservation.attempt_id,
                expected_status="running",
                termination_unconfirmed=False,
            )

        current = repo.get_attempt(reservation.attempt_id)
        assert current is not None
        assert current.status == "running"
        assert current.termination_unconfirmed is True


def test_external_coding_repository_rejects_stale_running_observation_after_terminal() -> None:
    with ExternalCodingSessionRepository() as repo:
        session = repo.create_session(
            coding_session_id="ecs_stale_observation",
            session_id="sess_stale_observation",
            owner_type="task",
            owner_id="tsk_stale_observation",
            parent_session_id=None,
            tool="claude_code",
            launch_mode="headless",
            status="planning",
            phase="plan",
            worktree_path="worktree",
            branch_name="coding/ecs_stale_observation",
            base_commit="a" * 40,
            artifact_dir="artifacts",
            handoff_path="artifacts/HANDOFF.md",
            plan_path="artifacts/PLAN.md",
            result_path="artifacts/RESULT.md",
        )
        attempt = repo.add_attempt(
            coding_session_id=session.coding_session_id,
            phase="plan",
            launch_mode="headless",
            status="running",
            termination_unconfirmed=True,
            launch_started=True,
        )

        terminal = repo.update_attempt(
            attempt.attempt_id,
            expected_status="running",
            status="succeeded",
            termination_unconfirmed=False,
            exit_code=0,
        )
        stale = repo.update_attempt(
            attempt.attempt_id,
            expected_status="running",
            status="running",
            termination_unconfirmed=True,
            error_message="stale poll result",
        )

        assert terminal is not None and terminal.status == "succeeded"
        assert stale is None
        current = repo.get_attempt(attempt.attempt_id)
        assert current is not None
        assert current.status == "succeeded"
        assert current.finished_at is not None
        assert current.termination_unconfirmed is False
        assert current.error_message is None

        with pytest.raises(ValueError, match="cannot return to running"):
            repo.update_attempt(attempt.attempt_id, status="running")


def test_external_coding_repository_rejects_unknown_projection_fields() -> None:
    with ExternalCodingSessionRepository() as repo:
        session = repo.create_session(
            coding_session_id="ecs_unknown_fields",
            session_id="sess_unknown_fields",
            owner_type="task",
            owner_id="tsk_unknown_fields",
            parent_session_id=None,
            tool="claude_code",
            launch_mode="headless",
            status="planning",
            phase="plan",
            worktree_path="worktree",
            branch_name="coding/ecs_unknown_fields",
            base_commit="a" * 40,
            artifact_dir="artifacts",
            handoff_path="artifacts/HANDOFF.md",
            plan_path="artifacts/PLAN.md",
            result_path="artifacts/RESULT.md",
        )
        attempt = repo.add_attempt(
            coding_session_id=session.coding_session_id,
            phase="plan",
            launch_mode="headless",
            status="running",
            termination_unconfirmed=True,
        )

        with pytest.raises(ValueError, match="unsupported external coding session fields"):
            repo.update_session(session.coding_session_id, typo_status="failed")
        with pytest.raises(ValueError, match="unsupported external coding attempt fields"):
            repo.update_attempt(attempt.attempt_id, typo_status="failed")
