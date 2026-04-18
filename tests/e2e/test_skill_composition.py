from __future__ import annotations

from collections import deque

import pytest
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import QApplication, QDialogButtonBox, QLabel

from src.business.services.skill_composition.service import SkillCompositionService
from src.business.services.skill_composition.types import (
    SkillCompositionTrialResult,
    SkillCompositionTrialSessionStart,
)
from src.data.repositories import SkillCompositionRepository, ToolRepository
from src.ui.page_ids import INTENT_CONFIRMATION, SKILLS

pytestmark = pytest.mark.e2e


def _labels_contain(widget, text: str) -> bool:
    return any(label.isVisible() and text in label.text() for label in widget.findChildren(QLabel))


def _find_composition_card(skills_page, composition_name: str):
    for card in skills_page.skill_composition_cards:
        if card.composition.composition_name == composition_name:
            return card
    return None


def _check_tool(dialog, tool_name: str) -> None:
    for index in range(dialog.available_list.count()):
        item = dialog.available_list.item(index)
        if tool_name in item.text():
            item.setCheckState(Qt.CheckState.Checked)
            return
    raise AssertionError(f"未在组合对话框中找到技能: {tool_name}")


def _schedule_menu_action(robot, action_text: str, delay_ms: int = 100) -> None:
    QTimer.singleShot(delay_ms, lambda: robot.ui.click_menu_action(action_text))


def test_create_composition(main_window, robot, published_tool_factory):
    first_tool = published_tool_factory(tool_name="组合技能 A", description="组合测试 A")
    second_tool = published_tool_factory(tool_name="组合技能 B", description="组合测试 B")

    robot.ui.click_sidebar_page(SKILLS)
    robot.ui.click_button_prefix("技能组合")
    assert main_window.pending_tools_page.compositions_empty_state.isVisible()

    def fill_dialog():
        dialog = QApplication.instance().activeModalWidget()
        assert dialog is not None
        assert dialog.windowTitle() == "新建技能组合"
        _check_tool(dialog, first_tool.tool_name)
        _check_tool(dialog, second_tool.tool_name)
        robot.ui.fill(dialog.name_input, "测试组合")
        robot.ui.fill(dialog.description_input, "测试组合描述")
        robot.ui.fill(dialog.applicability_input, "用于测试")
        robot.ui.click_button("保存")

    QTimer.singleShot(120, fill_dialog)
    robot.ui.click_button("新建技能组合")

    assert robot.wait.wait_until(
        lambda: _find_composition_card(main_window.pending_tools_page, "测试组合") is not None,
        timeout_ms=5_000,
    )
    composition = SkillCompositionRepository().get_by_name("测试组合")
    assert composition is not None
    assert composition.status == "draft"


def test_trial_composition(
    main_window,
    robot,
    monkeypatch,
    published_tool_factory,
    skill_composition_factory,
):
    first_tool = published_tool_factory(tool_name="试用技能 A")
    second_tool = published_tool_factory(tool_name="试用技能 B")
    composition = skill_composition_factory(
        composition_name="可试用组合",
        tool_ids=[first_tool.tool_id, second_tool.tool_id],
    )

    scripted_results = deque(
        [
            SkillCompositionTrialResult(
                success=False,
                reply="请补充测试环境信息。",
                result_type="needs_user_input",
                session_id="comptrial_scripted",
            ),
            SkillCompositionTrialResult(
                success=True,
                reply="组合试用完成。",
                result_type="completed",
                session_id="comptrial_scripted",
            ),
        ]
    )

    monkeypatch.setattr(
        SkillCompositionService,
        "start_trial_session",
        lambda self, composition_id: SkillCompositionTrialSessionStart(
            composition_id=composition_id,
            composition_name="可试用组合",
            session_id="comptrial_scripted",
        ),
    )
    monkeypatch.setattr(
        SkillCompositionService,
        "continue_trial",
        lambda self, composition_id, session_id, user_input: scripted_results.popleft(),
    )

    robot.ui.click_sidebar_page(SKILLS)
    robot.ui.click_button_prefix("技能组合")
    card = _find_composition_card(main_window.pending_tools_page, composition.composition_name)
    assert card is not None
    robot.ui.click_button("试一下", root=card)

    assert robot.wait.wait_until(
        lambda: main_window.main_content.get_current_page() == INTENT_CONFIRMATION,
        timeout_ms=5_000,
    )
    assert robot.wait.wait_until(
        lambda: _labels_contain(main_window.intent_confirmation_page, "请补充测试环境信息。"),
        timeout_ms=10_000,
    )

    robot.ui.fill(main_window.intent_confirmation_page.message_input, "浏览器环境已经就绪")
    robot.ui.click_button("发送")
    assert robot.wait.wait_until(
        lambda: _labels_contain(main_window.intent_confirmation_page, "组合试用完成。"),
        timeout_ms=10_000,
    )
    assert main_window._current_composition_trial_session_id is None


