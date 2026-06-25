"""GraphScheduler 类级单测（D1）+ needs_confirmation 裁定语义（FR-009）。

024 核心组件 GraphScheduler 的行为覆盖——独立实例化（不依赖 orchestrator 装配），
用真实 TaskCollaborationService 建图 + FakeDispatcher / FakeReentrySink 验证：

- start_graph 派发就绪执行节点，跳过 root 容器
- on_attempt_outcome 前置完成后推进下游
- requires_confirmation 节点派发前暂停（建 pending adjudication + suspended/waiting_user）
- decide(accepted) 经 callback 放行 → scheduler dispatch + task 翻 pending_dispatch（非 completed）
- 全图完成 → notify_graph_complete + root 收口 completed
- on_executor_recovered 重派恢复节点
- 普通结果裁定 decide(accepted) → completed（023 语义不回归）

scheduler 是确定性、非 LLM 推进器；本测验证其状态机（constitution IV 可验证交付）。
"""

from __future__ import annotations

import pytest

from src.business.task_collaboration.adjudication import TaskAdjudicationService
from src.business.task_collaboration.graph_scheduler import (
    GraphScheduler,
    set_graph_scheduler,
)
from src.business.task_collaboration.service import TaskCollaborationService
from src.data.repos.base_repository import generate_id


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


class TestStartGraph:
    def test_start_graph_dispatches_ready_node(self):
        graph_id, node_ids, _, _ = _build_graph(
            [{"nodeId": "n1", "title": "A", "description": "独立"}]
        )
        dispatcher = FakeDispatcher()
        scheduler = GraphScheduler(dispatcher=dispatcher, reentry_sink=FakeReentrySink())

        scheduler.start_graph(graph_id)

        assert node_ids["n1"] in [d["task_id"] for d in dispatcher.dispatched]

    def test_start_graph_skips_root_container(self):
        """root 容器节点（无 assignee、不直接执行）绝不被 dispatch。"""
        graph_id, node_ids, root_id, _ = _build_graph(
            [{"nodeId": "n1", "title": "A", "description": "独立"}]
        )
        dispatcher = FakeDispatcher()
        GraphScheduler(dispatcher=dispatcher, reentry_sink=FakeReentrySink()).start_graph(graph_id)

        assert root_id not in [d["task_id"] for d in dispatcher.dispatched]

    def test_start_graph_not_dispatch_unready_downstream(self):
        graph_id, node_ids, _, _ = _build_graph(
            [
                {"nodeId": "n1", "title": "A", "description": "先做"},
                {"nodeId": "n2", "title": "B", "description": "后做"},
            ],
            [{"from": "n1", "to": "n2"}],
        )
        dispatcher = FakeDispatcher()
        GraphScheduler(dispatcher=dispatcher, reentry_sink=FakeReentrySink()).start_graph(graph_id)

        assert [d["task_id"] for d in dispatcher.dispatched] == [node_ids["n1"]]


class TestAttemptOutcomeAdvances:
    def test_downstream_dispatched_after_predecessor_completes(self):
        graph_id, node_ids, _, _ = _build_graph(
            [
                {"nodeId": "n1", "title": "A", "description": "先做"},
                {"nodeId": "n2", "title": "B", "description": "后做"},
            ],
            [{"from": "n1", "to": "n2"}],
        )
        n1, n2 = node_ids["n1"], node_ids["n2"]
        dispatcher = FakeDispatcher()
        scheduler = GraphScheduler(dispatcher=dispatcher, reentry_sink=FakeReentrySink())
        scheduler.start_graph(graph_id)
        assert [d["task_id"] for d in dispatcher.dispatched] == [n1]

        _mark_completed(n1)
        scheduler.on_attempt_outcome(graph_id, n1)

        assert [d["task_id"] for d in dispatcher.dispatched] == [n1, n2]

    def test_parallel_downstream_both_dispatched(self):
        graph_id, node_ids, _, _ = _build_graph(
            [
                {"nodeId": "n1", "title": "A", "description": "先做"},
                {"nodeId": "n2", "title": "B", "description": "并行1"},
                {"nodeId": "n3", "title": "C", "description": "并行2"},
            ],
            [{"from": "n1", "to": "n2"}, {"from": "n1", "to": "n3"}],
        )
        n1, n2, n3 = node_ids["n1"], node_ids["n2"], node_ids["n3"]
        dispatcher = FakeDispatcher()
        scheduler = GraphScheduler(dispatcher=dispatcher, reentry_sink=FakeReentrySink())
        scheduler.start_graph(graph_id)

        _mark_completed(n1)
        scheduler.on_attempt_outcome(graph_id, n1)

        dispatched = [d["task_id"] for d in dispatcher.dispatched]
        assert n2 in dispatched and n3 in dispatched


