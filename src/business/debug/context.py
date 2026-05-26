"""Trace capture context management.

Provides ``contextvars``-based propagation of :class:`TraceCaptureContext`
so that the unified model invocation observation boundary can stamp each
trace record with its origin without threading explicit parameters through
every call site.

Cross-thread propagation is **not** automatic; callers that dispatch work
to threads or executors must explicitly copy the context via
:func:`set_context` in the target thread.
"""

from __future__ import annotations

import contextvars
from types import TracebackType
from typing import Optional, Type

from src.business.debug.models import TraceCaptureContext

# Module-level ContextVar; ``None`` means no active trace context.
_ctx_var: contextvars.ContextVar[Optional[TraceCaptureContext]] = contextvars.ContextVar(
    "debug_trace_capture_context",
    default=None,
)


def set_context(ctx: TraceCaptureContext) -> contextvars.Token:
    """Bind *ctx* to the current context and return a reset token."""
    return _ctx_var.set(ctx)


def reset_context(token: contextvars.Token) -> None:
    """Restore the previous context state using *token*."""
    _ctx_var.reset(token)


def get_current_context() -> Optional[TraceCaptureContext]:
    """Return the active :class:`TraceCaptureContext`, or ``None``."""
    return _ctx_var.get()


class TraceContext:
    """Context manager for scoped trace capture context.

    Usage::

        with TraceContext(source="assistant", session_id="abc"):
            # inside: get_current_context() returns the set context
            ...
        # outside: previous state restored

    Nesting is safe — each ``with`` block pushes/pops independently via
    ``contextvars`` tokens.
    """

    def __init__(
        self,
        source: str = "",
        agent_type: str = "",
        session_id: str = "",
        workflow_id: str = "",
        iteration: int = 0,
        transition_id: str = "",
        work_unit_id: str = "",
    ) -> None:
        self._ctx = TraceCaptureContext(
            source=source,
            agent_type=agent_type,
            session_id=session_id,
            workflow_id=workflow_id,
            iteration=iteration,
            transition_id=transition_id,
            work_unit_id=work_unit_id,
        )
        self._token: Optional[contextvars.Token] = None

    def __enter__(self) -> TraceCaptureContext:
        self._token = set_context(self._ctx)
        return self._ctx

    def __exit__(
        self,
        exc_type: Optional[Type[BaseException]],
        exc_val: Optional[BaseException],
        exc_tb: Optional[TracebackType],
    ) -> None:
        if self._token is not None:
            reset_context(self._token)
            self._token = None
