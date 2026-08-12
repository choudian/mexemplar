"""用户任务层 API 的路径门卫。

背景：`user_tasks.router` 的 prefix 曾漏掉 `/api/assistant`，实际注册成
`/sessions/{id}/user-tasks`，而前端 typed client 按 `/api/assistant/...` 调用
——四个端点全部 404。后端本身没报错、前端只是拿到空列表，于是用户任务卡片
静默不渲染，⑦ 的整条界面链路（执行体、todolist、继续按钮）跟着全部不可见。

这类不一致不会被任何业务测试发现，必须由路径门卫守住。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.desktop_api.app import create_app

# 前端 frontend/src/api/userTasks.ts 使用的路径模板（保持同步）
FRONTEND_USER_TASK_PATHS = [
    "/api/assistant/sessions/{session_id}/user-tasks",
    "/api/assistant/sessions/{session_id}/user-tasks/{task_id}/distribution",
    "/api/assistant/sessions/{session_id}/user-tasks/{task_id}/continue",
    "/api/assistant/sessions/{session_id}/user-tasks/{task_id}/graphs",
]


def test_registered_paths_match_frontend_client():
    """后端注册的路径必须与前端 typed client 逐字一致。"""
    registered = {getattr(route, "path", "") for route in create_app().routes}
    missing = [p for p in FRONTEND_USER_TASK_PATHS if p not in registered]
    assert not missing, (
        f"以下前端调用的路径未注册（会 404）: {missing}\n"
        f"已注册的 user-task 路径: "
        f"{sorted(p for p in registered if 'user-task' in p)}"
    )


def test_user_task_routes_are_reachable(desktop_api_client: TestClient):
    """真实请求不得返回 404——业务结果可以是空列表，但路由必须存在。"""
    response = desktop_api_client.get(
        "/api/assistant/sessions/ast_missing/user-tasks?statusFilter=open"
    )
    assert response.status_code != 404, "用户任务列表接口不可达"
    assert response.status_code == 200
    assert response.json() == {"tasks": []}


@pytest.mark.parametrize(
    "suffix",
    ["/distribution", "/graphs"],
)
def test_user_task_subresources_are_reachable(
    desktop_api_client: TestClient, suffix: str
):
    """子资源同样不得 404（不存在的 task 允许返回空结果或业务错误）。"""
    response = desktop_api_client.get(
        f"/api/assistant/sessions/ast_missing/user-tasks/utsk_missing{suffix}"
    )
    assert response.status_code != 404, f"{suffix} 接口不可达"


def test_graphs_endpoint_serializes_real_rows(desktop_api_client: TestClient):
    """带真实数据时也要能返回——空列表跑不到 DTO 的字段序列化。

    ``createdAt`` 曾被声明成 ``str``，而仓库层给的是 ``datetime`` 对象，
    于是这个接口对任何真实数据都 500（pydantic string_type），卡片展开时
    拉不到图，局部图和执行体兜底链路一起断（2026-08-11 实跑复现）。
    """
    from datetime import timedelta

    from src.business.agents.config import AgentType
    from src.data.models_sqlite import Session as SessionModel
    from src.data.repos import (
        AssistantTaskRepository,
        SessionRepository,
        UserTaskRepository,
    )

    SessionRepository().create(
        SessionModel(
            session_id="ast_graphs", workflow_id=None,
            agent_type=AgentType.ASSISTANT, status="active",
        )
    )
    with UserTaskRepository() as repo:
        user_task_id = repo.create(
            session_id="ast_graphs", title="季度报告", description="d",
        ).task_id
    with AssistantTaskRepository() as tasks:
        tasks.create_task(
            graph_id="tg_real", session_id="ast_graphs", task_id="tsk_real",
            title="抓数据", description="d",
            assignee_type="ephemeral_subagent", assignee_id="exec_1",
            status="running", user_task_id=user_task_id,
            user_message_sequence=3,
        )

    response = desktop_api_client.get(
        f"/api/assistant/sessions/ast_graphs/user-tasks/{user_task_id}/graphs"
    )
    assert response.status_code == 200, response.text
    graphs = response.json()["graphs"]
    assert len(graphs) == 1
    assert graphs[0]["graphId"] == "tg_real"
    assert graphs[0]["nodeCount"] == 1
    # 供卡片把局部图按发生顺序插进流里
    assert graphs[0]["userMessageSequence"] == 3
