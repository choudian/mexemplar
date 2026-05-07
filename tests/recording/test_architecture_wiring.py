import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from src.recording.browser_recorder import BrowserRecorder
from src.recording.websocket_server import WebSocketServer
from src.business.agents.tools import recording_data_tools


class StubWSServer:
    async def send_to_client(self, websocket, message):
        await websocket.send(__import__("json").dumps(message))


def build_recorder():
    with patch.object(BrowserRecorder, "_ensure_ws_server", return_value=None):
        recorder = BrowserRecorder()
    recorder._ws_server = StubWSServer()
    return recorder


class TestExtensionTriggerSmokeTests:
    def test_recording_control_routes_through_ws_to_handler(self):
        server = WebSocketServer(host="127.0.0.1", port=9999)
        called = []

        def handler(data, ws):
            del ws
            called.append(data)

        server.set_control_handler(handler)
        mock_ws = AsyncMock()
        mock_ws.remote_address = ("127.0.0.1", 12345)

        asyncio.run(server.process_message({"type": "recording_control", "action": "start"}, mock_ws))

        assert len(called) == 1
        assert called[0]["action"] == "start"

    def test_extension_start_triggers_proxy_and_accessibility(self):
        recorder = build_recorder()
        mock_proxy = MagicMock()
        mock_proxy.start.return_value = True
        mock_accessibility = MagicMock()
        mock_ws = AsyncMock()

        with patch.object(recorder, "_proxy_recorder", mock_proxy):
            with patch.object(recorder, "_accessibility_recorder", mock_accessibility):
                asyncio.run(
                    recorder._handle_control_message(
                        {"type": "recording_control", "action": "start", "source": "extension"},
                        mock_ws,
                    )
                )

        mock_proxy.start.assert_called_once()
        mock_accessibility.start.assert_called_once()


class TestGatekeeperTests:
    def test_recorder_module_removed(self):
        """src/recording/recorder.py was dead code and has been removed."""
        assert not Path("src/recording/recorder.py").exists()

    def test_browser_phase2_split_modules_exist(self):
        from src.recording.browser.async_event_loop_runner import AsyncEventLoopRunner
        from src.recording.browser.duckdb_recording_persister import DuckDBRecordingPersister
        from src.recording.browser.playwright_recording_driver import PlaywrightRecordingDriver
        from src.recording.browser.recording_websocket_coordinator import (
            RecordingWebSocketCoordinator,
        )

        assert AsyncEventLoopRunner is not None
        assert PlaywrightRecordingDriver is not None
        assert RecordingWebSocketCoordinator is not None
        assert DuckDBRecordingPersister is not None

    def test_browser_recorder_init_is_lazy_for_duckdb(self):
        with patch("src.data.recording_repository.RecordingRepository") as mock_repo_cls:
            with patch.object(BrowserRecorder, "_ensure_ws_server", return_value=None):
                BrowserRecorder()

        mock_repo_cls.assert_not_called()

    def test_browser_recorder_facade_delegates_to_new_persister(self):
        recorder = build_recorder()

        with patch.object(recorder._duckdb_persister, "save_to_duckdb", return_value=3) as mock_save:
            result = recorder._save_to_duckdb(123.0)

        assert result == 3
        mock_save.assert_called_once()

    def test_proxy_recorder_exists(self):
        from src.recording.proxy_recorder import ProxyRecorder, RecordingAddon

        assert ProxyRecorder is not None
        assert RecordingAddon is not None

    def test_accessibility_recorder_exists(self):
        from src.recording.accessibility_recorder import AccessibilityRecorder

        assert AccessibilityRecorder is not None

    def test_system_proxy_and_cert_manager_exist(self):
        from src.recording.cert_manager import CertManager
        from src.recording.system_proxy import SystemProxyManager

        assert SystemProxyManager is not None
        assert CertManager is not None


