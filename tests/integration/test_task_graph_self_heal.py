"""US4 集成测试：节点失败先自愈，兜不住再升级。

失败回流 briefing 附自愈动作清单；主助理优先自愈（重试/换执行器/调输入/跳过/改图），
兜不住才 ask_user_question 升级。
"""

from src.business.task_collaboration.adjudication import TaskAdjudicationService
from src.business.task_collaboration.graph_scheduler import GraphScheduler
from src.business.task_collaboration.reentry_briefing import build_reentry_briefing
from src.business.task_collaboration.service import TaskCollaborationService
from src.data.repos.base_repository import generate_id

# ---------------------------------------------------------------------------
# 测试辅助（inline，与 test_graph_scheduler_unit.py 同构）
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


def _status(task_id):
    with TaskCollaborationService() as svc:
        return svc._tasks.get_task(task_id).status


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


class TestSelfHeal:
    """US4: 失败节点自愈。"""

    def test_failure_entry_with_healing_actions(self):
        """失败 entry 附 healingActions 时 briefing 渲染自愈选项。"""
        entries = [
            {
                "taskId": "tsk-001",
                "deliveredStatus": "stuck",
                "safeSummary": "节点执行超时",
                "adjudicationId": "adj-001",
                "healingActions": ["retry", "swap_executor", "skip", "abandon"],
                "safeRecoveryHint": "节点执行超时，可重试或换执行器",
            },
        ]
        briefing = build_reentry_briefing(entries)
        assert "自愈选项" in briefing
        assert "重试" in briefing
        assert "换执行器" in briefing
        assert "跳过" in briefing
        assert "放弃" in briefing
        assert "ask_user_question 升级" in briefing
        assert "安全提示" in briefing

    def test_failure_entry_without_healing_actions(self):
        """无 healingActions 的 entry 正常渲染。"""
        entries = [
            {
                "taskId": "tsk-001",
                "deliveredStatus": "done",
                "safeSummary": "任务完成",
                "adjudicationId": "adj-001",
            },
        ]
        briefing = build_reentry_briefing(entries)
        assert "自愈选项" not in briefing

    def test_mutate_task_graph_skip_node(self, monkeypatch):
        """自愈跳过节点：mutate_task_graph(skip_node) 标记 cancelled。"""
        from src.business.agents import run_context
        from src.execution.cancellation import CancelReason

        signals = []
        monkeypatch.setattr(
            run_context,
            "request_cancel_key",
            lambda key, *, reason=CancelReason.USER_CANCEL: signals.append((key, reason)) or True,
        )
        session_id = generate_id("sess")
        with TaskCollaborationService() as svc:
            result = svc.build_task_graph(
                session_id=session_id,
                nodes=[
                    {"nodeId": "n1", "title": "失败节点", "description": "超时了"},
                ],
            )
            n1_id = result["nodeTaskIds"]["n1"]
            graph_id = result["graphId"]

            # 跳过该节点
            mutation = svc.mutate_task_graph(
                graph_id=graph_id,
                session_id=session_id,
                changes=[{"op": "skip_node", "taskId": n1_id}],
                reason="自愈：跳过超时节点",
            )
            assert len(mutation["applied"]) == 1
            task = svc._tasks.get_task(n1_id)
            assert task.status == "cancelled"
            assert signals == [(f"assistant_task:{n1_id}", CancelReason.SIBLING_ERROR)]

    def test_skip_node_cascades_downstream_so_graph_cannot_stall(self):
        """skip_node 的下游规则必须落地：不可继续的下游子图应被取消，避免依赖永久等待。"""
        session_id = generate_id("sess")
        with TaskCollaborationService() as svc:
            result = svc.build_task_graph(
                session_id=session_id,
                nodes=[
                    {"nodeId": "n1", "title": "失败节点", "description": "超时了"},
                    {"nodeId": "n2", "title": "依赖下游", "description": "依赖 n1"},
                    {"nodeId": "n3", "title": "更远下游", "description": "依赖 n2"},
                ],
                dependencies=[
                    {"from": "n1", "to": "n2"},
                    {"from": "n2", "to": "n3"},
                ],
            )
            graph_id = result["graphId"]
            n1_id = result["nodeTaskIds"]["n1"]
            n2_id = result["nodeTaskIds"]["n2"]
            n3_id = result["nodeTaskIds"]["n3"]

            mutation = svc.mutate_task_graph(
                graph_id=graph_id,
                session_id=session_id,
                changes=[{"op": "skip_node", "taskId": n1_id}],
                reason="自愈：跳过不可恢复节点",
            )

            assert len(mutation["applied"]) == 1
            assert svc._tasks.get_task(n1_id).status == "cancelled"
            assert svc._tasks.get_task(n2_id).status == "cancelled"
            assert svc._tasks.get_task(n3_id).status == "cancelled"

    def test_mutate_task_graph_add_node_replan(self):
        """自愈改图：add_node 添加替代节点。"""
        session_id = generate_id("sess")
        with TaskCollaborationService() as svc:
            result = svc.build_task_graph(
                session_id=session_id,
                nodes=[
                    {"nodeId": "n1", "title": "原始", "description": "原始方法"},
                ],
            )
            graph_id = result["graphId"]

            # 添加替代节点
            mutation = svc.mutate_task_graph(
                graph_id=graph_id,
                session_id=session_id,
                changes=[
                    {
                        "op": "add_node",
                        "nodeId": "n2",
                        "title": "替代方案",
                        "description": "用另一种方法",
                    },
                ],
                reason="自愈：添加替代节点",
            )
            assert len(mutation["applied"]) == 1

    # --- 以下为新增集成测试（D2 修复）---

    def test_self_heal_resolves_without_escalation(self):
        """FR-010: 可恢复失败自愈成功（decide returned）后 task 翻回 pending_dispatch，
        briefing 中自愈选项排在升级选项之前——自愈优先，升级仅为兜底。"""
        session_id = generate_id("sess")
        with TaskCollaborationService() as svc:
            result = svc.build_task_graph(
                session_id=session_id,
                nodes=[
                    {"nodeId": "n1", "title": "失败节点", "description": "超时"},
                ],
            )
            n1_id = result["nodeTaskIds"]["n1"]

            # 模拟 dispatcher 回流：创建 stuck failure adjudication
            adjudication = svc.create_parent_adjudication(
                task_id=n1_id,
                delivered_status="stuck",
                safe_summary="节点执行超时",
            )
            adjudication_id = adjudication.adjudication_id

        # 构建 briefing 并验证自愈选项优先
        entries = [
            {
                "taskId": n1_id,
                "deliveredStatus": "stuck",
                "safeSummary": "节点执行超时",
                "adjudicationId": adjudication_id,
                "healingActions": ["retry", "swap_executor", "skip", "abandon"],
                "safeRecoveryHint": "节点执行超时，可重试或换执行器",
            },
        ]
        briefing = build_reentry_briefing(entries)

        # 自愈选项存在且排在升级选项之前
        assert "自愈选项" in briefing
        assert "重试" in briefing
        assert "ask_user_question 升级" in briefing
        # 自愈选项索引 < 升级选项索引（自愈优先）
        heal_idx = briefing.index("重试")
        escalate_idx = briefing.index("ask_user_question 升级")
        assert heal_idx < escalate_idx

        # 实际走自愈路径：decide(returned) 打回返工
        dispatcher = FakeDispatcher()
        scheduler = GraphScheduler(dispatcher=dispatcher, reentry_sink=FakeReentrySink())
        _decide(
            adjudication_id,
            "returned",
            session_id=session_id,
            scheduler=scheduler,
            instruction="重试该节点",
        )

        # task 翻回 pending_dispatch（自愈成功，可重新执行）
        assert _status(n1_id) == "pending_dispatch"

    def test_unrecoverable_failure_abandoned_then_escalation_hint(self):
        """FR-010: 不可恢复失败（decide abandoned）后 task 变 failed 终态，
        briefing 中 abandon 选项和 escalation 提示并存——自愈兜不住才升级。"""
        session_id = generate_id("sess")
        with TaskCollaborationService() as svc:
            result = svc.build_task_graph(
                session_id=session_id,
                nodes=[
                    {"nodeId": "n1", "title": "不可恢复", "description": "结构性问题"},
                    {"nodeId": "n2", "title": "下游", "description": "依赖 n1"},
                ],
                dependencies=[{"from": "n1", "to": "n2"}],
            )
            n1_id = result["nodeTaskIds"]["n1"]

            # 模拟 dispatcher 回流：创建 stuck failure adjudication
            adjudication = svc.create_parent_adjudication(
                task_id=n1_id,
                delivered_status="stuck",
                safe_summary="结构性问题无法自愈",
            )
            adjudication_id = adjudication.adjudication_id

        # 构建 briefing 验证 escalation 提示存在
        entries = [
            {
                "taskId": n1_id,
                "deliveredStatus": "stuck",
                "safeSummary": "结构性问题无法自愈",
                "adjudicationId": adjudication_id,
                "healingActions": ["retry", "swap_executor", "skip", "replan", "abandon"],
                "safeRecoveryHint": "节点执行超时，可重试或换执行器",
            },
        ]
        briefing = build_reentry_briefing(entries)

        # abandon 自愈选项和 escalation 提示都存在
        assert "放弃" in briefing
        assert "ask_user_question 升级" in briefing

        # 走放弃路径：decide(abandoned) → task 变 failed
        dispatcher = FakeDispatcher()
        scheduler = GraphScheduler(dispatcher=dispatcher, reentry_sink=FakeReentrySink())
        _decide(
            adjudication_id,
            "abandoned",
            session_id=session_id,
            scheduler=scheduler,
        )

        # 不可恢复终态
        assert _status(n1_id) == "failed"
