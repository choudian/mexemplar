import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
import sys
from types import MethodType, SimpleNamespace

import pytest

from src.business.agents.config import ResultType
from src.business.agents.tools.dynamic_tool_manager import DynamicToolManager
from src.business.orchestration.agent_orchestrator import AgentOrchestrator
from src.business.services import SkillCompositionError, SkillCompositionService, SkillsService
import src.business.services.skill_composition_service as skill_composition_service_module
from src.data.models import SkillComposition, SkillCompositionMember, Tool
from src.data.models_sqlite import (
    Message as MessageOrm,
    Session as SessionOrm,
    SkillComposition as SkillCompositionOrm,
    SkillCompositionMember as SkillCompositionMemberOrm,
    Tool as ToolOrm,
)
from src.data.repositories import (
    MessageRepository,
    SessionRepository,
    SkillCompositionRepository,
    ToolRepository,
)
from src.ui.skill_composition_dialogs import (
    ApplicabilityGenerationThread,
    COMPOSITION_MODE_CHEVRON_DATA_URI,
    RecommendationGenerationThread,
    SkillCompositionEditDialog,
)
from src.ui.tools_management_ui import ToolsManagementUI


@pytest.fixture(scope="module")
def qt_app():
    try:
        from PyQt6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication(sys.argv)
    except Exception:
        pytest.skip("PyQt6 不可用或无法创建 QApplication")
    return app


class _DummySelectedListItem:
    def __init__(self, tool_id: str, checked):
        self._tool_id = tool_id
        self._checked = checked

    def data(self, _role):
        return self._tool_id

    def checkState(self):
        return self._checked


class _DummySelectedList:
    def __init__(self, items: list[tuple[str, object]]):
        self._items = [_DummySelectedListItem(tool_id, checked) for tool_id, checked in items]

    def count(self) -> int:
        return len(self._items)

    def item(self, row: int):
        return self._items[row]


class _DummyLineInput:
    def __init__(self, value: str):
        self._value = value

    def text(self) -> str:
        return self._value


class _DummyTextInput:
    def __init__(self, value: str):
        self._value = value

    def toPlainText(self) -> str:
        return self._value


class _FakeConfig:
    def get_ai_api_key(self) -> str:
        return "test-key"

    def get_ai_provider(self) -> str:
        return "openai"

    def get_ai_model(self) -> str:
        return "gpt-test"

    def get_ai_base_url(self):
        return None


class _DummyLLMClient:
    def __init__(self, *args, **kwargs):
        pass


def _patch_trial_environment(monkeypatch) -> None:
    monkeypatch.setattr(
        skill_composition_service_module,
        "get_unified_config",
        lambda: _FakeConfig(),
    )
    monkeypatch.setattr(
        skill_composition_service_module,
        "LangChainLLMClient",
        _DummyLLMClient,
    )


def _seed_published_tool(
    tool_id: str,
    tool_name: str,
    description: str = "技能描述",
) -> None:
    with ToolRepository() as tool_repo:
        tool_repo.create(
            ToolOrm(
                tool_id=tool_id,
                tool_name=tool_name,
                description=description,
                status="published",
            )
        )


def _create_composition(
    composition_name: str,
    tool_ids: list[str],
    mode: str = "range",
) -> SkillComposition:
    members = []
    for index, tool_id in enumerate(tool_ids, start=1):
        members.append(
            {
                "tool_id": tool_id,
                "selected_order": index,
                "execution_order": index if mode == "ordered" else None,
            }
        )
    return SkillCompositionService().create_composition(
        composition_name=composition_name,
        description=f"{composition_name}描述",
        applicability=f"{composition_name}适用场景",
        mode=mode,
        assistant_enabled=True,
        recommend_order=(mode == "ordered"),
        members=members,
    )


def _seed_review_required_composition() -> None:
    _seed_published_tool("tool_reviewed_member", "成员技能", "成员技能描述")

    with SkillCompositionRepository() as composition_repo:
        composition_repo.create(
            SkillCompositionOrm(
                composition_id="comp_needs_review",
                composition_name="待复核组合",
                description="需要重新发布",
                applicability="测试待复核过滤",
                mode="range",
                status="published",
                assistant_enabled=True,
                needs_review=True,
            ),
            [
                SkillCompositionMemberOrm(
                    member_id="member_reviewed_1",
                    composition_id="comp_needs_review",
                    tool_id="tool_reviewed_member",
                    selected_order=1,
                )
            ],
        )


def test_update_tool_metadata_persists_with_single_repository_session():
    with ToolRepository() as repo:
        repo.create(
            ToolOrm(
                tool_id="tool_meta_update",
                tool_name="旧名称",
                description="旧描述",
                status="published",
            )
        )

    referenced = SkillsService().update_tool_metadata(
        "tool_meta_update",
        "新名称",
        " 新描述 ",
    )

    assert referenced == []
    with ToolRepository() as repo:
        updated = repo.get_by_id("tool_meta_update")
        assert updated is not None
        assert updated.tool_name == "新名称"
        assert updated.description == "新描述"


def test_needs_review_compositions_are_hidden_from_assistant_queries():
    _seed_review_required_composition()

    service = SkillCompositionService()

    assert service.get_assistant_published_summaries() == []
    assert service.search_published_compositions("待复核组合") == []

    detail = DynamicToolManager().get_tool_detail("技能组合:待复核组合")
    assert "不存在或当前不可用" in detail


def test_execution_snapshot_hides_needs_review_composition_when_published_is_required():
    _seed_review_required_composition()

    service = SkillCompositionService()

    assert service.get_execution_snapshot("comp_needs_review") is None
    assert (
        service.get_execution_snapshot(
            "comp_needs_review",
            require_published=False,
        )
        is not None
    )


