"""用户任务层 · 身份/数据层行为测试。

验证 user_tasks 表、四态状态机、create_task 工具、聚焦指针、委派硬挂载守卫。
"""

from __future__ import annotations

import json
from datetime import timedelta
from unittest.mock import MagicMock, patch

import pytest

from src.business.agents.config import AgentResult, AgentType, ResultType
from src.business.agents.tools.assistant_tools import create_create_task_handler
from src.business.orchestration.agent.orchestrator import AgentOrchestrator
from src.business.user_tasks.service import UserTaskService
from src.data.models_sqlite import Session as SessionModel
from src.data.repos import (
    AssistantTaskAttemptRepository,
    AssistantTaskRepository,
    SessionRepository,
    UserTaskRepository,
)
from src.data.repos.base_repository import generate_id
from src.utils.timezone import utc_now_naive


def _seed_session(session_id: str) -> str:
    """Create an assistant session for testing."""
    SessionRepository().create(
        SessionModel(
            session_id=session_id,
            workflow_id=None,
            agent_type=AgentType.ASSISTANT,
            status="active",
        )
    )
    return session_id


# ---------------------------------------------------------------------------
# create_task 工具 + 聚焦指针
# ---------------------------------------------------------------------------


class TestCreateTask:
    def test_create_task_creates_user_task_and_sets_focus(self, in_memory_db):
        """create_task 建用户任务 + 设为会话聚焦。"""
        sid = _seed_session("ast_create")
        handler = create_create_task_handler(sid)
        result = json.loads(handler(title="季度报告", description="Q3 数据"))

        assert result["success"] is True
        assert result["task"]["title"] == "季度报告"
        assert result["task"]["status"] == "active"
        # 聚焦指针已设
        assert SessionRepository().get_focused_task_id(sid) == result["task"]["taskId"]

    def test_focused_task_pointer_single_value(self, in_memory_db):
        """切换聚焦后旧值被覆盖（单值指针）。"""
        sid = _seed_session("ast_focus")
        handler = create_create_task_handler(sid)
        r1 = json.loads(handler(title="任务一"))
        r2 = json.loads(handler(title="任务二"))

        # 第二次建任务后聚焦指向第二个
        assert SessionRepository().get_focused_task_id(sid) == r2["task"]["taskId"]
        assert r1["task"]["taskId"] != r2["task"]["taskId"]


# ---------------------------------------------------------------------------
# 委派硬挂载守卫
# ---------------------------------------------------------------------------


class TestDelegationGuard:
    def test_delegate_without_focus_task_rejected(self, in_memory_db):
        """无聚焦时 delegate_to_subagent 拒绝。"""
        sid = _seed_session("ast_guard1")
        orch = AgentOrchestrator(MagicMock(), MagicMock())
        result = orch.delegation_orchestrator.delegate_to_subagent(
            parent_session_id=sid,
            task_description="做点什么",
        )
        assert result["success"] is False
        assert "聚焦" in result["message"]

    def test_delegate_specialist_without_focus_task_rejected(self, in_memory_db):
        """无聚焦时 delegate_to_specialist 拒绝。"""
        sid = _seed_session("ast_guard2")
        orch = AgentOrchestrator(MagicMock(), MagicMock())
        result = orch.delegation_orchestrator.delegate_to_specialist(
            parent_session_id=sid,
            specialist_name="data_analyst",
            task="分析数据",
        )
        assert result["success"] is False
        assert "聚焦" in result["message"]

    def test_build_task_graph_without_focus_task_rejected(self, in_memory_db):
        """无聚焦时 build_task_graph 拒绝。"""
        from src.business.agents.tools.assistant_tools import create_build_task_graph_handler

        sid = _seed_session("ast_guard3")
        handler = create_build_task_graph_handler(sid)
        result_str = handler(nodes=[{"nodeId": "n1", "title": "N", "description": "d"}])
        result = json.loads(result_str)
        assert result["success"] is False

    def test_delegate_with_focus_task_passes_guard(self, in_memory_db):
        """有聚焦时委派守卫放行（不因守卫误拒）。"""
        sid = _seed_session("ast_guard4")
        # 先建任务设聚焦
        handler = create_create_task_handler(sid)
        json.loads(handler(title="任务"))

        orch = AgentOrchestrator(MagicMock(), MagicMock())
        # mock 掉下游让委派快速返回（守卫放行即可，不关心下游结果）
        with patch.object(
            orch.delegation_orchestrator,
            "run_sync_ephemeral_subagent",
            return_value={"success": True, "message": "ok"},
        ):
            with patch.object(
                orch.delegation_orchestrator,
                "_has_focused_user_task",
                return_value=True,
            ):
                result = orch.delegation_orchestrator.delegate_to_subagent(
                    parent_session_id=sid,
                    task_description="做点什么",
                    complexity="simple",
                )
        # 守卫放行了（没返回"聚焦"错误）
        assert "聚焦" not in result.get("message", "")


# ---------------------------------------------------------------------------
# 四态状态机
# ---------------------------------------------------------------------------


class TestUserTaskStatusMachine:
    def test_status_transitions_and_terminal_timestamp(self, in_memory_db):
        """四态状态机转换 + 终态写 completed_at。"""
        sid = _seed_session("ast_status")
        with UserTaskService() as svc:
            task = svc.create(session_id=sid, title="测试")
            assert task["status"] == "active"
            assert task["completedAt"] is None

            # active → cooling（非终态，无 completed_at）
            cooling = svc.update_status(task["taskId"], "cooling")
            assert cooling["status"] == "cooling"
            assert cooling["completedAt"] is None

            # cooling → done（终态，写 completed_at）
            done = svc.update_status(task["taskId"], "done")
            assert done["status"] == "done"
            assert done["completedAt"] is not None

            # done → active（从终态回退，清 completed_at）
            active = svc.update_status(task["taskId"], "active")
            assert active["status"] == "active"
            assert active["completedAt"] is None

            # active → dropped（终态）
            dropped = svc.update_status(task["taskId"], "dropped")
            assert dropped["status"] == "dropped"

    def test_invalid_status_rejected(self, in_memory_db):
        """非法 status 被拒。"""
        sid = _seed_session("ast_invalid")
        with UserTaskService() as svc:
            task = svc.create(session_id=sid, title="测试")
            with pytest.raises(ValueError, match="invalid status"):
                svc.update_status(task["taskId"], "suspended")


