from __future__ import annotations

from types import SimpleNamespace

from src.business.brain.context_builder import BrainContext, BrainContextBuilder
from src.business.orchestration.agent.orchestrator import AgentOrchestrator


def _equipped_skill_with_body() -> dict:
    return {
        "skill_id": "skill-1",
        "name": "测试方法论",
        "description": "只应注入轻量描述",
        "trigger_conditions": ["需要测试时"],
        "body_markdown": "SECRET_BODY_SHOULD_NOT_ENTER_SYSTEM_PROMPT",
    }


def test_equipped_skill_prompt_section_excludes_body_markdown() -> None:
    prompt_section = BrainContextBuilder.format_equipped_skills_for_prompt(
        [_equipped_skill_with_body()]
    )

    assert "skill-1" in prompt_section
    assert "只应注入轻量描述" in prompt_section
    assert "需要测试时" in prompt_section
    assert "SECRET_BODY_SHOULD_NOT_ENTER_SYSTEM_PROMPT" not in prompt_section
    assert "body_markdown" not in prompt_section


def test_specialist_system_prompt_excludes_methodology_body(monkeypatch) -> None:
    monkeypatch.setattr(
        BrainContextBuilder,
        "equipped_skills_for_entity",
        staticmethod(lambda _entity_id: [_equipped_skill_with_body()]),
    )
    specialist = SimpleNamespace(
        specialist_id="sp-1",
        name="测试专员",
        description="测试",
        role_definition="执行测试",
    )

    prompt = AgentOrchestrator._build_specialist_prompt(specialist, [])

    assert "测试方法论" in prompt
    assert "SECRET_BODY_SHOULD_NOT_ENTER_SYSTEM_PROMPT" not in prompt
    assert "body_markdown" not in prompt


def test_assistant_context_prompt_excludes_methodology_body() -> None:
    prompt = BrainContextBuilder().format_context_for_prompt(
        BrainContext(equipped_skills=[_equipped_skill_with_body()])
    )

    assert "测试方法论" in prompt
    assert "SECRET_BODY_SHOULD_NOT_ENTER_SYSTEM_PROMPT" not in prompt
    assert "body_markdown" not in prompt
