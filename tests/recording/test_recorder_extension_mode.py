import asyncio
import logging
import json
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.recording.browser.playwright_recording_driver import PlaywrightRecordingDriver
from src.recording.browser_recorder import BrowserRecorder


class StubWSServer:
    async def send_to_client(self, websocket, message):
        await websocket.send(json.dumps(message))


def _make_temp_dir(name: str) -> Path:
    base = Path.cwd() / ".reports" / "pytest_tmp"
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{uuid.uuid4().hex}_{name}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def build_recorder():
    with patch.object(BrowserRecorder, "_ensure_ws_server", return_value=None):
        recorder = BrowserRecorder()
    recorder._ws_server = StubWSServer()
    return recorder


def test_browser_recorder_init_does_not_start_ws_server():
    with patch.object(BrowserRecorder, "_ensure_ws_server") as mock_ensure:
        BrowserRecorder()

    mock_ensure.assert_not_called()


def test_playwright_extension_bundle_carries_websocket_url_for_service_worker(tmp_path):
    unified_config = MagicMock()
    unified_config.get_websocket_host.return_value = "127.0.0.42"
    unified_config.get_websocket_port.return_value = 9876
    driver = PlaywrightRecordingDriver(
        storage_path=tmp_path / "recordings",
        unified_config=unified_config,
    )
    extension_source = Path(__file__).parents[2] / "src" / "recording" / "browser_extension"

    bundle_path = driver.prepare_playwright_extension_bundle(
        extension_source,
        recording_id="rec-launch-context",
    )

    try:
        launch_context_source = (bundle_path / "launch_context.js").read_text(encoding="utf-8")
        payload = launch_context_source.removeprefix(
            "self.MEXEMPLAR_LAUNCH_CONTEXT = "
        ).removesuffix(";\n")

        assert json.loads(payload) == {
            "client_kind": "playwright_background",
            "launch_token": driver.playwright_launch_token,
            "recording_id": "rec-launch-context",
            "websocket_url": "ws://127.0.0.42:9876",
        }

        background_source = (bundle_path / "background_simple.js").read_text(encoding="utf-8")
        assert "launchContext.websocket_url" in background_source
        assert "new WebSocketClient(WEBSOCKET_URL)" in background_source
    finally:
        driver.cleanup_playwright_extension_bundle()


def test_playwright_init_script_serializes_recording_config_as_json(tmp_path):
    driver = PlaywrightRecordingDriver(
        storage_path=tmp_path / "recordings",
        unified_config=MagicMock(),
    )
    recording_id = "rec'; globalThis.injected = true; //"

    script = driver._build_page_init_script(
        websocket_url="ws://127.0.0.1:8765",
        recording_id=recording_id,
        max_response_body_size=3_145_728,
    )

    payload_source = script.split("window.MEXEMPLAR_CONFIG = ", 1)[1].split(";\n", 1)[0]
    assert json.loads(payload_source) == {
        "websocketUrl": "ws://127.0.0.1:8765",
        "recordingId": recording_id,
        "maxResponseBodySize": 3_145_728,
        "version": "1.0",
    }


def test_stop_recording_runs_resource_cleanup():
    recorder = BrowserRecorder()

    def run_and_close(coro, timeout=120):
        del timeout
        coro.close()
        return {"recording_id": "rec-clean"}

    with patch.object(recorder, "_run_async", side_effect=run_and_close):
        with patch.object(recorder, "cleanup") as mock_cleanup:
            result = recorder.stop_recording()

    assert result == {"recording_id": "rec-clean"}
    mock_cleanup.assert_called_once_with(stop_active_recording=False)


def test_cleanup_closes_persister_websocket_and_event_loop():
    recorder = BrowserRecorder()
    recorder._duckdb_persister = MagicMock()
    recorder._ws_coordinator = MagicMock()
    recorder._loop_runner = MagicMock()
    recorder._playwright_driver.cleanup_user_data_dir = MagicMock()

    recorder.cleanup()

    recorder._duckdb_persister.close.assert_called_once_with()
    recorder._ws_coordinator.stop_ws_server.assert_called_once_with()
    recorder._loop_runner.stop.assert_called_once_with()
    recorder._playwright_driver.cleanup_user_data_dir.assert_called_once_with()


def test_arm_extension_triggered_mode_starts_ws_server():
    recorder = BrowserRecorder()

    with patch.object(recorder, "_ensure_ws_server") as mock_ensure:
        recorder.arm_extension_triggered_mode()

    mock_ensure.assert_called_once_with()


