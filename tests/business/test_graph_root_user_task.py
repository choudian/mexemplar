"""图根归属改造：让任务图挂在用户任务底下。

验证 assistant_tasks.user_task_id 列正确记录图根归属，以及从 user_task 查图根的新查询。
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.business.agents.config import AgentType
from src.business.agents.tools.assistant_tools import create_create_task_handler
from src.business.task_collaboration.service import TaskCollaborationService
from src.data.models_sqlite import Session as SessionModel
from src.data.repos import (
    AssistantTaskRepository,
    SessionRepository,
    UserTaskRepository,
)


def _seed_session(session_id: str) -> str:
    SessionRepository().create(
        SessionModel(
            session_id=session_id,
            workflow_id=None,
            agent_type=AgentType.ASSISTANT,
            status="active",
        )
    )
    return session_id


def _create_user_task(session_id: str, title: str = "测试任务") -> str:
    """通过 create_task 工具建用户任务，返回 task_id。"""
    handler = create_create_task_handler(session_id)
    result = json.loads(handler(title=title))
    return result["task"]["taskId"]


# ---------------------------------------------------------------------------
# 图根归属记录
# ---------------------------------------------------------------------------


class TestGraphRootUserTaskId:
    def test_build_task_graph_records_user_task_id(self, in_memory_db):
        """build_task_graph 建的图根 user_task_id == 聚焦任务 id。"""
        sid = _seed_session("ast_graph1")
        user_task_id = _create_user_task(sid, "季度报告")

        with TaskCollaborationService() as tcs:
            result = tcs.build_task_graph(
                session_id=sid,
                nodes=[{"nodeId": "n1", "title": "步骤一", "description": "d"}],
                user_task_id=user_task_id,
            )
        graph_id = result["graphId"]

        root = AssistantTaskRepository().get_graph_root(graph_id)
        assert root is not None
        assert root.user_task_id == user_task_id

    def test_build_task_graph_without_user_task_id_is_none(self, in_memory_db):
        """不传 user_task_id 时（如 proposal 场景），图根 user_task_id 为 None。"""
        sid = _seed_session("ast_graph2")

        with TaskCollaborationService() as tcs:
            result = tcs.build_task_graph(
                session_id=sid,
                nodes=[{"nodeId": "n1", "title": "步骤", "description": "d"}],
            )
        graph_id = result["graphId"]

        root = AssistantTaskRepository().get_graph_root(graph_id)
        assert root is not None
        assert root.user_task_id is None

    def test_create_root_graph_records_user_task_id(self, in_memory_db):
        """create_root_graph 直接调时也记录 user_task_id。"""
        sid = _seed_session("ast_graph3")
        user_task_id = "utsk_test_root_graph"

        with TaskCollaborationService() as tcs:
            graph_id = tcs.create_root_graph(
                session_id=sid,
                title="根",
                description="d",
                user_task_id=user_task_id,
            )

        root = AssistantTaskRepository().get_graph_root(graph_id)
        assert root is not None
        assert root.user_task_id == user_task_id

    def test_one_user_task_multiple_graphs(self, in_memory_db):
        """同一 user_task 下建多张图，各自 user_task_id 相同。"""
        sid = _seed_session("ast_graph4")
        user_task_id = _create_user_task(sid, "多图任务")

        with TaskCollaborationService() as tcs:
            r1 = tcs.build_task_graph(
                session_id=sid,
                nodes=[{"nodeId": "n1", "title": "图一", "description": "d"}],
                user_task_id=user_task_id,
            )
            r2 = tcs.build_task_graph(
                session_id=sid,
                nodes=[{"nodeId": "n2", "title": "图二", "description": "d"}],
                user_task_id=user_task_id,
            )

        root1 = AssistantTaskRepository().get_graph_root(r1["graphId"])
        root2 = AssistantTaskRepository().get_graph_root(r2["graphId"])
        assert root1.user_task_id == user_task_id
        assert root2.user_task_id == user_task_id
        assert root1.task_id != root2.task_id  # 不同图

    def test_child_nodes_dont_carry_user_task_id(self, in_memory_db):
        """子节点 user_task_id 为 None（只图根有）。"""
        sid = _seed_session("ast_graph5")
        user_task_id = _create_user_task(sid, "子节点测试")

        with TaskCollaborationService() as tcs:
            result = tcs.build_task_graph(
                session_id=sid,
                nodes=[{"nodeId": "n1", "title": "节点", "description": "d"}],
                user_task_id=user_task_id,
            )
        graph_id = result["graphId"]
        node_task_id = result["nodeTaskIds"]["n1"]

        node = AssistantTaskRepository().get_task(node_task_id)
        assert node is not None
        assert node.user_task_id is None  # 子节点不冗余


# ---------------------------------------------------------------------------
# 新查询：从 user_task 找图根
# ---------------------------------------------------------------------------


class TestListGraphRootsForUserTask:
    def test_returns_correct_roots(self, in_memory_db):
        """list_graph_roots_for_user_task 返回正确的图根列表。"""
        sid = _seed_session("ast_query1")
        user_task_id = _create_user_task(sid, "查询测试")

        with TaskCollaborationService() as tcs:
            tcs.build_task_graph(
                session_id=sid,
                nodes=[{"nodeId": "n1", "title": "图A", "description": "d"}],
                user_task_id=user_task_id,
            )
            tcs.build_task_graph(
                session_id=sid,
                nodes=[{"nodeId": "n2", "title": "图B", "description": "d"}],
                user_task_id=user_task_id,
            )

        roots = AssistantTaskRepository().list_graph_roots_for_user_task(user_task_id)
        assert len(roots) == 2
        assert all(r.user_task_id == user_task_id for r in roots)
        assert all(r.parent_task_id is None for r in roots)

    def test_empty_for_unknown_user_task(self, in_memory_db):
        """不存在的 user_task_id 返回空列表。"""
        roots = AssistantTaskRepository().list_graph_roots_for_user_task("utsk_nonexistent")
        assert roots == []


# ---------------------------------------------------------------------------
# resolve_user_task_id：子节点上溯图根取归属（#5 修复）
# ---------------------------------------------------------------------------


class TestResolveUserTaskId:
    def test_root_node_returns_own_user_task_id(self, in_memory_db):
        """图根节点直接返回自己的 user_task_id。"""
        sid = _seed_session("ast_resolve1")
        user_task_id = _create_user_task(sid, "归属测试")

        with TaskCollaborationService() as tcs:
            result = tcs.build_task_graph(
                session_id=sid,
                nodes=[{"nodeId": "n1", "title": "步骤", "description": "d"}],
                user_task_id=user_task_id,
            )
        graph_id = result["graphId"]
        root = AssistantTaskRepository().get_graph_root(graph_id)
        assert root is not None

        resolved = AssistantTaskRepository().resolve_user_task_id(root)
        assert resolved == user_task_id

    def test_child_node_traverses_to_root(self, in_memory_db):
        """子节点（user_task_id=None）沿 graph_id 上溯到图根取归属。"""
        sid = _seed_session("ast_resolve2")
        user_task_id = _create_user_task(sid, "子节点上溯")

        with TaskCollaborationService() as tcs:
            result = tcs.build_task_graph(
                session_id=sid,
                nodes=[
                    {"nodeId": "n1", "title": "父", "description": "d"},
                    {"nodeId": "n2", "title": "子", "description": "d"},
                ],
                dependencies=[{"from": "n1", "to": "n2"}],
                user_task_id=user_task_id,
            )
        child_task_id = result["nodeTaskIds"]["n2"]
        child = AssistantTaskRepository().get_task(child_task_id)
        assert child is not None
        assert child.user_task_id is None  # 子节点确实没写

        # 但 resolve 能上溯到图根拿到归属
        resolved = AssistantTaskRepository().resolve_user_task_id(child)
        assert resolved == user_task_id

    def test_no_user_task_returns_none(self, in_memory_db):
        """图根也没有 user_task_id 时（proposal 场景）返回 None。"""
        sid = _seed_session("ast_resolve3")

        with TaskCollaborationService() as tcs:
            result = tcs.build_task_graph(
                session_id=sid,
                nodes=[{"nodeId": "n1", "title": "无归属", "description": "d"}],
            )
        root = AssistantTaskRepository().get_graph_root(result["graphId"])
        assert root is not None

        resolved = AssistantTaskRepository().resolve_user_task_id(root)
        assert resolved is None


# ---------------------------------------------------------------------------
# _validate_user_task_id：委派入口 taskId 校验（#1 修复）
# ---------------------------------------------------------------------------


class TestValidateUserTaskId:
    def test_valid_active_task_passes(self, in_memory_db):
        """active 状态的用户任务通过校验。"""
        from src.business.agents.tools.assistant_tools import _validate_user_task_id

        sid = _seed_session("ast_val1")
        user_task_id = _create_user_task(sid, "有效任务")

        assert _validate_user_task_id(user_task_id) == user_task_id

    def test_empty_task_id_rejected(self, in_memory_db):
        """空 taskId 被拒。"""
        from src.business.agents.tools.assistant_tools import _validate_user_task_id

        with pytest.raises(ValueError, match="taskId 必填"):
            _validate_user_task_id("")

    def test_nonexistent_task_id_rejected(self, in_memory_db):
        """不存在的 taskId 被拒。"""
        from src.business.agents.tools.assistant_tools import _validate_user_task_id

        with pytest.raises(ValueError, match="用户任务不存在"):
            _validate_user_task_id("utsk_made_up")

    def test_done_task_rejected(self, in_memory_db):
        """已完成的任务不能在其底下委派。"""
        from src.business.agents.tools.assistant_tools import _validate_user_task_id

        sid = _seed_session("ast_val2")
        user_task_id = _create_user_task(sid, "已完成任务")
        UserTaskRepository().update_status(user_task_id, "done")

        with pytest.raises(ValueError, match="已done"):
            _validate_user_task_id(user_task_id)

    def test_dropped_task_rejected(self, in_memory_db):
        """已放弃的任务不能在其底下委派。"""
        from src.business.agents.tools.assistant_tools import _validate_user_task_id

        sid = _seed_session("ast_val3")
        user_task_id = _create_user_task(sid, "已放弃任务")
        UserTaskRepository().update_status(user_task_id, "dropped")

        with pytest.raises(ValueError, match="已dropped"):
            _validate_user_task_id(user_task_id)

    def test_cooling_task_passes(self, in_memory_db):
        """冷却中的任务仍可委派（用户可能重新激活它）。"""
        from src.business.agents.tools.assistant_tools import _validate_user_task_id

        sid = _seed_session("ast_val4")
        user_task_id = _create_user_task(sid, "冷却任务")
        UserTaskRepository().update_status(user_task_id, "cooling")

        assert _validate_user_task_id(user_task_id) == user_task_id


# ---------------------------------------------------------------------------
# 迁移
# ---------------------------------------------------------------------------


class TestMigrationV43:
    def test_migration_adds_column_and_index(self, in_memory_db):
        """迁移 v43 加了 user_task_id 列 + 索引。"""
        from sqlalchemy import inspect

        inspector = inspect(in_memory_db.engine)
        cols = {c["name"] for c in inspector.get_columns("assistant_tasks")}
        assert "user_task_id" in cols

        indexes = {idx["name"] for idx in inspector.get_indexes("assistant_tasks")}
        assert "idx_assistant_tasks_user_task" in indexes

    def test_schema_version_is_latest(self, in_memory_db):
        from sqlalchemy import text

        with in_memory_db.engine.connect() as conn:
            version = conn.execute(text("SELECT version FROM schema_version")).scalar()
        assert version >= 43