def test_sync_selected_order_from_list_updates_selected_order_map():
    from PyQt6.QtCore import Qt

    dialog = SimpleNamespace(
        selected_tool_ids=["tool_a", "tool_b", "tool_c"],
        selection_order_map={"tool_a": 1, "tool_b": 2, "tool_c": 3},
        available_list=_DummySelectedList(
            [
                ("tool_c", Qt.CheckState.Checked),
                ("tool_a", Qt.CheckState.Checked),
                ("tool_x", Qt.CheckState.Unchecked),
                ("tool_b", Qt.CheckState.Checked),
            ]
        ),
    )
    dialog._sync_selection_order_map = MethodType(
        SkillCompositionEditDialog._sync_selection_order_map,
        dialog,
    )

    SkillCompositionEditDialog._sync_selected_order_from_list(dialog)

    assert dialog.selected_tool_ids == ["tool_c", "tool_a", "tool_b"]
    assert dialog.selection_order_map == {"tool_c": 1, "tool_a": 2, "tool_b": 3}


def test_large_composition_keeps_all_members_activated():
    manager = DynamicToolManager(revalidate_activated=False)
    members = []
    expected_short_ids = set()

    for index in range(1, 13):
        tool = Tool(
            tool_id=f"tool_large_{index}",
            tool_name=f"大组合成员 {index}",
            description=f"成员 {index}",
            status="published",
        )
        members.append(
            SkillCompositionMember(
                tool_id=tool.tool_id,
                selected_order=index,
                execution_order=index,
                tool=tool,
            )
        )
        expected_short_ids.add(manager._make_short_id(tool.tool_id, "utool"))

    composition = SkillComposition(
        composition_id="comp_large",
        composition_name="超大组合",
        applicability="验证成员激活不被提前淘汰",
        mode="ordered",
        status="published",
        assistant_enabled=True,
        members=members,
    )

    handler = manager._create_composition_handler(composition)
    handler(task="执行超大组合")

    activated_short_ids = {tool_def.name for tool_def in manager.get_activated_tools()}
    assert expected_short_ids.issubset(activated_short_ids)


def test_generate_applicability_uses_selected_skills_and_cleans_prefix(monkeypatch):
    _seed_published_tool("tool_apply_1", "资料抓取", "收集原始资料")
    _seed_published_tool("tool_apply_2", "结果整理", "整理输出结构")
    monkeypatch.setattr(
        skill_composition_service_module,
        "get_unified_config",
        lambda: _FakeConfig(),
    )

    captured = {}

    class _ApplicabilityLLM:
        def __init__(self, *args, **kwargs):
            pass

        def chat(self, prompt: str, **kwargs) -> str:
            captured["prompt"] = prompt
            return "适用场景：适合先抓取资料、再整理结果的多步骤任务。"

    monkeypatch.setattr(
        skill_composition_service_module,
        "LangChainLLMClient",
        _ApplicabilityLLM,
    )

    result = SkillCompositionService().generate_applicability(
        composition_name="资料整合组合",
        description="先抓取再整理",
        mode="ordered",
        members=[
            {"tool_id": "tool_apply_1", "selected_order": 1, "execution_order": 1},
            {"tool_id": "tool_apply_2", "selected_order": 2, "execution_order": 2},
        ],
    )

    assert result == "适合先抓取资料、再整理结果的多步骤任务。"
    assert "资料抓取" in captured["prompt"]
    assert "结果整理" in captured["prompt"]
    assert "组合模式：顺序型" in captured["prompt"]


def test_get_tool_detail_accepts_display_labels_shown_to_assistant():
    _seed_published_tool("tool_display_label", "展示技能", "用于验证展示名激活")
    service = SkillCompositionService()
    composition = service.create_composition(
        composition_name="展示组合",
        description="用于验证展示名激活",
        applicability="测试展示名解析",
        mode="ordered",
        assistant_enabled=True,
        recommend_order=False,
        members=[{"tool_id": "tool_display_label", "selected_order": 1, "execution_order": 1}],
    )
    service.publish_composition(composition.composition_id)

    manager = DynamicToolManager()

    tool_detail = manager.get_tool_detail("- **[技能] 展示技能**：用于验证展示名激活")
    composition_detail = manager.get_tool_detail("- [技能组合/顺序型] 展示组合：用于验证展示名激活")

    assert "技能已激活" in tool_detail
    assert "技能组合已激活" in composition_detail


def test_activated_composition_is_removed_after_it_needs_review():
    _seed_published_tool("tool_stale_member", "待失效成员", "用于验证重校验")
    service = SkillCompositionService()
    composition = service.create_composition(
        composition_name="待失效组合",
        description="用于验证重校验",
        applicability="用于验证重校验",
        mode="range",
        assistant_enabled=True,
        recommend_order=False,
        members=[{"tool_id": "tool_stale_member", "selected_order": 1}],
    )
    service.publish_composition(composition.composition_id)

    manager = DynamicToolManager()
    manager.get_tool_detail("技能组合:待失效组合")
    composition_short_id = manager._make_short_id(composition.composition_id, "comp")
    assert composition_short_id in {tool.name for tool in manager.get_activated_tools()}

    service.mark_needs_review_by_tool("tool_stale_member")

    assert composition_short_id not in {tool.name for tool in manager.get_activated_tools()}


