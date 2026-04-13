"""
技能卡片组件

包含三种卡片 Widget 及其公共基类：
- _SkillCardBase    — 公共基类（样式、菜单、通用构建块）
- PendingToolCard   — 待考核技能卡片
- PublishedToolCard — 已掌握技能卡片
- SkillCompositionCard — 技能组合卡片
- FailureCard       — 失败记录卡片
"""

from datetime import datetime

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from src.business.agents.config import AgentType
from src.business.tool_trial.trial_models import PendingTool, PendingToolStatus
from src.data.models import MODE_DISPLAY_TEXT, SkillComposition, Tool
from src.data.models_sqlite import TeachingFailureRecord
from src.ui.style_constants import HERO_BG_COLOR, PRIMARY_COLOR, SUBTITLE_COLOR, TITLE_COLOR

# ── 样式常量 ──

_CARD_STYLE = """
    QFrame#skill_card {{
        background-color: #ffffff;
        border: 1.5px solid {border};
        border-radius: 10px;
    }}
    QFrame#skill_card:hover {{
        border-color: {hover_border};
        background-color: """ + HERO_BG_COLOR + """;
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

_MORE_BTN_STYLE = f"""
    QPushButton {{
        background: transparent;
        border: none;
        color: #adb5bd;
        font-size: 18px;
        font-weight: bold;
        border-radius: 4px;
    }}
    QPushButton:hover {{
        background-color: #f0f1ff;
        color: {PRIMARY_COLOR};
    }}
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


# ── 基类 ──

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
        if dt is None:
            return ""
        delta = datetime.now() - dt
        if delta.days > 0:
            return f"{delta.days}天前"
        elif delta.seconds >= 3600:
            return f"{delta.seconds // 3600}小时前"
        elif delta.seconds >= 60:
            return f"{delta.seconds // 60}分钟前"
        return "刚刚"

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
            f"font-size: 15px; font-weight: 600; color: {TITLE_COLOR}; background: transparent;"
        )
        lbl.setWordWrap(True)
        return lbl

    def _build_desc_label(self) -> QLabel:
        lbl = QLabel(self._desc or "暂无描述")
        lbl.setStyleSheet(f"font-size: 12px; color: {SUBTITLE_COLOR}; background: transparent;")
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


# ── 待考核技能卡片 ──

