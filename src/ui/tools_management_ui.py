"""
技能列表 UI 组件

提供技能管理界面，包括：
1. 待考核 / 已掌握 / 失败记录 三个分类 Tab
2. 技能卡片展示（名称、描述、状态、创建时间、考核次数）
3. 操作：考核、删除、编辑名称/描述
4. 实时状态更新
"""

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QGridLayout,
    QInputDialog,
    QMessageBox,
    QMenu,
    QFrame,
    QDialog,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction
from typing import List
from datetime import datetime

from src.business.tool_trial.trial_models import PendingTool, PendingToolStatus
from src.utils.logger import get_logger
from src.data.models import Tool
from src.data.models_sqlite import TeachingFailureRecord


# ── 公共样式常量 ──

_CARD_STYLE = """
    QFrame#skill_card {{
        background-color: #ffffff;
        border: 1.5px solid {border};
        border-radius: 10px;
    }}
    QFrame#skill_card:hover {{
        border-color: {hover_border};
        background-color: #fafbff;
    }}
"""

_STATUS_PILL_STYLE = """
    QLabel {{
        font-size: 11px;
        font-weight: 600;
        color: {fg};
        background-color: {bg};
        padding: 3px 10px;
        border-radius: 10px;
    }}
"""

_ACTION_BTN_STYLE = """
    QPushButton {{
        font-size: 13px;
        font-weight: 600;
        padding: 6px 18px;
        border-radius: 6px;
        color: {fg};
        background-color: {bg};
        border: {border};
    }}
    QPushButton:hover {{
        background-color: {hover_bg};
    }}
    QPushButton:disabled {{
        color: #c5c9e0;
        background-color: #f8f9fa;
        border-color: #e0e0e0;
    }}
"""

_MORE_BTN_STYLE = """
    QPushButton {
        background: transparent;
        border: none;
        color: #adb5bd;
        font-size: 18px;
        font-weight: bold;
        border-radius: 4px;
    }
    QPushButton:hover {
        background-color: #f0f1ff;
        color: #5b6abf;
    }
"""

_META_STYLE = "font-size: 11px; color: #adb5bd; background: transparent;"

_MENU_STYLE = """
    QMenu {
        background-color: #ffffff;
        border: 1px solid #e9ecef;
        border-radius: 6px;
        padding: 4px;
    }
    QMenu::item { padding: 8px 16px; border-radius: 4px; }
    QMenu::item:selected { background-color: {selected_color}; }
"""


class _SkillCardBase(QFrame):
    """技能卡片基类"""

    delete_requested = pyqtSignal(str)
    edit_requested = pyqtSignal(str)

    def __init__(self, card_id: str, name: str, desc: str, parent=None):
        super().__init__(parent)
        self._card_id = card_id
        self._name = name
        self._desc = desc
        self.setObjectName("skill_card")
        self.setMinimumHeight(160)
        self.setMaximumHeight(200)

    @staticmethod
    def _format_time(dt: datetime) -> str:
        delta = datetime.now() - dt
        if delta.days > 0:
            return f"{delta.days}天前"
        elif delta.seconds >= 3600:
            return f"{delta.seconds // 3600}小时前"
        elif delta.seconds >= 60:
            return f"{delta.seconds // 60}分钟前"
        return "刚刚"

    # ── 通用构建块 ──

    def _build_top_row(self, left_widget: QWidget) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(left_widget)
        row.addStretch()
        more_btn = QPushButton("...")
        more_btn.setFixedSize(26, 26)
        more_btn.setStyleSheet(_MORE_BTN_STYLE)
        more_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        more_btn.clicked.connect(self._show_menu)
        row.addWidget(more_btn)
        self._more_btn = more_btn
        return row

    def _build_name_label(self) -> QLabel:
        lbl = QLabel(self._name)
        lbl.setStyleSheet(
            "font-size: 15px; font-weight: 600; color: #1a1a2e; background: transparent;"
        )
        lbl.setWordWrap(True)
        return lbl

    def _build_desc_label(self) -> QLabel:
        lbl = QLabel(self._desc or "暂无描述")
        lbl.setStyleSheet("font-size: 12px; color: #6c757d; background: transparent;")
        lbl.setWordWrap(True)
        lbl.setMaximumHeight(50)
        lbl.setAlignment(Qt.AlignmentFlag.AlignTop)
        return lbl

    def _show_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet(_MENU_STYLE.format(selected_color="#f0f1ff"))
        edit_action = QAction("编辑", self)
        edit_action.triggered.connect(lambda: self.edit_requested.emit(self._card_id))
        menu.addAction(edit_action)

        delete_action = QAction("删除", self)
        delete_action.triggered.connect(lambda: self.delete_requested.emit(self._card_id))
        menu.addAction(delete_action)
        menu.exec(self._more_btn.mapToGlobal(self._more_btn.rect().bottomLeft()))