class TestNeedsConfirmationPause:
    """FR-009：高风险节点派发前暂停，放行后才执行。"""

    def _setup(self):
        graph_id, node_ids, _, session_id = _build_graph(
            [
                {
                    "nodeId": "n1",
                    "title": "发邮件",
                    "description": "高风险对外发送",
                    "needsConfirmation": True,
                }
            ]
        )
        dispatcher = FakeDispatcher()
        scheduler = GraphScheduler(dispatcher=dispatcher, reentry_sink=FakeReentrySink())
        scheduler.start_graph(graph_id)
        return graph_id, node_ids["n1"], session_id, dispatcher, scheduler

    def test_confirmed_node_not_dispatched_before_adjudication(self):
        _, n1, _, dispatcher, _ = self._setup()
        assert dispatcher.dispatched == []

    def test_confirmed_node_suspended_with_waiting_user(self):
        _, n1, _, _, _ = self._setup()
        assert _status(n1) == "suspended"
        assert _suspend_reason(n1) == "waiting_user"

    def test_confirmed_node_has_pending_adjudication(self):
        _, n1, _, _, _ = self._setup()
        assert _pending_adjudication_id(n1) is not None

    def test_accepted_adjudication_dispatches_and_keeps_pending(self):
        """decide(accepted) 放行 → scheduler dispatch；task 翻 pending_dispatch（非 completed）。"""
        graph_id, n1, session_id, dispatcher, scheduler = self._setup()
        adjudication_id = _pending_adjudication_id(n1)
        assert adjudication_id is not None

        _decide(
            adjudication_id,
            "accepted",
            session_id=session_id,
            scheduler=scheduler,
        )

        # 放行后派发
        assert n1 in [d["task_id"] for d in dispatcher.dispatched]
        # task 翻 pending_dispatch（放行执行），绝不是 completed（尚未执行）
        assert _status(n1) == "pending_dispatch"

    def test_returned_adjudication_does_not_dispatch(self):
        """returned（打回）不直接派发该节点。"""
        graph_id, n1, session_id, dispatcher, scheduler = self._setup()
        adjudication_id = _pending_adjudication_id(n1)

        _decide(
            adjudication_id,
            "returned",
            session_id=session_id,
            scheduler=scheduler,
            instruction="调整收件人后重试",
        )

        assert n1 not in [d["task_id"] for d in dispatcher.dispatched]

    def test_abandoned_adjudication_does_not_dispatch(self):
        """abandoned（放弃）不直接派发该节点（与 returned 同走 _advance 重扫路径）。

        abandoned 的下游收口由 adjudication.decide 状态机负责，scheduler 本层只重扫；
        不断言下游取消（那不是 scheduler 职责，避免误解注释承诺）。
        """
        graph_id, n1, session_id, dispatcher, scheduler = self._setup()
        adjudication_id = _pending_adjudication_id(n1)

        _decide(adjudication_id, "abandoned", session_id=session_id, scheduler=scheduler)

        assert n1 not in [d["task_id"] for d in dispatcher.dispatched]

    def test_dispatcher_refuses_unaccepted_confirmation_node(self, mock_config):
        """派发层本身必须拒绝未 accepted 的 requires_confirmation 节点。"""
        from src.business.task_collaboration.dispatcher import TaskDispatcher

        graph_id, node_ids, _, _ = _build_graph(
            [
                {
                    "nodeId": "n1",
                    "title": "发邮件",
                    "description": "高风险对外发送",
                    "needsConfirmation": True,
                }
            ]
        )
        task_id = node_ids["n1"]
        dispatcher = TaskDispatcher(executor_callback=lambda _attempt_id: {"success": True})
        try:
            future = dispatcher.start_attempt_async(
                task_id=task_id,
                executor_type="ephemeral_subagent",
                executor_id=task_id,
                lease_owner="test",
            )
            assert future is None
        finally:
            dispatcher.shutdown()

    def test_needs_confirmation_pause_atomic_on_suspend_failure(self, monkeypatch):
        """suspend 写失败时 adjudication 一并回滚，不留孤儿（FR-009 原子性，SC-002）。

        create_pending + suspend 必须在单个 _atomic 内：suspend 失败 → adjudication 回滚，
        节点未挂起，避免高风险节点停在 pending_dispatch 既不执行也不暂停。
        """
        graph_id, node_ids, _, _ = _build_graph(
            [
                {
                    "nodeId": "n1",
                    "title": "A",
                    "description": "x",
                    "needsConfirmation": True,
                }
            ]
        )
        n1 = node_ids["n1"]
        with TaskCollaborationService() as svc:
            orig_update = svc._tasks.update_status

            def boom(*args, **kwargs):
                raise RuntimeError("db down on suspend")

            monkeypatch.setattr(svc._tasks, "update_status", boom)
            with pytest.raises(RuntimeError):
                svc.create_needs_confirmation_pause(task_id=n1, title="A")
            monkeypatch.setattr(svc._tasks, "update_status", orig_update)

            # 同事务回滚 → 不留孤儿 adjudication，task 未挂起
            assert svc._adjudications.get_pending_for_task(n1) is None
            assert svc._tasks.get_task(n1).status == "pending_dispatch"


