"""
技能列表 UI 组件

提供技能管理界面，包括：
1. 待考核 / 已掌握 / 失败记录 三个分类 Tab
2. 技能卡片展示（名称、描述、状态、创建时间、考核次数）
3. 操作：考核、删除、编辑名称/描述

卡片 Widget 定义在 src/ui/widgets/skill_cards.py。
"""

from typing import List

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from src.business.services import SkillCompositionError, SkillCompositionService, SkillsService
from src.business.tool_trial.trial_models import PendingTool, PendingToolStatus
from src.data.models import SkillComposition, Tool
from src.data.models_sqlite import TeachingFailureRecord
from src.ui.style_constants import (
    DIVIDER_COLOR,
    HERO_BG_COLOR,
    PRIMARY_COLOR,
    SUBTITLE_COLOR,
    TITLE_COLOR,
)
from src.ui.widgets.layout_utils import clear_layout
from src.ui.widgets.skill_cards import (
    FailureCard,
    PendingToolCard,
    PublishedToolCard,
    SkillCompositionCard,
)
from src.utils.logger import get_logger


class ToolsManagementUI(QWidget):
    """技能列表 UI 组件（带 Tab 切换）"""

    trial_start_request = pyqtSignal(str)
    composition_trial_request = pyqtSignal(str)
    tool_delete_request = pyqtSignal(str)
    tool_update_request = pyqtSignal(str, str, str)
    retry_requested = pyqtSignal(str, str)       # workflow_id, failed_stage
    failure_dismiss_requested = pyqtSignal(str)  # workflow_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger(__name__)
        self._composition_service = SkillCompositionService()
        self.pending_tools: List[PendingTool] = []
        self.pending_tool_cards: List[PendingToolCard] = []
        self.published_tools: List[Tool] = []
        self.published_tool_cards: List[PublishedToolCard] = []
        self.skill_compositions: List[SkillComposition] = []
        self.skill_composition_cards: List[SkillCompositionCard] = []
        self.failure_records: List[TeachingFailureRecord] = []
        self.failure_cards: List[FailureCard] = []
        self.init_ui()

    # =========================================================================
    # UI 初始化
    # =========================================================================

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        content = QWidget()
        content.setStyleSheet("background-color: #ffffff;")
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(0)
        content_layout.setContentsMargins(0, 0, 0, 0)

        content_layout.addWidget(self._build_hero())

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"background-color: {DIVIDER_COLOR}; max-height: 1px;")
        content_layout.addWidget(sep)

        content_layout.addWidget(self._build_tab_bar())
        content_layout.addWidget(self._build_cards_area(), 1)

        main_layout.addWidget(content)

        self._current_tab = "pending"
        self._load_tools()
        self._load_compositions()

    def _build_hero(self) -> QWidget:
        hero = QWidget()
        hero.setStyleSheet(f"background-color: {HERO_BG_COLOR};")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(40, 30, 40, 22)

        title_col = QVBoxLayout()
        title_col.setSpacing(8)

        title = QLabel("技能列表")
        title.setObjectName("tools_title")
        title.setStyleSheet(
            f"font-size: 26px; font-weight: 700; color: {TITLE_COLOR}; background: transparent;"
        )
        title_col.addWidget(title)

        subtitle = QLabel("通过教学习得的技能在这里考核和管理")
        subtitle.setStyleSheet(
            f"font-size: 14px; color: {SUBTITLE_COLOR}; background: transparent;"
        )
        title_col.addWidget(subtitle)

        hero_layout.addLayout(title_col, 1)
        return hero

    def _build_tab_bar(self) -> QWidget:
        self._tab_bar = QWidget()
        self._tab_bar.setStyleSheet("background-color: #ffffff;")
        tab_bar_layout = QHBoxLayout(self._tab_bar)
        tab_bar_layout.setContentsMargins(40, 0, 40, 0)
        tab_bar_layout.setSpacing(0)

        self._pending_tab_btn = self._create_tab_btn("待考核", True)
        self._pending_tab_btn.clicked.connect(lambda: self._switch_tab("pending"))
        tab_bar_layout.addWidget(self._pending_tab_btn)

        self._published_tab_btn = self._create_tab_btn("已掌握", False)
        self._published_tab_btn.clicked.connect(lambda: self._switch_tab("published"))
        tab_bar_layout.addWidget(self._published_tab_btn)

        self._compositions_tab_btn = self._create_tab_btn("技能组合", False)
        self._compositions_tab_btn.clicked.connect(lambda: self._switch_tab("compositions"))
        tab_bar_layout.addWidget(self._compositions_tab_btn)

        tab_bar_layout.addSpacing(8)

        self._failures_tab_btn = self._create_tab_btn("失败记录", False)
        self._failures_tab_btn.clicked.connect(lambda: self._switch_tab("failures"))
        tab_bar_layout.addWidget(self._failures_tab_btn)

        tab_bar_layout.addStretch()

        self._create_composition_btn = QPushButton("新建技能组合")
        self._create_composition_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._create_composition_btn.setVisible(False)
        self._create_composition_btn.clicked.connect(self._on_create_composition_clicked)
        self._create_composition_btn.setStyleSheet(
            f"""
            QPushButton {{
                min-height: 34px;
                padding: 0 16px;
                font-size: 13px;
                font-weight: 600;
                color: #ffffff;
                background-color: {PRIMARY_COLOR};
                border: none;
                border-radius: 17px;
            }}
            QPushButton:hover {{
                background-color: #4d5bb0;
            }}
            """
        )
        tab_bar_layout.addWidget(self._create_composition_btn)
        return self._tab_bar

    def _build_cards_area(self) -> QWidget:
        self._cards_area = QWidget()
        self._cards_area.setStyleSheet("background-color: #ffffff;")
        cards_layout = QVBoxLayout(self._cards_area)
        cards_layout.setContentsMargins(40, 24, 40, 24)
        cards_layout.setSpacing(0)

        self._pending_scroll = self._create_scroll_area()
        self._pending_scroll_content = QWidget()
        self.pending_tools_grid = QGridLayout(self._pending_scroll_content)
        self.pending_tools_grid.setSpacing(14)
        self.pending_tools_grid.setContentsMargins(0, 0, 0, 0)
        self.pending_tools_grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._pending_scroll.setWidget(self._pending_scroll_content)
        cards_layout.addWidget(self._pending_scroll)

        self.pending_empty_label = self._create_empty_label(
            "暂无待考核技能\n\n完成技能教学后，生成的技能会显示在这里"
        )
        cards_layout.addWidget(self.pending_empty_label)

        self._published_scroll = self._create_scroll_area()
        self._published_scroll.setVisible(False)
        self._published_scroll_content = QWidget()
        self.published_tools_grid = QGridLayout(self._published_scroll_content)
        self.published_tools_grid.setSpacing(14)
        self.published_tools_grid.setContentsMargins(0, 0, 0, 0)
        self.published_tools_grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._published_scroll.setWidget(self._published_scroll_content)
        cards_layout.addWidget(self._published_scroll)

        self.published_empty_label = self._create_empty_label(
            "暂无已掌握技能\n\n考核通过的技能会显示在这里"
        )
        self.published_empty_label.setVisible(False)
        cards_layout.addWidget(self.published_empty_label)

        self._compositions_scroll = self._create_scroll_area()
        self._compositions_scroll.setVisible(False)
        self._compositions_scroll_content = QWidget()
        self.skill_compositions_grid = QGridLayout(self._compositions_scroll_content)
        self.skill_compositions_grid.setSpacing(14)
        self.skill_compositions_grid.setContentsMargins(0, 0, 0, 0)
        self.skill_compositions_grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._compositions_scroll.setWidget(self._compositions_scroll_content)
        cards_layout.addWidget(self._compositions_scroll)

        self.compositions_empty_state = self._create_compositions_empty_state()
        self.compositions_empty_state.setVisible(False)
        cards_layout.addWidget(self.compositions_empty_state)

        self._failures_scroll = self._create_scroll_area()
        self._failures_scroll.setVisible(False)
        self._failures_scroll_content = QWidget()
        self.failures_grid = QGridLayout(self._failures_scroll_content)
        self.failures_grid.setSpacing(14)
        self.failures_grid.setContentsMargins(0, 0, 0, 0)
        self.failures_grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._failures_scroll.setWidget(self._failures_scroll_content)
        cards_layout.addWidget(self._failures_scroll)

        self.failures_empty_label = self._create_empty_label(
            "暂无失败记录\n\n教学流程中的异常会自动记录在这里"
        )
        self.failures_empty_label.setVisible(False)
        cards_layout.addWidget(self.failures_empty_label)

        return self._cards_area

    # =========================================================================
    # Tab 切换
    # =========================================================================

    def _create_tab_btn(self, text: str, active: bool) -> QPushButton:
        btn = QPushButton(text)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFixedHeight(44)
        btn.setMinimumWidth(100)
        self._apply_tab_style(btn, active)
        return btn

    @staticmethod
    def _apply_tab_style(btn: QPushButton, active: bool):
        if active:
            btn.setStyleSheet(
                f"""
                QPushButton {{
                    font-size: 14px; font-weight: 600; color: {PRIMARY_COLOR};
                    background: transparent; border: none;
                    border-bottom: 2.5px solid {PRIMARY_COLOR};
                    padding: 0 20px;
                }}
                """
            )
        else:
            btn.setStyleSheet(
                f"""
                QPushButton {{
                    font-size: 14px; font-weight: 500; color: #868e96;
                    background: transparent; border: none;
                    border-bottom: 2.5px solid transparent;
                    padding: 0 20px;
                }}
                QPushButton:hover {{ color: {PRIMARY_COLOR}; }}
                """
            )

    def _switch_tab(self, tab: str):
        self._current_tab = tab

        self._pending_scroll.setVisible(tab == "pending")
        self.pending_empty_label.setVisible(tab == "pending" and len(self.pending_tools) == 0)

        self._published_scroll.setVisible(tab == "published")
        self.published_empty_label.setVisible(
            tab == "published" and len(self.published_tools) == 0
        )

        self._create_composition_btn.setVisible(
            tab == "compositions" and len(self.skill_compositions) > 0
        )
        self._compositions_scroll.setVisible(tab == "compositions")
        self.compositions_empty_state.setVisible(
            tab == "compositions" and len(self.skill_compositions) == 0
        )

        self._failures_scroll.setVisible(tab == "failures")
        self.failures_empty_label.setVisible(
            tab == "failures" and len(self.failure_records) == 0
        )

        self._apply_tab_style(self._pending_tab_btn, tab == "pending")
        self._apply_tab_style(self._published_tab_btn, tab == "published")
        self._apply_tab_style(self._compositions_tab_btn, tab == "compositions")
        self._apply_tab_style(self._failures_tab_btn, tab == "failures")

        if tab == "failures":
            self._load_failures()

    # =========================================================================
    # 辅助创建
    # =========================================================================

    @staticmethod
    def _create_scroll_area() -> QScrollArea:
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setFrameShape(QScrollArea.Shape.NoFrame)
        sa.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        sa.setStyleSheet("QScrollArea { border: none; background: transparent; }")
        return sa

    @staticmethod
    def _create_empty_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet(
            "font-size: 14px; color: #adb5bd; background: transparent; padding: 60px 0;"
        )
        lbl.setVisible(False)
        return lbl

    def _create_compositions_empty_state(self) -> QWidget:
        state = QWidget()
        layout = QVBoxLayout(state)
        layout.setContentsMargins(0, 60, 0, 60)
        layout.setSpacing(14)

        label = QLabel("暂无技能组合\n\n创建后可以把多个技能组织成更大的能力单元")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("font-size: 14px; color: #adb5bd; background: transparent;")
        layout.addWidget(label)

        self._empty_create_composition_btn = QPushButton("新建技能组合")
        self._empty_create_composition_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._empty_create_composition_btn.clicked.connect(self._on_create_composition_clicked)
        self._empty_create_composition_btn.setStyleSheet(
            f"""
            QPushButton {{
                min-height: 38px;
                padding: 0 18px;
                font-size: 13px;
                font-weight: 600;
                color: #ffffff;
                background-color: {PRIMARY_COLOR};
                border: none;
                border-radius: 19px;
            }}
            QPushButton:hover {{
                background-color: #4d5bb0;
            }}
            """
        )
        layout.addWidget(self._empty_create_composition_btn, 0, Qt.AlignmentFlag.AlignHCenter)
        return state

    # =========================================================================
    # 数据加载
    # =========================================================================

    def refresh(self):
        """公开刷新方法（供外部调用，如页面切换时）"""
        self._load_tools()
        self._load_compositions()
        self._load_failures()

    def refresh_failures(self):
        """仅刷新失败记录"""
        self._load_failures()

    def _load_tools(self):
        try:
            pending_tools_list, published_tools_list = SkillsService().get_tools()
            self.update_pending_tools(pending_tools_list)
            self.update_published_tools(published_tools_list)
            self.logger.info(
                f"从数据库加载技能: {len(pending_tools_list)} 个待考核, "
                f"{len(published_tools_list)} 个已掌握"
            )
        except Exception as e:
            self.logger.error(f"从数据库加载技能失败: {e}", exc_info=True)
            self.update_pending_tools([])
            self.update_published_tools([])

    def _load_compositions(self):
        try:
            compositions = self._composition_service.list_compositions()
            self.update_skill_compositions(compositions)
        except Exception as e:
            self.logger.error(f"加载技能组合失败: {e}", exc_info=True)
            self.update_skill_compositions([])

    def _load_failures(self):
        try:
            records = SkillsService().get_active_failures()
            self.update_failure_records(records)
        except Exception as e:
            self.logger.error(f"加载失败记录失败: {e}", exc_info=True)
            self.update_failure_records([])

    # =========================================================================
    # 列表更新
    # =========================================================================

    def update_pending_tools(self, pending_tools: List[PendingTool]):
        self.pending_tools = pending_tools
        clear_layout(self.pending_tools_grid)
        self.pending_tool_cards.clear()

        self._pending_tab_btn.setText(f"待考核 ({len(pending_tools)})")
        self.pending_empty_label.setVisible(
            len(pending_tools) == 0 and self._current_tab == "pending"
        )

        for i, tool in enumerate(pending_tools):
            card = PendingToolCard(tool)
            card.trial_requested.connect(self._on_trial_requested)
            card.delete_requested.connect(self._on_delete_requested)
            card.edit_requested.connect(self._on_edit_requested)
            self.pending_tools_grid.addWidget(card, i // 3, i % 3)
            self.pending_tool_cards.append(card)

        for col in range(3):
            self.pending_tools_grid.setColumnStretch(col, 1)

    def update_published_tools(self, published_tools: List[Tool]):
        self.published_tools = published_tools
        clear_layout(self.published_tools_grid)
        self.published_tool_cards.clear()

        self._published_tab_btn.setText(f"已掌握 ({len(published_tools)})")
        self.published_empty_label.setVisible(
            len(published_tools) == 0 and self._current_tab == "published"
        )

        for i, tool in enumerate(published_tools):
            card = PublishedToolCard(tool)
            card.execute_requested.connect(self._on_execute_requested)
            card.delete_requested.connect(self._on_published_delete_requested)
            card.edit_requested.connect(self._on_published_edit_requested)
            self.published_tools_grid.addWidget(card, i // 3, i % 3)
            self.published_tool_cards.append(card)

        for col in range(3):
            self.published_tools_grid.setColumnStretch(col, 1)

    def update_skill_compositions(self, compositions: List[SkillComposition]):
        self.skill_compositions = compositions
        clear_layout(self.skill_compositions_grid)
        self.skill_composition_cards.clear()

        self._compositions_tab_btn.setText(f"技能组合 ({len(compositions)})")
        self.compositions_empty_state.setVisible(
            len(compositions) == 0 and self._current_tab == "compositions"
        )

        for i, composition in enumerate(compositions):
            card = SkillCompositionCard(composition)
            card.test_requested.connect(self._on_composition_test_requested)
            card.publish_requested.connect(self._on_composition_publish_requested)
            card.offline_requested.connect(self._on_composition_offline_requested)
            card.delete_requested.connect(self._on_composition_delete_requested)
            card.edit_requested.connect(self._on_composition_edit_requested)
            self.skill_compositions_grid.addWidget(card, i // 3, i % 3)
            self.skill_composition_cards.append(card)

        for col in range(3):
            self.skill_compositions_grid.setColumnStretch(col, 1)

    def update_failure_records(self, failure_records: List[TeachingFailureRecord]):
        self.failure_records = failure_records
        clear_layout(self.failures_grid)
        self.failure_cards.clear()

        self._failures_tab_btn.setText(f"失败记录 ({len(failure_records)})")
        self.failures_empty_label.setVisible(
            len(failure_records) == 0 and self._current_tab == "failures"
        )

        for i, record in enumerate(failure_records):
            card = FailureCard(record)
            card.retry_requested.connect(self.retry_requested.emit)
            card.dismiss_requested.connect(self.failure_dismiss_requested.emit)
            self.failures_grid.addWidget(card, i // 3, i % 3)
            self.failure_cards.append(card)

        for col in range(3):
            self.failures_grid.setColumnStretch(col, 1)

    # =========================================================================
    # 事件处理 — 待考核
    # =========================================================================

    def _on_trial_requested(self, pending_tool_id: str):
        self.logger.info(f"考核技能: {pending_tool_id}")
        self.trial_start_request.emit(pending_tool_id)
        for tool in self.pending_tools:
            if tool.pending_tool_id == pending_tool_id:
                tool.status = PendingToolStatus.TRIALING
                break
        self._refresh_pending_cards()

    def _on_delete_requested(self, pending_tool_id: str):
        self.logger.info(f"删除待考核技能: {pending_tool_id}")
        reply = QMessageBox.question(
            self,
            "确认删除",
            "确定要删除这个技能吗？\n\n此操作不可恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                SkillsService().delete_tool(pending_tool_id)
                self.pending_tools = [
                    t for t in self.pending_tools if t.pending_tool_id != pending_tool_id
                ]
                self._refresh_pending_cards()
                self._load_compositions()
            except Exception as e:
                QMessageBox.warning(self, "删除失败", str(e))

    def _on_edit_requested(self, pending_tool_id: str):
        self.logger.info(f"编辑待考核技能: {pending_tool_id}")
        tool = next(
            (t for t in self.pending_tools if t.pending_tool_id == pending_tool_id), None
        )
        if not tool:
            return
        name, ok = QInputDialog.getText(self, "编辑技能名称", "技能名称:", text=tool.tool_name)
        if ok and name:
            desc, ok = QInputDialog.getText(
                self, "编辑技能描述", "技能描述:", text=tool.tool_description or ""
            )
            if ok:
                try:
                    referenced = SkillsService().update_tool_metadata(pending_tool_id, name, desc)
                    tool.tool_name = name
                    tool.tool_description = desc
                    self._refresh_pending_cards()
                    self._load_compositions()
                    if referenced:
                        QMessageBox.information(
                            self,
                            "已更新技能",
                            "该技能已同步改名，引用它的技能组合：\n" + "\n".join(referenced),
                        )
                except Exception as e:
                    QMessageBox.warning(self, "更新失败", str(e))

    def _refresh_pending_cards(self):
        self.update_pending_tools(self.pending_tools)

    # =========================================================================
    # 事件处理 — 已掌握
    # =========================================================================

    def _on_execute_requested(self, tool_id: str):
        self.logger.info(f"执行已掌握技能: {tool_id}")
        tool = next((t for t in self.published_tools if t.tool_id == tool_id), None)
        if not tool:
            self.logger.error(f"未找到技能: {tool_id}")
            QMessageBox.warning(self, "技能未找到", f"未找到技能 ID: {tool_id}")
            return

        from src.ui.tool_execution_dialog import ExecutionResultDialog, ToolExecutionDialog
        from src.ui.tool_execution_thread import ToolExecutionProgressDialog, ToolExecutionThread

        dialog = ToolExecutionDialog(tool, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            parameters = dialog.get_parameters()
            self.logger.info(f"开始执行技能: {tool.tool_name}, 参数: {parameters}")
            execution_thread = ToolExecutionThread(tool, parameters)
            progress_dialog = ToolExecutionProgressDialog(tool.tool_name, self)
            progress_dialog.set_execution_thread(execution_thread)
            progress_dialog.exec()
            success, exec_result, error = progress_dialog.get_result()
            ExecutionResultDialog(
                tool_name=tool.tool_name,
                success=success,
                result=exec_result,
                error=error,
                parent=self,
            ).exec()

    def _on_published_delete_requested(self, tool_id: str):
        self.logger.info(f"删除已掌握技能: {tool_id}")
        reply = QMessageBox.question(
            self,
            "确认删除",
            "确定要删除这个技能吗？\n\n此操作不可恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                SkillsService().delete_tool(tool_id)
                self.published_tools = [t for t in self.published_tools if t.tool_id != tool_id]
                self._refresh_published_cards()
                self._load_compositions()
            except Exception as e:
                QMessageBox.warning(self, "删除失败", str(e))

    def _on_published_edit_requested(self, tool_id: str):
        self.logger.info(f"编辑已掌握技能: {tool_id}")
        tool = next((t for t in self.published_tools if t.tool_id == tool_id), None)
        if not tool:
            return
        name, ok = QInputDialog.getText(self, "编辑技能名称", "技能名称:", text=tool.tool_name)
        if ok and name:
            desc, ok = QInputDialog.getText(
                self, "编辑技能描述", "技能描述:", text=tool.description or ""
            )
            if ok:
                try:
                    referenced = SkillsService().update_tool_metadata(tool_id, name, desc)
                    tool.tool_name = name
                    tool.description = desc
                    self._refresh_published_cards()
                    self._load_compositions()
                    if referenced:
                        QMessageBox.information(
                            self,
                            "已更新技能",
                            "该技能已同步改名，引用它的技能组合：\n" + "\n".join(referenced),
                        )
                except Exception as e:
                    QMessageBox.warning(self, "更新失败", str(e))

    def _refresh_published_cards(self):
        self.update_published_tools(self.published_tools)

    # =========================================================================
    # 事件处理 — 技能组合
    # =========================================================================

    def _on_create_composition_clicked(self):
        from src.ui.skill_composition_dialogs import SkillCompositionEditDialog

        dialog = SkillCompositionEditDialog(parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        payload = dialog.get_payload()
        try:
            self._composition_service.create_composition(**payload)
            self._load_compositions()
        except SkillCompositionError as e:
            QMessageBox.warning(self, "创建失败", str(e))
        except Exception as e:
            self.logger.error(f"创建技能组合失败: {e}", exc_info=True)
            QMessageBox.warning(self, "创建失败", str(e))

    def _on_composition_edit_requested(self, composition_id: str):
        from src.ui.skill_composition_dialogs import SkillCompositionEditDialog

        composition = next(
            (item for item in self.skill_compositions if item.composition_id == composition_id),
            None,
        )
        if composition is None:
            QMessageBox.warning(self, "技能组合未找到", "请刷新后重试")
            return

        dialog = SkillCompositionEditDialog(composition=composition, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

        payload = dialog.get_payload()
        try:
            self._composition_service.update_composition(composition_id=composition_id, **payload)
            self._load_compositions()
        except SkillCompositionError as e:
            QMessageBox.warning(self, "保存失败", str(e))
        except Exception as e:
            self.logger.error(f"更新技能组合失败: {e}", exc_info=True)
            QMessageBox.warning(self, "保存失败", str(e))

    def _on_composition_test_requested(self, composition_id: str):
        self.composition_trial_request.emit(composition_id)

    def _on_composition_publish_requested(self, composition_id: str):
        try:
            self._composition_service.publish_composition(composition_id)
            self._load_compositions()
        except SkillCompositionError as e:
            QMessageBox.warning(self, "发布失败", str(e))
        except Exception as e:
            self.logger.error(f"发布技能组合失败: {e}", exc_info=True)
            QMessageBox.warning(self, "发布失败", str(e))

    def _on_composition_offline_requested(self, composition_id: str):
        reply = QMessageBox.question(
            self,
            "确认下线",
            "下线后组合将不再对 Assistant 可用，但仍可试一下和重新发布。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            self._composition_service.offline_composition(composition_id)
            self._load_compositions()
        except SkillCompositionError as e:
            QMessageBox.warning(self, "下线失败", str(e))
        except Exception as e:
            self.logger.error(f"下线技能组合失败: {e}", exc_info=True)
            QMessageBox.warning(self, "下线失败", str(e))

    def _on_composition_delete_requested(self, composition_id: str):
        reply = QMessageBox.question(
            self,
            "确认删除",
            "确定要删除这个技能组合吗？\n\n此操作不可恢复。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            self._composition_service.delete_composition(composition_id)
            self._load_compositions()
        except SkillCompositionError as e:
            QMessageBox.warning(self, "删除失败", str(e))
        except Exception as e:
            self.logger.error(f"删除技能组合失败: {e}", exc_info=True)
            QMessageBox.warning(self, "删除失败", str(e))
