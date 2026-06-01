from __future__ import annotations

import json
import re
from pathlib import Path

from src.desktop_api.ui_events import (
    exported_registry_examples,
    exported_registry_payload_enums,
    registered_event_types,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND_UI_EVENTS = REPO_ROOT / "frontend" / "src" / "api" / "uiEvents.ts"


def _extract_json_object_export(source: str, name: str) -> dict:
    assignment = f"export const {name} ="
    start = source.index(assignment)
    object_start = source.index("{", start)
    depth = 0
    in_string = False
    escaped = False
    for index in range(object_start, len(source)):
        char = source[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                raw = source[object_start : index + 1]
                raw = re.sub(r",(\s*[}\]])", r"\1", raw)
                return json.loads(raw)
    raise AssertionError(f"Could not parse exported object {name}")


def test_frontend_does_not_use_internal_source_event_for_display_decisions() -> None:
    marker = b"sourceEvent"
    offenders: list[str] = []
    for path in (REPO_ROOT / "frontend" / "src").rglob("*"):
        if path.suffix not in {".ts", ".tsx"}:
            continue
        if marker in path.read_bytes():
            offenders.append(str(path.relative_to(REPO_ROOT)))

    assert offenders == []


def test_frontend_event_types_match_backend_registry() -> None:
    source = FRONTEND_UI_EVENTS.read_text(encoding="utf-8")
    match = re.search(r"UI_EVENT_TYPES\s*=\s*\[(.*?)\]\s+as const", source, re.S)
    assert match is not None
    frontend_types = set(re.findall(r'"([^"]+)"', match.group(1)))

    assert frontend_types == set(registered_event_types())


def test_frontend_event_examples_match_backend_registry() -> None:
    source = FRONTEND_UI_EVENTS.read_text(encoding="utf-8")
    frontend_examples = _extract_json_object_export(source, "UI_EVENT_EXAMPLES")

    assert frontend_examples == exported_registry_examples()


def test_frontend_payload_enums_match_backend_registry() -> None:
    source = FRONTEND_UI_EVENTS.read_text(encoding="utf-8")
    frontend_enums = _extract_json_object_export(source, "UI_EVENT_PAYLOAD_ENUMS")

    assert frontend_enums == exported_registry_payload_enums()


def test_frontend_declares_handler_domain_for_every_backend_event_type() -> None:
    source = FRONTEND_UI_EVENTS.read_text(encoding="utf-8")
    handler_domains = _extract_json_object_export(source, "UI_EVENT_HANDLER_DOMAINS")

    assert set(handler_domains) == set(registered_event_types())
    assert set(handler_domains.values()).issubset(
        {"assistant", "teaching", "skills", "skill", "compositions", "settings", "brain", "resync"}
    )


def test_backend_event_adapter_does_not_default_forward_unknown_events() -> None:
    source = (REPO_ROOT / "src" / "desktop_api" / "events.py").read_text(encoding="utf-8")
    assert '"backend.event"' not in source
    assert 'payload.setdefault("sourceEvent"' not in source
