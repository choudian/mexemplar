"""Tests for _healing_actions_for pure function and related constants (024 C1)."""

from __future__ import annotations

from src.business.task_collaboration.dispatcher import (
    _healing_actions_for,
    _HEALING_ACTIONS_BY_STATUS,
    _DEFAULT_HEALING_ACTIONS,
    _HEALING_ACTION_HINTS,
)


class TestHealingActionsFor:
    """C1: _healing_actions_for returns status-specific actions or default."""

    def test_stuck_returns_stuck_specific_list(self) -> None:
        result = _healing_actions_for("stuck")
        assert result == _HEALING_ACTIONS_BY_STATUS["stuck"]

    def test_failed_input_returns_failed_input_specific_list(self) -> None:
        result = _healing_actions_for("failed_input")
        assert result == _HEALING_ACTIONS_BY_STATUS["failed_input"]

    def test_unknown_status_returns_default_actions(self) -> None:
        result = _healing_actions_for("unknown_status")
        assert result == _DEFAULT_HEALING_ACTIONS

    def test_each_action_name_exists_in_hints(self) -> None:
        """Every action name in all returned lists must have a hint entry."""
        for actions in _HEALING_ACTIONS_BY_STATUS.values():
            for action in actions:
                assert action in _HEALING_ACTION_HINTS, (
                    f"action '{action}' missing from _HEALING_ACTION_HINTS"
                )
        for action in _DEFAULT_HEALING_ACTIONS:
            assert action in _HEALING_ACTION_HINTS, (
                f"default action '{action}' missing from _HEALING_ACTION_HINTS"
            )

    def test_returned_list_is_a_copy(self) -> None:
        """Mutating the returned list must not affect the original constant."""
        result = _healing_actions_for("stuck")
        original_len = len(_HEALING_ACTIONS_BY_STATUS["stuck"])
        result.append("should_not_leak")
        assert len(_HEALING_ACTIONS_BY_STATUS["stuck"]) == original_len

    def test_default_returned_list_is_a_copy(self) -> None:
        """Mutating the default-branch list must not affect the constant."""
        result = _healing_actions_for("nonexistent")
        original_len = len(_DEFAULT_HEALING_ACTIONS)
        result.append("should_not_leak")
        assert len(_DEFAULT_HEALING_ACTIONS) == original_len
