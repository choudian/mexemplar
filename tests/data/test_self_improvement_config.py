"""Tests for self_improvement config loading through AppConfig."""

from __future__ import annotations

import json

from src.data.unified_config import UnifiedConfigManager


def _make_config(tmp_path, payload: dict) -> UnifiedConfigManager:
    path = tmp_path / "config.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return UnifiedConfigManager(config_path=str(path))


def test_self_improvement_proposal_config_loads_from_file(tmp_path):
    config = _make_config(
        tmp_path,
        {
            "self_improvement": {
                "proposals": {
                    "enabled": False,
                    "worktree_retention_max": 7,
                    "dedup_cooldown_hours": 0,
                }
            }
        },
    )

    assert config.get_self_improvement_proposals_enabled() is False
    assert config.get_self_improvement_proposals_worktree_retention_max() == 7
    assert config.get_self_improvement_proposals_dedup_cooldown_hours() == 0


def test_self_improvement_execution_review_config_loads_from_file(tmp_path):
    config = _make_config(
        tmp_path,
        {
            "self_improvement": {
                "execution_review": {
                    "enabled": False,
                    "model": {"provider": "openai", "model": "reviewer"},
                    "max_per_session": 9,
                }
            }
        },
    )

    assert config.get_self_improvement_execution_review_enabled() is False
    assert config.get_self_improvement_execution_review_model() == {
        "provider": "openai",
        "model": "reviewer",
    }
    assert config.get_self_improvement_execution_review_max_per_session() == 9


def test_self_improvement_legacy_limits_load_from_file(tmp_path):
    config = _make_config(
        tmp_path,
        {
            "self_improvement": {
                "max_prompt_supplements_per_day": 8,
                "max_tool_creations_per_day": 2,
                "max_reflections_per_session": 6,
                "convergence_threshold": 0.2,
                "degradation_threshold": 0.4,
                "sandbox_window": 30,
                "rollback_monitor_window": 12,
                "avoidance_top_n": 11,
                "tool_gap_threshold": 5,
            }
        },
    )

    assert config.get_self_improvement_max_prompt_supplements_per_day() == 8
    assert config.get_self_improvement_max_tool_creations_per_day() == 2
    assert config.get_self_improvement_max_reflections_per_session() == 6
    assert config.get_self_improvement_convergence_threshold() == 0.2
    assert config.get_self_improvement_degradation_threshold() == 0.4
    assert config.get_self_improvement_sandbox_window() == 30
    assert config.get_self_improvement_rollback_monitor_window() == 12
    assert config.get_self_improvement_avoidance_top_n() == 11
    assert config.get_self_improvement_tool_gap_threshold() == 5
