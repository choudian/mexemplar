"""LLM 最终失败的额度路由行为契约。"""

import logging

import pytest

from src.business.agents.agent_loop import _classify_llm_failure


_OLD_RECOVERABLE_MESSAGE_MARKERS = (
    "429",
    "rate limit",
    "ratelimit",
    "too many requests",
    "quota",
    "insufficient_quota",
    "billing",
    "credit balance",
    "insufficient credit",
    "overloaded",
    "529",
    "timeout",
    "temporarily unavailable",
    "service unavailable",
    "502",
    "503",
    "504",
)
_OLD_RECOVERABLE_EXCEPTION_TYPES = (
    "RateLimitError",
    "APIConnectionError",
    "APITimeoutError",
    "InternalServerError",
    "ServiceUnavailable",
    "OverloadedError",
    "ConnectionError",
    "ConnectTimeout",
    "ReadTimeout",
    "Timeout",
)


def test_explicit_quota_marker_is_classified_as_quota() -> None:
    assert (
        _classify_llm_failure(
            RuntimeError("provider error: insufficient_quota"),
            quota_markers=["insufficient_quota"],
        )
        == "quota"
    )


def test_quota_scan_covers_the_whole_chain_before_recoverable_fallback() -> None:
    class RateLimitError(RuntimeError):
        pass

    inner = RuntimeError("provider body: insufficient_quota")
    outer = RateLimitError("429 rate limit")
    outer.__cause__ = inner

    assert _classify_llm_failure(outer, quota_markers=["insufficient_quota"]) == "quota"


@pytest.mark.parametrize(
    "message",
    [
        "Error code: 429 rate limit",
        "HTTP 503 service unavailable",
        "request timeout",
        "billing subsystem error",
        "billing service temporarily unavailable",
    ],
)
def test_non_quota_recoverable_failures_keep_the_old_route(message: str) -> None:
    assert (
        _classify_llm_failure(
            RuntimeError(message),
            quota_markers=["insufficient_quota"],
        )
        == "other_recoverable"
    )


@pytest.mark.parametrize("marker", _OLD_RECOVERABLE_MESSAGE_MARKERS)
def test_empty_quota_markers_preserve_every_old_message_marker(marker: str) -> None:
    assert (
        _classify_llm_failure(
            RuntimeError(f"provider failure: {marker}"),
            quota_markers=[],
        )
        == "other_recoverable"
    )


@pytest.mark.parametrize("type_name", _OLD_RECOVERABLE_EXCEPTION_TYPES)
def test_empty_quota_markers_preserve_every_old_exception_type(type_name: str) -> None:
    exception_type = type(type_name, (RuntimeError,), {})
    assert (
        _classify_llm_failure(exception_type("opaque provider failure"), quota_markers=[])
        == "other_recoverable"
    )


def test_quota_marker_matching_strips_and_casefolds_both_sides() -> None:
    assert (
        _classify_llm_failure(
            RuntimeError("provider error: insufficient_quota"),
            quota_markers=[" Insufficient_Quota "],
        )
        == "quota"
    )


@pytest.mark.parametrize(
    "message",
    [
        "Error code: 401 authentication failed",
        "Error code: 400 invalid request",
    ],
)
def test_nonrecoverable_authentication_and_bad_request_stay_errors(message: str) -> None:
    assert _classify_llm_failure(RuntimeError(message), quota_markers=[]) is None


def test_custom_marker_cannot_widen_the_old_recoverable_boundary() -> None:
    """配置只细分既有可恢复失败，不能把认证错误从 ERROR 改成 PAUSED。"""
    assert (
        _classify_llm_failure(
            RuntimeError("Error code: 401 authentication failed"),
            quota_markers=["authentication"],
        )
        is None
    )


def test_custom_quota_marker_is_effective() -> None:
    class RateLimitError(RuntimeError):
        pass

    assert (
        _classify_llm_failure(
            RateLimitError("provider code: hard-wallet-empty"),
            quota_markers=["hard-wallet-empty"],
        )
        == "quota"
    )


@pytest.mark.parametrize(
    "invalid_markers",
    [
        "quota",
        ["", "   ", None, 7],
    ],
)
def test_invalid_quota_marker_configuration_is_ignored_with_warning(
    invalid_markers: object,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)

    assert (
        _classify_llm_failure(
            RuntimeError("provider returned the single letter q"),
            quota_markers=invalid_markers,
        )
        is None
    )
    assert "ai.failure_routing.quota_markers" in caplog.text
