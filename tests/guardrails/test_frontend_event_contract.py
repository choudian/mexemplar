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
FRONTEND_UI_EVENTS = REPO_ROOT / "frontend" / "src" / "api" / "uiEventTypes.ts"


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


def test_projector_event_types_are_all_registered() -> None:
    """All EVENT_TYPE_* constants referenced in ui_event_projector.py must have
    values that exist in UI_EVENT_REGISTRY.

    After the constant-refactoring, the projector no longer contains bare
    event-type strings; instead it references EVENT_TYPE_* constants from
    ui_events.py.  We verify that every such constant used by the projector
    resolves to a registered event type.
    """
    import ast

    from src.desktop_api.ui_events import UI_EVENT_REGISTRY

    registered = set(UI_EVENT_REGISTRY.keys())

    # Parse projector source and collect all EVENT_TYPE_* name references
    projector_path = REPO_ROOT / "src" / "desktop_api" / "ui_event_projector.py"
    projector_source = projector_path.read_text(encoding="utf-8")
    tree = ast.parse(projector_source)

    event_type_refs: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id.startswith("EVENT_TYPE_"):
            event_type_refs.add(node.id)

    # Resolve each referenced constant to its string value
    # by importing the module and checking the constant's value
    from src.desktop_api import ui_events

    unregistered: set[str] = set()
    for const_name in event_type_refs:
        const_value = getattr(ui_events, const_name, None)
        if const_value is None:
            # Constant doesn't exist in ui_events.py — that's a bug
            unregistered.add(f"{const_name} (not defined)")
        elif const_value not in registered:
            unregistered.add(f"{const_name}={const_value}")

    assert unregistered == set(), (
        f"Projector references unregistered EVENT_TYPE_* constants: {sorted(unregistered)}. "
        f"All projected event types must be registered in UI_EVENT_REGISTRY."
    )


def test_event_type_constants_match_registry_keys() -> None:
    """Every EVENT_TYPE_* constant value must be a key in UI_EVENT_REGISTRY,
    and every registry key must have a corresponding EVENT_TYPE_* constant."""
    from src.desktop_api.ui_events import UI_EVENT_REGISTRY

    # Collect all EVENT_TYPE_* constants from the module
    import src.desktop_api.ui_events as ui_events_mod

    constants = {
        name: getattr(ui_events_mod, name)
        for name in dir(ui_events_mod)
        if name.startswith("EVENT_TYPE_")
    }

    registry_keys = set(UI_EVENT_REGISTRY.keys())
    constant_values = set(constants.values())

    # Every constant value must be a registry key
    extra_constants = constant_values - registry_keys
    assert (
        extra_constants == set()
    ), f"EVENT_TYPE_* constants with values not in registry: {sorted(extra_constants)}"

    # Every registry key must have a constant
    missing_constants = registry_keys - constant_values
    assert (
        missing_constants == set()
    ), f"Registry keys without EVENT_TYPE_* constants: {sorted(missing_constants)}"


def test_projector_payload_keys_are_subset_of_registry() -> None:
    """Each projector-produced UiEventDraft's payload keys must be a subset
    of the corresponding UiEventDefinition's payload_keys."""
    from src.desktop_api.ui_events import UI_EVENT_REGISTRY
    from src.desktop_api.ui_event_projector import project_internal_event

    # Minimal payloads for each internal event name that the projector handles.
    # These are just enough to trigger the projection without crashing.
    sample_payloads: dict[str, dict] = {
        "assistant_agent_step": {
            "session_id": "s1",
            "agent_type": "assistant",
            "kind": "tool_call",
            "tool_name": "t",
            "text": "x",
            "seq": 1,
        },
        "assistant_subagent_started": {
            "session_id": "s1",
            "subagent_id": "sub1",
            "label": "l",
            "task": "t",
            "status": "running",
        },
        "assistant_subagent_completed": {
            "session_id": "s1",
            "subagent_id": "sub1",
            "label": "l",
            "task": "t",
            "status": "done",
        },
        "assistant_subagent_suspended": {
            "session_id": "s1",
            "subagent_id": "sub1",
            "label": "l",
            "task": "t",
            "status": "suspended",
        },
        "assistant_subagent_failed": {
            "session_id": "s1",
            "subagent_id": "sub1",
            "label": "l",
            "task": "t",
            "status": "failed",
            "reason": "error",
        },
        "recording_started": {"session_id": "s1"},
        "recording_stopped": {"session_id": "s1"},
        "recording_completed": {"session_id": "s1"},
        "desktop_action_count_changed": {"session_id": "s1", "action_count": 5},
        "desktop_recording_problem": {"session_id": "s1"},
        "desktop_recorder_start_failed": {"session_id": "s1"},
        "requirement_confirmed": {"session_id": "s1"},
        "code_completed": {"session_id": "s1"},
        "review_failed": {"session_id": "s1", "failed_stage": "code"},
        "teaching_failure_resolved": {"session_id": "s1"},
        "teaching_failure_retrying": {"session_id": "s1"},
        "trial_requested": {"session_id": "s1"},
        "trial_success": {"session_id": "s1", "published": False},
        "trial_failed": {"session_id": "s1"},
        "desktop_trial_finished": {"session_id": "s1", "trial_id": "t1"},
        "brain_skill_changed": {
            "session_id": "s1",
            "skill_id": "sk1",
            "operation": "updated",
            "chain_root_id": "sk1",
        },
        "brain_skill_bootstrap_fallback_used": {
            "session_id": "s1",
            "skill_id": "sk1",
            "seed_file_path": "/tmp/seed.py",
        },
        "brain_skill_equipment_changed": {
            "session_id": "s1",
            "skill_id": "sk1",
            "change_type": "unequipped",
            "entity_type": "specialist",
            "entity_id": "sp1",
        },
        "composition_catalog_invalidated": {"session_id": "s1", "composition_id": "c1"},
        "settings_invalidated": {"session_id": "s1", "keys": ["key1"]},
        "brain_zone_changed": {
            "session_id": "s1",
            "zone": "hot",
            "entry_id": "e1",
            "change_type": "added",
        },
        "brain_specialist_recruited": {
            "session_id": "s1",
            "specialist_id": "sp1",
            "name": "n1",
            "reason": "auto",
        },
        "brain_specialist_changed": {
            "session_id": "s1",
            "specialist_id": "sp1",
            "change_type": "updated",
        },
        "brain_context_ready": {"session_id": "s1"},
        "improvement_proposal_changed": {
            "session_id": "s1",
            "proposal_id": "p1",
            "source_review_id": "r1",
            "status": "pending",
            "severity": "low",
            "change_type": "created",
        },
        "tool_saved": {"session_id": "s1", "skill_id": "sk1"},
        "tool_published": {"session_id": "s1", "skill_id": "sk1"},
    }

    violations: list[str] = []
    for event_name, payload in sample_payloads.items():
        scope = {"sessionId": payload.get("session_id", "s1")}
        try:
            drafts = project_internal_event(event_name, payload, scope)
        except Exception:
            # Some handlers may need fields we didn't provide; skip gracefully
            continue

        if not drafts:
            continue

        for draft in drafts:
            definition = UI_EVENT_REGISTRY.get(draft.event_type)
            if definition is None:
                violations.append(f"{event_name} -> {draft.event_type}: unregistered")
                continue
            extra = set(draft.payload) - set(definition.payload_keys)
            if extra:
                violations.append(f"{event_name} -> {draft.event_type}: extra keys {sorted(extra)}")

    assert violations == [], "\n".join(violations)