def test_async_start_recording_targets_ws_client_by_launch_token():
    recorder = BrowserRecorder()
    existing_client = object()
    target_client = object()
    stub_ws_server = MagicMock()
    stub_ws_server.is_running = True
    stub_ws_server.clients = {existing_client}
    recorder._ws_server = stub_ws_server

    async def fake_launch(_start_url):
        recorder._playwright_launch_token = "launch-token-1"
        return True

    with patch.object(recorder, "_ensure_ws_server", return_value=None):
        with patch.object(
            recorder, "_launch_browser_with_subprocess", AsyncMock(side_effect=fake_launch)
        ):
            with patch.object(
                recorder, "_wait_for_target_ws_client", return_value=target_client
            ) as mock_wait:
                with patch.object(recorder, "_send_start_command_via_ws") as mock_send:
                    with patch("asyncio.sleep", new=AsyncMock(return_value=None)):
                        result = asyncio.run(
                            recorder._async_start_recording(
                                start_url="https://example.com",
                                recording_id="rec-target",
                            )
                        )

    assert result is True
    mock_wait.assert_called_once_with(
        timeout=20,
        existing_clients={existing_client},
        expected_metadata={"launch_token": "launch-token-1"},
    )
    mock_send.assert_called_once_with("rec-target", websocket=target_client)
    assert recorder._playwright_ws_client is target_client


def test_wait_for_target_ws_client_requires_metadata_match():
    recorder = BrowserRecorder()
    stray_client = object()
    stub_ws_server = MagicMock()
    stub_ws_server.get_client_by_metadata.return_value = None
    stub_ws_server.get_latest_client.return_value = stray_client
    recorder._ws_server = stub_ws_server

    with patch("src.recording.browser_recorder.time.time", side_effect=[0.0, 0.0, 1.0]):
        with patch("src.recording.browser_recorder.time.sleep", return_value=None):
            result = recorder._wait_for_target_ws_client(
                timeout=0.5,
                expected_metadata={"launch_token": "launch-token-1"},
            )

    assert result is None
    stub_ws_server.get_client_by_metadata.assert_called_once_with(
        {"launch_token": "launch-token-1"},
        exclude=set(),
    )
    stub_ws_server.get_latest_client.assert_not_called()


def test_launch_browser_uses_generated_extension_bundle():
    temp_root = _make_temp_dir("playwright_bundle")
    with patch.object(BrowserRecorder, "_ensure_ws_server", return_value=None):
        recorder = BrowserRecorder(storage_path=temp_root / "recordings")

    bundle_path = temp_root / "generated_bundle"
    bundle_path.mkdir(parents=True, exist_ok=True)
    launch_persistent_context = AsyncMock(side_effect=RuntimeError("launch failed"))

    class FakeAsyncPlaywrightContext:
        async def __aenter__(self):
            return SimpleNamespace(
                chromium=SimpleNamespace(launch_persistent_context=launch_persistent_context)
            )

        async def __aexit__(self, exc_type, exc, tb):
            return False

    with patch("src.recording.browser_recorder.PLAYWRIGHT_AVAILABLE", True):
        with patch(
            "src.recording.browser_recorder.async_playwright",
            return_value=FakeAsyncPlaywrightContext(),
        ):
            with patch.object(
                recorder,
                "_prepare_playwright_extension_bundle",
                return_value=bundle_path,
            ):
                result = asyncio.run(recorder._launch_browser_with_subprocess())

    assert result is False
    launch_args = launch_persistent_context.call_args.kwargs["args"]
    assert f"--disable-extensions-except={bundle_path.as_posix()}" in launch_args
    assert f"--load-extension={bundle_path.as_posix()}" in launch_args


def test_classify_extension_targets_ignores_non_extension_service_workers():
    targets = [
        {"type": "service_worker", "url": "https://example.com/sw.js"},
        {"type": "service_worker", "url": "chrome-extension://abc/background.js"},
        {"type": "page", "url": "chrome-extension://abc/popup.html"},
        {"type": "page", "url": "about:blank"},
        {"type": "service_worker", "url": None},
    ]

    classified = BrowserRecorder._classify_extension_targets(targets)

    assert len(classified["extension_targets"]) == 2
    assert len(classified["extension_service_workers"]) == 1
    assert (
        classified["extension_service_workers"][0]["url"] == "chrome-extension://abc/background.js"
    )


