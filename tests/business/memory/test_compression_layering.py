"""Compression must stop degrading its own output over time (1.3)."""

from __future__ import annotations

import json

from src.business.ai.token_usage import TokenUsage
from src.business.memory.compression_handler import (
    CompressionHandler,
    TokenTrigger,
    _is_summary,
)
from src.data.models_sqlite import Message
from src.data.unified_config import UnifiedConfigManager


def _msg(seq, role, content="", **kwargs):
    return Message(
        message_id=f"msg_{seq}",
        session_id="sess",
        sequence=seq,
        role=role,
        content=content,
        **kwargs,
    )


def _summary_msg(seq, content="旧摘要"):
    return _msg(seq, "summary", content, message_type="compressed")


def _handler(keep_recent=2):
    handler = object.__new__(CompressionHandler)
    handler.keep_recent = keep_recent
    handler.size_threshold = 100
    handler._trigger = TokenTrigger(10**9)
    return handler


# --- a. 摘要不重压 -----------------------------------------------------------


def test_existing_summaries_are_kept_out_of_the_compress_zone():
    # Re-compressing a summary makes the earliest content third-hand — and in
    # coding work the earliest content (the requirement, why an approach was
    # chosen) is the part that matters most.
    handler = _handler(keep_recent=2)
    messages = [
        _msg(1, "system", "sys"),
        _summary_msg(2),
        _msg(3, "user", "a"),
        _msg(4, "assistant", "b"),
        _msg(5, "user", "c"),
        _msg(6, "assistant", "d"),
    ]

    system_msg, summaries, compress, keep = handler._split_messages(messages)

    assert system_msg.role == "system"
    assert [m.sequence for m in summaries] == [2]
    assert [m.sequence for m in compress] == [3, 4]
    assert [m.sequence for m in keep] == [5, 6]


def test_keep_recent_counts_originals_only_so_summaries_do_not_squeeze_it():
    handler = _handler(keep_recent=2)
    messages = [
        _summary_msg(1),
        _summary_msg(2),
        _msg(3, "user", "a"),
        _msg(4, "assistant", "b"),
        _msg(5, "user", "c"),
    ]

    _system, summaries, compress, keep = handler._split_messages(messages)

    assert len(summaries) == 2
    assert [m.sequence for m in compress] == [3]
    assert [m.sequence for m in keep] == [4, 5]


def test_summaries_are_rebuilt_in_time_order_not_merged():
    handler = _handler()
    rebuilt = handler._rebuild_messages(
        _msg(1, "system", "sys"),
        [_summary_msg(9, "第三段"), _summary_msg(2, "第一段")],
        [_msg(20, "user", "now")],
    )

    assert [m.sequence for m in rebuilt] == [1, 2, 9, 20]
    assert rebuilt[1].content == "第一段"
    assert rebuilt[2].content == "第三段"


def test_summary_detection_accepts_both_markers():
    assert _is_summary(_msg(1, "summary", message_type="compressed"))
    assert _is_summary(_msg(1, "assistant", message_type="compressed"))
    assert _is_summary(_msg(1, "summary"))
    assert not _is_summary(_msg(1, "assistant", "normal reply"))


# --- c1. 真实 token 优先于估算 ------------------------------------------------


def _usage_json(input_tokens, source="actual"):
    return json.dumps(
        TokenUsage(
            input_tokens=input_tokens,
            output_tokens=0,
            total_tokens=input_tokens,
            source=source,
        ).to_dict()
    )


def test_measure_prefers_the_real_input_tokens_from_the_last_request():
    # Character estimation cannot see the system prompt or tool schemas at all.
    trigger = TokenTrigger(threshold=1000)
    messages = [
        _msg(1, "user", "短"),
        _msg(2, "assistant", "回复", token_usage=_usage_json(5000)),
    ]

    assert trigger.measure(messages) == 5000


def test_messages_after_the_anchor_are_estimated_and_added():
    trigger = TokenTrigger(threshold=1000)
    messages = [
        _msg(1, "assistant", "回复", token_usage=_usage_json(5000)),
        _msg(2, "user", "x" * 400),
    ]

    measured = trigger.measure(messages)

    assert measured > 5000
    assert measured < 5000 + 400  # latin text is well under one token per char


def test_estimated_usage_is_not_treated_as_an_anchor():
    # An estimated figure may drive a trigger but must not masquerade as the
    # authoritative context size.
    trigger = TokenTrigger(threshold=1000)
    messages = [_msg(1, "assistant", "hi", token_usage=_usage_json(5000, "estimated"))]

    assert trigger.measure(messages) < 100


def test_corrupt_usage_json_falls_back_instead_of_failing():
    trigger = TokenTrigger(threshold=1000)
    messages = [_msg(1, "assistant", "hello", token_usage="{not json")]

    assert trigger.measure(messages) >= 0


def test_tokens_freed_by_cheaper_layers_is_subtracted():
    # The anchor reports the size of *that* request and cannot see deletions
    # made afterwards, so each layer has to report what it freed.
    trigger = TokenTrigger(threshold=1000)
    messages = [_msg(1, "assistant", "回复", token_usage=_usage_json(5000))]

    assert trigger.measure(messages, tokens_freed=4000) == 1000
    assert trigger.measure(messages, tokens_freed=99999) == 0


def test_chinese_no_longer_under_counted_when_no_usage_exists():
    trigger = TokenTrigger(threshold=1000)
    text = "请" * 100
    old_formula = int(len(text) / 3 * 1.2)

    assert trigger.measure([_msg(1, "user", text)]) > old_formula


# --- d. 摘要结构 --------------------------------------------------------------


def test_summary_prompt_demands_verbatim_intent_and_next_step():
    prompt = CompressionHandler.COMPRESSION_PROMPT

    assert "任务初衷" in prompt
    assert "改动过的文件" in prompt
    assert "试过但失败的路径" in prompt
    assert "下一步" in prompt
    # Restating drifts; the point of these two sections is that they do not.
    assert "原样保留" in prompt
    assert "逐字引用" in prompt


def test_summary_prompt_still_forbids_dumping_raw_tool_data():
    # Raw payloads stay out of the summary and remain reachable by reference.
    assert "工具调用的原始数据" in CompressionHandler.COMPRESSION_PROMPT


# --- b1. 引用清单确定性附加 ---------------------------------------------------


def test_tool_calls_the_model_forgot_are_still_listed():
    handler = _handler()
    compress_msgs = [
        _msg(
            1,
            "assistant",
            "",
            tool_calls=json.dumps(
                [
                    {"id": "call_kept", "name": "read_file", "args": {"path": "a.py"}},
                    {"id": "call_lost", "name": "search", "args": {"q": "x"}},
                ]
            ),
        ),
        _msg(2, "tool", "y" * 50, tool_call_id="call_lost", tool_name="search"),
    ]

    result = handler._post_process_summary("模型只提到了 call_kept。", compress_msgs)

    assert "search" in result
    assert "本段其余工具调用" in result
    assert "[REF::msg_2]" in result


def test_no_index_section_when_the_model_mentioned_everything():
    handler = _handler()
    compress_msgs = [
        _msg(
            1,
            "assistant",
            "",
            tool_calls=json.dumps([{"id": "call_1", "name": "read_file", "args": {}}]),
        )
    ]

    result = handler._post_process_summary("用了 call_1 读文件。", compress_msgs)

    assert "本段其余工具调用" not in result


def test_config_defaults_are_still_readable():
    # Guards against the trigger construction path silently losing its config.
    config = UnifiedConfigManager()
    assert config.get_memory_compression_keep_recent() > 0
    assert config.get_memory_reference_size_threshold() > 0