class TestNormalOutcomeAdjudicationSemantics:
    """023 普通结果裁定不回归：普通节点 decide(accepted) → completed。"""

    def test_normal_node_accepted_completes(self):
        graph_id, node_ids, _, session_id = _build_graph(
            [{"nodeId": "n1", "title": "普通", "description": "无 needsConfirmation"}]
        )
        n1 = node_ids["n1"]
        # 模拟执行后回流：手动建一个普通 pending adjudication（dispatcher 路径）
        with TaskCollaborationService() as svc:
            adjudication = svc.create_parent_adjudication(
                task_id=n1,
                delivered_status="done",
                safe_summary="结果 OK",
            )
            adjudication_id = adjudication.adjudication_id
        scheduler = GraphScheduler(dispatcher=FakeDispatcher(), reentry_sink=FakeReentrySink())

        _decide(
            adjudication_id,
            "accepted",
            session_id=session_id,
            scheduler=scheduler,
        )

        # 普通结果采纳 → completed（023 语义保留）
        assert _status(n1) == "completed"


class TestGraphCompletion:
    def test_all_completed_notifies_and_closes_root(self):
        graph_id, node_ids, root_id, _ = _build_graph(
            [{"nodeId": "n1", "title": "A", "description": "x"}]
        )
        n1 = node_ids["n1"]
        sink = FakeReentrySink()
        scheduler = GraphScheduler(dispatcher=FakeDispatcher(), reentry_sink=sink)
        scheduler.start_graph(graph_id)

        _mark_completed(n1)
        scheduler.on_attempt_outcome(graph_id, n1)

        assert graph_id in sink.completed
        assert _status(root_id) == "completed"

    def test_no_notify_until_all_completed(self):
        graph_id, node_ids, _, _ = _build_graph(
            [
                {"nodeId": "n1", "title": "A", "description": "x"},
                {"nodeId": "n2", "title": "B", "description": "y"},
            ]
        )
        n1 = node_ids["n1"]
        sink = FakeReentrySink()
        scheduler = GraphScheduler(dispatcher=FakeDispatcher(), reentry_sink=sink)
        scheduler.start_graph(graph_id)
        _mark_completed(n1)
        scheduler.on_attempt_outcome(graph_id, n1)

        assert sink.completed == []

    def test_all_terminal_with_failure_still_notifies(self):
        """含失败/取消的终态图也触发回流，避免图静默停滞（FR-015/SC-003/constitution IV）。

        契约 §2 规定 all_nodes_terminal → notify；实现不得额外要求「全 completed」。
        """
        graph_id, node_ids, root_id, _ = _build_graph(
            [
                {"nodeId": "n1", "title": "A", "description": "x"},
                {"nodeId": "n2", "title": "B", "description": "y"},
            ]
        )
        n1, n2 = node_ids["n1"], node_ids["n2"]
        sink = FakeReentrySink()
        scheduler = GraphScheduler(dispatcher=FakeDispatcher(), reentry_sink=sink)
        scheduler.start_graph(graph_id)
        # n1 完成、n2 失败 → 全终态但非全 completed
        _mark_completed(n1)
        with TaskCollaborationService() as svc:
            svc.update_task_status(task_id=n2, status="failed")
        scheduler.on_attempt_outcome(graph_id, n2)

        # 含失败也必须通知主助理裁定后续
        assert graph_id in sink.completed
        # 含失败不收口 root（保留非终态供主助理 replan/abandon 裁定）
        assert _status(root_id) not in ("completed", "failed", "cancelled")

    def test_terminal_notify_not_repeated_after_root_closed(self):
        """全 completed 收口后，重复 _advance 不重复唤醒主助理。"""
        graph_id, node_ids, root_id, _ = _build_graph(
            [{"nodeId": "n1", "title": "A", "description": "x"}]
        )
        n1 = node_ids["n1"]
        sink = FakeReentrySink()
        scheduler = GraphScheduler(dispatcher=FakeDispatcher(), reentry_sink=sink)
        scheduler.start_graph(graph_id)
        _mark_completed(n1)
        scheduler.on_attempt_outcome(graph_id, n1)
        assert sink.completed == [graph_id]

        # 再次触发 advance（root 已 completed）→ 不重复通知
        scheduler.on_attempt_outcome(graph_id, n1)
        assert sink.completed == [graph_id]


