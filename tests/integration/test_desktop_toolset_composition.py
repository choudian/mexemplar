from types import SimpleNamespace

from src.business.agents.tools import desktop_tools


def test_desktop_toolset_composition_has_three_desktop_tools(monkeypatch):
    monkeypatch.setattr(
        desktop_tools,
        "get_unified_config",
        lambda: SimpleNamespace(get_desktop_vision_model=lambda: "vision-x"),
    )

    names = [tool.name for tool in desktop_tools.create_desktop_specific_tools("rec-1")]

    assert names == ["list_desktop_actions", "analyze_desktop_action", "read_action_clip"]
    assert "analyze_image" not in names