class TestScreenshotFeatureGatekeeper:
    """Gatekeeper tests from design doc §5.2 — screenshot feature wiring."""

    def test_analyze_image_no_legacy_screenshot_columns(self):
        """_analyze_image should not reference screenshot_before/screenshot_after from actions."""
        source = Path("src/business/agents/tools/recording_data_tools.py").read_text(encoding="utf-8")
        func_start = source.find("def _analyze_image(")
        func_end = source.find("\ndef ", func_start + 1)
        func_body = source[func_start:func_end]

        assert "screenshot_before" not in func_body, "_analyze_image still references screenshot_before"
        assert "screenshot_after" not in func_body, "_analyze_image still references screenshot_after"

    def test_analyze_image_sql_no_source_trigger_where(self):
        """_analyze_image SQL must not use source_trigger in WHERE clause."""
        source = Path("src/business/agents/tools/recording_data_tools.py").read_text(encoding="utf-8")
        func_start = source.find("def _analyze_image(")
        func_end = source.find("\ndef ", func_start + 1)
        func_body = source[func_start:func_end]

        assert "source_trigger" not in func_body, "_analyze_image SQL references source_trigger"

    def test_common_tables_has_recording_screenshots(self):
        """_COMMON_TABLES must include recording_screenshots."""
        from src.business.agents.tools.recording_data_tools import _COMMON_TABLES

        assert "recording_screenshots" in _COMMON_TABLES

    def test_duckdb_manager_valid_tables_has_screenshots(self):
        """DuckDBManager._VALID_TABLES must include recording_screenshots."""
        from src.data.duckdb_manager import _VALID_TABLES

        assert "recording_screenshots" in _VALID_TABLES

    def test_duckdb_manager_valid_columns_has_screenshots(self):
        """DuckDBManager._VALID_COLUMNS must include recording_screenshots with correct columns."""
        from src.data.duckdb_manager import _VALID_COLUMNS

        assert "recording_screenshots" in _VALID_COLUMNS
        cols = _VALID_COLUMNS["recording_screenshots"]
        for required in ["screenshot_id", "recording_id", "moment", "timestamp", "data"]:
            assert required in cols, f"Missing column {required} in _VALID_COLUMNS"

    def test_persister_no_pair_matching(self):
        """duckdb_recording_persister.py must not contain screenshot pairing/matching logic."""
        source = Path("src/recording/browser/duckdb_recording_persister.py").read_text(encoding="utf-8")
        for forbidden in ["pair_screenshot", "match_anchor", "match_window", "screenshot_pair"]:
            assert forbidden not in source, f"Persister contains forbidden term: {forbidden}"

    def test_websocket_coordinator_unchanged(self):
        """recording_websocket_coordinator.py should not contain browser_context."""
        source = Path("src/recording/browser/recording_websocket_coordinator.py").read_text(encoding="utf-8")
        assert "browser_context" not in source

    def test_playwright_driver_no_framenavigated(self):
        """playwright_recording_driver.py must not subscribe to framenavigated or URL tracking."""
        source = Path("src/recording/browser/playwright_recording_driver.py").read_text(encoding="utf-8")
        assert "framenavigated" not in source
        assert "update_current_url" not in source

    def test_recorder_uses_queue_paths(self):
        """browser_recorder.py should not hardcode get_default_data_dir / 'queues'."""
        source = Path("src/recording/browser_recorder.py").read_text(encoding="utf-8")
        assert 'get_default_data_dir()' not in source or "queue_paths" in source

    def test_browser_stop_order_keeps_hook_flush_before_close_and_save(self):
        source = Path("src/recording/browser_recorder.py").read_text(encoding="utf-8")
        func_start = source.find("async def _async_stop_recording(self)")
        func_end = source.find("\n    async def _wait_for_stop_drain", func_start)
        func_body = source[func_start:func_end]

        assert func_body.find("_send_stop_command_via_ws") < func_body.find("_wait_for_stop_drain")
        assert func_body.find("_wait_for_stop_drain") < func_body.find("self._screenshot_hook.stop")
        assert func_body.find("self._screenshot_hook.stop") < func_body.find("await self._close_browser()")
        assert func_body.find("await self._close_browser()") < func_body.find("self._save_to_duckdb")

    def test_recovery_no_screenshot_replay(self):
        """recording_recovery.py should not contain screenshot replay/restore logic."""
        source = Path("src/data/recording_recovery.py").read_text(encoding="utf-8")
        # "replay" or "restore" combined with "screenshot" is forbidden
        lines = source.lower().split("\n")
        for line in lines:
            if "screenshot" in line:
                assert "replay" not in line and "restore" not in line, \
                    f"Found forbidden screenshot replay/restore: {line.strip()}"

    def test_screenshot_modules_exist(self):
        """New screenshot modules should exist."""
        assert Path("src/recording/browser_screenshot_hook.py").exists()
        assert Path("src/recording/queue_paths.py").exists()
        assert Path("src/recording/browser/screenshot_queue_parser.py").exists()


class TestLargeFieldToolWiring:
    """T029: read_field_chunk 注册在 5 个通用录制工具内的 wiring smoke test。"""

    def test_browser_create_recording_tools_returns_five_common_plus_analyze_image(self):
        tools = recording_data_tools.create_recording_tools("test-rec")
        assert len(tools) == 6

    def test_read_field_chunk_is_registered(self):
        tools = recording_data_tools.create_recording_tools("test-rec")
        names = [t.name for t in tools]
        assert "read_field_chunk" in names

    def test_browser_tool_order_is_correct(self):
        tools = recording_data_tools.create_recording_tools("test-rec")
        names = [t.name for t in tools]
        assert names == [
            "describe_data",
            "query_data",
            "execute_code",
            "read_recording",
            "read_field_chunk",
            "analyze_image",
        ]
