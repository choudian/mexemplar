"""US3 集成测试：高风险节点执行前暂停等待确认。

requires_confirmation=1 节点在依赖前置完成后，scheduler 暂停、不 dispatch，
建 pending adjudication 回流主助理裁定；放行后才执行。

集成层验证完整服务链路：build_task_graph → scheduler.start_graph →
suspend(waiting_user) → adjudication pending → decide(accepted) → dispatch resume。
"""

import pytest

from src.business.task_collaboration.adjudication import TaskAdjudicationService
from src.business.task_collaboration.graph_scheduler import (
    GraphScheduler,
    set_graph_scheduler,
)
from src.business.task_collaboration.service import TaskCollaborationService
from src.data.repos.base_repository import generate_id

# ---------------------------------------------------------------------------
# 测试辅助（inline，与 test_graph_scheduler_unit.py 同构但不跨层 import）
# ---------------------------------------------------------------------------


class FakeDispatcher:
    """记录 start_attempt_async 调用，不真跑 executor。"""

    def __init__(self) -> None:
        self.dispatched: list[dict] = []

    def start_attempt_async(
        self,
        *,
        task_id: str,
        executor_type: str,
        executor_id: str,
        lease_owner: str,
        **kwargs,
    ) -> None:
        self.dispatched.append(
            {
                "task_id": task_id,
                "executor_type": executor_type,
                "executor_id": executor_id,
                "lease_owner": lease_owner,
            }
        )


class FakeReentrySink:
    """记录 notify_graph_complete 调用。"""

    def __init__(self) -> None:
        self.completed: list[str] = []

    def notify_graph_complete(self, graph_id: str, session_id: str) -> None:
        self.completed.append(graph_id)


@pytest.fixture(autouse=True)
def _reset_scheduler_singleton():
    """隔离全局单例，防跨测试污染。"""
    set_graph_scheduler(None)
    yield
    set_graph_scheduler(None)


def _build_graph(nodes, dependencies=None):
    """建图辅助：返回 (graph_id, node_task_ids, root_id, session_id)。"""
    session_id = generate_id("sess")
    with TaskCollaborationService() as svc:
        result = svc.build_task_graph(
            session_id=session_id,
            nodes=nodes,
            dependencies=dependencies,
        )
        graph_id = result["graphId"]
        root_id = svc._tasks.get_graph_root(graph_id).task_id
    return graph_id, result["nodeTaskIds"], root_id, session_id


def _status(task_id):
    with TaskCollaborationService() as svc:
        return svc._tasks.get_task(task_id).status


def _suspend_reason(task_id):
    with TaskCollaborationService() as svc:
        return svc._tasks.get_task(task_id).suspend_reason


def _pending_adjudication_id(task_id):
    """块内提取标量 id，避免 ORM 对象在 session 关闭后 DetachedInstanceError。"""
    with TaskCollaborationService() as svc:
        adj = svc._adjudications.get_pending_for_task(task_id)
        return adj.adjudication_id if adj is not None else None


def _mark_completed(task_id):
    with TaskCollaborationService() as svc:
        svc.update_task_status(task_id=task_id, status="completed")


def _mark_pending(task_id):
    with TaskCollaborationService() as svc:
        svc.update_task_status(task_id=task_id, status="pending_dispatch")


def _decide(adjudication_id, decision, *, session_id, scheduler, instruction=None):
    """调 TaskAdjudicationService.decide，注入 scheduler.on_adjudication_decided 回调。"""
    with TaskAdjudicationService(scheduler_callback=scheduler.on_adjudication_decided) as adj:
        return adj.decide(
            adjudication_id=adjudication_id,
            decision=decision,
            decided_by="agent",
            instruction=instruction,
            session_id=session_id,
        )


# ---------------------------------------------------------------------------
# 测试
# ---------------------------------------------------------------------------


