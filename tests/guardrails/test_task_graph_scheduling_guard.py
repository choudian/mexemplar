"""Architecture guard: 024 task-graph-scheduling 核心不变量。

复杂任务（超阈值触发）必须落库为带 dependency 边的 DAG 且由 scheduler 驱动；
简单任务（1-2 步单领域）走快速委派、不建图；
禁止"复杂任务一把委派"回归。

这些门卫测试验证的是落库层形态，不是 LLM 软判定的正确性（CC-006/CC-008）。
"""

import pytest

from src.business.task_collaboration.service import TaskCollaborationService
from src.data.repos.base_repository import generate_id


def _make_service() -> TaskCollaborationService:
    """创建一个短生命周期 service 实例（in-memory SQLite）。"""
    return TaskCollaborationService()


class TestComplexTaskMustBeDAG:
    """US1 门卫：复杂任务（≥3 节点 + dependency 边）必须落库为 DAG。"""

    def test_build_task_graph_creates_dependency_edges(self):
        """build_task_graph 必须创建 dependency 边。"""
        session_id = generate_id("sess")
        with TaskCollaborationService() as svc:
            result = svc.build_task_graph(
                session_id=session_id,
                nodes=[
                    {"nodeId": "n1", "title": "步骤1", "description": "先做这个"},
                    {"nodeId": "n2", "title": "步骤2", "description": "再做这个"},
                    {"nodeId": "n3", "title": "步骤3", "description": "最后做这个"},
                ],
                dependencies=[
                    {"from": "n1", "to": "n2"},
                    {"from": "n2", "to": "n3"},
                ],
            )
            graph_id = result["graphId"]
            snapshot = svc.get_graph_snapshot(session_id=session_id, graph_id=graph_id)
            assert snapshot is not None
            # 必须有 dependency 边
            dep_edges = [e for e in snapshot.edges if e.type == "dependency"]
            assert (
                len(dep_edges) == 2
            ), f"复杂任务 DAG 必须有 dependency 边，实际 {len(dep_edges)} 条"

    def test_build_task_graph_creates_all_node_tasks(self):
        """build_task_graph 必须为每个节点创建 task。"""
        session_id = generate_id("sess")
        with TaskCollaborationService() as svc:
            result = svc.build_task_graph(
                session_id=session_id,
                nodes=[
                    {"nodeId": "n1", "title": "步骤1", "description": "先做这个"},
                    {"nodeId": "n2", "title": "步骤2", "description": "再做这个"},
                ],
                dependencies=[{"from": "n1", "to": "n2"}],
            )
            # 除了根节点外，每个 node 都要有 task
            assert len(result["nodeTaskIds"]) == 2
            graph_id = result["graphId"]
            snapshot = svc.get_graph_snapshot(session_id=session_id, graph_id=graph_id)
            # 根 + 2 节点 = 3 个 task
            assert len(snapshot.tasks) == 3

    def test_build_task_graph_requires_confirmation_persisted(self):
        """needsConfirmation 节点必须在 DB 里标记 requires_confirmation=1。"""
        session_id = generate_id("sess")
        with TaskCollaborationService() as svc:
            result = svc.build_task_graph(
                session_id=session_id,
                nodes=[
                    {"nodeId": "n1", "title": "普通步骤", "description": "普通"},
                    {
                        "nodeId": "n2",
                        "title": "发送邮件",
                        "description": "对外发送",
                        "needsConfirmation": True,
                    },
                ],
                dependencies=[{"from": "n1", "to": "n2"}],
            )
            graph_id = result["graphId"]
            snapshot = svc.get_graph_snapshot(session_id=session_id, graph_id=graph_id)
            n2_task = next(t for t in snapshot.tasks if t.task_id == result["nodeTaskIds"]["n2"])
            assert (
                n2_task.requires_confirmation is True
            ), "needsConfirmation=true 的节点必须落库 requires_confirmation=1"
            n1_task = next(t for t in snapshot.tasks if t.task_id == result["nodeTaskIds"]["n1"])
            assert n1_task.requires_confirmation is False

    def test_dependency_cycle_rejected(self):
        """DAG 不能有环——build_task_graph 必须拒绝环依赖。"""
        session_id = generate_id("sess")
        with TaskCollaborationService() as svc:
            with pytest.raises(ValueError, match="cycle"):
                svc.build_task_graph(
                    session_id=session_id,
                    nodes=[
                        {"nodeId": "n1", "title": "A", "description": "a"},
                        {"nodeId": "n2", "title": "B", "description": "b"},
                        {"nodeId": "n3", "title": "C", "description": "c"},
                    ],
                    dependencies=[
                        {"from": "n1", "to": "n2"},
                        {"from": "n2", "to": "n3"},
                        {"from": "n3", "to": "n1"},  # 环！
                    ],
                )

    def test_graph_budget_exceeded_rejected(self):
        """超过 graph 预算必须被拒。"""
        session_id = generate_id("sess")
        # 创建超多节点（默认预算 200）
        nodes = [
            {"nodeId": f"n{i}", "title": f"步骤{i}", "description": f"step {i}"} for i in range(201)
        ]
        with TaskCollaborationService() as svc:
            with pytest.raises(ValueError, match="budget"):
                svc.build_task_graph(
                    session_id=session_id,
                    nodes=nodes,
                )


