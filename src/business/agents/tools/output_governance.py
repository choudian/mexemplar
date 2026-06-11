"""Visible-result governance and raw-output recovery for built-in tools."""

from __future__ import annotations

import json
import logging
import copy
from pathlib import Path
from typing import Any, Mapping

from src.business.agents.tools.builtin_config import get_config_int
from src.business.agents.tools.builtin_contracts import (
    OUTCOME_REJECTED,
    UPGRADED_BUILTIN_TOOL_NAMES,
    ToolOutputReference,
    current_tool_runtime,
    error_json,
    parse_envelope,
    runtime_session_id,
    runtime_workspace_root,
    standardized_error_to_envelope,
    success_json,
)
from src.business.agents.tools.file_tools import _looks_binary, _redact_text
from src.business.agents.tools.semantic_summary import (
    build_deterministic_preview,
    extract_deterministic_facts,
    normalize_tool_output,
    resolve_extraction_goal,
    summarize_tool_output,
)
from src.data.repos.tool_output_repository import ToolOutputRepository
from src.data.unified_config import get_unified_config
from src.utils.agent_tool_health import (
    get_agent_tool_health_counters,
    increment_agent_tool_health,
    record_retention_cleanup,
)

logger = logging.getLogger(__name__)


def _governance_fallback(*, tool_name: str, raw_chars: int | None = None) -> str:
    increment_agent_tool_health(compaction_fallbacks=1)
    payload: dict[str, Any] = {
        "compacted": True,
        "preview": "[tool output withheld after governance failure]",
    }
    if raw_chars is not None:
        payload["rawChars"] = raw_chars
    return error_json(
        tool_name,
        "compaction_failed_fallback",
        "Tool output governance failed; raw output was withheld.",
        payload=payload,
        warnings=["compaction_failed_fallback"],
    )


def governance_failure_fallback(*, tool_name: str, content: str) -> str:
    raw_chars = len(content) if isinstance(content, str) else 0
    return _governance_fallback(tool_name=tool_name, raw_chars=raw_chars)


def governance_double_failure_fallback(*, tool_name: str) -> str:
    """Last-resort envelope when both governance and governance_failure_fallback throw."""
    return _governance_fallback(tool_name=tool_name)


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_text(value)[0]
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact_value(val) for key, val in value.items() if _safe_key(key)}
    return value


def _safe_key(key: str) -> bool:
    lowered = str(key).lower()
    return lowered not in {"storage_key", "storagepath", "storage_path", "blob_path", "raw_path"}


def _json_dumps(obj: dict[str, Any]) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)


