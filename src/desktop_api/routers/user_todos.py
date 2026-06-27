from __future__ import annotations

from collections.abc import Iterator
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from src.business.user_todos import UserTodoService
from src.desktop_api.schemas import (
    UserTodoCompleteRequest,
    UserTodoCreateRequest,
    UserTodoItem,
    UserTodoListResponse,
    UserTodoUpdateRequest,
)

router = APIRouter(prefix="/api/user-todos", tags=["user-todos"])


def get_user_todo_service() -> Iterator[UserTodoService]:
    with UserTodoService() as service:
        yield service


@router.get("", response_model=UserTodoListResponse)
def list_user_todos(
    status: Literal["all", "open", "done", "pending", "in_progress"] = Query(default="all"),
    sort: Literal["created_desc", "created_asc", "priority_desc", "priority_asc"] = Query(
        default="created_desc"
    ),
    query: str = Query(default="", max_length=200),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    service: UserTodoService = Depends(get_user_todo_service),
) -> UserTodoListResponse:
    try:
        items, total = service.list_todos(
            status_filter=status,
            sort=sort,
            query=query,
            limit=limit,
            offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return UserTodoListResponse(
        items=[UserTodoItem(**item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=UserTodoItem)
def create_user_todo(
    body: UserTodoCreateRequest,
    service: UserTodoService = Depends(get_user_todo_service),
) -> UserTodoItem:
    try:
        return UserTodoItem(
            **service.create(
                title=body.title,
                description=body.description,
                priority=body.priority,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put("/{todo_id}", response_model=UserTodoItem)
def update_user_todo(
    todo_id: str,
    body: UserTodoUpdateRequest,
    service: UserTodoService = Depends(get_user_todo_service),
) -> UserTodoItem:
    try:
        return UserTodoItem(**service.update(todo_id, body.model_dump(exclude_unset=True)))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="User Todo not found.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/{todo_id}/complete", response_model=UserTodoItem)
def complete_user_todo(
    todo_id: str,
    body: UserTodoCompleteRequest,
    service: UserTodoService = Depends(get_user_todo_service),
) -> UserTodoItem:
    try:
        return UserTodoItem(**service.complete(todo_id, done=body.done))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="User Todo not found.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/{todo_id}", status_code=204)
def delete_user_todo(
    todo_id: str,
    service: UserTodoService = Depends(get_user_todo_service),
) -> Response:
    try:
        service.delete(todo_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="User Todo not found.") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return Response(status_code=204)
