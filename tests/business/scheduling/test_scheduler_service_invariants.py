"""SchedulerService hard invariants added by the implementation review."""

from __future__ import annotations

from datetime import timedelta

import pytest

from src.business.agents.config import AgentType
from src.business.scheduling.scheduler_service import (
    SchedulerRuntimeUnavailable,
    SchedulerService,
    clear_default_scheduler_launcher,
    configure_default_scheduler_launcher,
)
from src.business.scheduling.session_launcher import SessionLauncher
from src.data.models_sqlite import Session
from src.utils.timezone import utc_now_naive


def _draft(*, schedule_kind: str, schedule_payload: dict) -> dict:
    return {
        "source_type": "direct",
        "source_ref": "执行调度任务",
        "title": "调度任务",
        "instruction": "执行调度任务",
        "schedule_kind": schedule_kind,
        "schedule_payload": schedule_payload,
    }


@pytest.mark.parametrize(
    ("schedule_kind", "schedule_payload"),
    [
        ("one_shot", {"interval_seconds": 60}),
        ("one_shot", {"run_at": "2099-01-01T00:00:00", "kind": "daily"}),
        ("recurring", {"run_at": "2099-01-01T00:00:00"}),
        ("recurring", {"interval_seconds": 60, "kind": "daily", "time": "09:00"}),
        ("recurring", {"kind": "monthly", "time": "09:00"}),
        ("recurring", {"kind": "interval", "interval_seconds": 1.5}),
        ("recurring", {"kind": "interval", "interval_seconds": "1.5"}),
        ("recurring", {"kind": "interval", "interval_seconds": True}),
        ("recurring", {"kind": "interval", "interval_seconds": 10**100}),
        ("recurring", {"kind": "weekly", "weekdays": 1, "time_of_day": "09:00"}),
        (
            "recurring",
            {"kind": "weekly", "weekdays": ["Monday"], "time_of_day": "09:00"},
        ),
    ],
)
def test_create_rejects_mismatched_schedule_shape(
    schedule_kind: str,
    schedule_payload: dict,
) -> None:
    with SchedulerService() as service:
        _, before = service.list_tasks()
        with pytest.raises(ValueError):
            service.create_from_draft(
                _draft(
                    schedule_kind=schedule_kind,
                    schedule_payload=schedule_payload,
                )
            )
        _, after = service.list_tasks()
        assert after == before


def test_create_accepts_interval_shape_from_tool_contract() -> None:
    with SchedulerService() as service:
        task = service.create_from_draft(
            _draft(
                schedule_kind="recurring",
                schedule_payload={"kind": "interval", "interval_seconds": 60},
            )
        )

        assert task["status"] == "active"
        assert service._repo.get(task["scheduledTaskId"]).next_fire_at > utc_now_naive()


def test_resume_overdue_one_shot_expires_without_catchup() -> None:
    with SchedulerService() as service:
        task = service.create_from_draft(
            _draft(schedule_kind="one_shot", schedule_payload={"run_at": "now"})
        )
        task_id = task["scheduledTaskId"]
        service.pause(task_id)

        resumed = service.resume(task_id)

        assert resumed["status"] == "expired"
        assert resumed["nextFireAt"] is None or resumed["nextFireAt"] <= utc_now_naive().isoformat()


def test_resume_overdue_recurring_rolls_to_future_without_catchup() -> None:
    with SchedulerService() as service:
        task = service.create_from_draft(
            _draft(
                schedule_kind="recurring",
                schedule_payload={"interval_seconds": 60},
            )
        )
        task_id = task["scheduledTaskId"]
        service.pause(task_id)
        service._repo.cas_next_fire(
            task_id,
            next_fire_at=utc_now_naive() - timedelta(minutes=5),
        )

        resumed = service.resume(task_id)

        assert resumed["status"] == "active"
        assert service._repo.get(task_id).next_fire_at > utc_now_naive()


def test_rollover_expires_recurring_task_with_invalid_stored_payload() -> None:
    with SchedulerService() as service:
        task = service.create_from_draft(
            _draft(
                schedule_kind="recurring",
                schedule_payload={"interval_seconds": 60},
            )
        )
        task_id = task["scheduledTaskId"]
        row = service._repo.get(task_id)
        row.schedule_payload = '{"run_at":"now"}'
        service._repo.session.commit()

        service.rollover(task_id)

        assert service._repo.get(task_id).status == "expired"


def test_fire_now_without_runtime_launcher_fails_closed() -> None:
    clear_default_scheduler_launcher()
    with SchedulerService() as service:
        task = service.create_from_draft(
            _draft(
                schedule_kind="one_shot",
                schedule_payload={"run_at": "2099-01-01T00:00:00"},
            )
        )

        with pytest.raises(SchedulerRuntimeUnavailable):
            service.fire_now(task["scheduledTaskId"])


