"""Tests for ScheduledTaskRepository / ScheduledTaskRunRepository（033）。

CAS 守卫与软删序列化测试（非真线程并发——in_memory StaticPool 下的 threading CAS
不可靠，见 memory project_in_memory_db_static_pool_concurrency）。
"""

from __future__ import annotations

import pytest

from src.data.models_sqlite import Session
from src.data.repos.session_repository import SessionRepository
from src.data.repos.scheduled_task_repository import ScheduledTaskRepository
from src.data.repos.scheduled_task_run_repository import ScheduledTaskRunRepository
from src.utils.timezone import utc_now_naive


def _make_task(repo: ScheduledTaskRepository, **kwargs):
    defaults = dict(
        source_type="direct",
        source_ref="do something",
        title="T",
        schedule_kind="one_shot",
        schedule_payload={"run_at": "2026-07-19T10:00:00"},
        next_fire_at=utc_now_naive(),
    )
    defaults.update(kwargs)
    return repo.create(**defaults)


# ---------------------------------------------------------------------------
# ScheduledTaskRepository
# ---------------------------------------------------------------------------


def test_task_create_and_get():
    with ScheduledTaskRepository() as r:
        t = _make_task(r)
        assert t.scheduled_task_id.startswith("sch_")
        assert t.status == "active"
        assert t.unattended_auto_approve == 0
        assert t.is_deleted == 0
        assert t.instruction == "do something"
        assert r.get(t.scheduled_task_id).title == "T"


def test_task_cas_status_legal_and_illegal():
    with ScheduledTaskRepository() as r:
        t = _make_task(r)
        # legal active -> paused
        paused = r.cas_status(t.scheduled_task_id, from_status="active", to_status="paused")
        assert paused is not None and paused.status == "paused"
        # illegal: from active again (now paused) -> None
        assert r.cas_status(t.scheduled_task_id, from_status="active", to_status="paused") is None
        # legal paused -> active
        resumed = r.cas_status(t.scheduled_task_id, from_status="paused", to_status="active")
        assert resumed.status == "active"


def test_task_cas_status_rejects_caller_claimed_illegal_transition():
    with ScheduledTaskRepository() as r:
        task = _make_task(r)
        completed = r.cas_status(
            task.scheduled_task_id,
            from_status="active",
            to_status="completed",
        )
        assert completed is not None

        assert (
            r.cas_status(
                task.scheduled_task_id,
                from_status="completed",
                to_status="active",
            )
            is None
        )
        assert (
            r.cas_status(
                task.scheduled_task_id,
                from_status="completed",
                to_status="not-a-status",
            )
            is None
        )
        assert r.get(task.scheduled_task_id).status == "completed"


def test_task_cas_next_fire_and_soft_delete():
    with ScheduledTaskRepository() as r:
        t = _make_task(r)
        new_fire = utc_now_naive()
        row = r.cas_next_fire(t.scheduled_task_id, next_fire_at=new_fire, last_fired_at=new_fire)
        assert row is not None
        assert row.last_fired_at == new_fire
        # soft delete
        assert r.soft_delete(t.scheduled_task_id) is True
        # already deleted -> second soft_delete returns False
        assert r.soft_delete(t.scheduled_task_id) is False
        # deleted task excluded from list_tasks by default
        items, _ = r.list_tasks()
        assert all(it.scheduled_task_id != t.scheduled_task_id for it in items)


def test_task_unattended_auto_approve_toggle_and_list():
    with ScheduledTaskRepository() as r:
        t = _make_task(r)
        assert r.list_unattended_auto_approve_task_ids() == []
        r.set_unattended_auto_approve(t.scheduled_task_id, True)
        assert t.scheduled_task_id in r.list_unattended_auto_approve_task_ids()
        r.set_unattended_auto_approve(t.scheduled_task_id, False)
        assert r.list_unattended_auto_approve_task_ids() == []


def test_task_current_session_binding_is_compare_and_swap():
    with ScheduledTaskRepository() as r:
        task = _make_task(r)

        bound = r.cas_bind_session(
            task.scheduled_task_id,
            "ast_current",
            expected_session_id=None,
        )
        assert bound is not None and bound.session_id == "ast_current"
        lost_race = r.cas_bind_session(
            task.scheduled_task_id,
            "ast_other",
            expected_session_id=None,
        )
        wrong_clear = r.cas_clear_session(
            task.scheduled_task_id,
            expected_session_id="ast_other",
        )
        cleared = r.cas_clear_session(
            task.scheduled_task_id,
            expected_session_id="ast_current",
        )

        assert lost_race is None
        assert wrong_clear is None
        assert cleared is not None and cleared.session_id is None


