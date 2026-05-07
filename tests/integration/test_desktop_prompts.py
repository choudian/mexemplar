from src.business.agents.prompts.desktop_prompts import (
    PM_SYSTEM_PROMPT_LEGACY,
    PROGRAMMER_SYSTEM_PROMPT_LEGACY,
    build_pm_prompt,
    build_programmer_prompt,
)


def test_desktop_prompt_builders_keep_browser_identity():
    assert build_pm_prompt("browser") is PM_SYSTEM_PROMPT_LEGACY
    assert build_programmer_prompt("browser") is PROGRAMMER_SYSTEM_PROMPT_LEGACY


def test_desktop_prompt_builders_include_contract_phrases():
    pm_prompt = build_pm_prompt("desktop", vision_enabled=True)
    programmer_prompt = build_programmer_prompt("desktop")

    assert "按 window_title 聚焦" in pm_prompt
    assert "list_desktop_actions" in pm_prompt
    assert "analyze_desktop_action" in pm_prompt
    assert "read_action_clip" in pm_prompt
    assert "async def execute() -> dict" in programmer_prompt


def test_desktop_pm_prompt_does_not_call_missing_vision_tool():
    pm_prompt = build_pm_prompt("desktop", vision_enabled=False)

    assert "list_desktop_actions" in pm_prompt
    assert "analyze_desktop_action" not in pm_prompt
