"""Immutable capability snapshot for a specialist's isolated subagent."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ScopeCaptureState(str, Enum):
    """Whether an unrestricted parent range had to be materialized at capture time."""

    BOUNDED = "bounded"
    UNRESTRICTED_AT_CAPTURE = "unrestricted_at_capture"


@dataclass(frozen=True, slots=True)
class EffectiveSubagentScope:
    """The concrete authority granted to one isolated child at first launch.

    All whitelist-governed dimensions are materialized as concrete sets so a later
    continuation can only remove unavailable members; it can never pick up a newly
    published capability.  MCP and executor-collaboration tools are intentionally
    ambient and therefore are not represented here.
    """

    dynamic_tool_ids: frozenset[str]
    builtin_names: frozenset[str]
    composition_ids: frozenset[str]
    workspace_root: str | None
    capture_state: ScopeCaptureState = ScopeCaptureState.BOUNDED


# A missing closure entry must never share a value with an explicitly unrestricted
# capture.  V1 supports continuation only while the same specialist tool closure is
# alive; rebuilding the closure therefore fails closed and asks the specialist to
# escalate with ask_parent.
SCOPE_SNAPSHOT_MISSING = object()


def resolve_effective_builtin_names(
    *,
    requested_tool_whitelist: list[str] | None,
    specialist_builtin_names: set[str],
    all_builtin_names: set[str],
) -> frozenset[str]:
    """Apply the existing explicit-built-in filtering rule under a hard parent cap."""

    requested_builtin_names = {
        item.strip()
        for item in requested_tool_whitelist or []
        if isinstance(item, str) and item.strip() in all_builtin_names
    }
    if not requested_builtin_names:
        return frozenset(specialist_builtin_names)
    return frozenset(specialist_builtin_names.intersection(requested_builtin_names))
