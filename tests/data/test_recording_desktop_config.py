import json
import sys
import types

from src.data.config_models import AppConfig
from src.data.unified_config import UnifiedConfigManager


def test_recording_desktop_config_defaults_and_round_trip(tmp_path, monkeypatch):
    assert AppConfig().ai.timeout == 180
    assert AppConfig().recording.desktop.enable_clip is True
    assert AppConfig().recording.desktop.vision_model is None
    assert AppConfig().recording.default_recording_mode == "browser"

    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps(
            {"recording": {"desktop": {"enable_clip": False, "vision_model": "vision-x"}}},
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
    desktop = config.get_recording_desktop_config()

    assert desktop.enable_clip is False
    assert desktop.vision_model == "vision-x"
    assert config.get_desktop_enable_clip() is False
    assert config.get_desktop_vision_model() == "vision-x"


def test_desktop_vision_model_does_not_fallback_to_general_vision(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"ai": {"vision_model": "general-vision"}, "recording": {"desktop": {}}}),
        encoding="utf-8",
    )
    monkeypatch.setitem(
        sys.modules,
        "keyring",
        types.SimpleNamespace(get_password=lambda *args, **kwargs: None),
    )

    config = UnifiedConfigManager(config_path=str(config_path))

    assert config.get_ai_vision_model() == "general-vision"
    assert config.get_desktop_vision_model() is None


def test_example_config_has_desktop_keys():
    data = json.loads(open("config.example.json", encoding="utf-8").read())

    assert data["recording"]["default_recording_mode"] == "browser"
    assert data["recording"]["desktop"] == {"enable_clip": True, "vision_model": None}
