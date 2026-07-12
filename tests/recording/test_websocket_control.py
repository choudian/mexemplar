import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

from src.recording.websocket_server import WebSocketServer


def test_websocket_server_keeps_explicit_port_zero_instead_of_using_configured_port():
    config = MagicMock()
    config.get_websocket_host.return_value = "127.0.0.1"
    config.get_websocket_port.return_value = 8765

    with patch("src.recording.websocket_server.get_unified_config", return_value=config):
        server = WebSocketServer(host="0.0.0.0", port=0)

    assert server.host == "0.0.0.0"
    assert server.port == 0


def test_websocket_start_passes_configured_max_size_to_server():
    class StubServeContext:
        def __init__(self, entered):
            self._entered = entered

        async def __aenter__(self):
            self._entered.set()
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    async def run_test():
        entered = asyncio.Event()
        config = MagicMock()
        config.get_websocket_max_message_size.return_value = 12_345_678
        serve_mock = MagicMock(return_value=StubServeContext(entered))

        with patch("src.recording.websocket_server.get_unified_config", return_value=config):
            with patch("src.recording.websocket_server.serve", serve_mock):
                server = WebSocketServer(host="127.0.0.1", port=9999)
                task = asyncio.create_task(server.start())
                await asyncio.wait_for(entered.wait(), timeout=1)
                await server.stop()
                await task

        serve_mock.assert_called_once_with(
            server.handle_client,
            "127.0.0.1",
            9999,
            max_size=12_345_678,
        )

    asyncio.run(run_test())


def test_recording_control_routes_to_handler():
    server = WebSocketServer(host="127.0.0.1", port=9999)
    received = []

    def handler(data, websocket):
        del websocket
        received.append(data)

    server.set_control_handler(handler)

    mock_ws = AsyncMock()
    mock_ws.remote_address = ("127.0.0.1", 12345)

    asyncio.run(server.process_message({"type": "recording_control", "action": "start"}, mock_ws))

    assert len(received) == 1
    assert received[0]["action"] == "start"


def test_recording_control_without_handler_replies_error():
    server = WebSocketServer(host="127.0.0.1", port=9999)
    mock_ws = AsyncMock()
    mock_ws.remote_address = ("127.0.0.1", 12345)

    asyncio.run(server.process_message({"type": "recording_control", "action": "start"}, mock_ws))

    mock_ws.send.assert_called_once()
    reply = json.loads(mock_ws.send.call_args[0][0])
    assert reply["type"] == "recording_control_reply"
    assert reply["status"] == "error"
    assert "未注册" in reply["error"]


def test_recording_control_unknown_action_replies_to_handler():
    server = WebSocketServer(host="127.0.0.1", port=9999)
    received = []
    server.set_control_handler(lambda data, ws: received.append((data, ws)))

    mock_ws = AsyncMock()
    mock_ws.remote_address = ("127.0.0.1", 12345)

    asyncio.run(
        server.process_message({"type": "recording_control", "action": "unknown_action"}, mock_ws)
    )

    assert len(received) == 1
    assert received[0][0]["action"] == "unknown_action"


def test_client_hello_registers_metadata_for_targeted_lookup():
    server = WebSocketServer(host="127.0.0.1", port=9999)
    mock_ws = AsyncMock()
    mock_ws.remote_address = ("127.0.0.1", 12345)
    server.clients.add(mock_ws)
    server._client_connected_at[mock_ws] = 1.0
    server._client_metadata[mock_ws] = {}

    asyncio.run(
        server.process_message(
            {
                "type": "client_hello",
                "metadata": {"launch_token": "launch-1", "recording_id": "rec-1"},
            },
            mock_ws,
        )
    )

    assert server.get_client_by_metadata({"launch_token": "launch-1"}) is mock_ws
