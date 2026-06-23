from __future__ import annotations

import pytest

from src.business.services.settings_actions_service import SettingsActionsService
from src.business.services.settings_service import SettingsService, SettingsValidationError
from src.desktop_api.routers import settings as settings_router


class FakeSettingsService:
    def __init__(self):
        self.updated = None
        self.secret_written = None
        self.secret_deleted = None
        self.secret_writes = []
        self.secret_deletes = []

    def get_schema(self):
        return {
            "sections": [
                {
                    "id": "ai",
                    "label": "AI",
                    "items": [
                        {
                            "key": "ai.model",
                            "label": "主模型",
                            "section": "ai",
                            "valueKind": "string",
                            "validationRules": {"required": True},
                            "status": "available",
                        }
                    ],
                    "actions": [
                        {
                            "key": "test_ai_connection",
                            "label": "测试 AI 连接",
                            "section": "ai",
                            "valueKind": "action",
                            "status": "available",
                        }
                    ],
                }
            ]
        }

    def get_values(self):
        return {
            "values": {"ai.model": "claude-sonnet-4-20250514"},
            "secrets": {
                "ai.api_key": {"secretKey": "ai.api_key", "present": False, "masked": ""},
                "web.brave_api_key": {
                    "secretKey": "web.brave_api_key",
                    "present": False,
                    "masked": "",
                },
            },
            "status": {"ai.api_key": "missing_secret", "web.brave_api_key": "missing_secret"},
        }

    def update_values(self, values):
        if values.get("ai.timeout") == 0:
            raise SettingsValidationError("ai.timeout", "不能小于 1。")
        self.updated = values
        return {
            "values": values,
            "secrets": {
                "ai.api_key": {"secretKey": "ai.api_key", "present": False, "masked": ""},
                "web.brave_api_key": {
                    "secretKey": "web.brave_api_key",
                    "present": False,
                    "masked": "",
                },
            },
            "status": {},
        }

    def write_secret(self, secret_key, value):
        self.secret_written = (secret_key, value)
        self.secret_writes.append((secret_key, value))
        return {"secretKey": secret_key, "present": True, "masked": "••••••••"}

    def delete_secret(self, secret_key):
        self.secret_deleted = secret_key
        self.secret_deletes.append(secret_key)
        return {"secretKey": secret_key, "present": False, "masked": ""}


class FakeSettingsActionsService:
    def run_action(self, action_name, *, confirmed=False):
        return {
            "actionName": action_name,
            "status": "completed",
            "message": "done",
            "details": {"path": "data", "confirmed": confirmed},
        }


def test_settings_schema_values_update_secret_and_action_endpoints(desktop_api_client):
    service = FakeSettingsService()
    desktop_api_client.app.dependency_overrides[settings_router.get_settings_service] = (
        lambda: service
    )
    desktop_api_client.app.dependency_overrides[settings_router.get_settings_actions_service] = (
        lambda: FakeSettingsActionsService()
    )
    try:
        schema = desktop_api_client.get("/api/settings/schema")
        values = desktop_api_client.get("/api/settings/values")
        updated = desktop_api_client.patch(
            "/api/settings/values", json={"values": {"ai.model": "gpt-5.1"}}
        )
        secret = desktop_api_client.post(
            "/api/settings/secrets/ai.api_key", json={"value": "sk-test-secret"}
        )
        brave_secret = desktop_api_client.post(
            "/api/settings/secrets/web.brave_api_key", json={"value": "brave-test-secret"}
        )
        deleted = desktop_api_client.delete("/api/settings/secrets/ai.api_key")
        brave_deleted = desktop_api_client.delete("/api/settings/secrets/web.brave_api_key")
        action = desktop_api_client.post("/api/settings/actions/test_ai_connection")
    finally:
        desktop_api_client.app.dependency_overrides.clear()

    assert schema.status_code == 200
    assert schema.json()["sections"][0]["items"][0]["key"] == "ai.model"
    assert values.status_code == 200
    assert values.json()["secrets"]["ai.api_key"]["present"] is False
    assert values.json()["secrets"]["web.brave_api_key"]["present"] is False
    assert updated.status_code == 200
    assert service.updated == {"ai.model": "gpt-5.1"}
    assert secret.status_code == 200
    assert "sk-test-secret" not in secret.text
    assert brave_secret.status_code == 200
    assert "brave-test-secret" not in brave_secret.text
    assert service.secret_writes == [
        ("ai.api_key", "sk-test-secret"),
        ("web.brave_api_key", "brave-test-secret"),
    ]
    assert deleted.status_code == 200
    assert brave_deleted.status_code == 200
    assert service.secret_deletes == ["ai.api_key", "web.brave_api_key"]
    assert action.status_code == 200
    assert action.json()["actionName"] == "test_ai_connection"


def test_settings_validation_errors_return_stable_422(desktop_api_client):
    service = FakeSettingsService()
    desktop_api_client.app.dependency_overrides[settings_router.get_settings_service] = (
        lambda: service
    )
    try:
        response = desktop_api_client.patch(
            "/api/settings/values", json={"values": {"ai.timeout": 0}}
        )
    finally:
        desktop_api_client.app.dependency_overrides.clear()

    assert response.status_code == 422
    assert response.json()["detail"]["key"] == "ai.timeout"


