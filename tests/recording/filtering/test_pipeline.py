from src.data.config_models import RecordingNoiseFilterConfig
from src.recording.filtering.pipeline import NoiseFilterPipeline


def _pipeline() -> NoiseFilterPipeline:
    return NoiseFilterPipeline(RecordingNoiseFilterConfig())


def test_pipeline_applies_rules_in_order():
    decision = _pipeline().evaluate(
        {
            "url": "https://www.googletagmanager.com/redirect.png",
            "method": "OPTIONS",
            "response_status": 302,
            "response_headers": {"content-type": "image/png"},
        },
        primary_site="example.com",
    )

    assert decision is not None
    assert decision.reason == "options_preflight"


def test_pipeline_prefers_blacklist_reason_over_third_party():
    decision = _pipeline().evaluate(
        {"url": "https://www.googletagmanager.com/gtm.js", "method": "GET"},
        primary_site="example.com",
    )

    assert decision is not None
    assert decision.reason == "ad_tracking_blacklist"
    assert decision.pattern_matched == "googletagmanager"


def test_pipeline_stops_after_first_matching_rule():
    decision = _pipeline().evaluate(
        {
            "url": "https://www.googletagmanager.com/logo.png",
            "method": "GET",
            "response_headers": {"content-type": "image/png"},
        },
        primary_site="example.com",
    )

    assert decision is not None
    assert decision.reason == "static_asset"
    assert decision.pattern_matched in {".png", "image/png"}


def test_pipeline_returns_none_when_no_rule_matches():
    decision = _pipeline().evaluate(
        {
            "url": "https://api.example.com/orders",
            "method": "POST",
            "response_status": 200,
            "response_headers": {"content-type": "application/json"},
        },
        primary_site="example.com",
    )

    assert decision is None
