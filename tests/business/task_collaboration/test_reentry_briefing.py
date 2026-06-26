"""I18-4 / I18-5: build_reentry_briefing unit tests.

I18-4: needs_review entries rendering — "需确认" in text, decide_task_adjudication
       in text, taskId appears in output, combination of result + needs_review + question.
I18-5: snapshot rendering — graph progress with failed tasks, all_terminal but not
       all_completed, running/suspended tasks, healingActions format.

Pure function tests; no IO, no DB. Uses mock TaskGraphSnapshot dataclasses from models.
"""

from __future__ import annotations

from src.business.task_collaboration.models import (
    TaskEdgeSnapshot,
    TaskEdgeType,
    TaskGraphSnapshot,
    TaskSnapshot,
    TaskStatus,
)
from src.business.task_collaboration.reentry_briefing import build_reentry_briefing


def _make_task(
    task_id: str = "t1",
    *,
    status: TaskStatus = TaskStatus.COMPLETED,
    requires_review: bool = False,
    requires_confirmation: bool = False,
    title: str = "Test task",
    parent_task_id: str | None = "root",
) -> TaskSnapshot:
    return TaskSnapshot(
        task_id=task_id,
        graph_id="g1",
        parent_task_id=parent_task_id,
        title=title,
        description_preview="",
        status=status,
        display_phase="running",
        requires_review=requires_review,
        requires_confirmation=requires_confirmation,
    )


def _make_snapshot(
    *,
    tasks: list[TaskSnapshot] | None = None,
    edges: list[TaskEdgeSnapshot] | None = None,
) -> TaskGraphSnapshot:
    return TaskGraphSnapshot(
        graph_id="g1",
        session_id="s1",
        user_message_sequence=1,
        version=1,
        tasks=tasks or [],
        edges=edges or [],
    )


# === I18-4: needs_review entries ===


class TestNeedsReviewEntries:
    def test_needs_review_shows_confirmation_text(self):
        """needs_review entry produces '需确认' in the briefing text."""
        entries = [
            {
                "eventType": "needs_review",
                "taskId": "t-1",
                "safeSummary": "高风险操作需确认",
            }
        ]
        text = build_reentry_briefing(entries)
        assert "需确认" in text

    def test_needs_review_shows_decide_task_adjudication(self):
        """needs_review entry mentions decide_task_adjudication tool."""
        entries = [
            {
                "eventType": "needs_review",
                "taskId": "t-1",
                "safeSummary": "请裁定",
            }
        ]
        text = build_reentry_briefing(entries)
        assert "decide_task_adjudication" in text

    def test_needs_review_contains_task_id(self):
        """needs_review entry includes the taskId in output."""
        entries = [
            {
                "eventType": "needs_review",
                "taskId": "t-special-42",
                "safeSummary": "请裁定",
            }
        ]
        text = build_reentry_briefing(entries)
        assert "t-special-42" in text

    def test_combination_result_needs_review_question(self):
        """Result entry + needs_review entry + question entry all appear in combined output."""
        entries = [
            {
                "eventType": "result",
                "taskId": "t-1",
                "deliveredStatus": "done",
                "safeSummary": "结果正常",
                "adjudicationId": "adj-1",
            },
            {
                "eventType": "needs_review",
                "taskId": "t-2",
                "safeSummary": "需确认操作",
            },
            {
                "eventType": "task_question",
                "taskId": "t-3",
                "questionId": "q-1",
                "questionKind": "clarification",
                "safeSummary": "需要补充信息",
            },
        ]
        text = build_reentry_briefing(entries)
        assert "t-1" in text
        assert "t-2" in text
        assert "t-3" in text
        assert "需确认" in text


# === I18-5: snapshot rendering ===


class TestSnapshotGraphProgress:
    def test_failed_tasks_appear_in_progress(self):
        """Snapshot with failed tasks → '失败节点' in output."""
        snapshot = _make_snapshot(
            tasks=[
                _make_task("t1", status=TaskStatus.COMPLETED, title="OK task"),
                _make_task("t2", status=TaskStatus.FAILED, title="Bad task"),
            ]
        )
        text = build_reentry_briefing([], snapshot=snapshot)
        assert "失败节点" in text

    def test_all_terminal_not_all_completed_shows_mixed_status(self):
        """All terminal but not all completed → shows '含失败/取消' or '已全部终止'."""
        snapshot = _make_snapshot(
            tasks=[
                _make_task("t1", status=TaskStatus.COMPLETED, title="Done"),
                _make_task("t2", status=TaskStatus.FAILED, title="Failed"),
            ]
        )
        text = build_reentry_briefing([], snapshot=snapshot)
        assert "已全部终止" in text
        assert "含失败/取消" in text

    def test_running_suspended_tasks_show_active_section(self):
        """Snapshot with running/suspended tasks → '进行中节点' section."""
        snapshot = _make_snapshot(
            tasks=[
                _make_task("t1", status=TaskStatus.RUNNING, title="Working"),
                _make_task("t2", status=TaskStatus.SUSPENDED, title="Paused"),
            ]
        )
        text = build_reentry_briefing([], snapshot=snapshot)
        assert "进行中节点" in text

    def test_healing_actions_rendering_format(self):
        """Entry with healingActions renders the self-healing options format."""
        entries = [
            {
                "eventType": "result",
                "taskId": "t-fail",
                "deliveredStatus": "stuck",
                "safeSummary": "执行失败",
                "healingActions": ["retry", "skip", "abandon"],
            }
        ]
        text = build_reentry_briefing(entries)
        assert "失败自愈选项" in text
        assert "t-fail" in text
        # Check that some action hints are rendered
        assert "重试" in text or "retry" in text