def test_save_tool_marks_referencing_compositions_stale_when_status_changes_to_pending(monkeypatch):
    workflow_id = "wf_status_flip_member"
    with ToolRepository() as tool_repo:
        tool_repo.create(
            ToolOrm(
                tool_id="tool_status_flip_member",
                tool_name="状态回退成员",
                description="用于验证状态回退触发复核",
                execution_code="print('stable')",
                parameters=[{"name": "topic", "description": "主题"}],
                execution_strategy="function_call",
                workflow_id=workflow_id,
                source="intent",
                status="published",
            )
        )

    service = SkillCompositionService()
    composition = service.create_composition(
        composition_name="状态回退组合",
        description="用于验证状态回退触发复核",
        applicability="用于验证状态回退触发复核",
        mode="range",
        assistant_enabled=True,
        recommend_order=False,
        members=[{"tool_id": "tool_status_flip_member", "selected_order": 1}],
    )
    service.publish_composition(composition.composition_id)

    manager = DynamicToolManager()
    manager.get_tool_detail("技能组合:状态回退组合")
    composition_short_id = manager._make_short_id(composition.composition_id, "comp")
    assert composition_short_id in {tool.name for tool in manager.get_activated_tools()}

    orchestrator = AgentOrchestrator(
        llm_client=SimpleNamespace(),
        config=SimpleNamespace(),
        llm_reviewer=SimpleNamespace(),
    )
    orchestrator._composition_service = service
    monkeypatch.setattr(orchestrator, "_emit_and_log", lambda *args, **kwargs: None)

    saved_tool_id = orchestrator._save_tool(
        {
            "code": "print('stable')",
            "tool_name": "状态回退成员",
            "description": "用于验证状态回退触发复核",
            "parameters": [{"name": "topic", "description": "主题"}],
            "execution_strategy": "function_call",
        },
        workflow_id=workflow_id,
        session_id="session_status_flip_member",
        status="pending",
    )

    assert saved_tool_id == "tool_status_flip_member"
    refreshed = service.get_composition(composition.composition_id)
    assert refreshed is not None
    assert refreshed.needs_review is True
    assert composition_short_id not in {tool.name for tool in manager.get_activated_tools()}


def test_dialog_payload_does_not_include_business_defaults():
    """UI payload 不再包含 assistant_enabled / recommend_order，由 Service 层提供默认值。"""
    dialog = SimpleNamespace(
        selected_tool_ids=["tool_a", "tool_b"],
        selection_order_map={"tool_a": 1, "tool_b": 2},
        _current_mode=lambda: "ordered",
        name_input=_DummyLineInput("组合名称"),
        description_input=_DummyTextInput("组合描述"),
        applicability_input=_DummyTextInput("组合适用场景"),
    )

    payload = SkillCompositionEditDialog.get_payload(dialog)

    assert "assistant_enabled" not in payload
    assert "recommend_order" not in payload
    assert payload["members"] == [
        {"tool_id": "tool_a", "selected_order": 1, "execution_order": 1},
        {"tool_id": "tool_b", "selected_order": 2, "execution_order": 2},
    ]


def test_service_create_composition_defaults_assistant_enabled_and_recommend_order():
    """Service 层 create_composition 的 assistant_enabled / recommend_order 有正确默认值。"""
    import inspect
    sig = inspect.signature(SkillCompositionService.create_composition)
    assert sig.parameters["assistant_enabled"].default is True
    assert sig.parameters["recommend_order"].default is False


def test_dialog_tab_focus_and_applicability_overlay(qt_app, monkeypatch):
    from PyQt6.QtCore import QPoint, Qt, QRect
    from PyQt6.QtTest import QTest
    from PyQt6.QtWidgets import QAbstractItemView

    monkeypatch.setattr(
        SkillCompositionService,
        "get_published_tool_choices",
        lambda self: [
            Tool(tool_id="tool_a", tool_name="技能A", description="A", status="published"),
            Tool(tool_id="tool_b", tool_name="技能B", description="B", status="published"),
            Tool(tool_id="tool_c", tool_name="技能C", description="C", status="published"),
        ],
    )

    dialog = SkillCompositionEditDialog()
    dialog.show()
    qt_app.processEvents()

    try:
        assert dialog.description_input.tabChangesFocus() is True
        assert dialog.applicability_input.tabChangesFocus() is True
        assert dialog.mode_combo.objectName() == "composition_mode_combo"
        assert COMPOSITION_MODE_CHEVRON_DATA_URI in dialog.styleSheet()

        dialog.description_input.setFocus()
        qt_app.processEvents()
        assert dialog.description_input.hasFocus() is True

        dialog.selected_tool_ids = ["tool_a", "tool_b"]
        dialog.selection_order_map = {"tool_a": 1, "tool_b": 2}
        dialog._refresh_selected_tools()
        qt_app.processEvents()

        assert not hasattr(dialog, "selected_title_label")
        assert dialog.available_list.dragDropMode() == QAbstractItemView.DragDropMode.NoDragDrop
        assert dialog.recommend_now_button.parentWidget() is dialog.available_list
        assert dialog.recommend_now_button.isVisible() is False
        assert dialog.available_list.viewportMargins().top() == 0
        assert dialog.available_list.count() == 3
        assert dialog.available_list.item(0).text() == "技能A"
        assert dialog.available_list.item(1).text() == "技能B"
        assert dialog.available_list.item(2).text() == "技能C"
        assert "选择序" not in dialog.available_list.item(0).text()

        ordered_index = dialog.mode_combo.findData("ordered")
        dialog.mode_combo.setCurrentIndex(ordered_index)
        qt_app.processEvents()

        assert dialog.available_list.dragDropMode() == QAbstractItemView.DragDropMode.InternalMove
        assert dialog.recommend_now_button.isVisible() is True
        assert dialog.available_list.viewportMargins().top() == 0
        assert dialog.available_list.item(0).text() == "1. 技能A"
        assert dialog.available_list.item(1).text() == "2. 技能B"
        assert dialog.available_list.item(2).text() == "技能C"
        button_rect = dialog.recommend_now_button.geometry()
        assert button_rect.top() == 8
        assert button_rect.right() <= dialog.available_list.rect().right() - 8

        dialog._set_recommend_button_position(QPoint(10_000, 10_000))
        qt_app.processEvents()
        left, top, width, height = dialog._recommend_button_bounds()
        allowed_rect = QRect(left, top, width, height)
        button_rect = dialog.recommend_now_button.geometry()
        assert allowed_rect.contains(button_rect.topLeft())
        assert allowed_rect.contains(button_rect.bottomRight())

        dialog._set_recommend_button_position(QPoint(-10_000, -10_000))
        qt_app.processEvents()
        button_rect = dialog.recommend_now_button.geometry()
        assert allowed_rect.contains(button_rect.topLeft())
        assert allowed_rect.contains(button_rect.bottomRight())

        QTest.keyClick(dialog.description_input, Qt.Key.Key_Tab)
        qt_app.processEvents()
        assert dialog.applicability_input.hasFocus() is True

        floating_field = dialog.generate_applicability_button.parentWidget().parentWidget()
        floating_field._set_button_position(QPoint(10_000, 10_000))
        qt_app.processEvents()

        left, top, width, height = floating_field._button_bounds()
        allowed_rect = QRect(left, top, width, height)
        button_rect = dialog.generate_applicability_button.geometry()
        assert allowed_rect.contains(button_rect.topLeft())
        assert allowed_rect.contains(button_rect.bottomRight())

        floating_field._set_button_position(QPoint(-10_000, -10_000))
        qt_app.processEvents()
        button_rect = dialog.generate_applicability_button.geometry()
        assert allowed_rect.contains(button_rect.topLeft())
        assert allowed_rect.contains(button_rect.bottomRight())

        assert (
            dialog.generate_applicability_button.parentWidget()
            is floating_field.panel
        )
        assert dialog.applicability_input.viewportMargins().right() == 0
    finally:
        dialog.close()
        dialog.deleteLater()


