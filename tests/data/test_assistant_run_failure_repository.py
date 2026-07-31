from __future__ import annotations

import re

from src.business.agents.config import AgentType
from src.business.services.assistant_failure_classifier import KNOWN_FAILURE_CATEGORIES
from src.business.services.assistant_failure_service import AssistantFailureService
from src.data.models_sqlite import AssistantRunFailure, Message, Session
from src.data.repos import (
    AssistantRunFailureRepository,
    MessageRepository,
    SessionRepository,
)


def test_every_classifier_category_is_accepted_by_the_database() -> None:
    """分类器每加一个 category，这张表的 CHECK 约束必须同步。

    漏了会怎样：分类器算出一个新 category → 落库撞 CHECK → 抛 IntegrityError
    → **"记录失败"这件事本身失败**。而这恰好是最坏的一类故障：出了事，连
    "出过事"都记不下来。

    这个守卫是静态的（读 ORM 上的约束定义），所以加了新 category 却忘了迁移时
    会当场红，不用等到线上真撞。
    """
    constraint = next(
        c
        for c in AssistantRunFailure.__table__.constraints
        if getattr(c, "name", None) == "ck_assistant_run_failures_category"
    )
    allowed = set(re.findall(r"'([a-z_]+)'", str(constraint.sqltext)))

    missing = KNOWN_FAILURE_CATEGORIES - allowed
    assert not missing, f"分类器会产出这些 category，但 DB 约束不认：{sorted(missing)}"


def _seed_session() -> str:
    session_id = "ast_failure_repo"
    SessionRepository().create(
        Session(
            session_id=session_id,
            workflow_id=None,
            agent_type=AgentType.ASSISTANT,
            status="active",
        )
    )
    MessageRepository().create(
        Message(
            message_id="msg_failure_repo",
            session_id=session_id,
            sequence=1,
            role="user",
            content="original",
        )
    )
    return session_id


def test_failure_repository_state_machine_and_message_migration() -> None:
    session_id = _seed_session()
    service = AssistantFailureService()
    summary = service.record_terminal_failure(
        session_id=session_id,
        message_sequence=1,
        error="timeout while calling provider",
    )

    assert summary.category == "network"
    assert summary.attempt_count == 1

    preparation = service.prepare_retry(session_id, 1, "edited")
    current = AssistantRunFailureRepository().get_current(session_id)
    assert current is not None
    assert current.status == "retrying"
    assert current.attempt_count == 2

    service.record_terminal_failure(
        session_id=session_id,
        message_sequence=2,
        error="server error",
        source_failure_id=preparation.failure_id,
    )
    moved = AssistantRunFailureRepository().get_current(session_id)
    assert moved is not None
    assert moved.message_sequence == 2
    assert moved.status == "failed"
    assert moved.attempt_count == 2

    service.resolve(moved.failure_id)
    assert AssistantRunFailureRepository().get_current(session_id) is None


def test_duplicate_retry_claim_is_rejected_and_startup_recovers_retrying() -> None:
    session_id = _seed_session()
    service = AssistantFailureService()
    service.record_terminal_failure(
        session_id=session_id,
        message_sequence=1,
        error="quota exceeded",
    )

    first = AssistantRunFailureRepository().claim_retry(session_id, 1)
    second = AssistantRunFailureRepository().claim_retry(session_id, 1)

    assert first is not None
    assert second is None
    assert AssistantRunFailureRepository().recover_interrupted_retries() == 1
    recovered = AssistantRunFailureRepository().get_current(session_id)
    assert recovered is not None
    assert recovered.status == "failed"
    assert recovered.attempt_count == 2
