from __future__ import annotations

import pytest
from PyQt6.QtWidgets import QLabel, QPushButton

from src.data.repositories import ToolRepository
from src.ui.page_ids import CONVERSATIONS, INTENT_CONFIRMATION, SKILLS, TEACHING
from tests.e2e.support import (
    pm_submit_requirements,
    programmer_submit_code,
    review_passed,
    text_reply,
    trial_submit_result,
)

pytestmark = pytest.mark.e2e


def _labels_contain(widget, text: str) -> bool:
    return any(text in label.text() for label in widget.findChildren(QLabel))


def _toast_contains(main_window, text: str) -> bool:
    toast = getattr(main_window, "_active_toast", None)
    if toast is None:
        return False
    label = toast.findChild(QLabel, "notification_toast_text")
    return label is not None and text in label.text()


def _find_pending_card(skills_page, tool_name: str):
    for card in skills_page.pending_tool_cards:
        if card.pending_tool.tool_name == tool_name:
            return card
    return None


def test_teaching_full_happy_path(
    main_window,
    robot,
    mock_llm,
    event_log,
    simulate_recording_completion,
):
    workflow_id = "wf-teaching-happy"
    mock_llm.push(
        text_reply("你希望这个技能自动完成什么操作？"),
        pm_submit_requirements(workflow_id),
        programmer_submit_code(),
        review_passed(),
        text_reply("请进行第一次考核并告诉我结果。"),
        trial_submit_result(True, "第一次成功"),
        text_reply("请进行第二次考核并告诉我结果。"),
        trial_submit_result(True, "第二次成功"),
        text_reply("请进行第三次考核并告诉我结果。"),
        trial_submit_result(True, "第三次成功"),
    )

    assert main_window.isVisible()
    assert robot.ui.find_widget(QPushButton, "技能教学") is not None
    assert robot.ui.find_widget(QPushButton, "会话列表") is not None
    assert robot.ui.find_widget(QPushButton, "技能列表") is not None
    assert robot.ui.find_widget(QPushButton, "设置") is not None

    robot.ui.click_sidebar_page(TEACHING)
    recording_page = main_window.recording_page
    assert recording_page.isVisible()
    assert recording_page.browser_card.isVisible()
    assert recording_page.desktop_card.isVisible()
    assert recording_page.extension_card.isVisible()

    simulate_recording_completion(workflow_id=workflow_id)

    intent_page = main_window.intent_confirmation_page
    assert robot.wait.wait_until(
        lambda: main_window.main_content.get_current_page() == INTENT_CONFIRMATION,
        timeout_ms=5_000,
    )
    assert robot.wait.wait_until(
        lambda: _labels_contain(intent_page, "你希望这个技能自动完成什么操作？"),
        timeout_ms=10_000,
    )

    robot.ui.fill(intent_page.message_input, "我要自动填写搜索表单并提交")
    robot.ui.click_button("发送")

    assert robot.wait.wait_until(
        lambda: len(event_log["tool_saved"]) >= 1,
        timeout_ms=20_000,
    )
    assert robot.wait.wait_until(
        lambda: _toast_contains(main_window, "技能学习完毕"),
        timeout_ms=10_000,
    )

    tool = ToolRepository().get_by_workflow_id(workflow_id)
    assert tool is not None
    assert tool.status == "pending"
    assert len(event_log["requirement_confirmed"]) == 1
    assert len(event_log["code_completed"]) == 1
    assert len(event_log["review_passed"]) == 1
    assert len(event_log["review_failed"]) == 0

    for round_index, prompt in enumerate(
        [
            "请进行第一次考核并告诉我结果。",
            "请进行第二次考核并告诉我结果。",
            "请进行第三次考核并告诉我结果。",
        ],
        start=1,
    ):
        robot.ui.click_sidebar_page(SKILLS)
        assert robot.wait.wait_until(
            lambda: _labels_contain(main_window.pending_tools_page, tool.tool_name),
            timeout_ms=5_000,
        )
        main_window._on_trial_start_request(tool.tool_id)

        assert robot.wait.wait_until(
            lambda: main_window.main_content.get_current_page() == INTENT_CONFIRMATION,
            timeout_ms=5_000,
        )
        assert robot.wait.wait_until(
            lambda prompt_text=prompt: _labels_contain(intent_page, prompt_text),
            timeout_ms=10_000,
        )

        robot.ui.fill(intent_page.message_input, f"第 {round_index} 次执行成功，结果正确")
        robot.ui.click_button("发送")

        assert robot.wait.wait_until(
            lambda expected=round_index: len(event_log["trial_success"]) >= expected,
            timeout_ms=15_000,
        )
        tool = ToolRepository().get_by_workflow_id(workflow_id)
        assert tool is not None
        assert tool.trial_success_count == round_index

    assert robot.wait.wait_until(
        lambda: len(event_log["tool_published"]) >= 1,
        timeout_ms=15_000,
    )
    tool = ToolRepository().get_by_workflow_id(workflow_id)
    assert tool is not None
    assert tool.status == "published"

    robot.ui.click_sidebar_page(SKILLS)
    robot.ui.click_button_prefix("已掌握")
    assert robot.wait.wait_until(
        lambda: _labels_contain(main_window.pending_tools_page, tool.tool_name),
        timeout_ms=5_000,
    )


def test_teaching_user_abort(main_window, robot, mock_llm, simulate_recording_completion):
    workflow_id = "wf-teaching-abort"
    mock_llm.push(text_reply("你希望这个技能自动完成什么操作？"))

    robot.ui.click_sidebar_page(TEACHING)
    simulate_recording_completion(workflow_id=workflow_id)

    intent_page = main_window.intent_confirmation_page
    assert robot.wait.wait_until(
        lambda: _labels_contain(intent_page, "你希望这个技能自动完成什么操作？"),
        timeout_ms=10_000,
    )

    robot.ui.click_button("取消")

    assert robot.wait.wait_until(
        lambda: main_window.main_content.get_current_page() == CONVERSATIONS,
        timeout_ms=5_000,
    )
    assert ToolRepository().get_by_workflow_id(workflow_id) is None
    assert main_window._current_agent_workflow_id is None
    assert main_window._current_agent_type is None
