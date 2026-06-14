from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = ROOT / "src"
INVENTORY_PATH = ROOT / "tests/guardrails/debug_provider_inventory.json"

REQUIRED_FIELDS = {
    "callsite",
    "category",
    "trace_handling",
    "real_tour_provider_handling",
    "redaction_handling",
    "owner",
    "out_of_scope_skip_rationale",
    "verification_status",
}

ALLOWED_STATUSES = {"covered", "out_of_scope"}
EXCLUDED_SCAN_FILES = {
    "src/data/unified_config.py",
}

CALL_PATTERNS = {
    "LangChainLLMClient": re.compile(r"\bLangChainLLMClient\s*\("),
    "OpenAIEmbeddings": re.compile(r"\bOpenAIEmbeddings\s*\("),
    ".invoke(": re.compile(r"\.invoke\s*\("),
    "embed_query": re.compile(r"\.embed_query\s*\("),
    "get_ai_api_key": re.compile(r"\.get_ai_api_key\s*\("),
    "get_ai_vision_api_key": re.compile(r"\.get_ai_vision_api_key\s*\("),
    "get_embedding_api_key": re.compile(r"\.get_embedding_api_key\s*\("),
    "get_compression_model_api_key": re.compile(r"\.get_compression_model_api_key\s*\("),
    "get_tool_output_summary_api_key": re.compile(r"\.get_tool_output_summary_api_key\s*\("),
}


def _load_inventory() -> list[dict]:
    data = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))
    assert data["$schema"] == "debug_provider_inventory_v1"
    return data["entries"]


def _scan_provider_callsites() -> set[str]:
    callsites: set[str] = set()
    for path in SRC_ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT).as_posix()
        if rel in EXCLUDED_SCAN_FILES:
            continue
        text = path.read_text(encoding="utf-8")
        for symbol, pattern in CALL_PATTERNS.items():
            if pattern.search(text):
                callsites.add(f"{rel}::{symbol}")
    return callsites


def test_provider_inventory_schema_is_complete_and_statused() -> None:
    entries = _load_inventory()
    callsites = [entry.get("callsite") for entry in entries]

    assert len(callsites) == len(set(callsites))
    for entry in entries:
        assert set(entry) == REQUIRED_FIELDS
        assert entry["callsite"]
        assert entry["category"]
        assert entry["trace_handling"]
        assert entry["real_tour_provider_handling"]
        assert "pending" not in entry["real_tour_provider_handling"].lower()
        assert entry["redaction_handling"]
        assert entry["owner"] in {"US2", "US3"}
        assert entry["verification_status"] in ALLOWED_STATUSES
        if entry["verification_status"] == "out_of_scope":
            assert entry["out_of_scope_skip_rationale"]


def test_provider_inventory_covers_static_model_and_credential_callsites() -> None:
    inventory_callsites = {entry["callsite"] for entry in _load_inventory()}
    scanned_callsites = _scan_provider_callsites()

    assert scanned_callsites - inventory_callsites == set()
