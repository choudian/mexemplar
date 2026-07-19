"""Tests: misfire 补跑 —— app 未运行错过只补最近一次、recurring 滚到未来首点（033 T046/T050）。

注意：真「app 未运行过点」是时间维度行为，这里用「next_fire 在过去」+ worker._tick 模拟。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from src.business.scheduling import scheduler_service as scheduler_service_module
from src.business.scheduling.scheduler_service import SchedulerService
from src.business.scheduling.scheduler_worker import SchedulerWorker
from src.utils.timezone import utc_now_naive


class _FakeLauncher:
    def __init__(self) -> None:
        self.launches: list[str] = []

    def launch(self, *, scheduled_task_id: str, instruction: str, started_at=None) -> str:
        self.launches.append(scheduled_task_id)
        return f"schr_fake_{len(self.launches)}"


def test_recurring_misfire_fires_once_and_rolls_to_future():
    """错过多个周期（next_fire 远在过去）→ 只 fire 一次（补最近一次），然后滚到未来。"""
    service = SchedulerService()
    launcher = _FakeLauncher()
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
    # next_fire 设为 3 个周期前（错过 3 次）
    far_past = utc_now_naive() - timedelta(seconds=180)
    service._repo.cas_next_fire(task_id, next_fire_at=far_past)

    worker = SchedulerWorker(service, launcher)
    worker._tick()

    # 只补一次（不是 3 次）
    assert launcher.launches.count(task_id) == 1
    # next_fire 滚到未来（>= now），不是停留在过去
    row = service._repo.get(task_id)
    assert row.next_fire_at is not None
    assert row.next_fire_at > utc_now_naive() - timedelta(seconds=1)


def test_interval_misfire_preserves_the_original_schedule_grid(monkeypatch):
    """延迟补跑只跳过旧格点；下次触发仍锚定原计划，而不是锚定实际醒来时间。"""
    now = datetime(2026, 7, 19, 12, 5, 30)
    original_fire = datetime(2026, 7, 19, 12, 0, 0)
    monkeypatch.setattr(scheduler_service_module, "utc_now_naive", lambda: now)
    service = SchedulerService()
    task = service.create_from_draft(
        {
            "source_type": "direct",
            "source_ref": "hourly",
            "title": "整点任务",
            "schedule_kind": "recurring",
            "schedule_payload": {"interval_seconds": 3600},
            "instruction": "hourly",
        }
    )
    task_id = task["scheduledTaskId"]
    service._repo.cas_next_fire(task_id, next_fire_at=original_fire)

    service.rollover(task_id)

    row = service._repo.get(task_id)
    assert row.next_fire_at == datetime(2026, 7, 19, 13, 0, 0)
    assert row.last_fired_at == now


def test_one_shot_fires_once_then_completed():
    """一次性任务 fire 一次后进入终态 completed、next_fire=NULL，不再重复触发。"""
    service = SchedulerService()
    launcher = _FakeLauncher()
    task = service.create_from_draft(
        {
            "source_type": "direct",
            "source_ref": "once",
            "title": "一次性",
            "schedule_kind": "one_shot",
            "schedule_payload": {"run_at": "now"},
            "instruction": "do once",
        }
    )
    task_id = task["scheduledTaskId"]

    worker = SchedulerWorker(service, launcher)
    worker._tick()
    # 再 tick 一次验证不重复触发
    worker._tick()

    assert launcher.launches.count(task_id) == 1
    row = service._repo.get(task_id)
    assert row.status == "completed"
    assert row.next_fire_at is None


def test_paused_task_not_fired():
    """paused 任务不被 worker 扫描触发（list_due 只取 active）。"""
    service = SchedulerService()
    launcher = _FakeLauncher()
    task = service.create_from_draft(
        {
            "source_type": "direct",
            "source_ref": "p",
            "title": "paused",
            "schedule_kind": "one_shot",
            "schedule_payload": {"run_at": "now"},
            "instruction": "x",
        }
    )
    task_id = task["scheduledTaskId"]
    service._repo.cas_status(task_id, from_status="active", to_status="paused")
    service._repo.cas_next_fire(task_id, next_fire_at=utc_now_naive())

    SchedulerWorker(service, launcher)._tick()

    assert launcher.launches == []


def test_task_paused_after_due_scan_is_not_fired(monkeypatch):
    """list_due 旧快照之后暂停也必须在 launch 前被权威重读挡住。"""
    service = SchedulerService()
    launcher = _FakeLauncher()
    task = service.create_from_draft(
        {
            "source_type": "direct",
            "source_ref": "race",
            "title": "pause race",
            "schedule_kind": "one_shot",
            "schedule_payload": {"run_at": "now"},
            "instruction": "must not run",
        }
    )
    task_id = task["scheduledTaskId"]
    original_list_due = service._repo.list_due

    def list_due_then_pause(now, *, limit=100):
        candidates = original_list_due(now, limit=limit)
        service._repo.cas_status(task_id, from_status="active", to_status="paused")
        return candidates

    monkeypatch.setattr(service._repo, "list_due", list_due_then_pause)

    SchedulerWorker(service, launcher)._tick()

    assert launcher.launches == []
    assert service._repo.get(task_id).status == "paused"
