"""执行记录与执行会话的绑定。

派活时执行体尚未创建，所以 ``executor_id`` 对临时子代理只能填任务 id 顶替——
"谁在干这活"因此在库里不存在，``ask_parent`` / ``todo_update`` 的归属校验永远查无此人。
执行体在 agent loop 启动前把自己的会话 id 绑定到当前 active attempt，补上这条身份。
"""

from __future__ import annotations

from datetime import timedelta

from src.data.repos import AssistantTaskAttemptRepository, AssistantTaskRepository
from src.utils.timezone import utc_now_naive


def _task(task_id: str = "tsk_bind") -> str:
    repo = AssistantTaskRepository()
    row = repo.create_task(
        graph_id="tg_bind",
        session_id="ast_bind",
        task_id=task_id,
        title="bind",
        description="bind",
        owner_session_id="ast_bind",
        status="running",
    )
    return row.task_id


def _attempt(task_id: str, attempts: AssistantTaskAttemptRepository):
    return attempts.start_attempt(
        task_id=task_id,
        executor_type="ephemeral_subagent",
        executor_id=task_id,
        lease_owner="graph_scheduler",
        lease_expires_at=utc_now_naive() + timedelta(minutes=2),
    )


def test_bind_session_records_executor_session_on_active_attempt() -> None:
    task_id = _task()
    attempts = AssistantTaskAttemptRepository()
    attempt = _attempt(task_id, attempts)
    assert attempt is not None

    bound = attempts.bind_session(task_id=task_id, executor_session_id="sess_child_1")

    assert bound is True
    assert attempts.get_by_id(attempt.attempt_id).executor_session_id == "sess_child_1"


def test_bind_session_returns_false_when_task_has_no_active_attempt() -> None:
    task_id = _task("tsk_no_attempt")
    attempts = AssistantTaskAttemptRepository()

    assert attempts.bind_session(task_id=task_id, executor_session_id="sess_child_1") is False


def test_active_attempt_session_reads_back_bound_session() -> None:
    task_id = _task()
    attempts = AssistantTaskAttemptRepository()
    _attempt(task_id, attempts)
    attempts.bind_session(task_id=task_id, executor_session_id="sess_child_2")

    assert attempts.active_attempt_session(task_id) == "sess_child_2"


def test_active_attempt_session_is_none_before_binding() -> None:
    task_id = _task()
    attempts = AssistantTaskAttemptRepository()
    _attempt(task_id, attempts)

    assert attempts.active_attempt_session(task_id) is None
