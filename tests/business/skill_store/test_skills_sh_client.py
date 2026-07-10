from __future__ import annotations

import pytest

from src.business.skill_store.skills_sh_client import (
    AUTH_INVALID_MESSAGE,
    AUTH_REQUIRED_MESSAGE,
    SkillsShAuthenticationError,
    SkillsShClient,
)


class _Response:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _Http:
    def __init__(self, response: _Response):
        self.response = response
        self.calls = []

    def get(self, url, *, params=None, headers=None):
        self.calls.append({"url": url, "params": params, "headers": headers})
        return self.response


def test_skills_sh_client_sends_bearer_token_and_parses_contents_field():
    http = _Http(
        _Response(
            200,
            {
                "id": "acme/api-test-skill",
                "name": "api-test-skill",
                "source": "acme",
                "url": "https://skills.sh/acme/api-test-skill",
                "files": [{"path": "SKILL.md", "contents": "body"}],
            },
        )
    )
    client = SkillsShClient(http_client=http, api_key_provider=lambda: "oidc-token")

    detail = client.detail("acme/api-test-skill")

    assert detail.files == [{"path": "SKILL.md", "content": "body"}]
    assert http.calls[0]["headers"] == {"Authorization": "Bearer oidc-token"}


def test_skills_sh_client_rejects_missing_token_without_network_call():
    http = _Http(_Response(200, {}))
    client = SkillsShClient(http_client=http, api_key_provider=lambda: None)

    with pytest.raises(SkillsShAuthenticationError) as exc_info:
        client.search("anything")

    assert str(exc_info.value) == AUTH_REQUIRED_MESSAGE
    assert http.calls == []


def test_skills_sh_client_reports_invalid_or_expired_token_without_leaking_token():
    http = _Http(_Response(401, {"error": "authentication_required"}))
    client = SkillsShClient(http_client=http, api_key_provider=lambda: "expired-token")

    with pytest.raises(SkillsShAuthenticationError) as exc_info:
        client.curated()

    assert str(exc_info.value) == AUTH_INVALID_MESSAGE
    assert "expired-token" not in str(exc_info.value)
