from src.business.agents.prompts.desktop_prompts import build_pm_prompt, build_programmer_prompt
from src.business.agents.prompts.pm_prompt import PM_SYSTEM_PROMPT
from src.business.agents.prompts.programmer_prompt import PROGRAMMER_SYSTEM_PROMPT


def test_browser_prompts_guard_returns_legacy_constants():
    assert build_pm_prompt("browser") == PM_SYSTEM_PROMPT
    assert build_programmer_prompt("browser") == PROGRAMMER_SYSTEM_PROMPT
