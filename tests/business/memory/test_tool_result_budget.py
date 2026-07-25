"""Parallel tool results share one budget per turn (1.4)."""

from __future__ import annotations

import json

from src.business.memory.tool_result_budget import (
    ToolResultBudget,
    ToolResultGroup,
    group_tool_results,
    select_to_trim,
)
from src.data.models_sqlite import Message


class _FakeRepo:
    def __init__(self):
        self.created: list[Message] = []
        self.updated: dict[str, str] = {}

    def create(self, message):
        self.created.append(message)
        return message

    def update_content(self, message_id, content):
        self.updated[message_id] = content


class _BrokenRepo(_FakeRepo):
    def create(self, message):
        raise RuntimeError("disk full")


def _assistant(seq, call_ids):
    return Message(
        message_id=f"msg_{seq}",
        session_id="sess",
        sequence=seq,
        role="assistant",
        content="",
        tool_calls=json.dumps([{"id": cid, "name": "read_file", "args": {}} for cid in call_ids]),
    )


def _result(seq, call_id, size, tool_name="read_file"):
    return Message(
        message_id=f"msg_{seq}",
        session_id="sess",
        sequence=seq,
        role="tool",
        content="x" * size,
        tool_call_id=call_id,
        tool_name=tool_name,
    )


# --- 分组 --------------------------------------------------------------------


def test_results_are_grouped_by_the_turn_that_requested_them():
    messages = [
        _assistant(1, ["a", "b"]),
        _result(2, "a", 10),
        _result(3, "b", 20),
        _assistant(4, ["c", "d"]),
        _result(5, "c", 30),
        _result(6, "d", 40),
    ]

    groups = group_tool_results(messages)

    assert [g.total_chars for g in groups] == [30, 70]


def test_single_result_turns_are_not_groups():
    # A lone result is already bounded by the per-result cap.
    messages = [_assistant(1, ["a"]), _result(2, "a", 50_000)]

    assert group_tool_results(messages) == []


def test_unrelated_messages_close_the_group():
    messages = [
        _assistant(1, ["a", "b"]),
        _result(2, "a", 10),
        Message(
            message_id="msg_3", session_id="sess", sequence=3, role="user", content="hi"
        ),
        _result(4, "b", 20),
    ]

    assert group_tool_results(messages) == []


def test_malformed_tool_calls_json_yields_no_group():
    broken = Message(
        message_id="msg_1",
        session_id="sess",
        sequence=1,
        role="assistant",
        content="",
        tool_calls="{not json",
    )

    assert group_tool_results([broken, _result(2, "a", 10)]) == []


# --- 选择策略 ----------------------------------------------------------------


def test_the_largest_result_is_trimmed_first():
    # 500 / 30000 / 800 / 600: trimming the last leaves the group still over
    # budget; trimming the largest alone brings it under and spares the rest.
    group = ToolResultGroup(
        [
            _result(2, "a", 500),
            _result(3, "b", 30_000),
            _result(4, "c", 800),
            _result(5, "d", 600),
        ]
    )

    selected = select_to_trim(group, limit=24_000)

    assert [m.message_id for m in selected] == ["msg_3"]


def test_trimming_continues_until_the_group_fits():
    group = ToolResultGroup(
        [_result(2, "a", 20_000), _result(3, "b", 20_000), _result(4, "c", 20_000)]
    )

    selected = select_to_trim(group, limit=24_000)

    assert len(selected) == 2


def test_nothing_selected_when_the_group_already_fits():
    group = ToolResultGroup([_result(2, "a", 100), _result(3, "b", 200)])

    assert select_to_trim(group, limit=24_000) == []


def test_recovery_tool_results_are_never_selected():
    group = ToolResultGroup(
        [
            _result(2, "a", 30_000, tool_name="load_reference"),
            _result(3, "b", 1_000),
        ]
    )

    selected = select_to_trim(group, limit=500)

    assert [m.message_id for m in selected] == ["msg_3"]


