"""I18-4 / I18-5: build_reentry_briefing unit tests.

I18-4: needs_review entries rendering — "需确认" in text, decide_task_adjudication
       in text, taskId appears in output, combination of result + needs_review + question.
I18-5: snapshot rendering — graph progress with failed tasks, all_terminal but not
       all_completed, running/suspended tasks, healingActions format.

Pure function tests; no IO, no DB. Uses mock TaskGraphSnapshot dataclasses from models.
"""

from __future__ import annotations

from src.business.task_collaboration.models import (
    DeliveredStatus,
    TaskAdjudicationSnapshot,
    TaskEdgeSnapshot,
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

    def test_result_deliverable_can_fall_back_to_snapshot_adjudication(self):
        """Entry 只带 adjudicationId 时，可从 snapshot pending adjudication 恢复结果。"""
        entries = [
            {
                "eventType": "result",
                "taskId": "t-1",
                "deliveredStatus": "done",
                "safeSummary": "短摘要",
                "adjudicationId": "adj-1",
            }
        ]
        snapshot = _make_snapshot()
        snapshot = TaskGraphSnapshot(
            graph_id=snapshot.graph_id,
            session_id=snapshot.session_id,
            user_message_sequence=snapshot.user_message_sequence,
            version=snapshot.version,
            tasks=snapshot.tasks,
            edges=snapshot.edges,
            adjudications=[
                TaskAdjudicationSnapshot(
                    adjudication_id="adj-1",
                    task_id="t-1",
                    safe_summary="短摘要",
                    delivered_status=DeliveredStatus.DONE,
                    raw_result_ref="子任务整理后的最终结果",
                )
            ],
        )

        text = build_reentry_briefing(entries, snapshot=snapshot)

        assert "子任务整理后的最终结果" in text
        assert "短摘要" not in text


# === I18-5: snapshot rendering ===


class TestSnapshotGraphProgress:
    def test_abandoned_tasks_appear_in_progress(self):
        """Snapshot with abandoned tasks → '已放弃节点' in output.

        简报里刻意不写"失败"：这些节点是**有人拍板不做了**，写失败会引主助理去想
        重试，而重试正是这里不该发生的事。
        """
        snapshot = _make_snapshot(
            tasks=[
                _make_task("t1", status=TaskStatus.COMPLETED, title="OK task"),
                _make_task("t2", status=TaskStatus.ABANDONED, title="Bad task"),
            ]
        )
        text = build_reentry_briefing([], snapshot=snapshot)
        assert "已放弃节点" in text
        assert "失败节点" not in text

    def test_all_terminal_not_all_completed_shows_mixed_status(self):
        """All terminal but not all completed → shows '含放弃/取消' or '已全部终止'."""
        snapshot = _make_snapshot(
            tasks=[
                _make_task("t1", status=TaskStatus.COMPLETED, title="Done"),
                _make_task("t2", status=TaskStatus.ABANDONED, title="Abandoned"),
            ]
        )
        text = build_reentry_briefing([], snapshot=snapshot)
        assert "已全部终止" in text
        assert "含放弃/取消" in text

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

    def test_root_container_node_excluded_from_progress(self):
        """根容器节点（parent_task_id=None）不计入任务图进度段。

        回归 bug：回流 briefing 把永远 pending_dispatch 的根节点 "Assistant request"
        算进统计，输出 "completed=0, running=1, pending=1, 就绪可派节点：Assistant
        request"，误导主助理以为还有节点在跑、不敢把结果呈现给用户。
        生产布局：1 个 root（parent_task_id=None）+ N 个真实节点。
        """
        snapshot = _make_snapshot(
            tasks=[
                _make_task(
                    "root-1",
                    status=TaskStatus.PENDING_DISPATCH,
                    title="Assistant request",
                    parent_task_id=None,
                ),
                _make_task(
                    "t-real",
                    status=TaskStatus.RUNNING,
                    title="获取 GitHub Trending",
                ),
            ]
        )
        text = build_reentry_briefing([], snapshot=snapshot)

        assert "任务图进度" in text
        # 真实节点计数：只算 t-real，root 不算
        assert "共 1 节点" in text
        assert "running=1" in text
        assert "pending=0" in text
        # root 标题不得进入"就绪可派节点"清单
        assert "Assistant request" not in text

    def test_root_excluded_and_all_real_completed_reports_to_user(self):
        """根节点排除后，所有真实节点 completed 时应提示向用户汇报最终结果。"""
        snapshot = _make_snapshot(
            tasks=[
                _make_task(
                    "root-1",
                    status=TaskStatus.PENDING_DISPATCH,
                    title="Assistant request",
                    parent_task_id=None,
                ),
                _make_task(
                    "t-real",
                    status=TaskStatus.COMPLETED,
                    title="获取 GitHub Trending",
                ),
            ]
        )
        text = build_reentry_briefing([], snapshot=snapshot)

        assert "共 1 节点" in text
        assert "completed=1" in text
        # 全图完成（root 未计入）应触发汇报提示
        assert "已全部完成" in text
        assert "向用户汇报最终结果" in text


def _paused_entry(**overrides) -> dict:
    entry = {
        "accepted": True,
        "taskId": "tsk_paused",
        "taskStatus": "suspended",
        "suspendReason": "budget_exhausted",
        "waitingOn": "assistant",
        "safeSummary": "已达迭代上限（30 轮）",
        "eventType": "budget_exhausted",
        "subagentId": "ast_child",
        "iterationsUsed": 30,
        "maxIterations": 30,
    }
    entry.update(overrides)
    return entry


class TestPausedEntriesAreNotRenderedAsDeliveries:
    """暂停的活什么都没交，不能摆「认可/打回/放弃」给主助理。

    在此之前，撞轮次预算暂停的回流会掉进普通结果段，主助理看到的是
    「- 任务 X：result」——`result` 是兜底值，零信息量；引导却是去认可/打回/放弃，
    甚至提示它可以放弃整张任务图。而这个活正确的处置是追加预算续跑。
    """

    def test_paused_entry_goes_to_its_own_section(self):
        text = build_reentry_briefing([_paused_entry()])

        assert "停下来了" in text
        assert "认可/打回/放弃" not in text
        assert "abandon_request_graph" not in text
        # `result` 那个兜底值不该再出现
        assert "：result" not in text

    def test_paused_entry_states_the_reason_in_plain_words(self):
        text = build_reentry_briefing([_paused_entry()])

        assert "撞到轮次上限" in text
        assert "工作已完整保留" in text
        assert "已用 30 / 上限 30 轮" in text

    def test_paused_entry_carries_the_executor_id_so_it_can_be_resumed(self):
        """主助理要续跑得知道续哪个执行体——没有这个 id，它知道该做什么也做不了。"""
        text = build_reentry_briefing([_paused_entry()])

        assert "ast_child" in text
        assert "continue_subagent" in text

    def test_delivery_and_pause_render_as_two_separate_sections(self):
        delivered = {
            "taskId": "tsk_done",
            "deliveredStatus": "done",
            "safeSummary": "组件已实现",
            "adjudicationId": "adj_1",
        }
        text = build_reentry_briefing([delivered, _paused_entry()])

        assert "认可/打回/放弃" in text  # 交付段还在
        assert "decide_task_adjudication" in text
        assert "停下来了" in text  # 暂停段也在
        assert "continue_subagent" in text
        # 两段各自独立，交付段的裁定引导不该落到暂停的活上
        assert text.index("认可/打回/放弃") < text.index("停下来了")

    def test_interrupted_pause_tells_the_assistant_to_verify_first(self):
        text = build_reentry_briefing(
            [_paused_entry(suspendReason="interrupted", eventType="interrupted")]
        )

        assert "上次异常中断" in text
        assert "核对" in text

    def test_unknown_pause_reason_still_offers_a_way_forward(self):
        """认不出的停法也要给出路，不能只丢一句状态。"""
        text = build_reentry_briefing(
            [_paused_entry(suspendReason="something_new", eventType="something_new")]
        )

        assert "停下来了" in text
        assert "continue_subagent" in text
