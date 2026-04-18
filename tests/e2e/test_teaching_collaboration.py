from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QLabel

from src.data.repositories import ToolRepository, WorkflowTransitionRepository
from src.ui.page_ids import INTENT_CONFIRMATION, SKILLS
from tests.e2e.support import (
    SAMPLE_CODE_V2,
    pm_report_code_issue,
    pm_submit_requirements,
    programmer_submit_code,
    review_failed,
    review_passed,
    text_reply,
    trial_submit_result,
)

pytestmark = pytest.mark.e2e


def _labels_contain(widget, text: str) -> bool:
    return any(label.isVisible() and text in label.text() for label in widget.findChildren(QLabel))


def _find_pending_card(skills_page, tool_name: str):
    for card in skills_page.pending_tool_cards:
        if card.pending_tool.tool_name == tool_name:
            return card
    return None


def test_requirement_confirmation(
    main_window,
    robot,
    mock_llm,
    event_log,
    simulate_recording_completion,
):
    workflow_id = "wf-req-confirm"
    mock_llm.push(
        text_reply("你希望这个技能做什么？"),
        text_reply("这个技能需要哪些输入参数？"),
        pm_submit_requirements(workflow_id),
        programmer_submit_code(),
        review_passed(),
    )

    simulate_recording_completion(workflow_id=workflow_id)
    intent_page = main_window.intent_confirmation_page

    assert robot.wait.wait_until(
        lambda: _labels_contain(intent_page, "你希望这个技能做什么？"),
        timeout_ms=10_000,
    )
    robot.ui.fill(intent_page.message_input, "我要自动填写搜索表单并提交")
    robot.ui.click_button("发送")

    assert robot.wait.wait_until(
        lambda: _labels_contain(intent_page, "这个技能需要哪些输入参数？"),
        timeout_ms=10_000,
    )
    robot.ui.fill(intent_page.message_input, "输入参数是搜索关键词")
    robot.ui.click_button("发送")

    assert robot.wait.wait_until(
        lambda: len(event_log["requirement_confirmed"]) >= 1,
        timeout_ms=15_000,
    )
    assert robot.wait.wait_until(
        lambda: len(event_log["tool_saved"]) >= 1,
        timeout_ms=15_000,
    )

    payload = event_log["requirement_confirmed"][0]["requirements_json"]
    assert payload["recording_id"] == workflow_id
    assert payload["parameters"][0]["name"] == "keyword"
    assert not event_log["agent_error"]


def test_code_generation_and_review(
    main_window,
    robot,
    mock_llm,
    event_log,
    simulate_recording_completion,
):
    workflow_id = "wf-code-review"
    mock_llm.push(
        pm_submit_requirements(workflow_id),
        programmer_submit_code(),
        review_passed(),
    )

    simulate_recording_completion(workflow_id=workflow_id)

    assert robot.wait.wait_until(
        lambda: len(event_log["tool_saved"]) >= 1,
        timeout_ms=15_000,
    )

    tool = ToolRepository().get_by_workflow_id(workflow_id)
    assert tool is not None
    assert tool.status == "pending"
    assert len(event_log["code_completed"]) == 1
    assert len(event_log["review_passed"]) == 1
    assert len(event_log["review_failed"]) == 0


def test_review_failure_auto_retry(
    main_window,
    robot,
    mock_llm,
    event_log,
    simulate_recording_completion,
):
    workflow_id = "wf-review-retry"
    mock_llm.push(
        pm_submit_requirements(workflow_id),
        programmer_submit_code(tc_id="tc-prog-1"),
        review_failed("函数签名错误"),
        programmer_submit_code(tc_id="tc-prog-2"),
        review_passed(),
    )

    simulate_recording_completion(workflow_id=workflow_id)

    assert robot.wait.wait_until(
        lambda: len(event_log["tool_saved"]) >= 1,
        timeout_ms=20_000,
    )

    review_failed_event = event_log["review_failed"][0]
    assert review_failed_event["retry_count"] == 1
    assert review_failed_event["forced_save"] is False

    transitions = WorkflowTransitionRepository().get_by_workflow(workflow_id)
    assert len([item for item in transitions if item.event_type == "code_completed"]) == 2
    assert len([item for item in transitions if item.event_type == "review_failed"]) == 1
    assert len([item for item in transitions if item.event_type == "review_passed"]) == 1
    assert not event_log["agent_error"]


