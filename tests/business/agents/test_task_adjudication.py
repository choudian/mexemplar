from __future__ import annotations

from src.business.task_collaboration.adjudication import TaskAdjudicationService
from src.business.task_collaboration.service import TaskCollaborationService
from src.data.repos import AssistantTaskAdjudicationRepository, AssistantTaskRepository


def _pending_adjudication():
    service = TaskCollaborationService()
    graph_id = service.create_root_graph(
        session_id="ast_adj",
        title="root",
        description="root",
    )
    root = AssistantTaskRepository().list_graph_tasks(graph_id)[0]
    task_id = service.create_child_task(
        graph_id=graph_id,
        session_id="ast_adj",
        parent_task_id=root.task_id,
        title="child",
        description="child",
    )
    service.update_task_status(task_id=task_id, status="running")
    adjudication = service.create_parent_adjudication(
        task_id=task_id,
        delivered_status="done",
        safe_summary="child done",
    )
    return task_id, adjudication.adjudication_id


def test_parent_adjudication_accepts_task() -> None:
    task_id, adjudication_id = _pending_adjudication()

    result = TaskAdjudicationService().decide(
        adjudication_id=adjudication_id,
        decision="accepted",
        session_id="ast_adj",
    )

    assert result["taskStatus"] == "done"
    assert AssistantTaskRepository().get_task(task_id).status == "done"
    assert AssistantTaskAdjudicationRepository().get_by_id(adjudication_id).decision == "accepted"


def test_load_task_result_returns_raw_result_for_current_session() -> None:
    service = TaskCollaborationService()
    graph_id = service.create_root_graph(
        session_id="ast_result",
        title="root",
        description="root",
    )
    root = AssistantTaskRepository().list_graph_tasks(graph_id)[0]
    task_id = service.create_child_task(
        graph_id=graph_id,
        session_id="ast_result",
        parent_task_id=root.task_id,
        title="child",
        description="child",
    )
    adjudication = service.create_parent_adjudication(
        task_id=task_id,
        delivered_status="done",
        safe_summary="short",
        raw_result_ref="完整交付物",
    )

    result = service.load_task_result(
        session_id="ast_result",
        adjudication_id=adjudication.adjudication_id,
    )

    assert result["adjudicationId"] == adjudication.adjudication_id
    assert result["result"] == "完整交付物"
    assert result["hasResult"] is True


def test_load_task_result_rejects_other_session() -> None:
    service = TaskCollaborationService()
    graph_id = service.create_root_graph(
        session_id="ast_result_owner",
        title="root",
        description="root",
    )
    root = AssistantTaskRepository().list_graph_tasks(graph_id)[0]
    task_id = service.create_child_task(
        graph_id=graph_id,
        session_id="ast_result_owner",
        parent_task_id=root.task_id,
        title="child",
        description="child",
    )
    adjudication = service.create_parent_adjudication(
        task_id=task_id,
        delivered_status="done",
        safe_summary="short",
        raw_result_ref="完整交付物",
    )

    try:
        service.load_task_result(
            session_id="ast_other",
            adjudication_id=adjudication.adjudication_id,
        )
    except LookupError as exc:
        assert "不属于当前会话" in str(exc)
    else:
        raise AssertionError("cross-session task result read should fail")


def test_parent_adjudication_returns_task_for_rework() -> None:
    task_id, adjudication_id = _pending_adjudication()

    result = TaskAdjudicationService().decide(
        adjudication_id=adjudication_id,
        decision="returned",
        instruction="补齐缺失部分",
        session_id="ast_adj",
    )

    assert result["taskStatus"] == "pending_dispatch"
    assert AssistantTaskRepository().get_task(task_id).status == "pending_dispatch"


def test_parent_adjudication_abandons_task() -> None:
    task_id, adjudication_id = _pending_adjudication()

    result = TaskAdjudicationService().decide(
        adjudication_id=adjudication_id,
        decision="abandoned",
        session_id="ast_adj",
    )

    assert result["taskStatus"] == "abandoned"
    assert AssistantTaskRepository().get_task(task_id).status == "abandoned"