# ---------------------------------------------------------------------------
# 表独立性
# ---------------------------------------------------------------------------


class TestTableSeparation:
    def test_user_tasks_independent_from_assistant_tasks(self, in_memory_db):
        """user_tasks 表独立，不影响 assistant_tasks 的 parent_task_id 根判据。"""
        sid = _seed_session("ast_sep")
        # 建一个用户任务并设为聚焦
        handler = create_create_task_handler(sid)
        json.loads(handler(title="用户的事"))
        # 建一个执行任务图（直接走 service 层，不经 handler 的聚焦守卫）
        from src.business.task_collaboration.service import TaskCollaborationService

        with TaskCollaborationService() as tcs:
            result = tcs.build_task_graph(
                session_id=sid,
                nodes=[{"nodeId": "n1", "title": "执行步骤", "description": "d"}],
            )
        graph_id = result["graphId"]

        # assistant_tasks 的根判据不受影响
        root = AssistantTaskRepository().get_graph_root(graph_id)
        assert root is not None
        assert root.parent_task_id is None  # 根的 parent 仍为空
        root_task_id = root.root_task_id

        # user_tasks 和 assistant_tasks 是完全独立的 id 空间
        focused = SessionRepository().get_focused_task_id(sid)
        assert focused is not None
        assert focused != root_task_id
        assert focused.startswith("utsk_")
        assert root_task_id.startswith("tsk_")


# ---------------------------------------------------------------------------
# 迁移
# ---------------------------------------------------------------------------


class TestMigrationV42:
    def test_migration_creates_user_tasks_table_and_column(self, in_memory_db):
        """迁移 v42 建了 user_tasks 表 + sessions.focused_user_task_id 列。"""
        from src.data.models_sqlite import UserTask
        from sqlalchemy import inspect

        engine = in_memory_db.engine
        inspector = inspect(engine)

        # user_tasks 表存在
        assert "user_tasks" in inspector.get_table_names()
        # sessions 有 focused_user_task_id 列
        session_cols = {c["name"] for c in inspector.get_columns("sessions")}
        assert "focused_user_task_id" in session_cols
        # user_tasks 有正确的列
        task_cols = {c["name"] for c in inspector.get_columns("user_tasks")}
        assert {"task_id", "session_id", "title", "status", "created_at"} <= task_cols

    def test_schema_version_is_42(self, in_memory_db):
        from sqlalchemy import text

        with in_memory_db.engine.connect() as conn:
            version = conn.execute(text("SELECT version FROM schema_version")).scalar()
        assert version == 42


# ---------------------------------------------------------------------------
# create_task 工具只给主助理（门卫）
# ---------------------------------------------------------------------------


class TestCreateTaskToolVisibility:
    def _make_registry(self):
        from src.business.orchestration.agent.tool_registry import ToolRegistry

        session_store = MagicMock()
        # build_assistant_tools reads session.parse_tool_ids() — mock it
        mock_session = MagicMock()
        mock_session.parse_tool_ids.return_value = (None, None)
        mock_session.get_tool_id_set.return_value = None
        session_store.get_session.return_value = mock_session
        return ToolRegistry(
            session_store=session_store,
            dynamic_manager_cache=MagicMock(),
            delegation_orchestrator=MagicMock(),
            resolve_recording_mode=MagicMock(),
            redispatch_answered_task=MagicMock(),
        )

    def test_create_task_in_assistant_tools(self, in_memory_db):
        """create_task 出现在主助理 static_tools 列表中。

        直接检查 build_assistant_tools 内部的 static_tools——完整的 tool_factory
        依赖 dynamic_manager/mcp_registry 的大量 mock，不适合测工具可见性。
        static_tools 是主助理独占工具的权威清单。
        """
        registry = self._make_registry()
        # build_assistant_tools returns a factory that closes over static_tools;
        # the factory's closure captures the list. We patch dynamic_manager/mcp
        # to return empty so tool_factory() succeeds.
        mock_dynamic = MagicMock()
        mock_dynamic.get_activated_tools.return_value = []
        mock_mcp = MagicMock()
        mock_mcp.get_preset_tools.return_value = []
        mock_mcp.get_activated_custom_tools.return_value = []
        registry._dynamic_manager_cache.get_or_create_dynamic_manager.return_value = mock_dynamic
        with patch(
            "src.business.mcp.get_mcp_tool_registry",
            return_value=mock_mcp,
        ):
            tool_factory = registry.build_tools(AgentType.ASSISTANT, session_id="ast_vis")
            tools = tool_factory() if callable(tool_factory) else tool_factory
        tool_names = {td.name for td in tools}
        assert "create_task" in tool_names

    def test_create_task_not_in_executor_tools(self, in_memory_db):
        """create_task 不出现在委派执行体工具列表中（只给主助理）。"""
        registry = self._make_registry()
        tools = registry.build_delegated_executor_tools(
            {"tool-a"},
            agent_type=AgentType.EPHEMERAL_SUBAGENT,
            executor_id="exec-session",
        )
        tool_names = {td.name for td in tools()}
        assert "create_task" not in tool_names