def test_dialog_member_list_enables_vertical_scrollbar_when_height_is_limited(qt_app, monkeypatch):
    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QSizePolicy

    monkeypatch.setattr(
        SkillCompositionService,
        "get_published_tool_choices",
        lambda self: [
            Tool(tool_id=f"tool_{index}", tool_name=f"技能{index}", description=str(index), status="published")
            for index in range(1, 9)
        ],
    )

    dialog = SkillCompositionEditDialog()
    dialog.show()
    qt_app.processEvents()

    try:
        assert dialog.available_list.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded
        assert dialog.available_list.sizePolicy().verticalPolicy() == QSizePolicy.Policy.Expanding
        assert dialog.available_list.count() == 8

        row_height = dialog.available_list.sizeHintForRow(0)
        assert row_height > 0
        dialog.available_list.setMaximumHeight(row_height * 5 + dialog.available_list.frameWidth() * 2)
        qt_app.processEvents()

        assert dialog.available_list.verticalScrollBar().maximum() > 0
    finally:
        dialog.close()
        dialog.deleteLater()


def test_dialog_member_list_double_click_toggles_membership(qt_app, monkeypatch):
    from PyQt6.QtCore import Qt
    from PyQt6.QtTest import QTest

    monkeypatch.setattr(
        SkillCompositionService,
        "get_published_tool_choices",
        lambda self: [
            Tool(tool_id="tool_a", tool_name="技能A", description="A", status="published"),
            Tool(tool_id="tool_b", tool_name="技能B", description="B", status="published"),
        ],
    )

    dialog = SkillCompositionEditDialog()
    dialog.show()
    qt_app.processEvents()

    try:
        first_item = dialog.available_list.item(0)
        assert first_item.checkState() == Qt.CheckState.Unchecked

        first_rect = dialog.available_list.visualItemRect(first_item)
        QTest.mouseDClick(
            dialog.available_list.viewport(),
            Qt.MouseButton.LeftButton,
            pos=first_rect.center(),
        )
        qt_app.processEvents()

        assert dialog.selected_tool_ids == ["tool_a"]
        assert dialog.available_list.item(0).checkState() == Qt.CheckState.Checked

        first_item = dialog.available_list.item(0)
        first_rect = dialog.available_list.visualItemRect(first_item)
        QTest.mouseDClick(
            dialog.available_list.viewport(),
            Qt.MouseButton.LeftButton,
            pos=first_rect.center(),
        )
        qt_app.processEvents()

        assert dialog.selected_tool_ids == []
        assert dialog.available_list.item(0).checkState() == Qt.CheckState.Unchecked
    finally:
        dialog.close()
        dialog.deleteLater()


