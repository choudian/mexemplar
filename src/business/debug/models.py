"""Debug data models for the trace inspector.

Defines Pydantic BaseModel types and dataclass types used across the debug
subsystem: trace records, capture context, group/transition/reference views,
and related literal enums.

All models are immutable data holders; business logic lives in the service
and buffer layers.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field

# ---- Literal enums ----

DetailAvailability = Literal[
    "full_text",
    "media_metadata_only",
    "oversized_omitted",
    "diagnostic_unavailable",
]

TraceMethod = Literal["chat", "chat_with_tools", "multimodal"]

TraceOutcome = Literal["succeeded", "failed", "cancelled"]

CaptureStatus = Literal["idle", "armed", "capturing"]


# ---- Capture context (dataclass — used with contextvars) ----


@dataclass(frozen=True)
class TraceCaptureContext:
    """Immutable context attached to an in-flight model invocation.

    Propagated via ``contextvars`` so that the unified observation boundary
    can stamp each trace record with its origin.  Cross-thread propagation
    is the caller's responsibility (explicit copy via ``set_context``).
    """

    source: str = ""
    agent_type: str = ""
    session_id: str = ""
    workflow_id: str = ""
    iteration: int = 0
    transition_id: str = ""
    work_unit_id: str = ""


# ---- Arm state ----


class TraceArmState(BaseModel):
    """Snapshot of the trace-arm control state.

    ``enabled`` is driven by the authenticated debug control facade via
    ``UnifiedConfigManager.set("debug.trace.enabled", ..., persist="runtime")``.
    """

    enabled: bool = False
    warning_acknowledged: bool = False
    armed_at: Optional[datetime] = None
    capture_status: CaptureStatus = "idle"
    retention_epoch: str = ""


# ---- Core trace record ----


class LLMTraceRecord(BaseModel):
    """A single captured LLM invocation.

    Text calls store redacted ``input_messages`` / ``output_content``;
    multimodal calls store ``input_media`` metadata (type, count, byte size)
    but never restorable media bytes or data URLs.
    """

    trace_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    retention_epoch: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    method: TraceMethod = "chat"
    source: str = ""
    agent_type: str = ""
    session_id: str = ""
    workflow_id: str = ""
    work_unit_id: str = ""
    iteration: int = 0

    input_messages: Optional[str] = None
    input_media: Optional[str] = None
    input_tools: Optional[str] = None

    output_content: Optional[str] = None
    output_tool_calls: Optional[str] = None

    outcome: TraceOutcome = "succeeded"
    error_summary: str = ""

    linked_transition_ids: list[str] = Field(default_factory=list)
    retained_bytes: int = 0
    detail_availability: DetailAvailability = "full_text"


# ---- Grouped view ----


class TraceGroupView(BaseModel):
    """Aggregated view of traces sharing the same logical grouping key."""

    group_key: str = ""
    source: str = ""
    agent_type: str = ""
    session_id: str = ""
    workflow_id: str = ""
    work_unit_id: str = ""
    trace_count: int = 0
    last_created_at: Optional[datetime] = None
    retained_bytes: int = 0
    omitted_count: int = 0


# ---- Agent flow transition view ----


class AgentFlowTransitionView(BaseModel):
    """A single workflow transition projected for the debug Agent Flow view.

    Existing persisted transition detail may be projected while tracing is
    armed. Additional Assistant delegation detail is ephemeral debug capture
    and is destroyed on disable/clear/restart.
    """

    transition_id: str = ""
    workflow_id: str = ""
    event_type: str = ""
    created_at: Optional[datetime] = None
    from_session: str = ""
    to_session: str = ""
    status: str = ""
    reason: str = ""
    detail: Optional[str] = None
    detail_provenance: Literal["persisted_transition", "ephemeral_debug_capture", "unavailable"] = (
        "unavailable"
    )
    trace_ids: list[str] = Field(default_factory=list)
    link_status: Literal["linked", "unlinked", "unavailable"] = "unavailable"


# ---- Reference expansion view ----


class ExpandedReferenceView(BaseModel):
    """Bounded response for on-demand trace detail expansion.

    The client requests expansion of a specific field within a trace record;
    the response is bounded by ``debug.reference.max_response_bytes``.
    ``next_chunk`` is reserved for a future chunked-read implementation.
    """

    reference_id: str = ""
    content: str = ""
    available: bool = True
    truncated: bool = False
    next_chunk: Optional[int] = None
