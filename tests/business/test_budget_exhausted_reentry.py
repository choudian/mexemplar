"""Hitting the turn budget must reach the parent, not hang silently (1.2).

Before this, the chain dropped the reason at every hop:
AgentLoop returned PAUSED with only free text → _map_to_outcome defaulted to
waiting_system → _paused_reentry_payload recognised neither → parent got nothing.
"""

from __future__ import annotations

from src.business.agents.config import AgentResult, PauseReason, ResultType
from src.business.orchestration.agent.task_executor_adapter import TaskExecutorAdapter
from src.business.task_collaboration.dispatcher import _paused_reentry_payload
from src.business.task_collaboration.models import (
    SuspendReason,
    WaitingOn,
    waiting_on_for_reason,
)


def _map(result: dict) -> dict:
    return TaskExecutorAdapter._map_to_outcome(result)


def test_budget_pause_is_distinguishable_from_waiting_on_the_outside_world():
    # The parent can add turns for one and only wait for the other, so the two
    # must not collapse into the same reason.
    assert PauseReason.BUDGET_EXHAUSTED.value != PauseReason.EXTERNAL_UNAVAILABLE.value


def test_agent_result_carries_the_reason_and_the_turn_counts():
    result = AgentResult(
        result_type=ResultType.PAUSED,
        error="已达迭代上限（30 轮）",
        pause_reason=PauseReason.BUDGET_EXHAUSTED.value,
        iterations_used=30,
        max_iterations=30,
    )

    assert result.pause_reason == "budget_exhausted"
    assert result.iterations_used == 30
    assert result.max_iterations == 30


def test_budget_pause_maps_to_its_own_suspend_reason_not_waiting_system():
    outcome = _map(
        {
            "paused": True,
            "pause_reason": PauseReason.BUDGET_EXHAUSTED.value,
            "iterations_used": 30,
            "max_iterations": 30,
            "message": "子代理已暂停",
            "subagent_id": "ast_child",
        }
    )

    assert outcome["task_outcome"] == "suspended"
    assert outcome["suspend_reason"] == SuspendReason.BUDGET_EXHAUSTED.value
    assert outcome["reentry_type"] == "budget_exhausted"
    assert outcome["iterations_used"] == 30
    assert outcome["max_iterations"] == 30
    # 球在主助理手上：它能追加预算让这个活接着跑。
    assert waiting_on_for_reason(outcome["suspend_reason"]) is WaitingOn.ASSISTANT


def test_external_unavailable_pause_still_reads_as_waiting_system():
    outcome = _map(
        {
            "paused": True,
            "pause_reason": PauseReason.EXTERNAL_UNAVAILABLE.value,
            "message": "LLM 调用失败",
        }
    )

    assert outcome["suspend_reason"] == SuspendReason.WAITING_SYSTEM.value
    assert "reentry_type" not in outcome
    # waiting_system 的实际生产者是 ask_parent 和未知情形兜底，两者都该由主助理来
    # 处理。归到 SYSTEM 会让它进 recovery 自动重试，那是错的。
    assert waiting_on_for_reason(outcome["suspend_reason"]) is WaitingOn.ASSISTANT


def test_quota_pause_maps_to_user_without_waking_the_assistant():
    outcome = _map(
        {
            "paused": True,
            "pause_reason": PauseReason.QUOTA_EXHAUSTED.value,
            "message": "模型额度已用完，充值后可继续",
            "subagent_id": "ast_child",
        }
    )

    assert outcome["task_outcome"] == "suspended"
    assert outcome["suspend_reason"] == SuspendReason.QUOTA_EXHAUSTED.value
    assert waiting_on_for_reason(outcome["suspend_reason"]) is WaitingOn.USER
    assert _paused_reentry_payload(outcome, waiting_on=WaitingOn.USER.value) is None


def test_user_stop_keeps_priority_over_the_budget_reason():
    outcome = _map(
        {
            "paused": True,
            "cancelled": True,
            "pause_reason": PauseReason.BUDGET_EXHAUSTED.value,
            "message": "用户已停止",
        }
    )

    assert outcome["suspend_reason"] == SuspendReason.USER_STOP.value
    # 用户自己按的停，只有他能说继续——不叫主助理。
    assert waiting_on_for_reason(outcome["suspend_reason"]) is WaitingOn.USER


def test_a_more_specific_reentry_type_is_not_overwritten():
    # A pending question outranks the budget signal: answering it is what
    # actually unblocks the task.
    outcome = _map(
        {
            "paused": True,
            "pause_reason": PauseReason.BUDGET_EXHAUSTED.value,
            "reentry_type": "task_question",
            "question_id": "q_1",
            "question_kind": "clarification",
            "message": "等待答复",
        }
    )

    assert outcome["reentry_type"] == "task_question"
    assert outcome["suspend_reason"] != SuspendReason.BUDGET_EXHAUSTED.value


def test_dispatcher_emits_a_reentry_payload_so_the_parent_is_told():
    payload = _paused_reentry_payload(
        {
            "reentry_type": "budget_exhausted",
            "task_id": "tsk_1",
            "subagent_id": "ast_child",
            "iterations_used": 30,
            "max_iterations": 30,
        }
    )

    assert payload is not None
    assert payload["eventType"] == "budget_exhausted"
    assert payload["taskId"] == "tsk_1"
    assert payload["iterationsUsed"] == 30
    assert payload["maxIterations"] == 30
    assert payload["safeSummary"]


def test_unknown_pause_types_still_reach_the_parent():
    """认不出的暂停兜底通知主助理，绝不静默丢弃。

    这条原名 ``test_unknown_pause_types_still_yield_no_payload``，断言未知类型返回
    ``None``——那正是白名单设计本身：认不出就什么都不做。它和"撞预算暂停必须回流"
    不可能同时成立，因为 ``budget_exhausted`` 对旧白名单来说就是个未知类型。

    改成默认通知 + 显式排除后，"不通知父侧"成了需要写明理由的例外（等用户、等系统
    各有自己的路径），而不是默认行为。
    """
    payload = _paused_reentry_payload({"reentry_type": "something_else"})
    assert payload is not None
    assert payload["safeSummary"]

    # 输入不是 dict 属于调用错误，跟"认不出的暂停"是两回事，仍然返回 None
    assert _paused_reentry_payload(None) is None


def test_pauses_that_wait_on_someone_else_do_not_wake_the_assistant():
    """只有球在主助理手上才叫醒它。"""
    assert (
        _paused_reentry_payload(
            {"reentry_type": "budget_exhausted"}, waiting_on=WaitingOn.USER.value
        )
        is None
    )
    assert (
        _paused_reentry_payload(
            {"reentry_type": "budget_exhausted"}, waiting_on=WaitingOn.SYSTEM.value
        )
        is None
    )
