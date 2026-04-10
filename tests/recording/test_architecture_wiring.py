import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from src.recording.browser_recorder import BrowserRecorder
from src.recording.websocket_server import WebSocketServer


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
    def test_recorder_does_not_import_removed_modules(self):
        source = Path("src/recording/recorder.py").read_text(encoding="utf-8")
        assert "workflow_orchestrator" not in source.lower()

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
