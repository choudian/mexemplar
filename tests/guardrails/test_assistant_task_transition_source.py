from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_new_task_router_does_not_derive_truth_from_workflow_transitions() -> None:
    source = (ROOT / "src/desktop_api/routers/assistant_tasks.py").read_text(encoding="utf-8")

    assert "workflow_transitions" not in source
    assert "build_subagent_list" not in source


def test_assistant_task_graph_is_only_accessible_via_dedicated_router() -> None:
    runtime_source = (ROOT / "src/desktop_api/assistant_runtime.py").read_text(encoding="utf-8")
    router_source = (ROOT / "src/desktop_api/routers/assistant_tasks.py").read_text(encoding="utf-8")

    # Task graph facade lives in the dedicated router, not in AssistantRuntime.
    assert "get_current_task_graph" not in runtime_source
    assert "get_current_task_graph" in router_source
    assert "TaskCollaborationService" in router_source


def test_task_collaboration_repositories_are_distinct_from_transition_log() -> None:
    repo_source = (ROOT / "src/data/repos/assistant_task_repository.py").read_text(encoding="utf-8")

    assert "WorkflowTransition" not in repo_source
    assert "workflow_transitions" not in repo_source


def test_frontend_task_state_does_not_derive_truth_from_workflow_transitions() -> None:
    # D2：前端 task store / typed API 也不得从 workflow_transitions / build_subagent_list
    # 派生任务真相，只消费 typed task UI events + 权威快照端点（FR-022/plan cutover）。
    store_source = (ROOT / "frontend/src/state/assistantTaskStore.ts").read_text(encoding="utf-8")
    api_source = (ROOT / "frontend/src/api/assistantTasks.ts").read_text(encoding="utf-8")

    assert "workflow_transitions" not in store_source
    assert "workflowTransition" not in store_source
    assert "build_subagent_list" not in store_source
    assert "workflow_transitions" not in api_source
    assert "build_subagent_list" not in api_source
