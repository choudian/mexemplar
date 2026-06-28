"""Deterministic gate and enqueue logic for execution reviews."""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


def should_review(
    *,
    enabled: bool,
    delegated: bool,
    tool_executed: bool,
    session_count_today: int,
    max_per_session: int,
) -> bool:
    if not enabled:
        return False
    if not (delegated or tool_executed):
        return False
    if session_count_today >= max_per_session:
        return False
    return True


def compute_priority(*, failed: bool, iterations: int, tool_calls: int) -> int:
    return (100 if failed else 0) + min(max(iterations, 0), 50) + min(max(tool_calls, 0), 50)


def on_turn_completed(
    session_id: str,
    *,
    delegated: bool,
    tool_executed: bool,
    failed: bool,
    iterations: int,
    tool_calls: int,
    repo,
    config,
) -> Optional[str]:
    enabled = config.get_self_improvement_execution_review_enabled()
    max_per_session = config.get_self_improvement_execution_review_max_per_session()
    if not should_review(
        enabled=enabled,
        delegated=delegated,
        tool_executed=tool_executed,
        session_count_today=repo.count_session_today(session_id),
        max_per_session=max_per_session,
    ):
        return None
    return repo.enqueue(
        session_id,
        priority=compute_priority(
            failed=failed,
            iterations=iterations,
            tool_calls=tool_calls,
        ),
    )


def enqueue_from_session(session_id: str, *, failed: bool = False) -> Optional[str]:
    """Build current session skeleton and enqueue when deterministic gates pass."""
    if not session_id:
        return None
    from src.business.self_improvement.execution_trace_builder import build_skeleton
    from src.data.repos.execution_review_repository import ExecutionReviewRepository
    from src.data.repos.message_repository import MessageRepository
    from src.data.unified_config import get_unified_config

    with ExecutionReviewRepository() as repo, MessageRepository() as message_repo:
        skeleton = build_skeleton(session_id, message_repo)
        return on_turn_completed(
            session_id,
            delegated=bool(skeleton.get("delegated")),
            tool_executed=bool(skeleton.get("steps")),
            failed=failed,
            iterations=int(skeleton.get("iterations") or 0),
            tool_calls=len(skeleton.get("steps") or []),
            repo=repo,
            config=get_unified_config(),
        )


def register() -> None:
    from src.utils.events import agent_needs_user_input

    agent_needs_user_input.connect(_handle_turn_completed, weak=False)


def _handle_turn_completed(sender, **payload) -> None:
    try:
        session_id = str(payload.get("session_id") or "")
        enqueue_from_session(session_id, failed=False)
    except Exception:
        logger.warning("Execution review trigger failed", exc_info=True)