def test_dialog_generate_applicability_uses_background_thread(qt_app, monkeypatch):
    monkeypatch.setattr(
        SkillCompositionService,
        "get_published_tool_choices",
        lambda self: [
            Tool(tool_id="tool_a", tool_name="技能A", description="A", status="published"),
        ],
    )

    def fail_if_called(*args, **kwargs):
        raise AssertionError("generate_applicability should not run on the UI thread")

    started = {}

    def fake_start(self):
        started["composition_name"] = self.composition_name
        started["mode"] = self.mode
        started["members"] = self.members

    monkeypatch.setattr(SkillCompositionService, "generate_applicability", fail_if_called)
    monkeypatch.setattr(ApplicabilityGenerationThread, "start", fake_start)

    dialog = SkillCompositionEditDialog()
    dialog.show()
    qt_app.processEvents()

    try:
        dialog.name_input.setText("异步组合")
        dialog.selected_tool_ids = ["tool_a"]
        dialog.selection_order_map = {"tool_a": 1}
        dialog._refresh_selected_tools()
        qt_app.processEvents()

        dialog._generate_applicability()

        assert started["composition_name"] == "异步组合"
        assert started["mode"] == "range"
        assert started["members"] == [{"tool_id": "tool_a", "selected_order": 1, "execution_order": None}]
        assert dialog.generate_applicability_button.text() == "生成中..."
        assert dialog.generate_applicability_button.isEnabled() is False

        dialog._on_applicability_generated(True, "适合异步生成测试。", "")
        dialog._clear_applicability_generation_thread()
        qt_app.processEvents()

        assert dialog.applicability_input.toPlainText() == "适合异步生成测试。"
        assert dialog.generate_applicability_button.text() == "一键生成"
        assert dialog.generate_applicability_button.isEnabled() is True
    finally:
        dialog.close()
        dialog.deleteLater()


def test_dialog_generate_recommendation_uses_background_thread(qt_app, monkeypatch):
    from PyQt6.QtWidgets import QMessageBox

    monkeypatch.setattr(
        SkillCompositionService,
        "get_published_tool_choices",
        lambda self: [
            Tool(tool_id="tool_a", tool_name="技能A", description="A", status="published"),
            Tool(tool_id="tool_b", tool_name="技能B", description="B", status="published"),
        ],
    )

    def fail_if_called(*args, **kwargs):
        raise AssertionError("recommend_execution_order should not run on the UI thread")

    started = {}
    notices = []

    def fake_start(self):
        started["composition_name"] = self.composition_name
        started["applicability"] = self.applicability
        started["members"] = self.members

    monkeypatch.setattr(SkillCompositionService, "recommend_execution_order", fail_if_called)
    monkeypatch.setattr(RecommendationGenerationThread, "start", fake_start)
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda *args: notices.append((args[1], args[2])),
    )

    dialog = SkillCompositionEditDialog()
    dialog.show()
    qt_app.processEvents()

    try:
        dialog.selected_tool_ids = ["tool_a", "tool_b"]
        dialog.selection_order_map = {"tool_a": 1, "tool_b": 2}
        dialog.name_input.setText("异步推荐组合")
        dialog.applicability_input.setPlainText("适合同步改异步测试。")
        ordered_index = dialog.mode_combo.findData("ordered")
        dialog.mode_combo.setCurrentIndex(ordered_index)
        dialog._refresh_selected_tools()
        qt_app.processEvents()

        assert dialog._generate_recommendation() is True

        assert started["composition_name"] == "异步推荐组合"
        assert started["applicability"] == "适合同步改异步测试。"
        assert started["members"] == [
            {"tool_id": "tool_a", "selected_order": 1, "execution_order": 1},
            {"tool_id": "tool_b", "selected_order": 2, "execution_order": 2},
        ]
        assert dialog.recommend_now_button.text() == "推荐中..."
        assert dialog.recommend_now_button.isEnabled() is False
        assert dialog.mode_combo.isEnabled() is False
        assert dialog.available_list.isEnabled() is False

        dialog._on_recommendation_generated(
            True,
            {
                "members": [
                    {"tool_id": "tool_b", "execution_order": 1},
                    {"tool_id": "tool_a", "execution_order": 2},
                ],
                "reason": "建议先执行技能B。",
            },
            "",
        )
        dialog._clear_recommendation_generation_thread()
        qt_app.processEvents()

        assert dialog.selected_tool_ids == ["tool_b", "tool_a"]
        assert dialog.recommend_now_button.text() == "推荐顺序"
        assert dialog.recommend_now_button.isEnabled() is True
        assert dialog.mode_combo.isEnabled() is True
        assert dialog.available_list.isEnabled() is True
        assert notices == [("推荐顺序已更新", "建议先执行技能B。")]
    finally:
        dialog.close()
        dialog.deleteLater()


def test_tools_management_composition_create_button_moves_to_tab_bar(qt_app, monkeypatch):
    monkeypatch.setattr(ToolsManagementUI, "_load_tools", lambda self: None)
    monkeypatch.setattr(ToolsManagementUI, "_load_compositions", lambda self: None)

    ui = ToolsManagementUI()
    ui.show()
    qt_app.processEvents()

    try:
        assert ui._create_composition_btn.parentWidget() is ui._tab_bar
        assert ui._create_composition_btn.isVisible() is False
        assert ui.compositions_empty_state.isVisible() is False

        ui._switch_tab("compositions")
        qt_app.processEvents()

        assert ui._create_composition_btn.isVisible() is True
        assert ui.compositions_empty_state.isVisible() is True
        assert ui._empty_create_composition_btn.isVisible() is True

        ui.update_skill_compositions(
            [
                SkillComposition(
                    composition_id="comp_visible",
                    composition_name="可见组合",
                    applicability="测试",
                    mode="range",
                    status="draft",
                    assistant_enabled=True,
                    members=[],
                )
            ]
        )
        qt_app.processEvents()

        assert ui.compositions_empty_state.isVisible() is False
    finally:
        ui.close()
        ui.deleteLater()


