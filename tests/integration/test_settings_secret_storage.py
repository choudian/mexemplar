from __future__ import annotations

import keyring
import pytest
from keyring.backend import KeyringBackend
from keyring.errors import PasswordDeleteError

from src.business.services.settings_service import SettingsService
from src.data.sqlalchemy_manager import get_sqlalchemy_manager
from src.data.unified_config import UnifiedConfigManager


class InMemoryKeyring(KeyringBackend):
    priority = 1

    def __init__(self):
        self.values: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.values.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.values[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        if (service, username) not in self.values:
            raise PasswordDeleteError("missing")
        del self.values[(service, username)]


@pytest.fixture()
def memory_keyring(monkeypatch):
    original = keyring.get_keyring()
    backend = InMemoryKeyring()
    service_name = "Mexemplar-Test-Settings"
    monkeypatch.setenv("EXEMPLAR_KEYRING_SERVICE_NAME", service_name)
    keyring.set_keyring(backend)
    try:
        yield backend, service_name
    finally:
        keyring.set_keyring(original)


def test_settings_secret_write_masks_response_and_avoids_plaintext_db(tmp_path, memory_keyring):
    backend, service_name = memory_keyring
    config = UnifiedConfigManager(config_path=str(tmp_path / "config.json"))
    service = SettingsService(config)

    response = service.write_secret("ai.api_key", "sk-secret-value")

    assert response == {"secretKey": "ai.api_key", "present": True, "masked": "••••••••"}
    assert "sk-secret-value" not in str(response)
    assert backend.get_password(service_name, "anthropic_api_key") == "sk-secret-value"
    assert get_sqlalchemy_manager().get_setting("ai.api_key", default="") == ""

    values = service.get_values()
    assert values["secrets"]["ai.api_key"]["present"] is True
    assert "sk-secret-value" not in str(values)


def test_settings_secret_delete_clears_keyring_without_exposing_secret(tmp_path, memory_keyring):
    backend, service_name = memory_keyring
    backend.set_password(service_name, "anthropic_api_key", "sk-delete-me")
    config = UnifiedConfigManager(config_path=str(tmp_path / "config.json"))
    service = SettingsService(config)

    response = service.delete_secret("ai.api_key")

    assert response == {"secretKey": "ai.api_key", "present": False, "masked": ""}
    assert backend.get_password(service_name, "anthropic_api_key") is None
    assert "sk-delete-me" not in str(response)


def test_brave_secret_write_masks_response_and_avoids_plaintext_db(tmp_path, memory_keyring):
    backend, service_name = memory_keyring
    config = UnifiedConfigManager(config_path=str(tmp_path / "config.json"))
    service = SettingsService(config)

    response = service.write_secret("web.brave_api_key", "brave-secret-value")

    assert response == {"secretKey": "web.brave_api_key", "present": True, "masked": "••••••••"}
    assert "brave-secret-value" not in str(response)
    assert backend.get_password(service_name, "brave_search_api_key") == "brave-secret-value"
    assert get_sqlalchemy_manager().get_setting("web.brave_api_key", default="") == ""

    values = service.get_values()
    assert values["secrets"]["web.brave_api_key"]["present"] is True
    assert "brave-secret-value" not in str(values)


def test_brave_secret_delete_clears_keyring_without_exposing_secret(tmp_path, memory_keyring):
    backend, service_name = memory_keyring
    backend.set_password(service_name, "brave_search_api_key", "brave-delete-me")
    config = UnifiedConfigManager(config_path=str(tmp_path / "config.json"))
    service = SettingsService(config)

    response = service.delete_secret("web.brave_api_key")

    assert response == {"secretKey": "web.brave_api_key", "present": False, "masked": ""}
    assert backend.get_password(service_name, "brave_search_api_key") is None
    assert "brave-delete-me" not in str(response)


def test_tool_output_summary_secret_is_keyring_only(tmp_path, memory_keyring):
    backend, service_name = memory_keyring
    config = UnifiedConfigManager(config_path=str(tmp_path / "config.json"))
    service = SettingsService(config)

    response = service.write_secret(
        "agent_tools.output.semantic_summary.api_key",
        "sk-summary-only",
    )

    assert response["present"] is True
    assert backend.get_password(service_name, "tool_output_summary_api_key") == "sk-summary-only"
    assert (
        get_sqlalchemy_manager().get_setting(
            "agent_tools.output.semantic_summary.api_key",
            default="",
        )
        == ""
    )
    assert "sk-summary-only" not in str(service.get_values())

    service.delete_secret("agent_tools.output.semantic_summary.api_key")
    assert backend.get_password(service_name, "tool_output_summary_api_key") is None