def test_overage_is_accepted_when_only_protected_results_remain():
    # Better to run over budget than to take back content the model asked for.
    group = ToolResultGroup(
        [
            _result(2, "a", 30_000, tool_name="load_reference"),
            _result(3, "b", 30_000, tool_name="load_tool_output"),
        ]
    )

    assert select_to_trim(group, limit=1_000) == []


# --- 应用 --------------------------------------------------------------------


def test_trimmed_result_keeps_its_pairing_and_stays_recoverable():
    budget = ToolResultBudget(limit=1_000)
    repo = _FakeRepo()
    messages = [_assistant(1, ["a", "b"]), _result(2, "a", 5_000), _result(3, "b", 100)]

    freed = budget.apply("sess", messages, repo)

    assert freed > 0
    archived = repo.created[0]
    assert archived.is_archived is True
    assert archived.content == "x" * 5_000
    assert messages[1].tool_call_id == "a"
    assert f"[REF::{archived.message_id}]" in repo.updated["msg_2"]
    assert "load_reference" in repo.updated["msg_2"]
    # The small sibling is untouched.
    assert "msg_3" not in repo.updated


def test_preview_keeps_the_head_of_the_original():
    budget = ToolResultBudget(limit=100)
    repo = _FakeRepo()
    messages = [_assistant(1, ["a", "b"]), _result(2, "a", 5_000), _result(3, "b", 10)]

    budget.apply("sess", messages, repo)

    assert repo.updated["msg_2"].startswith("x" * 100)


def test_applying_twice_is_a_no_op_the_second_time():
    budget = ToolResultBudget(limit=1_000)
    repo = _FakeRepo()
    messages = [_assistant(1, ["a", "b"]), _result(2, "a", 5_000), _result(3, "b", 100)]

    first = budget.apply("sess", messages, repo)
    second = budget.apply("sess", messages, repo)

    assert first > 0
    assert second == 0
    assert len(repo.created) == 1


def test_groups_under_budget_are_left_completely_alone():
    budget = ToolResultBudget(limit=24_000)
    repo = _FakeRepo()
    messages = [_assistant(1, ["a", "b"]), _result(2, "a", 100), _result(3, "b", 200)]

    assert budget.apply("sess", messages, repo) == 0
    assert repo.created == []


def test_one_failed_trim_does_not_abort_the_rest():
    budget = ToolResultBudget(limit=1_000)
    repo = _BrokenRepo()
    messages = [_assistant(1, ["a", "b"]), _result(2, "a", 5_000), _result(3, "b", 100)]

    assert budget.apply("sess", messages, repo) == 0
    assert messages[1].content == "x" * 5_000


def test_absurdly_small_budgets_fall_back_to_the_default():
    """A budget below one result's own cap can only shred every result.

    Hit twice during development: a mock config that does not stub the getter
    yields `int(MagicMock()) == 1`, silently setting the budget to one
    character. Production code refuses the value rather than trusting it.
    """
    from unittest.mock import MagicMock

    from src.business.memory.context_manager import (
        _DEFAULT_TOOL_RESULT_GROUP_BUDGET,
        _MIN_SANE_TOOL_RESULT_GROUP_BUDGET,
        _positive_int,
    )

    for bad in (MagicMock(), 1, 0, -5, None, "abc"):
        resolved = _positive_int(
            bad,
            default=_DEFAULT_TOOL_RESULT_GROUP_BUDGET,
            minimum=_MIN_SANE_TOOL_RESULT_GROUP_BUDGET,
        )
        assert resolved == _DEFAULT_TOOL_RESULT_GROUP_BUDGET, bad

    # A deliberate, plausible value is still honoured.
    assert (
        _positive_int(
            5000,
            default=_DEFAULT_TOOL_RESULT_GROUP_BUDGET,
            minimum=_MIN_SANE_TOOL_RESULT_GROUP_BUDGET,
        )
        == 5000
    )