def test_intent_confirmation_cancel_emits_signal_without_closing_parent(qt_app):
    from PyQt6.QtWidgets import QWidget

    from src.ui.intent_confirmation_ui import IntentConfirmationUI

    class _ParentWidget(QWidget):
        def __init__(self):
            super().__init__()
            self.closed_via_event = False

        def closeEvent(self, event):
            self.closed_via_event = True
            super().closeEvent(event)

    parent = _ParentWidget()
    page = IntentConfirmationUI(parent)
    triggered = []
    page.cancel_requested.connect(lambda: triggered.append(True))

    parent.show()
    page.show()
    qt_app.processEvents()

    try:
        page.cancel_button.click()
        qt_app.processEvents()

        assert triggered == [True]
        assert parent.closed_via_event is False
        assert parent.isVisible() is True
    finally:
        page.close()
        page.deleteLater()
        parent.close()
        parent.deleteLater()


def test_start_trial_session_creates_session():
    _seed_published_tool("tool_range_dialog_member", "范围成员", "范围成员描述")
    composition = _create_composition(
        "范围试用组合",
        ["tool_range_dialog_member"],
        mode="range",
    )

    start = SkillCompositionService().start_trial_session(composition.composition_id)

    assert start.composition_id == composition.composition_id
    assert start.composition_name == composition.composition_name

    with SessionRepository() as repo:
        session = repo.get_by_id(start.session_id)
        assert session is not None
        assert session.workflow_id == composition.composition_id
        assert session.agent_type == "composition_trial"


def test_build_trial_bootstrap_input_uses_program_role():
    bootstrap = SkillCompositionService.build_trial_bootstrap_input()

    assert bootstrap["role"] == "program"
    assert "主动向用户发起第一轮沟通" in bootstrap["content"]
    assert "不要先讲长篇说明" in bootstrap["content"]


def test_trial_prompt_does_not_reference_unavailable_helper_tools():
    composition = SkillComposition(
        composition_id="comp_prompt_test",
        composition_name="试用提示组合",
        description="验证试用提示词",
        applicability="验证试用提示词",
        mode="ordered",
        status="published",
        assistant_enabled=True,
        members=[
            SkillCompositionMember(
                tool_id="tool_prompt_a",
                selected_order=1,
                execution_order=1,
                tool=Tool(
                    tool_id="tool_prompt_a",
                    tool_name="成员A",
                    parameters=[
                        {"name": "query", "description": "想查的主题", "required": True},
                        {"name": "limit", "description": "数量上限", "required": False, "default": 3},
                    ],
                    status="published",
                ),
            ),
            SkillCompositionMember(
                tool_id="tool_prompt_b",
                selected_order=2,
                execution_order=2,
                tool=Tool(tool_id="tool_prompt_b", tool_name="成员B", status="published"),
            ),
        ],
    )

    prompt = SkillCompositionService._build_trial_system_prompt(composition)

    assert "search_tools" not in prompt
    assert "get_tool_detail" not in prompt
    assert "report_tool_bug" not in prompt
    assert "你必须先直接调用这个技能组合本身" in prompt
    assert "成员技能只会在技能组合启动后才会出现" in prompt
    assert "## 你的任务" in prompt
    assert "## 你的内部推进节奏" in prompt
    assert "## 引导策略" in prompt
    assert "先获取用户这次想通过这个技能组合完成什么任务" in prompt
    assert "先判断这个技能组合能不能完成当前任务" in prompt
    assert "获取目标：先判断用户有没有明确说出这次想完成什么任务" in prompt
    assert "判断可行性与缺口：基于整体目标，先判断这个技能组合能不能完成任务" in prompt
    assert "顺序型组合的完整目标有四件事" in prompt
    assert "先判断这个技能组合按当前配置是否真的适合完成用户的任务" in prompt
    assert "更合适的路径更像是 1-3-2 而不是当前配置的 1-2-3" in prompt
    assert "用户接受就继续，以完成任务为第一优先" in prompt
    assert "用非技术语言说话" in prompt
    assert "不要说“参数”“字段”“变量”“内部名”" in prompt
    assert "不要把“参数”“参数名”“字段名”“内部名”这类技术词直接抛给用户" in prompt
    assert "如果你判断这个组合本身不适合当前任务，或者当前顺序不太对" in prompt
    assert "不要为了顺序完美而放弃完成任务" in prompt
    assert "不要先做大段说明" in prompt
    assert "不要模板化寒暄" in prompt
    assert "把任务最终结果用用户能看懂的方式反馈给用户" in prompt
    assert "第 1 步技能：成员A" in prompt
    assert "想查的主题" in prompt


def test_trial_initially_exposes_only_composition_tool(monkeypatch):
    _seed_published_tool("tool_trial_member", "试用成员")
    composition = _create_composition("试用组合", ["tool_trial_member"])
    _patch_trial_environment(monkeypatch)

    captured = {}
    composition_short_id = DynamicToolManager()._make_short_id(
        composition.composition_id,
        "comp",
    )
    member_short_id = DynamicToolManager()._make_short_id("tool_trial_member", "utool")

    def fake_run(self, session_id, user_input=None, tools=None, system_prompt_override=None):
        tool_defs = tools() if callable(tools) else tools
        captured["tool_names"] = [tool.name for tool in tool_defs]
        captured["session_id"] = session_id
        captured["user_input"] = user_input
        captured["system_prompt"] = system_prompt_override
        return SimpleNamespace(
            result_type=ResultType.NEEDS_USER_INPUT,
            question="请补充任务细节",
            error=None,
        )

    monkeypatch.setattr(skill_composition_service_module.AgentLoop, "run", fake_run)

    start = SkillCompositionService().start_trial_session(composition.composition_id)
    result = SkillCompositionService().continue_trial(
        composition.composition_id,
        start.session_id,
        SkillCompositionService.build_trial_bootstrap_input(),
    )

    assert composition_short_id in captured["tool_names"]
    assert member_short_id not in captured["tool_names"]
    assert captured["user_input"]["role"] == "program"
    assert "第一轮沟通" in captured["user_input"]["content"]
    assert "你必须先直接调用这个技能组合本身" in captured["system_prompt"]
    assert "成员技能只会在技能组合启动后才会出现" in captured["system_prompt"]
    assert result.success is False
    assert result.result_type == ResultType.NEEDS_USER_INPUT.value
    assert result.reply == "请补充任务细节"
    assert result.session_id == captured["session_id"]

    with SessionRepository() as repo:
        session = repo.get_by_id(result.session_id)
        assert session is not None
        assert session.workflow_id == composition.composition_id


