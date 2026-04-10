import asyncio
import json
import time
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.recording.proxy_recorder import ProxyRecorder, RecordingAddon


def _make_temp_file(name: str) -> Path:
    base = Path.cwd() / ".reports" / "pytest_tmp"
    base.mkdir(parents=True, exist_ok=True)
    return base / f"{uuid.uuid4().hex}_{name}"


class TestRecordingAddon:
    def test_request_response_written_to_queue(self):
        queue_file = _make_temp_file("test_actions.jsonl")
        addon = RecordingAddon(
            recording_id="rec_001",
            queue_file=queue_file,
        )

        mock_flow = MagicMock()
        mock_flow.request.url = "https://example.com/api/data"
        mock_flow.request.host = "example.com"
        mock_flow.request.method = "POST"
        mock_flow.request.content = b'{"key": "value"}'
        mock_flow.request.headers = {"content-type": "application/json"}
        mock_flow.request.timestamp_start = time.time()
        mock_flow.response.status_code = 200
        mock_flow.response.content = b'{"result": "ok"}'
        mock_flow.response.headers = {"content-type": "application/json"}

        addon.response(mock_flow)

        lines = queue_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 1
        data = json.loads(lines[0])
        assert data["type"] == "browser_action"
        assert data["recording_id"] == "rec_001"
        assert data["action"]["action_type"] == "network_request"
        assert data["action"]["url"] == "https://example.com/api/data"
        assert data["action"]["parameters"]["method"] == "POST"
        assert data["action"]["parameters"]["response_status"] == 200

    def test_ignored_hosts_not_written(self):
        queue_file = _make_temp_file("test_actions.jsonl")
        addon = RecordingAddon(
            recording_id="rec_001",
            queue_file=queue_file,
            ignore_hosts=["127.0.0.1"],
        )

        mock_flow = MagicMock()
        mock_flow.request.url = "http://127.0.0.1:8765/ws"
        mock_flow.request.host = "127.0.0.1"
        mock_flow.response.status_code = 200
        mock_flow.response.content = b""
        mock_flow.response.headers = {}

        addon.response(mock_flow)

        assert not queue_file.exists()


def test_start_rolls_back_system_proxy_when_enable_fails():
    recorder = ProxyRecorder(host="127.0.0.1", port=8080)
    queue_file = _make_temp_file("actions.jsonl")

    class ImmediateThread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            self._target()

        def join(self, timeout=None):
            return None

    class FakeLoop:
        def run_until_complete(self, coro):
            return asyncio.run(coro)

        def call_soon_threadsafe(self, callback):
            callback()

    class FakeDumpMaster:
        def __init__(self, *args, **kwargs):
            self.addons = SimpleNamespace(add=MagicMock())

        async def run(self):
            return None

        def shutdown(self):
            return None

    with patch("src.recording.proxy_recorder.MITMPROXY_AVAILABLE", True):
        with patch("src.recording.proxy_recorder.options") as mock_options:
            mock_options.Options.return_value = object()
            with patch("src.recording.proxy_recorder.DumpMaster", FakeDumpMaster):
                with patch(
                    "src.recording.proxy_recorder.asyncio.new_event_loop",
                    return_value=FakeLoop(),
                ):
                    with patch("src.recording.proxy_recorder.asyncio.set_event_loop"):
                        with patch(
                            "src.recording.proxy_recorder.threading.Thread",
                            ImmediateThread,
                        ):
                            with patch.object(recorder, "_shutdown_master") as mock_shutdown:
                                with patch.object(
                                    recorder, "_reset_runtime_state"
                                ) as mock_reset:
                                    with patch.object(
                                        recorder._system_proxy,
                                        "enable",
                                        side_effect=OSError("refresh failed"),
                                    ):
                                        with patch.object(
                                            recorder._system_proxy, "disable"
                                        ) as mock_disable:
                                            result = recorder.start(
                                                "rec_001",
                                                queue_file,
                                            )

    assert result is False
    mock_disable.assert_called_once_with()
    mock_shutdown.assert_called_once_with()
    mock_reset.assert_called_once_with()