def test_publish_and_offline_composition(
    main_window,
    robot,
    published_tool_factory,
    skill_composition_factory,
):
    first_tool = published_tool_factory(tool_name="发布技能 A")
    second_tool = published_tool_factory(tool_name="发布技能 B")
    skill_composition_factory(
        composition_name="发布组合",
        tool_ids=[first_tool.tool_id, second_tool.tool_id],
        status="published",
    )

    robot.ui.click_sidebar_page(SKILLS)
    robot.ui.click_button_prefix("技能组合")

    card = _find_composition_card(main_window.pending_tools_page, "发布组合")
    assert card is not None
    _schedule_menu_action(robot, "下线")
    QTimer.singleShot(
        220,
        lambda: robot.ui.click_dialog_button(QDialogButtonBox.StandardButton.Yes),
    )
    robot.ui.click_widget(card._more_btn)

    assert robot.wait.wait_until(
        lambda: SkillCompositionRepository().get_by_name("发布组合").status == "offline",
        timeout_ms=5_000,
    )

    main_window.pending_tools_page.refresh()
    card = _find_composition_card(main_window.pending_tools_page, "发布组合")
    assert card is not None
    _schedule_menu_action(robot, "重新发布")
    robot.ui.click_widget(card._more_btn)
    assert robot.wait.wait_until(
        lambda: SkillCompositionRepository().get_by_name("发布组合").status == "published",
        timeout_ms=5_000,
    )

    main_window.pending_tools_page.refresh()
    card = _find_composition_card(main_window.pending_tools_page, "发布组合")
    assert card is not None
    _schedule_menu_action(robot, "下线")
    QTimer.singleShot(
        220,
        lambda: robot.ui.click_dialog_button(QDialogButtonBox.StandardButton.Yes),
    )
    robot.ui.click_widget(card._more_btn)

    main_window.pending_tools_page.refresh()
    card = _find_composition_card(main_window.pending_tools_page, "发布组合")
    assert card is not None
    _schedule_menu_action(robot, "删除")
    QTimer.singleShot(
        220,
        lambda: robot.ui.click_dialog_button(QDialogButtonBox.StandardButton.Yes),
    )
    robot.ui.click_widget(card._more_btn)

    assert robot.wait.wait_until(
        lambda: SkillCompositionRepository().get_by_name("发布组合") is None,
        timeout_ms=5_000,
    )


def test_cascade_review_on_skill_change(
    main_window,
    robot,
    published_tool_factory,
    skill_composition_factory,
):
    primary_tool = published_tool_factory(
        tool_name="级联技能 A",
        workflow_id="wf-cascade-a",
        code="async def execute(**kwargs):\n    return {'success': True, 'message': 'v1', 'data': {}}\n",
    )
    secondary_tool = published_tool_factory(tool_name="级联技能 B")
    skill_composition_factory(
        composition_name="级联组合",
        tool_ids=[primary_tool.tool_id, secondary_tool.tool_id],
        status="published",
    )
    assert main_window._ensure_agent_bridge(timeout=10.0)

    orchestrator = main_window.agent_ui_bridge._orchestrator
    orchestrator._save_tool(
        {
            "tool_name": "级联技能 A",
            "description": "更新后的描述",
            "code": "async def execute(**kwargs):\n    return {'success': True, 'message': 'v2', 'data': kwargs}\n",
            "execution_strategy": "api",
            "parameters": [],
        },
        "wf-cascade-a",
        "session-cascade",
    )

    robot.ui.click_sidebar_page(SKILLS)
    robot.ui.click_button_prefix("技能组合")
    main_window.pending_tools_page.refresh()

    composition = SkillCompositionRepository().get_by_name("级联组合")
    assert composition is not None
    assert composition.needs_review is True
    assert composition.status == "published"
    assert not SkillCompositionService().get_assistant_published_summaries()

    card = _find_composition_card(main_window.pending_tools_page, "级联组合")
    assert card is not None
    assert card.composition.needs_review is True

    updated_tool = ToolRepository().get_by_id(primary_tool.tool_id)
    assert updated_tool is not None
    assert updated_tool.status == "pending"
