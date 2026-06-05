from __future__ import annotations

from types import SimpleNamespace

import pytest


class FakeConfig:
    def get_ai_provider(self) -> str:
        return "anthropic"

    def get_ai_model(self) -> str:
        return "model-from-config"

    def get_ai_api_key(self) -> str:
        raise AssertionError("ordinary migration-capable getter must not be used")

    def get_ai_base_url(self):
        return None

    def get_ai_thinking_level(self) -> str:
        return "off"

    def get_ai_max_tokens(self) -> int:
        return 32000

    def get_ai_request_timeout(self) -> float:
        return 30.0

    def get(self, key: str, default=None):
        values = {
            "ai.provider": "anthropic",
            "ai.model": "model-from-config",
        }
        return values.get(key, default)


class FakeResolver:
    def __init__(self, key: str | None) -> None:
        self.key = key
        self.calls = 0

    def get_ai_api_key(self) -> str | None:
        self.calls += 1
        return self.key

    def get_ai_vision_api_key(self) -> str | None:
        return self.key


def test_real_tour_build_default_orchestrator_uses_read_only_resolver(monkeypatch) -> None:
    from src.desktop_api import orchestrator_runtime

    captured = {}

    class FakeLLM:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    class FakeOrchestrator:
        def __init__(self, *, llm_client, config):
            self.llm_client = llm_client
            self.config = config

    resolver = FakeResolver("sk-read-only")
    monkeypatch.setenv("MEXEMPLAR_REAL_GRAND_TOUR", "1")
    monkeypatch.setattr(orchestrator_runtime, "get_unified_config", lambda: FakeConfig())
    monkeypatch.setattr(orchestrator_runtime, "LangChainLLMClient", FakeLLM)
    monkeypatch.setattr(orchestrator_runtime, "AgentOrchestrator", FakeOrchestrator)

    orchestrator_runtime.build_default_orchestrator(credential_resolver=resolver)

    assert resolver.calls == 1
    assert captured["api_key"] == "sk-read-only"
    assert captured["model"] == "model-from-config"


def test_real_tour_missing_read_only_credential_fails_before_ordinary_getter(monkeypatch) -> None:
    from src.desktop_api import orchestrator_runtime

    class FakeLLM:
        def __init__(self, **kwargs):
            if not kwargs.get("api_key"):
                raise ValueError("missing real-tour credential")

    monkeypatch.setenv("MEXEMPLAR_REAL_GRAND_TOUR", "1")
    monkeypatch.setattr(orchestrator_runtime, "get_unified_config", lambda: FakeConfig())
    monkeypatch.setattr(orchestrator_runtime, "LangChainLLMClient", FakeLLM)

    with pytest.raises(ValueError, match="missing real-tour credential"):
        orchestrator_runtime.build_default_orchestrator(credential_resolver=FakeResolver(None))


def test_settings_connection_validation_uses_injected_read_only_resolver() -> None:
    from src.business.services.settings_actions_service import SettingsActionsService

    service = SettingsActionsService(
        config=FakeConfig(),
        data_dir=None,
        credential_resolver=FakeResolver("sk-read-only"),
    )

    result = service.run_action("test_ai_connection")

    assert result["status"] == "completed"
    assert result["details"] == {"provider": "anthropic", "model": "model-from-config"}


def test_settings_connection_validation_reports_missing_real_tour_key() -> None:
    from src.business.services.settings_actions_service import SettingsActionsService

    config = SimpleNamespace(
        get=lambda key, default=None: {"ai.provider": "anthropic", "ai.model": "model"}.get(
            key, default
        )
    )
    service = SettingsActionsService(
        config=config,
        data_dir=None,
        credential_resolver=FakeResolver(None),
    )

    result = service.run_action("test_ai_connection")

    assert result["status"] == "failed"
    assert result["details"]["code"] == "missing_secret"


def test_real_tour_settings_value_reads_use_read_only_resolver(monkeypatch) -> None:
    from src.business.services.settings_service import SettingsService

    monkeypatch.setenv("MEXEMPLAR_REAL_GRAND_TOUR", "1")
    resolver = FakeResolver("sk-read-only")
    service = SettingsService(config=FakeConfig(), credential_resolver=resolver)

    result = service.get_values()

    assert result["secrets"]["ai.api_key"]["present"] is True
    assert result["status"]["ai.api_key"] == "available"
    assert resolver.calls >= 1


def test_real_tour_settings_secret_mutations_are_rejected(monkeypatch) -> None:
    from src.business.services.settings_service import SettingsService, SettingsValidationError

    monkeypatch.setenv("MEXEMPLAR_REAL_GRAND_TOUR", "1")
    service = SettingsService(config=FakeConfig(), credential_resolver=FakeResolver("sk-read-only"))

    with pytest.raises(SettingsValidationError, match="只读"):
        service.write_secret("ai.api_key", "sk-replacement")
    with pytest.raises(SettingsValidationError, match="只读"):
        service.delete_secret("ai.api_key")
