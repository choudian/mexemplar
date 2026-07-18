import json

from src.data.unified_config import UnifiedConfigManager, _log_value


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


def test_ai_temperature_defaults_and_rejects_non_finite_or_out_of_range_values(tmp_path):
    config = UnifiedConfigManager(config_path=str(tmp_path / "config.json"))
    config._sa = _SettingsStore()

    assert config.get_ai_temperature() == 0.7

    for invalid in (
        None,
        True,
        "not-a-number",
        -0.01,
        2.01,
        float("nan"),
        float("inf"),
        float("-inf"),
    ):
        config.set("ai.temperature", invalid, persist="runtime")
        assert config.get_ai_temperature() == 0.7

    config.set("ai.temperature", 0, persist="runtime")
    assert config.get_ai_temperature() == 0.0
    config.set("ai.temperature", 2, persist="runtime")
    assert config.get_ai_temperature() == 2.0


def test_agent_tools_discovery_defaults_and_bounds(tmp_path):
    config = UnifiedConfigManager(config_path=str(tmp_path / "config.json"))
    store = _SettingsStore()
    config._sa = store

    assert config.get_agent_tools_discovery_full_catalog_max_items() == 20
    assert config.get_agent_tools_discovery_full_catalog_max_chars() == 6000
    assert config.get_agent_tools_discovery_search_default_limit() == 10
    assert config.get_agent_tools_discovery_search_max_limit() == 25
    assert config.get_agent_tools_discovery_result_description_max_chars() == 500

    config.set("agent_tools.discovery.full_catalog_max_items", 0, persist="runtime")
    config.set(
        "agent_tools.discovery.full_catalog_max_chars",
        200000,
        persist="runtime",
    )
    config.set("agent_tools.discovery.search_default_limit", 80, persist="runtime")
    config.set("agent_tools.discovery.search_max_limit", 12, persist="runtime")
    config.set(
        "agent_tools.discovery.result_description_max_chars",
        "bad",
        persist="runtime",
    )

    assert config.get_agent_tools_discovery_full_catalog_max_items() == 20
    assert config.get_agent_tools_discovery_full_catalog_max_chars() == 100000
    assert config.get_agent_tools_discovery_search_max_limit() == 12
    assert config.get_agent_tools_discovery_search_default_limit() == 12
    assert config.get_agent_tools_discovery_result_description_max_chars() == 500


def test_agent_tools_delegation_context_expansion_defaults_and_bounds(tmp_path):
    config = UnifiedConfigManager(config_path=str(tmp_path / "config.json"))
    config._sa = _SettingsStore()

    assert config.get_agent_tools_delegation_context_expansion_max_chars() == 30000

    config.set(
        "agent_tools.delegation.context_expansion_max_chars",
        1000,
        persist="runtime",
    )
    assert config.get_agent_tools_delegation_context_expansion_max_chars() == 1000

    config.set(
        "agent_tools.delegation.context_expansion_max_chars",
        45000,
        persist="runtime",
    )
    assert config.get_agent_tools_delegation_context_expansion_max_chars() == 45000

    config.set(
        "agent_tools.delegation.context_expansion_max_chars",
        999,
        persist="runtime",
    )
    assert config.get_agent_tools_delegation_context_expansion_max_chars() == 30000

    config.set(
        "agent_tools.delegation.context_expansion_max_chars",
        1000001,
        persist="runtime",
    )
    assert config.get_agent_tools_delegation_context_expansion_max_chars() == 1000000


def test_agent_tools_delegation_context_expansion_loads_nested_config(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "agent_tools": {
                    "delegation": {"context_expansion_max_chars": 64000},
                }
            }
        ),
        encoding="utf-8",
    )
    config = UnifiedConfigManager(config_path=str(config_path))
    config._sa = _SettingsStore()

    assert config.get_agent_tools_delegation_context_expansion_max_chars() == 64000


