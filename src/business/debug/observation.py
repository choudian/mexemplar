"""Fail-isolated model invocation observation boundary.

Wraps LLM calls to capture trace data without changing provider behavior.
Capture, redaction, correlation, or buffer failures must NOT change
provider success/failure semantics.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from src.business.debug.context import get_current_context
from src.business.debug.models import LLMTraceRecord, TraceCaptureContext
from src.business.debug.redaction import SecretRedactor
from src.business.debug.trace_buffer import TraceBuffer

logger = logging.getLogger(__name__)


def observe_chat(
    buffer: TraceBuffer | None,
    redactor: SecretRedactor | None,
    epoch: str | None,
    prompt: str,
    invoke_fn: Callable[[str], str],
    method: str = "chat",
) -> str:
    """Observe a ``chat()`` call.  Returns the provider result unchanged.

    Parameters
    ----------
    buffer:
        The active trace buffer, or ``None`` when tracing is disabled.
    redactor:
        The secret redactor, or ``None`` when tracing is disabled.
    epoch:
        The current retention epoch, or ``None`` when tracing is disabled.
    prompt:
        The user prompt string passed to the provider.
    invoke_fn:
        Callable that receives *prompt* and returns the provider response.
    method:
        The trace method label (default ``"chat"``).
    """
    context, trace_id, created_at = _capture_metadata(buffer, redactor, epoch)

    # Pre-call: attempt capture (failure = skip, don't block provider)
    captured_input: str | None = None
    capture_unavailable = False
    if trace_id and buffer and epoch and redactor:
        try:
            captured_input = redactor.redact(prompt)
        except Exception:
            captured_input = None
            capture_unavailable = True

    # Execute provider call (always happens)
    try:
        result = invoke_fn(prompt)
    except Exception as provider_error:
        if trace_id and created_at:
            _record_failure(
                buffer, redactor, trace_id, epoch,
                created_at, method, context, str(provider_error),
                captured_input=captured_input,
                detail_availability=(
                    "diagnostic_unavailable" if capture_unavailable else "full_text"
                ),
            )
        raise

    # Post-call: attempt capture (failure = skip, don't change result)
    if trace_id and created_at:
        _record_success(
            buffer, redactor, trace_id, epoch,
            created_at, method, context, captured_input, result,
            detail_availability=(
                "diagnostic_unavailable" if capture_unavailable else "full_text"
            ),
        )
    return result


def observe_chat_with_tools(
    buffer: TraceBuffer | None,
    redactor: SecretRedactor | None,
    epoch: str | None,
    messages: list[dict],
    tools: list[dict] | None,
    invoke_fn: Callable[[list[dict], list[dict] | None], Any],
    method: str = "chat_with_tools",
) -> Any:
    """Observe a ``chat_with_tools()`` call.

    Parameters
    ----------
    buffer:
        The active trace buffer, or ``None`` when tracing is disabled.
    redactor:
        The secret redactor, or ``None`` when tracing is disabled.
    epoch:
        The current retention epoch, or ``None`` when tracing is disabled.
    messages:
        The message list passed to the provider.
    tools:
        The tool schema list, or ``None``.
    invoke_fn:
        Callable that receives (*messages*, *tools*) and returns an
        ``LLMResponse``-like object with ``.content`` and ``.tool_calls``.
    method:
        The trace method label.
    """
    context, trace_id, created_at = _capture_metadata(buffer, redactor, epoch)

    captured_messages: str | None = None
    captured_tools: str | None = None
    capture_unavailable = False
    if trace_id and buffer and epoch and redactor:
        try:
            if messages:
                redacted_msgs = redactor.redact_json(messages)
                captured_messages = json.dumps(redacted_msgs, ensure_ascii=False)
            if tools:
                redacted_tools = redactor.redact_json(tools)
                captured_tools = json.dumps(redacted_tools, ensure_ascii=False)
        except Exception:
            captured_messages = None
            captured_tools = None
            capture_unavailable = True

    try:
        result = invoke_fn(messages, tools)
    except Exception as provider_error:
        if trace_id and created_at:
            _record_failure(
                buffer, redactor, trace_id, epoch,
                created_at, method, context, str(provider_error),
                captured_input=captured_messages,
                captured_tools=captured_tools,
                detail_availability=(
                    "diagnostic_unavailable" if capture_unavailable else "full_text"
                ),
            )
        raise

    output_content: str | None = None
    output_tool_calls: str | None = None
    try:
        output_content = result.content if result else None
        if result and result.tool_calls:
            tc_list = [
                {"name": tc.name, "args": tc.args}
                for tc in result.tool_calls
            ]
            output_tool_calls = json.dumps(tc_list, ensure_ascii=False)
    except Exception:
        output_content = None
        output_tool_calls = None
        capture_unavailable = True

    if trace_id and created_at:
        _record_success(
            buffer, redactor, trace_id, epoch,
            created_at, method, context,
            captured_messages, output_content,
            output_tool_calls=output_tool_calls,
            captured_tools=captured_tools,
            detail_availability=(
                "diagnostic_unavailable" if capture_unavailable else "full_text"
            ),
        )
    return result


def observe_multimodal(
    buffer: TraceBuffer | None,
    redactor: SecretRedactor | None,
    epoch: str | None,
    content: list[dict],
    invoke_fn: Callable[[list[dict]], str],
) -> str:
    """Observe a multimodal/vision call.

    Only captures text blocks and media metadata — never raw image bytes
    or data URLs.
    """
    context, trace_id, created_at = _capture_metadata(buffer, redactor, epoch)

    captured_text_parts: list[dict] = []
    media_metadata: list[dict] = []
    capture_unavailable = False
    if trace_id and buffer and epoch and redactor:
        try:
            for block in content:
                if not isinstance(block, dict):
                    continue
                block_type = block.get("type", "")
                if block_type == "text":
                    text_value = block.get("text", "")
                    captured_text_parts.append({
                        "type": "text",
                        "text": redactor.redact(text_value),
                    })
                elif block_type == "image_url":
                    url = block.get("image_url", {}).get("url", "")
                    media_metadata.append({
                        "type": "image_url",
                        "media_type": "image",
                        "byte_count": len(url) if url else 0,
                    })
        except Exception:
            captured_text_parts = []
            media_metadata = []
            capture_unavailable = True

    captured_input: str | None = None
    if captured_text_parts:
        captured_input = json.dumps(captured_text_parts, ensure_ascii=False)

    try:
        result = invoke_fn(content)
    except Exception as provider_error:
        if trace_id and created_at:
            _record_failure(
                buffer, redactor, trace_id, epoch,
                created_at, "multimodal", context, str(provider_error),
                captured_input=captured_input,
                media_metadata=media_metadata,
                detail_availability=(
                    "diagnostic_unavailable" if capture_unavailable else "full_text"
                ),
            )
        raise

    if trace_id and created_at:
        _record_success(
            buffer, redactor, trace_id, epoch,
            created_at, "multimodal", context,
            captured_input, result,
            media_metadata=media_metadata,
            detail_availability=(
                "diagnostic_unavailable" if capture_unavailable else "full_text"
            ),
        )
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _capture_metadata(
    buffer: TraceBuffer | None,
    redactor: SecretRedactor | None,
    epoch: str | None,
) -> tuple[TraceCaptureContext | None, str | None, datetime | None]:
    """Create diagnostic metadata only when capture is active.

    Any failure here is diagnostic-only; the provider invocation must still
    run and no record is written for this call.
    """
    if not buffer or not redactor or not epoch:
        return None, None, None
    try:
        return get_current_context(), uuid.uuid4().hex, datetime.now(timezone.utc)
    except Exception:
        logger.debug("debug trace metadata capture failed", exc_info=True)
        return None, None, None

def _record_success(
    buffer: TraceBuffer | None,
    redactor: SecretRedactor | None,
    trace_id: str,
    epoch: str | None,
    created_at: datetime,
    method: str,
    context: TraceCaptureContext | None,
    captured_input: str | None,
    output_content: str | None,
    output_tool_calls: str | None = None,
    captured_tools: str | None = None,
    media_metadata: list[dict] | None = None,
    detail_availability: str = "full_text",
) -> None:
    """Build an ``LLMTraceRecord`` for a succeeded invocation and add it."""
    if not buffer or not epoch:
        return
    try:
        completed_at = datetime.now(timezone.utc)

        # Normalise captured_input to a JSON string for the model field
        input_messages: str | None = captured_input
        if input_messages is None:
            input_messages = None

        try:
            redacted_output = (
                redactor.redact(output_content)
                if output_content and redactor
                else output_content
            )
            redacted_tool_calls = (
                redactor.redact(output_tool_calls)
                if output_tool_calls and redactor
                else output_tool_calls
            )
        except Exception:
            input_messages = None
            captured_tools = None
            media_metadata = None
            redacted_output = None
            redacted_tool_calls = None
            detail_availability = "diagnostic_unavailable"

        input_media_str: str | None = None
        if media_metadata:
            input_media_str = json.dumps(media_metadata, ensure_ascii=False)

        record = LLMTraceRecord(
            trace_id=trace_id,
            retention_epoch=epoch,
            created_at=created_at,
            completed_at=completed_at,
            method=method,
            source=context.source if context else "unknown",
            agent_type=context.agent_type if context else "",
            session_id=context.session_id if context else "",
            workflow_id=context.workflow_id if context else "",
            work_unit_id=context.work_unit_id if context else "",
            iteration=context.iteration if context else 0,
            input_messages=input_messages,
            input_media=input_media_str,
            input_tools=captured_tools,
            output_content=redacted_output,
            output_tool_calls=redacted_tool_calls,
            outcome="succeeded",
            error_summary="",
            linked_transition_ids=_context_links(context),
            retained_bytes=0,
            detail_availability=detail_availability,
        )
        buffer.add_record(record)
    except Exception:
        logger.debug(
            "debug trace capture failed (provider result unchanged)",
            exc_info=True,
        )


def _record_failure(
    buffer: TraceBuffer | None,
    redactor: SecretRedactor | None,
    trace_id: str,
    epoch: str | None,
    created_at: datetime,
    method: str,
    context: TraceCaptureContext | None,
    error_summary: str,
    captured_input: str | None = None,
    captured_tools: str | None = None,
    media_metadata: list[dict] | None = None,
    detail_availability: str = "full_text",
) -> None:
    """Build an ``LLMTraceRecord`` for a failed invocation and add it."""
    if not buffer or not epoch:
        return
    try:
        completed_at = datetime.now(timezone.utc)
        safe_summary = error_summary[:200] if error_summary else ""
        if redactor and safe_summary:
            try:
                safe_summary = redactor.redact(safe_summary)
            except Exception:
                safe_summary = "diagnostic_unavailable"
                detail_availability = "diagnostic_unavailable"

        input_media = (
            json.dumps(media_metadata, ensure_ascii=False)
            if media_metadata
            else None
        )
        record = LLMTraceRecord(
            trace_id=trace_id,
            retention_epoch=epoch,
            created_at=created_at,
            completed_at=completed_at,
            method=method,
            source=context.source if context else "unknown",
            agent_type=context.agent_type if context else "",
            session_id=context.session_id if context else "",
            workflow_id=context.workflow_id if context else "",
            work_unit_id=context.work_unit_id if context else "",
            iteration=context.iteration if context else 0,
            input_messages=captured_input,
            input_media=input_media,
            input_tools=captured_tools,
            output_content=None,
            output_tool_calls=None,
            outcome="failed",
            error_summary=safe_summary,
            linked_transition_ids=_context_links(context),
            retained_bytes=0,
            detail_availability=detail_availability,
        )
        buffer.add_record(record)
    except Exception:
        logger.debug(
            "debug trace failure capture failed",
            exc_info=True,
        )


def _context_links(context: TraceCaptureContext | None) -> list[str]:
    if context is None or not context.transition_id:
        return []
    return [context.transition_id]
