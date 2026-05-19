from __future__ import annotations

from fastapi.testclient import TestClient

from src.desktop_api.app import SESSION_HEADER, create_app
from src.desktop_api.events import event_queue


def _read_sse_event(response) -> str:
    lines: list[str] = []
    for line in response.iter_lines():
        lines.append(line)
        if line == "":
            break
    return "\n".join(lines)


def test_desktop_api_requires_runtime_token() -> None:
    app = create_app("expected-token")
    client = TestClient(app)

    response = client.get("/api/health")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "desktop_api_unauthorized"


def test_desktop_api_registers_core_routes(desktop_api_client: TestClient) -> None:
    response = desktop_api_client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    for path in [
        "/api/health",
        "/api/bootstrap",
        "/api/events",
        "/api/assistant",
        "/api/teaching",
        "/api/teaching/trial-preview/{request_id}/decision",
        "/api/skills",
        "/api/compositions",
        "/api/settings",
    ]:
        assert path in paths


def test_authorized_request_uses_session_header() -> None:
    client = TestClient(
        create_app("expected-token"),
        headers={SESSION_HEADER: "expected-token"},
    )

    response = client.get("/api/health")

    assert response.status_code == 200


def test_cors_allows_vite_loopback_origin_with_session_header() -> None:
    client = TestClient(create_app("expected-token"))

    response = client.options(
        "/api/health",
        headers={
            "Origin": "http://127.0.0.1:1420",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": SESSION_HEADER,
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:1420"


def test_events_endpoint_replays_query_cursor(monkeypatch) -> None:
    event_queue.reset_for_tests()
    token = "expected-token"
    client = TestClient(create_app(token), headers={SESSION_HEADER: token})
    first = event_queue.publish_nowait("settings.changed", {"reason": "settings_invalidated", "keys": ["first"]})
    second = event_queue.publish_nowait("settings.changed", {"reason": "settings_invalidated", "keys": ["second"]})
    captured: dict[str, object] = {}

    async def finite_stream(*, last_seen_sequence, event_session_id, force_resync_reason):
        captured["last_seen_sequence"] = last_seen_sequence
        captured["event_session_id"] = event_session_id
        captured["force_resync_reason"] = force_resync_reason
        yield second

    monkeypatch.setattr(event_queue, "stream", finite_stream)

    with client.stream(
        "GET",
        f"/api/events?lastSeenSequence={first.sequence}&eventSessionId={first.sessionId}",
    ) as response:
        event = _read_sse_event(response)

    assert response.status_code == 200
    assert f"id: {second.sessionId}:{second.sequence}" in event
    assert "event: settings.changed" in event
    assert '"keys":["second"]' in event
    assert captured == {
        "last_seen_sequence": first.sequence,
        "event_session_id": first.sessionId,
        "force_resync_reason": None,
    }


def test_events_endpoint_replays_last_event_id_cursor(monkeypatch) -> None:
    event_queue.reset_for_tests()
    token = "expected-token"
    client = TestClient(create_app(token), headers={SESSION_HEADER: token})
    first = event_queue.publish_nowait("settings.changed", {"reason": "settings_invalidated", "keys": ["first"]})
    second = event_queue.publish_nowait("settings.changed", {"reason": "settings_invalidated", "keys": ["second"]})
    captured: dict[str, object] = {}

    async def finite_stream(*, last_seen_sequence, event_session_id, force_resync_reason):
        captured["last_seen_sequence"] = last_seen_sequence
        captured["event_session_id"] = event_session_id
        captured["force_resync_reason"] = force_resync_reason
        yield second

    monkeypatch.setattr(event_queue, "stream", finite_stream)

    with client.stream(
        "GET",
        "/api/events",
        headers={SESSION_HEADER: token, "Last-Event-ID": f"{first.sessionId}:{first.sequence}"},
    ) as response:
        event = _read_sse_event(response)

    assert response.status_code == 200
    assert f"id: {second.sessionId}:{second.sequence}" in event
    assert "event: settings.changed" in event
    assert captured == {
        "last_seen_sequence": first.sequence,
        "event_session_id": first.sessionId,
        "force_resync_reason": None,
    }


def test_events_endpoint_invalid_cursor_requests_resync() -> None:
    event_queue.reset_for_tests()
    token = "expected-token"
    client = TestClient(create_app(token), headers={SESSION_HEADER: token})

    with client.stream("GET", "/api/events?lastSeenSequence=bad") as response:
        event = _read_sse_event(response)

    assert response.status_code == 200
    assert "event: backend.resync_required" in event
    assert '"reason":"invalid_cursor"' in event
