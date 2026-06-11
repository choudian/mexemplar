import json
import sys
import types

from src.data.unified_config import UnifiedConfigManager


def test_compression_model_follows_primary_chat_model(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "ai": {
                    "provider": "openai",
                    "model": "gpt-4o-mini",
                    "api_key": "chat-key",
                    "base_url": "https://chat.example/v1",
                    "compression_model_provider": "anthropic",
                    "compression_model_name": "claude-3-5-haiku-20241022",
                    "compression_model_api_key": "compact-key",
                    "compression_model_base_url": "https://compact.example/v1",
                    "compression_model_temperature": 0.25,
                    "compression_model_max_tokens": 321,
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setitem(
        sys.modules,
        "keyring",
        types.SimpleNamespace(get_password=lambda *args, **kwargs: None),
    )

    config = UnifiedConfigManager(config_path=str(config_path))

    assert config.get_compression_model_provider() == "openai"
    assert config.get_compression_model_name() == "gpt-4o-mini"
    assert config.get_compression_model_api_key() == "chat-key"
    assert config.get_compression_model_base_url() == "https://chat.example/v1"
    assert config.get_compression_model_temperature() == 0.25
    assert config.get_compression_model_max_tokens() == 321


def test_tool_output_semantic_summary_defaults_and_bounds(tmp_path, monkeypatch):
    config = UnifiedConfigManager(config_path=str(tmp_path / "config.json"))

    assert config.get_agent_tools_output_semantic_summary_enabled() is True
    assert config.get_agent_tools_output_semantic_summary_provider() == "anthropic"
    assert config.get_agent_tools_output_semantic_summary_model() == ""
    assert config.get_agent_tools_output_semantic_summary_temperature() == 0.2
    assert config.get_agent_tools_output_semantic_summary_trigger_chars() == 20000
    assert config.get_agent_tools_output_semantic_summary_max_input_chars() == 120000
    assert config.get_agent_tools_output_semantic_summary_chunk_chars() == 20000
    assert config.get_agent_tools_output_semantic_summary_max_map_chunks() == 6
    assert config.get_agent_tools_output_semantic_summary_map_concurrency() == 3
    assert config.get_agent_tools_output_semantic_summary_total_timeout_seconds() == 12
    assert config.get_agent_tools_output_semantic_summary_map_max_tokens() == 500
    assert config.get_agent_tools_output_semantic_summary_reduce_max_tokens() == 900
    assert config.get_agent_tools_output_semantic_summary_summary_max_chars() == 4000


def test_recording_noise_filter_config_reads_nested_defaults_and_overrides(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "recording": {
                    "noise_filter": {
                        "enabled": False,
                        "blacklist_domains": ["example-tracker"],
                        "first_party_whitelist": ["static.example.com"],
                        "static_extensions": [".png", ".css"],
                        "static_content_type_prefixes": ["image/", "text/css"],
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setitem(
        sys.modules,
        "keyring",
        types.SimpleNamespace(get_password=lambda *args, **kwargs: None),
    )

    config = UnifiedConfigManager(config_path=str(config_path))
    noise_filter = config.get_recording_noise_filter_config()

    assert noise_filter.enabled is False
    assert noise_filter.blacklist_domains == ["example-tracker"]
    assert noise_filter.first_party_whitelist == ["static.example.com"]
    assert noise_filter.static_extensions == [".png", ".css"]
    assert noise_filter.static_content_type_prefixes == ["image/", "text/css"]


def test_web_search_backend_defaults_to_auto(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    monkeypatch.setitem(
        sys.modules,
        "keyring",
        types.SimpleNamespace(get_password=lambda *args, **kwargs: None),
    )

    config = UnifiedConfigManager(config_path=str(config_path))

    assert config.get_web_search_backend() == "auto"


def test_web_search_backend_reads_file_override_normalized(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"web": {"search_backend": "DDG-HTML"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setitem(
        sys.modules,
        "keyring",
        types.SimpleNamespace(get_password=lambda *args, **kwargs: None),
    )

    config = UnifiedConfigManager(config_path=str(config_path))

    assert config.get_web_search_backend() == "ddg-html"


def test_memory_reference_size_threshold_default_is_raised(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    monkeypatch.setitem(
        sys.modules,
        "keyring",
        types.SimpleNamespace(get_password=lambda *args, **kwargs: None),
    )

    config = UnifiedConfigManager(config_path=str(config_path))

    assert config.get_memory_reference_size_threshold() == 10000