def test_task_list_due_and_soonest():
    now = utc_now_naive()
    with ScheduledTaskRepository() as r:
        _make_task(r, next_fire_at=now)  # due now
        due = r.list_due(now)
        assert any(it.next_fire_at <= now for it in due)
        assert r.soonest_next_fire() is not None


# ---------------------------------------------------------------------------
# ScheduledTaskRunRepository
# ---------------------------------------------------------------------------


def test_run_create_and_cas_to_succeeded_sets_finished_at():
    with ScheduledTaskRunRepository() as rr:
        run = rr.create(scheduled_task_id="sch_x", session_id="ast_y")
        assert run.status == "running"
        assert run.finished_at is None
        s = rr.cas_transition(
            run.run_id, from_status="running", to_status="succeeded", summary="done"
        )
        assert s.status == "succeeded"
        assert s.finished_at is not None
        assert s.summary == "done"


def test_active_run_persists_message_window_and_is_found_without_latest_heuristic():
    with ScheduledTaskRunRepository() as rr:
        run = rr.create(
            scheduled_task_id="sch_window",
            session_id="ast_window",
            baseline_message_sequence=7,
            trigger_message_sequence=8,
        )

        active = rr.get_active_by_session("ast_window")

        assert active is not None
        assert active.run_id == run.run_id
        assert active.baseline_message_sequence == 7
        assert active.trigger_message_sequence == 8


def test_active_run_trigger_must_be_the_immediate_next_message_sequence() -> None:
    with ScheduledTaskRunRepository() as rr:
        with pytest.raises(
            ValueError,
            match=r"trigger_message_sequence must equal baseline_message_sequence \+ 1",
        ):
            rr.create(
                scheduled_task_id="sch_invalid_window",
                session_id="ast_invalid_window",
                baseline_message_sequence=7,
                trigger_message_sequence=9,
            )


def test_run_terminal_non_reversible():
    with ScheduledTaskRunRepository() as rr:
        run = rr.create(scheduled_task_id="sch_x", session_id="ast_y")
        rr.cas_transition(
            run.run_id, from_status="running", to_status="failed", failure_reason="boom"
        )
        # from running again -> None (already failed)
        assert rr.cas_transition(run.run_id, from_status="running", to_status="succeeded") is None
        # 即使调用方谎报当前终态，也不能绕过 Repository 的合法转移表。
        assert rr.cas_transition(run.run_id, from_status="failed", to_status="running") is None
        assert rr.cas_transition(run.run_id, from_status="failed", to_status="unknown") is None


def test_run_waiting_user_round_trip_and_active_detection():
    with ScheduledTaskRunRepository() as rr:
        run = rr.create(scheduled_task_id="sch_z", session_id="ast_w")
        rr.cas_transition(run.run_id, from_status="running", to_status="waiting_user")
        assert rr.has_active_run("sch_z") is True  # waiting_user counts as active (reentry)
        # takeover resume -> running again, finished_at cleared
        again = rr.cas_transition(run.run_id, from_status="waiting_user", to_status="running")
        assert again.status == "running"
        assert again.finished_at is None


def test_run_transition_map_rejects_illegal_waiting_user_success() -> None:
    with ScheduledTaskRunRepository() as rr:
        run = rr.create(scheduled_task_id="sch_transition", session_id="ast_transition")
        rr.cas_transition(run.run_id, from_status="running", to_status="waiting_user")

        assert (
            rr.cas_transition(
                run.run_id,
                from_status="waiting_user",
                to_status="succeeded",
            )
            is None
        )
        failed = rr.cas_transition(
            run.run_id,
            from_status="waiting_user",
            to_status="failed",
            failure_reason="stopped while waiting",
        )
        assert failed is not None
        assert failed.status == "failed"
        assert failed.finished_at is not None


def test_try_create_active_uses_unique_slot_and_releases_after_terminal() -> None:
    with ScheduledTaskRunRepository() as rr:
        first = rr.try_create_active(
            scheduled_task_id="sch_atomic",
            session_id="ast_atomic_1",
        )
        assert first is not None

        duplicate = rr.try_create_active(
            scheduled_task_id="sch_atomic",
            session_id="ast_atomic_2",
        )
        assert duplicate is None

        rr.cas_transition(first.run_id, from_status="running", to_status="failed")
        replacement = rr.try_create_active(
            scheduled_task_id="sch_atomic",
            session_id="ast_atomic_3",
        )
        assert replacement is not None


