from __future__ import annotations


def test_vision_client_uses_temperature_and_rebuilds_when_it_changes(monkeypatch) -> None:
    from src.business.agents import tool_helpers
    import src.business.ai.llm_client as llm_client_module
    import src.data.unified_config as unified_config_module

    created: list[dict[str, object]] = []

    class Config:
        temperature = 0.25

        def get_ai_vision_provider(self) -> str:
            return "openai"

        def get_ai_vision_model(self) -> str:
            return "vision-model"

        def get_ai_vision_api_key(self):
            return None

        def get_ai_vision_base_url(self):
            return None

        def get_ai_temperature(self) -> float:
            return self.temperature

        def get_ai_request_timeout(self) -> float:
            return 30.0

    class FakeLLM:
        def __init__(self, **kwargs) -> None:
            created.append(kwargs)

    config = Config()
    monkeypatch.setattr(unified_config_module, "get_unified_config", lambda: config)
    monkeypatch.setattr(llm_client_module, "LangChainLLMClient", FakeLLM)

    # vision client 现在每次基于最新配置现组装（无模块级缓存），故配置变更后
    # 下一次调用立即拾取新值。
    first = tool_helpers.get_vision_llm_client()
    config.temperature = 0.8
    second = tool_helpers.get_vision_llm_client()

    assert first is not second
    assert [client["temperature"] for client in created] == [0.25, 0.8]
