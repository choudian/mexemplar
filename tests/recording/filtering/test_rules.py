from src.recording.filtering.rules import (
    is_options_preflight,
    is_redirect_3xx,
    is_static_asset,
    is_third_party,
    matches_blacklist,
)


def test_is_options_preflight_matches_options_only():
    assert is_options_preflight({"method": "OPTIONS"}) is True
    assert is_options_preflight({"method": "GET"}) is False


def test_is_redirect_3xx_accepts_int_or_string_status():
    assert is_redirect_3xx({"response_status": 302}) is True
    assert is_redirect_3xx({"response_status": "301"}) is True
    assert is_redirect_3xx({"response_status": 200}) is False
    assert is_redirect_3xx({"response_status": "nope"}) is False


def test_is_static_asset_matches_extension_and_content_type_case_insensitively():
    config_extensions = [".png", ".css"]
    config_content_types = ["image/", "text/css", "application/octet-stream"]

    assert (
        is_static_asset(
            {"url": "https://example.com/assets/logo.PNG?cache=1"},
            static_extensions=config_extensions,
            static_content_type_prefixes=config_content_types,
        )
        == ".png"
    )
    assert (
        is_static_asset(
            {
                "url": "https://example.com/api/data",
                "response_headers": {"CONTENT-TYPE": "image/svg+xml; charset=utf-8"},
            },
            static_extensions=config_extensions,
            static_content_type_prefixes=config_content_types,
        )
        == "image/svg+xml"
    )
    assert (
        is_static_asset(
            {"url": "https://example.com/api/data"},
            static_extensions=config_extensions,
            static_content_type_prefixes=config_content_types,
        )
        is None
    )


def test_matches_blacklist_returns_first_matching_pattern():
    request = {"url": "https://www.googletagmanager.com/gtm.js"}

    assert (
        matches_blacklist(
            request,
            blacklist_domains=["doubleclick", "googletagmanager", "sentry"],
        )
        == "googletagmanager"
    )
    assert matches_blacklist(request, blacklist_domains=["sentry"]) is None


def test_is_third_party_respects_primary_site_and_whitelist():
    assert (
        is_third_party(
            {"url": "https://api.example.com/data"},
            primary_site="example.com",
            first_party_sites=[],
        )
        is False
    )
    assert (
        is_third_party(
            {"url": "https://assets.partner.com/app.js"},
            primary_site="example.com",
            first_party_sites=["partner.com"],
        )
        is False
    )
    assert (
        is_third_party(
            {"url": "https://analytics.other.com/pixel"},
            primary_site="example.com",
            first_party_sites=[],
        )
        is True
    )
    assert (
        is_third_party(
            {"url": "https://127.0.0.1/api"},
            primary_site="example.com",
            first_party_sites=[],
        )
        is False
    )
