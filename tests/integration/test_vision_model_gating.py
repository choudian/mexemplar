from types import SimpleNamespace

from src.business.agents.tools import desktop_tools
from src.data.unified_config import UnifiedConfigManager


def test_vision_model_missing_omits_analyze_desktop_action(monkeypatch):
    monkeypatch.setattr(
        desktop_tools,
        "get_unified_config",
        lambda: SimpleNamespace(get_desktop_vision_model=lambda: None),
    )

    names = [tool.name for tool in desktop_tools.create_desktop_specific_tools("rec-1")]

    assert "list_desktop_actions" in names
    assert "read_action_clip" in names
    assert "analyze_desktop_action" not in names


def test_default_config_omits_analyze_desktop_action_without_monkeypatch(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    config_path.write_text(
        '{"ai": {"vision_model": "general-vision"}, "recording": {"desktop": {"vision_model": null}}}',
        encoding="utf-8",
    )
    config = UnifiedConfigManager(config_path=str(config_path))
    monkeypatch.setattr(desktop_tools, "get_unified_config", lambda: config)

    names = [tool.name for tool in desktop_tools.create_desktop_specific_tools("rec-1")]

    assert "analyze_desktop_action" not in names


def test_vision_model_present_injects_analyze_desktop_action(monkeypatch):
    monkeypatch.setattr(
        desktop_tools,
        "get_unified_config",
        lambda: SimpleNamespace(get_desktop_vision_model=lambda: "vision-x"),
    )

    names = [tool.name for tool in desktop_tools.create_desktop_specific_tools("rec-1")]

    assert "analyze_desktop_action" in names
