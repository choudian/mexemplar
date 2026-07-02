"""Tests for the parent-side reentry briefing pure function."""

from __future__ import annotations

from src.business.task_collaboration.reentry_briefing import (
    build_reentry_briefing,
    filter_pending_entries,
)


def test_empty_entries_returns_no_new_results_message() -> None:
    assert build_reentry_briefing([]) == "你之前派发的子任务暂无新结果。"


def test_single_entry_without_adjudication_lists_task_status_summary() -> None:
    text = build_reentry_briefing(
        [{"taskId": "tsk_1", "deliveredStatus": "done", "safeSummary": "报告已生成"}]
    )
    assert "认可/打回/放弃" in text
    assert "- 任务 tsk_1：done — 报告已生成" in text
    assert "decide_task_adjudication" not in text


def test_entry_with_adjudication_id_appends_decision_hint() -> None:
    text = build_reentry_briefing(
        [
            {
                "taskId": "tsk_2",
                "deliveredStatus": "stuck",
                "safeSummary": "需要重试",
                "adjudicationId": "adj_9",
            }
        ]
    )
    assert "- 任务 tsk_2：stuck — 需要重试" in text
    assert "裁定ID adj_9：可调用 decide_task_adjudication 工具决策。" in text


def test_result_entry_with_deliverable_renders_final_output_without_repeating_summary() -> None:
    deliverable = "| 项目 | 说明 |\n| repo/demo | 已整理完成 |"
    text = build_reentry_briefing(
        [
            {
                "taskId": "tsk_2",
                "deliveredStatus": "done",
                "safeSummary": "这只是短摘要",
                "adjudicationId": "adj_9",
                "deliverablePreview": deliverable,
                "deliverableTruncated": False,
                "resultReferenceId": "adj_9",
            }
        ]
    )

    assert "- 任务 tsk_2：done" in text
    assert "这只是短摘要" not in text
    assert "【子任务最终交付物】" in text
    assert "| repo/demo | 已整理完成 |" in text
    assert "不要重新抓取或重做同一子任务" in text


def test_result_entry_with_truncated_deliverable_points_to_load_task_result() -> None:
    text = build_reentry_briefing(
        [
            {
                "taskId": "tsk_2",
                "deliveredStatus": "done",
                "adjudicationId": "adj_9",
                "deliverablePreview": "partial",
                "deliverableTruncated": True,
                "resultReferenceId": "adj_9",
            }
        ]
    )

    assert 'load_task_result(adjudication_id="adj_9")' in text
    assert "load_reference" not in text


def test_result_entry_without_deliverable_warns_not_to_load_task_id_as_reference() -> None:
    text = build_reentry_briefing(
        [
            {
                "taskId": "tsk_2",
                "deliveredStatus": "done",
                "safeSummary": "需要下钻",
                "adjudicationId": "adj_9",
            }
        ]
    )

    assert "- 任务 tsk_2：done — 需要下钻" in text
    assert 'load_task_result(adjudication_id="adj_9")' in text
    assert "不要把 taskId 传给 load_reference" in text


def test_multiple_entries_are_each_listed_once() -> None:
    text = build_reentry_briefing(
        [
            {"taskId": "tsk_a", "deliveredStatus": "done", "safeSummary": "a done"},
            {"taskId": "tsk_b", "deliveredStatus": "stuck", "safeSummary": ""},
        ]
    )
    assert "- 任务 tsk_a：done — a done" in text
    assert "- 任务 tsk_b：stuck" in text
    assert text.count("认可/打回/放弃") == 1


def test_question_reentry_points_parent_to_answer_tool() -> None:
    text = build_reentry_briefing(
        [
            {
                "eventType": "task_question",
                "taskId": "tsk_q",
                "questionId": "qst_1",
                "questionKind": "capability_request",
                "safeSummary": "Need write access.",
            }
        ]
    )

    assert "正在等待你答复" in text
    assert "- 任务 tsk_q 提问 qst_1（capability_request）：Need write access." in text
    assert "answer_task_question" in text


def test_missing_safe_summary_is_treated_as_empty() -> None:
    text = build_reentry_briefing([{"taskId": "tsk_3", "deliveredStatus": "done"}])
    assert "- 任务 tsk_3：done" in text


def test_filter_pending_entries_drops_decided_adjudications() -> None:
    entries = [
        {"taskId": "tsk_a", "adjudicationId": "adj_pending"},
        {"taskId": "tsk_b", "adjudicationId": "adj_decided"},
    ]
    kept = filter_pending_entries(entries, {"adj_pending"})
    assert [e["taskId"] for e in kept] == ["tsk_a"]


def test_filter_pending_entries_keeps_all_when_all_pending() -> None:
    entries = [
        {"taskId": "tsk_a", "adjudicationId": "adj_1"},
        {"taskId": "tsk_b", "adjudicationId": "adj_2"},
    ]
    kept = filter_pending_entries(entries, {"adj_1", "adj_2"})
    assert kept == entries


def test_filter_pending_entries_drops_all_when_none_pending() -> None:
    entries = [{"taskId": "tsk_a", "adjudicationId": "adj_1"}]
    assert filter_pending_entries(entries, set()) == []


def test_filter_pending_entries_keeps_entries_without_adjudication_id() -> None:
    # 防御性：无 adjudicationId 的条目（理论上不应出现）不被误删。
    entries = [
        {"taskId": "tsk_none"},
        {"taskId": "tsk_b", "adjudicationId": "adj_decided"},
    ]
    kept = filter_pending_entries(entries, set())
    assert [e["taskId"] for e in kept] == ["tsk_none"]


def test_filter_pending_entries_empty_entries_returns_empty() -> None:
    assert filter_pending_entries([], {"adj_1"}) == []


def test_result_entries_include_abandon_request_graph_hint() -> None:
    # 有结果回流时，提示主助理可在请求无法完成时调用 abandon_request_graph 放弃整图。
    text = build_reentry_briefing(
        [{"taskId": "tsk_1", "deliveredStatus": "stuck", "safeSummary": "卡住"}]
    )
    assert "abandon_request_graph" in text


def test_empty_entries_do_not_include_abandon_request_graph_hint() -> None:
    # 无结果回流时不提示放弃整图——只有看到失败结果后才该考虑放弃整个请求。
    assert "abandon_request_graph" not in build_reentry_briefing([])


def test_question_only_entries_do_not_include_abandon_request_graph_hint() -> None:
    # 仅提问回流（无结果回流）时不提示放弃整图。
    text = build_reentry_briefing(
        [
            {
                "eventType": "task_question",
                "taskId": "tsk_q",
                "questionId": "qst_1",
                "questionKind": "clarification",
                "safeSummary": "需要补充",
            }
        ]
    )
    assert "abandon_request_graph" not in text
