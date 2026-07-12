"""UnifiedConfigManager 的配置来源优先级与生效边界。"""

import json

from src.data.unified_config import UnifiedConfigManager


class _SettingsStore:
    def __init__(self):
        self.values = {}

    def initialize(self):
        pass

    def get_setting(self, key, default=None):
        return self.values.get(key, default)

    def set_setting(self, key, value, value_type="string"):
        del value_type
        self.values[key] = value


def _make_manager(monkeypatch, config_path, store):
    monkeypatch.setattr(
        "src.data.unified_config.get_sqlalchemy_manager",
        lambda: store,
    )
    return UnifiedConfigManager(config_path=str(config_path))


def test_database_value_supersedes_file_after_file_value_was_already_read(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"ai": {"model": "file-model"}}), encoding="utf-8")
    store = _SettingsStore()
    config = _make_manager(monkeypatch, config_path, store)

    assert config.get_ai_model() == "file-model"

    # 模拟 Settings/API 在本 manager 生命周期内写入 app_settings。
    store.values["ai.model"] = "database-model"
    assert config.get_ai_model() == "database-model"


def test_file_change_requires_a_new_manager_instance(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"ai": {"model": "first-file-model"}}), encoding="utf-8")
    store = _SettingsStore()
    first_manager = _make_manager(monkeypatch, config_path, store)

    assert first_manager.get_ai_model() == "first-file-model"

    config_path.write_text(json.dumps({"ai": {"model": "updated-file-model"}}), encoding="utf-8")
    assert first_manager.get_ai_model() == "first-file-model"

    restarted_manager = _make_manager(monkeypatch, config_path, store)
    assert restarted_manager.get_ai_model() == "updated-file-model"


def test_runtime_override_beats_database_and_database_write_replaces_runtime_override(
    tmp_path, monkeypatch
):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"ai": {"model": "file-model"}}), encoding="utf-8")
    store = _SettingsStore()
    store.values["ai.model"] = "database-model"
    config = _make_manager(monkeypatch, config_path, store)

    assert config.get_ai_model() == "database-model"

    config.set("ai.model", "runtime-model", persist="runtime")
    assert config.get_ai_model() == "runtime-model"

    config.set("ai.model", "new-database-model", persist="database")
    assert config.get_ai_model() == "new-database-model"