def test_trial_success_and_auto_publish(
    main_window,
    robot,
    mock_llm,
    event_log,
    pending_tool_factory,
):
    workflow_id = "wf-trial-publish"
    pending_tool = pending_tool_factory(
        tool_name="考核自动发布技能",
        description="三次成功后自动发布",
        workflow_id=workflow_id,
    )
    mock_llm.push(
        text_reply("请完成第 1 次考核并反馈结果。"),
        trial_submit_result(True, "第 1 次成功"),
        text_reply("请完成第 2 次考核并反馈结果。"),
        trial_submit_result(True, "第 2 次成功"),
        text_reply("请完成第 3 次考核并反馈结果。"),
        trial_submit_result(True, "第 3 次成功"),
    )
    assert main_window._ensure_agent_bridge(timeout=10.0)

    robot.ui.click_sidebar_page(SKILLS)
    assert robot.wait.wait_until(
        lambda: _labels_contain(main_window.pending_tools_page, pending_tool.tool_name),
        timeout_ms=5_000,
    )

    for round_index in range(1, 4):
        main_window._on_trial_start_request(pending_tool.tool_id)
        assert robot.wait.wait_until(
            lambda: main_window.main_content.get_current_page() == INTENT_CONFIRMATION,
            timeout_ms=5_000,
        )
        assert robot.wait.wait_until(
            lambda expected=round_index: _labels_contain(
                main_window.intent_confirmation_page,
                f"请完成第 {expected} 次考核并反馈结果。",
            ),
            timeout_ms=10_000,
        )
        robot.ui.fill(
            main_window.intent_confirmation_page.message_input,
            f"第 {round_index} 次结果正确",
        )
        robot.ui.click_button("发送")
        assert robot.wait.wait_until(
            lambda expected=round_index: len(event_log["trial_success"]) >= expected,
            timeout_ms=10_000,
        )
        tool = ToolRepository().get_by_workflow_id(workflow_id)
        assert tool is not None
        assert tool.trial_success_count == round_index

        if round_index < 3:
            robot.ui.click_sidebar_page(SKILLS)

    assert robot.wait.wait_until(
        lambda: len(event_log["tool_published"]) >= 1,
        timeout_ms=15_000,
    )
    tool = ToolRepository().get_by_workflow_id(workflow_id)
    assert tool is not None
    assert tool.status == "published"


def test_trial_failure_triage_and_retry(
    main_window,
    robot,
    mock_llm,
    event_log,
    pending_tool_factory,
):
    workflow_id = "wf-trial-fail-retry"
    pending_tool_factory(
        tool_name="失败后修复技能",
        description="试用失败后会触发修复",
        workflow_id=workflow_id,
    )
    mock_llm.push(
        text_reply("请试用这个技能并告诉我哪里出错了。"),
        trial_submit_result(False, "输出结果不对"),
        pm_report_code_issue("输出结果不对，代码逻辑有误"),
        programmer_submit_code(SAMPLE_CODE_V2, tc_id="tc-prog-fix"),
        review_passed(),
        text_reply("工具已经修复，请再次验证。"),
    )
    assert main_window._ensure_agent_bridge(timeout=10.0)

    robot.ui.click_sidebar_page(SKILLS)
    main_window._on_trial_start_request(
        ToolRepository().get_by_workflow_id(workflow_id).tool_id
    )
    assert robot.wait.wait_until(
        lambda: _labels_contain(main_window.intent_confirmation_page, "请试用这个技能并告诉我哪里出错了。"),
        timeout_ms=10_000,
    )

    robot.ui.fill(main_window.intent_confirmation_page.message_input, "输出结果不对")
    robot.ui.click_button("发送")

    assert robot.wait.wait_until(
        lambda: len(event_log["tool_saved"]) >= 1,
        timeout_ms=20_000,
    )
    assert len(event_log["trial_failed"]) == 1
    assert len(event_log["triage_completed"]) == 1
    assert event_log["trial_failed"][0]["user_feedback"] == "输出结果不对"
    assert event_log["triage_completed"][0]["triage_result"] == "code_issue"

    tool = ToolRepository().get_by_workflow_id(workflow_id)
    assert tool is not None
    assert tool.execution_code == SAMPLE_CODE_V2
    assert tool.trial_success_count == 0
    assert robot.wait.wait_until(
        lambda: _labels_contain(main_window.intent_confirmation_page, "工具已经修复，请再次验证。"),
        timeout_ms=10_000,
    )