def test_launch_browser_warns_instead_of_error_when_extension_targets_not_visible(caplog):
    temp_root = _make_temp_dir("playwright_bundle_no_target")
    with patch("src.data.recording_repository.RecordingRepository", return_value=MagicMock()):
        with patch.object(BrowserRecorder, "_ensure_ws_server", return_value=None):
            recorder = BrowserRecorder(storage_path=temp_root / "recordings")

    bundle_path = temp_root / "generated_bundle"
    bundle_path.mkdir(parents=True, exist_ok=True)

    class FakePage:
        def __init__(self):
            self.url = "about:blank"

        async def wait_for_load_state(self, *_args, **_kwargs):
            return None

    class FakeCDPSession:
        async def send(self, method):
            assert method == "Target.getTargets"
            return {
                "targetInfos": [
                    {"type": "page", "url": "about:blank"},
                    {"type": "service_worker", "url": "https://example.com/sw.js"},
                ]
            }

        async def detach(self):
            return None

    class FakeContext:
        def __init__(self):
            self.pages = [FakePage()]
            self.background_pages = []

        async def add_init_script(self, _script):
            return None

        def on(self, *_args, **_kwargs):
            return None

        async def new_page(self):
            return FakePage()

        async def new_cdp_session(self, _page):
            return FakeCDPSession()

    launch_persistent_context = AsyncMock(return_value=FakeContext())

    class FakeAsyncPlaywrightContext:
        async def __aenter__(self):
            return SimpleNamespace(
                chromium=SimpleNamespace(launch_persistent_context=launch_persistent_context)
            )

        async def __aexit__(self, exc_type, exc, tb):
            return False

    with caplog.at_level(logging.WARNING, logger="src.recording.browser_recorder"):
        with patch("src.recording.browser_recorder.PLAYWRIGHT_AVAILABLE", True):
            with patch(
                "src.recording.browser_recorder.async_playwright",
                return_value=FakeAsyncPlaywrightContext(),
            ):
                with patch.object(
                    recorder,
                    "_prepare_playwright_extension_bundle",
                    return_value=bundle_path,
                ):
                    with patch(
                        "src.recording.browser_recorder.asyncio.sleep",
                        new=AsyncMock(return_value=None),
                    ):
                        result = asyncio.run(recorder._launch_browser_with_subprocess())

    assert result is True
    assert "启动阶段暂未确认扩展已加载" in caplog.text
    assert "⚠ 警告：未检测到扩展已加载！" not in caplog.text


def test_control_start_creates_session_and_starts_recorders():
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

    assert recorder._is_recording is True
    assert recorder._is_extension_recording is True
    mock_proxy.start.assert_called_once()
    mock_accessibility.start.assert_called_once()
    reply = json.loads(mock_ws.send.call_args[0][0])
    assert reply["status"] == "started"


def test_control_start_uses_armed_recording_id():
    recorder = build_recorder()
    mock_proxy = MagicMock()
    mock_proxy.start.return_value = True
    mock_accessibility = MagicMock()
    mock_ws = AsyncMock()

    with patch.object(recorder, "_ensure_ws_server", return_value=None):
        recorder.arm_extension_triggered_mode(recording_id="rec_expected")
    with patch.object(recorder, "_proxy_recorder", mock_proxy):
        with patch.object(recorder, "_accessibility_recorder", mock_accessibility):
            asyncio.run(
                recorder._handle_control_message(
                    {"type": "recording_control", "action": "start", "source": "extension"},
                    mock_ws,
                )
            )

    reply = json.loads(mock_ws.send.call_args[0][0])
    assert reply["status"] == "started"
    assert reply["recording_id"] == "rec_expected"
    assert recorder._recording_id == "rec_expected"


def test_control_start_replies_error_when_proxy_fails():
    recorder = build_recorder()
    mock_proxy = MagicMock()
    mock_proxy.start.return_value = False
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

    reply = json.loads(mock_ws.send.call_args[0][0])
    assert reply["status"] == "error"
    assert recorder._is_recording is False
    assert not recorder._is_extension_recording
    mock_accessibility.stop.assert_called_once()


def test_control_start_replies_error_when_playwright_active():
    recorder = build_recorder()
    recorder._is_recording = True
    recorder._active_recording_mode = "browser"
    mock_ws = AsyncMock()

    asyncio.run(
        recorder._handle_control_message(
            {"type": "recording_control", "action": "start", "source": "extension"},
            mock_ws,
        )
    )

    reply = json.loads(mock_ws.send.call_args[0][0])
    assert reply["status"] == "error"
    assert "已有录制" in reply["error"]


def test_async_start_recording_marks_startup_busy_before_launch():
    recorder = build_recorder()
    recorder._ws_server.clients = set()
    recorder._ws_server.is_running = True

    async def fake_launch(_start_url):
        mock_ws = AsyncMock()
        await recorder._handle_control_message(
            {"type": "recording_control", "action": "start", "source": "extension"},
            mock_ws,
        )
        reply = json.loads(mock_ws.send.call_args[0][0])
        assert reply["status"] == "error"
        assert "启动中" in reply["error"]
        return False

    with patch.object(recorder, "_ensure_ws_server", return_value=None):
        with patch.object(
            recorder, "_launch_browser_with_subprocess", AsyncMock(side_effect=fake_launch)
        ):
            result = asyncio.run(
                recorder._async_start_recording(
                    start_url="https://example.com",
                    recording_id="rec_busy",
                )
            )

    assert result is False
    assert recorder._recording_startup_in_progress is False
    assert recorder._recording_id is None
    assert recorder._action_queue_path is None


