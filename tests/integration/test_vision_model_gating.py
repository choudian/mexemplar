from types import SimpleNamespace

from src.business.agents.tools import desktop_tools


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


def test_vision_model_present_injects_analyze_desktop_action(monkeypatch):
    monkeypatch.setattr(
        desktop_tools,
        "get_unified_config",
        lambda: SimpleNamespace(get_desktop_vision_model=lambda: "vision-x"),
    )

    names = [tool.name for tool in desktop_tools.create_desktop_specific_tools("rec-1")]

    assert "analyze_desktop_action" in names
