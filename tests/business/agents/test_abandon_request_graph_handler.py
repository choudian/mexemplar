"""Tests for abandon_request_graph handler (024 C3)."""

from __future__ import annotations

import json

from src.business.agents.tools.assistant_tools import create_abandon_request_graph_handler
from src.business.task_collaboration.service import TaskCollaborationService
from src.data.repos import AssistantTaskRepository

_SESSION_ID = "test_abandon_graph_session"


def _build_graph_with_children() -> dict:
    """Helper: build a root + 2 children graph, return {graph_id, root_id, child_ids}."""
    service = TaskCollaborationService()
    graph_id = service.create_root_graph(
        session_id=_SESSION_ID,
        title="root task",
        description="root task",
    )
    task_repo = AssistantTaskRepository()
    root = task_repo.list_graph_tasks(graph_id)[0]
    child_a = service.create_child_task(
        graph_id=graph_id,
        session_id=_SESSION_ID,
        parent_task_id=root.task_id,
        title="child A",
        description="child A",
    )
    child_b = service.create_child_task(
        graph_id=graph_id,
        session_id=_SESSION_ID,
        parent_task_id=root.task_id,
        title="child B",
        description="child B",
    )
    return {"graph_id": graph_id, "root_id": root.task_id, "child_ids": [child_a, child_b]}


class TestAbandonRequestGraphHandler:
    """C3: abandon_request_graph handler wraps fail_root_graph."""

    def test_abandon_marks_root_abandoned_and_children_cancelled(self) -> None:
        """Abandoning a graph: root is ABANDONED, children are CANCELLED."""
        info = _build_graph_with_children()
        handler = create_abandon_request_graph_handler(_SESSION_ID)

        result_json = handler(safeSummary="整个请求无法完成")
        result = json.loads(result_json)

        assert result.get("abandoned") is True
        assert result["graphId"] == info["graph_id"]
        assert result["rootTaskId"] == info["root_id"]
        assert result["taskStatus"] == "abandoned"

        task_repo = AssistantTaskRepository()
        root_task = task_repo.get_task(info["root_id"])
        assert root_task.status == "abandoned"

        for child_id in info["child_ids"]:
            child_task = task_repo.get_task(child_id)
            assert child_task.status == "cancelled"

    def test_abandon_no_active_graph_returns_error_json(self) -> None:
        """When there is no active graph, handler returns error_json (no exception)."""
        handler = create_abandon_request_graph_handler("session_without_graph")

        result_json = handler(safeSummary="nothing to abandon")
        result = json.loads(result_json)

        # _run_task_service wraps LookupError as error_json
        assert result.get("success") is False

    def test_abandon_schema_has_correct_name(self) -> None:
        from src.business.agents.tools.assistant_tools import ABANDON_REQUEST_GRAPH_SCHEMA

        assert ABANDON_REQUEST_GRAPH_SCHEMA["function"]["name"] == "abandon_request_graph"

    def test_abandon_schema_requires_safe_summary(self) -> None:
        from src.business.agents.tools.assistant_tools import ABANDON_REQUEST_GRAPH_SCHEMA

        required = ABANDON_REQUEST_GRAPH_SCHEMA["function"]["parameters"]["required"]
        assert "safeSummary" in required
