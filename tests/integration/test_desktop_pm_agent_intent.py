from src.business.agents.prompts.desktop_prompts import build_pm_prompt


def test_desktop_pm_prompt_guides_agent_to_desktop_tools():
    prompt = build_pm_prompt("desktop", vision_enabled=True)

    assert "list_desktop_actions" in prompt
    assert "analyze_desktop_action" in prompt
    assert "intent" in prompt