def test_continue_trial_exposes_members_after_composition_has_started(monkeypatch):
    _seed_published_tool("tool_continue_member_1", "续跑成员1")
    _seed_published_tool("tool_continue_member_2", "续跑成员2")
    composition = _create_composition(
        "续跑组合",
        ["tool_continue_member_1", "tool_continue_member_2"],
        mode="ordered",
    )
    _patch_trial_environment(monkeypatch)

    session_id = "comptrial_continue"
    composition_short_id = DynamicToolManager()._make_short_id(
        composition.composition_id,
        "comp",
    )
    member_short_ids = {
        DynamicToolManager()._make_short_id("tool_continue_member_1", "utool"),
        DynamicToolManager()._make_short_id("tool_continue_member_2", "utool"),
    }

    with SessionRepository() as session_repo:
        session_repo.create(
            SessionOrm(
                session_id=session_id,
                workflow_id=composition.composition_id,
                agent_type="composition_trial",
                status="suspended",
            )
        )

    with MessageRepository() as message_repo:
        message_repo.create(
            MessageOrm(
                message_id="msg_composition_started",
                session_id=session_id,
                sequence=1,
                role="tool",
                content="技能组合已启动",
                tool_name=composition_short_id,
            )
        )

    captured = {}

    def fake_run(self, session_id, user_input=None, tools=None, system_prompt_override=None):
        tool_defs = tools() if callable(tools) else tools
        captured["tool_names"] = [tool.name for tool in tool_defs]
        with MessageRepository() as message_repo:
            message_repo.create(
                MessageOrm(
                    message_id="msg_composition_reply",
                    session_id=session_id,
                    sequence=message_repo.get_next_sequence(session_id),
                    role="assistant",
                    content="组合试用完成",
                )
            )
        return SimpleNamespace(result_type=ResultType.COMPLETED, error=None)

    monkeypatch.setattr(skill_composition_service_module.AgentLoop, "run", fake_run)

    result = SkillCompositionService().continue_trial(
        composition.composition_id,
        session_id,
        "补充信息",
    )

    assert composition_short_id in captured["tool_names"]
    assert member_short_ids.issubset(set(captured["tool_names"]))
    assert result.success is True
    assert result.reply == "组合试用完成"


def test_continue_trial_uses_saved_session_snapshot_when_live_composition_changes(monkeypatch):
    _seed_published_tool("snapold1_member", "旧成员1", "旧成员1描述")
    _seed_published_tool("snapold2_member", "旧成员2")
    _seed_published_tool("snapnewx_member", "新成员")

    service = SkillCompositionService()
    composition = service.create_composition(
        composition_name="快照组合",
        description="旧版组合",
        applicability="旧版组合适用场景",
        mode="ordered",
        assistant_enabled=True,
        recommend_order=False,
        members=[
            {"tool_id": "snapold1_member", "selected_order": 1, "execution_order": 1},
            {"tool_id": "snapold2_member", "selected_order": 2, "execution_order": 2},
        ],
    )
    snapshot_payload = service._build_trial_session_snapshot_payload(composition)
    _patch_trial_environment(monkeypatch)

    service.update_composition(
        composition_id=composition.composition_id,
        composition_name="快照组合",
        description="新版组合",
        applicability="新版组合适用场景",
        mode="range",
        assistant_enabled=True,
        recommend_order=False,
        members=[{"tool_id": "snapnewx_member", "selected_order": 1}],
    )
    with ToolRepository() as tool_repo:
        old_member = tool_repo.get_by_id("snapold1_member")
        assert old_member is not None
        old_member.tool_name = "旧成员1-线上改版"
        old_member.description = "旧成员1线上改版描述"
        old_member.parameters = [{"name": "city", "description": "线上改版输入"}]
        old_member.execution_code = "print('live-changed')"
        tool_repo.update(old_member)

    session_id = "comptrial_snapshot"
    composition_short_id = DynamicToolManager()._make_short_id(
        composition.composition_id,
        "comp",
    )
    old_member_short_ids = {
        DynamicToolManager()._make_short_id("snapold1_member", "utool"),
        DynamicToolManager()._make_short_id("snapold2_member", "utool"),
    }
    new_member_short_id = DynamicToolManager()._make_short_id("snapnewx_member", "utool")

    with SessionRepository() as session_repo:
        session_repo.create(
            SessionOrm(
                session_id=session_id,
                workflow_id=composition.composition_id,
                agent_type="composition_trial",
                status="suspended",
                tool_ids=json.dumps(snapshot_payload, ensure_ascii=False),
            )
        )
        session = session_repo.get_by_id(session_id)
        assert session is not None

    restored = service._get_trial_session_composition(session)
    assert restored is not None
    assert restored.mode == "ordered"
    assert restored.description == "旧版组合"
    assert restored.applicability == "旧版组合适用场景"
    assert [member.tool_id for member in restored.members] == ["snapold1_member", "snapold2_member"]
    assert [member.selected_order for member in restored.members] == [1, 2]
    assert [member.execution_order for member in restored.members] == [1, 2]
    assert restored.members[0].tool is not None
    assert restored.members[0].tool.tool_name == "旧成员1"
    assert restored.members[0].tool.description == "旧成员1描述"
    assert restored.members[0].tool.parameters == []
    assert restored.members[0].tool.execution_code is None

    with MessageRepository() as message_repo:
        message_repo.create(
            MessageOrm(
                message_id="msg_snapshot_started",
                session_id=session_id,
                sequence=1,
                role="tool",
                content="技能组合已启动",
                tool_name=composition_short_id,
            )
        )

    captured = {}

    def fake_run(self, session_id, user_input=None, tools=None, system_prompt_override=None):
        tool_defs = tools() if callable(tools) else tools
        captured["tool_names"] = [tool.name for tool in tool_defs]
        return SimpleNamespace(
            result_type=ResultType.NEEDS_USER_INPUT,
            question="继续补充信息",
            error=None,
        )

    monkeypatch.setattr(skill_composition_service_module.AgentLoop, "run", fake_run)

    result = service.continue_trial(
        composition.composition_id,
        session_id,
        "继续试用",
    )

    assert composition_short_id in captured["tool_names"]
    assert old_member_short_ids.issubset(set(captured["tool_names"]))
    assert new_member_short_id not in captured["tool_names"]
    assert result.result_type == ResultType.NEEDS_USER_INPUT.value