def test_stop_recording_raises_when_duckdb_save_fails():
    recorder = build_recorder()
    recorder._is_recording = True
    recorder._recording_id = "rec_save_failed"
    recorder._recording_start_time = 100.0
    recorder._action_queue_path, recorder._screenshot_queue_path = recorder._get_queue_paths(
        "rec_save_failed"
    )
    recorder._active_recording_mode = "browser"
    recorder._playwright_driver.cleanup_user_data_dir = MagicMock()

    with patch.object(recorder, "_send_stop_command_via_ws", return_value=None):
        with patch.object(recorder, "_wait_for_stop_drain", new=AsyncMock(return_value=None)):
            with patch.object(recorder, "_close_browser", new=AsyncMock(return_value=None)):
                with patch.object(recorder, "_cleanup_playwright_extension_bundle"):
                    with patch.object(
                        recorder,
                        "_save_to_duckdb",
                        side_effect=RuntimeError("missing packaged data"),
                    ):
                        with pytest.raises(RuntimeError, match="recording_persistence_failed"):
                            asyncio.run(recorder._async_stop_recording())

    assert recorder._recording_id is None
    assert recorder._is_recording is False


def test_control_stop_stops_recorders_and_emits_event():
    recorder = build_recorder()
    recorder._recording_id = "rec_test"
    recorder._recording_start_time = 123.0
    recorder._action_queue_path, recorder._screenshot_queue_path = recorder._get_queue_paths(
        "rec_test"
    )
    recorder._is_recording = True
    recorder._active_recording_mode = "extension_triggered"

    mock_proxy = MagicMock()
    mock_accessibility = MagicMock()
    mock_ws = AsyncMock()
    emitted = []

    with patch(
        "src.recording.browser_recorder.emit", side_effect=lambda name, **kw: emitted.append(name)
    ):
        with patch.object(recorder, "_proxy_recorder", mock_proxy):
            with patch.object(recorder, "_accessibility_recorder", mock_accessibility):
                with patch.object(recorder, "_save_to_duckdb", return_value=0):
                    asyncio.run(
                        recorder._handle_control_message(
                            {"type": "recording_control", "action": "stop", "source": "extension"},
                            mock_ws,
                        )
                    )

    mock_proxy.stop.assert_called_once()
    mock_accessibility.stop.assert_called_once()
    reply = json.loads(mock_ws.send.call_args[0][0])
    assert reply["status"] == "stopped"
    assert "recording_completed" in emitted
    assert recorder._is_recording is False
    assert not recorder._is_extension_recording


def test_control_stop_replies_before_duckdb_flush():
    recorder = build_recorder()
    recorder._recording_id = "rec_test"
    recorder._recording_start_time = 123.0
    recorder._action_queue_path, recorder._screenshot_queue_path = recorder._get_queue_paths(
        "rec_test"
    )
    recorder._is_recording = True
    recorder._active_recording_mode = "extension_triggered"

    mock_proxy = MagicMock()
    mock_accessibility = MagicMock()
    mock_ws = AsyncMock()
    call_order = []

    async def capture_reply(payload):
        reply = json.loads(payload)
        call_order.append(reply["status"])

    mock_ws.send.side_effect = capture_reply

    def save_side_effect(_end_time):
        call_order.append("save")
        return 0

    with patch("src.recording.browser_recorder.emit"):
        with patch.object(recorder, "_proxy_recorder", mock_proxy):
            with patch.object(recorder, "_accessibility_recorder", mock_accessibility):
                with patch.object(recorder, "_save_to_duckdb", side_effect=save_side_effect):
                    asyncio.run(
                        recorder._handle_control_message(
                            {"type": "recording_control", "action": "stop", "source": "extension"},
                            mock_ws,
                        )
                    )

    assert call_order[:2] == ["stopped", "save"]


def test_control_stop_replies_stopped_when_already_idle():
    recorder = build_recorder()
    recorder._active_recording_mode = "browser"
    recorder._is_recording = False
    mock_ws = AsyncMock()

    asyncio.run(
        recorder._handle_control_message(
            {"type": "recording_control", "action": "stop", "source": "extension"},
            mock_ws,
        )
    )

    reply = json.loads(mock_ws.send.call_args[0][0])
    assert reply["status"] == "stopped"


def test_control_stop_replies_error_when_playwright_active():
    recorder = build_recorder()
    recorder._active_recording_mode = "browser"
    recorder._is_recording = True
    mock_ws = AsyncMock()

    asyncio.run(
        recorder._handle_control_message(
            {"type": "recording_control", "action": "stop", "source": "extension"},
            mock_ws,
        )
    )

    reply = json.loads(mock_ws.send.call_args[0][0])
    assert reply["status"] == "error"
    assert "App 中停止" in reply["error"]
