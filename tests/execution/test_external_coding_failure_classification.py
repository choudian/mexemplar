"""Failure classification decides what the specialist does next (1.x).

A misread is not cosmetic: `model_unavailable` tells the specialist to switch
tools or lower the effort, while the real cause may be that the endpoint is
unreachable — no tool switch will ever fix that.

The strings below are taken from real logs produced during the first live run.
"""

from __future__ import annotations

from src.execution.external_coding_process import _classify_failure


def _category(log_text: str) -> str:
    return _classify_failure(log_text)[0]


# --- 网络层拒绝：本次实际发生的误判 -------------------------------------------


def test_network_level_403_is_not_reported_as_a_model_problem():
    # Real log line. A bare curl with no credentials at all gets the same 403,
    # so this is the endpoint refusing the machine, not the account failing.
    log = (
        'claude -p <prompt> --effort max --safe-mode\n'
        '{"type":"text","text":"Failed to authenticate. API Error: 403 Request not allowed"}\n'
        '{"api_error_status":403,"error":"authentication_failed"}'
    )

    assert _category(log) != "model_unavailable"


def test_the_effort_flag_in_the_command_line_does_not_drive_classification():
    # `--effort` appears in every Claude command we build, so a bare "effort"
    # substring matched almost any failure and shadowed the real reason.
    log = "claude -p <prompt> --effort max\nsomething entirely unrelated went wrong"

    assert _category(log) == "process_error"


def test_a_genuine_effort_rejection_is_still_recognised():
    assert _category("error: unsupported effort level 'max' for this model") == (
        "model_unavailable"
    )
    assert _category("model unavailable for this account") == "model_unavailable"


def test_unrecognised_wording_falls_through_instead_of_guessing():
    # Deliberately narrow. An unmatched failure lands on process_error, which
    # tells the specialist nothing but misleads it nowhere; a wrong specific
    # category sends it off fixing something that was never broken.
    assert _category("the requested model is unavailable") == "process_error"


# --- 认证 ---------------------------------------------------------------------


def test_authentication_wording_variants_are_recognised():
    # The previous word list only had unauthorized / not logged in / login
    # required, none of which appear in what the CLI actually prints.
    for log in (
        "Failed to authenticate. API Error: 401",
        '{"error":"authentication_failed"}',
        "Error: unauthorized",
        "You are not logged in",
        "login required",
    ):
        assert _category(log) == "login_required", log


# --- 既有分类不回归 -----------------------------------------------------------


def test_quota_still_wins_over_everything_else():
    # Quota is the most actionable signal; keep it ahead of the rest.
    assert _category("usage limit reached; also unauthorized") == "quota_exhausted"


def test_network_failures_are_still_recognised():
    for log in (
        "connection refused",
        "getaddrinfo failed: dns error",
        "request timed out",
    ):
        assert _category(log) == "network", log


def test_unmatched_output_falls_back_to_process_error():
    assert _category("segmentation fault") == "process_error"
    assert _category("") == "process_error"


def test_every_category_carries_a_message():
    for log in ("quota exceeded", "unauthorized", "unsupported model", "dns", "boom"):
        category, message = _classify_failure(log)
        assert category and message, log
