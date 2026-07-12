from types import SimpleNamespace

from src.recording.browser_recorder import BrowserRecorder


def _recorder_with_configured_url(url):
    recorder = object.__new__(BrowserRecorder)
    recorder._unified_config = SimpleNamespace(
        get_recording_browser_start_url=lambda: url,
    )
    return recorder


def test_explicit_start_url_has_precedence_over_configured_url():
    recorder = _recorder_with_configured_url("https://configured.example/path")

    assert (
        recorder._resolve_browser_start_url(" https://explicit.example/path ")
        == "https://explicit.example/path"
    )


def test_none_start_url_falls_back_to_configured_url():
    recorder = _recorder_with_configured_url("https://configured.example/path")

    assert recorder._resolve_browser_start_url(None) == "https://configured.example/path"


def test_explicit_blank_start_url_suppresses_configured_fallback():
    recorder = _recorder_with_configured_url("https://configured.example/path")

    assert recorder._resolve_browser_start_url("   ") is None


def test_invalid_configured_start_url_falls_back_to_blank_page():
    recorder = _recorder_with_configured_url("not a URL")

    assert recorder._resolve_browser_start_url(None) is None
