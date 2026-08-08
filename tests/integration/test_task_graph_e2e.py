"""US1 集成 E2E：复杂任务分解成有序图并按序执行。

验证：
- 中等任务：主助理调 build_task_graph 自拆
- 超阈值任务：主助理 delegate_to_specialist(planner)，规划专员产出图
- scheduler 按依赖推进
- 全图完成后汇报
"""

import json

import pytest

from src.business.agents.config import AgentResult, ResultType
from src.business.brain.specialist_service import SpecialistService
from src.business.orchestration.agent import AgentOrchestrator
from src.business.task_collaboration.service import TaskCollaborationService
from src.data.repos.base_repository import generate_id


class TestTaskGraphE2E:
    """US1 端到端集成测试。"""

    def test_build_task_graph_creates_dag_with_dependencies(self):
        """中等任务自拆：build_task_graph 创建带依赖边的 DAG。"""
        session_id = generate_id("sess")
        with TaskCollaborationService() as svc:
            result = svc.build_task_graph(
                session_id=session_id,
                nodes=[
                    {"nodeId": "n1", "title": "收集会议纪要", "description": "拉取三场会议记录"},
                    {"nodeId": "n2", "title": "提取待办", "description": "从纪要中提取待办项"},
                    {"nodeId": "n3", "title": "合并周报", "description": "合并待办成周报草稿"},
                ],
                dependencies=[
                    {"from": "n1", "to": "n2"},
                    {"from": "n2", "to": "n3"},
                ],
            )
            assert result["graphId"] is not None
            assert len(result["nodeTaskIds"]) == 3
            assert result["readyNodeCount"] == 1  # 只有 n1 无前置

            graph_id = result["graphId"]
            snapshot = svc.get_graph_snapshot(session_id=session_id, graph_id=graph_id)
            assert snapshot is not None

            # 验证 dependency 边
            dep_edges = [e for e in snapshot.edges if e.type == "dependency"]
            assert len(dep_edges) == 2

    def test_scheduler_advances_on_completion(self):
        """scheduler 按依赖推进：前置完成后下游就绪。"""
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
            n1_id = result["nodeTaskIds"]["n1"]
            n2_id = result["nodeTaskIds"]["n2"]
            graph_id = result["graphId"]

            # n1 就绪
            svc._tasks.assert_dependencies_satisfied(graph_id, n1_id)

            # n2 不就绪
            with pytest.raises(ValueError, match="dependency not satisfied"):
                svc._tasks.assert_dependencies_satisfied(graph_id, n2_id)

            # n1 完成后 n2 就绪
            svc.update_task_status(task_id=n1_id, status="completed")
            svc._tasks.assert_dependencies_satisfied(graph_id, n2_id)

    def test_parallel_nodes_both_ready(self):
        """并行无依赖节点同时就绪。"""
        session_id = generate_id("sess")
        with TaskCollaborationService() as svc:
            result = svc.build_task_graph(
                session_id=session_id,
                nodes=[
                    {"nodeId": "n1", "title": "独立1", "description": "无依赖"},
                    {"nodeId": "n2", "title": "独立2", "description": "无依赖"},
                    {"nodeId": "n3", "title": "汇总", "description": "汇总结果"},
                ],
                dependencies=[
                    {"from": "n1", "to": "n3"},
                    {"from": "n2", "to": "n3"},
                ],
            )
            n1_id = result["nodeTaskIds"]["n1"]
            n2_id = result["nodeTaskIds"]["n2"]
            n3_id = result["nodeTaskIds"]["n3"]
            graph_id = result["graphId"]

            # n1 和 n2 都就绪
            svc._tasks.assert_dependencies_satisfied(graph_id, n1_id)
            svc._tasks.assert_dependencies_satisfied(graph_id, n2_id)

            # n3 不就绪
            with pytest.raises(ValueError):
                svc._tasks.assert_dependencies_satisfied(graph_id, n3_id)

            # 两个前置都完成后 n3 就绪
            svc.update_task_status(task_id=n1_id, status="completed")
            svc.update_task_status(task_id=n2_id, status="completed")
            svc._tasks.assert_dependencies_satisfied(graph_id, n3_id)

    def test_full_graph_completion(self):
        """全图完成检测。"""
        session_id = generate_id("sess")
        with TaskCollaborationService() as svc:
            result = svc.build_task_graph(
                session_id=session_id,
                nodes=[
                    {"nodeId": "n1", "title": "A", "description": "先做"},
                ],
            )
            n1_id = result["nodeTaskIds"]["n1"]

            # 完成根节点和 n1
            graph_id = result["graphId"]
            root = svc._tasks.get_graph_root(graph_id)
            svc.update_task_status(task_id=root.task_id, status="completed")
            svc.update_task_status(task_id=n1_id, status="completed")

            snapshot = svc.get_graph_snapshot(session_id=session_id, graph_id=graph_id)
            all_completed = all(t.status == "completed" for t in snapshot.tasks)
            assert all_completed

    def test_needs_confirmation_node_in_graph(self):
        """含需确认节点的图：confirmationRequired=True。"""
        session_id = generate_id("sess")
        with TaskCollaborationService() as svc:
            result = svc.build_task_graph(
                session_id=session_id,
                nodes=[
                    {"nodeId": "n1", "title": "整理数据", "description": "整理"},
                    {
                        "nodeId": "n2",
                        "title": "发送邮件",
                        "description": "对外发送",
                        "needsConfirmation": True,
                    },
                ],
                dependencies=[{"from": "n1", "to": "n2"}],
            )
            assert result["confirmationRequired"] is True

    def test_planner_specialist_delegation_builds_graph_for_parent_session(
        self, mock_config, monkeypatch
    ):
        """超阈值路径：delegate_to_specialist(planner) 穿过 planner 工具装配并产出父会话任务图。"""
        mock_config.get_assistant_tasks_unified_dispatch_enabled.return_value = False

        planner = SpecialistService().ensure_planner_specialist()
        parent_session_id = generate_id("parent")
        from src.data.repos import UserTaskRepository

        user_task_id = UserTaskRepository().create(
            session_id=parent_session_id, title="会议纪要"
        ).task_id

        class _PlannerLoop:
            def __init__(self) -> None:
                self.graph_result: dict | None = None

            def run(self, session_id, user_input, *, tools, system_prompt_override=None):
                tool_list = tools() if callable(tools) else tools
                names = {tool.name for tool in tool_list}
                assert "build_task_graph" in names
                assert "todo_update" not in names
                assert "ask_parent" not in names
                build_tool = next(tool for tool in tool_list if tool.name == "build_task_graph")
                self.graph_result = json.loads(
                    build_tool.handler(
                        taskId=user_task_id,
                        nodes=[
                            {"nodeId": "n1", "title": "收集资料", "description": "收集资料"},
                            {"nodeId": "n2", "title": "生成报告", "description": "生成报告"},
                        ],
                        dependencies=[{"from": "n1", "to": "n2"}],
                    )
                )
                return AgentResult(result_type=ResultType.COMPLETED)

        planner_loop = _PlannerLoop()
        orchestrator = AgentOrchestrator(
            llm_client=object(),
            config=mock_config,
            llm_reviewer=object(),
        )
        monkeypatch.setattr(orchestrator, "_get_loop", lambda *args, **kwargs: planner_loop)
        monkeypatch.setattr(orchestrator, "_resolve_user_tool_ids", lambda **kwargs: set())
        monkeypatch.setattr(orchestrator, "_specialist_equipped_skills_snapshot", lambda _s: [])
        monkeypatch.setattr(
            orchestrator,
            "_extract_latest_assistant_text",
            lambda _session_id, **_kw: "planner graph built",
        )

        result = orchestrator.delegation_orchestrator.delegate_to_specialist(
            parent_session_id=parent_session_id,
            specialist_name=planner["name"],
            task="整理会议纪要、生成报告并准备对外发送",
            user_task_id=user_task_id,
        )

        assert result["success"] is True
        assert planner_loop.graph_result is not None
        graph_id = planner_loop.graph_result["graphId"]
        with TaskCollaborationService() as svc:
            snapshot = svc.get_graph_snapshot(session_id=parent_session_id, graph_id=graph_id)
            assert snapshot is not None
            assert len([edge for edge in snapshot.edges if edge.type == "dependency"]) == 1
