from src.business.self_improvement.execution_review_trigger import compute_priority, should_review


def test_switch_off_blocks_everything():
    assert should_review(
        enabled=False,
        delegated=True,
        tool_executed=True,
        session_count_today=0,
        max_per_session=3,
    ) is False


def test_pure_chat_not_reviewed():
    assert should_review(
        enabled=True,
        delegated=False,
        tool_executed=False,
        session_count_today=0,
        max_per_session=3,
    ) is False


def test_real_work_reviewed():
    assert should_review(
        enabled=True,
        delegated=True,
        tool_executed=False,
        session_count_today=0,
        max_per_session=3,
    ) is True


def test_rate_limit_blocks():
    assert should_review(
        enabled=True,
        delegated=True,
        tool_executed=True,
        session_count_today=3,
        max_per_session=3,
    ) is False


def test_priority_prefers_failed_and_high_iter():
    assert compute_priority(failed=True, iterations=10, tool_calls=8) > compute_priority(
        failed=False,
        iterations=2,
        tool_calls=1,
    )
