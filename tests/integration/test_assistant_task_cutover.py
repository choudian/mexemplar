from __future__ import annotations

from src.business.task_collaboration.cutover import TaskCollaborationCutoverGuard


class _Config:
    def __init__(self, enabled: bool, guard: bool = True) -> None:
        self.enabled = enabled
        self.guard = guard

    def get_assistant_tasks_unified_dispatch_enabled(self) -> bool:
        return self.enabled

    def get_assistant_tasks_clean_start_guard_enabled(self) -> bool:
        return self.guard


class _Transition:
    def __init__(self, event_type: str) -> None:
        self.event_type = event_type


class _Transitions:
    def __init__(self, rows: list[_Transition]) -> None:
        self.rows = rows

    def has_recent_event_types(self, event_types, *, window: int = 200) -> bool:
        allowed = set(event_types)
        return any(row.event_type in allowed for row in self.rows)


def test_clean_start_cutover_blocks_legacy_active_delegation(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.business.task_collaboration.cutover.get_unified_config",
        lambda: _Config(True),
    )
    guard = TaskCollaborationCutoverGuard(
        transition_repo=_Transitions([_Transition("assistant_delegation_started")])
    )

    state = guard.evaluate()

    assert state.enabled is False
    assert state.reason == "legacy_active_delegation"


class _BrokenTransitions:
    def has_recent_event_types(self, event_types, *, window: int = 200) -> bool:
        raise RuntimeError("transition store unavailable")


def test_cutover_fails_closed_when_legacy_state_unreadable(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.business.task_collaboration.cutover.get_unified_config",
        lambda: _Config(True),
    )
    guard = TaskCollaborationCutoverGuard(transition_repo=_BrokenTransitions())

    state = guard.evaluate()

    # 读不到 legacy transition 时 fail-closed：当作 legacy 仍在跑，阻止新统一派发
    assert state.enabled is False
    assert state.reason == "legacy_active_delegation"


def test_cutover_disabled_is_safe_rollback(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.business.task_collaboration.cutover.get_unified_config",
        lambda: _Config(False),
    )
    guard = TaskCollaborationCutoverGuard(transition_repo=_Transitions([]))

    state = guard.evaluate()

    assert state.enabled is False
    assert state.reason == "unified_dispatch_disabled"
