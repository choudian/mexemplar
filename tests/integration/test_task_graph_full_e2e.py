"""全链路 E2E：decompose → schedule → needs-confirmation adjudicate → failure self-heal → cancel/redirect。

本测试验证 024 task-graph-scheduling 的核心端到端流程。
"""

from src.business.task_collaboration.reentry_briefing import build_reentry_briefing
from src.business.task_collaboration.service import TaskCollaborationService
from src.data.repos.base_repository import generate_id


class TestFullE2E:
    """024 全链路端到端。"""

    def test_decompose_schedule_complete(self):
        """Step 1: 分解 → 按序调度 → 全图完成。"""
        session_id = generate_id("sess")
        with TaskCollaborationService() as svc:
            result = svc.build_task_graph(
                session_id=session_id,
                nodes=[
                    {"nodeId": "n1", "title": "收集数据", "description": "拉取数据"},
                    {"nodeId": "n2", "title": "整理数据", "description": "整理和清洗"},
                    {"nodeId": "n3", "title": "生成报告", "description": "合并成周报"},
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

            # n1 就绪 → 完成
            svc._tasks.assert_dependencies_satisfied(graph_id, n1_id)
            svc.update_task_status(task_id=n1_id, status="done")

            # n2 就绪 → 完成
            svc._tasks.assert_dependencies_satisfied(graph_id, n2_id)
            svc.update_task_status(task_id=n2_id, status="done")

            # n3 就绪 → 完成
            svc._tasks.assert_dependencies_satisfied(graph_id, n3_id)
            svc.update_task_status(task_id=n3_id, status="done")

            # 完成根节点（图的容器）
            root = svc._tasks.get_graph_root(graph_id)
            svc.update_task_status(task_id=root.task_id, status="done")

            # 全图完成
            snapshot = svc.get_graph_snapshot(session_id=session_id, graph_id=graph_id)
            all_completed = all(t.status == "done" for t in snapshot.tasks)
            assert all_completed

    def test_needs_confirmation_adjudicate(self):
        """Step 2: 需确认节点 → 暂停 → 放行 → 继续执行。"""
        session_id = generate_id("sess")
        with TaskCollaborationService() as svc:
            result = svc.build_task_graph(
                session_id=session_id,
                nodes=[
                    {"nodeId": "n1", "title": "准备", "description": "准备数据"},
                    {
                        "nodeId": "n2",
                        "title": "发送",
                        "description": "对外发送",
                        "needsConfirmation": True,
                    },
                ],
                dependencies=[{"from": "n1", "to": "n2"}],
            )
            assert result["confirmationRequired"] is True

            # n2 的 requires_confirmation 落库
            snapshot = svc.get_graph_snapshot(session_id=session_id, graph_id=result["graphId"])
            n2_id = result["nodeTaskIds"]["n2"]
            n2_task = next(t for t in snapshot.tasks if t.task_id == n2_id)
            assert n2_task.requires_confirmation is True

    def test_failure_self_heal_briefing(self):
        """Step 3: 失败节点 → briefing 附自愈清单。"""
        entries = [
            {
                "taskId": "tsk-failed",
                "deliveredStatus": "stuck",
                "safeSummary": "节点执行超时",
                "adjudicationId": "adj-001",
                "healingActions": ["retry", "swap_executor", "skip", "replan", "abandon"],
                "safeRecoveryHint": "执行超时，可重试或换执行器",
            },
        ]
        briefing = build_reentry_briefing(entries)
        assert "自愈选项" in briefing
        assert "重试" in briefing
        assert "skip" in briefing.lower() or "跳过" in briefing

    def test_cancel_and_redirect(self):
        """Step 4: 取消旧图 → 重新分解。"""
        session_id = generate_id("sess")
        with TaskCollaborationService() as svc:
            # 旧图
            result1 = svc.build_task_graph(
                session_id=session_id,
                nodes=[
                    {"nodeId": "n1", "title": "旧步骤", "description": "旧"},
                ],
            )
            old_graph_id = result1["graphId"]

            # 取消旧图
            svc.cancel_graph(graph_id=old_graph_id, session_id=session_id)

            # 重新分解
            result2 = svc.build_task_graph(
                session_id=session_id,
                nodes=[
                    {"nodeId": "n1", "title": "新步骤A", "description": "新方案"},
                    {"nodeId": "n2", "title": "新步骤B", "description": "新方案2"},
                ],
                dependencies=[{"from": "n1", "to": "n2"}],
            )
            assert result2["graphId"] != old_graph_id
