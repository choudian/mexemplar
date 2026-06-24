from __future__ import annotations

from src.business.task_collaboration.adjudication import TaskFailureBridge
from src.business.task_collaboration.service import TaskCollaborationService
from src.data.repos import AssistantRunFailureRepository, AssistantTaskRepository


def test_root_task_failure_bridges_to_assistant_run_failure() -> None:
    service = TaskCollaborationService()
    graph_id = service.create_root_graph(
        session_id="ast_fail",
        title="root",
        description="root",
        user_message_sequence=7,
    )
    root = AssistantTaskRepository().list_graph_tasks(graph_id)[0]
    service.update_task_status(task_id=root.task_id, status="failed")

    summary = TaskFailureBridge().bridge_root_failure(
        task_id=root.task_id,
        safe_summary="顶层任务失败",
    )

    assert summary is not None
    failure = AssistantRunFailureRepository().get_current("ast_fail")
    assert failure is not None
    assert failure.message_sequence == 7


def test_child_task_failure_does_not_bridge_to_run_failure() -> None:
    service = TaskCollaborationService()
    graph_id = service.create_root_graph(
        session_id="ast_child_fail",
        title="root",
        description="root",
        user_message_sequence=9,
    )
    task_repo = AssistantTaskRepository()
    root = task_repo.list_graph_tasks(graph_id)[0]
    child_id = service.create_child_task(
        graph_id=graph_id,
        session_id="ast_child_fail",
        parent_task_id=root.task_id,
        title="child",
        description="child",
    )
    service.update_task_status(task_id=child_id, status="failed")

    summary = TaskFailureBridge().bridge_root_failure(
        task_id=child_id,
        safe_summary="子任务失败",
    )

    assert summary is None
    assert AssistantRunFailureRepository().get_current("ast_child_fail") is None


def test_fail_root_graph_entry_bridges_to_run_failure() -> None:
    """FR-008/CC-004：通过 TaskAdjudicationService.fail_root_graph 生产入口（主助理
    abandon_request_graph 工具）触发 root FAILED → bridge → AssistantRunFailure 卡。

    这条路径补上了 decide(abandoned) 缺的"整图放弃→run 卡"一跳：decide 处理的是有 parent
    的子任务，其 bridge 调用撞 root-only 守卫 return None；fail_root_graph 直接定位 root
    （parent_task_id is None）翻 FAILED，让 bridge_root_failure 真正命中。
    """
    from src.business.task_collaboration.adjudication import TaskAdjudicationService

    service = TaskCollaborationService()
    graph_id = service.create_root_graph(
        session_id="ast_fail_entry",
        title="root",
        description="root",
        user_message_sequence=21,
    )
    root = AssistantTaskRepository().list_graph_tasks(graph_id)[0]

    result = TaskAdjudicationService().fail_root_graph(
        session_id="ast_fail_entry",
        safe_summary="整张请求无法完成",
    )

    assert result["abandoned"] is True
    assert result["rootTaskId"] == root.task_id
    assert result["taskStatus"] == "failed"
    assert AssistantTaskRepository().get_task(root.task_id).status == "failed"
    failure = AssistantRunFailureRepository().get_current("ast_fail_entry")
    assert failure is not None
    assert failure.message_sequence == 21


def test_fail_root_graph_cascades_cancel_to_children() -> None:
    """fail_root_graph 翻 root FAILED 的同时级联取消下游子任务（终态、不复活）。"""
    from src.business.task_collaboration.adjudication import TaskAdjudicationService

    service = TaskCollaborationService()
    graph_id = service.create_root_graph(
        session_id="ast_fail_cascade",
        title="root",
        description="root",
        user_message_sequence=22,
    )
    task_repo = AssistantTaskRepository()
    root = task_repo.list_graph_tasks(graph_id)[0]
    child_id = service.create_child_task(
        graph_id=graph_id,
        session_id="ast_fail_cascade",
        parent_task_id=root.task_id,
        title="child",
        description="child",
    )
    service.update_task_status(task_id=child_id, status="running")

    TaskAdjudicationService().fail_root_graph(
        session_id="ast_fail_cascade",
        safe_summary="整张请求无法完成",
    )

    # 用新的 repo 实例读：setup 时的 task_repo session 已缓存 stale root（identity map），
    # fail_root_graph 经独立 session 提交后必须新开 session 才能看到刷新后的状态。
    fresh_repo = AssistantTaskRepository()
    assert fresh_repo.get_task(root.task_id).status == "failed"
    assert fresh_repo.get_task(child_id).status == "cancelled"


def test_fail_root_graph_without_user_message_sequence_fails_without_card() -> None:
    """root 无 user_message_sequence（无消息上下文）时，fail_root_graph 仍翻 root FAILED，
    但 bridge 不桥接（无消息回合可挂失败卡），不产生 run 失败卡。"""
    from src.business.task_collaboration.adjudication import TaskAdjudicationService

    service = TaskCollaborationService()
    graph_id = service.create_root_graph(
        session_id="ast_no_seq",
        title="root",
        description="root",
    )
    root = AssistantTaskRepository().list_graph_tasks(graph_id)[0]

    result = TaskAdjudicationService().fail_root_graph(
        session_id="ast_no_seq",
        safe_summary="无消息上下文的请求失败",
    )

    assert result["taskStatus"] == "failed"
    assert AssistantTaskRepository().get_task(root.task_id).status == "failed"
    assert AssistantRunFailureRepository().get_current("ast_no_seq") is None
