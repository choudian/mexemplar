from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.data.models_sqlite import Base, WorkflowTransition
from src.data.repos.workflow_transition_repository import WorkflowTransitionRepository


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _add(session, *, idx: int, event_type: str) -> None:
    # 用递增 created_at 控制"最近窗口"的判定顺序。
    session.add(
        WorkflowTransition(
            transition_id=f"tr_{idx}",
            workflow_id="wf_1",
            event_type=event_type,
            created_at=datetime(2026, 6, 21) + timedelta(seconds=idx),
        )
    )


def test_has_recent_event_types_detects_match(db_session) -> None:
    _add(db_session, idx=1, event_type="assistant_delegation_started")
    db_session.flush()
    repo = WorkflowTransitionRepository(db_session)

    assert repo.has_recent_event_types({"assistant_delegation_started"}) is True


def test_has_recent_event_types_returns_false_without_match(db_session) -> None:
    _add(db_session, idx=1, event_type="something_else")
    db_session.flush()
    repo = WorkflowTransitionRepository(db_session)

    assert repo.has_recent_event_types({"assistant_delegation_started"}) is False


def test_has_recent_event_types_only_scans_recent_window(db_session) -> None:
    # 最旧的一条才是 legacy 事件；更近的两条都不是。
    _add(db_session, idx=1, event_type="assistant_delegation_started")
    _add(db_session, idx=2, event_type="noise_a")
    _add(db_session, idx=3, event_type="noise_b")
    db_session.flush()
    repo = WorkflowTransitionRepository(db_session)

    # 窗口只覆盖最近两条 → 看不到最旧的 legacy 事件。
    assert repo.has_recent_event_types({"assistant_delegation_started"}, window=2) is False
    # 窗口放大到三条 → 命中。
    assert repo.has_recent_event_types({"assistant_delegation_started"}, window=3) is True


def test_has_recent_event_types_empty_set_is_false(db_session) -> None:
    _add(db_session, idx=1, event_type="assistant_delegation_started")
    db_session.flush()
    repo = WorkflowTransitionRepository(db_session)

    assert repo.has_recent_event_types(frozenset()) is False
