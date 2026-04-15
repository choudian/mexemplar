"""
技能组合相关对话框与执行线程
"""

from typing import Any, Dict, List, Optional

from PyQt6.QtCore import QEvent, QPoint, QSize, Qt, QMutex, QMutexLocker, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from src.business.agents.config import ResultType
from src.business.services import SkillCompositionError, SkillCompositionService
from src.data.models import SkillComposition, sort_composition_members
from src.ui.style_constants import DIVIDER_COLOR, HERO_BG_COLOR, PRIMARY_COLOR, SUBTITLE_COLOR, TITLE_COLOR
from src.utils.logger import get_logger


COMPOSITION_MODE_CHEVRON_DATA_URI = (
    "data:image/svg+xml;base64,"
    "PHN2ZyB3aWR0aD0iMTIiIGhlaWdodD0iMTIiIHZpZXdCb3g9IjAgMCAxMiAxMiIgZmlsbD0ibm9uZSIg"
    "eG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cGF0aCBkPSJNMyA0LjVMNiA3LjVMOSA0"
    "LjUiIHN0cm9rZT0iIzRmNWQ5NSIgc3Ryb2tlLXdpZHRoPSIxLjgiIHN0cm9rZS1saW5lY2FwPSJyb3Vu"
    "ZCIgc3Ryb2tlLWxpbmVqb2luPSJyb3VuZCIvPjwvc3ZnPg=="
)


class _DraggableButtonHelper:
    """可拖拽悬浮按钮的通用逻辑（位置计算、拖拽检测、边界钳位）。"""

    def __init__(self, button: QPushButton, container: QWidget, margin_x: int = 10, margin_y: int = 8, margin_right: Optional[int] = None, margin_bottom: Optional[int] = None):
        self.button = button
        self.container = container
        self._margin_x = margin_x
        self._margin_y = margin_y
        self._margin_right = margin_right if margin_right is not None else margin_x
        self._margin_bottom = margin_bottom if margin_bottom is not None else max(10, margin_y)
        self._drag_origin: Optional[QPoint] = None
        self._button_origin = QPoint()
        self._dragging = False
        self._button_pos: Optional[QPoint] = None

    def bounds(self) -> tuple[int, int, int, int]:
        left = self._margin_x
        top = self._margin_y
        width = max(0, self.container.width() - self._margin_x - self._margin_right)
        height = max(0, self.container.height() - self._margin_y - self._margin_bottom)
        return left, top, width, height

    def default_position(self) -> QPoint:
        left, top, width, _ = self.bounds()
        x = left + max(0, width - self.button.width())
        return QPoint(x, top)

    def clamp(self, pos: QPoint) -> QPoint:
        left, top, width, height = self.bounds()
        max_x = left + max(0, width - self.button.width())
        max_y = top + max(0, height - self.button.height())
        return QPoint(
            min(max(pos.x(), left), max_x),
            min(max(pos.y(), top), max_y),
        )

    def set_position(self, pos: QPoint) -> None:
        self._button_pos = self.clamp(pos)
        self.button.move(self._button_pos)
        self.button.raise_()

    def update_overlay(self) -> None:
        self.button.resize(self.button.sizeHint())
        target = self._button_pos if self._button_pos is not None else self.default_position()
        self.set_position(target)

    def handle_event(self, watched, event) -> Optional[bool]:
        """处理按钮的鼠标事件。返回 True 表示事件已消费，None 表示未处理。"""
        if watched is not self.button:
            return None
        if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            self._drag_origin = event.globalPosition().toPoint()
            self._button_origin = self.button.pos()
            self._dragging = False
        elif (
            event.type() == QEvent.Type.MouseMove
            and self._drag_origin is not None
            and event.buttons() & Qt.MouseButton.LeftButton
        ):
            delta = event.globalPosition().toPoint() - self._drag_origin
            if not self._dragging and delta.manhattanLength() < 4:
                return False
            self._dragging = True
            self.set_position(self._button_origin + delta)
            return True
        elif event.type() == QEvent.Type.MouseButtonRelease and self._drag_origin is not None:
            was_dragging = self._dragging
            self._drag_origin = None
            self._dragging = False
            if was_dragging:
                return True
        return None


