"""Behaviour contract for token usage capture (1.1)."""

from __future__ import annotations

from src.business.ai.token_usage import (
    TokenUsage,
    estimate_token_usage,
    estimate_tokens,
    extract_token_usage,
)


class _Message:
    def __init__(self, usage_metadata):
        self.usage_metadata = usage_metadata


def test_extracts_provider_reported_usage_including_cache_and_reasoning():
    # Shape verified against GLM-4.7 and 讯飞 astron-code via LangChain.
    message = _Message(
        {
            "input_tokens": 11,
            "output_tokens": 246,
            "total_tokens": 257,
            "input_token_details": {"cache_read": 4},
            "output_token_details": {"reasoning": 243},
        }
    )

    usage = extract_token_usage(message)

    assert usage is not None
    assert usage.input_tokens == 11
    assert usage.output_tokens == 246
    assert usage.total_tokens == 257
    assert usage.cache_read_tokens == 4
    assert usage.reasoning_tokens == 243
    assert usage.source == "actual"
    assert usage.is_actual is True


def test_missing_detail_blocks_default_to_zero_without_failing():
    usage = extract_token_usage(_Message({"input_tokens": 10, "output_tokens": 5}))

    assert usage is not None
    assert usage.cache_read_tokens == 0
    assert usage.reasoning_tokens == 0
    assert usage.total_tokens == 15


def test_returns_none_when_provider_reports_nothing():
    assert extract_token_usage(_Message(None)) is None
    assert extract_token_usage(_Message({})) is None
    assert extract_token_usage(object()) is None


def test_negative_or_malformed_counts_are_clamped_not_propagated():
    usage = extract_token_usage(
        _Message({"input_tokens": -5, "output_tokens": "abc", "total_tokens": 7})
    )

    assert usage is not None
    assert usage.input_tokens == 0
    assert usage.output_tokens == 0
    assert usage.total_tokens == 7


def test_estimation_is_marked_so_it_never_passes_as_a_cost_figure():
    usage = estimate_token_usage(prompt="hello", completion="world")

    assert usage.source == "estimated"
    assert usage.is_actual is False


def test_chinese_is_not_under_counted_the_way_a_single_divisor_would():
    # 58 Chinese characters measured at 37 real input tokens; the previous
    # len/3*1.2 formula produced 23, a 38% under-count that delayed compression.
    text = "请" * 58
    old_formula = int(len(text) / 3 * 1.2)

    assert estimate_tokens(text) > old_formula


def test_round_trips_through_dict_for_persistence():
    usage = TokenUsage(
        input_tokens=1,
        output_tokens=2,
        total_tokens=3,
        cache_read_tokens=4,
        reasoning_tokens=5,
        source="estimated",
    )

    assert TokenUsage.from_dict(usage.to_dict()) == usage


def test_from_dict_rejects_unusable_payloads():
    assert TokenUsage.from_dict(None) is None
    assert TokenUsage.from_dict({"inputTokens": object()}) is None
