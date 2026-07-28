"""Planner specialist 工具门卫：规划专员只拿规划工具，不拿执行器工具（FR-005）。

真断言：实例化 ``_build_delegated_executor_tools(role_kind="planner")``，验证工具名集合
不含 todo_update/ask_parent/meeting_send_message/delegate_to_subagent，含 build_task_graph；
对比 executor 角色仍含执行器工具（防 planner 分支误伤 executor）。schema 列存在性一并守护。
"""

import json

from src.business.agents.config import AgentType
from src.business.task_collaboration.service import TaskCollaborationService
from src.data.repos.base_repository import generate_id


def _tool_names(factory):
    return {t.name for t in factory()}


# planner MUST NOT 拿的执行器协作工具（FR-005：只规划不执行，深度封顶）
_EXECUTOR_ONLY_TOOLS = {
    "todo_update",
    "ask_parent",
    "meeting_send_message",
    "delegate_to_subagent",
}

# planner MUST NOT 拿的 BUILTIN_GENERAL_TOOLS 工具（FR-005/DEC-B：只规划不执行）
#
# DEC-B 修订 2026-07-27：原清单把纯只读的读取/搜索也算作"执行工具"一并禁掉，
# 导致规划专员无法核实任务书里的指代，只能把调研甩给下游执行体。只读四件套 +
# load_tool_output 已移到 _PLANNER_READONLY_TOOL_NAMES 放行；写、执行、进程管理
# 和网络访问仍然禁止——"只规划不执行"的硬边界不变。
_BUILTIN_EXECUTION_TOOL_NAMES = {
    "web_search",
    "web_fetch",
    "write_file",
    "edit_file",
    "apply_patch",
    "exec",
    "process_list",
    "process_poll",
    "process_logs",
    "process_wait",
    "wait_for_process_event",
    "process_stop",
    "process_send_input",
    "process_close",
}

# planner MUST 拿到的只读调研工具（DEC-B 修订）——缺任何一个都会让它退回
# "先阅读以下文件确认…"式的甩锅节点描述
_PLANNER_READONLY_TOOL_NAMES = {
    "read_file",
    "list_dir",
    "search_files",
    "search_content",
    "load_tool_output",
}


def _planner_tools(orch):
    return _tool_names(
        orch._build_delegated_executor_tools(
            None,
            agent_type=AgentType.SPECIALIST,
            specialist_id="planner-guard",
            role_kind="planner",
        )
    )


def _executor_tools(orch):
    return _tool_names(
        orch._build_delegated_executor_tools(
            None,
            agent_type=AgentType.SPECIALIST,
            specialist_id="spec-guard",
            role_kind="executor",
        )
    )


