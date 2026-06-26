"""I18-3: mutate_task_graph add_dependency / remove_dependency success and error paths.

Uses TaskCollaborationService directly (not through tool handlers) to verify
that add_dependency creates edges and remove_dependency deletes them, and that
removing a nonexistent edge is rejected with a reason.
"""

from __future__ import annotations

from src.business.task_collaboration.service import TaskCollaborationService
from src.data.repos.base_repository import generate_id


def _build_graph_3_nodes():
    """Build a graph with 3 independent nodes; return (graph_id, node_task_ids, session_id)."""
    session_id = generate_id("sess")
    with TaskCollaborationService() as svc:
        result = svc.build_task_graph(
            session_id=session_id,
            nodes=[
                {"nodeId": "n1", "title": "A", "description": "First"},
                {"nodeId": "n2", "title": "B", "description": "Second"},
                {"nodeId": "n3", "title": "C", "description": "Third"},
            ],
        )
    return result["graphId"], result["nodeTaskIds"], session_id


def _edge_exists(graph_id: str, source_task_id: str, target_task_id: str) -> bool:
    """Check if a dependency edge exists between source and target in the graph."""
    with TaskCollaborationService() as svc:
        edges = svc._tasks.list_graph_edges(graph_id)
    return any(
        e.source_task_id == source_task_id
        and e.target_task_id == target_task_id
        and e.edge_type == "dependency"
        for e in edges
    )


class TestMutateAddDependency:
    def test_add_dependency_creates_edge(self):
        """add_dependency op creates a dependency edge between two nodes."""
        graph_id, node_ids, session_id = _build_graph_3_nodes()
        n1, n2 = node_ids["n1"], node_ids["n2"]

        with TaskCollaborationService() as svc:
            result = svc.mutate_task_graph(
                graph_id=graph_id,
                session_id=session_id,
                changes=[{"op": "add_dependency", "from": n1, "to": n2}],
            )

        assert len(result["applied"]) == 1
        assert result["applied"][0]["op"] == "add_dependency"
        assert _edge_exists(graph_id, n1, n2)

    def test_add_dependency_shows_in_snapshot(self):
        """Edge created by add_dependency is visible in graph snapshot."""
        graph_id, node_ids, session_id = _build_graph_3_nodes()
        n1, n2 = node_ids["n1"], node_ids["n2"]

        with TaskCollaborationService() as svc:
            svc.mutate_task_graph(
                graph_id=graph_id,
                session_id=session_id,
                changes=[{"op": "add_dependency", "from": n1, "to": n2}],
            )
            snapshot = svc.get_graph_snapshot(session_id=session_id, graph_id=graph_id)

        assert snapshot is not None
        dep_edges = [
            e for e in snapshot.edges
            if e.source_task_id == n1 and e.target_task_id == n2 and e.type == "dependency"
        ]
        assert len(dep_edges) == 1


class TestMutateRemoveDependency:
    def test_remove_dependency_deletes_edge(self):
        """remove_dependency op deletes an existing dependency edge."""
        graph_id, node_ids, session_id = _build_graph_3_nodes()
        n1, n2 = node_ids["n1"], node_ids["n2"]

        with TaskCollaborationService() as svc:
            # First add the edge
            svc.mutate_task_graph(
                graph_id=graph_id,
                session_id=session_id,
                changes=[{"op": "add_dependency", "from": n1, "to": n2}],
            )
            assert _edge_exists(graph_id, n1, n2)

            # Now remove it
            result = svc.mutate_task_graph(
                graph_id=graph_id,
                session_id=session_id,
                changes=[{"op": "remove_dependency", "from": n1, "to": n2}],
            )

        assert len(result["applied"]) == 1
        assert result["applied"][0]["op"] == "remove_dependency"
        assert not _edge_exists(graph_id, n1, n2)

    def test_remove_dependency_reflected_in_snapshot(self):
        """Edge removed by remove_dependency is gone from graph snapshot."""
        graph_id, node_ids, session_id = _build_graph_3_nodes()
        n1, n2 = node_ids["n1"], node_ids["n2"]

        with TaskCollaborationService() as svc:
            svc.mutate_task_graph(
                graph_id=graph_id,
                session_id=session_id,
                changes=[{"op": "add_dependency", "from": n1, "to": n2}],
            )
            svc.mutate_task_graph(
                graph_id=graph_id,
                session_id=session_id,
                changes=[{"op": "remove_dependency", "from": n1, "to": n2}],
            )
            snapshot = svc.get_graph_snapshot(session_id=session_id, graph_id=graph_id)

        assert snapshot is not None
        dep_edges = [
            e for e in snapshot.edges
            if e.source_task_id == n1 and e.target_task_id == n2 and e.type == "dependency"
        ]
        assert len(dep_edges) == 0


class TestMutateRemoveNonexistentDependency:
    def test_remove_nonexistent_dependency_rejected(self):
        """remove_dependency on a nonexistent edge is rejected with a reason."""
        graph_id, node_ids, session_id = _build_graph_3_nodes()
        n1, n3 = node_ids["n1"], node_ids["n3"]

        with TaskCollaborationService() as svc:
            result = svc.mutate_task_graph(
                graph_id=graph_id,
                session_id=session_id,
                changes=[{"op": "remove_dependency", "from": n1, "to": n3}],
            )

        assert len(result["rejected"]) == 1
        assert result["rejected"][0]["op"] == "remove_dependency"
        assert result["rejected"][0].get("reason")

    def test_remove_nonexistent_dependency_no_applied(self):
        """remove_dependency on a nonexistent edge produces no applied changes."""
        graph_id, node_ids, session_id = _build_graph_3_nodes()
        n1, n3 = node_ids["n1"], node_ids["n3"]

        with TaskCollaborationService() as svc:
            result = svc.mutate_task_graph(
                graph_id=graph_id,
                session_id=session_id,
                changes=[{"op": "remove_dependency", "from": n1, "to": n3}],
            )

        assert len(result["applied"]) == 0
