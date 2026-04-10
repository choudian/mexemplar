import asyncio
import json
from unittest.mock import AsyncMock

from src.recording.websocket_server import WebSocketServer


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