def test_short_lived_service_uses_lifespan_registered_launcher() -> None:
    class _ChatService:
        @staticmethod
        def generate_session_id() -> str:
            return "ast_registered_launcher"

        @staticmethod
        def build_scheduled_session(scheduled_task_id: str, **kwargs) -> Session:
            return Session(
                session_id=kwargs["session_id"],
                workflow_id=None,
                agent_type=AgentType.ASSISTANT,
                status="active",
                source="scheduled",
                scheduled_task_id=scheduled_task_id,
                is_scheduled=1,
            )

    launcher = SessionLauncher(
        dispatch_callback=lambda _session_id, _instruction: True,
        chat_service=_ChatService(),
    )
    configure_default_scheduler_launcher(launcher)
    try:
        with SchedulerService() as service:
            task = service.create_from_draft(
                _draft(
                    schedule_kind="one_shot",
                    schedule_payload={"run_at": "2099-01-01T00:00:00"},
                )
            )

            run = service.fire_now(task["scheduledTaskId"])

            assert run["status"] == "running"
            assert run["sessionId"] == "ast_registered_launcher"
    finally:
        clear_default_scheduler_launcher(launcher)
        launcher.close()


def test_fire_now_allows_paused_task_without_resuming_it() -> None:
    """暂停只阻止自动到点扫描；用户手动 fire-now 仍可跑一次且不改变原排期状态。"""

    class _ChatService:
        @staticmethod
        def generate_session_id() -> str:
            return "ast_paused_manual_fire"

        @staticmethod
        def build_scheduled_session(scheduled_task_id: str, **kwargs) -> Session:
            return Session(
                session_id=kwargs["session_id"],
                workflow_id=None,
                agent_type=AgentType.ASSISTANT,
                status="active",
                source="scheduled",
                scheduled_task_id=scheduled_task_id,
                is_scheduled=1,
            )

    launcher = SessionLauncher(
        dispatch_callback=lambda _session_id, _instruction: True,
        chat_service=_ChatService(),
    )
    try:
        with SchedulerService(launcher=launcher) as service:
            task = service.create_from_draft(
                _draft(
                    schedule_kind="recurring",
                    schedule_payload={"interval_seconds": 3600},
                )
            )
            task_id = task["scheduledTaskId"]
            paused = service.pause(task_id)
            original_next_fire = service._repo.get(task_id).next_fire_at

            run = service.fire_now(task_id)

            assert run["status"] == "running"
            assert run["sessionId"] == "ast_paused_manual_fire"
            assert paused["status"] == "paused"
            row = service._repo.get(task_id)
            assert row.status == "paused"
            assert row.next_fire_at == original_next_fire
    finally:
        launcher.close()


def test_task_change_wakes_scheduler_worker(monkeypatch) -> None:
    from src.business.scheduling import scheduler_worker

    notifications: list[str] = []
    monkeypatch.setattr(
        scheduler_worker,
        "notify_scheduler_worker",
        lambda: notifications.append("wake"),
    )

    with SchedulerService() as service:
        service.create_from_draft(
            _draft(
                schedule_kind="one_shot",
                schedule_payload={"run_at": "2099-01-01T00:00:00"},
            )
        )

    assert notifications == ["wake"]


def test_unattended_disable_does_not_persist_if_runtime_revoke_fails(
    monkeypatch,
) -> None:
    from src.business.scheduling import unattended_confirmation_manager as manager_module

    class _FailingManager:
        @staticmethod
        def set(_task_id, _enabled):
            raise RuntimeError("runtime authorization unavailable")

    with SchedulerService() as service:
        task = service.create_from_draft(
            _draft(
                schedule_kind="one_shot",
                schedule_payload={"run_at": "2099-01-01T00:00:00"},
            )
        )
        task_id = task["scheduledTaskId"]
        service._repo.set_unattended_auto_approve(task_id, True)
        monkeypatch.setattr(
            manager_module,
            "get_unattended_confirmation_manager",
            lambda: _FailingManager(),
        )

        with pytest.raises(RuntimeError):
            service.set_unattended(task_id, False)

        assert bool(service._repo.get(task_id).unattended_auto_approve) is True


def test_unattended_enable_runtime_failure_compensates_persistent_flag(
    monkeypatch,
) -> None:
    from src.business.scheduling import unattended_confirmation_manager as manager_module

    class _FailingManager:
        @staticmethod
        def set(_task_id, enabled):
            if enabled:
                raise RuntimeError("runtime authorization unavailable")

    with SchedulerService() as service:
        task = service.create_from_draft(
            _draft(
                schedule_kind="one_shot",
                schedule_payload={"run_at": "2099-01-01T00:00:00"},
            )
        )
        task_id = task["scheduledTaskId"]
        monkeypatch.setattr(
            manager_module,
            "get_unattended_confirmation_manager",
            lambda: _FailingManager(),
        )

        with pytest.raises(RuntimeError):
            service.set_unattended(task_id, True)

        assert bool(service._repo.get(task_id).unattended_auto_approve) is False


