"""Debug Inspector service — authenticated, warning-gated, runtime-only control facade.

``DebugInspectorService`` is the sole business entry point for debug control
and trace inspection.  It owns the ``TraceBuffer`` and ``SecretRedactor``
lifecycles and routes all state changes through ``UnifiedConfigManager``
with ``persist="runtime"`` so that settings never survive a sidecar restart.
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone
import json
from typing import Any, Callable

from src.data.unified_config import get_unified_config
from src.data.repos.workflow_transition_repository import WorkflowTransitionRepository
from src.business.debug.flow import (
    EphemeralFlowDetail,
    FlowCorrelationService,
    classify_event_status,
)
from src.business.debug.models import LLMTraceRecord
from src.business.debug.references import DebugReferenceService
from src.business.debug.trace_buffer import SharedRetentionBudget, TraceBuffer
from src.business.debug.redaction import SecretRedactor


class DebugInspectorService:
    """Process-local debug inspector control facade.

    All public methods are thread-safe.
    """

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._buffer: TraceBuffer | None = None
        self._redactor = SecretRedactor()
        self._current_epoch: str | None = None
        self._armed_at: datetime | None = None
        self._flow_details: FlowCorrelationService | None = None
        self._retention_budget: SharedRetentionBudget | None = None

    @property
    def buffer(self) -> TraceBuffer | None:
        """Return the active trace buffer, or ``None`` when unarmed."""
        return self._buffer

    @property
    def redactor(self) -> SecretRedactor:
        """Return the secret redactor."""
        return self._redactor

    @property
    def current_epoch(self) -> str | None:
        """Return the current retention epoch, or ``None`` when unarmed."""
        return self._current_epoch

    # ---- control ----

    def get_status(self) -> dict[str, Any]:
        """Return the safe control status (no raw trace data)."""
        config = get_unified_config()
        with self._lock:
            enabled = (
                config.get_debug_trace_enabled()
                and self._buffer is not None
                and self._current_epoch is not None
            )
            armed_at = self._armed_at if enabled else None
            retention_epoch = self._current_epoch if enabled else None
        return {
            "enabled": enabled,
            "armedAt": armed_at.isoformat() if armed_at else None,
            "retentionEpoch": retention_epoch,
            "warning": ("调试记录可能包含原始用户文本，请勿在 traced 对话中输入自行管理的秘密。"),
            "limits": {
                "maxRecords": config.get_debug_trace_max_records(),
                "maxRecordBytes": config.get_debug_trace_max_record_bytes(),
                "maxTotalBytes": config.get_debug_trace_max_total_bytes(),
            },
        }

    def arm(self, warning_acknowledged: bool = False) -> dict[str, Any]:
        """Enable trace capture after warning acknowledgement.

        Raises ``ValueError`` with code ``debug_warning_required`` if the
        caller has not acknowledged the warning.
        """
        if not warning_acknowledged:
            raise ValueError("debug_warning_required")

        config = get_unified_config()
        with self._lock:
            if config.get_debug_trace_enabled() and self._buffer and self._current_epoch:
                return self.get_status()
            config.set("debug.trace.enabled", True, persist="runtime")
            self._retention_budget = SharedRetentionBudget(config.get_debug_trace_max_total_bytes())
            self._buffer = TraceBuffer(
                max_records=config.get_debug_trace_max_records(),
                max_record_bytes=config.get_debug_trace_max_record_bytes(),
                max_total_bytes=config.get_debug_trace_max_total_bytes(),
                shared_budget=self._retention_budget,
            )
            self._current_epoch = self._buffer.new_epoch()
            self._flow_details = FlowCorrelationService(
                max_total_bytes=config.get_debug_trace_max_total_bytes(),
                shared_budget=self._retention_budget,
            )
            self._flow_details.set_epoch(self._current_epoch)
            self._armed_at = datetime.now(timezone.utc)

        return self.get_status()

    def stop(self) -> dict[str, Any]:
        """Disable trace capture and purge all retained data."""
        config = get_unified_config()
        old_buffer: TraceBuffer | None = None
        old_flow_details: FlowCorrelationService | None = None
        with self._lock:
            old_buffer = self._buffer
            old_flow_details = self._flow_details
            self._buffer = None
            self._flow_details = None
            self._retention_budget = None
            self._current_epoch = None
            self._armed_at = None
            config.set("debug.trace.enabled", False, persist="runtime")

        if old_buffer:
            try:
                old_buffer.invalidate_epoch()
            except Exception:
                self._force_invalidate_buffer(old_buffer)
        if old_flow_details:
            old_flow_details.clear_epoch()

        return self.get_status()

    def clear(self) -> None:
        """Clear trace records and start a new epoch within the same arm session."""
        with self._lock:
            if not self._is_active_unlocked():
                raise LookupError("debug_disabled")
            self._current_epoch = self._buffer.new_epoch()
            if self._flow_details is not None:
                self._flow_details.set_epoch(self._current_epoch)

    # ---- query ----

    def is_enabled(self) -> bool:
        """Return whether tracing is currently enabled."""
        with self._lock:
            return self._is_active_unlocked()

    def list_traces(
        self,
        *,
        source: str | None = None,
        agent_type: str | None = None,
        session_id: str | None = None,
        workflow_id: str | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Return trace summaries for the current epoch."""
        buffer, epoch = self._require_active_capture()
        safe_limit = min(max(int(limit), 1), 200)
        records = buffer.get_records(
            source=source,
            session_id=session_id,
            workflow_id=workflow_id,
            epoch=epoch,
        )
        if agent_type is not None:
            records = [record for record in records if record.agent_type == agent_type]
        records = records[-safe_limit:]
        return {
            "items": [self._trace_summary(record) for record in records],
            "retainedBytes": buffer.get_retained_bytes(),
            "omittedCount": sum(
                1 for record in records if record.detail_availability != "full_text"
            ),
            "warning": self.get_status()["warning"],
        }

    def get_trace_detail(self, trace_id: str) -> dict[str, Any]:
        """Return full detail for one trace in the current epoch."""
        buffer, _epoch = self._require_active_capture()
        record = buffer.get_record(trace_id)
        if record is None:
            raise LookupError("trace_not_found")
        return self._trace_detail(record)

    def list_flows(
        self,
        *,
        workflow_id: str | None = None,
        session_id: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Return flow summaries from authoritative workflow transitions."""
        buffer, epoch = self._require_active_capture()
        with WorkflowTransitionRepository() as repo:
            items = repo.list_flow_summaries(
                workflow_id=workflow_id,
                session_id=session_id,
                limit=limit,
            )
        for item in items:
            traces = buffer.get_records(
                workflow_id=item["workflowId"],
                epoch=epoch,
            )
            item["linkedTraceCount"] = len(traces)
        return {"items": items}

    def get_flow_detail(self, workflow_id: str) -> dict[str, Any]:
        """Return transitions for one workflow."""
        self._require_active_capture()
        with WorkflowTransitionRepository() as repo:
            transitions = repo.get_by_workflow(workflow_id)
        return {
            "workflowId": workflow_id,
            "transitions": [self._project_transition(transition) for transition in transitions],
        }

    def expand_reference(
        self,
        reference_id: str,
        loader_fn: Callable[[str], str | None] | None = None,
    ) -> dict[str, Any]:
        """Expand a reference through the debug facade."""
        self._require_active_capture()
        config = get_unified_config()
        reference_service = DebugReferenceService(
            self._redactor,
            max_response_bytes=config.get_debug_reference_max_response_bytes(),
        )
        if loader_fn is None:
            from src.business.memory.context_manager import ContextManager

            context = ContextManager(session_id="debug_reference_expansion", config=config)
            loader_fn = context.load_reference
        result = reference_service.expand(reference_id, loader_fn)
        if not result["available"]:
            raise LookupError("reference_not_found")
        return result

    # ---- secret registration ----

    def register_secret(self, secret: str) -> None:
        """Register a secret value for redaction in all captured traces."""
        self._redactor.register_secret(secret)

    def capture_delegation_detail(
        self,
        *,
        transition_id: str | None,
        workflow_id: str,
        input_detail: dict[str, Any],
        output_detail: dict[str, Any] | None = None,
    ) -> None:
        """Capture Assistant handoff text outside the LLM invocation trace list."""
        if not transition_id:
            return
        with self._lock:
            if not self._is_active_unlocked() or self._flow_details is None:
                return
            content: dict[str, Any] = {"input": self._redactor.redact_json(input_detail)}
            if output_detail is not None:
                content["output"] = self._redactor.redact_json(output_detail)
            self._flow_details.add_detail(
                transition_id,
                workflow_id,
                "assistant_delegation",
                json.dumps(content, ensure_ascii=False),
            )

    def _is_active_unlocked(self) -> bool:
        return (
            get_unified_config().get_debug_trace_enabled()
            and self._buffer is not None
            and self._current_epoch is not None
        )

    def _require_active_capture(self) -> tuple[TraceBuffer, str]:
        with self._lock:
            if not self._is_active_unlocked():
                raise LookupError("debug_disabled")
            assert self._buffer is not None
            assert self._current_epoch is not None
            return self._buffer, self._current_epoch

    def _trace_summary(self, record: LLMTraceRecord) -> dict[str, Any]:
        return {
            "traceId": record.trace_id,
            "method": record.method,
            "source": record.source or "unknown",
            "agentType": record.agent_type or None,
            "sessionId": record.session_id or None,
            "workflowId": record.workflow_id or None,
            "workUnitId": record.work_unit_id or None,
            "iteration": record.iteration or None,
            "outcome": record.outcome,
            "detailAvailability": record.detail_availability,
            "retainedBytes": record.retained_bytes,
            "createdAt": record.created_at,
            "completedAt": record.completed_at,
            "summary": self._summarize(record),
            "linkedTransitionIds": self._linked_transition_ids_for_record(record),
        }

    def _trace_detail(self, record: LLMTraceRecord) -> dict[str, Any]:
        return {
            **self._trace_summary(record),
            "inputMessages": self._decode_safe_json_or_text(record.input_messages),
            "inputMedia": self._decode_safe_json_or_text(record.input_media, default=[]),
            "inputTools": self._decode_safe_json_or_text(record.input_tools),
            "outputContent": (
                self._redactor.redact(record.output_content) if record.output_content else None
            ),
            "outputToolCalls": self._decode_safe_json_or_text(record.output_tool_calls, default=[]),
            "errorSummary": (
                self._redactor.redact(record.error_summary) if record.error_summary else None
            ),
        }

    @staticmethod
    def _decode_json_or_text(value: str | None, default: Any = None) -> Any:
        if value is None:
            return default
        try:
            return json.loads(value)
        except (TypeError, ValueError):
            return value

    def _decode_safe_json_or_text(self, value: str | None, default: Any = None) -> Any:
        if value is None:
            return default
        return self._decode_json_or_text(self._redactor.redact(value), default)

    def _project_transition(self, transition: Any) -> dict[str, Any]:
        trace_ids = self._trace_ids_for_transition(transition)
        detail_record = self._delegation_detail_for_transition(transition.transition_id)
        if detail_record is not None:
            payload = self._decode_safe_json_or_text(detail_record.content)
            provenance = "ephemeral_debug_capture"
            detail_availability = detail_record.detail_availability
        elif transition.event_type.startswith("assistant_delegation_"):
            payload = None
            provenance = "unavailable"
            detail_availability = "unavailable"
        else:
            payload = self._decode_payload(transition.payload)
            provenance = "persisted_transition" if payload is not None else "unavailable"
            detail_availability = "full_text" if payload is not None else "unavailable"
        return {
            "transitionId": transition.transition_id,
            "workflowId": transition.workflow_id,
            "eventType": transition.event_type,
            "status": classify_event_status(transition.event_type),
            "fromSession": self._session_ref(transition.from_session_id),
            "toSession": self._session_ref(transition.to_session_id),
            "reason": self._extract_reason(payload),
            "detail": payload,
            "detailProvenance": provenance,
            "detailAvailability": detail_availability,
            "traceIds": trace_ids,
            "linkStatus": "linked" if trace_ids else "unlinked",
            "createdAt": transition.created_at,
        }

    def _trace_ids_for_transition(self, transition: Any) -> list[str]:
        if self._buffer is None or self._current_epoch is None:
            return []
        return [
            record.trace_id
            for record in self._buffer.get_records(epoch=self._current_epoch)
            if self._record_matches_transition(record, transition)
        ]

    def _linked_transition_ids_for_record(self, record: LLMTraceRecord) -> list[str]:
        linked_ids = list(record.linked_transition_ids)
        if not record.workflow_id or not record.session_id:
            return linked_ids
        try:
            with WorkflowTransitionRepository() as repo:
                transitions = repo.get_by_workflow(record.workflow_id)
        except Exception:
            return linked_ids
        for transition in transitions:
            if self._record_matches_transition(record, transition):
                transition_id = transition.transition_id
                if transition_id not in linked_ids:
                    linked_ids.append(transition_id)
        return linked_ids

    @staticmethod
    def _record_matches_transition(record: LLMTraceRecord, transition: Any) -> bool:
        if transition.transition_id in record.linked_transition_ids:
            return True
        if not record.workflow_id or record.workflow_id != transition.workflow_id:
            return False
        if not record.session_id:
            return False
        return record.session_id in {
            transition.from_session_id,
            transition.to_session_id,
        }

    def _delegation_detail_for_transition(self, transition_id: str) -> EphemeralFlowDetail | None:
        if self._flow_details is None or self._current_epoch is None:
            return None
        return self._flow_details.get_detail(transition_id)

    def _decode_payload(self, payload: str | None) -> Any:
        if not payload:
            return None
        redacted = self._redactor.redact(payload)
        try:
            return json.loads(redacted)
        except (TypeError, ValueError):
            return redacted

    @staticmethod
    def _session_ref(session_id: str | None) -> dict[str, str] | None:
        if not session_id:
            return None
        return {"sessionId": session_id, "agentType": ""}

    @staticmethod
    def _extract_reason(payload: Any) -> str | None:
        if isinstance(payload, dict):
            for key in ("reason", "error", "message", "summary"):
                value = payload.get(key)
                if isinstance(value, str) and value:
                    return value
        return None

    @staticmethod
    def _summarize(record: LLMTraceRecord) -> str:
        if record.output_tool_calls:
            return "tool_calls"
        if record.output_content:
            return f"text_chars:{len(record.output_content)}"
        if record.error_summary:
            return "failed"
        return record.detail_availability

    @staticmethod
    def _force_invalidate_buffer(buffer: TraceBuffer) -> None:
        """Best-effort fallback used when normal cleanup raises."""
        lock = getattr(buffer, "_lock", None)
        if lock is None:
            return
        with lock:
            budget = getattr(buffer, "_budget", None)
            records = list(getattr(buffer, "_records", ()))
            if budget is not None:
                for record in records:
                    budget.release(buffer._budget_key(record))  # type: ignore[attr-defined]
            if hasattr(buffer, "_epoch"):
                buffer._epoch = ""  # type: ignore[attr-defined]
            if hasattr(buffer, "_records"):
                buffer._records.clear()  # type: ignore[attr-defined]
            if hasattr(buffer, "_retained_bytes"):
                buffer._retained_bytes = 0  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_debug_service: DebugInspectorService | None = None
_service_lock = threading.Lock()


def get_debug_service() -> DebugInspectorService:
    """Return the module-level ``DebugInspectorService`` singleton."""
    global _debug_service
    with _service_lock:
        if _debug_service is None:
            _debug_service = DebugInspectorService()
        return _debug_service


def get_active_capture() -> tuple[TraceBuffer | None, SecretRedactor | None, str | None]:
    """Return active capture objects, or ``(None, None, None)`` when disabled."""
    service = get_debug_service()
    if not service.is_enabled() or service.buffer is None or service.current_epoch is None:
        return None, None, None
    return service.buffer, service.redactor, service.current_epoch
