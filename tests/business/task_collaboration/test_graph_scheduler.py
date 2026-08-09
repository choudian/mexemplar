"""DAG scheduler 单测：就绪激活顺序、无环校验、就绪硬校验拒乱序。

scheduler 是确定性、非 LLM 的推进器。本测试验证其核心逻辑：
- 就绪节点按依赖顺序激活
- 无依赖节点可并行
- 就绪硬校验拒绝乱序派发
- 全图完成触发汇报
"""

import json

import pytest

from src.data.repos.base_repository import generate_id
from src.business.task_collaboration.service import TaskCollaborationService


class TestDependenciesSatisfied:
    """就绪硬校验 assert_dependencies_satisfied。"""

    def test_no_predecessors_passes(self):
        """无前置依赖的节点始终就绪。"""
        session_id = generate_id("sess")
        with TaskCollaborationService() as svc:
            result = svc.build_task_graph(
                session_id=session_id,
                nodes=[
                    {"nodeId": "n1", "title": "独立节点", "description": "无依赖"},
                ],
            )
            graph_id = result["graphId"]
            n1_id = result["nodeTaskIds"]["n1"]
            # 无前置依赖，校验应通过
            svc.assert_dependencies_satisfied(graph_id, n1_id)

    def test_completed_predecessors_passes(self):
        """所有前置已完成时校验通过。"""
        session_id = generate_id("sess")
        with TaskCollaborationService() as svc:
            result = svc.build_task_graph(
                session_id=session_id,
                nodes=[
                    {"nodeId": "n1", "title": "A", "description": "先做"},
                    {"nodeId": "n2", "title": "B", "description": "后做"},
                ],
                dependencies=[{"from": "n1", "to": "n2"}],
            )
            graph_id = result["graphId"]
            n1_id = result["nodeTaskIds"]["n1"]
            n2_id = result["nodeTaskIds"]["n2"]
            # n1 完成
            svc.update_task_status(task_id=n1_id, status="done")
            # n2 的前置已完成，校验应通过
            svc.assert_dependencies_satisfied(graph_id, n2_id)

    def test_incomplete_predecessor_rejected(self):
        """前置未完成时校验拒绝。"""
        session_id = generate_id("sess")
        with TaskCollaborationService() as svc:
            result = svc.build_task_graph(
                session_id=session_id,
                nodes=[
                    {"nodeId": "n1", "title": "A", "description": "先做"},
                    {"nodeId": "n2", "title": "B", "description": "后做"},
                ],
                dependencies=[{"from": "n1", "to": "n2"}],
            )
            graph_id = result["graphId"]
            n2_id = result["nodeTaskIds"]["n2"]
            # n1 还是 pending_dispatch，n2 不应就绪
            with pytest.raises(ValueError, match="dependency not satisfied"):
                svc.assert_dependencies_satisfied(graph_id, n2_id)


