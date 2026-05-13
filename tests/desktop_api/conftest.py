from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.desktop_api.app import SESSION_HEADER, create_app


@pytest.fixture()
def desktop_api_token() -> str:
    return "test-session-token"


@pytest.fixture()
def desktop_api_client(desktop_api_token: str) -> TestClient:
    return TestClient(
        create_app(desktop_api_token),
        headers={SESSION_HEADER: desktop_api_token},
    )