class PendingToolCard(_SkillCardBase):
    """待考核技能卡片"""

    trial_requested = pyqtSignal(str)

    def __init__(self, pending_tool: PendingTool, parent=None):
        super().__init__(
            card_id=pending_tool.pending_tool_id,
            name=pending_tool.tool_name,
            desc=pending_tool.tool_description,
            parent=parent,
        )
        self.pending_tool = pending_tool
        self.logger = get_logger(__name__)
        self._init_ui()

    def _init_ui(self):
        self.setStyleSheet(_CARD_STYLE.format(border="#e0e0e0", hover_border="#b0b5e0"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        # 顶部：状态标签 + 更多
        status_lbl = QLabel(self._status_text())
        status_lbl.setStyleSheet(_STATUS_PILL_STYLE.format(**self._status_colors()))
        layout.addLayout(self._build_top_row(status_lbl))

        # 名称
        layout.addWidget(self._build_name_label())
        # 描述
        layout.addWidget(self._build_desc_label(), 1)

        # 底部信息
        meta_row = QHBoxLayout()
        trial_lbl = QLabel(f"考核 {self.pending_tool.trial_count}/{self.pending_tool.max_trials}")
        trial_lbl.setStyleSheet(_META_STYLE)
        meta_row.addWidget(trial_lbl)
        meta_row.addStretch()
        if self.pending_tool.created_at:
            time_lbl = QLabel(self._format_time(self.pending_tool.created_at))
            time_lbl.setStyleSheet(_META_STYLE)
            meta_row.addWidget(time_lbl)
        layout.addLayout(meta_row)

        # 操作按钮
        if self.pending_tool.can_trial():
            btn = QPushButton("开始考核")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(34)
            btn.setStyleSheet(
                _ACTION_BTN_STYLE.format(
                    fg="white",
                    bg="#5b6abf",
                    border="none",
                    hover_bg="#4a58a8",
                )
            )
            btn.clicked.connect(
                lambda: self.trial_requested.emit(self.pending_tool.pending_tool_id)
            )
            layout.addWidget(btn)
        elif self.pending_tool.status == PendingToolStatus.TRIAL_SUCCESS:
            lbl = QLabel("可提升为已掌握技能")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setFixedHeight(34)
            lbl.setStyleSheet(
                "font-size: 12px; font-weight: 600; color: #28a745; "
                "background-color: #f0fff4; border: 1px solid #c3e6cb; border-radius: 6px;"
            )
            layout.addWidget(lbl)
        elif self.pending_tool.status == PendingToolStatus.FAILED:
            lbl = QLabel("考核未通过")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setFixedHeight(34)
            lbl.setStyleSheet(
                "font-size: 12px; font-weight: 600; color: #dc3545; "
                "background-color: #fff5f5; border: 1px solid #f5c6cb; border-radius: 6px;"
            )
            layout.addWidget(lbl)

    def _status_text(self) -> str:
        return {
            PendingToolStatus.PENDING_TRIAL: "等待考核",
            PendingToolStatus.TRIALING: "考核中",
            PendingToolStatus.TRIAL_SUCCESS: "考核通过",
            PendingToolStatus.TRIAL_FAILED: "考核未通过",
            PendingToolStatus.AWAITING_REAL_DATA: "等待数据",
            PendingToolStatus.PROMOTED: "已提升",
            PendingToolStatus.FAILED: "最终失败",
        }.get(self.pending_tool.status, "未知状态")

    def _status_colors(self) -> dict:
        return {
            PendingToolStatus.PENDING_TRIAL: {"fg": "#6c757d", "bg": "#f1f3f5"},
            PendingToolStatus.TRIALING: {"fg": "#5b6abf", "bg": "#f0f1ff"},
            PendingToolStatus.TRIAL_SUCCESS: {"fg": "#28a745", "bg": "#f0fff4"},
            PendingToolStatus.TRIAL_FAILED: {"fg": "#dc3545", "bg": "#fff5f5"},
            PendingToolStatus.AWAITING_REAL_DATA: {"fg": "#fd7e14", "bg": "#fff8f0"},
            PendingToolStatus.PROMOTED: {"fg": "#6f42c1", "bg": "#f8f0ff"},
            PendingToolStatus.FAILED: {"fg": "#343a40", "bg": "#f1f3f5"},
        }.get(self.pending_tool.status, {"fg": "#6c757d", "bg": "#f1f3f5"})


class PublishedToolCard(_SkillCardBase):
    """已掌握技能卡片"""

    execute_requested = pyqtSignal(str)

    def __init__(self, tool: Tool, parent=None):
        super().__init__(
            card_id=tool.tool_id,
            name=tool.tool_name,
            desc=tool.description,
            parent=parent,
        )
        self.tool = tool
        self.logger = get_logger(__name__)
        self._init_ui()

    def _init_ui(self):
        self.setStyleSheet(_CARD_STYLE.format(border="#c3e6cb", hover_border="#28a745"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        # 顶部：来源标签 + 更多
        source_text = {
            "manual": "手动创建",
            "intent": "意图生成",
            "trial": "考核转化",
        }.get(self.tool.source, "未知")
        source_lbl = QLabel(source_text)
        source_lbl.setStyleSheet(_STATUS_PILL_STYLE.format(fg="#5b6abf", bg="#f0f1ff"))
        layout.addLayout(self._build_top_row(source_lbl))

        # 名称
        layout.addWidget(self._build_name_label())
        # 描述
        layout.addWidget(self._build_desc_label(), 1)

        # 底部信息
        meta_row = QHBoxLayout()
        param_count = len(self.tool.parameters)
        if param_count > 0:
            param_lbl = QLabel(f"参数: {param_count}")
            param_lbl.setStyleSheet(_META_STYLE)
            meta_row.addWidget(param_lbl)
        meta_row.addStretch()
        if self.tool.created_at:
            time_lbl = QLabel(_SkillCardBase._format_time(self.tool.created_at))
            time_lbl.setStyleSheet(_META_STYLE)
            meta_row.addWidget(time_lbl)
        layout.addLayout(meta_row)

        # 操作按钮
        param_count = len(self.tool.parameters)
        if param_count == 0:
            btn = QPushButton("执行")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(34)
            btn.setStyleSheet(
                _ACTION_BTN_STYLE.format(
                    fg="white",
                    bg="#28a745",
                    border="none",
                    hover_bg="#218838",
                )
            )
            btn.clicked.connect(lambda: self.execute_requested.emit(self.tool.tool_id))
            layout.addWidget(btn)
        else:
            btn = QPushButton("配置")
            btn.setFixedHeight(34)
            btn.setEnabled(False)
            btn.setToolTip(f"该技能需要 {param_count} 个参数\n参数配置功能开发中")
            btn.setStyleSheet(
                _ACTION_BTN_STYLE.format(
                    fg="#6c757d",
                    bg="#f8f9fa",
                    border="1px solid #e0e0e0",
                    hover_bg="#e9ecef",
                )
            )
            layout.addWidget(btn)


class FailureCard(_SkillCardBase):
    """失败记录卡片"""

    retry_requested = pyqtSignal(str, str)  # workflow_id, failed_stage
    dismiss_requested = pyqtSignal(str)  # workflow_id

    _STAGE_DISPLAY = {"pm": "需求分析", "programmer": "代码生成", "trial": "技能试用"}

    def __init__(self, record: TeachingFailureRecord, parent=None):
        super().__init__(
            card_id=record.workflow_id,
            name=record.tool_name or record.workflow_id[:8],
            desc=record.error_summary or "未知错误",
            parent=parent,
        )
        self._record = record
        self._init_failure_ui()

    def _init_failure_ui(self):
        self.setStyleSheet(_CARD_STYLE.format(border="#f5c6cb", hover_border="#dc3545"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        # 顶部：失败阶段 pill
        stage_text = self._STAGE_DISPLAY.get(self._record.failed_stage, self._record.failed_stage)
        stage_lbl = QLabel(stage_text)
        stage_lbl.setStyleSheet(_STATUS_PILL_STYLE.format(fg="#dc3545", bg="#fff5f5"))
        layout.addLayout(self._build_top_row(stage_lbl))

        # 工具名 / 错误摘要
        self._name_label = self._build_name_label()
        layout.addWidget(self._name_label)
        self._desc_label = self._build_desc_label()
        layout.addWidget(self._desc_label, 1)

        # 底部：时间 + 失败次数
        meta_row = QHBoxLayout()
        if self._record.created_at:
            time_lbl = QLabel(_SkillCardBase._format_time(self._record.created_at))
            time_lbl.setStyleSheet(_META_STYLE)
            meta_row.addWidget(time_lbl)
        retry_lbl = QLabel(f"已失败 {self._record.retry_count} 次")
        retry_lbl.setStyleSheet(_META_STYLE)
        meta_row.addWidget(retry_lbl)
        meta_row.addStretch()
        layout.addLayout(meta_row)

        # 重试按钮 / 正在修复状态
        self._action_widget = QWidget()
        action_layout = QHBoxLayout(self._action_widget)
        action_layout.setContentsMargins(0, 0, 0, 0)
        self._retry_btn = QPushButton("重试")
        self._retry_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._retry_btn.setFixedHeight(34)
        self._retry_btn.setStyleSheet(
            _ACTION_BTN_STYLE.format(
                fg="white",
                bg="#dc3545",
                border="none",
                hover_bg="#c82333",
            )
        )
        self._retry_btn.clicked.connect(
            lambda: self.retry_requested.emit(self._record.workflow_id, self._record.failed_stage)
        )
        action_layout.addWidget(self._retry_btn)
        self._retrying_label = QLabel("正在修复...")
        self._retrying_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._retrying_label.setFixedHeight(34)
        self._retrying_label.setStyleSheet(
            "font-size: 13px; font-weight: 600; color: #868e96; background-color: #f8f9fa; "
            "border: 1px solid #e0e0e0; border-radius: 6px;"
        )
        self._retrying_label.setVisible(False)
        action_layout.addWidget(self._retrying_label)
        layout.addWidget(self._action_widget)

        if self._record.status == "retrying":
            self._show_retrying_state()

    def _show_retrying_state(self):
        """切换到正在修复状态"""
        self._retry_btn.setVisible(False)
        self._retrying_label.setVisible(True)

    def _show_menu(self):
        """只显示忽略选项"""
        menu = QMenu(self)
        menu.setStyleSheet(_MENU_STYLE.format(selected_color="#fff5f5"))
        dismiss_action = QAction("忽略", self)
        dismiss_action.setToolTip("忽略后不会再显示；如需恢复只能重新录制")
        dismiss_action.triggered.connect(
            lambda: self.dismiss_requested.emit(self._record.workflow_id)
        )
        menu.addAction(dismiss_action)
        menu.exec(self._more_btn.mapToGlobal(self._more_btn.rect().bottomLeft()))


class ToolsManagementUI(QWidget):
    """技能列表 UI 组件（带 Tab 切换）"""

    trial_start_request = pyqtSignal(str)
    tool_delete_request = pyqtSignal(str)
    tool_update_request = pyqtSignal(str, str, str)
    retry_requested = pyqtSignal(str, str)  # workflow_id, failed_stage
    failure_dismiss_requested = pyqtSignal(str)  # workflow_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger(__name__)
        self.pending_tools: List[PendingTool] = []
        self.pending_tool_cards: List[PendingToolCard] = []
        self.published_tools: List[Tool] = []
        self.published_tool_cards: List[PublishedToolCard] = []
        self.failure_records: List[TeachingFailureRecord] = []
        self.failure_cards: List[FailureCard] = []
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        content = QWidget()
        content.setStyleSheet("background-color: #ffffff;")
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(0)
        content_layout.setContentsMargins(0, 0, 0, 0)

        # ── Hero 区域 ──
        hero = QWidget()
        hero.setStyleSheet("background-color: #fafbff;")
        hero_layout = QHBoxLayout(hero)
        hero_layout.setContentsMargins(40, 30, 40, 22)

        title_col = QVBoxLayout()
        title_col.setSpacing(8)
        title = QLabel("技能列表")
        title.setObjectName("tools_title")
        title.setStyleSheet(
            "font-size: 26px; font-weight: 700; color: #1a1a2e; background: transparent;"
        )
        title_col.addWidget(title)
        subtitle = QLabel("通过教学习得的技能在这里考核和管理")
        subtitle.setStyleSheet("font-size: 14px; color: #6c757d; background: transparent;")
        title_col.addWidget(subtitle)
        hero_layout.addLayout(title_col, 1)

        content_layout.addWidget(hero)

        # ── 分隔线 ──
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("background-color: #eef0f4; max-height: 1px;")
        content_layout.addWidget(sep)

        # ── Tab 切换条 ──
        tab_bar = QWidget()
        tab_bar.setStyleSheet("background-color: #ffffff;")
        tab_bar_layout = QHBoxLayout(tab_bar)
        tab_bar_layout.setContentsMargins(40, 0, 40, 0)
        tab_bar_layout.setSpacing(0)

        self._pending_tab_btn = self._create_tab_btn("待考核", True)
        self._pending_tab_btn.clicked.connect(lambda: self._switch_tab("pending"))
        tab_bar_layout.addWidget(self._pending_tab_btn)

        self._published_tab_btn = self._create_tab_btn("已掌握", False)
        self._published_tab_btn.clicked.connect(lambda: self._switch_tab("published"))
        tab_bar_layout.addWidget(self._published_tab_btn)

        tab_bar_layout.addSpacing(8)

        self._failures_tab_btn = self._create_tab_btn("失败记录", False)
        self._failures_tab_btn.clicked.connect(lambda: self._switch_tab("failures"))
        tab_bar_layout.addWidget(self._failures_tab_btn)

        tab_bar_layout.addStretch()
        content_layout.addWidget(tab_bar)

        # ── 内容区 ──
        self._cards_area = QWidget()
        self._cards_area.setStyleSheet("background-color: #ffffff;")
        cards_layout = QVBoxLayout(self._cards_area)
        cards_layout.setContentsMargins(40, 24, 40, 24)
        cards_layout.setSpacing(0)

        # 待考核 scroll
        self._pending_scroll = self._create_scroll_area()
        self._pending_scroll_content = QWidget()
        self.pending_tools_grid = QGridLayout(self._pending_scroll_content)
        self.pending_tools_grid.setSpacing(14)
        self.pending_tools_grid.setContentsMargins(0, 0, 0, 0)
        self.pending_tools_grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._pending_scroll.setWidget(self._pending_scroll_content)
        cards_layout.addWidget(self._pending_scroll)

        # 待考核空状态
        self.pending_empty_label = self._create_empty_label(
            "暂无待考核技能\n\n完成技能教学后，生成的技能会显示在这里"
        )
        cards_layout.addWidget(self.pending_empty_label)

        # 已掌握 scroll
        self._published_scroll = self._create_scroll_area()
        self._published_scroll.setVisible(False)
        self._published_scroll_content = QWidget()
        self.published_tools_grid = QGridLayout(self._published_scroll_content)
        self.published_tools_grid.setSpacing(14)
        self.published_tools_grid.setContentsMargins(0, 0, 0, 0)
        self.published_tools_grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._published_scroll.setWidget(self._published_scroll_content)
        cards_layout.addWidget(self._published_scroll)

        # 已掌握空状态
        self.published_empty_label = self._create_empty_label(
            "暂无已掌握技能\n\n考核通过的技能会显示在这里"
        )
        self.published_empty_label.setVisible(False)
        cards_layout.addWidget(self.published_empty_label)

        # 失败记录 scroll
        self._failures_scroll = self._create_scroll_area()
        self._failures_scroll.setVisible(False)
        self._failures_scroll_content = QWidget()
        self.failures_grid = QGridLayout(self._failures_scroll_content)
        self.failures_grid.setSpacing(14)
        self.failures_grid.setContentsMargins(0, 0, 0, 0)
        self.failures_grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._failures_scroll.setWidget(self._failures_scroll_content)
        cards_layout.addWidget(self._failures_scroll)

        # 失败记录空状态
        self.failures_empty_label = self._create_empty_label(
            "暂无失败记录\n\n教学流程中的异常会自动记录在这里"
        )
        self.failures_empty_label.setVisible(False)
        cards_layout.addWidget(self.failures_empty_label)

        content_layout.addWidget(self._cards_area, 1)
        main_layout.addWidget(content)

        self._current_tab = "pending"
        self._load_tools()

    # ── Tab 按钮 ──

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
                """
                QPushButton {
                    font-size: 14px; font-weight: 600; color: #5b6abf;
                    background: transparent; border: none;
                    border-bottom: 2.5px solid #5b6abf;
                    padding: 0 20px;
                }
            """
            )
        else:
            btn.setStyleSheet(
                """
                QPushButton {
                    font-size: 14px; font-weight: 500; color: #868e96;
                    background: transparent; border: none;
                    border-bottom: 2.5px solid transparent;
                    padding: 0 20px;
                }
                QPushButton:hover { color: #5b6abf; }
            """
            )

    def _switch_tab(self, tab: str):
        self._current_tab = tab

        self._pending_scroll.setVisible(tab == "pending")
        self.pending_empty_label.setVisible(tab == "pending" and len(self.pending_tools) == 0)

        self._published_scroll.setVisible(tab == "published")
        self.published_empty_label.setVisible(tab == "published" and len(self.published_tools) == 0)

        self._failures_scroll.setVisible(tab == "failures")
        self.failures_empty_label.setVisible(tab == "failures" and len(self.failure_records) == 0)

        self._apply_tab_style(self._pending_tab_btn, tab == "pending")
        self._apply_tab_style(self._published_tab_btn, tab == "published")
        self._apply_tab_style(self._failures_tab_btn, tab == "failures")

        # 切换到失败记录 Tab 时刷新数据
        if tab == "failures":
            self._load_failures()

    # ── 辅助创建 ──

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

    # ── 数据加载 ──

    def _load_tools(self):
        try:
            from src.data.repositories import ToolRepository
            from src.business.tool_trial.trial_models import PendingTool, PendingToolStatus

            repo = ToolRepository()
            all_tools = repo.get_all()

            pending_tools_list = []
            published_tools_list = []

            for tool in all_tools:
                if tool.status == "published":
                    published_tools_list.append(tool)
                elif tool.source == "intent":
                    pending_tools_list.append(
                        PendingTool(
                            pending_tool_id=tool.tool_id,
                            tool_name=tool.tool_name,
                            tool_description=tool.description,
                            execution_code=tool.execution_code,
                            execution_strategy=tool.execution_strategy,
                            parameters=tool.parameters if tool.parameters else [],
                            status=PendingToolStatus.PENDING_TRIAL,
                            trial_count=tool.trial_success_count,
                            max_trials=3,
                            created_at=tool.created_at,
                            updated_at=tool.updated_at,
                        )
                    )

            self.update_pending_tools(pending_tools_list)
            self.update_published_tools(published_tools_list)
            self.logger.info(
                f"从数据库加载技能: {len(pending_tools_list)} 个待考核, "
                f"{len(published_tools_list)} 个已掌握"
            )
        except Exception as e:
            self.logger.error(f"从数据库加载技能失败: {e}", exc_info=True)
            self._load_sample_tools()

    def load_tools(self):
        """公开刷新方法"""
        self._load_tools()
        self._load_failures()

    def _load_sample_tools(self):
        sample_pending = [
            PendingTool(
                tool_name="网页登录",
                tool_description="自动登录到指定网站",
                status=PendingToolStatus.PENDING_TRIAL,
                trial_count=0,
                max_trials=3,
                created_at=datetime.now(),
            ),
            PendingTool(
                tool_name="数据提取",
                tool_description="从网页提取表格数据",
                status=PendingToolStatus.TRIAL_SUCCESS,
                trial_count=1,
                max_trials=3,
                created_at=datetime.now(),
            ),
            PendingTool(
                tool_name="表单填写",
                tool_description="自动填写并提交表单",
                status=PendingToolStatus.TRIAL_FAILED,
                trial_count=2,
                max_trials=3,
                last_error="找不到元素：#submit-button",
                created_at=datetime.now(),
            ),
            PendingTool(
                tool_name="文件下载",
                tool_description="下载指定文件",
                status=PendingToolStatus.AWAITING_REAL_DATA,
                trial_count=1,
                max_trials=3,
                created_at=datetime.now(),
            ),
        ]
        sample_published = [
            Tool(
                tool_name="邮件发送",
                description="自动发送邮件通知",
                source="intent",
                created_at=datetime.now(),
            ),
            Tool(
                tool_name="数据备份",
                description="自动备份重要数据到云盘",
                source="trial",
                created_at=datetime.now(),
            ),
            Tool(
                tool_name="报表生成",
                description="自动生成周报和月报",
                source="manual",
                created_at=datetime.now(),
            ),
        ]
        self.update_pending_tools(sample_pending)
        self.update_published_tools(sample_published)

    # ── 列表更新 ──

    def update_pending_tools(self, pending_tools: List[PendingTool]):
        self.pending_tools = pending_tools
        self._clear_grid(self.pending_tools_grid)
        self.pending_tool_cards.clear()

        # 更新 Tab 文字
        self._pending_tab_btn.setText(f"待考核 ({len(pending_tools)})")

        show_empty = len(pending_tools) == 0 and self._current_tab == "pending"
        self.pending_empty_label.setVisible(show_empty)

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
        self._clear_grid(self.published_tools_grid)
        self.published_tool_cards.clear()

        self._published_tab_btn.setText(f"已掌握 ({len(published_tools)})")

        show_empty = len(published_tools) == 0 and self._current_tab == "published"
        self.published_empty_label.setVisible(show_empty)

        for i, tool in enumerate(published_tools):
            card = PublishedToolCard(tool)
            card.execute_requested.connect(self._on_execute_requested)
            card.delete_requested.connect(self._on_published_delete_requested)
            card.edit_requested.connect(self._on_published_edit_requested)
            self.published_tools_grid.addWidget(card, i // 3, i % 3)
            self.published_tool_cards.append(card)

        for col in range(3):
            self.published_tools_grid.setColumnStretch(col, 1)

    @staticmethod
    def _clear_grid(grid: QGridLayout):
        while grid.count():
            child = grid.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    # ── 事件处理 ──

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
            self.tool_delete_request.emit(pending_tool_id)
            self.pending_tools = [
                t for t in self.pending_tools if t.pending_tool_id != pending_tool_id
            ]
            self._refresh_pending_cards()

    def _on_edit_requested(self, pending_tool_id: str):
        self.logger.info(f"编辑待考核技能: {pending_tool_id}")
        tool = next((t for t in self.pending_tools if t.pending_tool_id == pending_tool_id), None)
        if not tool:
            return
        name, ok = QInputDialog.getText(self, "编辑技能名称", "技能名称:", text=tool.tool_name)
        if ok and name:
            desc, ok = QInputDialog.getText(
                self, "编辑技能描述", "技能描述:", text=tool.tool_description or ""
            )
            if ok:
                tool.tool_name = name
                tool.tool_description = desc
                self.tool_update_request.emit(pending_tool_id, name, desc)
                self._refresh_pending_cards()

    def _on_execute_requested(self, tool_id: str):
        self.logger.info(f"执行已掌握技能: {tool_id}")
        tool = next((t for t in self.published_tools if t.tool_id == tool_id), None)
        if not tool:
            self.logger.error(f"未找到技能: {tool_id}")
            QMessageBox.warning(self, "技能未找到", f"未找到技能 ID: {tool_id}")
            return

        from src.ui.tool_execution_dialog import ToolExecutionDialog, ExecutionResultDialog
        from src.ui.tool_execution_thread import ToolExecutionThread, ToolExecutionProgressDialog

        dialog = ToolExecutionDialog(tool, self)
        result = dialog.exec()
        if result == QDialog.DialogCode.Accepted:
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
            self.published_tools = [t for t in self.published_tools if t.tool_id != tool_id]
            self._refresh_published_cards()

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
                tool.tool_name = name
                tool.description = desc
                self._refresh_published_cards()

    def _refresh_pending_cards(self):
        self.update_pending_tools(self.pending_tools)

    def _refresh_published_cards(self):
        self.update_published_tools(self.published_tools)

    # ── 失败记录 ──

    def update_failure_records(self, failure_records: List[TeachingFailureRecord]):
        self.failure_records = failure_records
        self._clear_grid(self.failures_grid)
        self.failure_cards.clear()

        self._failures_tab_btn.setText(f"失败记录 ({len(failure_records)})")

        show_empty = len(failure_records) == 0 and self._current_tab == "failures"
        self.failures_empty_label.setVisible(show_empty)

        for i, record in enumerate(failure_records):
            card = FailureCard(record)
            card.retry_requested.connect(self.retry_requested.emit)
            card.dismiss_requested.connect(self.failure_dismiss_requested.emit)
            self.failures_grid.addWidget(card, i // 3, i % 3)
            self.failure_cards.append(card)

        for col in range(3):
            self.failures_grid.setColumnStretch(col, 1)

    def _load_failures(self):
        try:
            from src.data.repositories import TeachingFailureRepository

            repo = TeachingFailureRepository()
            records = repo.get_active_failures()
            self.update_failure_records(records)
        except Exception as e:
            self.logger.error(f"加载失败记录失败: {e}", exc_info=True)
            self.update_failure_records([])
