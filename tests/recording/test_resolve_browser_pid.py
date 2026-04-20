"""Tests for PlaywrightRecordingDriver.resolve_browser_pid."""

import sys
from unittest.mock import MagicMock, patch

import pytest

from src.recording.browser.playwright_recording_driver import PlaywrightRecordingDriver


@pytest.fixture
def driver(tmp_path):
    return PlaywrightRecordingDriver(
        storage_path=tmp_path / "storage",
        unified_config=MagicMock(),
    )


def _fake_process(pid, name, cmdline):
    """Create a mock psutil process."""
    proc = MagicMock()
    proc.info = {"pid": pid, "name": name, "cmdline": cmdline}
    proc.pid = pid
    return proc


class TestResolveBrowserPid:
    def test_returns_pid_when_single_match(self, driver, tmp_path):
        bundle = tmp_path / "bundle_token123"
        bundle.mkdir()
        driver._playwright_extension_bundle_path = bundle

        fake_proc = _fake_process(
            42, "chrome.exe",
            ["chrome.exe", f"--load-extension={bundle}"],
        )

        with patch("psutil.process_iter", return_value=[fake_proc]):
            result = driver.resolve_browser_pid()

        assert result == 42

    def test_returns_none_when_no_bundle_path(self, driver):
        driver._playwright_extension_bundle_path = None
        assert driver.resolve_browser_pid() is None

    def test_returns_none_when_bundle_not_exists(self, driver, tmp_path):
        driver._playwright_extension_bundle_path = tmp_path / "nonexistent"
        assert driver.resolve_browser_pid() is None

    def test_filters_type_subprocesses(self, driver, tmp_path):
        bundle = tmp_path / "bundle"
        bundle.mkdir()
        driver._playwright_extension_bundle_path = bundle

        main_proc = _fake_process(
            42, "chrome.exe",
            ["chrome.exe", f"--load-extension={bundle}"],
        )
        renderer_proc = _fake_process(
            43, "chrome.exe",
            ["chrome.exe", f"--load-extension={bundle}", "--type=renderer"],
        )

        with patch("psutil.process_iter", return_value=[main_proc, renderer_proc]):
            result = driver.resolve_browser_pid()

        assert result == 42

    def test_returns_none_when_multiple_candidates(self, driver, tmp_path):
        bundle = tmp_path / "bundle"
        bundle.mkdir()
        driver._playwright_extension_bundle_path = bundle

        proc1 = _fake_process(42, "chrome.exe", ["chrome.exe", f"--load-extension={bundle}"])
        proc2 = _fake_process(99, "chrome.exe", ["chrome.exe", f"--load-extension={bundle}"])

        with patch("psutil.process_iter", return_value=[proc1, proc2]):
            result = driver.resolve_browser_pid()

        assert result is None

    def test_returns_none_when_no_match(self, driver, tmp_path):
        bundle = tmp_path / "bundle"
        bundle.mkdir()
        driver._playwright_extension_bundle_path = bundle

        other_proc = _fake_process(
            42, "chrome.exe",
            ["chrome.exe", "--load-extension=/other/path"],
        )

        with patch("psutil.process_iter", return_value=[other_proc]):
            result = driver.resolve_browser_pid()

        assert result is None

    def test_matches_when_cmdline_uses_different_path_separators(self, driver, tmp_path):
        bundle = tmp_path / "bundle"
        bundle.mkdir()
        driver._playwright_extension_bundle_path = bundle

        bundle_backslash = str(bundle).replace("/", "\\")
        fake_proc = _fake_process(
            77,
            "chrome.exe",
            ["chrome.exe", f"--load-extension={bundle_backslash}"],
        )

        with patch("psutil.process_iter", return_value=[fake_proc]):
            result = driver.resolve_browser_pid()

        assert result == 77

    def test_ignores_non_chromium_processes(self, driver, tmp_path):
        bundle = tmp_path / "bundle"
        bundle.mkdir()
        driver._playwright_extension_bundle_path = bundle

        fake_proc = _fake_process(
            42, "firefox.exe",
            ["firefox.exe", f"--load-extension={bundle}"],
        )

        with patch("psutil.process_iter", return_value=[fake_proc]):
            result = driver.resolve_browser_pid()

        assert result is None

    def test_matches_edge_browser(self, driver, tmp_path):
        bundle = tmp_path / "bundle"
        bundle.mkdir()
        driver._playwright_extension_bundle_path = bundle

        edge_proc = _fake_process(
            55, "msedge.exe",
            ["msedge.exe", f"--load-extension={bundle}"],
        )

        with patch("psutil.process_iter", return_value=[edge_proc]):
            result = driver.resolve_browser_pid()

        assert result == 55

    def test_psutil_import_error(self, driver, tmp_path):
        bundle = tmp_path / "bundle"
        bundle.mkdir()
        driver._playwright_extension_bundle_path = bundle

        with patch.dict(sys.modules, {"psutil": None}):
            with patch("builtins.__import__", side_effect=ImportError("no psutil")):
                result = driver.resolve_browser_pid()

        assert result is None

    def test_shared_user_data_dir_is_not_used_as_fallback(self, driver, tmp_path):
        bundle = tmp_path / "missing_bundle"
        driver._playwright_extension_bundle_path = bundle
        driver.user_data_dir = tmp_path / "playwright_user_data_persistent"

        fake_proc = _fake_process(
            42,
            "chrome.exe",
            ["chrome.exe", f"--user-data-dir={driver.user_data_dir}"],
        )

        with patch("psutil.process_iter", return_value=[fake_proc]):
            result = driver.resolve_browser_pid()

        assert result is None