class FakeConfig:
    def __init__(self):
        self.writes = {}

    def get(self, key, default=None):
        values = {
            "ai.provider": "anthropic",
            "ai.model": "claude-sonnet-4-20250514",
            "web.search_backend": "auto",
            "version": "0.1.0",
        }
        values.update(self.writes)
        return values.get(key, default)

    def set(self, key, value, persist="database", value_type="string"):
        self.writes[key] = value

    def get_ai_api_key(self):
        return None

    def get_ai_vision_api_key(self):
        return None

    def get_web_brave_api_key(self):
        return None

    def get_tool_output_summary_api_key(self):
        return None


def test_settings_real_actions_create_artifacts_and_report_business_errors(
    desktop_api_client, tmp_path
):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "mexemplar.db").write_text("db", encoding="utf-8")
    service = SettingsActionsService(config=FakeConfig(), data_dir=data_dir)
    desktop_api_client.app.dependency_overrides[settings_router.get_settings_actions_service] = (
        lambda: service
    )
    try:
        backup = desktop_api_client.post("/api/settings/actions/backup_data")
        export = desktop_api_client.post("/api/settings/actions/export_all_data")
        missing_key = desktop_api_client.post("/api/settings/actions/test_ai_connection")
        updates = desktop_api_client.post("/api/settings/actions/check_updates")
    finally:
        desktop_api_client.app.dependency_overrides.clear()

    assert backup.status_code == 200
    assert backup.json()["status"] == "completed"
    assert (data_dir / "backups").exists()
    assert export.status_code == 200
    assert export.json()["status"] == "completed"
    assert missing_key.json()["details"]["code"] == "missing_secret"
    assert updates.json()["status"] == "unavailable"


def test_settings_service_validates_web_search_backend() -> None:
    service = SettingsService(config=FakeConfig())

    service.update_values({"web.search_backend": "ddg-html"})
    assert service._config.writes["web.search_backend"] == "ddg-html"

    with pytest.raises(SettingsValidationError):
        service.update_values({"web.search_backend": "unknown"})


def test_tool_output_settings_schema_exposes_advanced_fields():
    schema = SettingsService().get_schema()
    section = next(item for item in schema["sections"] if item["id"] == "tool_output")

    assert section["label"] == "工具输出"
    assert any(
        item["key"] == "agent_tools.output.semantic_summary.model" for item in section["items"]
    )
    assert any(item["advanced"] is True for item in section["items"])
    assert section["actions"][0]["key"] == "test_tool_output_summary_connection"


def test_tool_output_settings_status_marks_invalid_compatible_endpoint():
    config = FakeConfig()
    config.writes.update(
        {
            "agent_tools.output.semantic_summary.enabled": True,
            "agent_tools.output.semantic_summary.provider": "openai-compatible",
            "agent_tools.output.semantic_summary.model": "summary-model",
            "agent_tools.output.semantic_summary.base_url": "not-a-url",
        }
    )

    status = SettingsService(config=config).get_values()["status"]

    assert status["agent_tools.output.semantic_summary.model"] == "invalid"


class SummaryActionConfig:
    provider = "openai"
    base_url = ""

    def get_agent_tools_output_semantic_summary_provider(self):
        return self.provider

    def get_agent_tools_output_semantic_summary_model(self):
        return "summary-model"

    def get_agent_tools_output_semantic_summary_base_url(self):
        return self.base_url

    def get_agent_tools_output_semantic_summary_enabled(self):
        return True

    def get_agent_tools_output_semantic_summary_temperature(self):
        return 0.2

    def get_agent_tools_output_semantic_summary_max_input_chars(self):
        return 120000

    def get_agent_tools_output_semantic_summary_chunk_chars(self):
        return 20000

    def get_agent_tools_output_semantic_summary_max_map_chunks(self):
        return 6

    def get_agent_tools_output_semantic_summary_map_concurrency(self):
        return 3

    def get_agent_tools_output_semantic_summary_total_timeout_seconds(self):
        return 12

    def get_agent_tools_output_semantic_summary_map_max_tokens(self):
        return 500

    def get_agent_tools_output_semantic_summary_reduce_max_tokens(self):
        return 900

    def get_agent_tools_output_semantic_summary_summary_max_chars(self):
        return 4000

    def get_tool_output_summary_api_key(self):
        return "sk-summary"


def test_tool_output_connection_action_returns_only_status_provider_and_model(monkeypatch):
    monkeypatch.setattr(
        "src.business.agents.tools.semantic_summary.test_semantic_summary_connection",
        lambda **_kwargs: (True, "success"),
    )
    result = SettingsActionsService(config=SummaryActionConfig()).run_action(
        "test_tool_output_summary_connection"
    )

    assert result["status"] == "completed"
    assert result["details"] == {"provider": "openai", "model": "summary-model"}
    assert "response" not in result["details"]


def test_tool_output_connection_rejects_invalid_compatible_endpoint_without_call(monkeypatch):
    config = SummaryActionConfig()
    config.provider = "openai-compatible"
    config.base_url = "not-a-url"
    calls = []
    monkeypatch.setattr(
        "src.business.agents.tools.semantic_summary._invoke_with_deadline",
        lambda **kwargs: calls.append(kwargs),
    )

    result = SettingsActionsService(config=config).run_action("test_tool_output_summary_connection")

    assert result["status"] == "failed"
    assert result["message"] == "摘要模型 API 地址格式无效。"
    assert result["details"]["code"] == "invalid_base_url"
    assert calls == []
