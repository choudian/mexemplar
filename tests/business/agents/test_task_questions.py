from __future__ import annotations

import json

import pytest

from src.business.agents.tools.assistant_tools import (
    create_answer_task_question_handler,
    create_ask_parent_handler,
)
from src.business.task_collaboration.questions import TaskQuestionService
from src.data.repos import AssistantTaskQuestionRepository, AssistantTaskRepository


def _graph_with_parent_scope(scope: list[str] | None = None) -> tuple[str, str]:
    task_repo = AssistantTaskRepository()
    root = task_repo.create_task(
        graph_id="tg_questions",
        session_id="ast_questions",
        task_id="tsk_parent",
        title="parent",
        description="parent",
        owner_session_id="ast_questions",
        assignee_type="specialist",
        assignee_id="sp_parent",
        capability_scope=json.dumps(scope or ["tool.read", "tool.write"]),
        status="running",
    )
    child = task_repo.create_task(
        graph_id=root.graph_id,
        session_id=root.session_id,
        task_id="tsk_child",
        root_task_id=root.task_id,
        parent_task_id=root.task_id,
        title="child",
        description="child",
        owner_session_id=root.session_id,
        assignee_type="specialist",
        assignee_id="sp_child",
        status="running",
    )
    task_repo.add_edge(
        graph_id=root.graph_id,
        source_task_id=root.task_id,
        target_task_id=child.task_id,
        edge_type="delegation",
        propagation="blocking",
    )
    return root.task_id, child.task_id


def test_expire_stale_questions_invalidates_user_pending_and_suspends_task() -> None:
    # FR-017：用户待答因超时/重启失效 → 问题标 expired，原任务 fail-closed 挂起为"等回话"
    from datetime import datetime, timedelta

    _, child_id = _graph_with_parent_scope()
    service = TaskQuestionService()
    question = service.ask_parent(
        task_id=child_id,
        asker_type="specialist",
        asker_id="sp_child",
        kind="clarification",
        question="目标是什么？",
        expires_at=datetime.now() - timedelta(seconds=1),
    )
    service.escalate_to_user(question.question_id, user_request_id="req_1")

    expired = service.expire_stale_questions(datetime.now())

    assert expired == 1
    refreshed = AssistantTaskQuestionRepository().get_by_id(question.question_id)
    assert refreshed.status == "expired"
    task = AssistantTaskRepository().get_task(child_id)
    assert task.status == "suspended"
    assert task.suspend_reason == "waiting_user"


def test_ask_parent_persists_agent_to_agent_question_route() -> None:
    _, child_id = _graph_with_parent_scope()

    question = TaskQuestionService().ask_parent(
        task_id=child_id,
        asker_type="specialist",
        asker_id="sp_child",
        kind="resource_request",
        question="Need the invoice folder.",
    )

    assert question.status == "escalated_to_parent"
    assert question.parent_task_id == "tsk_parent"
    assert question.recipient_type == "specialist"
    assert question.recipient_id == "sp_parent"
    assert question.question_text == "Need the invoice folder."
    edges = AssistantTaskRepository().list_graph_edges("tg_questions")
    assert any(
        edge.source_task_id == "tsk_parent"
        and edge.target_task_id == child_id
        and edge.edge_type == "resource_request"
        for edge in edges
    )


def test_ask_parent_rejects_non_assigned_executor() -> None:
    _, child_id = _graph_with_parent_scope()

    with pytest.raises(PermissionError):
        TaskQuestionService().ask_parent(
            task_id=child_id,
            asker_type="specialist",
            asker_id="sp_other",
            kind="clarification",
            question="Can I use this task id?",
        )


def test_capability_request_grant_must_be_parent_scope_subset() -> None:
    _, child_id = _graph_with_parent_scope(scope=["tool.read"])
    service = TaskQuestionService()

    question = service.ask_parent(
        task_id=child_id,
        asker_type="specialist",
        asker_id="sp_child",
        kind="capability_request",
        question="Need read access.",
        capability_delta=["tool.read"],
    )

    assert json.loads(question.capability_delta) == ["tool.read"]
    with pytest.raises(ValueError):
        service.ask_parent(
            task_id=child_id,
            asker_type="specialist",
            asker_id="sp_child",
            kind="capability_request",
            question="Need write access.",
            capability_delta=["tool.write"],
        )


def test_answer_question_applies_granted_capability_to_task_scope() -> None:
    _, child_id = _graph_with_parent_scope(scope=["tool.read", "tool.write"])
    service = TaskQuestionService()
    question = service.ask_parent(
        task_id=child_id,
        asker_type="specialist",
        asker_id="sp_child",
        kind="capability_request",
        question="Need write access.",
        capability_delta=["tool.write"],
    )

    answered = service.answer_question(
        question.question_id,
        safe_answer_summary="Granted write access.",
        capability_delta=["tool.write"],
    )

    task = AssistantTaskRepository().get_task(child_id)
    assert answered.status == "answered"
    assert json.loads(answered.capability_delta) == ["tool.write"]
    assert json.loads(task.capability_scope) == ["tool.write"]