def test_decide_abandon_survives_failure_bridge_error() -> None:
    # I1：裁定提交后的根失败桥接是旁路副作用（独立 session）。桥接抛错不得回滚已提交的
    # 裁定、不得把成功的决策冒泡成异常——任务仍为 abandoned（已提交）、裁定仍为 decided，
    # 错误只记日志。
    task_id, adjudication_id = _pending_adjudication()

    class _BoomBridge:
        def bridge_root_failure(self, **kwargs):
            raise RuntimeError("bridge down")

    service = TaskAdjudicationService(failure_bridge=_BoomBridge())
    result = service.decide(
        adjudication_id=adjudication_id,
        decision="abandoned",
        session_id="ast_adj",
    )

    assert result["taskStatus"] == "abandoned"
    assert AssistantTaskRepository().get_task(task_id).status == "abandoned"
    assert AssistantTaskAdjudicationRepository().get_by_id(adjudication_id).status == "decided"


def test_abandoned_adjudication_cascades_cancel_to_children() -> None:
    """C3: Abandoning a non-root task MUST cancel its children."""
    service = TaskCollaborationService()
    graph_id = service.create_root_graph(
        session_id="ast_cascade",
        title="root",
        description="root",
    )
    task_repo = AssistantTaskRepository()
    root = task_repo.list_graph_tasks(graph_id)[0]
    # root -> child -> grandchild
    child_id = service.create_child_task(
        graph_id=graph_id,
        session_id="ast_cascade",
        parent_task_id=root.task_id,
        title="child",
        description="child",
    )
    grandchild_id = service.create_child_task(
        graph_id=graph_id,
        session_id="ast_cascade",
        parent_task_id=child_id,
        title="grandchild",
        description="grandchild",
    )
    service.update_task_status(task_id=child_id, status="running")
    service.update_task_status(task_id=grandchild_id, status="running")
    adjudication = service.create_parent_adjudication(
        task_id=child_id,
        delivered_status="stuck",
        safe_summary="child stuck",
    )

    TaskAdjudicationService().decide(
        adjudication_id=adjudication.adjudication_id,
        decision="abandoned",
        session_id="ast_cascade",
    )

    # child is abandoned
    assert task_repo.get_task(child_id).status == "abandoned"
    # grandchild is cancelled (cascaded)
    assert task_repo.get_task(grandchild_id).status == "cancelled"
    # root is still pending_dispatch (not affected)
    assert task_repo.get_task(root.task_id).status == "pending_dispatch"


def test_abandoned_adjudication_cascades_cancel_skips_terminal_children() -> None:
    """C3: Cascade cancel MUST skip already-terminal children."""
    service = TaskCollaborationService()
    graph_id = service.create_root_graph(
        session_id="ast_cascade_term",
        title="root",
        description="root",
    )
    task_repo = AssistantTaskRepository()
    root = task_repo.list_graph_tasks(graph_id)[0]
    child_id = service.create_child_task(
        graph_id=graph_id,
        session_id="ast_cascade_term",
        parent_task_id=root.task_id,
        title="child",
        description="child",
    )
    grandchild_a_id = service.create_child_task(
        graph_id=graph_id,
        session_id="ast_cascade_term",
        parent_task_id=child_id,
        title="grandchild_a",
        description="grandchild_a",
    )
    grandchild_b_id = service.create_child_task(
        graph_id=graph_id,
        session_id="ast_cascade_term",
        parent_task_id=child_id,
        title="grandchild_b",
        description="grandchild_b",
    )
    service.update_task_status(task_id=child_id, status="running")
    # grandchild_a already completed
    service.update_task_status(task_id=grandchild_a_id, status="running")
    service.update_task_status(task_id=grandchild_a_id, status="done")
    # grandchild_b still running
    service.update_task_status(task_id=grandchild_b_id, status="running")
    adjudication = service.create_parent_adjudication(
        task_id=child_id,
        delivered_status="stuck",
        safe_summary="child stuck",
    )

    TaskAdjudicationService().decide(
        adjudication_id=adjudication.adjudication_id,
        decision="abandoned",
        session_id="ast_cascade_term",
    )

    # child is abandoned
    assert task_repo.get_task(child_id).status == "abandoned"
    # grandchild_a stays completed (already terminal, not re-cancelled)
    assert task_repo.get_task(grandchild_a_id).status == "done"
    # grandchild_b is cancelled
    assert task_repo.get_task(grandchild_b_id).status == "cancelled"