class TestSimpleTaskFastDelegation:
    """US2 门卫：简单任务走快速委派、不建图。"""

    def test_simple_task_no_graph(self):
        """简单任务（complexity="simple"）走快速委派路径，不调 _dispatch_task_via_unified_model。

        验证 DelegationOrchestrator.delegate_to_subagent 在 complexity="simple" 时
        直接走 run_sync_ephemeral_subagent，不产出任务图。
        """
        from unittest.mock import MagicMock

        from src.business.agents.config import AgentType
        from src.business.orchestration.agent.delegation_orchestrator import (
            DelegationOrchestrator,
        )

        owner = MagicMock()
        owner._dispatch_task_via_unified_model = MagicMock(return_value=None)

        # Mock sync path to avoid needing full orchestrator setup
        owner.run_sync_ephemeral_subagent = MagicMock(
            return_value={
                "success": True,
                "result_text": "done",
                "executor_session_id": "child_sess",
                "delegation_type": "ephemeral_subagent",
            }
        )
        # DelegationOrchestrator.run_sync_ephemeral_subagent calls
        # self._owner methods; mock the full chain
        owner._resolve_user_tool_ids = MagicMock(return_value=None)
        owner._prompt_builder = MagicMock()
        owner._prompt_builder.format_capability_catalog = MagicMock(return_value="")
        owner._build_ephemeral_subagent_prompt = MagicMock(return_value="prompt")
        owner._new_delegation_workflow_id = MagicMock(return_value="dlg_test")
        owner._session_store = MagicMock()
        owner._session_store.create_session = MagicMock(return_value="child_sess")
        owner._format_delegated_task_input = MagicMock(return_value="input")
        owner._run_delegated_executor = MagicMock(
            return_value={
                "success": True,
                "result_text": "done",
                "executor_session_id": "child_sess",
                "workflow_id": "dlg_test",
            }
        )
        owner._record_delegation_signal = MagicMock()

        orch = DelegationOrchestrator(owner)
        result = orch.delegate_to_subagent(
            parent_session_id="parent",
            task_description="简单任务",
            complexity="simple",
        )

        # 验证: _dispatch_task_via_unified_model 不被调用
        owner._dispatch_task_via_unified_model.assert_not_called()

        # 验证: 走同步路径（_run_delegated_executor 被调用）
        owner._run_delegated_executor.assert_called_once()

        # 验证: 结果不含任务图标识
        assert "taskId" not in result
        assert "graphId" not in result

    def test_complex_task_still_uses_unified_dispatch(self):
        """复杂任务（complexity="complex"）仍走 _dispatch_task_via_unified_model。"""
        from unittest.mock import MagicMock

        from src.business.orchestration.agent.delegation_orchestrator import (
            DelegationOrchestrator,
        )

        owner = MagicMock()
        owner._dispatch_task_via_unified_model = MagicMock(
            return_value={
                "success": True,
                "taskId": "tsk_1",
                "graphId": "tg_1",
            }
        )

        orch = DelegationOrchestrator(owner)
        result = orch.delegate_to_subagent(
            parent_session_id="parent",
            task_description="复杂任务",
            complexity="complex",
        )

        # 验证: _dispatch_task_via_unified_model 被调用
        owner._dispatch_task_via_unified_model.assert_called_once()

        # 验证: 结果含任务图标识
        assert "taskId" in result
        assert "graphId" in result

    def test_build_task_graph_backward_compatible(self):
        """build_task_graph 不应破坏现有 023 快速委派路径。"""
        session_id = generate_id("sess")
        with TaskCollaborationService() as svc:
            # 023 快速委派仍可用
            graph_id = svc.create_root_graph(
                session_id=session_id,
                title="快速任务",
                description="023 兼容",
            )
            snapshot = svc.get_graph_snapshot(session_id=session_id, graph_id=graph_id)
            assert snapshot is not None
            assert len(snapshot.tasks) == 1  # 只有根节点


