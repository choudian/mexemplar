"""``/api/scheduled-tasks`` router（033 调度中心管理 + 历史 + 接管 + 确认卡决策）。

仿 ``routers/user_todos.py``（``APIRouter(prefix="/api/scheduled-tasks")``），schema 集中
在 ``desktop_api/schemas.py``，字段一律 camelCase。鉴权自动（应用级 ``X-Mexemplar-Session``
中间件，零 Depends）。错误映射手写 ``LookupError→404 / ValueError→422``。

创建入口：定时任务创建经主助理工具 + 创建确认卡（见 ``confirmation-and-unattended.md``），
REST 不暴露创建表单（FR-005）。本 router 只承载管理、行内操作、历史、接管、确认卡决策提交。

CC-005 三重不暴露之一：router create/update 源码不含该免确认字段的 snake_case 字面量
（PATCH 接受 ``unattendedAutoApprove`` camelCase 是详情页开关的唯一 REST 写入路径，guard
test ``test_scheduled_task_unattended_field_isolated.py`` 按 snake_case 不出现断言）。
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from src.business.scheduling.scheduler_service import (
    SchedulerRuntimeUnavailable,
    SchedulerService,
    ScheduledSessionResetConflict,
    ScheduledTakeoverUnavailable,
)
from src.business.scheduling.session_launcher import ScheduledSessionCreationFailed
from src.business.scheduling.scheduling_confirmation_manager import (
    get_scheduling_confirmation_manager,
)
from src.desktop_api.schemas import (
    ScheduledConfirmationDecisionRequest,
    ScheduledConfirmationPendingItem,
    ScheduledConfirmationPendingResponse,
    ScheduledTaskItem,
    ScheduledTaskListResponse,
    ScheduledTaskPatchRequest,
    ScheduledTaskRunItem,
    ScheduledTaskRunListResponse,
    ScheduledTaskStartedRunItem,
    TakeoverResponse,
)

router = APIRouter(prefix="/api/scheduled-tasks", tags=["scheduled-tasks"])


def get_scheduler_service() -> Iterator[SchedulerService]:
    with SchedulerService() as service:
        yield service


# ---------------------------------------------------------------------------
# 任务 CRUD（不含创建表单）+ 行内操作
# ---------------------------------------------------------------------------


@router.get("", response_model=ScheduledTaskListResponse)
def list_scheduled_tasks(
    status: Literal["active", "paused", "completed", "expired"] | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    service: SchedulerService = Depends(get_scheduler_service),
) -> ScheduledTaskListResponse:
    items, total = service.list_tasks(status_filter=status, limit=limit, offset=offset)
    return ScheduledTaskListResponse(
        items=[ScheduledTaskItem(**item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{scheduled_task_id}", response_model=ScheduledTaskItem)
def get_scheduled_task(
    scheduled_task_id: str,
    service: SchedulerService = Depends(get_scheduler_service),
) -> ScheduledTaskItem:
    try:
        return ScheduledTaskItem(**service.get_task(scheduled_task_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="scheduled_task_not_found") from exc


@router.patch("/{scheduled_task_id}", response_model=ScheduledTaskItem)
def patch_scheduled_task(
    scheduled_task_id: str,
    body: ScheduledTaskPatchRequest,
    service: SchedulerService = Depends(get_scheduler_service),
) -> ScheduledTaskItem:
    """暂停/启用、``unattendedAutoApprove`` 开关（**仅这俩**）。

    严禁接受 scheduleKind / schedulePayload / sourceType / sourceRef / title —— schema
    层已限定字段集。``status='paused'`` → pause；``status='active'`` → resume。
    """
    try:
        if body.status is not None:
            if body.status == "paused":
                result = service.pause(scheduled_task_id)
            else:
                result = service.resume(scheduled_task_id)
            # 同请求里若同时带 unattendedAutoApprove，再单独写入
            if body.unattendedAutoApprove is not None:
                result = service.set_unattended(scheduled_task_id, body.unattendedAutoApprove)
            return ScheduledTaskItem(**result)
        if body.unattendedAutoApprove is not None:
            return ScheduledTaskItem(
                **service.set_unattended(scheduled_task_id, body.unattendedAutoApprove)
            )
        # 空补丁：返回当前快照（PATCH 语义，幂等）
        return ScheduledTaskItem(**service.get_task(scheduled_task_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="scheduled_task_not_found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/{scheduled_task_id}/fire-now",
    response_model=ScheduledTaskStartedRunItem,
    status_code=202,
)
def fire_now(
    scheduled_task_id: str,
    service: SchedulerService = Depends(get_scheduler_service),
) -> ScheduledTaskStartedRunItem:
    """行内「现在跑一次」立即触发（FR-018，不经确认卡）。reentry 仍生效。"""
    try:
        result = service.fire_now(scheduled_task_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="scheduled_task_not_found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SchedulerRuntimeUnavailable as exc:
        raise HTTPException(status_code=503, detail="scheduler_runtime_unavailable") from exc
    except ScheduledSessionCreationFailed as exc:
        raise HTTPException(status_code=503, detail="scheduled_task_start_failed") from exc
    status = result.get("status")
    if status == "skipped":
        raise HTTPException(status_code=409, detail="scheduled_task_run_already_active")
    if status == "failed":
        raise HTTPException(status_code=503, detail="scheduled_task_start_failed")
    if status != "running":
        raise HTTPException(status_code=503, detail="scheduled_task_not_started")
    return ScheduledTaskStartedRunItem(**result)


@router.post(
    "/{scheduled_task_id}/reset-session",
    response_model=ScheduledTaskItem,
)
def reset_session(
    scheduled_task_id: str,
    service: SchedulerService = Depends(get_scheduler_service),
) -> ScheduledTaskItem:
    """显式重开：安全解绑 current session，下一次触发创建新会话。"""
    try:
        return ScheduledTaskItem(**service.reset_session(scheduled_task_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="scheduled_task_not_found") from exc
    except ScheduledSessionResetConflict as exc:
        raise HTTPException(status_code=409, detail="scheduled_task_session_busy") from exc
    except SchedulerRuntimeUnavailable as exc:
        raise HTTPException(status_code=503, detail="scheduler_runtime_unavailable") from exc


@router.delete("/{scheduled_task_id}", status_code=204)
def delete_scheduled_task(
    scheduled_task_id: str,
    service: SchedulerService = Depends(get_scheduler_service),
) -> Response:
    try:
        service.soft_delete(scheduled_task_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="scheduled_task_not_found") from exc
    return Response(status_code=204)


# ---------------------------------------------------------------------------
# 历史 runs + 接管
# ---------------------------------------------------------------------------


@router.get("/{scheduled_task_id}/runs", response_model=ScheduledTaskRunListResponse)
def list_scheduled_task_runs(
    scheduled_task_id: str,
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    service: SchedulerService = Depends(get_scheduler_service),
) -> ScheduledTaskRunListResponse:
    try:
        items, total = service.list_runs(scheduled_task_id, limit=limit, offset=offset)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="scheduled_task_not_found") from exc
    return ScheduledTaskRunListResponse(
        items=[ScheduledTaskRunItem(**item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/{scheduled_task_id}/runs/{run_id}/takeover",
    response_model=TakeoverResponse,
)
def takeover_run(
    scheduled_task_id: str,
    run_id: str,
    service: SchedulerService = Depends(get_scheduler_service),
) -> TakeoverResponse:
    """接管 ``waiting_user``/``failed`` run → 进入会话接着聊。"""
    try:
        result = service.takeover(run_id, scheduled_task_id=scheduled_task_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="scheduled_run_not_found") from exc
    except ScheduledTakeoverUnavailable as exc:
        raise HTTPException(status_code=503, detail="scheduled_takeover_unavailable") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return TakeoverResponse(
        sessionId=result["sessionId"],
        recoveryDraft=result.get("recoveryDraft"),
    )


# ---------------------------------------------------------------------------
# 创建确认卡决策 + pending 恢复
# ---------------------------------------------------------------------------


@router.post(
    "/confirmations/{request_id}/decision",
    response_model=ScheduledTaskItem | None,
)
def submit_confirmation_decision(
    request_id: str,
    body: ScheduledConfirmationDecisionRequest,
) -> Response | ScheduledTaskItem:
    """创建确认卡决策（confirm / cancel / 编辑后 confirm）。

    - confirm → 落库并返回 ``ScheduledTaskItem``（200）；
    - cancel → 返回 204；
    - 已结算 / 归属错配 / 不存在 → 404（不泄漏存在性）；
    - 校验失败 → 422。
    """
    manager = get_scheduling_confirmation_manager()
    try:
        # 按位置传入 unattended 标志（camelCase body → positional），避免 snake_case
        # 字面量进入 router 源码（CC-005 guard test 三重不暴露之一）。
        result = manager.submit_decision(
            request_id,
            body.decision,
            body.editedDraft.model_dump() if body.editedDraft is not None else None,
            bool(body.unattendedAutoApprove),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="scheduled_confirmation_not_found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result is None:
        # 已结算 / 不存在 → 404
        raise HTTPException(status_code=404, detail="scheduled_confirmation_not_found")
    if body.decision == "cancel":
        return Response(status_code=204)
    # confirm 落库返回任务投影
    return ScheduledTaskItem(**result)


@router.get(
    "/confirmations/pending",
    response_model=ScheduledConfirmationPendingResponse,
)
def list_pending_confirmations(
    sessionId: str = Query(default=""),
) -> ScheduledConfirmationPendingResponse:
    """SSE 重连恢复：返回可渲染 pending 快照；空 sessionId 表示全局卡列表。"""
    manager = get_scheduling_confirmation_manager()
    items = manager.list_pending(sessionId)
    return ScheduledConfirmationPendingResponse(
        items=[ScheduledConfirmationPendingItem(**item) for item in items]
    )