class TestPlannerToolScope:
    """FR-005: planner 工具集边界——真断言工具名集合。"""

    def test_planner_excludes_executor_collaboration_tools(self, in_memory_db, orchestrator):
        """planner 工具集不含 todo_update/ask_parent/meeting_send_message/delegate_to_subagent。"""
        names = _planner_tools(orchestrator)
        leaked = _EXECUTOR_ONLY_TOOLS & names
        assert not leaked, f"planner 不该拿执行器工具，却包含：{leaked}"

    def test_planner_excludes_builtin_execution_tools(self, in_memory_db, orchestrator):
        """planner 工具集不含写/执行/进程/网络工具（DEC-B：只规划不执行）。"""
        names = _planner_tools(orchestrator)
        leaked = _BUILTIN_EXECUTION_TOOL_NAMES & names
        assert not leaked, f"planner 不该拿 BUILTIN 执行工具，却包含：{leaked}"

    def test_planner_includes_readonly_research_tools(self, in_memory_db, orchestrator):
        """planner 必须拿到只读调研工具（DEC-B 修订）。

        缺任何一个，规划专员就无法核实任务书里的指代（"复用现有 X"），只能把
        调研甩给下游执行体——那次 run 的 TaskDetailPane 节点就是这么写成
        "先阅读以下文件确认…"的。
        """
        names = _planner_tools(orchestrator)
        missing = _PLANNER_READONLY_TOOL_NAMES - names
        assert not missing, f"planner 缺少只读调研工具：{missing}"

    def test_planner_readonly_tools_are_side_effect_free(self):
        """放行清单里的工具必须无副作用——防止以后某个工具变成有副作用还留在清单里。"""
        from src.business.agents.tools.builtin_general_tools import BUILTIN_GENERAL_TOOLS

        by_name = {tool.name: tool for tool in BUILTIN_GENERAL_TOOLS}
        for name in _PLANNER_READONLY_TOOL_NAMES:
            tool = by_name.get(name)
            assert tool is not None, f"放行清单引用了不存在的工具：{name}"
            assert (
                getattr(tool, "has_side_effects", True) is False
            ), f"{name} 有副作用，不该出现在 planner 只读放行清单里"

    def test_executor_still_includes_builtin_tools(self, in_memory_db, orchestrator):
        """executor（默认）仍含 BUILTIN 执行工具——防 planner 分支误伤 executor 路径。"""
        names = _executor_tools(orchestrator)
        assert "read_file" in names
        assert "exec" in names

    def test_planner_includes_build_task_graph(self, in_memory_db, orchestrator):
        """planner 拿 build_task_graph（规划变体）。"""
        names = _planner_tools(orchestrator)
        assert "build_task_graph" in names

    def test_planner_includes_list_specialists(self, in_memory_db, orchestrator):
        """planner 拿 list_specialists——build_task_graph 的 assigneeId 要求填具体
        specialist id，没有这个工具就只能把所有节点退化成临时子代理。"""
        names = _planner_tools(orchestrator)
        assert "list_specialists" in names

    def test_executor_excludes_list_specialists(self, in_memory_db, orchestrator):
        """executor 不拿 list_specialists——它不拆任务图，不需要挑执行者。"""
        names = _executor_tools(orchestrator)
        assert "list_specialists" not in names

    def test_executor_still_includes_executor_tools(self, in_memory_db, orchestrator):
        """executor（默认）仍含执行器工具——防 planner 分支误伤 executor 路径。"""
        names = _executor_tools(orchestrator)
        assert "todo_update" in names
        assert "ask_parent" in names

    def test_planner_build_graph_binds_parent_session(self, in_memory_db, orchestrator):
        """planner 在子会话内调用 build_task_graph 时，图必须归属父助理会话。"""
        parent_session_id = generate_id("parent")
        child_session_id = generate_id("child")
        factory = orchestrator._build_delegated_executor_tools(
            None,
            agent_type=AgentType.SPECIALIST,
            executor_id=child_session_id,
            specialist_id="planner-guard",
            parent_session_id=parent_session_id,
            role_kind="planner",
        )
        tool = next(t for t in factory() if t.name == "build_task_graph")

        result = json.loads(
            tool.handler(nodes=[{"nodeId": "n1", "title": "A", "description": "x"}])
        )

        with TaskCollaborationService() as svc:
            assert (
                svc.get_graph_snapshot(
                    session_id=parent_session_id,
                    graph_id=result["graphId"],
                )
                is not None
            )
            assert (
                svc.get_graph_snapshot(
                    session_id=child_session_id,
                    graph_id=result["graphId"],
                )
                is None
            )


class TestPlannerSchema:
    """schema 列守护（planner/needs_confirmation 落库基础）。"""

    def test_planner_role_kind_exists_in_model(self):
        from src.data.models_sqlite import BrainSpecialist

        assert hasattr(BrainSpecialist, "role_kind")

    def test_planner_default_role_is_executor(self):
        from src.data.models_sqlite import BrainSpecialist

        col = BrainSpecialist.__table__.columns.get("role_kind")
        assert col is not None and col.default is not None
        assert col.default.arg == "executor"

    def test_requires_confirmation_column_exists(self):
        from src.data.models_sqlite import AssistantTask

        assert hasattr(AssistantTask, "requires_confirmation")

    def test_requires_confirmation_default_zero(self):
        from src.data.models_sqlite import AssistantTask

        col = AssistantTask.__table__.columns.get("requires_confirmation")
        assert col is not None and col.default is not None
        assert col.default.arg == 0


