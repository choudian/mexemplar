"""执行体 todo 的两个动作：列出（create）与按 id 改（update）。

原先只有一个全量替换的 ``todo_update``：执行体每次交完整清单，漏带一条就等于
删除，而「漏带」和「有意删除」在数据上无法区分。它还得自己填 ``todoId``，
schema 里那个字段又没有说明，于是模型每个任务都从 "1" 开始编号——第二个建
清单的任务写第一条即撞主键，``UNIQUE constraint failed`` 让整批回滚，那个
任务一条 todo 都存不下（2026-08-11 实跑复现）。

现在拆开：``create`` 不接受 id（系统分配、随返回值给出），``update`` 必须带
id 且只改给出的字段。id 规则从模型软约束变成结构性的。
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from src.business.agents.config import AgentType
from src.business.task_collaboration.todos import TaskTodoService
from src.data.models_sqlite import Session as SessionModel
from src.data.repos import AssistantTaskRepository, AssistantTodoRepository, SessionRepository
from src.data.repos.assistant_task_attempt_repository import AssistantTaskAttemptRepository
from src.utils.timezone import utc_now_naive

EXECUTOR = "ephemeral_subagent"


def _seed_task(session_id: str, task_id: str, exec_session: str) -> None:
    try:
        SessionRepository().create(
            SessionModel(
                session_id=session_id, workflow_id=None,
                agent_type=AgentType.ASSISTANT, status="active",
            )
        )
    except Exception:
        pass  # 同一会话下建第二个任务时会话已存在
    with AssistantTaskRepository() as tasks:
        tasks.create_task(
            graph_id=f"tg_{task_id}", session_id=session_id, task_id=task_id,
            title="抓数据", description="d",
            assignee_type=EXECUTOR, assignee_id=EXECUTOR, status="running",
        )
    with AssistantTaskAttemptRepository() as attempts:
        attempts.start_attempt(
            task_id=task_id, executor_type=EXECUTOR, executor_id=EXECUTOR,
            lease_owner="test", lease_expires_at=utc_now_naive() + timedelta(minutes=5),
        )
        attempts.bind_session(task_id=task_id, executor_session_id=exec_session)


def _create(svc: TaskTodoService, task_id: str, exec_session: str, *texts: str) -> list[dict]:
    return svc.create_todos(
        task_id=task_id, executor_type=EXECUTOR, executor_id=EXECUTOR,
        items=[{"text": t} for t in texts], executor_session_id=exec_session,
    )


def test_create_assigns_ids_and_returns_them():
    """执行体不填 id，系统分配并随返回值交给它。"""
    _seed_task("s_a", "tsk_a", "es_a")
    with TaskTodoService() as svc:
        rows = _create(svc, "tsk_a", "es_a", "抓 Daily", "抓 Weekly")
    assert [r["text"] for r in rows] == ["抓 Daily", "抓 Weekly"]
    assert all(r["todoId"].startswith("todo_") for r in rows), rows
    assert len({r["todoId"] for r in rows}) == 2
    assert [r["sortOrder"] for r in rows] == [1, 2]


def test_two_tasks_never_collide():
    """两个任务各自列清单，id 全局唯一，不会互相撞。"""
    _seed_task("s_b", "tsk_b1", "es_b1")
    _seed_task("s_b", "tsk_b2", "es_b2")
    with TaskTodoService() as svc:
        a = _create(svc, "tsk_b1", "es_b1", "抓 Daily", "抓 Weekly")
        b = _create(svc, "tsk_b2", "es_b2", "读配置", "跑校验", "写报告")
        assert [t["text"] for t in svc.list_todos("tsk_b1")] == ["抓 Daily", "抓 Weekly"]
        assert [t["text"] for t in svc.list_todos("tsk_b2")] == ["读配置", "跑校验", "写报告"]
    assert not ({t["todoId"] for t in a} & {t["todoId"] for t in b})


def test_update_changes_only_given_fields():
    """按 id 改：给什么改什么，没给的保持原样。"""
    _seed_task("s_c", "tsk_c", "es_c")
    with TaskTodoService() as svc:
        created = _create(svc, "tsk_c", "es_c", "抓 Daily", "抓 Weekly")
        updated = svc.update_todo(
            task_id="tsk_c", todo_id=created[0]["todoId"],
            executor_type=EXECUTOR, executor_id=EXECUTOR,
            executor_session_id="es_c", status="done",
        )
        rows = svc.list_todos("tsk_c")

    assert updated["status"] == "done"
    assert updated["text"] == "抓 Daily", "没给 text 就不该动它"
    assert len(rows) == 2, "改一条不该影响另一条"
    assert [r["status"] for r in rows] == ["done", "todo"]


def test_update_rejects_unknown_id():
    """id 不存在直接报错，不静默新建——否则执行体会以为改成功了。"""
    _seed_task("s_d", "tsk_d", "es_d")
    with TaskTodoService() as svc:
        _create(svc, "tsk_d", "es_d", "唯一一步")
        with pytest.raises(LookupError):
            svc.update_todo(
                task_id="tsk_d", todo_id="1",  # 执行体自己编的号
                executor_type=EXECUTOR, executor_id=EXECUTOR,
                executor_session_id="es_d", status="done",
            )
        assert len(svc.list_todos("tsk_d")) == 1, "失败的更新不该留下副作用"


def test_create_appends_without_touching_existing():
    """追加语义：再列几条不影响已有的进度。"""
    _seed_task("s_e", "tsk_e", "es_e")
    with TaskTodoService() as svc:
        first = _create(svc, "tsk_e", "es_e", "第一步")
        svc.update_todo(
            task_id="tsk_e", todo_id=first[0]["todoId"],
            executor_type=EXECUTOR, executor_id=EXECUTOR,
            executor_session_id="es_e", status="done",
        )
        _create(svc, "tsk_e", "es_e", "追加的一步")
        rows = svc.list_todos("tsk_e")

    assert [r["text"] for r in rows] == ["第一步", "追加的一步"]
    assert rows[0]["status"] == "done", "已有条目的进度被追加操作冲掉了"
    assert rows[1]["sortOrder"] == 2, "追加的条目应排在已有条目之后"


def test_records_which_session_created_the_todo():
    """记下是哪个执行会话建的——临时子代理的 executor_id 只是类型名，
    定位不到具体哪次执行，靠这一列回溯。"""
    _seed_task("s_f", "tsk_f", "es_f")
    with TaskTodoService() as svc:
        _create(svc, "tsk_f", "es_f", "第一步", "第二步")
    with AssistantTodoRepository() as repo:
        rows = repo.list_for_task("tsk_f")
    assert {r.creator_session_id for r in rows} == {"es_f"}


def test_creator_survives_takeover_by_another_session():
    """续跑后换会话接手：改状态不覆盖创建来源，新列的条目记新会话。"""
    _seed_task("s_g", "tsk_g", "es_g1")
    with TaskTodoService() as svc:
        created = _create(svc, "tsk_g", "es_g1", "第一步")
        # 模拟 503 暂停后续跑，换一个执行会话接手
        with AssistantTaskAttemptRepository() as attempts:
            attempts.bind_session(task_id="tsk_g", executor_session_id="es_g2")
        svc.update_todo(
            task_id="tsk_g", todo_id=created[0]["todoId"],
            executor_type=EXECUTOR, executor_id=EXECUTOR,
            executor_session_id="es_g2", status="done",
        )
        _create(svc, "tsk_g", "es_g2", "接手后新增")
    with AssistantTodoRepository() as repo:
        by_text = {r.text: r.creator_session_id for r in repo.list_for_task("tsk_g")}
    assert by_text["第一步"] == "es_g1", "创建来源被接手方冲掉了"
    assert by_text["接手后新增"] == "es_g2"