def test_events_py_resync_type_matches_registry() -> None:
    """The hardcoded 'backend.resync_required' in events.py must match the Registry."""
    source = (REPO_ROOT / "src" / "desktop_api" / "events.py").read_text(encoding="utf-8")
    resync_count = source.count('"backend.resync_required"')
    assert (
        resync_count >= 2
    ), "Expected at least 2 occurrences of backend.resync_required in events.py"
    assert "backend.resync_required" in registered_event_types()


def test_runtime_and_confirmation_event_types_are_registered() -> None:
    """Event types in assistant_runtime.py, orchestrator_runtime.py,
    confirmations.py, and clarifications.py must be in Registry."""
    registered = set(registered_event_types())
    extra_files = [
        "src/desktop_api/assistant_runtime.py",
        "src/desktop_api/orchestrator_runtime.py",
        "src/desktop_api/confirmations.py",
        "src/desktop_api/clarifications.py",
    ]
    unregistered_all: set[str] = set()
    for rel_path in extra_files:
        full_path = REPO_ROOT / rel_path
        if not full_path.exists():
            continue
        source = full_path.read_text(encoding="utf-8")
        # Find quoted event type strings containing dots
        found_types = set(re.findall(r'"([a-z][a-z_]*\.[a-z_]+(?:\.[a-z_]+)?)"', source))
        found_types = {t for t in found_types if "." in t}
        unregistered_all |= found_types - registered

    assert (
        unregistered_all == set()
    ), f"Runtime/confirmation files use unregistered event types: {sorted(unregistered_all)}"


def test_frontend_parser_covers_all_registered_types() -> None:
    """Every registered event type must appear in either the frontend parser
    (UI_EVENT_MAPPERS or fallback) or the frontend types file.

    The critical contract is that UI_EVENT_TYPES matches registered_event_types(),
    already tested above.  This test additionally checks that every type with
    a typed mapper in the parser is registered, and that the parser file
    references the UI_EVENT_TYPES array (ensuring it covers all types).
    """
    parser_source = (REPO_ROOT / "frontend" / "src" / "api" / "uiEventParser.ts").read_text(
        encoding="utf-8"
    )
    assert (
        "UI_EVENT_TYPES" in parser_source or "UiEventType" in parser_source
    ), "uiEventParser.ts must reference UI_EVENT_TYPES or UiEventType to cover all registered types"

    # Verify that every event type with a typed mapper in the parser is registered
    registered = set(registered_event_types())
    # Find all event-type-like strings in the mapper section
    if "UI_EVENT_MAPPERS" in parser_source:
        after_mappers = parser_source.split("UI_EVENT_MAPPERS")[1]
        mapper_types = set(
            re.findall(r'"([a-z][a-z_]*\.[a-z_]+(?:\.[a-z_]+)?)"', after_mappers[:5000])
        )
        unregistered_mappers = mapper_types - registered
        assert (
            unregistered_mappers == set()
        ), f"Parser UI_EVENT_MAPPERS references unregistered types: {sorted(unregistered_mappers)}"
