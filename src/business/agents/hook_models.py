"""
Agent tool hook protocol models.

These types live outside config.py so recursive argument freezing and internal
execution bookkeeping stay close to the Agent runtime.
"""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Mapping


@dataclass(frozen=True)
class ToolCallContext:
    """Read-only context visible to tool pre/post hooks."""

    tool_name: str
    args: Mapping[str, Any]
    session_id: str
    agent_type: Any
    iteration: int


@dataclass(frozen=True)
class PreHookResult:
    """Pre-hook decision. A non-None error rejects the tool call."""

    error: str | None = None


@dataclass(frozen=True)
class PostHookResult:
    """Post-hook decision. A non-None result replaces final string output."""

    result: str | None = None


PreHook = Callable[[ToolCallContext], PreHookResult | None]
PostHook = Callable[[ToolCallContext, str], PostHookResult | None]


@dataclass(frozen=True)
class ToolExecutionOutcome:
    """Internal result used by AgentLoop batch execution."""

    result: Any
    failed: bool = False
    failure_code: str | None = None


def freeze_tool_args(args: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return a detached recursive read-only view of tool arguments."""

    frozen = {key: _freeze_value(value) for key, value in dict(args).items()}
    return MappingProxyType(frozen)


def _freeze_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_value(inner) for key, inner in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze_value(item) for item in value)
    return value


__all__ = [
    "ToolCallContext",
    "PreHookResult",
    "PostHookResult",
    "PreHook",
    "PostHook",
    "ToolExecutionOutcome",
    "freeze_tool_args",
]