class _FloatingCornerField(QWidget):
    """让按钮悬浮在输入区域内，并允许在区域内拖动。"""

    def __init__(self, editor: QTextEdit, action_button: QPushButton, parent=None):
        super().__init__(parent)
        self.editor = editor
        self._dragger: Optional[_DraggableButtonHelper] = None

        self.panel = QFrame(self)
        self.panel.setObjectName("inline_text_panel")
        panel_layout = QVBoxLayout(self.panel)
        panel_layout.setContentsMargins(10, 8, 10, 10)
        panel_layout.setSpacing(0)
        panel_layout.addWidget(self.editor)

        action_button.setParent(self.panel)
        self._dragger = _DraggableButtonHelper(action_button, self.panel)
        action_button.installEventFilter(self)
        action_button.setToolTip("点击生成；也可以拖动按钮位置")
        action_button.raise_()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.panel.setGeometry(self.rect())
        if self._dragger is not None:
            self._dragger.update_overlay()

    def eventFilter(self, watched, event) -> bool:
        if self._dragger is None:
            return super().eventFilter(watched, event)
        result = self._dragger.handle_event(watched, event)
        if result is not None:
            return result
        return super().eventFilter(watched, event)

    def sizeHint(self) -> QSize:
        return self.panel.sizeHint()

    def minimumSizeHint(self) -> QSize:
        return self.panel.minimumSizeHint()

    # Compatibility wrappers kept for existing UI regression tests.
    def _button_bounds(self) -> tuple[int, int, int, int]:
        if self._dragger is None:
            return (0, 0, 0, 0)
        return self._dragger.bounds()

    def _set_button_position(self, pos: QPoint) -> None:
        if self._dragger is None:
            return
        self._dragger.set_position(pos)


class ApplicabilityGenerationThread(QThread):
    """后台生成适用场景，避免阻塞表单主线程。"""

    finished_signal = pyqtSignal(bool, str, str)

    def __init__(
        self,
        composition_name: str,
        description: str,
        mode: str,
        members: List[dict],
    ):
        super().__init__()
        self.logger = get_logger(__name__)
        self.composition_name = composition_name
        self.description = description
        self.mode = mode
        self.members = [dict(member) for member in members]

    def run(self) -> None:
        try:
            generated = SkillCompositionService().generate_applicability(
                composition_name=self.composition_name,
                description=self.description,
                mode=self.mode,
                members=self.members,
            )
        except SkillCompositionError as e:
            self.finished_signal.emit(False, "", str(e))
            return
        except Exception as e:
            self.logger.error(f"生成适用场景失败: {e}", exc_info=True)
            self.finished_signal.emit(False, "", str(e))
            return

        self.finished_signal.emit(True, generated, "")


class RecommendationGenerationThread(QThread):
    """后台生成推荐顺序，避免阻塞表单主线程。"""

    finished_signal = pyqtSignal(bool, object, str)

    def __init__(
        self,
        composition_name: str,
        description: str,
        applicability: str,
        members: List[dict],
    ):
        super().__init__()
        self.logger = get_logger(__name__)
        self.composition_name = composition_name
        self.description = description
        self.applicability = applicability
        self.members = [dict(member) for member in members]

    def run(self) -> None:
        try:
            result = SkillCompositionService().recommend_execution_order(
                composition_name=self.composition_name,
                description=self.description,
                applicability=self.applicability,
                members=self.members,
            )
        except SkillCompositionError as e:
            self.finished_signal.emit(False, None, str(e))
            return
        except Exception as e:
            self.logger.error(f"生成推荐顺序失败: {e}", exc_info=True)
            self.finished_signal.emit(False, None, str(e))
            return

        self.finished_signal.emit(True, result, "")