class TestSchedulerWiring:
    """FR-006/FR-009 装配门卫：tool handler 必须接 GraphScheduler 单例。

    守护 C1 接线——build_task_graph handler 建图后触发 scheduler.start_graph；
    decide_task_adjudication handler 经单例触发 on_adjudication_decided。
    防止接线被回退（green-wash 根因复发）。
    """

    def test_build_task_graph_handler_triggers_start_graph(self, in_memory_db):
        """build_task_graph 建图后必须触发 scheduler.start_graph（FR-006 自动推进入口）。"""
        import json

        from src.business.agents.tools.assistant_tools import (
            create_build_task_graph_handler,
        )
        from src.business.task_collaboration.graph_scheduler import (
            install_graph_scheduler_event_subscriptions,
            set_graph_scheduler,
        )

        triggered: list[str] = []

        class _FakeScheduler:
            def start_graph(self, graph_id):
                triggered.append(graph_id)

        set_graph_scheduler(_FakeScheduler())
        install_graph_scheduler_event_subscriptions()
        try:
            handler = create_build_task_graph_handler(generate_id("sess"))
            data = json.loads(handler(nodes=[{"nodeId": "n1", "title": "A", "description": "x"}]))
            assert data.get("graphId"), data
            assert triggered == [data["graphId"]], "建图必须触发 scheduler.start_graph"
        finally:
            set_graph_scheduler(None)

    def test_build_task_graph_handler_persists_latest_user_message_sequence(self, in_memory_db):
        """build_task_graph handler 必须把当前用户消息 sequence 传给 root graph。"""
        import json

        from src.business.agents.tools.assistant_tools import (
            create_build_task_graph_handler,
        )
        from src.data.models_sqlite import Message
        from src.data.repos import MessageRepository

        session_id = generate_id("sess")
        with MessageRepository() as messages:
            messages.create(
                Message(
                    message_id=generate_id("msg"),
                    session_id=session_id,
                    sequence=41,
                    role="user",
                    content="旧请求",
                )
            )
            messages.create(
                Message(
                    message_id=generate_id("msg"),
                    session_id=session_id,
                    sequence=42,
                    role="user",
                    content="当前请求",
                )
            )

        handler = create_build_task_graph_handler(session_id)
        data = json.loads(handler(nodes=[{"nodeId": "n1", "title": "A", "description": "x"}]))

        with _make_service() as svc:
            root = svc._tasks.get_graph_root(data["graphId"])
            assert root.user_message_sequence == 42

    def test_decide_handler_triggers_scheduler_callback(self, in_memory_db):
        """decide(accepted) 必须经 scheduler 单例触发 on_adjudication_decided（FR-009 放行链）。"""
        from src.business.agents.tools.assistant_tools import (
            create_decide_task_adjudication_handler,
        )
        from src.business.task_collaboration.graph_scheduler import set_graph_scheduler

        decided: list[tuple] = []

        class _FakeScheduler:
            def on_adjudication_decided(self, graph_id, task_id, decision):
                decided.append((graph_id, task_id, decision))

        session_id = generate_id("sess")
        with _make_service() as svc:
            result = svc.build_task_graph(
                session_id=session_id,
                nodes=[{"nodeId": "n1", "title": "A", "description": "x"}],
            )
            adj = svc.create_parent_adjudication(
                task_id=result["nodeTaskIds"]["n1"],
                delivered_status="done",
                safe_summary="ok",
            )
            adj_id = adj.adjudication_id

        set_graph_scheduler(_FakeScheduler())
        try:
            handler = create_decide_task_adjudication_handler(session_id)
            handler(adjudication_id=adj_id, decision="accepted")
            assert decided, "decide(accepted) 必须触发 scheduler.on_adjudication_decided"
        finally:
            set_graph_scheduler(None)

    def test_mutate_task_graph_handler_triggers_rescan(self, in_memory_db):
        """mutate_task_graph 成功改图后必须触发 scheduler.start_graph 重新扫描就绪节点。"""
        import json

        from src.business.agents.tools.assistant_tools import (
            create_mutate_task_graph_handler,
        )
        from src.business.task_collaboration.graph_scheduler import (
            install_graph_scheduler_event_subscriptions,
            set_graph_scheduler,
        )

        triggered: list[str] = []

        class _FakeScheduler:
            def start_graph(self, graph_id):
                triggered.append(graph_id)

        session_id = generate_id("sess")
        with _make_service() as svc:
            result = svc.build_task_graph(
                session_id=session_id,
                nodes=[{"nodeId": "n1", "title": "A", "description": "x"}],
            )
            graph_id = result["graphId"]

        set_graph_scheduler(_FakeScheduler())
        install_graph_scheduler_event_subscriptions()
        try:
            handler = create_mutate_task_graph_handler(session_id)
            data = json.loads(
                handler(
                    graphId=graph_id,
                    changes=[
                        {
                            "op": "add_node",
                            "nodeId": "n2",
                            "title": "B",
                            "description": "新增节点",
                        }
                    ],
                    reason="self-heal",
                )
            )
            assert data["rescanned"] is True
            assert triggered == [graph_id]
        finally:
            set_graph_scheduler(None)
