"""Build a compact, read-only execution skeleton for review."""

from __future__ import annotations

import json
from typing import Any


def _parse_json(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return json.loads(value)
    except Exception:
        return None


def _tool_calls_from(message: Any) -> list[dict[str, Any]]:
    parsed = _parse_json(getattr(message, "tool_calls", None))
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]
    if isinstance(parsed, dict):
        calls = parsed.get("tool_calls") or parsed.get("calls")
        if isinstance(calls, list):
            return [item for item in calls if isinstance(item, dict)]
    return []


def _call_name_and_args(call: dict[str, Any]) -> tuple[str, str]:
    function = call.get("function")
    if isinstance(function, dict):
        return str(function.get("name") or "?"), str(function.get("arguments") or "")
    return str(call.get("name") or "?"), str(call.get("arguments") or call.get("args") or "")


def _result_info(content: str) -> tuple[bool, int, str | None]:
    parsed = _parse_json(content)
    if not isinstance(parsed, dict):
        return True, len(content), None

    limits = parsed.get("limits") if isinstance(parsed.get("limits"), dict) else {}
    raw_size = (
        limits.get("visibleChars")
        or limits.get("rawChars")
        or limits.get("visible_chars")
        or len(content)
    )
    try:
        result_size = int(raw_size)
    except (TypeError, ValueError):
        result_size = len(content)

    output_ref = None
    references = parsed.get("references")
    if isinstance(references, list) and references:
        first = references[0]
        if isinstance(first, dict):
            output_ref = first.get("referenceId") or first.get("reference_id") or first.get("id")
    if output_ref is None:
        reference = parsed.get("reference")
        if isinstance(reference, dict):
            output_ref = (
                reference.get("referenceId") or reference.get("reference_id") or reference.get("id")
            )

    outcome = str(parsed.get("outcome") or parsed.get("status") or "success").lower()
    ok = outcome not in {"error", "failed", "failure"}
    return ok, result_size, str(output_ref) if output_ref else None


def build_skeleton(session_id: str, message_repo) -> dict[str, Any]:
    messages = message_repo.get_all(session_id)
    steps: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    iterations = 0
    delegated = False

    for message in messages:
        role = getattr(message, "role", None)
        if role == "assistant":
            calls = _tool_calls_from(message)
            if calls:
                iterations += 1
            for call in calls:
                name, args = _call_name_and_args(call)
                if name in {"delegate_to_subagent", "delegate_to_specialist"}:
                    delegated = True
                step = {
                    "index": len(steps),
                    "tool": name,
                    "args_summary": args[:200],
                    "ok": True,
                    "result_size": 0,
                    "output_ref": None,
                }
                steps.append(step)
                pending.append(step)
        elif role == "tool" and pending:
            step = pending.pop(0)
            content = str(getattr(message, "content", "") or "")
            ok, result_size, output_ref = _result_info(content)
            step["ok"] = ok
            step["result_size"] = result_size
            step["output_ref"] = output_ref

    return {
        "session_id": session_id,
        "steps": steps,
        "iterations": iterations,
        "delegated": delegated,
    }
