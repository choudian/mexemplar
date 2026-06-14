import json

from src.data.unified_config import UnifiedConfigManager


class _SettingsStore:
    def __init__(self):
        self.values = {}

    def get_setting(self, key, default=None):
        return self.values.get(key, default)

    def set_setting(self, key, value, value_type="string"):
        self.values[key] = value


def test_compression_model_follows_primary_chat_model(tmp_path):
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
    config = UnifiedConfigManager(config_path=str(config_path))
    config._sa = _SettingsStore()

    assert config.get_compression_model_provider() == "openai"
    assert config.get_compression_model_name() == "gpt-4o-mini"
    assert config.get_compression_model_api_key() == "chat-key"
    assert config.get_compression_model_base_url() == "https://chat.example/v1"
    assert config.get_compression_model_temperature() == 0.25
    assert config.get_compression_model_max_tokens() == 321


def test_tool_output_semantic_summary_defaults_and_bounds(tmp_path):
    config = UnifiedConfigManager(config_path=str(tmp_path / "config.json"))
    config._sa = _SettingsStore()

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


def test_all_api_keys_are_read_from_unified_config(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "ai": {
                    "api_key": "main-key",
                    "vision_api_key": "vision-key",
                    "embedding_api_key": "embedding-key",
                },
                "web": {"brave_api_key": "brave-key"},
                "agent_tools": {
                    "output": {
                        "semantic_summary": {
                            "api_key": "summary-key",
                        }
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    config = UnifiedConfigManager(config_path=str(config_path))
    config._sa = _SettingsStore()

    assert config.get_ai_api_key() == "main-key"
    assert config.get_ai_vision_api_key() == "vision-key"
    assert config.get_embedding_api_key() == "embedding-key"
    assert config.get_web_brave_api_key() == "brave-key"
    assert config.get_tool_output_summary_api_key() == "summary-key"


def test_secret_setters_persist_to_unified_config_and_clear(tmp_path):
    config = UnifiedConfigManager(config_path=str(tmp_path / "config.json"))
    store = _SettingsStore()
    config._sa = store

    config.set_ai_api_key(" main-key ")
    config.set_web_brave_api_key(" brave-key ")
    config.set_tool_output_summary_api_key(" summary-key ")

    assert store.values["ai.api_key"] == "main-key"
    assert store.values["web.brave_api_key"] == "brave-key"
    assert store.values["agent_tools.output.semantic_summary.api_key"] == "summary-key"
    assert config.get_ai_api_key() == "main-key"
    assert config.get_web_brave_api_key() == "brave-key"
    assert config.get_tool_output_summary_api_key() == "summary-key"

    config.clear_ai_api_key()
    config.clear_web_brave_api_key()
    config.clear_tool_output_summary_api_key()

    assert config.get_ai_api_key() is None
    assert config.get_web_brave_api_key() is None
    assert config.get_tool_output_summary_api_key() is None


def test_secret_values_are_redacted_from_config_logs(tmp_path, caplog):
    config = UnifiedConfigManager(config_path=str(tmp_path / "config.json"))
    config._sa = _SettingsStore()

    config.set_ai_api_key("sk-log-secret")
    config.get_ai_api_key()

    assert "sk-log-secret" not in caplog.text


def test_recording_noise_filter_config_reads_nested_defaults_and_overrides(tmp_path):
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
    config = UnifiedConfigManager(config_path=str(config_path))
    config._sa = _SettingsStore()
    noise_filter = config.get_recording_noise_filter_config()

    assert noise_filter.enabled is False
    assert noise_filter.blacklist_domains == ["example-tracker"]
    assert noise_filter.first_party_whitelist == ["static.example.com"]
    assert noise_filter.static_extensions == [".png", ".css"]
    assert noise_filter.static_content_type_prefixes == ["image/", "text/css"]


def test_web_search_backend_defaults_to_auto(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    config = UnifiedConfigManager(config_path=str(config_path))
    config._sa = _SettingsStore()

    assert config.get_web_search_backend() == "auto"


def test_web_search_backend_reads_file_override_normalized(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"web": {"search_backend": "DDG-HTML"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    config = UnifiedConfigManager(config_path=str(config_path))
    config._sa = _SettingsStore()

    assert config.get_web_search_backend() == "ddg-html"


def test_memory_reference_size_threshold_default_is_raised(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text("{}", encoding="utf-8")
    config = UnifiedConfigManager(config_path=str(config_path))
    config._sa = _SettingsStore()

    assert config.get_memory_reference_size_threshold() == 10000
