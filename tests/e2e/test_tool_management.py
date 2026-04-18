from __future__ import annotations

from collections import deque

import pytest
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QDialogButtonBox, QLabel, QLineEdit, QPushButton, QTextEdit

from src.data.repositories import ToolRepository
from src.ui.page_ids import SKILLS

pytestmark = pytest.mark.e2e


def _labels_contain(widget, text: str) -> bool:
    return any(label.isVisible() and text in label.text() for label in widget.findChildren(QLabel))


def _find_pending_card(skills_page, tool_name: str):
    for card in skills_page.pending_tool_cards:
        if card.pending_tool.tool_name == tool_name:
            return card
    return None


def _find_published_card(skills_page, tool_name: str):
    for card in skills_page.published_tool_cards:
        if card.tool.tool_name == tool_name:
            return card
    return None


def _schedule_input_dialog_sequence(robot, responses: list[str], interval_ms: int = 100) -> None:
    queue = deque(responses)

    def step():
        if not queue:
            return
        dialog = QApplication.instance().activeModalWidget()
        if dialog is None:
            QTimer.singleShot(interval_ms, step)
            return

        input_widget = dialog.findChild(QLineEdit)
        button_box = dialog.findChild(QDialogButtonBox)
        if input_widget is None or button_box is None:
            QTimer.singleShot(interval_ms, step)
            return

        robot.ui.fill(input_widget, queue.popleft())
        robot.ui.click_dialog_button(QDialogButtonBox.StandardButton.Ok)
        if queue:
            QTimer.singleShot(interval_ms, step)

    QTimer.singleShot(interval_ms, step)


def _schedule_yes(robot, delay_ms: int = 100) -> None:
    def step(attempt: int = 0):
        try:
            robot.ui.click_dialog_button(QDialogButtonBox.StandardButton.Yes)
            return
        except AssertionError:
            if attempt < 20:
                QTimer.singleShot(delay_ms, lambda: step(attempt + 1))

    QTimer.singleShot(delay_ms, step)


def _schedule_menu_action(robot, action_text: str, delay_ms: int = 100) -> None:
    def step(attempt: int = 0):
        try:
            robot.ui.click_menu_action(action_text)
            return
        except AssertionError:
            if attempt < 20:
                QTimer.singleShot(delay_ms, lambda: step(attempt + 1))

    QTimer.singleShot(delay_ms, step)


def _schedule_execution_flow(captured: dict[str, str], interval_ms: int = 120) -> None:
    def step():
        dialog = QApplication.instance().activeModalWidget()
        if dialog is None:
            QTimer.singleShot(interval_ms, step)
            return

        title = dialog.windowTitle()
        if title.startswith("执行工具："):
            execute_btn = dialog.findChild(QPushButton, "tool_execution_execute_button")
            if execute_btn is not None:
                execute_btn.click()
                QTimer.singleShot(interval_ms, step)
                return

        if title.startswith("✅ 执行成功") or title.startswith("❌ 执行失败"):
            result_view = dialog.findChild(QTextEdit, "execution_result_text")
            error_view = dialog.findChild(QTextEdit, "execution_error_text")
            if result_view is not None:
                captured["text"] = result_view.toPlainText()
            if error_view is not None:
                captured["error"] = error_view.toPlainText()
            close_btn = dialog.findChild(QPushButton, "execution_result_close_button")
            if close_btn is not None:
                close_btn.click()
            return

        QTimer.singleShot(interval_ms, step)

    QTimer.singleShot(interval_ms, step)


def test_execute_parameterless_tool(main_window, robot, published_tool_factory):
    published_tool_factory(
        tool_name="无参执行技能",
        description="无参数执行测试",
        code=(
            "async def execute(**kwargs):\n"
            "    return {'success': True, 'message': 'ran', 'data': {'value': 42}}\n"
        ),
    )
    captured: dict[str, str] = {}
    _schedule_execution_flow(captured)

    robot.ui.click_sidebar_page(SKILLS)
    robot.ui.click_button_prefix("已掌握")
    assert robot.wait.wait_until(
        lambda: _find_published_card(main_window.pending_tools_page, "无参执行技能") is not None,
        timeout_ms=5_000,
    )

    robot.ui.click_button("执行")
    assert robot.wait.wait_until(
        lambda: "42" in captured.get("text", ""),
        timeout_ms=15_000,
    )