def test_new_scheduled_session_binding_and_active_run_commit_atomically() -> None:
    with ScheduledTaskRepository() as tasks:
        task = _make_task(tasks)
        task_id = task.scheduled_task_id
    session = Session(
        session_id="ast_bound_atomic",
        workflow_id=None,
        agent_type="assistant",
        status="active",
        source="scheduled",
        scheduled_task_id=task_id,
        is_scheduled=1,
    )

    with ScheduledTaskRunRepository() as runs:
        run = runs.try_create_active_with_new_bound_session(
            scheduled_task_id=task_id,
            session=session,
            expected_session_id=None,
            baseline_message_sequence=0,
            trigger_message_sequence=1,
        )

    assert run is not None
    with ScheduledTaskRepository() as tasks:
        assert tasks.get(task_id).session_id == "ast_bound_atomic"
    with SessionRepository() as sessions:
        assert sessions.get_by_id("ast_bound_atomic") is not None
    with ScheduledTaskRunRepository() as runs:
        persisted = runs.get(run.run_id)
        assert persisted is not None
        assert persisted.session_id == "ast_bound_atomic"
        assert persisted.trigger_message_sequence == 1


def test_bound_scheduled_session_can_start_a_later_run_without_new_session() -> None:
    with ScheduledTaskRepository() as tasks:
        task = _make_task(tasks)
        task_id = task.scheduled_task_id
    session = Session(
        session_id="ast_reused",
        workflow_id=None,
        agent_type="assistant",
        status="active",
        source="scheduled",
        scheduled_task_id=task_id,
        is_scheduled=1,
    )
    with ScheduledTaskRunRepository() as runs:
        first = runs.try_create_active_with_new_bound_session(
            scheduled_task_id=task_id,
            session=session,
            expected_session_id=None,
            baseline_message_sequence=0,
            trigger_message_sequence=1,
        )
        assert first is not None
        runs.cas_transition(first.run_id, from_status="running", to_status="succeeded")
        second = runs.try_create_active_for_bound_session(
            scheduled_task_id=task_id,
            session_id="ast_reused",
            baseline_message_sequence=9,
            trigger_message_sequence=10,
        )

    assert second is not None
    assert second.session_id == "ast_reused"
    assert second.baseline_message_sequence == 9
    with SessionRepository() as sessions:
        assert len(sessions.get_by_ids(["ast_reused"])) == 1


def test_run_is_resolved_by_message_sequence_window_not_latest_session_row() -> None:
    with ScheduledTaskRunRepository() as runs:
        first = runs.create(
            scheduled_task_id="sch_message_owner",
            session_id="ast_message_owner",
            baseline_message_sequence=0,
            trigger_message_sequence=1,
        )
        runs.cas_transition(first.run_id, from_status="running", to_status="succeeded")
        second = runs.create(
            scheduled_task_id="sch_message_owner",
            session_id="ast_message_owner",
            baseline_message_sequence=5,
            trigger_message_sequence=6,
        )

        assert runs.get_for_message_sequence("ast_message_owner", 2).run_id == first.run_id
        assert runs.get_for_message_sequence("ast_message_owner", 6).run_id == second.run_id
        assert runs.get_for_message_sequence("ast_message_owner", 0) is None


def test_run_skipped_is_a_separate_trigger_record_not_a_running_transition():
    with ScheduledTaskRunRepository() as rr:
        run = rr.create(scheduled_task_id="sch_s", session_id="ast_s")
        assert rr.cas_transition(run.run_id, from_status="running", to_status="skipped") is None
        assert rr.has_active_run("sch_s") is True

        skipped = rr.create_skipped(scheduled_task_id="sch_s")
        assert skipped.status == "skipped"
        assert skipped.finished_at is not None
        assert skipped.session_id == f"ast_skipped_{skipped.run_id}"
        assert rr.has_active_run("sch_s") is True


def test_run_create_rejects_skipped_status_and_placeholder_session():
    with ScheduledTaskRunRepository() as rr:
        with pytest.raises(ValueError, match="create_skipped"):
            rr.create(
                scheduled_task_id="sch_s",
                session_id="ast_real",
                status="skipped",  # type: ignore[arg-type]
            )
        with pytest.raises(ValueError, match="real session_id"):
            rr.create(
                scheduled_task_id="sch_s",
                session_id="ast_skipped_not_real",
            )


def test_run_list_by_task_ordering():
    with ScheduledTaskRunRepository() as rr:
        a = rr.create(scheduled_task_id="sch_o", session_id="ast_1")
        rr.cas_transition(a.run_id, from_status="running", to_status="succeeded")
        b = rr.create(scheduled_task_id="sch_o", session_id="ast_2")
        items, total = rr.list_by_task("sch_o")
        assert total == 2
        # most recent first
        assert items[0].run_id == b.run_id
        assert items[1].run_id == a.run_id
