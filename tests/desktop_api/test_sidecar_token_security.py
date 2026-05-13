from __future__ import annotations

import logging

from fastapi.testclient import TestClient

from src.desktop_api.app import SESSION_HEADER, create_app


def test_sidecar_token_is_required_but_not_returned_or_logged(caplog) -> None:
    token = "secret-runtime-token"
    caplog.set_level(logging.INFO)
    client = TestClient(create_app(token))

    response = client.get("/api/health")

    assert response.status_code == 401
    assert token not in response.text
    assert token not in "\n".join(record.getMessage() for record in caplog.records)


def test_sidecar_token_is_header_scoped_not_persisted_to_openapi() -> None:
    token = "another-secret-runtime-token"
    client = TestClient(create_app(token), headers={SESSION_HEADER: token})

    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert token not in response.text

    health_response = client.get("/api/health")

    assert health_response.status_code == 200
    assert token not in health_response.text