class PendingToolCard(_SkillCardBase):
    """待考核技能卡片"""

    trial_requested = pyqtSignal(str)

    _STATUS_TEXT_MAP = {
        PendingToolStatus.PENDING_TRIAL: "等待考核",
        PendingToolStatus.TRIALING: "考核中",
        PendingToolStatus.TRIAL_SUCCESS: "考核通过",
        PendingToolStatus.TRIAL_FAILED: "考核未通过",
        PendingToolStatus.AWAITING_REAL_DATA: "等待数据",
        PendingToolStatus.PROMOTED: "已提升",
        PendingToolStatus.FAILED: "最终失败",
    }
    _STATUS_COLOR_MAP = {
        PendingToolStatus.PENDING_TRIAL: {"fg": SUBTITLE_COLOR, "bg": "#f1f3f5"},
        PendingToolStatus.TRIALING: {"fg": PRIMARY_COLOR, "bg": "#f0f1ff"},
        PendingToolStatus.TRIAL_SUCCESS: {"fg": "#28a745", "bg": "#f0fff4"},
        PendingToolStatus.TRIAL_FAILED: {"fg": "#dc3545", "bg": "#fff5f5"},
        PendingToolStatus.AWAITING_REAL_DATA: {"fg": "#fd7e14", "bg": "#fff8f0"},
        PendingToolStatus.PROMOTED: {"fg": "#6f42c1", "bg": "#f8f0ff"},
        PendingToolStatus.FAILED: {"fg": "#343a40", "bg": "#f1f3f5"},
    }
    _DEFAULT_STATUS_COLORS = {"fg": SUBTITLE_COLOR, "bg": "#f1f3f5"}

    def __init__(self, pending_tool: PendingTool, parent=None):
        super().__init__(
            card_id=pending_tool.pending_tool_id,
            name=pending_tool.tool_name,
            desc=pending_tool.tool_description,
            parent=parent,
        )
        self.pending_tool = pending_tool
        self._init_ui()

    def _init_ui(self):
        self.setStyleSheet(_CARD_STYLE.format(border="#e0e0e0", hover_border="#b0b5e0"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        status_lbl = QLabel(self._status_text())
        status_lbl.setStyleSheet(_STATUS_PILL_STYLE.format(**self._status_colors()))
        layout.addLayout(self._build_top_row(status_lbl))

        layout.addWidget(self._build_name_label())
        layout.addWidget(self._build_desc_label(), 1)

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

        if self.pending_tool.can_trial():
            btn = QPushButton("开始考核")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(34)
            btn.setStyleSheet(
                _ACTION_BTN_STYLE.format(
                    fg="white", bg=PRIMARY_COLOR, border="none", hover_bg="#4a58a8"
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
        return self._STATUS_TEXT_MAP.get(self.pending_tool.status, "未知状态")

    def _status_colors(self) -> dict:
        return self._STATUS_COLOR_MAP.get(self.pending_tool.status, self._DEFAULT_STATUS_COLORS)


# ── 已掌握技能卡片 ──

class PublishedToolCard(_SkillCardBase):
    """已掌握技能卡片"""

    execute_requested = pyqtSignal(str)

    _SOURCE_TEXT_MAP = {
        "manual": "手动创建",
        "intent": "意图生成",
        "trial": "考核转化",
    }

    def __init__(self, tool: Tool, parent=None):
        super().__init__(
            card_id=tool.tool_id,
            name=tool.tool_name,
            desc=tool.description,
            parent=parent,
        )
        self.tool = tool
        self._init_ui()

    def _init_ui(self):
        self.setStyleSheet(_CARD_STYLE.format(border="#c3e6cb", hover_border="#28a745"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        source_text = self._SOURCE_TEXT_MAP.get(self.tool.source, "未知")
        source_lbl = QLabel(source_text)
        source_lbl.setStyleSheet(_STATUS_PILL_STYLE.format(fg=PRIMARY_COLOR, bg="#f0f1ff"))
        layout.addLayout(self._build_top_row(source_lbl))

        layout.addWidget(self._build_name_label())
        layout.addWidget(self._build_desc_label(), 1)

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

        if param_count == 0:
            btn = QPushButton("执行")
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedHeight(34)
            btn.setStyleSheet(
                _ACTION_BTN_STYLE.format(
                    fg="white", bg="#28a745", border="none", hover_bg="#218838"
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
                    fg=SUBTITLE_COLOR, bg="#f8f9fa", border="1px solid #e0e0e0", hover_bg="#e9ecef"
                )
            )
            layout.addWidget(btn)


class SkillCompositionCard(_SkillCardBase):
    """技能组合卡片"""

    test_requested = pyqtSignal(str)
    publish_requested = pyqtSignal(str)
    offline_requested = pyqtSignal(str)

    _STATUS_STYLE_MAP = {
        "draft": {"text": "草稿", "fg": "#856404", "bg": "#fff3cd"},
        "published": {"text": "已发布", "fg": "#155724", "bg": "#d4edda"},
        "offline": {"text": "已下线", "fg": "#495057", "bg": "#e9ecef"},
    }

    def __init__(self, composition: SkillComposition, parent=None):
        super().__init__(
            card_id=composition.composition_id,
            name=composition.composition_name,
            desc=composition.description or composition.applicability,
            parent=parent,
        )
        self.composition = composition
        self._init_ui()

    def _init_ui(self):
        border = "#d8dee9" if self.composition.status != "published" else "#b7e4c7"
        hover_border = "#4c6ef5" if self.composition.status != "published" else "#2f9e44"
        self.setStyleSheet(_CARD_STYLE.format(border=border, hover_border=hover_border))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        top_left = QWidget()
        top_left_layout = QHBoxLayout(top_left)
        top_left_layout.setContentsMargins(0, 0, 0, 0)
        top_left_layout.setSpacing(6)

        status_cfg = self._STATUS_STYLE_MAP.get(
            self.composition.status,
            {"text": self.composition.status, "fg": SUBTITLE_COLOR, "bg": "#f1f3f5"},
        )
        status_lbl = QLabel(status_cfg["text"])
        status_lbl.setStyleSheet(
            _STATUS_PILL_STYLE.format(fg=status_cfg["fg"], bg=status_cfg["bg"])
        )
        top_left_layout.addWidget(status_lbl)

        mode_text = MODE_DISPLAY_TEXT.get(self.composition.mode, self.composition.mode)
        mode_lbl = QLabel(mode_text)
        mode_lbl.setStyleSheet(_STATUS_PILL_STYLE.format(fg=PRIMARY_COLOR, bg="#f0f1ff"))
        top_left_layout.addWidget(mode_lbl)

        if self.composition.needs_review:
            review_lbl = QLabel("待复核")
            review_lbl.setStyleSheet(_STATUS_PILL_STYLE.format(fg="#c92a2a", bg="#fff5f5"))
            top_left_layout.addWidget(review_lbl)

        top_left_layout.addStretch()
        layout.addLayout(self._build_top_row(top_left))

        layout.addWidget(self._build_name_label())
        layout.addWidget(self._build_desc_label(), 1)

        meta_row = QHBoxLayout()
        member_lbl = QLabel(f"成员: {len(self.composition.members)}")
        member_lbl.setStyleSheet(_META_STYLE)
        meta_row.addWidget(member_lbl)
        meta_row.addStretch()
        if self.composition.updated_at:
            time_lbl = QLabel(_SkillCardBase._format_time(self.composition.updated_at))
            time_lbl.setStyleSheet(_META_STYLE)
            meta_row.addWidget(time_lbl)
        layout.addLayout(meta_row)

        btn = QPushButton("试一下")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setFixedHeight(34)
        btn.setStyleSheet(
            _ACTION_BTN_STYLE.format(
                fg="white", bg=PRIMARY_COLOR, border="none", hover_bg="#4a58a8"
            )
        )
        btn.clicked.connect(lambda: self.test_requested.emit(self.composition.composition_id))
        layout.addWidget(btn)

    def _show_menu(self):
        menu = QMenu(self)
        menu.setStyleSheet(_MENU_STYLE.format(selected_color="#f0f1ff"))

        edit_action = QAction("编辑", self)
        edit_action.triggered.connect(lambda: self.edit_requested.emit(self._card_id))
        menu.addAction(edit_action)

        if self.composition.status == "draft":
            publish_action = QAction("发布", self)
            publish_action.triggered.connect(lambda: self.publish_requested.emit(self._card_id))
            menu.addAction(publish_action)

            delete_action = QAction("删除", self)
            delete_action.triggered.connect(lambda: self.delete_requested.emit(self._card_id))
            menu.addAction(delete_action)
        elif self.composition.status == "published":
            offline_action = QAction("下线", self)
            offline_action.triggered.connect(lambda: self.offline_requested.emit(self._card_id))
            menu.addAction(offline_action)
        elif self.composition.status == "offline":
            publish_action = QAction("重新发布", self)
            publish_action.triggered.connect(lambda: self.publish_requested.emit(self._card_id))
            menu.addAction(publish_action)

            delete_action = QAction("删除", self)
            delete_action.triggered.connect(lambda: self.delete_requested.emit(self._card_id))
            menu.addAction(delete_action)

        menu.exec(self._more_btn.mapToGlobal(self._more_btn.rect().bottomLeft()))


# ── 失败记录卡片 ──

class FailureCard(_SkillCardBase):
    """失败记录卡片"""

    retry_requested = pyqtSignal(str, str)   # workflow_id, failed_stage
    dismiss_requested = pyqtSignal(str)       # workflow_id

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

        try:
            stage_text = AgentType(self._record.failed_stage).display_name
        except ValueError:
            stage_text = self._record.failed_stage
        stage_lbl = QLabel(stage_text)
        stage_lbl.setStyleSheet(_STATUS_PILL_STYLE.format(fg="#dc3545", bg="#fff5f5"))
        layout.addLayout(self._build_top_row(stage_lbl))

        layout.addWidget(self._build_name_label())
        layout.addWidget(self._build_desc_label(), 1)

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

        self._action_widget = QWidget()
        action_layout = QHBoxLayout(self._action_widget)
        action_layout.setContentsMargins(0, 0, 0, 0)

        self._retry_btn = QPushButton("重试")
        self._retry_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._retry_btn.setFixedHeight(34)
        self._retry_btn.setStyleSheet(
            _ACTION_BTN_STYLE.format(
                fg="white", bg="#dc3545", border="none", hover_bg="#c82333"
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