class TestPlannerSpecialistCatalogInjection:
    """planner 的 system prompt 必须带可用专员目录——否则 assigneeId 无从填起。"""

    @staticmethod
    def _planner(specialist_id="sp_me"):
        from types import SimpleNamespace

        return SimpleNamespace(
            specialist_id=specialist_id,
            name="planner",
            description="规划",
            role_definition="拆图",
            role_kind="planner",
        )

    @staticmethod
    def _patch_catalog(monkeypatch, payload):
        from src.business.brain import assistant_facades

        monkeypatch.setattr(
            assistant_facades.AssistantSpecialistToolFacade,
            "list_active",
            lambda self, **kwargs: payload,
        )

    def test_planner_prompt_contains_specialist_catalog(self, monkeypatch):
        from src.business.orchestration.agent.orchestrator import AgentOrchestrator

        self._patch_catalog(
            monkeypatch,
            {
                "specialists": [
                    {
                        "specialist_id": "sp_coder",
                        "name": "编码执行专员",
                        "description": "跑外部 coding",
                        "role_definition": "执行编码任务",
                        "tool_whitelist": ["start_external_coding_session"],
                    }
                ],
                "total": 1,
            },
        )
        prompt = AgentOrchestrator._build_specialist_prompt(self._planner(), [], equipped_skills=[])

        assert "## 可用专员" in prompt
        assert "sp_coder" in prompt
        assert "编码执行专员" in prompt
        # 工具白名单必须一并给出：planner 要据此判断该专员能不能完成这个节点
        assert "start_external_coding_session" in prompt

    def test_planner_prompt_excludes_self(self, monkeypatch):
        """planner 不能把节点派回给自己，目录里不该出现自己。"""
        from src.business.orchestration.agent.orchestrator import AgentOrchestrator

        self._patch_catalog(
            monkeypatch,
            {
                "specialists": [
                    {
                        "specialist_id": "sp_me",
                        "name": "planner",
                        "description": "规划",
                        "role_definition": "拆图",
                        "tool_whitelist": ["build_task_graph"],
                    }
                ],
                "total": 1,
            },
        )
        prompt = AgentOrchestrator._build_specialist_prompt(self._planner("sp_me"), [], equipped_skills=[])

        assert "当前没有其他可用专员" in prompt

    def test_executor_prompt_has_no_specialist_catalog(self, monkeypatch):
        """executor 不拆图，不注入专员目录。"""
        from types import SimpleNamespace

        from src.business.orchestration.agent.orchestrator import AgentOrchestrator

        executor = SimpleNamespace(
            specialist_id="sp_x",
            name="编码执行专员",
            description="执行",
            role_definition="干活",
            role_kind="executor",
        )
        prompt = AgentOrchestrator._build_specialist_prompt(executor, [], equipped_skills=[])

        assert "## 可用专员" not in prompt

    def test_catalog_failure_degrades_without_breaking_delegation(self, monkeypatch):
        """目录加载失败只降级为提示，不得中断委派（对比方法论装备失败是 raise）。"""
        from src.business.brain import assistant_facades
        from src.business.orchestration.agent.orchestrator import AgentOrchestrator

        def _boom(self, **kwargs):
            raise RuntimeError("specialist repo down")

        monkeypatch.setattr(
            assistant_facades.AssistantSpecialistToolFacade, "list_active", _boom
        )
        prompt = AgentOrchestrator._build_specialist_prompt(self._planner(), [], equipped_skills=[])

        assert "专员目录暂时不可用" in prompt
        assert "list_specialists" in prompt