class TestConfirmationPause:
    """US3: requires_confirmation 节点裁定前绝不执行。"""

    def test_confirmation_node_suspended_not_dispatched(self):
        """需确认节点前置完成后应被挂起（suspended），不被 dispatch。"""
        session_id = generate_id("sess")
        with TaskCollaborationService() as svc:
            result = svc.build_task_graph(
                session_id=session_id,
                nodes=[
                    {"nodeId": "n1", "title": "准备数据", "description": "整理"},
                    {
                        "nodeId": "n2",
                        "title": "发送邮件",
                        "description": "对外发送",
                        "needsConfirmation": True,
                    },
                ],
                dependencies=[{"from": "n1", "to": "n2"}],
            )
            n2_id = result["nodeTaskIds"]["n2"]

            # n2 标记了 requires_confirmation
            snapshot = svc.get_graph_snapshot(session_id=session_id, graph_id=result["graphId"])
            n2_task = next(t for t in snapshot.tasks if t.task_id == n2_id)
            assert n2_task.requires_confirmation is True

    def test_confirmation_node_snapshot(self):
        """requires_confirmation 投影正确传递到快照。"""
        session_id = generate_id("sess")
        with TaskCollaborationService() as svc:
            result = svc.build_task_graph(
                session_id=session_id,
                nodes=[
                    {"nodeId": "n1", "title": "普通", "description": "普通"},
                    {
                        "nodeId": "n2",
                        "title": "高风险",
                        "description": "发送邮件",
                        "needsConfirmation": True,
                    },
                ],
            )
            snapshot = svc.get_graph_snapshot(session_id=session_id, graph_id=result["graphId"])
            n1_task = next(t for t in snapshot.tasks if t.task_id == result["nodeTaskIds"]["n1"])
            n2_task = next(t for t in snapshot.tasks if t.task_id == result["nodeTaskIds"]["n2"])
            assert n1_task.requires_confirmation is False
            assert n2_task.requires_confirmation is True

    # --- 以下为新增集成测试（D1 修复）---

    def test_confirmation_node_suspended_with_waiting_user_suspend_reason(self):
        """FR-009: requires_confirmation 节点在依赖前置完成后，
        scheduler 暂停该节点，suspend_reason=waiting_user。"""
        graph_id, node_ids, _, session_id = _build_graph(
            [
                {"nodeId": "n1", "title": "准备数据", "description": "整理"},
                {
                    "nodeId": "n2",
                    "title": "发送邮件",
                    "description": "对外发送",
                    "needsConfirmation": True,
                },
            ],
            [{"from": "n1", "to": "n2"}],
        )
        n1, n2 = node_ids["n1"], node_ids["n2"]
        dispatcher = FakeDispatcher()
        scheduler = GraphScheduler(dispatcher=dispatcher, reentry_sink=FakeReentrySink())
        scheduler.start_graph(graph_id)

        # n1 独立就绪，会被 dispatch；n2 依赖 n1，尚不可就绪
        # 先完成 n1 让 n2 就绪
        _mark_completed(n1)
        scheduler.on_attempt_outcome(graph_id, n1)

        # n2 就绪但因 requires_confirmation 被暂停
        assert _status(n2) == "suspended"
        assert _suspend_reason(n2) == "waiting_user"
        # dispatcher 绝未收到 n2
        assert n2 not in [d["task_id"] for d in dispatcher.dispatched]

    def test_accepted_adjudication_resumes_dispatch(self):
        """FR-009: decide(accepted) 放行 → scheduler dispatch；
        task 翻 pending_dispatch（非 completed——尚未执行）。"""
        graph_id, node_ids, _, session_id = _build_graph(
            [
                {
                    "nodeId": "n1",
                    "title": "发送邮件",
                    "description": "高风险对外发送",
                    "needsConfirmation": True,
                },
            ],
        )
        n1 = node_ids["n1"]
        dispatcher = FakeDispatcher()
        scheduler = GraphScheduler(dispatcher=dispatcher, reentry_sink=FakeReentrySink())
        scheduler.start_graph(graph_id)

        # n1 因 requires_confirmation 被暂停
        assert _status(n1) == "suspended"
        adjudication_id = _pending_adjudication_id(n1)
        assert adjudication_id is not None

        # 主助理裁定 accepted
        _decide(adjudication_id, "accepted", session_id=session_id, scheduler=scheduler)

        # 放行后 task 翻 pending_dispatch（可执行但尚未执行）
        assert _status(n1) == "pending_dispatch"
        # scheduler 已 dispatch 该节点
        assert n1 in [d["task_id"] for d in dispatcher.dispatched]

    def test_confirmation_node_never_executed_without_accepted_adjudication(self):
        """FR-009: 未获 accepted 的 requires_confirmation 节点，
        派发层必须拒绝（pending_dispatch + 无 accepted adjudication → return None）。

        验证 dispatcher 的 confirmation 门卫在 task 尚未 suspended 的早期场景
        也能拦截——比如 scheduler 装配延迟时 dispatcher 直接被调。
        """
        graph_id, node_ids, _, _ = _build_graph(
            [
                {
                    "nodeId": "n1",
                    "title": "发送邮件",
                    "description": "高风险对外发送",
                    "needsConfirmation": True,
                },
            ],
        )
        n1 = node_ids["n1"]

        # 不经过 scheduler，task 仍为 pending_dispatch 但 requires_confirmation=True
        # 且无 accepted adjudication → dispatcher 必须拒绝
        from src.business.task_collaboration.dispatcher import TaskDispatcher

        real_dispatcher = TaskDispatcher(executor_callback=lambda _attempt_id: {"success": True})
        try:
            future = real_dispatcher.start_attempt_async(
                task_id=n1,
                executor_type="ephemeral_subagent",
                executor_id=n1,
                lease_owner="test",
            )
            # 派发层必须拒绝：pending_dispatch + requires_confirmation + 无 accepted → None
            assert future is None
        finally:
            real_dispatcher.shutdown()

        # task 仍为 pending_dispatch，未被翻到 running
        assert _status(n1) == "pending_dispatch"
