"""Architecture guardrails for brain layering and unchanged recording agents"""


class TestBrainLayering:
    """Verify brain package respects layering rules"""

    def test_brain_business_does_not_import_desktop_api(self):
        """business/brain/ must not import desktop_api"""
        import src.business.brain.models as brain_models

        source_file = brain_models.__file__
        with open(source_file, "r", encoding="utf-8") as f:
            content = f.read()
        assert "desktop_api" not in content

    def test_brain_business_does_not_import_frontend(self):
        """business/brain/ must not import frontend"""
        import src.business.brain.models as brain_models

        source_file = brain_models.__file__
        with open(source_file, "r", encoding="utf-8") as f:
            content = f.read()
        assert "frontend" not in content

    def test_brain_router_does_not_import_repos_at_module_level(self):
        """desktop_api/routers/brain.py must not import repos at module level (lazy imports in handlers are OK)"""
        import src.desktop_api.routers.brain as brain_router

        source_file = brain_router.__file__
        with open(source_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        # Check that no top-level (unindented) imports of repos exist
        for i, line in enumerate(lines, 1):
            stripped = line.lstrip()
            if (
                stripped.startswith("from src.data.repos")
                and not line.startswith(" ")
                and not line.startswith("\t")
            ):
                raise AssertionError(f"Module-level repo import found at line {i}: {line.rstrip()}")

    def test_data_repositories_do_not_import_business_or_emit_domain_events(self):
        """Repositories persist data; business services own brain notifications."""
        from pathlib import Path

        for relative_path in (
            "src/data/repos/brain_repository.py",
            "src/data/repos/brain_segment_repository.py",
            "src/data/repos/brain_memory_repository.py",
            "src/data/repos/brain_prediction_repository.py",
            "src/data/repos/brain_feedback_repository.py",
            "src/data/repos/specialist_repository.py",
        ):
            content = Path(relative_path).read_text(encoding="utf-8")
            assert "src.business" not in content
            assert "src.utils.events" not in content
            assert "emit(" not in content


class TestScoringWeightInvariants:
    """Verify composite scoring weights sum to 1.0 so scores stay in [0, 1]."""

    def test_hot_zone_weights_sum_to_one(self):
        from src.business.brain.scoring import (
            HOT_EFFECTIVENESS_WEIGHT,
            HOT_EXPLORATION_WEIGHT,
            HOT_RECENCY_WEIGHT,
            HOT_RELEVANCE_WEIGHT,
        )

        total = (
            HOT_RELEVANCE_WEIGHT
            + HOT_RECENCY_WEIGHT
            + HOT_EFFECTIVENESS_WEIGHT
            + HOT_EXPLORATION_WEIGHT
        )
        assert abs(total - 1.0) < 1e-9, f"Hot zone weights sum to {total}, expected 1.0"

    def test_subconscious_zone_weights_sum_to_one(self):
        from src.business.brain.scoring import (
            SUBCONSCIOUS_EFFECTIVENESS_WEIGHT,
            SUBCONSCIOUS_EXPLORATION_WEIGHT,
            SUBCONSCIOUS_RECENCY_WEIGHT,
        )

        total = (
            SUBCONSCIOUS_RECENCY_WEIGHT
            + SUBCONSCIOUS_EFFECTIVENESS_WEIGHT
            + SUBCONSCIOUS_EXPLORATION_WEIGHT
        )
        assert abs(total - 1.0) < 1e-9, f"Subconscious zone weights sum to {total}, expected 1.0"


class TestRecordingAgentsUnchanged:
    """Verify recording-related agents are not modified by brain feature"""

    def test_pm_agent_config_unchanged(self):
        from src.business.agents.config import AgentType

        assert hasattr(AgentType, "PM")
        assert AgentType.PM.value == "pm"

    def test_programmer_agent_config_unchanged(self):
        from src.business.agents.config import AgentType

        assert hasattr(AgentType, "PROGRAMMER")
        assert AgentType.PROGRAMMER.value == "programmer"

    def test_trial_agent_config_unchanged(self):
        from src.business.agents.config import AgentType

        assert hasattr(AgentType, "TRIAL")
        assert AgentType.TRIAL.value == "trial"

    def test_assistant_agent_config_exists(self):
        from src.business.agents.config import AgentType

        assert hasattr(AgentType, "ASSISTANT")
        assert AgentType.ASSISTANT.value == "assistant"