def test_agent_tools_discovery_nested_config_loads(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "agent_tools": {
                    "discovery": {
                        "full_catalog_max_items": 7,
                        "full_catalog_max_chars": 2500,
                        "search_default_limit": 4,
                        "search_max_limit": 9,
                        "result_description_max_chars": 240,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    config = UnifiedConfigManager(config_path=str(config_path))
    config._sa = _SettingsStore()

    discovery = config.get_agent_tools_discovery_config()
    assert discovery.full_catalog_max_items == 7
    assert discovery.full_catalog_max_chars == 2500
    assert discovery.search_default_limit == 4
    assert discovery.search_max_limit == 9
    assert discovery.result_description_max_chars == 240


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
                "skill_store": {"skills_sh_api_key": "skills-sh-key"},
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
    assert config.get_skill_store_skills_sh_api_key() == "skills-sh-key"
    assert config.get_tool_output_summary_api_key() == "summary-key"


def test_secret_setters_persist_to_unified_config_and_clear(tmp_path):
    config = UnifiedConfigManager(config_path=str(tmp_path / "config.json"))
    store = _SettingsStore()
    config._sa = store

    config.set_ai_api_key(" main-key ")
    config.set_web_brave_api_key(" brave-key ")
    config.set_skill_store_skills_sh_api_key(" skills-sh-key ")
    config.set_tool_output_summary_api_key(" summary-key ")

    assert store.values["ai.api_key"] == "main-key"
    assert store.values["web.brave_api_key"] == "brave-key"
    assert store.values["skill_store.skills_sh_api_key"] == "skills-sh-key"
    assert store.values["agent_tools.output.semantic_summary.api_key"] == "summary-key"
    assert config.get_ai_api_key() == "main-key"
    assert config.get_web_brave_api_key() == "brave-key"
    assert config.get_skill_store_skills_sh_api_key() == "skills-sh-key"
    assert config.get_tool_output_summary_api_key() == "summary-key"

    config.clear_ai_api_key()
    config.clear_web_brave_api_key()
    config.clear_skill_store_skills_sh_api_key()
    config.clear_tool_output_summary_api_key()

    assert config.get_ai_api_key() is None
    assert config.get_web_brave_api_key() is None
    assert config.get_skill_store_skills_sh_api_key() is None
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


def test_memory_reference_size_threshold_reads_canonical_ai_file_key(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {"ai": {"memory_reference_size_threshold": 4321}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    config = UnifiedConfigManager(config_path=str(config_path))
    config._sa = _SettingsStore()

    assert config.get_memory_reference_size_threshold() == 4321


def test_memory_legacy_file_key_is_compatible_but_canonical_key_wins(tmp_path, caplog):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "memory": {"reference_size_threshold": 4321},
                "ai": {"memory_reference_size_threshold": 7654},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    config = UnifiedConfigManager(config_path=str(config_path))
    config._sa = _SettingsStore()

    assert config.get_memory_reference_size_threshold() == 7654

    legacy_path = tmp_path / "legacy-config.json"
    legacy_path.write_text(
        json.dumps({"memory": {"reference_size_threshold": 4321}}, ensure_ascii=False),
        encoding="utf-8",
    )
    legacy_config = UnifiedConfigManager(config_path=str(legacy_path))
    legacy_config._sa = _SettingsStore()

    assert legacy_config.get_memory_reference_size_threshold() == 4321
    assert "memory.reference_size_threshold" in caplog.text


def test_memory_legacy_database_key_is_used_when_canonical_key_is_absent(tmp_path, caplog):
    config = UnifiedConfigManager(config_path=str(tmp_path / "config.json"))
    store = _SettingsStore()
    store.values["memory.reference_size_threshold"] = 4321
    config._sa = store

    assert config.get_memory_reference_size_threshold() == 4321
    assert "memory.reference_size_threshold" in caplog.text


def test_websocket_size_limits_read_from_file_config(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "recording": {
                    "websocket": {
                        "max_message_size": 123456,
                        "max_response_body_size": 654321,
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    config = UnifiedConfigManager(config_path=str(config_path))
    config._sa = _SettingsStore()

    assert config.get_websocket_max_message_size() == 123456
    assert config.get_websocket_max_response_body_size() == 654321


def test_websocket_size_limits_reject_non_positive_or_non_numeric_values(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "recording": {
                    "websocket": {
                        "max_message_size": "not-a-size",
                        "max_response_body_size": 0,
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    config = UnifiedConfigManager(config_path=str(config_path))
    config._sa = _SettingsStore()

    assert config.get_websocket_max_message_size() == 50 * 1024 * 1024
    assert config.get_websocket_max_response_body_size() == 5 * 1024 * 1024


def test_websocket_file_port_requires_a_connectable_tcp_port(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"recording": {"websocket": {"port": 0}}}, ensure_ascii=False),
        encoding="utf-8",
    )
    config = UnifiedConfigManager(config_path=str(config_path))
    config._sa = _SettingsStore()

    assert config.get_websocket_port() == 8765


def test_assistant_task_settings_read_from_file_config(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "assistant_tasks": {
                    "unified_dispatch": {"enabled": False},
                    "complexity": {"step_threshold": 7},
                    "planner": {"specialist_name": "architecture-planner"},
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    config = UnifiedConfigManager(config_path=str(config_path))
    config._sa = _SettingsStore()

    assert config.get_assistant_tasks_unified_dispatch_enabled() is False
    assert config.get_assistant_tasks_complexity_step_threshold() == 7
    assert config.get_assistant_tasks_planner_specialist_name() == "architecture-planner"


def test_external_coding_settings_read_from_file_config(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "external_coding": {
                    "enabled": False,
                    "default_launch_mode": "interactive",
                    "quota_probe": {
                        "enabled": False,
                        "timeout_seconds": 9,
                        "low_threshold_percent": 70,
                    },
                    "codex": {
                        "command": "custom-codex",
                        "reasoning_effort": "high",
                    },
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    config = UnifiedConfigManager(config_path=str(config_path))
    config._sa = _SettingsStore()

    assert config.get_external_coding_enabled() is False
    assert config.get_external_coding_default_launch_mode() == "interactive"
    assert config.get_external_coding_quota_probe_enabled() is False
    assert config.get_external_coding_quota_probe_timeout_seconds() == 9
    assert config.get_external_coding_quota_low_threshold_percent() == 70
    assert config.get_external_coding_codex_command() == "custom-codex"
    assert config.get_external_coding_codex_reasoning_effort() == "high"


def test_agent_tool_limits_read_from_file_config(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {
                "agent_tools": {
                    "max_parallel_workers": 7,
                    "output": {"load_max_bytes": 262144},
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    config = UnifiedConfigManager(config_path=str(config_path))
    config._sa = _SettingsStore()

    assert config.get_agent_tools_max_parallel_workers() == 7
    assert config.get_agent_tools_output_load_max_bytes() == 262144


def test_nested_model_profile_secret_is_redacted_from_config_logs():
    assert (
        _log_value(
            "self_improvement.execution_review.model",
            {"provider": "test", "api_key": "x"},
        )
        == "<redacted>"
    )
    assert _log_value("mcp.servers.mcs_example.env.API_TOKEN", "x") == "<redacted>"
