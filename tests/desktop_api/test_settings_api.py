from __future__ import annotations

from src.business.services.settings_actions_service import SettingsActionsService
from src.business.services.settings_service import SettingsValidationError
from src.desktop_api.routers import settings as settings_router


class FakeSettingsService:
    def __init__(self):
        self.updated = None
        self.secret_written = None
        self.secret_deleted = None

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
            "secrets": {"ai.api_key": {"secretKey": "ai.api_key", "present": False, "masked": ""}},
            "status": {"ai.api_key": "missing_secret"},
        }

    def update_values(self, values):
        if values.get("ai.timeout") == 0:
            raise SettingsValidationError("ai.timeout", "不能小于 1。")
        self.updated = values
        return {
            "values": values,
            "secrets": {"ai.api_key": {"secretKey": "ai.api_key", "present": False, "masked": ""}},
            "status": {},
        }

    def write_secret(self, secret_key, value):
        self.secret_written = (secret_key, value)
        return {"secretKey": secret_key, "present": True, "masked": "••••••••"}

    def delete_secret(self, secret_key):
        self.secret_deleted = secret_key
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
        deleted = desktop_api_client.delete("/api/settings/secrets/ai.api_key")
        action = desktop_api_client.post("/api/settings/actions/test_ai_connection")
    finally:
        desktop_api_client.app.dependency_overrides.clear()

    assert schema.status_code == 200
    assert schema.json()["sections"][0]["items"][0]["key"] == "ai.model"
    assert values.status_code == 200
    assert values.json()["secrets"]["ai.api_key"]["present"] is False
    assert updated.status_code == 200
    assert service.updated == {"ai.model": "gpt-5.1"}
    assert secret.status_code == 200
    assert "sk-test-secret" not in secret.text
    assert service.secret_written == ("ai.api_key", "sk-test-secret")
    assert deleted.status_code == 200
    assert service.secret_deleted == "ai.api_key"
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
    def get(self, key, default=None):
        values = {
            "ai.provider": "anthropic",
            "ai.model": "claude-sonnet-4-20250514",
            "version": "0.1.0",
        }
        return values.get(key, default)

    def get_ai_api_key(self):
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
