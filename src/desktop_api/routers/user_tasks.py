"""用户任务层（«用户交办的一件事»）API 路由。"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from src.business.task_collaboration.service import TaskCollaborationService
from src.business.user_tasks import UserTaskService
from src.desktop_api.assistant_runtime import AssistantRuntime
from src.desktop_api.routers.assistant import get_assistant_runtime

logger = logging.getLogger(__name__)

# 前缀必须带 `/api/assistant`，与 assistant.py / assistant_tasks.py 一致——
# 前端 typed client 统一按该前缀调用；少了它整个用户任务层接口 404，
# 卡片拿不到列表就不渲染，⑦ 的界面链路第一步就断了。
router = APIRouter(
    prefix="/api/assistant/sessions/{session_id}/user-tasks", tags=["user-tasks"]
)


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
    stillFinishing: list[dict[str, Any]] = Field(default_factory=list)
    total: int
    success: bool


class UserTaskStopResponse(BaseModel):
    """用户点停止的结构化回报。"""
    stopped: list[dict[str, Any]]
    total: int
    success: bool


class UserTaskGraphSummary(BaseModel):
    """某 user_task 名下一张图的摘要。"""
    graphId: str
    rootTaskId: str
    title: str
    nodeCount: int
    status: str
    # plan=planner 产的 DAG（展示局部图）；request=委派容器（节点平铺为执行体，
    # 不以任务图身份展示）。旧数据无值时 service 层默认 request。
    kind: str = "request"
    # 仓库层给的是 datetime 对象，不是字符串——声明成 str 会让整个接口
    # 500（pydantic string_type 校验失败），卡片展开时拉不到图。
    # 项目内其他 DTO 的时间字段同样直接用 datetime。
    createdAt: datetime | None = None
    userMessageSequence: int | None = None


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
    still_finishing = [
        {"title": item.get("title", ""), "reason": item.get("reason", "")}
        for item in report.get("still_finishing", [])
    ]
    return UserTaskContinueResponse(
        pushed=pushed,
        notPushed=not_pushed,
        stillFinishing=still_finishing,
        total=report.get("total", 0),
        success=report.get("success", False),
    )


@router.post("/{task_id}/stop", response_model=UserTaskStopResponse)
def stop_user_task(
    session_id: str,
    task_id: str,
    runtime: AssistantRuntime = Depends(get_assistant_runtime),
) -> UserTaskStopResponse:
    """用户对一件事点「停止」：遍历这件事底下所有图，把正在跑的都停了。

    返回结构化回报：停了几张图、几张没动。
    """
    report = runtime.stop_user_task(session_id, task_id)
    stopped = [
        {"graphId": item.get("graph_id"), "affected": item.get("affected", 0)}
        for item in report.get("stopped", [])
    ]
    return UserTaskStopResponse(
        stopped=stopped,
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
                userMessageSequence=g.get("userMessageSequence"),
            )
            for g in graphs
        ]
    )

