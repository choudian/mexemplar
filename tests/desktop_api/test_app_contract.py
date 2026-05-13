from __future__ import annotations

from fastapi.testclient import TestClient

from src.desktop_api.app import SESSION_HEADER, create_app


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
