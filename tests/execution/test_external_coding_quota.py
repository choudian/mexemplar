import json

from src.execution.external_coding_quota import (
    _parse_claude_usage_output,
    _parse_codex_rate_limits_response,
)


def test_claude_usage_parser_discards_raw_account_text() -> None:
    raw = json.dumps(
        {
            "type": "result",
            "is_error": False,
            "result": (
                "Current session: 10% used\n"
                "Current week (all models): 82% used\n"
                "account=test@example.com token=secret"
            ),
        }
    )

    snapshot = _parse_claude_usage_output(raw)

    assert snapshot is not None
    assert snapshot.usage_percents == (10, 82)
    assert "test@example.com" not in repr(snapshot)
    assert "secret" not in repr(snapshot)


def test_codex_rate_limit_parser_discards_credits_and_account_metadata() -> None:
    response = {
        "id": 2,
        "result": {
            "rateLimits": {
                "primary": {"usedPercent": 100, "resetsAt": 1_800_000_000},
                "secondary": {"usedPercent": 20, "resetsAt": 1_900_000_000},
                "rateLimitReachedType": "rate_limit_reached",
            },
            "rateLimitResetCredits": {
                "credits": [{"description": "invited private@example.com", "token": "secret"}]
            },
        },
    }

    snapshot = _parse_codex_rate_limits_response(response)

    assert snapshot is not None
    assert snapshot.usage_percents == (100, 20)
    assert snapshot.reached is True
    assert snapshot.reset_epochs == (1_800_000_000, 1_900_000_000)
    assert "private@example.com" not in repr(snapshot)
    assert "secret" not in repr(snapshot)
