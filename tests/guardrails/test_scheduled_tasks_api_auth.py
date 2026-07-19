"""T026: guard — ``/api/scheduled-tasks`` 无 token 返 401。

CC-007：所有 ``/api/scheduled-tasks`` endpoint 都走应用级 ``X-Mexemplar-Session`` 中间件鉴权；
无 token / 错 token → 401，不进入业务逻辑。
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from src.desktop_api.app import SESSION_HEADER, create_app

VALID_TOKEN = "valid-test-token"


def _client_without_token() -> TestClient:
    return TestClient(create_app(VALID_TOKEN))


def _client_with_wrong_token() -> TestClient:
    return TestClient(create_app(VALID_TOKEN), headers={SESSION_HEADER: "wrong-token"})


PROTECTED_PATHS = [
    ("/api/scheduled-tasks", "GET"),
    ("/api/scheduled-tasks/sch_x", "GET"),
    ("/api/scheduled-tasks/sch_x", "PATCH"),
    ("/api/scheduled-tasks/sch_x/fire-now", "POST"),
    ("/api/scheduled-tasks/sch_x", "DELETE"),
    ("/api/scheduled-tasks/sch_x/runs", "GET"),
    ("/api/scheduled-tasks/sch_x/runs/schr_y/takeover", "POST"),
    ("/api/scheduled-tasks/confirmations/scf_x/decision", "POST"),
    ("/api/scheduled-tasks/confirmations/pending", "GET"),
]


def test_no_token_returns_401():
    client = _client_without_token()
    for path, method in PROTECTED_PATHS:
        resp = client.request(method, path)
        assert resp.status_code == 401, f"{method} {path} returned {resp.status_code}, expected 401"
        assert "test-token" not in resp.text  # token 不进响应正文


def test_wrong_token_returns_401():
    client = _client_with_wrong_token()
    for path, method in PROTECTED_PATHS:
        resp = client.request(method, path)
        assert resp.status_code == 401, f"{method} {path} returned {resp.status_code}, expected 401"