def test_unattended_enable_partial_runtime_mutation_is_revoked(monkeypatch) -> None:
    from src.business.scheduling import unattended_confirmation_manager as manager_module

    class _PartiallyFailingManager:
        def __init__(self) -> None:
            self.authorized: set[str] = set()

        def set(self, task_id, enabled):
            if enabled:
                self.authorized.add(task_id)
                raise RuntimeError("failed after runtime authorization")
            self.authorized.discard(task_id)

    manager = _PartiallyFailingManager()
    monkeypatch.setattr(
        manager_module,
        "get_unattended_confirmation_manager",
        lambda: manager,
    )

    with SchedulerService() as service:
        task = service.create_from_draft(
            _draft(
                schedule_kind="one_shot",
                schedule_payload={"run_at": "2099-01-01T00:00:00"},
            )
        )
        task_id = task["scheduledTaskId"]

        with pytest.raises(RuntimeError):
            service.set_unattended(task_id, True)

        assert bool(service._repo.get(task_id).unattended_auto_approve) is False
        assert task_id not in manager.authorized


def test_create_with_partial_runtime_authorization_returns_fail_closed(monkeypatch) -> None:
    from src.business.scheduling import unattended_confirmation_manager as manager_module

    class _PartiallyFailingManager:
        def __init__(self) -> None:
            self.authorized: set[str] = set()

        def set(self, task_id, enabled):
            if enabled:
                self.authorized.add(task_id)
                raise RuntimeError("failed after runtime authorization")
            self.authorized.discard(task_id)

    manager = _PartiallyFailingManager()
    monkeypatch.setattr(
        manager_module,
        "get_unattended_confirmation_manager",
        lambda: manager,
    )

    with SchedulerService() as service:
        task = service.create_from_draft(
            _draft(
                schedule_kind="one_shot",
                schedule_payload={"run_at": "2099-01-01T00:00:00"},
            ),
            unattended_auto_approve=True,
        )

        assert task["unattendedAutoApprove"] is False
        assert task["scheduledTaskId"] not in manager.authorized


def test_soft_delete_does_not_persist_if_runtime_revoke_fails(monkeypatch) -> None:
    from src.business.scheduling import unattended_confirmation_manager as manager_module

    class _FailingManager:
        @staticmethod
        def set(_task_id, _enabled):
            raise RuntimeError("runtime authorization unavailable")

    with SchedulerService() as service:
        task = service.create_from_draft(
            _draft(
                schedule_kind="one_shot",
                schedule_payload={"run_at": "2099-01-01T00:00:00"},
            )
        )
        task_id = task["scheduledTaskId"]
        monkeypatch.setattr(
            manager_module,
            "get_unattended_confirmation_manager",
            lambda: _FailingManager(),
        )

        with pytest.raises(RuntimeError):
            service.soft_delete(task_id)

        assert service._repo.get(task_id).is_deleted == 0


def test_soft_deleted_task_cannot_be_reauthorized() -> None:
    with SchedulerService() as service:
        task = service.create_from_draft(
            _draft(
                schedule_kind="one_shot",
                schedule_payload={"run_at": "2099-01-01T00:00:00"},
            )
        )
        task_id = task["scheduledTaskId"]
        service.soft_delete(task_id)

        with pytest.raises(LookupError):
            service.set_unattended(task_id, True)

        assert service._repo.get(task_id).is_deleted == 1


def test_soft_deleted_task_cannot_be_updated() -> None:
    with SchedulerService() as service:
        task = service.create_from_draft(
            _draft(
                schedule_kind="one_shot",
                schedule_payload={"run_at": "2099-01-01T00:00:00"},
            )
        )
        task_id = task["scheduledTaskId"]
        service.soft_delete(task_id)

        with pytest.raises(LookupError):
            service.update_display(task_id, title="不应复活")

        row = service._repo.get(task_id)
        assert row is not None
        assert row.is_deleted == 1
        assert row.title != "不应复活"


def test_title_over_persisted_limit_is_rejected_instead_of_silently_truncated() -> None:
    with SchedulerService() as service:
        draft = _draft(
            schedule_kind="one_shot",
            schedule_payload={"run_at": "2099-01-01T00:00:00"},
        )
        draft["title"] = "题" * 121
        with pytest.raises(ValueError, match="at most 120"):
            service.create_from_draft(draft)