def test_edit_pending_tool_metadata(
    main_window,
    robot,
    pending_tool_factory,
    published_tool_factory,
    skill_composition_factory,
):
    pending_tool = pending_tool_factory(
        tool_name="待编辑技能",
        description="旧描述",
        workflow_id="wf-edit-pending",
    )
    published_tool = published_tool_factory(tool_name="引用技能", description="引用测试")
    skill_composition_factory(
        composition_name="引用该技能的组合",
        tool_ids=[pending_tool.tool_id, published_tool.tool_id],
    )

    robot.ui.click_sidebar_page(SKILLS)
    card = _find_pending_card(main_window.pending_tools_page, "待编辑技能")
    assert card is not None

    _schedule_input_dialog_sequence(robot, ["新名称", "新描述"])
    QTimer.singleShot(
        500,
        lambda: robot.ui.click_dialog_button(QDialogButtonBox.StandardButton.Ok),
    )
    _schedule_menu_action(robot, "编辑")
    robot.ui.click_widget(card._more_btn)

    assert robot.wait.wait_until(
        lambda: _find_pending_card(main_window.pending_tools_page, "新名称") is not None,
        timeout_ms=8_000,
    )
    assert _labels_contain(main_window.pending_tools_page, "新描述")
    tool = ToolRepository().get_by_id(pending_tool.tool_id)
    assert tool is not None
    assert tool.tool_name == "新名称"
    assert tool.description == "新描述"


def test_delete_pending_tool(main_window, robot, pending_tool_factory):
    pending_tool = pending_tool_factory(tool_name="待删除技能")

    robot.ui.click_sidebar_page(SKILLS)
    card = _find_pending_card(main_window.pending_tools_page, "待删除技能")
    assert card is not None

    _schedule_yes(robot)
    _schedule_menu_action(robot, "删除")
    robot.ui.click_widget(card._more_btn)

    assert robot.wait.wait_until(
        lambda: ToolRepository().get_by_id(pending_tool.tool_id) is None,
        timeout_ms=5_000,
    )


def test_delete_published_tool(main_window, robot, published_tool_factory):
    published_tool = published_tool_factory(tool_name="已掌握待删除技能")

    robot.ui.click_sidebar_page(SKILLS)
    robot.ui.click_button_prefix("已掌握")
    assert robot.wait.wait_until(
        lambda: _find_published_card(main_window.pending_tools_page, "已掌握待删除技能") is not None,
        timeout_ms=5_000,
    )

    card = _find_published_card(main_window.pending_tools_page, "已掌握待删除技能")
    assert card is not None
    _schedule_yes(robot)
    _schedule_menu_action(robot, "删除")
    robot.ui.click_widget(card._more_btn)

    assert robot.wait.wait_until(
        lambda: ToolRepository().get_by_id(published_tool.tool_id) is None,
        timeout_ms=5_000,
    )


def test_published_tool_has_no_edit(main_window, robot, published_tool_factory):
    published_tool_factory(tool_name="只允许删除技能")

    robot.ui.click_sidebar_page(SKILLS)
    robot.ui.click_button_prefix("已掌握")
    assert robot.wait.wait_until(
        lambda: _find_published_card(main_window.pending_tools_page, "只允许删除技能") is not None,
        timeout_ms=5_000,
    )

    card = _find_published_card(main_window.pending_tools_page, "只允许删除技能")
    assert card is not None
    QTimer.singleShot(
        120,
        lambda: captured_actions.extend(
            action.text() for action in QApplication.instance().activePopupWidget().actions()
        ),
    )
    QTimer.singleShot(
        220,
        lambda: QApplication.instance().activePopupWidget().close(),
    )
    captured_actions: list[str] = []
    robot.ui.click_widget(card._more_btn)

    assert captured_actions == ["删除"]
