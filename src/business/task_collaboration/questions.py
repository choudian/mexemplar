"""Business service for persisted task question and resource request routes."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Iterable

from src.business.task_collaboration.events import emit_question_changed, emit_task_updated
from src.business.task_collaboration.models import (
    TERMINAL_TASK_STATUSES,
    SuspendReason,
    TaskQuestionKind,
    TaskQuestionStatus,
    TaskStatus,
    safe_preview,
    validate_task_transition,
)
from src.business.task_collaboration.unit_of_work import AtomicTaskService
from src.data.repos import AssistantTaskQuestionRepository, AssistantTaskRepository


class TaskQuestionService(AtomicTaskService):
    def __init__(
        self,
        task_repo: AssistantTaskRepository | None = None,
        question_repo: AssistantTaskQuestionRepository | None = None,
    ) -> None:
        self._init_repos(
            tasks=(AssistantTaskRepository, task_repo),
            questions=(AssistantTaskQuestionRepository, question_repo),
        )

    def ask_parent(
        self,
        *,
        task_id: str,
        asker_type: str,
        asker_id: str,
        kind: str,
        question: str,
        capability_delta: Iterable[str] | None = None,
        expires_at: datetime | None = None,
    ):
        task = self._tasks.get_task(task_id)
        if task is None:
            raise LookupError("task not found")
        _assert_asker_owns_task(task, asker_type, asker_id)
        question_kind = TaskQuestionKind(kind)
        parent = self._tasks.get_task(task.parent_task_id) if task.parent_task_id else None
        recipient_type = parent.assignee_type if parent is not None else None
        recipient_id = parent.assignee_id if parent is not None else None
        encoded_delta = None
        if question_kind == TaskQuestionKind.CAPABILITY_REQUEST:
            requested = _normalized_scope(capability_delta)
            self._assert_parent_scope_subset(parent, requested)
            encoded_delta = json.dumps(sorted(requested), ensure_ascii=False)
        elif capability_delta:
            encoded_delta = json.dumps(
                sorted(_normalized_scope(capability_delta)), ensure_ascii=False
            )

        # create + update 必须同一事务：否则 create 成功但 update 失败时，
        # question 停在 "open" 状态，下游不会处理它。
        with self._atomic():
            row = self._questions.create_question(
                graph_id=task.graph_id,
                task_id=task.task_id,
                parent_task_id=task.parent_task_id,
                asker_type=asker_type,
                asker_id=asker_id,
                recipient_type=recipient_type,
                recipient_id=recipient_id,
                kind=question_kind.value,
                question_text=safe_preview(question, max_chars=500),
                capability_delta=encoded_delta,
                expires_at=expires_at,
            )
            row = self._questions.update_status(row.question_id, TaskQuestionStatus.ESCALATED_TO_PARENT)
            if parent is not None:
                self._tasks.add_edge(
                    graph_id=task.graph_id,
                    source_task_id=parent.task_id,
                    target_task_id=task.task_id,
                    edge_type=_edge_type_for_question(question_kind),
                    propagation="message_only",
                )
        emit_question_changed(
            self,
            session_id=task.session_id,
            graph_id=task.graph_id,
            task_id=task.task_id,
            question_id=row.question_id,
            kind=row.kind,
            status=row.status,
            change_type="created",
        )
        return row

    def escalate_to_user(self, question_id: str, *, user_request_id: str):
        # update question + suspend task 必须同一事务：否则 question 已标记
        # escalated_to_user 但 task 仍在运行，用户看不到澄清卡。
        with self._atomic():
            question = self._questions.update_status(
                question_id,
                TaskQuestionStatus.ESCALATED_TO_USER,
                escalated_to_user=True,
                user_request_id=user_request_id,
            )
            if question is None:
                raise LookupError("question not found")
            current_task = self._tasks.get_task(question.task_id)
            if current_task is not None:
                validate_task_transition(
                    current_task.status,
                    TaskStatus.SUSPENDED,
                    suspend_reason=SuspendReason.WAITING_USER,
                )
            task = self._tasks.update_status(
                question.task_id,
                status=TaskStatus.SUSPENDED,
                suspend_reason=SuspendReason.WAITING_USER,
            )
        if task is not None:
            emit_task_updated(self, task)
        emit_question_changed(
            self,
            session_id=task.session_id if task else "",
            graph_id=question.graph_id,
            task_id=question.task_id,
            question_id=question.question_id,
            kind=question.kind,
            status=question.status,
            change_type="escalated_to_user",
        )
        return question

    def answer_question(
        self,
        question_id: str,
        *,
        safe_answer_summary: str,
        raw_user_answer: str | None = None,
        capability_delta: Iterable[str] | None = None,
    ):
        question = self._questions.get_by_id(question_id)
        if question is None:
            raise LookupError("question not found")
        task = self._tasks.get_task(question.task_id)
        encoded_delta = None
        if capability_delta is not None:
            parent = (
                self._tasks.get_task(task.parent_task_id) if task and task.parent_task_id else None
            )
            requested = _normalized_scope(capability_delta)
            self._assert_parent_scope_subset(parent, requested)
            encoded_delta = json.dumps(sorted(requested), ensure_ascii=False)
            merged_task_scope = json.dumps(
                sorted(_scope_from_json(getattr(task, "capability_scope", None)) | requested),
                ensure_ascii=False,
            )
        else:
            merged_task_scope = None
        resumed_task = None
        # answer 落库必须在自有事务里提交：共享 session 下 update_status 只 flush，
        # 缺 _atomic 出口会随 session 关闭回滚，造成"已发 answered 事件但 DB 仍是
        # escalated_to_user"的静默丢失。与 ask_parent / escalate_to_user 一致。
        # FR-017：raw_user_answer 从不入库（面向用户的答案不得持久化，见
        # test_user_escalation_answer_resumes_without_persisting_raw_user_answer）；
        # safe_answer_summary 是经 safe_preview 脱敏的审计投影，仅记录"已这样回答"，
        # 不用于复用执行或副作用，失效答案由 expire_stale_questions fail-closed 挂起等回话。
        with self._atomic():
            answered = self._questions.update_status(
                question_id,
                TaskQuestionStatus.ANSWERED,
                safe_answer_summary=safe_preview(safe_answer_summary, max_chars=500),
                capability_delta=encoded_delta,
            )
            if merged_task_scope is not None and task is not None:
                self._tasks.update_capability_scope(task.task_id, merged_task_scope)
            resume_reasons = {SuspendReason.WAITING_SYSTEM}
            if question.escalated_to_user or question.status == TaskQuestionStatus.ESCALATED_TO_USER:
                resume_reasons.add(SuspendReason.WAITING_USER)
            if (
                task is not None
                and task.status == TaskStatus.SUSPENDED
                and task.suspend_reason in resume_reasons
            ):
                validate_task_transition(task.status, TaskStatus.PENDING_DISPATCH)
                resumed_task = self._tasks.update_status(
                    task.task_id,
                    status=TaskStatus.PENDING_DISPATCH,
                )
        if resumed_task is not None:
            emit_task_updated(self, resumed_task)
        emit_question_changed(
            self,
            session_id=task.session_id if task else "",
            graph_id=question.graph_id,
            task_id=question.task_id,
            question_id=question.question_id,
            kind=question.kind,
            status="answered",
            change_type="answered",
        )
        return answered

    def expire_stale_questions(self, now: datetime) -> int:
        """回收过期未决问题（FR-017 重启/超时恢复）。

        面向用户的待答（escalated_to_user）在超时/重启后失效：标记问题为 expired，并把原任务
        fail-closed 挂起为"等回话"（waiting_user），等用户下次可交互时重新发起澄清——绝不复用
        失效答案、绝不猜答案继续副作用。agent↔agent 的过期问题一并标记 expired 做清理。
        """
        count = 0
        updated_tasks: list = []
        for question in self._questions.scan_expired(now):
            # 每个 question 的 expire + task suspend 必须同一事务
            with self._atomic():
                updated = self._questions.update_status(question.question_id, TaskQuestionStatus.EXPIRED)
                if updated is None:
                    continue
                if question.escalated_to_user or question.status == TaskQuestionStatus.ESCALATED_TO_USER:
                    task = self._tasks.get_task(question.task_id)
                    if task is not None and task.status not in TERMINAL_TASK_STATUSES:
                        validate_task_transition(
                            task.status,
                            TaskStatus.SUSPENDED,
                            suspend_reason=SuspendReason.WAITING_USER,
                        )
                        suspended = self._tasks.update_status(
                            question.task_id,
                            status=TaskStatus.SUSPENDED,
                            suspend_reason=SuspendReason.WAITING_USER,
                        )
                        if suspended is not None:
                            updated_tasks.append(suspended)
            count += 1
        for suspended in updated_tasks:
            emit_task_updated(self, suspended)
        return count

    @staticmethod
    def _assert_parent_scope_subset(parent, requested: set[str]) -> None:
        parent_scope = _scope_from_json(getattr(parent, "capability_scope", None))
        if not requested.issubset(parent_scope):
            raise ValueError("capability request exceeds parent task capability scope")


def _normalized_scope(values: Iterable[str] | None) -> set[str]:
    return {str(value).strip() for value in values or [] if str(value).strip()}


def _assert_asker_owns_task(task, asker_type: str, asker_id: str) -> None:
    """Only the task's assigned executor can open parent/resource routes.

    Ephemeral tasks currently store the type placeholder as assignee_id while
    the runtime handler identity uses the child session id. Binding handlers to
    the current task id prevents model-supplied cross-task ids; this guard still
    rejects wrong executor types and specialist id mismatches.
    """
    if task.assignee_type != asker_type:
        raise PermissionError("ask_parent requires the assigned executor")
    if task.assignee_id == asker_id:
        return
    if task.assignee_type == "ephemeral_subagent" and task.assignee_id == "ephemeral_subagent":
        return
    raise PermissionError("ask_parent requires the assigned executor")


def _edge_type_for_question(kind: TaskQuestionKind) -> str:
    if kind in {TaskQuestionKind.RESOURCE_REQUEST, TaskQuestionKind.CAPABILITY_REQUEST}:
        return "resource_request"
    return "question"


def _scope_from_json(value: str | None) -> set[str]:
    if not value:
        return set()
    try:
        loaded = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return set()
    if not isinstance(loaded, list):
        return set()
    return _normalized_scope(str(item) for item in loaded)
