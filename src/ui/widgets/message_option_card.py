"""
消息选项卡片组件

用于在对话框内显示单个确认问题及其选项。
支持列表式确认交互，问题卡片放在对话气泡内。
"""

from typing import Dict, List, Optional
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
)
from PyQt6.QtCore import Qt, pyqtSignal

from src.utils.logger import get_logger


class MessageOptionCard(QWidget):
    """
    消息选项卡片组件

    用于在对话气泡内显示单个确认问题及其选项。

    信号：
    - option_selected: 当用户选择一个选项时发射 (question_id, selected_value)
    """

    # 定义信号
    option_selected = pyqtSignal(str, str)  # (question_id, selected_value)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger(__name__)

        # 当前问题数据
        self._question_data: Optional[Dict] = None
        self._option_buttons: List[QPushButton] = []

        self.init_ui()

    def init_ui(self):
        """初始化用户界面"""
        # 主布局 - 无边距，由外部气泡控制
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(8)

        # 问题文本
        self.question_label = QLabel()
        self.question_label.setObjectName("confirmation_question_label")
        self.question_label.setWordWrap(True)
        self.question_label.setTextFormat(Qt.TextFormat.RichText)
        self.main_layout.addWidget(self.question_label)

        # 上下文说明（可选）
        self.context_label = QLabel()
        self.context_label.setObjectName("confirmation_context_label")
        self.context_label.setWordWrap(True)
        self.context_label.hide()  # 默认隐藏
        self.main_layout.addWidget(self.context_label)

        # 选项容器
        self.options_container = QWidget()
        self.options_container.setObjectName("confirmation_options_container")
        self.options_layout = QVBoxLayout(self.options_container)
        self.options_layout.setContentsMargins(0, 0, 0, 0)
        self.options_layout.setSpacing(6)
        self.main_layout.addWidget(self.options_container)

    def set_question(self, question_data: Dict):
        """
        设置问题数据

        Args:
            question_data: 问题数据，包含：
                - id: 问题 ID
                - index: 当前问题索引（1-based）
                - total: 总问题数
                - question: 问题文本
                - context: 上下文说明（可选）
                - options: 选项列表 [{"value": "...", "label": "...", "impact": "..."}]
                - recommended: 推荐选项值（可选）
        """
        self._question_data = question_data

        # 更新问题文本（包含序号）
        index = question_data.get("index", 1)
        question_text = question_data.get("question", "")
        self.question_label.setText(f"<b>Q{index}.</b> {question_text}")

        # 更新上下文说明
        context = question_data.get("context", "")
        if context:
            self.context_label.setText(f"💡 {context}")
            self.context_label.show()
        else:
            self.context_label.hide()

        # 清除旧选项
        self._clear_options()

        # 添加新选项
        options = question_data.get("options", [])
        recommended = question_data.get("recommended", "")

        for opt in options:
            self._add_option_button(
                value=opt.get("value", ""),
                label=opt.get("label", ""),
                impact=opt.get("impact", ""),
                is_recommended=(opt.get("value") == recommended),
            )

        self.logger.debug(f"设置问题: {question_data.get('id')}, 选项数: {len(options)}")

    def _clear_options(self):
        """清除所有选项按钮"""
        for btn in self._option_buttons:
            btn.deleteLater()
        self._option_buttons.clear()

    def _add_option_button(
        self, value: str, label: str, impact: str = "", is_recommended: bool = False
    ):
        """
        添加一个选项按钮

        Args:
            value: 选项值
            label: 选项标签
            impact: 选项影响说明
            is_recommended: 是否是推荐选项
        """
        # 创建选项容器
        option_widget = QWidget()
        option_layout = QVBoxLayout(option_widget)
        option_layout.setContentsMargins(0, 0, 0, 0)
        option_layout.setSpacing(2)

        # 创建选项按钮
        btn = QPushButton()
        btn.setObjectName("confirmation_option_button")
        btn.setCheckable(True)
        btn.setAutoExclusive(True)

        # 设置按钮文本
        btn_text = label
        if is_recommended:
            btn_text = f"⭐ {label}"
            btn.setProperty("recommended", True)
        btn.setText(btn_text)

        # 设置最小高度
        btn.setMinimumHeight(36)

        # 设置基础样式
        self._set_button_style(btn, "normal", is_recommended)

        # 连接点击事件
        btn.clicked.connect(lambda checked, v=value, b=btn: self._on_option_clicked(v, b))

        # 存储按钮引用
        self._option_buttons.append(btn)
        option_layout.addWidget(btn)

        # 添加影响说明
        if impact:
            impact_label = QLabel(f"   ↳ {impact}")
            impact_label.setObjectName("confirmation_impact_label")
            impact_label.setWordWrap(True)
            option_layout.addWidget(impact_label)

        self.options_layout.addWidget(option_widget)

    def _set_button_style(self, btn: QPushButton, state: str, is_recommended: bool = False):
        """设置按钮样式

        Args:
            btn: 按钮对象
            state: 状态 ("normal" | "selected")
            is_recommended: 是否是推荐选项
        """
        if state == "selected":
            # 用户选中状态：浅绿色
            btn.setStyleSheet(
                """
                QPushButton {
                    text-align: left;
                    padding-left: 12px;
                    background-color: #c8e6c9;
                    border: 2px solid #4caf50;
                    border-radius: 6px;
                    color: #2e7d32;
                    font-weight: 500;
                }
            """
            )
        else:
            # 未选中状态：无特殊颜色
            btn.setStyleSheet(
                """
                QPushButton {
                    text-align: left;
                    padding-left: 12px;
                    background-color: #ffffff;
                    border: 1px solid #e0e0e0;
                    border-radius: 6px;
                    color: #424242;
                }
            """
            )

    def _on_option_clicked(self, value: str, btn: QPushButton):
        """处理选项点击"""
        # 更新所有按钮样式
        for b in self._option_buttons:
            recommended = b.property("recommended")
            if b == btn:
                # 当前选中：蓝色高亮
                self._set_button_style(b, "selected", recommended)
            else:
                # 取消选中
                self._set_button_style(b, "normal", recommended)

        if self._question_data:
            question_id = self._question_data.get("id", "")
            self.logger.info(f"用户选择: 问题={question_id}, 选项={value}")

            # 发射信号
            self.option_selected.emit(question_id, value)


