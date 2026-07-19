"""T056: 周期 e2e — 滚动触发 + misfire 补一次 + reentry skipped（US3）。

轻量 mock（worker._tick 推进；reentry 用真 active run）。
"""

from __future__ import annotations

from datetime import timedelta

from src.business.scheduling.scheduler_service import SchedulerService
from src.business.scheduling.scheduler_worker import SchedulerWorker
from src.data.repos.scheduled_task_run_repository import ScheduledTaskRunRepository
from src.utils.timezone import utc_now_naive


class _FakeLauncher:
    def __init__(self) -> None:
        self.launches: list[str] = []

    def launch(self, *, scheduled_task_id, instruction, started_at=None):
        self.launches.append(scheduled_task_id)
        with ScheduledTaskRunRepository() as rr:
            run = rr.create(
                scheduled_task_id=scheduled_task_id,
                session_id=f"ast_rec_{scheduled_task_id}_{len(self.launches)}",
                started_at=started_at,
            )
        return run.run_id


def test_recurring_rolls_forward_each_fire():
    """周期任务每次 worker._tick 触发后 next_fire 滚到下个未来时点（不主动 completed）。"""
    launcher = _FakeLauncher()
    with SchedulerService(launcher=launcher) as service:
        task = service.create_from_draft(
            {
                "source_type": "direct",
                "source_ref": "poll",
                "title": "周期",
                "schedule_kind": "recurring",
                "schedule_payload": {"interval_seconds": 60},
                "instruction": "poll",
            }
        )
        task_id = task["scheduledTaskId"]
        worker = SchedulerWorker(service, launcher)

        # 把上一次的 run 置终态，避免 reentry skip
        def _force_due_and_tick():
            service._repo.cas_next_fire(task_id, next_fire_at=utc_now_naive())
            with ScheduledTaskRunRepository() as rr:
                for r, _ in [rr.list_by_task(task_id)]:
                    pass
                # 把所有 running/waiting_user 收尾成 succeeded，使 has_active_run=False
                runs, _ = rr.list_by_task(task_id)
                for run in runs:
                    if run.status in ("running", "waiting_user"):
                        rr.cas_transition(run.run_id, from_status=run.status, to_status="succeeded")
            worker._tick()

        _force_due_and_tick()
        assert launcher.launches.count(task_id) == 1
        first_next = service._repo.get(task_id).next_fire_at
        assert first_next is not None and first_next > utc_now_naive()
        assert service._repo.get(task_id).status == "active"  # recurring 不主动 completed

        _force_due_and_tick()
        assert launcher.launches.count(task_id) == 2  # 滚动第二次


def test_recurring_misfire_fires_once_not_all_periods():
    """错过多个周期（next_fire 远在过去）→ worker._tick 只补一次，next_fire 滚到未来。"""
    launcher = _FakeLauncher()
    with SchedulerService(launcher=launcher) as service:
        task = service.create_from_draft(
            {
                "source_type": "direct",
                "source_ref": "p",
                "title": "misfire",
                "schedule_kind": "recurring",
                "schedule_payload": {"interval_seconds": 60},
                "instruction": "p",
            }
        )
        task_id = task["scheduledTaskId"]
        service._repo.cas_next_fire(task_id, next_fire_at=utc_now_naive() - timedelta(seconds=300))

        SchedulerWorker(service, launcher)._tick()

        assert launcher.launches.count(task_id) == 1  # 只补最近一次，不是 5 次
        row = service._repo.get(task_id)
        assert row.next_fire_at > utc_now_naive() - timedelta(seconds=1)  # 滚到未来


def test_recurring_reentry_records_skipped():
    """到点时上次 run 未静默 → 本次记 skipped、不启动会话（T055）。"""
    launcher = _FakeLauncher()
    with SchedulerService(launcher=launcher) as service:
        task = service.create_from_draft(
            {
                "source_type": "direct",
                "source_ref": "r",
                "title": "reentry",
                "schedule_kind": "recurring",
                "schedule_payload": {"interval_seconds": 60},
                "instruction": "r",
            }
        )
        task_id = task["scheduledTaskId"]
        service._repo.cas_next_fire(task_id, next_fire_at=utc_now_naive())
        # 造活跃 run
        with ScheduledTaskRunRepository() as rr:
            rr.create(scheduled_task_id=task_id, session_id="ast_active_rec", status="running")

        SchedulerWorker(service, launcher)._tick()

        assert launcher.launches == []  # 不启动新会话
        with ScheduledTaskRunRepository() as rr:
            runs, _ = rr.list_by_task(task_id)
        assert any(r.status == "skipped" for r in runs)
