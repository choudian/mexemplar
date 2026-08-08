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
    def test_create_task_creates_user_task(self, in_memory_db):
        """create_task 建用户任务（聚焦指针已移除，不再有建完即聚焦副作用）。"""
        sid = _seed_session("ast_create")
        handler = create_create_task_handler(sid)
        result = json.loads(handler(title="季度报告", description="Q3 数据"))

        assert result["success"] is True
        assert result["task"]["title"] == "季度报告"
        assert result["task"]["status"] == "active"

    def test_create_task_does_not_set_focus_pointer(self, in_memory_db):
        """create_task 不再写聚焦指针——后续委派/建图改由主助理显式传 taskId。

        聚焦指针已移除：session 不再持有 focused_user_task_id 列，create_task
        不做 update_focused_task 副作用。回归保护：避免有人把聚焦指针再加回来。
        """
        sid = _seed_session("ast_focus")
        handler = create_create_task_handler(sid)
        r1 = json.loads(handler(title="任务一"))
        r2 = json.loads(handler(title="任务二"))

        # 两次建任务都成功，互不干扰；不再有单值聚焦指针
        assert r1["task"]["taskId"] != r2["task"]["taskId"]
        # SessionRepository 已无 get_focused_task_id 方法
        assert not hasattr(SessionRepository(), "get_focused_task_id")


# ---------------------------------------------------------------------------
# 委派硬挂载守卫
# ---------------------------------------------------------------------------


class TestDelegationGuard:
    def test_delegate_to_subagent_requires_user_task_id(self, in_memory_db):
        """delegate_to_subagent 现在把 user_task_id 作为必填 kw-only 参数。

        聚焦指针已移除——用户任务归属由主助理经工具的 taskId 显式传入；orchestrator
        层不再做"有没有聚焦"的守卫，而是要求调用方一定带 user_task_id。
        """
        sid = _seed_session("ast_guard1")
        orch = AgentOrchestrator(MagicMock(), MagicMock())
        with pytest.raises(TypeError):
            orch.delegation_orchestrator.delegate_to_subagent(
                parent_session_id=sid,
                task_description="做点什么",
            )

    def test_delegate_to_specialist_requires_user_task_id(self, in_memory_db):
        """delegate_to_specialist 同样把 user_task_id 作为必填 kw-only 参数。"""
        sid = _seed_session("ast_guard2")
        orch = AgentOrchestrator(MagicMock(), MagicMock())
        with pytest.raises(TypeError):
            orch.delegation_orchestrator.delegate_to_specialist(
                parent_session_id=sid,
                specialist_name="data_analyst",
                task="分析数据",
            )

    def test_build_task_graph_without_task_id_rejected(self, in_memory_db):
        """build_task_graph 工具层守卫：未带 taskId 时拒绝（fail-closed）。"""
        from src.business.agents.tools.assistant_tools import create_build_task_graph_handler

        sid = _seed_session("ast_guard3")
        handler = create_build_task_graph_handler(sid)
        result_str = handler(nodes=[{"nodeId": "n1", "title": "N", "description": "d"}])
        result = json.loads(result_str)
        assert result["success"] is False

    def test_delegate_with_user_task_id_passes_to_executor(self, in_memory_db):
        """显式带 user_task_id 时委派放行，并透传给执行核心。"""
        sid = _seed_session("ast_guard4")
        orch = AgentOrchestrator(MagicMock(), MagicMock())
        # 建一个真实的用户任务，让 taskId 校验通过
        UserTaskRepository().create(session_id=sid, title="测试任务")
        user_task_id = UserTaskRepository().list_for_session(sid)[0].task_id
        captured: dict = {}

        def _fake_run_sync(*, parent_session_id, task, execution_context, tool_whitelist,
                           user_task_id, **kwargs):
            captured["user_task_id"] = user_task_id
            return {"success": True, "message": "ok"}

        with patch.object(
            orch.delegation_orchestrator,
            "run_sync_ephemeral_subagent",
            side_effect=_fake_run_sync,
        ):
            result = orch.delegation_orchestrator.delegate_to_subagent(
                parent_session_id=sid,
                task_description="做点什么",
                user_task_id=user_task_id,
                complexity="simple",
            )
        # 放行并透传
        assert captured["user_task_id"] == user_task_id
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
        # 建一个用户任务（聚焦指针已移除，create_task 不再写副作用）
        handler = create_create_task_handler(sid)
        user_task = json.loads(handler(title="用户的事"))
        # 建一个执行任务图（直接走 service 层，不经 handler 的 taskId 守卫）
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
        user_task_id = user_task["task"]["taskId"]
        assert user_task_id is not None
        assert user_task_id != root_task_id
        assert user_task_id.startswith("utsk_")
        assert root_task_id.startswith("tsk_")


# ---------------------------------------------------------------------------
# 迁移
# ---------------------------------------------------------------------------


class TestMigrationV42:
    def test_migration_creates_user_tasks_table_and_column(self, in_memory_db):
        """迁移建了 user_tasks 表 + sessions 上的用户任务归属列。

        注：原 v42 引入的 ``focused_user_task_id`` 单值聚焦指针已在去聚焦指针
        重构中改为 ``owner_user_task_id``（会话归属的用户任务 id）。本测试只断言
        表与归属列存在，不再锁定已废弃的聚焦指针列名。
        """
        from src.data.models_sqlite import UserTask
        from sqlalchemy import inspect

        engine = in_memory_db.engine
        inspector = inspect(engine)

        # user_tasks 表存在
        assert "user_tasks" in inspector.get_table_names()
        # sessions 上有用户任务归属列（owner_user_task_id）
        session_cols = {c["name"] for c in inspector.get_columns("sessions")}
        assert "owner_user_task_id" in session_cols
        # user_tasks 有正确的列
        task_cols = {c["name"] for c in inspector.get_columns("user_tasks")}
        assert {"task_id", "session_id", "title", "status", "created_at"} <= task_cols

    def test_schema_version_is_latest(self, in_memory_db):
        from sqlalchemy import text

        with in_memory_db.engine.connect() as conn:
            version = conn.execute(text("SELECT version FROM schema_version")).scalar()
        assert version >= 42


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
