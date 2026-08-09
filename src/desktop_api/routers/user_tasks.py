"""用户任务层（«用户交办的一件事»）API 路由。"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from src.business.user_tasks import UserTaskService
from src.desktop_api.assistant_runtime import AssistantRuntime
from src.desktop_api.routers.assistant import get_assistant_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions/{session_id}/user-tasks", tags=["user-tasks"])


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
    return UserTaskContinueResponse(
        pushed=report.get("pushed", []),
        notPushed=report.get("not_pushed", []),
        total=report.get("total", 0),
        success=report.get("success", False),
    )
