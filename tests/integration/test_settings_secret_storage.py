from __future__ import annotations

from src.business.services.settings_service import SettingsService
from src.data.sqlalchemy_manager import get_sqlalchemy_manager
from src.data.unified_config import UnifiedConfigManager


def _service(tmp_path) -> SettingsService:
    return SettingsService(UnifiedConfigManager(config_path=str(tmp_path / "config.json")))


def test_settings_secret_write_masks_response_and_persists_unified_config(tmp_path):
    service = _service(tmp_path)

    response = service.write_secret("ai.api_key", "sk-secret-value")

    assert response == {
        "secretKey": "ai.api_key",
        "present": True,
        "masked": "••••••••",
    }
    assert "sk-secret-value" not in str(response)
    assert get_sqlalchemy_manager().get_setting("ai.api_key") == "sk-secret-value"
    assert "sk-secret-value" not in str(service.get_values())

    service.delete_secret("ai.api_key")


def test_settings_secret_delete_clears_unified_config_without_exposing_secret(tmp_path):
    service = _service(tmp_path)
    service.write_secret("ai.api_key", "sk-delete-me")

    response = service.delete_secret("ai.api_key")

    assert response == {
        "secretKey": "ai.api_key",
        "present": False,
        "masked": "",
    }
    assert get_sqlalchemy_manager().get_setting("ai.api_key") == ""
    assert "sk-delete-me" not in str(response)


def test_brave_secret_uses_unified_config_and_masked_response(tmp_path):
    service = _service(tmp_path)

    response = service.write_secret("web.brave_api_key", "brave-secret-value")

    assert response["present"] is True
    assert response["masked"] == "••••••••"
    assert get_sqlalchemy_manager().get_setting("web.brave_api_key") == "brave-secret-value"
    assert "brave-secret-value" not in str(service.get_values())

    service.delete_secret("web.brave_api_key")
    assert get_sqlalchemy_manager().get_setting("web.brave_api_key") == ""


def test_tool_output_summary_secret_uses_unified_config(tmp_path):
    service = _service(tmp_path)

    response = service.write_secret(
        "agent_tools.output.semantic_summary.api_key",
        "sk-summary-only",
    )

    assert response["present"] is True
    assert (
        get_sqlalchemy_manager().get_setting("agent_tools.output.semantic_summary.api_key")
        == "sk-summary-only"
    )
    assert "sk-summary-only" not in str(service.get_values())

    service.delete_secret("agent_tools.output.semantic_summary.api_key")
    assert get_sqlalchemy_manager().get_setting("agent_tools.output.semantic_summary.api_key") == ""
