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
        )
        repo.update_session(session.coding_session_id, status="plan_ready", plan_path="PLAN.md")
        repo.add_attempt(
            coding_session_id=session.coding_session_id,
            phase="plan",
            launch_mode="headless",
            status="succeeded",
            command_summary="claude -p <prompt>",
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
        assert repo.list_attempts("ecs_test")[0].status == "succeeded"
        assert repo.latest_quota_by_tool()["claude_code"].safe_detail == "ok"
        assert repo.list_merge_records("ecs_test")[0].conflict_risk == "overlap"
        assert repo.list_rollback_decisions("ecs_test")[0].requires_confirmation is True