class SkillCompositionEditDialog(QDialog):
    """技能组合创建/编辑对话框"""

    def __init__(self, composition: Optional[SkillComposition] = None, parent=None):
        super().__init__(parent)
        self.logger = get_logger(__name__)
        self.service = SkillCompositionService()
        self.composition = composition
        self.available_tools = self.service.get_published_tool_choices()
        self.tool_map = {tool.tool_id: tool for tool in self.available_tools}
        self.selected_tool_ids: List[str] = []
        self.selection_order_map: Dict[str, int] = {}
        self._syncing_checks = False
        self._recommend_dragger: Optional[_DraggableButtonHelper] = None
        self._applicability_generation_thread: Optional[ApplicabilityGenerationThread] = None
        self._is_generating_applicability = False
        self._recommendation_generation_thread: Optional[RecommendationGenerationThread] = None
        self._is_generating_recommendation = False
        self._init_from_composition()
        self._init_ui()
        self._populate_available_tools()
        self._refresh_selected_tools()

    def _init_from_composition(self) -> None:
        if not self.composition:
            return
        for member in self.composition.members:
            self.selection_order_map[member.tool_id] = member.selected_order
        ordered_members = sort_composition_members(
            self.composition.members, self.composition.mode
        )
        self.selected_tool_ids = [member.tool_id for member in ordered_members]

    def _init_ui(self) -> None:
        self.setWindowTitle("编辑技能组合" if self.composition else "新建技能组合")
        self.setMinimumSize(960, 760)
        self.setStyleSheet(
            f"""
            QDialog {{
                background-color: {HERO_BG_COLOR};
            }}
            QFrame#composition_section {{
                background-color: #ffffff;
                border: 1px solid {DIVIDER_COLOR};
                border-radius: 12px;
            }}
            QFrame#inline_text_panel {{
                background-color: #ffffff;
                border: 1px solid {DIVIDER_COLOR};
                border-radius: 10px;
            }}
            QLineEdit, QListWidget, QTextEdit {{
                background-color: #ffffff;
                border: 1px solid {DIVIDER_COLOR};
                border-radius: 8px;
                padding: 6px 8px;
            }}
            QListWidget::item {{
                padding: 6px 8px;
            }}
            QComboBox#composition_mode_combo {{
                min-height: 36px;
                padding: 0 34px 0 12px;
                color: {TITLE_COLOR};
                background-color: #fbfcff;
                border: 1px solid #d7def5;
                border-radius: 10px;
                font-size: 13px;
                font-weight: 600;
            }}
            QComboBox#composition_mode_combo:hover {{
                background-color: #f4f7ff;
                border-color: #bcc9f5;
            }}
            QComboBox#composition_mode_combo:focus {{
                background-color: #ffffff;
                border: 1px solid {PRIMARY_COLOR};
            }}
            QComboBox#composition_mode_combo::drop-down {{
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 28px;
                border: none;
                margin-right: 6px;
            }}
            QComboBox#composition_mode_combo::down-arrow {{
                image: url({COMPOSITION_MODE_CHEVRON_DATA_URI});
                width: 12px;
                height: 12px;
            }}
            QComboBox#composition_mode_combo QAbstractItemView {{
                background-color: #ffffff;
                color: {TITLE_COLOR};
                border: 1px solid #d7def5;
                border-radius: 10px;
                outline: 0;
                padding: 4px;
                selection-background-color: #eef2ff;
                selection-color: {TITLE_COLOR};
            }}
            QPushButton#secondary_action {{
                font-size: 12px;
                font-weight: 600;
                color: {PRIMARY_COLOR};
                background-color: #f0f1ff;
                border: 1px solid #d6dcff;
                border-radius: 7px;
                padding: 6px 12px;
            }}
            QPushButton#secondary_action:hover {{
                background-color: #e6eaff;
            }}
            QPushButton#primary_action {{
                font-size: 13px;
                font-weight: 600;
                color: #ffffff;
                background-color: {PRIMARY_COLOR};
                border: none;
                border-radius: 8px;
                padding: 8px 18px;
            }}
            QPushButton#primary_action:hover {{
                background-color: #4d5bb0;
            }}
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(16)

        blueprint_card = QFrame()
        blueprint_card.setObjectName("composition_section")
        blueprint_layout = QVBoxLayout(blueprint_card)
        blueprint_layout.setContentsMargins(18, 18, 18, 18)
        blueprint_layout.setSpacing(14)
        blueprint_layout.addWidget(
            self._build_section_header(
                "Step 1",
                "先组装能力骨架",
                "先确定组合模式、勾选成员技能并整理当前顺序，再补名称和适用场景。",
            )
        )

        mode_row = QWidget()
        mode_layout = QHBoxLayout(mode_row)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.setSpacing(10)

        mode_label = QLabel("组合模式")
        mode_label.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {TITLE_COLOR};")
        mode_layout.addWidget(mode_label)

        self.mode_combo = QComboBox()
        self.mode_combo.setObjectName("composition_mode_combo")
        self.mode_combo.addItem("范围型", "range")
        self.mode_combo.addItem("顺序型", "ordered")
        if self.composition:
            index = self.mode_combo.findData(self.composition.mode)
            if index >= 0:
                self.mode_combo.setCurrentIndex(index)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        self.mode_combo.setMinimumWidth(180)
        mode_layout.addWidget(self.mode_combo)
        mode_layout.addStretch()
        blueprint_layout.addWidget(mode_row)

        self.member_summary_label = QLabel()
        self.member_summary_label.setWordWrap(True)
        self.member_summary_label.setStyleSheet(f"font-size: 12px; color: {SUBTITLE_COLOR};")
        blueprint_layout.addWidget(self.member_summary_label)

        member_layout = QGridLayout()
        member_layout.setHorizontalSpacing(14)
        member_layout.setVerticalSpacing(8)

        self.member_overlay_panel = QWidget()
        member_panel_layout = QVBoxLayout(self.member_overlay_panel)
        member_panel_layout.setContentsMargins(0, 0, 0, 0)
        member_panel_layout.setSpacing(8)
        member_layout.addWidget(self.member_overlay_panel, 0, 0)

        member_header = QWidget()
        member_header_layout = QHBoxLayout(member_header)
        member_header_layout.setContentsMargins(0, 0, 0, 0)
        member_header_layout.setSpacing(8)
        member_label = QLabel("成员技能")
        member_label.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {TITLE_COLOR};")
        member_header_layout.addWidget(member_label)
        self.recommend_now_button = QPushButton("推荐顺序")
        self.recommend_now_button.setObjectName("secondary_action")
        self.recommend_now_button.clicked.connect(self._generate_recommendation)
        member_header_layout.addStretch()
        member_panel_layout.addWidget(member_header)

        self.member_hint_label = QLabel()
        self.member_hint_label.setWordWrap(True)
        self.member_hint_label.setStyleSheet(f"font-size: 12px; color: {SUBTITLE_COLOR};")
        member_panel_layout.addWidget(self.member_hint_label)

        self.available_list = QListWidget()
        self.available_list.itemChanged.connect(self._on_available_item_changed)
        self.available_list.setMinimumHeight(220)
        self.available_list.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self.available_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.available_list.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.available_list.setAcceptDrops(True)
        self.available_list.setDropIndicatorShown(True)
        self.available_list.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.available_list.model().rowsMoved.connect(self._on_selected_rows_moved)
        self.available_list.installEventFilter(self)
        self.available_list.viewport().installEventFilter(self)
        self.recommend_now_button.setParent(self.available_list)
        self.recommend_now_button.installEventFilter(self)
        self.recommend_now_button.raise_()
        self._recommend_dragger = _DraggableButtonHelper(
            self.recommend_now_button, self.available_list,
            margin_right=12, margin_bottom=42,
        )
        member_panel_layout.addWidget(self.available_list)
        member_layout.setColumnStretch(0, 1)
        blueprint_layout.addLayout(member_layout)
        root.addWidget(blueprint_card, 1)

        details_card = QFrame()
        details_card.setObjectName("composition_section")
        details_layout = QVBoxLayout(details_card)
        details_layout.setContentsMargins(18, 18, 18, 18)
        details_layout.setSpacing(14)
        details_layout.addWidget(
            self._build_section_header(
                "Step 2",
                "再补充基础信息",
                "选好技能后，再填写组合名称、描述和适用场景。适用场景支持一键生成后继续手动修改。",
            )
        )

        form = QFormLayout()
        form.setSpacing(10)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)

        self.name_input = QLineEdit(self.composition.composition_name if self.composition else "")
        self.name_input.setPlaceholderText("例如：多站点资料采集与整理")
        form.addRow("名称", self.name_input)

        self.description_input = QTextEdit(self.composition.description or "" if self.composition else "")
        self.description_input.setPlaceholderText("可选。补充这个组合的工作思路、边界或输出预期。")
        self.description_input.setTabChangesFocus(True)
        self.description_input.setMaximumHeight(96)
        form.addRow("描述", self.description_input)

        self.applicability_input = QTextEdit(
            self.composition.applicability if self.composition else ""
        )
        self.applicability_input.setPlaceholderText("必填。可在选好技能后点击右上角一键生成，再继续修改。")
        self.applicability_input.setTabChangesFocus(True)
        self.applicability_input.setFrameShape(QFrame.Shape.NoFrame)
        self.applicability_input.setMaximumHeight(120)
        self.applicability_input.setStyleSheet(
            "background: transparent; border: none; padding: 0px;"
        )

        self.generate_applicability_button = QPushButton("一键生成")
        self.generate_applicability_button.setObjectName("secondary_action")
        self.generate_applicability_button.clicked.connect(self._generate_applicability)
        applicability_panel = _FloatingCornerField(
            self.applicability_input,
            self.generate_applicability_button,
        )
        form.addRow("适用场景", applicability_panel)
        details_layout.addLayout(form)
        root.addWidget(details_card)

        button_row = QHBoxLayout()
        button_row.addStretch()

        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        button_row.addWidget(cancel_btn)

        save_btn = QPushButton("保存")
        save_btn.setObjectName("primary_action")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._on_save_clicked)
        button_row.addWidget(save_btn)
        root.addLayout(button_row)

        self.setTabOrder(self.name_input, self.description_input)
        self.setTabOrder(self.description_input, self.applicability_input)
        self.setTabOrder(self.applicability_input, self.generate_applicability_button)
        self.setTabOrder(self.generate_applicability_button, cancel_btn)
        self.setTabOrder(cancel_btn, save_btn)

        self._on_mode_changed()

    def _populate_available_tools(self) -> None:
        self._syncing_checks = True
        current_tool_id = None
        current_item = self.available_list.currentItem()
        if current_item is not None:
            current_tool_id = current_item.data(Qt.ItemDataRole.UserRole)
        self.available_list.clear()
        mode = self._current_mode()
        ordered_ids = self.selected_tool_ids + [
            tool.tool_id for tool in self.available_tools if tool.tool_id not in self.selected_tool_ids
        ]
        selected_index = 0
        for tool_id in ordered_ids:
            tool = self.tool_map.get(tool_id)
            if tool is None:
                continue
            checked = tool_id in self.selected_tool_ids
            if checked and mode == "ordered":
                selected_index += 1
                text = f"{selected_index}. {tool.tool_name}"
            else:
                text = tool.tool_name
            item = QListWidgetItem(text)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            if not (checked and mode == "ordered"):
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsDragEnabled)
            item.setData(Qt.ItemDataRole.UserRole, tool.tool_id)
            item.setToolTip(tool.description or "暂无描述")
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            self.available_list.addItem(item)
            if current_tool_id == tool_id:
                self.available_list.setCurrentItem(item)
        self._syncing_checks = False
        self._update_action_states()

    def _refresh_selected_tools(self) -> None:
        self._populate_available_tools()

    def _on_available_item_changed(self, item: QListWidgetItem) -> None:
        if self._syncing_checks:
            return

        tool_id = item.data(Qt.ItemDataRole.UserRole)
        checked = item.checkState() == Qt.CheckState.Checked
        if checked:
            if tool_id not in self.selection_order_map:
                self.selection_order_map[tool_id] = max(self.selection_order_map.values(), default=0) + 1
            if tool_id not in self.selected_tool_ids:
                self.selected_tool_ids.append(tool_id)
        else:
            self.selection_order_map.pop(tool_id, None)
            self.selected_tool_ids = [existing for existing in self.selected_tool_ids if existing != tool_id]

        self._sync_selection_order_map()
        self._refresh_selected_tools()

    def _on_available_item_double_clicked(self, item: QListWidgetItem) -> None:
        current = item.checkState()
        target = (
            Qt.CheckState.Unchecked
            if current == Qt.CheckState.Checked
            else Qt.CheckState.Checked
        )
        item.setCheckState(target)

    def _sync_selected_order_from_list(self) -> None:
        ordered_ids = []
        for row in range(self.available_list.count()):
            item = self.available_list.item(row)
            tool_id = item.data(Qt.ItemDataRole.UserRole)
            if tool_id and item.checkState() == Qt.CheckState.Checked:
                ordered_ids.append(tool_id)
        self.selected_tool_ids = ordered_ids
        self._sync_selection_order_map()

    def _on_selected_rows_moved(self, *_args) -> None:
        self._sync_selected_order_from_list()
        self._refresh_selected_tools()

    def _update_recommend_button_overlay(self) -> None:
        if not hasattr(self, "available_list") or self._recommend_dragger is None:
            return

        if self.recommend_now_button.isVisible():
            self.available_list.setViewportMargins(0, 0, 0, 42)
            self._recommend_dragger.update_overlay()
        else:
            self.available_list.setViewportMargins(0, 0, 0, 0)

    # Compatibility wrappers kept for existing UI regression tests.
    def _recommend_button_bounds(self) -> tuple[int, int, int, int]:
        if self._recommend_dragger is None:
            return (0, 0, 0, 0)
        return self._recommend_dragger.bounds()

    def _set_recommend_button_position(self, pos: QPoint) -> None:
        if self._recommend_dragger is None:
            return
        self._recommend_dragger.set_position(pos)

    def eventFilter(self, watched, event) -> bool:
        if watched is getattr(self, "available_list", None) and event.type() in {
            QEvent.Type.Resize,
            QEvent.Type.Show,
        }:
            self._update_recommend_button_overlay()
        elif watched is getattr(getattr(self, "available_list", None), "viewport", lambda: None)():
            if event.type() == QEvent.Type.MouseButtonDblClick and event.button() == Qt.MouseButton.LeftButton:
                item = self.available_list.itemAt(event.position().toPoint())
                if item is not None:
                    self._on_available_item_double_clicked(item)
                    return True
        elif self._recommend_dragger and watched is self._recommend_dragger.button:
            result = self._recommend_dragger.handle_event(watched, event)
            if result is not None:
                return result
        return super().eventFilter(watched, event)

    def _build_section_header(self, step_text: str, title: str, desc: str) -> QWidget:
        header = QWidget()
        layout = QVBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        top_row = QHBoxLayout()
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.setSpacing(8)
        badge = QLabel(step_text)
        badge.setStyleSheet(
            f"font-size: 11px; font-weight: 700; color: {PRIMARY_COLOR}; "
            "background-color: #f0f1ff; padding: 3px 10px; border-radius: 10px;"
        )
        top_row.addWidget(badge)

        title_label = QLabel(title)
        title_label.setStyleSheet(
            f"font-size: 16px; font-weight: 700; color: {TITLE_COLOR};"
        )
        top_row.addWidget(title_label)
        top_row.addStretch()
        layout.addLayout(top_row)

        desc_label = QLabel(desc)
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet(f"font-size: 12px; color: {SUBTITLE_COLOR};")
        layout.addWidget(desc_label)
        return header

    def _sync_selection_order_map(self) -> None:
        self.selection_order_map = {
            tool_id: index for index, tool_id in enumerate(self.selected_tool_ids, start=1)
        }

    def _current_mode(self) -> str:
        return self.mode_combo.currentData()

    def _on_mode_changed(self) -> None:
        is_ordered = self._current_mode() == "ordered"
        self.recommend_now_button.setVisible(is_ordered)
        if is_ordered:
            self.member_hint_label.setText("勾选要加入的技能；拖动已勾选项即可调整执行顺序。")
            self.available_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
            self.available_list.setDragEnabled(True)
        else:
            self.member_hint_label.setText("勾选要加入的技能。")
            self.available_list.setDragDropMode(QAbstractItemView.DragDropMode.NoDragDrop)
            self.available_list.setDragEnabled(False)
        self._update_recommend_button_overlay()
        self._sync_selection_order_map()
        self._refresh_selected_tools()

    def _update_action_states(self) -> None:
        selected_count = len(self.selected_tool_ids)
        is_ordered = self._current_mode() == "ordered"

        self.recommend_now_button.setEnabled(
            is_ordered and selected_count > 1 and not self._is_generating_recommendation
        )
        self.generate_applicability_button.setEnabled(
            selected_count > 0 and not self._is_generating_applicability
        )

        if selected_count == 0:
            summary = "先勾选成员技能，再填写名称和适用场景。"
        elif is_ordered:
            summary = f"已选 {selected_count} 个技能。拖动已勾选项即可调整实际执行顺序，也可以点击“推荐顺序”自动重排。"
        else:
            summary = f"已选 {selected_count} 个技能。范围型组合会在这些技能之间灵活选择。"
        self.member_summary_label.setText(summary)

        if self._is_generating_recommendation:
            self.recommend_now_button.setToolTip("正在生成推荐顺序，请稍候")
        elif is_ordered and selected_count <= 1:
            self.recommend_now_button.setToolTip("至少选择两个技能后，才需要生成推荐顺序")
        elif is_ordered:
            self.recommend_now_button.setToolTip("基于当前已选技能和上下文，生成更合适的执行顺序")
        else:
            self.recommend_now_button.setToolTip("范围型组合不需要推荐顺序")

        if self._is_generating_applicability:
            self.generate_applicability_button.setToolTip("正在生成适用场景，请稍候")
        elif selected_count > 0:
            self.generate_applicability_button.setToolTip("根据当前已选技能生成适用场景")
        else:
            self.generate_applicability_button.setToolTip("先选择技能，再生成适用场景")

    def _generate_recommendation(self) -> bool:
        if self._current_mode() != "ordered":
            return True
        if len(self.selected_tool_ids) <= 1 or self._recommendation_generation_thread is not None:
            return False

        try:
            payload = self.get_payload()
        except SkillCompositionError as e:
            QMessageBox.warning(self, "生成推荐顺序失败", str(e))
            return False

        self._set_recommendation_generation_state(True)
        thread = RecommendationGenerationThread(
            composition_name=payload["composition_name"],
            description=payload["description"],
            applicability=payload["applicability"],
            members=payload["members"],
        )
        self._recommendation_generation_thread = thread
        thread.finished_signal.connect(self._on_recommendation_generated)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_recommendation_generation_thread)
        thread.start()
        return True

    def _set_recommendation_generation_state(self, is_generating: bool) -> None:
        self._is_generating_recommendation = is_generating
        self.recommend_now_button.setText("推荐中..." if is_generating else "推荐顺序")
        self.mode_combo.setEnabled(not is_generating)
        self.available_list.setEnabled(not is_generating)
        self._update_action_states()
        self._update_recommend_button_overlay()

    def _on_recommendation_generated(self, success: bool, result: object, error: str) -> None:
        self._set_recommendation_generation_state(False)
        if not success:
            QMessageBox.warning(self, "生成推荐顺序失败", error or "生成推荐顺序失败")
            return

        payload = result if isinstance(result, dict) else {}
        recommended_members = payload.get("members") or []
        recommended_ids = [member["tool_id"] for member in recommended_members if member.get("tool_id")]
        changed = recommended_ids != self.selected_tool_ids
        if recommended_ids:
            self.selected_tool_ids = recommended_ids
            self._refresh_selected_tools()

        reason = payload.get("reason") or "已根据当前场景自动生成推荐顺序。"
        title = "推荐顺序已更新" if changed else "推荐顺序已确认"
        QMessageBox.information(self, title, reason)

    def _clear_recommendation_generation_thread(self) -> None:
        self._recommendation_generation_thread = None

    def _generate_applicability(self) -> None:
        if not self.selected_tool_ids or self._applicability_generation_thread is not None:
            return

        try:
            payload = self.get_payload()
        except SkillCompositionError as e:
            QMessageBox.warning(self, "生成适用场景失败", str(e))
            return

        self._set_applicability_generation_state(True)
        thread = ApplicabilityGenerationThread(
            composition_name=payload["composition_name"],
            description=payload["description"],
            mode=payload["mode"],
            members=payload["members"],
        )
        self._applicability_generation_thread = thread
        thread.finished_signal.connect(self._on_applicability_generated)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._clear_applicability_generation_thread)
        thread.start()

    def _set_applicability_generation_state(self, is_generating: bool) -> None:
        self._is_generating_applicability = is_generating
        self.generate_applicability_button.setText("生成中..." if is_generating else "一键生成")
        self._update_action_states()

    def _on_applicability_generated(self, success: bool, generated: str, error: str) -> None:
        self._set_applicability_generation_state(False)
        if not success:
            QMessageBox.warning(self, "生成适用场景失败", error or "生成适用场景失败")
            return

        self.applicability_input.setPlainText(generated)
        self.applicability_input.setFocus()

    def _clear_applicability_generation_thread(self) -> None:
        self._applicability_generation_thread = None

    def reject(self) -> None:
        """关闭对话框前断开后台线程信号，防止回调访问已销毁对象。"""
        for thread_attr, clear_attr in [
            ("_applicability_generation_thread", "_clear_applicability_generation_thread"),
            ("_recommendation_generation_thread", "_clear_recommendation_generation_thread"),
        ]:
            thread = getattr(self, thread_attr, None)
            if thread is not None and thread.isRunning():
                clear_handler = getattr(self, clear_attr)
                try:
                    thread.finished_signal.disconnect()
                except (TypeError, RuntimeError):
                    pass
                try:
                    thread.finished.disconnect(clear_handler)
                except (TypeError, RuntimeError):
                    pass
                clear_handler()
        super().reject()

    def _on_save_clicked(self) -> None:
        try:
            self.get_payload(validate=True)
        except SkillCompositionError as e:
            QMessageBox.warning(self, "保存失败", str(e))
            return
        self.accept()

    def get_payload(self, validate: bool = False) -> dict:
        members = []
        mode = self._current_mode()
        for index, tool_id in enumerate(self.selected_tool_ids, start=1):
            members.append(
                {
                    "tool_id": tool_id,
                    "selected_order": self.selection_order_map.get(tool_id, index),
                    "execution_order": index if mode == "ordered" else None,
                }
            )

        payload = {
            "composition_name": self.name_input.text().strip(),
            "description": self.description_input.toPlainText().strip(),
            "applicability": self.applicability_input.toPlainText().strip(),
            "mode": mode,
            "members": members,
        }
        if validate:
            self.service.validate_composition_payload(
                composition_id=self.composition.composition_id if self.composition else "preview",
                composition_name=payload["composition_name"],
                description=payload["description"],
                applicability=payload["applicability"],
                mode=mode,
                status=self.composition.status if self.composition else "draft",
                members=members,
            )
        return payload


class SkillCompositionExecutionThread(QThread):
    """技能组合执行线程"""

    started_signal = pyqtSignal()
    progress_signal = pyqtSignal(str, int)
    finished_signal = pyqtSignal(bool, object, str)
    error_signal = pyqtSignal(str)

    def __init__(
        self,
        composition_id: str,
        task: str = "",
        context: str = "",
        session_id: str = "",
        user_input: Any = "",
    ):
        super().__init__()
        self.logger = get_logger(__name__)
        self.composition_id = composition_id
        self.task = task
        self.context = context
        self.session_id = session_id
        self.user_input = user_input
        self._mutex = QMutex()
        self._is_cancelled = False
        self._success = False
        self._result = None
        self._error = None
        self._service = SkillCompositionService()

    def run(self):
        try:
            self.started_signal.emit()
            self.progress_signal.emit("正在准备技能组合试用环境...", 10)

            with QMutexLocker(self._mutex):
                cancelled = self._is_cancelled
            if cancelled:
                self.error_signal.emit("执行已被用户取消")
                return

            self.progress_signal.emit("正在生成并执行技能组合...", 45)
            if self.session_id:
                trial_result = self._service.continue_trial(
                    self.composition_id,
                    self.session_id,
                    self.user_input,
                )
            else:
                trial_result = self._service.run_trial(
                    self.composition_id,
                    self.task,
                    self.context,
                )

            payload = {
                "reply": trial_result.reply,
                "result_type": trial_result.result_type,
                "session_id": trial_result.session_id,
            }

            with QMutexLocker(self._mutex):
                self._success = trial_result.success
                self._result = payload
                self._error = trial_result.error

            self.progress_signal.emit("技能组合试用完成，正在整理结果...", 90)
            if trial_result.result_type == ResultType.NEEDS_USER_INPUT.value:
                self.finished_signal.emit(False, payload, "需要补充信息")
            elif trial_result.success:
                self.finished_signal.emit(True, payload, "")
            else:
                self.finished_signal.emit(False, payload, trial_result.error or "技能组合试用失败")

        except Exception as e:
            error_msg = f"技能组合试用异常: {e}"
            self.logger.error(error_msg, exc_info=True)
            with QMutexLocker(self._mutex):
                self._success = False
                self._result = None
                self._error = error_msg
            self.error_signal.emit(error_msg)
            self.finished_signal.emit(False, None, error_msg)

    def cancel(self):
        with QMutexLocker(self._mutex):
            self._is_cancelled = True
