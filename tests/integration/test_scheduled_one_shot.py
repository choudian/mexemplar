"""T051: 一次性定时 e2e — 创建 → 到点触发 → 完成 → 历史 + 终态不重复（US2）。

轻量 mock 版（worker._tick 模拟到点；RunCompletionMonitor 注入静默 callbacks）。
"""

from __future__ import annotations

from datetime import timedelta

from types import SimpleNamespace

from src.business.scheduling.run_completion_monitor import RunCompletionMonitor
from src.business.scheduling.scheduler_service import SchedulerService
from src.business.scheduling.scheduler_worker import SchedulerWorker
from src.data.models_sqlite import Message
from src.data.repos.message_repository import MessageRepository
from src.data.repos.scheduled_task_run_repository import ScheduledTaskRunRepository
from src.utils.timezone import utc_now_naive


class _FakeLauncher:
    def __init__(self) -> None:
        self.launches: list[str] = []

    def launch(self, *, scheduled_task_id, instruction, started_at=None):
        self.launches.append(scheduled_task_id)
        from src.data.repos.scheduled_task_run_repository import ScheduledTaskRunRepository

        # 真实建 run（fire 路径）
        with ScheduledTaskRunRepository() as rr:
            run = rr.create(
                scheduled_task_id=scheduled_task_id,
                session_id=f"ast_oneshot_{scheduled_task_id}",
                started_at=started_at,
            )
        return run.run_id


def _quiesce(session_id: str, snapshot_tasks=None):
    """构造静默 RunCompletionMonitor.evaluate_session。"""
    tasks = snapshot_tasks or [
        SimpleNamespace(task_id="root", parent_task_id=None, status="completed"),
        SimpleNamespace(task_id="t1", parent_task_id="root", status="completed"),
    ]
    snapshot = SimpleNamespace(tasks=tasks)
    with ScheduledTaskRunRepository() as rr:
        return RunCompletionMonitor(
            has_active_worker=lambda sid: False,
            has_pending_reentry=lambda sid: False,
            get_graph_snapshot=lambda sid: snapshot,
            run_repo=rr,
        ).evaluate_session(session_id)


def test_one_shot_fires_once_then_completed_no_repeat():
    """一次性任务到点触发一次 → 完成 → worker 再 tick 不重复触发。"""
    launcher = _FakeLauncher()
    with SchedulerService(launcher=launcher) as service:
        task = service.create_from_draft(
            {
                "source_type": "direct",
                "source_ref": "整理会议纪要",
                "title": "会议纪要",
                "schedule_kind": "one_shot",
                "schedule_payload": {"run_at": "now"},
                "instruction": "整理本周会议纪要",
            }
        )
        task_id = task["scheduledTaskId"]

        # 到点：worker._tick 触发
        worker = SchedulerWorker(service, launcher)
        worker._tick()
        assert launcher.launches.count(task_id) == 1
        # one_shot 触发后 status=completed、next_fire=NULL（终态）
        row = service._repo.get(task_id)
        assert row.status == "completed"
        assert row.next_fire_at is None

        # 再 tick 不重复触发
        worker._tick()
        assert launcher.launches.count(task_id) == 1


def test_one_shot_completion_writes_terminal_run_and_summary():
    """一次性 run 静默后写 succeeded + summary，历史可见。"""
    launcher = _FakeLauncher()
    with SchedulerService(launcher=launcher) as service:
        task = service.create_from_draft(
            {
                "source_type": "direct",
                "source_ref": "纪要",
                "title": "纪要",
                "schedule_kind": "one_shot",
                "schedule_payload": {"run_at": "now"},
                "instruction": "整理纪要",
            }
        )
        task_id = task["scheduledTaskId"]
        worker = SchedulerWorker(service, launcher)
        worker._tick()

        # 取刚建的 run 的 session，塞 assistant 消息，静默判定
        runs, _ = service.list_runs(task_id)
        session_id = runs[0]["sessionId"]
        with MessageRepository() as mr:
            mr.session.add(
                Message(
                    message_id=f"msg_{session_id}",
                    session_id=session_id,
                    role="assistant",
                    content="纪要已整理完成",
                    sequence=1,
                )
            )
            mr.session.commit()
        result = _quiesce(session_id)
        assert result is not None and result["status"] == "succeeded"

        runs2, _ = service.list_runs(task_id)
        assert any(r["status"] == "succeeded" for r in runs2)


def test_one_shot_past_fire_still_fires_misfire():
    """一次性任务 run_at 已过（app 未运行错过）→ worker 仍补跑一次（misfire 补最近一次）。"""
    launcher = _FakeLauncher()
    with SchedulerService(launcher=launcher) as service:
        task = service.create_from_draft(
            {
                "source_type": "direct",
                "source_ref": "补跑",
                "title": "补跑",
                "schedule_kind": "one_shot",
                "schedule_payload": {
                    "run_at": (utc_now_naive() - timedelta(minutes=5)).isoformat()
                },
                "instruction": "补跑任务",
            }
        )
        task_id = task["scheduledTaskId"]
        SchedulerWorker(service, launcher)._tick()
        assert launcher.launches.count(task_id) == 1  # 补跑一次
        assert service._repo.get(task_id).status == "completed"
