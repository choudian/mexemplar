"""Tests: reentry skip —— 到点时上次未静默则本次跳过、记 skipped、不堆积（033 T055）。"""

from __future__ import annotations

import pytest

from src.business.scheduling.scheduler_service import SchedulerService
from src.business.scheduling.scheduler_worker import SchedulerWorker
from src.data.repos.scheduled_task_run_repository import ScheduledTaskRunRepository
from src.utils.timezone import utc_now_naive


class _FakeLauncher:
    """记录 launch 调用，返回伪 run_id（不启动真实会话）。"""

    def __init__(self) -> None:
        self.launches: list[tuple[str, str]] = []

    def launch(self, *, scheduled_task_id: str, instruction: str, started_at=None) -> str:
        self.launches.append((scheduled_task_id, instruction))
        return f"schr_fake_{len(self.launches)}"


def _make_due_task(service: SchedulerService, *, interval_seconds: int = 60, next_fire=None):
    """建一条 recurring 任务并把 next_fire_at 调到 due（<= now）。"""
    task = service.create_from_draft(
        {
            "source_type": "direct",
            "source_ref": "do job",
            "title": "周期任务",
            "schedule_kind": "recurring",
            "schedule_payload": {"interval_seconds": interval_seconds},
            "instruction": "run",
        }
    )
    task_id = task["scheduledTaskId"]
    # 强制 next_fire 到 due（create_from_draft 算出的是未来时刻）
    service._repo.cas_next_fire(task_id, next_fire_at=next_fire or utc_now_naive())
    return task_id


def test_reentry_records_skipped_and_does_not_launch():
    service = SchedulerService()
    launcher = _FakeLauncher()
    task_id = _make_due_task(service, next_fire=utc_now_naive())
    # 造一条活跃 run（上次未静默）
    with ScheduledTaskRunRepository() as rr:
        rr.create(scheduled_task_id=task_id, session_id="ast_active_1", status="running")

    worker = SchedulerWorker(service, launcher)  # noqa: no start — 直接调 _tick
    worker._tick()

    # 本次不启动会话
    assert all(tid != task_id for tid, _ in launcher.launches), "reentry 不应启动新会话"
    # 记一条 skipped run（不堆积：仅 1 条）
    with ScheduledTaskRunRepository() as rr:
        runs, _ = rr.list_by_task(task_id)
    skipped = [r for r in runs if r.status == "skipped"]
    assert len(skipped) == 1
    # next_fire 滚到未来（rollover 已推进，不卡在 due）
    task_row = service._repo.get(task_id)
    assert task_row.next_fire_at is not None
    assert task_row.next_fire_at > utc_now_naive()


def test_reentry_skip_is_not_runtime_configurable():
    """FR-011 是硬保证：即使注入的 config 声称关闭，也不得并发同一任务。"""
    service = SchedulerService()
    launcher = _FakeLauncher()
    task_id = _make_due_task(service, next_fire=utc_now_naive())
    with ScheduledTaskRunRepository() as rr:
        rr.create(scheduled_task_id=task_id, session_id="ast_active_2", status="running")

    class _ConfigThatWouldDisableReentry:
        def get_scheduler_reentry_skip_enabled(self):
            return False

    worker = SchedulerWorker(service, launcher, config=_ConfigThatWouldDisableReentry())
    worker._tick()

    assert all(tid != task_id for tid, _ in launcher.launches)
    with ScheduledTaskRunRepository() as rr:
        runs, _ = rr.list_by_task(task_id)
    assert len([run for run in runs if run.status == "skipped"]) == 1


def test_reentry_keeps_task_due_when_skipped_audit_write_fails():
    """skipped 是 FR-011 账目事实；写失败时不得静默 rollover 丢掉本次审计。"""

    class _FailingRunRepository:
        @staticmethod
        def has_active_run(_task_id):
            return True

        @staticmethod
        def create(**_kwargs):
            raise RuntimeError("database unavailable")

    service = SchedulerService()
    launcher = _FakeLauncher()
    due_at = utc_now_naive()
    task_id = _make_due_task(service, next_fire=due_at)
    worker = SchedulerWorker(
        service,
        launcher,
        run_repo=_FailingRunRepository(),
    )

    worker._tick()

    assert launcher.launches == []
    assert service._repo.get(task_id).next_fire_at == due_at


def test_reentry_recovers_on_next_tick_after_transient_audit_failure(monkeypatch):
    """生产 fresh Repository scope 让一次失败不会毒化后续 tick。"""
    from src.business.scheduling import scheduler_worker as worker_module

    attempts = {"create": 0}

    class _FreshRunRepository:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        @staticmethod
        def has_active_run(_task_id):
            return True

        @staticmethod
        def close():
            return None

        @staticmethod
        def create_skipped(**_kwargs):
            attempts["create"] += 1
            if attempts["create"] == 1:
                raise RuntimeError("transient database failure")
            return object()

    monkeypatch.setattr(
        worker_module,
        "ScheduledTaskRunRepository",
        _FreshRunRepository,
    )
    service = SchedulerService()
    launcher = _FakeLauncher()
    due_at = utc_now_naive()
    task_id = _make_due_task(service, next_fire=due_at)
    worker = SchedulerWorker(service, launcher)

    worker._tick()
    assert service._repo.get(task_id).next_fire_at == due_at

    worker._tick()
    assert attempts["create"] == 2
    assert service._repo.get(task_id).next_fire_at > utc_now_naive()


def test_production_worker_uses_fresh_service_after_repository_failure(monkeypatch):
    from src.business.scheduling import scheduler_worker as worker_module

    calls = {"instances": 0, "closed": 0}

    class _Repo:
        def __init__(self, instance_number):
            self.instance_number = instance_number

        def list_due(self, _now, *, limit):
            assert limit == 100
            if self.instance_number == 1:
                raise RuntimeError("transaction failed")
            return []

    class _FreshService:
        def __init__(self, *, launcher):
            assert launcher is not None
            calls["instances"] += 1
            self._repo = _Repo(calls["instances"])

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            calls["closed"] += 1

    monkeypatch.setattr(worker_module, "SchedulerService", _FreshService)
    worker = SchedulerWorker(None, _FakeLauncher())

    with pytest.raises(RuntimeError):
        worker._tick()
    worker._tick()

    assert calls == {"instances": 2, "closed": 2}


def test_worker_start_failure_clears_process_singleton(monkeypatch):
    from src.business.scheduling import scheduler_worker as worker_module

    worker = SchedulerWorker(SchedulerService(), _FakeLauncher())

    def _raise(_thread):
        raise RuntimeError("thread creation failed")

    monkeypatch.setattr(worker_module.threading.Thread, "start", _raise)

    with pytest.raises(RuntimeError):
        worker.start()

    assert worker_module.get_scheduler_worker() is None
    assert worker._thread is None
