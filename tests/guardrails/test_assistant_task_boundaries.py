from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_assistant_task_router_does_not_import_repositories() -> None:
    source = _read("src/desktop_api/routers/assistant_tasks.py")

    assert "src.data.repos" not in source
    assert "Repository" not in source


def test_task_collaboration_business_models_do_not_import_orm() -> None:
    source = _read("src/business/task_collaboration/models.py")

    assert "src.data.models_sqlite" not in source
    assert "sqlalchemy" not in source


def test_main_assistant_is_not_a_task_attempt_executor_type() -> None:
    source = _read("src/data/models_sqlite.py")

    assert "executor_type IN ('ephemeral_subagent', 'specialist')" in source
    assert "executor_type IN ('assistant'" not in source


def test_task_cutover_reads_config_through_unified_config() -> None:
    source = _read("src/business/task_collaboration/dispatcher.py")

    assert "get_unified_config" in source
    assert "config.json" not in source


def test_assistant_task_config_defaults_are_in_example_config() -> None:
    data = json.loads(_read("config.example.json"))
    assistant_tasks = data.get("assistant_tasks")

    assert assistant_tasks["unified_dispatch"]["enabled"] is True
    assert assistant_tasks["cutover"]["clean_start_guard"] is True
    assert assistant_tasks["dispatch"]["max_workers"] == 4
    assert assistant_tasks["graph"]["max_tasks"] == 200
    assert assistant_tasks["board"]["capacity"] == 50
    assert assistant_tasks["board"]["fallback_seconds"] == 60
    assert assistant_tasks["recruitment"]["min_fallback_count"] == 3
    assert assistant_tasks["attempt"]["lease_seconds"] == 120
    assert assistant_tasks["recovery"]["scan_interval_seconds"] == 30
    assert assistant_tasks["meeting"]["turn_budget"] == 12
    assert assistant_tasks["meeting"]["time_budget_seconds"] == 900
    assert assistant_tasks["api"]["default_limit"] == 50


def test_todo_service_does_not_import_brain_memory() -> None:
    source = _read("src/business/task_collaboration/todos.py")

    assert "BrainRepository" not in source
    assert "SegmentService" not in source
    assert "brain_memory" not in source
