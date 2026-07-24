"""The packaged webview's origin must pass CORS (regression for the connect bug).

Dev worked, every packaged install failed with "连不上后端": the sidecar CORS
allowlist covered the dev origin (http://127.0.0.1:1420) but not the packaged
Windows webview origin (http://tauri.localhost). A raw socket succeeded because
it does not go through CORS; the webview's fetch did.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.desktop_api.app import SESSION_HEADER, create_app


@pytest.fixture
def client():
    return TestClient(create_app("test-token"))


def _preflight(client, origin):
    return client.options(
        "/api/health",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": SESSION_HEADER,
        },
    )


@pytest.mark.parametrize(
    "origin",
    [
        "http://tauri.localhost",   # packaged Windows — the one that was missing
        "https://tauri.localhost",  # packaged Windows with useHttpsScheme
        "tauri://localhost",        # packaged macOS / Linux
        "http://127.0.0.1:1420",    # dev (devUrl)
        "http://localhost:5173",    # dev, alternate host
    ],
)
def test_webview_origins_pass_preflight(client, origin):
    response = _preflight(client, origin)

    assert response.status_code in (200, 204)
    assert response.headers.get("access-control-allow-origin") == origin


def test_custom_session_header_is_allowed_through_preflight(client):
    # The session header is what makes every request non-simple and forces a
    # preflight in the first place.
    response = _preflight(client, "http://tauri.localhost")

    allowed = response.headers.get("access-control-allow-headers", "").lower()
    assert SESSION_HEADER.lower() in allowed


def test_a_foreign_origin_is_still_rejected(client):
    # The fix must not turn into "allow everything".
    response = _preflight(client, "http://evil.example.com")

    assert response.headers.get("access-control-allow-origin") != "http://evil.example.com"
