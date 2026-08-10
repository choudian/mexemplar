"""用户任务层（«用户交办的一件事»）API 路由。"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.business.task_collaboration.service import TaskCollaborationService
from src.business.user_tasks import UserTaskService
from src.desktop_api.assistant_runtime import AssistantRuntime
from src.desktop_api.routers.assistant import get_assistant_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions/{session_id}/user-tasks", tags=["user-tasks"])


class UserTaskItem(BaseModel):
    taskId: str
    title: str
    description: str
    status: str


class UserTaskListResponse(BaseModel):
    tasks: list[UserTaskItem]


class UserTaskStatusDistributionResponse(BaseModel):
    """一件事底下所有执行节点的状态分布。"""
    taskId: str
    distribution: dict[str, int]


class UserTaskContinueResponse(BaseModel):
    """用户点继续的结构化回报。"""
    pushed: list[dict[str, Any]]
    notPushed: list[dict[str, Any]]
    total: int
    success: bool


class UserTaskGraphSummary(BaseModel):
    """某 user_task 名下一张图的摘要。"""
    graphId: str
    rootTaskId: str
    title: str
    nodeCount: int
    status: str
    createdAt: str | None = None


class UserTaskGraphsResponse(BaseModel):
    graphs: list[UserTaskGraphSummary]


@router.get("", response_model=UserTaskListResponse)
def list_user_tasks(
    session_id: str,
    status_filter: str = "open",
    runtime: AssistantRuntime = Depends(get_assistant_runtime),
) -> UserTaskListResponse:
    """列出会话的用户任务。默认只看 open（active/cooling）。"""
    with UserTaskService() as service:
        tasks = service.list_for_session(
            session_id=session_id, status_filter=status_filter
        )
    return UserTaskListResponse(
        tasks=[
            UserTaskItem(
                taskId=t["taskId"],
                title=t["title"],
                description=t.get("description", ""),
                status=t["status"],
            )
            for t in tasks
        ]
    )


@router.get("/{task_id}/distribution", response_model=UserTaskStatusDistributionResponse)
def get_user_task_distribution(
    session_id: str,
    task_id: str,
    runtime: AssistantRuntime = Depends(get_assistant_runtime),
) -> UserTaskStatusDistributionResponse:
    """获取用户任务下所有执行节点的状态分布（供界面画分布条）。"""
    with UserTaskService() as service:
        distribution = service.status_distribution(task_id)
    return UserTaskStatusDistributionResponse(taskId=task_id, distribution=distribution)


@router.post("/{task_id}/continue", response_model=UserTaskContinueResponse)
def continue_user_task(
    session_id: str,
    task_id: str,
    runtime: AssistantRuntime = Depends(get_assistant_runtime),
) -> UserTaskContinueResponse:
    """用户对一件事点「继续」：遍历这件事底下所有图，推得动的都推。

    返回结构化回报：几摊动了、几摊没动、每摊没动的原因。
    """
    report = runtime.continue_user_task(session_id, task_id)
    # 后端 service 返回 snake_case（graph_id），DTO 要求 camelCase（graphId）
    pushed = [
        {"title": item.get("title", ""), "graphId": item.get("graph_id")}
        for item in report.get("pushed", [])
    ]
    not_pushed = [
        {"title": item.get("title", ""), "reason": item.get("reason", "")}
        for item in report.get("not_pushed", [])
    ]
    return UserTaskContinueResponse(
        pushed=pushed,
        notPushed=not_pushed,
        total=report.get("total", 0),
        success=report.get("success", False),
    )


@router.get("/{task_id}/graphs", response_model=UserTaskGraphsResponse)
def get_user_task_graphs(
    session_id: str,
    task_id: str,
    runtime: AssistantRuntime = Depends(get_assistant_runtime),
) -> UserTaskGraphsResponse:
    """列出某 user_task 名下所有任务图（供局部图/全图弹窗入口）。

    一件事可能有多张图（跨多轮沟通先后建图）。
    """
    with TaskCollaborationService() as service:
        graphs = service.list_graphs_for_user_task(task_id)
    return UserTaskGraphsResponse(
        graphs=[
            UserTaskGraphSummary(
                graphId=g["graphId"],
                rootTaskId=g["rootTaskId"],
                title=g["title"],
                nodeCount=g["nodeCount"],
                status=g["status"],
                createdAt=g.get("createdAt"),
            )
            for g in graphs
        ]
    )