class TestReadyActivationOrder:
    """就绪激活顺序：串行链、并行 fan-out、串并混合。"""

    def test_serial_chain_order(self):
        """串行链：n1 → n2 → n3，按序就绪。"""
        session_id = generate_id("sess")
        with TaskCollaborationService() as svc:
            result = svc.build_task_graph(
                session_id=session_id,
                nodes=[
                    {"nodeId": "n1", "title": "A", "description": "先做"},
                    {"nodeId": "n2", "title": "B", "description": "再做"},
                    {"nodeId": "n3", "title": "C", "description": "最后做"},
                ],
                dependencies=[
                    {"from": "n1", "to": "n2"},
                    {"from": "n2", "to": "n3"},
                ],
            )
            graph_id = result["graphId"]

            # 初始：只有 n1 就绪（无前置）
            n1_id = result["nodeTaskIds"]["n1"]
            n2_id = result["nodeTaskIds"]["n2"]
            n3_id = result["nodeTaskIds"]["n3"]

            # n1 无前置，就绪校验通过
            svc.assert_dependencies_satisfied(graph_id, n1_id)
            # n2 有前置 n1（pending），校验拒绝
            with pytest.raises(ValueError):
                svc.assert_dependencies_satisfied(graph_id, n2_id)
            # n3 有前置 n2（pending），校验拒绝
            with pytest.raises(ValueError):
                svc.assert_dependencies_satisfied(graph_id, n3_id)

            # n1 完成后，n2 就绪
            svc.update_task_status(task_id=n1_id, status="done")
            svc.assert_dependencies_satisfied(graph_id, n2_id)
            # n3 仍不就绪
            with pytest.raises(ValueError):
                svc.assert_dependencies_satisfied(graph_id, n3_id)

            # n2 完成后，n3 就绪
            svc.update_task_status(task_id=n2_id, status="done")
            svc.assert_dependencies_satisfied(graph_id, n3_id)

    def test_parallel_fan_out(self):
        """并行 fan-out：n1 → n2, n1 → n3，n1 完成后 n2 和 n3 同时就绪。"""
        session_id = generate_id("sess")
        with TaskCollaborationService() as svc:
            result = svc.build_task_graph(
                session_id=session_id,
                nodes=[
                    {"nodeId": "n1", "title": "A", "description": "先做"},
                    {"nodeId": "n2", "title": "B", "description": "并行1"},
                    {"nodeId": "n3", "title": "C", "description": "并行2"},
                ],
                dependencies=[
                    {"from": "n1", "to": "n2"},
                    {"from": "n1", "to": "n3"},
                ],
            )
            graph_id = result["graphId"]
            n1_id = result["nodeTaskIds"]["n1"]
            n2_id = result["nodeTaskIds"]["n2"]
            n3_id = result["nodeTaskIds"]["n3"]

            # n1 完成后，n2 和 n3 都就绪
            svc.update_task_status(task_id=n1_id, status="done")
            svc.assert_dependencies_satisfied(graph_id, n2_id)
            svc.assert_dependencies_satisfied(graph_id, n3_id)

    def test_independent_nodes_parallel(self):
        """无依赖的独立节点同时就绪。"""
        session_id = generate_id("sess")
        with TaskCollaborationService() as svc:
            result = svc.build_task_graph(
                session_id=session_id,
                nodes=[
                    {"nodeId": "n1", "title": "A", "description": "独立1"},
                    {"nodeId": "n2", "title": "B", "description": "独立2"},
                ],
            )
            graph_id = result["graphId"]
            n1_id = result["nodeTaskIds"]["n1"]
            n2_id = result["nodeTaskIds"]["n2"]

            # 两者都无前置，同时就绪
            svc.assert_dependencies_satisfied(graph_id, n1_id)
            svc.assert_dependencies_satisfied(graph_id, n2_id)


class TestBuildTaskGraphContract:
    """build_task_graph 返回值契约。"""

    def test_return_structure(self):
        """返回值含 graphId / nodeTaskIds / confirmationRequired / readyNodeCount。"""
        session_id = generate_id("sess")
        with TaskCollaborationService() as svc:
            result = svc.build_task_graph(
                session_id=session_id,
                nodes=[
                    {"nodeId": "n1", "title": "A", "description": "先做"},
                    {
                        "nodeId": "n2",
                        "title": "B",
                        "description": "后做",
                        "needsConfirmation": True,
                    },
                ],
                dependencies=[{"from": "n1", "to": "n2"}],
            )
            assert "graphId" in result
            assert "nodeTaskIds" in result
            assert "confirmationRequired" in result
            assert "readyNodeCount" in result
            assert result["confirmationRequired"] is True
            assert result["readyNodeCount"] == 1  # 只有 n1 无前置
            assert len(result["nodeTaskIds"]) == 2

    def test_no_confirmation_when_none_needed(self):
        """无 needsConfirmation 节点时 confirmationRequired=False。"""
        session_id = generate_id("sess")
        with TaskCollaborationService() as svc:
            result = svc.build_task_graph(
                session_id=session_id,
                nodes=[
                    {"nodeId": "n1", "title": "A", "description": "普通"},
                    {"nodeId": "n2", "title": "B", "description": "普通"},
                ],
                dependencies=[{"from": "n1", "to": "n2"}],
            )
            assert result["confirmationRequired"] is False

    def test_capability_scope_persisted_as_executor_json(self):
        """capabilityScope 落库格式必须与 TaskExecutorAdapter 的 JSON 解析一致。"""
        from src.business.orchestration.agent.task_executor_adapter import (
            _parse_capability_scope,
        )

        session_id = generate_id("sess")
        with TaskCollaborationService() as svc:
            result = svc.build_task_graph(
                session_id=session_id,
                nodes=[
                    {
                        "nodeId": "n1",
                        "title": "A",
                        "description": "限定工具",
                        "capabilityScope": ["read_file", "exec"],
                    },
                ],
            )
            task = svc._tasks.get_task(result["nodeTaskIds"]["n1"])
            assert json.loads(task.capability_scope) == ["read_file", "exec"]
            assert _parse_capability_scope(task.capability_scope) == ["read_file", "exec"]

    def test_specialist_hint_without_assignee_id_is_not_persisted_as_specialist(self):
        """只有 specialist hint 没有具体 id 时不能落成空 specialist 派发。"""
        session_id = generate_id("sess")
        with TaskCollaborationService() as svc:
            result = svc.build_task_graph(
                session_id=session_id,
                nodes=[
                    {
                        "nodeId": "n1",
                        "title": "A",
                        "description": "建议专员但未指定 id",
                        "assigneeHint": "specialist",
                    },
                ],
            )
            task = svc._tasks.get_task(result["nodeTaskIds"]["n1"])
            assert task.assignee_type is None
            assert task.assignee_id is None

    def test_specialist_hint_with_assignee_id_is_persisted(self):
        """带具体 assigneeId 的 specialist hint 可作为定向专员派发。"""
        session_id = generate_id("sess")
        with TaskCollaborationService() as svc:
            result = svc.build_task_graph(
                session_id=session_id,
                nodes=[
                    {
                        "nodeId": "n1",
                        "title": "A",
                        "description": "定向专员",
                        "assigneeHint": "specialist",
                        "assigneeId": "spec_1",
                    },
                ],
            )
            task = svc._tasks.get_task(result["nodeTaskIds"]["n1"])
            assert task.assignee_type == "specialist"
            assert task.assignee_id == "spec_1"


