from __future__ import annotations

import inspect

from src.business.orchestration.agent.delegation_orchestrator import DelegationOrchestrator
from src.business.orchestration.agent.orchestrator import AgentOrchestrator


def test_specialist_dispatch_decision_does_not_read_methodology_equipment() -> None:
    source = inspect.getsource(DelegationOrchestrator.delegate_to_specialist)

    assert "SkillEquipmentService" not in source
    assert "BrainContextBuilder" not in source
    assert "load_skill_methodology" not in source
    assert "trigger_conditions" not in source
    assert "run_specialist_via_delegated_executor" in source


def test_methodology_equipment_is_only_added_after_specialist_is_selected() -> None:
    source = inspect.getsource(AgentOrchestrator._build_specialist_prompt)

    assert "BrainContextBuilder" in source
    assert "equipped_skills_for_entity" in source