def _fit_compacted_envelope(
    obj: dict[str, Any],
    *,
    preview_source: str,
    visible_cap: int,
    tool_name: str,
    extraction_goal: str,
    content_type: str,
) -> str:
    """Fit the final compact envelope inside the configured visible cap when possible."""
    payload = obj.get("payload")
    if not isinstance(payload, dict):
        return _json_dumps(obj)

    preview_budget = max(0, min(visible_cap // 2, visible_cap - 1024))
    if preview_budget <= 0:
        preview_budget = max(0, visible_cap // 4)
    for _ in range(12):
        payload["preview"] = (
            build_deterministic_preview(
                preview_source,
                preview_budget,
                tool_name=tool_name,
                extraction_goal=extraction_goal,
                content_type=content_type,
            )
            if preview_budget
            else ""
        )
        encoded = _json_dumps(obj)
        if len(encoded) <= visible_cap:
            return encoded
        overflow = len(encoded) - visible_cap
        if preview_budget <= 0:
            break
        preview_budget = max(0, preview_budget - overflow - 32)

    payload["preview"] = ""
    encoded = _json_dumps(obj)
    if len(encoded) <= visible_cap:
        return encoded

    payload["originalPayloadKeys"] = payload.get("originalPayloadKeys", [])[:8]
    warnings = obj.get("warnings")
    if isinstance(warnings, list):
        obj["warnings"] = warnings[:4]
    encoded = _json_dumps(obj)
    if len(encoded) <= visible_cap:
        return encoded

    semantic = payload.get("semanticSummary")
    if isinstance(semantic, dict):
        for key in ("nextActions", "importantData", "keyFindings", "errors"):
            value = semantic.get(key)
            if isinstance(value, list):
                semantic[key] = value[:2]
        semantic["overview"] = str(semantic.get("overview") or "")[:600]
        encoded = _json_dumps(obj)
        if len(encoded) <= visible_cap:
            return encoded
        payload.pop("semanticSummary", None)
    return _json_dumps(obj)


def _reports_truncation(obj: Mapping[str, Any] | None) -> bool:
    if not isinstance(obj, Mapping):
        return False
    limits = obj.get("limits")
    if isinstance(limits, Mapping):
        if any(bool(limits.get(key)) for key in ("truncated", "clipped", "cropped", "hasMore")):
            return True
        status = str(limits.get("status") or "").lower()
        if status in {"truncated", "clipped", "cropped"}:
            return True
    payload = obj.get("payload")
    if isinstance(payload, Mapping):
        if bool(payload.get("truncated")) or bool(payload.get("hasMore")):
            return True
        status = str(payload.get("status") or "").lower()
        if status in {"truncated", "clipped", "cropped"}:
            return True
    warnings = obj.get("warnings")
    if isinstance(warnings, list):
        return any(
            any(token in str(item).lower() for token in ("truncat", "clip", "crop"))
            for item in warnings
        )
    return False


def _authorized_existing_references(
    *,
    references: list[Any],
    session_id: str,
    workspace_root: str | Path | None,
) -> tuple[list[dict[str, Any]], str | None]:
    authorized: list[dict[str, Any]] = []
    source_text: str | None = None
    seen: set[str] = set()
    repo = ToolOutputRepository()
    for item in references:
        if not isinstance(item, dict):
            continue
        reference_id = str(item.get("referenceId") or "")
        if not reference_id or reference_id in seen:
            continue
        seen.add(reference_id)
        loaded = repo.load_authorized_bytes(
            reference_id,
            session_id=session_id,
            workspace_root=workspace_root or runtime_workspace_root(),
        )
        if loaded is None:
            continue
        model = loaded.model
        authorized.append(
            ToolOutputReference(
                reference_id=model.reference_id,
                kind=model.kind,
                size_bytes=model.size_bytes,
                content_type=model.content_type,
                sha256=model.sha256,
                expires_at=model.expires_at.isoformat() if model.expires_at else None,
            ).to_dict()
        )
        if source_text is None:
            source_text = loaded.data.decode("utf-8", errors="replace")
    return authorized, source_text


def govern_tool_result(
    *,
    tool_name: str,
    tool_call_id: str,
    session_id: str,
    content: str,
    tool_args: Mapping[str, Any] | None = None,
    workspace_root: str | Path | None = None,
) -> str:
    """Apply deterministic and optional semantic governance before persistence."""
    is_upgraded = tool_name in UPGRADED_BUILTIN_TOOL_NAMES
    obj = parse_envelope(content)
    config = get_unified_config()
    trigger_chars = config.get_agent_tools_output_semantic_summary_trigger_chars()
    visible_cap = get_config_int("get_agent_tools_output_visible_char_cap", 12000, maximum=50000)
    plain_custom = not is_upgraded and obj is None
    if plain_custom and len(content) < trigger_chars and len(content) <= visible_cap:
        return content

    if obj is not None and obj.get("tool") != tool_name:
        obj = None
    if obj is None:
        converted = standardized_error_to_envelope(tool_name, content)
        if converted is None:
            if not is_upgraded:
                obj = json.loads(success_json(tool_name, {"content": content}))
        else:
            obj = parse_envelope(converted)
            content = converted
    if obj is None:
        return error_json(
            tool_name,
            "handler_contract_violation",
            "Built-in tool returned an invalid result envelope; raw output was withheld.",
            payload={"compacted": True, "rawChars": len(content)},
            warnings=["invalid_tool_result_withheld"],
        )

    raw_reference_text = content
    visible_obj = copy.deepcopy(obj)
    visible_obj["payload"] = _redact_value(visible_obj.get("payload") or {})
    if "error" in visible_obj:
        visible_obj["error"] = _redact_value(visible_obj["error"])
    raw_text = _json_dumps(visible_obj)
    max_artifact = get_config_int(
        "get_agent_tools_output_max_artifact_bytes", 10_485_760, maximum=104_857_600
    )
    existing_references = list(visible_obj.get("references") or [])
    must_compact = (
        len(raw_reference_text) >= trigger_chars
        or len(raw_text) > visible_cap
        or bool(existing_references)
        or _reports_truncation(visible_obj)
    )
    if not must_compact:
        return raw_text

    warnings = list(visible_obj.get("warnings") or [])
    references, referenced_source = _authorized_existing_references(
        references=existing_references,
        session_id=session_id,
        workspace_root=workspace_root,
    )
    payload_keys = sorted(str(key) for key in (visible_obj.get("payload") or {}).keys())
    source_for_normalization = (
        raw_reference_text
        if tool_name == "load_tool_output"
        else referenced_source or raw_reference_text
    )
    normalized = normalize_tool_output(
        tool_name,
        source_for_normalization,
        visible_obj,
    )
    facts = extract_deterministic_facts(visible_obj)
    facts.update(normalized.facts)
    extraction_goal = resolve_extraction_goal(tool_name, tool_args)
    compact_payload = {
        "compacted": True,
        "originalOutcome": visible_obj.get("outcome"),
        "originalPayloadKeys": payload_keys,
        "rawChars": len(source_for_normalization),
        "facts": facts,
        "preview": "",
    }
    raw_bytes = raw_reference_text.encode("utf-8")
    if not references and len(raw_bytes) <= max_artifact:
        try:
            repo = ToolOutputRepository()
            model = repo.create_reference(
                session_id=session_id,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                kind="tool_payload",
                data=raw_reference_text,
                workspace_root=workspace_root or runtime_workspace_root(),
                retention_days=get_config_int(
                    "get_agent_tools_output_retention_days", 14, maximum=90
                ),
                content_type="application/json",
                redaction_profile="visible_preview_redacted",
            )
            references.append(
                ToolOutputReference(
                    reference_id=model.reference_id,
                    kind=model.kind,
                    size_bytes=model.size_bytes,
                    content_type=model.content_type,
                    sha256=model.sha256,
                    expires_at=model.expires_at.isoformat() if model.expires_at else None,
                ).to_dict()
            )
            warnings.append("tool_output_compacted")
        except Exception:
            logger.warning("[agent_tools] raw reference creation failed", exc_info=True)
            warnings.append("compaction_failed_fallback")
            increment_agent_tool_health(raw_reference_create_failures=1, compaction_fallbacks=1)
    else:
        if not references and len(raw_bytes) > max_artifact:
            warnings.append("max_artifact_bytes_exceeded")
            increment_agent_tool_health(compaction_fallbacks=1)

    try:
        semantic_summary = summarize_tool_output(
            tool_name=tool_name,
            tool_args=tool_args,
            source_text=normalized.text,
            source_obj=None,
            config=config,
        )
    except Exception:
        logger.warning(
            "[agent_tools] semantic tool-output summary failed: tool=%s",
            tool_name,
            exc_info=True,
        )
        semantic_summary = None
    if semantic_summary is not None:
        compact_payload["semanticSummary"] = semantic_summary
    if "tool_output_compacted" not in warnings:
        warnings.append("tool_output_compacted")
    increment_agent_tool_health(compacted_outputs=1)

    visible_obj["payload"] = compact_payload
    visible_obj["references"] = references
    visible_obj["warnings"] = warnings
    return _fit_compacted_envelope(
        visible_obj,
        preview_source=normalized.text,
        visible_cap=visible_cap,
        tool_name=tool_name,
        extraction_goal=extraction_goal,
        content_type=normalized.content_type,
    )


def load_tool_output_handler(
    referenceId: str,
    offset: int = 0,
    maxBytes: int = 64000,
    renderAs: str = "text",
    extractionGoal: str | None = None,
    sessionId: str | None = None,
    workspaceRoot: str | None = None,
) -> str:
    tool = "load_tool_output"
    runtime = current_tool_runtime()
    session_id = runtime.session_id if runtime is not None else sessionId or runtime_session_id()
    workspace = (
        runtime.workspace_root if runtime is not None else runtime_workspace_root(workspaceRoot)
    )
    repo = ToolOutputRepository()
    model = repo.get_by_reference_id(referenceId)
    if model is None:
        increment_agent_tool_health(raw_reference_load_failures=1)
        return error_json(
            tool,
            "output_reference_not_found",
            "Output reference was not found.",
            outcome=OUTCOME_REJECTED,
            payload={"referenceId": referenceId},
        )
    if model.session_id != session_id:
        return error_json(
            tool,
            "permission_denied",
            "Output reference belongs to a different session.",
            outcome=OUTCOME_REJECTED,
            payload={"referenceId": referenceId},
        )
    if repo.is_expired(model):
        repo.mark_expired(referenceId)
        model.status = "expired"
    if model.status == "expired":
        return error_json(
            tool,
            "output_reference_expired",
            "Output reference has expired.",
            outcome=OUTCOME_REJECTED,
            payload={"referenceId": referenceId},
        )
    if model.status != "active":
        return error_json(
            tool,
            "output_reference_not_found",
            "Output reference is no longer active.",
            outcome=OUTCOME_REJECTED,
            payload={"referenceId": referenceId},
        )
    loaded = repo.load_authorized_bytes(
        referenceId,
        session_id=session_id,
        workspace_root=workspace,
    )
    if loaded is None:
        increment_agent_tool_health(raw_reference_load_failures=1)
        return error_json(
            tool,
            "output_reference_not_found",
            "Output reference blob is missing or unauthorized.",
            outcome=OUTCOME_REJECTED,
            payload={"referenceId": referenceId},
        )
    data = loaded.data
    start = max(0, int(offset or 0))
    limit = max(1, min(int(maxBytes or 64000), 1_000_000))
    window = data[start : start + limit]
    if renderAs != "text" or _looks_binary(Path(referenceId), window[:4096]):
        return error_json(
            tool,
            "unsupported_binary",
            "Binary/media raw output is not rendered as text.",
            outcome=OUTCOME_REJECTED,
            payload={
                "referenceId": referenceId,
                "kind": model.kind,
                "sizeBytes": model.size_bytes,
                "contentType": model.content_type,
            },
        )
    text = window.decode("utf-8", errors="replace")
    redacted, redactions = _redact_text(text)
    has_more = start + len(window) < len(data)
    return success_json(
        tool,
        {
            "referenceId": referenceId,
            "kind": model.kind,
            "offset": start,
            "bytesReturned": len(window),
            "hasMore": has_more,
            "content": redacted,
            "redactions": redactions,
        },
        limits={
            "truncated": has_more,
            "rawBytes": len(data),
            "visibleChars": len(redacted),
            "hasMore": has_more,
            "nextPageToken": str(start + len(window)) if has_more else None,
        },
        references=[
            ToolOutputReference(
                reference_id=model.reference_id,
                kind=model.kind,
                size_bytes=model.size_bytes,
                content_type=model.content_type,
                sha256=model.sha256,
                expires_at=model.expires_at.isoformat() if model.expires_at else None,
            ).to_dict()
        ],
    )


def cleanup_tool_outputs() -> dict[str, int]:
    try:
        result = ToolOutputRepository().cleanup_expired()
        record_retention_cleanup(result)
        return result
    except Exception:
        logger.warning("[agent_tools] tool output cleanup failed", exc_info=True)
        increment_agent_tool_health(cleanup_failures=1, retention_cleanup_failures=1)
        counters = get_agent_tool_health_counters()
        return {"cleanupFailures": counters["cleanup_failures"]}


def get_tool_output_health_counters() -> dict[str, int]:
    return get_agent_tool_health_counters()