class TestMutateTaskGraph:
    """mutate_task_graph 改图操作。"""

    def test_add_node(self):
        """add_node 添加新节点。"""
        session_id = generate_id("sess")
        with TaskCollaborationService() as svc:
            result = svc.build_task_graph(
                session_id=session_id,
                nodes=[
                    {"nodeId": "n1", "title": "A", "description": "原节点"},
                ],
            )
            graph_id = result["graphId"]

            mutation = svc.mutate_task_graph(
                graph_id=graph_id,
                session_id=session_id,
                changes=[
                    {"op": "add_node", "nodeId": "n2", "title": "新增", "description": "自愈添加"},
                ],
                reason="自愈：添加替代节点",
            )
            assert len(mutation["applied"]) == 1
            assert len(mutation["rejected"]) == 0

    def test_skip_node(self):
        """skip_node 跳过节点（标记 cancelled）。"""
        session_id = generate_id("sess")
        with TaskCollaborationService() as svc:
            result = svc.build_task_graph(
                session_id=session_id,
                nodes=[
                    {"nodeId": "n1", "title": "A", "description": "要跳过的"},
                ],
            )
            graph_id = result["graphId"]
            n1_id = result["nodeTaskIds"]["n1"]

            mutation = svc.mutate_task_graph(
                graph_id=graph_id,
                session_id=session_id,
                changes=[
                    {"op": "skip_node", "taskId": n1_id},
                ],
                reason="自愈：跳过失败节点",
            )
            assert len(mutation["applied"]) == 1
            # 验证节点已 cancelled
            task = svc._tasks.get_task(n1_id)
            assert task.status == "cancelled"

    def test_add_dependency_cycle_rejected(self):
        """add_dependency 不允许创建环。"""
        session_id = generate_id("sess")
        with TaskCollaborationService() as svc:
            result = svc.build_task_graph(
                session_id=session_id,
                nodes=[
                    {"nodeId": "n1", "title": "A", "description": "a"},
                    {"nodeId": "n2", "title": "B", "description": "b"},
                ],
                dependencies=[{"from": "n1", "to": "n2"}],
            )
            graph_id = result["graphId"]
            n1_id = result["nodeTaskIds"]["n1"]
            n2_id = result["nodeTaskIds"]["n2"]

            # 尝试添加 n2→n1（会形成环）
            mutation = svc.mutate_task_graph(
                graph_id=graph_id,
                session_id=session_id,
                changes=[
                    {"op": "add_dependency", "from": n2_id, "to": n1_id},
                ],
                reason="尝试加环",
            )
            assert len(mutation["rejected"]) == 1
            assert "cycle" in str(mutation["rejected"][0].get("reason", "")).lower()