class TestExecutorRecovered:
    def test_recovered_node_redispatched(self):
        graph_id, node_ids, _, _ = _build_graph(
            [{"nodeId": "n1", "title": "A", "description": "独立"}]
        )
        n1 = node_ids["n1"]
        dispatcher = FakeDispatcher()
        scheduler = GraphScheduler(dispatcher=dispatcher, reentry_sink=FakeReentrySink())
        scheduler.start_graph(graph_id)
        assert sum(1 for d in dispatcher.dispatched if d["task_id"] == n1) == 1

        _mark_pending(n1)
        scheduler.on_executor_recovered(graph_id, n1)

        assert sum(1 for d in dispatcher.dispatched if d["task_id"] == n1) == 2


class TestSchedulerSingleton:
    def test_get_set_graph_scheduler_roundtrip(self):
        scheduler = GraphScheduler(dispatcher=FakeDispatcher(), reentry_sink=FakeReentrySink())
        set_graph_scheduler(scheduler)
        from src.business.task_collaboration.graph_scheduler import get_graph_scheduler

        assert get_graph_scheduler() is scheduler

    def test_get_graph_scheduler_none_when_unset(self):
        from src.business.task_collaboration.graph_scheduler import get_graph_scheduler

        assert get_graph_scheduler() is None
