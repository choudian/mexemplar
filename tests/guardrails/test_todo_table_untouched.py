"""Guard: 调度路径不写 user_todos 表（033 CC-001 / FR-015）。

待办只以 ``todo_id`` 字符串外部引用；创建 / 触发 / 滚动 todo 来源任务 MUST NOT 修改
``user_todos`` 表（行数、状态、updated_at 不变）。
"""

from __future__ import annotations

import pytest

from src.business.scheduling.scheduler_service import SchedulerService
from src.data.repos.scheduled_task_run_repository import ScheduledTaskRunRepository
from src.data.repos.user_todo_repository import UserTodoRepository
from src.utils.timezone import utc_now_naive


def _snapshot_user_todos() -> list[tuple]:
    from src.data.models_sqlite import UserTodo

    with UserTodoRepository() as r:
        todos = r.session.query(UserTodo).all()
    return [(t.todo_id, t.status, t.title, str(t.updated_at)) for t in todos]


def _make_todo() -> str:
    with UserTodoRepository() as r:
        todo = r.create(title="整理 PR 列表", description="本周", priority="medium")
        return todo.todo_id


def test_creating_todo_sourced_task_does_not_write_user_todos():
    todo_id = _make_todo()
    before = _snapshot_user_todos()

    service = SchedulerService()
    service.create_from_draft(
        {
            "source_type": "todo",
            "source_ref": todo_id,
            "title": "待办任务",
            "schedule_kind": "one_shot",
            "schedule_payload": {"run_at": "now"},
            "instruction": "整理 PR",
        }
    )

    after = _snapshot_user_todos()
    assert before == after, "创建 todo 来源任务不得写 user_todos"


def test_firing_todo_sourced_task_does_not_write_user_todos():
    todo_id = _make_todo()

    class _FakeLauncher:
        @staticmethod
        def launch(*, scheduled_task_id, instruction, started_at=None):
            with ScheduledTaskRunRepository() as run_repo:
                return run_repo.create(
                    scheduled_task_id=scheduled_task_id,
                    session_id="ast_todo_write_guard",
                    started_at=started_at,
                ).run_id

    service = SchedulerService(launcher=_FakeLauncher())
    task = service.create_from_draft(
        {
            "source_type": "todo",
            "source_ref": todo_id,
            "title": "待办任务",
            "schedule_kind": "one_shot",
            "schedule_payload": {"run_at": "now"},
            "instruction": "整理 PR",
        }
    )
    task_id = task["scheduledTaskId"]
    before = _snapshot_user_todos()

    # fire_now 必须显式注入 runtime launcher；受控替身只建 run，不碰 user_todos。
    service.fire_now(task_id)

    after = _snapshot_user_todos()
    assert before == after, "触发 todo 来源任务不得写 user_todos"


def test_todo_dangling_does_not_write_user_todos():
    """待办被删（悬空）时任务作废，仍不得写 user_todos。"""
    todo_id = _make_todo()
    service = SchedulerService()
    task = service.create_from_draft(
        {
            "source_type": "todo",
            "source_ref": todo_id,
            "title": "待办任务",
            "schedule_kind": "one_shot",
            "schedule_payload": {"run_at": "now"},
            "instruction": "整理 PR",
        }
    )
    task_id = task["scheduledTaskId"]
    # 删除待办（user_todos 物理删——这是 user_todos 自身能力，不是调度路径写的）
    with UserTodoRepository() as r:
        r.delete(todo_id)
    before = _snapshot_user_todos()

    # 触发已悬空任务：先作废 scheduled task，再显式拒绝启动会话。
    with pytest.raises(ValueError, match="todo is unavailable"):
        service.fire_now(task_id)
    assert service._repo.get(task_id).status == "expired"

    after = _snapshot_user_todos()
    assert before == after, "悬空处理不得写 user_todos"


def test_worker_expires_dangling_todo_task():
    """T058：worker 扫到 todo 来源到期任务、待办已被删/完成 → 任务作废 expired，不触发。"""
    from src.business.scheduling.scheduler_worker import SchedulerWorker

    todo_id = _make_todo()
    service = SchedulerService()
    task = service.create_from_draft(
        {
            "source_type": "todo",
            "source_ref": todo_id,
            "title": "待办任务",
            "schedule_kind": "one_shot",
            "schedule_payload": {"run_at": "now"},
            "instruction": "整理 PR",
        }
    )
    task_id = task["scheduledTaskId"]
    service._repo.cas_next_fire(task_id, next_fire_at=utc_now_naive())  # due

    # 用户手动标记待办完成（悬空）
    with UserTodoRepository() as r:
        r.update(todo_id, {"status": "done"})

    class _FakeLauncher:
        def __init__(self):
            self.launches = []

        def launch(self, *, scheduled_task_id, instruction, started_at=None):
            self.launches.append((scheduled_task_id, instruction))

    launcher = _FakeLauncher()
    SchedulerWorker(service, launcher)._tick()

    # 任务作废 expired，不触发会话
    assert launcher.launches == []
    assert service._repo.get(task_id).status == "expired"


def test_worker_fires_when_todo_still_active():
    """对照：todo 来源任务、待办仍 active → 正常触发（不作废）。"""
    from src.business.scheduling.scheduler_worker import SchedulerWorker

    todo_id = _make_todo()
    service = SchedulerService()
    task = service.create_from_draft(
        {
            "source_type": "todo",
            "source_ref": todo_id,
            "title": "待办任务",
            "schedule_kind": "one_shot",
            "schedule_payload": {"run_at": "now"},
            "instruction": "整理 PR",
        }
    )
    task_id = task["scheduledTaskId"]
    service._repo.cas_next_fire(task_id, next_fire_at=utc_now_naive())

    class _FakeLauncher:
        def __init__(self):
            self.launches = []

        def launch(self, *, scheduled_task_id, instruction, started_at=None):
            self.launches.append((scheduled_task_id, instruction))

    launcher = _FakeLauncher()
    SchedulerWorker(service, launcher)._tick()

    assert launcher.launches == [(task_id, "整理 PR")]
