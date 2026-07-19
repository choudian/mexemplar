"""T071: 管理操作 e2e — 暂停/启用/现在跑一次/删除/详情开关 + waiting_user 接管（US6）。

service 层（router 契约由 test_scheduled_tasks_api.py 覆盖）；接管走真 CAS 状态机。
"""

from __future__ import annotations

import pytest

from src.business.scheduling.scheduler_service import SchedulerService
from src.business.scheduling.session_launcher import SessionLauncher
from src.data.repos.scheduled_task_run_repository import ScheduledTaskRunRepository


def _service():
    return SchedulerService(launcher=SessionLauncher(dispatch_callback=lambda sid, instr: True))


def _make_task(service, **kw):
    defaults = dict(
        source_type="direct",
        source_ref="mgmt",
        title="管理任务",
        schedule_kind="recurring",
        schedule_payload={"interval_seconds": 60},
        instruction="x",
    )
    defaults.update(kw)
    return service.create_from_draft(defaults)["scheduledTaskId"]


def test_pause_and_resume():
    with _service() as service:
        task_id = _make_task(service)
        paused = service.pause(task_id)
        assert paused["status"] == "paused"
        resumed = service.resume(task_id)
        assert resumed["status"] == "active"


def test_pause_idempotent_invalid_transition():
    with _service() as service:
        task_id = _make_task(service)
        service.pause(task_id)
        # paused -> paused 非法转移（应抛）
        with pytest.raises(Exception):
            service.pause(task_id)


def test_fire_now_creates_running_run():
    with _service() as service:
        task_id = _make_task(service)
        run = service.fire_now(task_id)
        assert run["status"] == "running"
        assert run["sessionId"].startswith("ast_")
        runs, total = service.list_runs(task_id)
        assert total == 1


def test_soft_delete_then_not_listed():
    with _service() as service:
        task_id = _make_task(service)
        service.soft_delete(task_id)
        tasks, _ = service.list_tasks()
        assert all(t["scheduledTaskId"] != task_id for t in tasks)


def test_detail_unattended_switch_revokes_authority():
    with _service() as service:
        task_id = _make_task(service)
        # 开启
        service.set_unattended(task_id, True)
        from src.business.scheduling.unattended_confirmation_manager import (
            get_unattended_confirmation_manager,
        )

        mgr = get_unattended_confirmation_manager()
        assert mgr.is_authorized(task_id)
        # 回收（详情页开关）
        service.set_unattended(task_id, False)
        assert not mgr.is_authorized(task_id)


def test_takeover_waiting_user_back_to_running_returns_session():
    """waiting_user run 经接管 CAS 回 running，返回 sessionId 供前端打开接着聊。"""
    with _service() as service:
        task_id = _make_task(service)
        run = service.fire_now(task_id)
        run_id = run["runId"]
        session_id = run["sessionId"]
        # 落 waiting_user
        with ScheduledTaskRunRepository() as rr:
            rr.cas_transition(run_id, from_status="running", to_status="waiting_user")
        # 接管
        result = service.takeover(run_id)
        assert result["sessionId"] == session_id
        with ScheduledTaskRunRepository() as rr:
            refreshed = rr.get(run_id)
        assert refreshed.status == "running"
        assert refreshed.finished_at is None  # 接管清 finished_at