def test_answer_question_resumes_waiting_system_task_for_redispatch() -> None:
    _, child_id = _graph_with_parent_scope()
    service = TaskQuestionService()
    question = service.ask_parent(
        task_id=child_id,
        asker_type="specialist",
        asker_id="sp_child",
        kind="clarification",
        question="Need parent input.",
    )
    AssistantTaskRepository().update_status(
        child_id,
        status="suspended",
        suspend_reason="waiting_system",
    )

    answered = service.answer_question(
        question.question_id,
        safe_answer_summary="Use the shorter path.",
    )

    task = AssistantTaskRepository().get_task(child_id)
    assert answered.status == "answered"
    assert task.status == "pending_dispatch"
    assert task.suspend_reason is None


def test_user_escalation_answer_resumes_without_persisting_raw_user_answer() -> None:
    _, child_id = _graph_with_parent_scope()
    service = TaskQuestionService()
    question = service.ask_parent(
        task_id=child_id,
        asker_type="specialist",
        asker_id="sp_child",
        kind="clarification",
        question="Should this be sorted by date?",
    )

    escalated = service.escalate_to_user(
        question.question_id,
        user_request_id="clr_process_local",
    )
    escalated_status = escalated.status
    answered = service.answer_question(
        question.question_id,
        safe_answer_summary="User chose date order.",
        raw_user_answer="Sort by date using the private folder path.",
    )

    stored = AssistantTaskQuestionRepository().list_open_for_task(child_id)
    task = AssistantTaskRepository().get_task(child_id)
    assert escalated_status == "escalated_to_user"
    assert task.status == "pending_dispatch"
    assert task.suspend_reason is None
    assert answered.status == "answered"
    assert answered.safe_answer_summary == "User chose date order."
    assert "private folder" not in str(answered.__dict__)
    assert stored == []


def test_answer_question_persists_after_session_close() -> None:
    # C1 回归：answer_question 必须在自有事务里提交。共享 session 下 Repository._commit
    # 只 flush，真正落库靠 service 的 _atomic 出口；缺 _atomic 时答复只 flush 不 commit，
    # session 关闭即回滚，造成"已发 answered 事件但 DB 仍是 escalated_to_user"的静默丢失。
    # 注意：:memory:+StaticPool 共享连接会让未提交 flush 对 fresh session 可见而掩盖此 bug，
    # 故必须先 close 触发回滚，再用新 session 读回，才能穿透假象验证提交边界。
    _, child_id = _graph_with_parent_scope()
    service = TaskQuestionService()
    question = service.ask_parent(
        task_id=child_id,
        asker_type="specialist",
        asker_id="sp_child",
        kind="clarification",
        question="Sort by date?",
    )
    service.escalate_to_user(question.question_id, user_request_id="req_close")
    service.answer_question(
        question.question_id,
        safe_answer_summary="Yes, by date.",
    )
    service.close()

    persisted = AssistantTaskQuestionRepository().get_by_id(question.question_id)
    assert persisted is not None
    assert persisted.status == "answered"
    assert persisted.safe_answer_summary == "Yes, by date."
    assert persisted.resolved_at is not None


def test_ask_parent_tool_handler_returns_persisted_route_json() -> None:
    _, child_id = _graph_with_parent_scope()
    handler = create_ask_parent_handler(executor_type="specialist", executor_id="sp_child")

    result = json.loads(
        handler(
            taskId=child_id,
            question="Need access.",
            kind="capability_request",
            capabilityDelta=["tool.read"],
        )
    )

    assert result["success"] is True
    assert result["taskId"] == child_id
    assert result["status"] == "escalated_to_parent"


def test_bound_ask_parent_handler_uses_current_task_without_model_task_id() -> None:
    _, child_id = _graph_with_parent_scope()
    handler = create_ask_parent_handler(
        executor_type="specialist",
        executor_id="sp_child",
        bound_task_id=child_id,
    )

    result = json.loads(handler(question="Need parent input.", kind="clarification"))

    assert result["success"] is True
    assert result["taskId"] == child_id
    assert result["status"] == "escalated_to_parent"


def test_answer_task_question_handler_answers_and_requests_redispatch() -> None:
    _, child_id = _graph_with_parent_scope()
    service = TaskQuestionService()
    question = service.ask_parent(
        task_id=child_id,
        asker_type="specialist",
        asker_id="sp_child",
        kind="clarification",
        question="Need parent input.",
    )
    AssistantTaskRepository().update_status(
        child_id,
        status="suspended",
        suspend_reason="waiting_system",
    )
    redispatches: list[str] = []
    handler = create_answer_task_question_handler(
        redispatch_callback=lambda task_id: redispatches.append(task_id) or True
    )

    result = json.loads(
        handler(
            questionId=question.question_id,
            safeAnswerSummary="Use the shorter path.",
        )
    )

    assert result["success"] is True
    assert result["status"] == "answered"
    assert result["redispatched"] is True
    assert redispatches == [child_id]