class MultiQuestionCard(QWidget):
    """
    多问题列表卡片组件

    一次性显示所有确认问题，支持本地保存答案。
    所有问题放在一个对话气泡内。
    """

    # 定义信号
    all_questions_answered = pyqtSignal(bool)  # 所有问题都已回答时发射

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger(__name__)

        # 问题数据和答案
        self._questions: List[Dict] = []
        self._answers: Dict[str, str] = {}  # {question_id: selected_value}
        self._question_cards: List[MessageOptionCard] = []

        self.init_ui()

    def init_ui(self):
        """初始化用户界面"""
        # 主布局
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(20)  # 问题之间间距

        # 问题列表容器
        self.questions_container = QWidget()
        self.questions_layout = QVBoxLayout(self.questions_container)
        self.questions_layout.setContentsMargins(0, 0, 0, 0)
        self.questions_layout.setSpacing(20)

        self.main_layout.addWidget(self.questions_container)

    def set_questions(self, questions: List[Dict]):
        """
        设置问题列表

        Args:
            questions: 问题列表，每个问题包含：
                - id: 问题 ID
                - question: 问题文本
                - context: 上下文说明（可选）
                - options: 选项列表 [{"value": "...", "label": "...", "impact": "..."}]
                - recommended: 推荐选项值（可选）
        """
        # 清除旧问题
        self._clear_questions()

        self._questions = questions
        self._answers = {}

        # 添加新问题
        for i, q in enumerate(questions):
            card = MessageOptionCard()

            # 添加索引信息
            q_with_index = q.copy()
            q_with_index["index"] = i + 1
            q_with_index["total"] = len(questions)

            card.set_question(q_with_index)
            card.option_selected.connect(self._on_option_selected)

            self._question_cards.append(card)
            self.questions_layout.addWidget(card)

            # 添加分隔线（最后一个不加）
            if i < len(questions) - 1:
                separator = QFrame()
                separator.setObjectName("question_separator")
                separator.setFrameShape(QFrame.Shape.HLine)
                separator.setFixedHeight(1)
                self.questions_layout.addWidget(separator)

        self.logger.debug(f"设置 {len(questions)} 个问题")

    def _clear_questions(self):
        """清除所有问题卡片"""
        for card in self._question_cards:
            card.deleteLater()
        self._question_cards.clear()
        self._questions = []
        self._answers = {}

    def _on_option_selected(self, question_id: str, selected_value: str):
        """处理选项选中"""
        self._answers[question_id] = selected_value
        self.logger.info(f"问题 {question_id} 选择: {selected_value}")

        # 检查是否所有问题都已回答
        all_answered = len(self._answers) == len(self._questions)
        self.all_questions_answered.emit(all_answered)