def test_continue_trial_keeps_members_hidden_until_composition_has_started(monkeypatch):
    _seed_published_tool("tool_continue_hidden", "续跑隐藏成员")
    composition = _create_composition("续跑未启动组合", ["tool_continue_hidden"])
    _patch_trial_environment(monkeypatch)

    session_id = "comptrial_not_started"
    composition_short_id = DynamicToolManager()._make_short_id(
        composition.composition_id,
        "comp",
    )
    member_short_id = DynamicToolManager()._make_short_id("tool_continue_hidden", "utool")

    with SessionRepository() as session_repo:
        session_repo.create(
            SessionOrm(
                session_id=session_id,
                workflow_id=composition.composition_id,
                agent_type="composition_trial",
                status="suspended",
            )
        )

    captured = {}

    def fake_run(self, session_id, user_input=None, tools=None, system_prompt_override=None):
        tool_defs = tools() if callable(tools) else tools
        captured["tool_names"] = [tool.name for tool in tool_defs]
        return SimpleNamespace(
            result_type=ResultType.NEEDS_USER_INPUT,
            question="还需要更多信息",
            error=None,
        )

    monkeypatch.setattr(skill_composition_service_module.AgentLoop, "run", fake_run)

    result = SkillCompositionService().continue_trial(
        composition.composition_id,
        session_id,
        "补充信息",
    )

    assert composition_short_id in captured["tool_names"]
    assert member_short_id not in captured["tool_names"]
    assert result.success is False
    assert result.result_type == ResultType.NEEDS_USER_INPUT.value


def test_continue_trial_rejects_session_from_other_composition():
    _seed_published_tool("tool_session_guard", "会话守卫成员")
    first = _create_composition("会话组合A", ["tool_session_guard"])
    second = _create_composition("会话组合B", ["tool_session_guard"])

    with SessionRepository() as session_repo:
        session_repo.create(
            SessionOrm(
                session_id="comptrial_foreign",
                workflow_id=first.composition_id,
                agent_type="composition_trial",
                status="suspended",
            )
        )

    with pytest.raises(SkillCompositionError, match="不属于当前技能组合"):
        SkillCompositionService().continue_trial(
            second.composition_id,
            "comptrial_foreign",
            "补充信息",
        )


def test_duplicate_composition_name_is_rejected_on_create():
    _seed_published_tool("tool_duplicate_create", "重名成员")
    service = SkillCompositionService()
    service.create_composition(
        composition_name="重名组合",
        description="第一个组合",
        applicability="创建测试",
        mode="range",
        assistant_enabled=True,
        recommend_order=False,
        members=[{"tool_id": "tool_duplicate_create", "selected_order": 1}],
    )

    with pytest.raises(SkillCompositionError, match="技能组合名称已存在"):
        service.create_composition(
            composition_name=" 重名组合 ",
            description="第二个组合",
            applicability="创建测试2",
            mode="range",
            assistant_enabled=True,
            recommend_order=False,
            members=[{"tool_id": "tool_duplicate_create", "selected_order": 1}],
        )


def test_duplicate_composition_name_is_rejected_on_update():
    _seed_published_tool("tool_duplicate_update", "更新重名成员")
    service = SkillCompositionService()
    first = service.create_composition(
        composition_name="组合甲",
        description="第一个组合",
        applicability="更新测试1",
        mode="range",
        assistant_enabled=True,
        recommend_order=False,
        members=[{"tool_id": "tool_duplicate_update", "selected_order": 1}],
    )
    second = service.create_composition(
        composition_name="组合乙",
        description="第二个组合",
        applicability="更新测试2",
        mode="range",
        assistant_enabled=True,
        recommend_order=False,
        members=[{"tool_id": "tool_duplicate_update", "selected_order": 1}],
    )

    with pytest.raises(SkillCompositionError, match="技能组合名称已存在"):
        service.update_composition(
            composition_id=second.composition_id,
            composition_name="组合甲",
            description="第二个组合",
            applicability="更新测试2",
            mode="range",
            assistant_enabled=True,
            recommend_order=False,
            members=[{"tool_id": "tool_duplicate_update", "selected_order": 1}],
        )

    reloaded = service.get_composition(second.composition_id)
    assert reloaded is not None
    assert reloaded.composition_name == "组合乙"
