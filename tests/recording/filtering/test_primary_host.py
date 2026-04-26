from src.recording.filtering import primary_host


def test_derive_primary_host_uses_first_http_or_https_action():
    actions = [
        {"url": "chrome://settings"},
        {"url": "https://www.example.com/home"},
        {"url": "https://other.example.net"},
    ]

    assert primary_host._derive_primary_host(actions) == "www.example.com"


def test_derive_primary_host_returns_none_for_empty_or_non_http_actions():
    assert primary_host._derive_primary_host([]) is None
    assert primary_host._derive_primary_host([{"url": "file:///tmp/demo.html"}]) is None


def test_normalize_host_to_site_collapses_same_site_subdomains():
    assert primary_host.normalize_host_to_site("www.example.com") == "example.com"
    assert primary_host.normalize_host_to_site("api.example.com") == "example.com"


def test_normalize_host_to_site_handles_cctld_and_invalid_hosts():
    assert primary_host.normalize_host_to_site("www.example.co.uk") == "example.co.uk"
    assert primary_host.normalize_host_to_site("api.example.co.uk") == "example.co.uk"
    assert primary_host.normalize_host_to_site("127.0.0.1") is None
    assert primary_host.normalize_host_to_site("localhost") is None
    assert primary_host.normalize_host_to_site("") is None


def test_derive_primary_site_returns_none_when_actions_cannot_produce_site():
    assert primary_host.derive_primary_site([{"url": "about:blank"}]) is None
    assert primary_host.derive_primary_site([{"url": "https://www.example.com"}]) == "example.com"


def test_tldextract_is_configured_without_network_fetch():
    assert primary_host._TLD_EXTRACT.suffix_list_urls == ()
