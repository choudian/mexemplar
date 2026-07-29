"""US5 集成测试：中途可见进度、能取消/改主意。

取消顺图传播、改主意走 cancel+重分解。
"""

import pytest

from src.business.task_collaboration.service import TaskCollaborationService
from src.data.repos.base_repository import generate_id


class TestCancelPropagation:
    """US5: 取消传播。"""

    def test_cancel_graph_stops_all_nodes(self, monkeypatch):
        """取消图：所有节点变为 cancelled。"""
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
                    {"nodeId": "n1", "title": "A", "description": "先做"},
                    {"nodeId": "n2", "title": "B", "description": "后做"},
                ],
                dependencies=[{"from": "n1", "to": "n2"}],
            )
            graph_id = result["graphId"]

            # 取消整张图
            svc.cancel_graph(
                graph_id=graph_id,
                session_id=session_id,
            )

            snapshot = svc.get_graph_snapshot(session_id=session_id, graph_id=graph_id)
            for task in snapshot.tasks:
                assert task.status in ("cancelled", "failed")
            assert signals == [(f"assistant_task_graph:{graph_id}", CancelReason.USER_CANCEL)]

    def test_redirect_cancel_and_redecompose(self):
        """改主意：取消旧图 + 重新分解。"""
        session_id = generate_id("sess")
        with TaskCollaborationService() as svc:
            # 旧图
            result1 = svc.build_task_graph(
                session_id=session_id,
                nodes=[
                    {"nodeId": "n1", "title": "旧任务1", "description": "旧"},
                    {"nodeId": "n2", "title": "旧任务2", "description": "旧"},
                ],
            )
            old_graph_id = result1["graphId"]

            # 取消旧图
            svc.cancel_graph(graph_id=old_graph_id, session_id=session_id)

            # 新图
            result2 = svc.build_task_graph(
                session_id=session_id,
                nodes=[
                    {"nodeId": "n1", "title": "新任务1", "description": "新"},
                ],
            )
            assert result2["graphId"] != old_graph_id

    def test_cancel_graph_accepts_matching_expected_version(self):
        """FR-011: expected_graph_version 匹配当前版本时 cancel 成功。"""
        session_id = generate_id("sess")
        with TaskCollaborationService() as svc:
            result = svc.build_task_graph(
                session_id=session_id,
                nodes=[{"nodeId": "n1", "title": "A", "description": "x"}],
            )
            graph_id = result["graphId"]
            snapshot = svc.get_graph_snapshot(session_id=session_id, graph_id=graph_id)
            assert snapshot is not None

            affected = svc.cancel_graph(
                graph_id=graph_id,
                session_id=session_id,
                expected_graph_version=snapshot.version,
            )
            assert affected >= 1

    def test_cancel_graph_rejects_mismatched_expected_version(self):
        """FR-011: expected_graph_version 不匹配（并发 replan 改了图版本）→ cancel 被拒。"""
        session_id = generate_id("sess")
        with TaskCollaborationService() as svc:
            result = svc.build_task_graph(
                session_id=session_id,
                nodes=[{"nodeId": "n1", "title": "A", "description": "x"}],
            )
            graph_id = result["graphId"]

            with pytest.raises(ValueError, match="graph version"):
                svc.cancel_graph(
                    graph_id=graph_id,
                    session_id=session_id,
                    expected_graph_version=999999,
                )

    def test_briefing_with_snapshot_shows_progress(self):
        """回流 briefing 含任务图进度段。"""
        from src.business.task_collaboration.reentry_briefing import build_reentry_briefing
        from src.business.task_collaboration.models import (
            TaskGraphSnapshot,
            TaskSnapshot,
            TaskEdgeSnapshot,
        )

        snapshot = TaskGraphSnapshot(
            graph_id="graph-001",
            session_id="sess-001",
            user_message_sequence=1,
            version=1,
            tasks=[
                TaskSnapshot(
                    task_id="tsk-root",
                    graph_id="graph-001",
                    parent_task_id=None,
                    title="Assistant request",
                    description_preview="整个请求",
                    status="pending_dispatch",
                    display_phase="running",
                    requires_review=False,
                ),
                TaskSnapshot(
                    task_id="tsk-001",
                    graph_id="graph-001",
                    parent_task_id="tsk-root",
                    title="步骤A",
                    description_preview="先做",
                    status="completed",
                    display_phase="done",
                    requires_review=False,
                ),
                TaskSnapshot(
                    task_id="tsk-002",
                    graph_id="graph-001",
                    parent_task_id="tsk-root",
                    title="步骤B",
                    description_preview="后做",
                    status="pending_dispatch",
                    display_phase="running",
                    requires_review=False,
                ),
            ],
            edges=[
                TaskEdgeSnapshot(
                    source_task_id="tsk-001",
                    target_task_id="tsk-002",
                    type="dependency",
                ),
            ],
            adjudications=[],
        )

        entries = [
            {
                "taskId": "tsk-001",
                "deliveredStatus": "done",
                "safeSummary": "步骤A已完成",
                "adjudicationId": "adj-001",
            },
        ]
        briefing = build_reentry_briefing(entries, snapshot=snapshot)
        assert "任务图进度" in briefing
        # 根节点 tsk-root 不计入；真实节点 tsk-001(completed) + tsk-002(pending)
        assert "共 2 节点" in briefing
        assert "completed=1" in briefing
