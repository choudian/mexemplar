"""Reference replacement runs inside compression, once, and cannot loop (1.3e).

The old `reference_handler` did the same substitution on *every* context
assembly. Being stateless, it re-archived whatever the model had just recovered,
so the model kept loading the same reference forever. Moving the step into the
compression pipeline makes it a one-shot persisted change instead.
"""

from __future__ import annotations

from src.business.memory.compression_handler import CompressionHandler, TokenTrigger
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


def _msg(seq, role, content="", **kwargs):
    return Message(
        message_id=f"msg_{seq}",
        session_id="sess",
        sequence=seq,
        role=role,
        content=content,
        **kwargs,
    )


def _handler(size_threshold=100):
    handler = object.__new__(CompressionHandler)
    handler.keep_recent = 2
    handler.size_threshold = size_threshold
    handler._trigger = TokenTrigger(10**9)
    return handler


def test_large_tool_result_becomes_a_pointer_and_the_original_is_archived():
    handler = _handler()
    repo = _FakeRepo()
    big = _msg(5, "tool", "x" * 500, tool_call_id="call_1", tool_name="read_file")

    freed = handler._replace_large_tool_results("sess", [big], repo)

    assert freed > 0
    assert len(repo.created) == 1
    archived = repo.created[0]
    assert archived.is_archived is True
    assert archived.content == "x" * 500
    # Pairing must survive: the visible message keeps its tool_call_id.
    assert big.tool_call_id == "call_1"
    assert f"[REF::{archived.message_id}]" in repo.updated["msg_5"]
    assert "load_reference" in repo.updated["msg_5"]


def test_load_reference_results_are_never_replaced():
    # Otherwise: replace -> model recovers -> replaced again -> loops.
    handler = _handler()
    repo = _FakeRepo()
    recovered = _msg(
        5, "tool", "x" * 500, tool_call_id="call_1", tool_name="load_reference"
    )

    freed = handler._replace_large_tool_results("sess", [recovered], repo)

    assert freed == 0
    assert repo.created == []
    assert repo.updated == {}


def test_load_tool_output_results_are_also_protected():
    handler = _handler()
    repo = _FakeRepo()
    recovered = _msg(
        5, "tool", "x" * 500, tool_call_id="call_1", tool_name="load_tool_output"
    )

    assert handler._replace_large_tool_results("sess", [recovered], repo) == 0


def test_small_results_are_left_alone():
    handler = _handler(size_threshold=1000)
    repo = _FakeRepo()
    small = _msg(5, "tool", "x" * 50, tool_call_id="call_1", tool_name="read_file")

    assert handler._replace_large_tool_results("sess", [small], repo) == 0
    assert small.content == "x" * 50


def test_non_tool_messages_are_left_alone():
    handler = _handler()
    repo = _FakeRepo()
    assistant = _msg(5, "assistant", "y" * 500)

    assert handler._replace_large_tool_results("sess", [assistant], repo) == 0


def test_replacing_the_same_message_twice_is_a_no_op_the_second_time():
    # After the first pass the visible content is a short pointer, so the size
    # check alone stops the second pass — no extra state needed.
    handler = _handler()
    repo = _FakeRepo()
    big = _msg(5, "tool", "x" * 500, tool_call_id="call_1", tool_name="read_file")

    first = handler._replace_large_tool_results("sess", [big], repo)
    second = handler._replace_large_tool_results("sess", [big], repo)

    assert first > 0
    assert second == 0
    assert len(repo.created) == 1


def test_one_failing_replacement_does_not_abort_the_rest():
    handler = _handler()
    repo = _BrokenRepo()
    big = _msg(5, "tool", "x" * 500, tool_call_id="call_1", tool_name="read_file")

    # Compression must still be able to proceed to the LLM step.
    assert handler._replace_large_tool_results("sess", [big], repo) == 0
    assert big.content == "x" * 500


def test_summary_accumulation_warns_but_does_not_merge(caplog):
    handler = _handler()
    summaries = [
        _msg(i, "summary", "s", message_type="compressed") for i in range(20)
    ]

    with caplog.at_level("WARNING"):
        handler._warn_if_summaries_accumulating(summaries)

    assert any("摘要" in record.message for record in caplog.records)


def test_no_warning_for_a_handful_of_summaries(caplog):
    handler = _handler()
    summaries = [_msg(i, "summary", "s", message_type="compressed") for i in range(3)]

    with caplog.at_level("WARNING"):
        handler._warn_if_summaries_accumulating(summaries)

    assert not caplog.records
