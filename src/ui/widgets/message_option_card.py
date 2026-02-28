"""
消息选项卡片组件

用于在对话框内显示单个确认问题及其选项。
支持列表式确认交互，问题卡片放在对话气泡内。
"""

from typing import Dict, List, Optional
from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QFrame,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from src.utils.logger import get_logger

logger = get_logger(__name__)


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
        self._selected_value: Optional[str] = None
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
        self._selected_value = None

        # 更新问题文本（包含序号）
        index = question_data.get("index", 1)
        total = question_data.get("total", 1)
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
                is_recommended=(opt.get("value") == recommended)
            )

        self.logger.debug(f"设置问题: {question_data.get('id')}, 选项数: {len(options)}")

    def _clear_options(self):
        """清除所有选项按钮"""
        for btn in self._option_buttons:
            btn.deleteLater()
        self._option_buttons.clear()

    def _add_option_button(
        self,
        value: str,
        label: str,
        impact: str = "",
        is_recommended: bool = False
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

        # 如果是推荐选项，默认选中
        if is_recommended:
            btn.setChecked(True)
            self._set_button_style(btn, "selected", is_recommended)
            self._selected_value = value

    def _set_button_style(self, btn: QPushButton, state: str, is_recommended: bool = False):
        """设置按钮样式

        Args:
            btn: 按钮对象
            state: 状态 ("normal" | "selected")
            is_recommended: 是否是推荐选项
        """
        if state == "selected":
            # 用户选中状态：浅绿色
            btn.setStyleSheet("""
                QPushButton {
                    text-align: left;
                    padding-left: 12px;
                    background-color: #c8e6c9;
                    border: 2px solid #4caf50;
                    border-radius: 6px;
                    color: #2e7d32;
                    font-weight: 500;
                }
            """)
        else:
            # 未选中状态：无特殊颜色
            btn.setStyleSheet("""
                QPushButton {
                    text-align: left;
                    padding-left: 12px;
                    background-color: #ffffff;
                    border: 1px solid #e0e0e0;
                    border-radius: 6px;
                    color: #424242;
                }
            """)

    def _on_option_clicked(self, value: str, btn: QPushButton):
        """处理选项点击"""
        self._selected_value = value

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

    def get_selected_value(self) -> Optional[str]:
        """获取当前选中的值"""
        return self._selected_value

    def get_question_id(self) -> Optional[str]:
        """获取当前问题 ID"""
        if self._question_data:
            return self._question_data.get("id")
        return None


class InvalidatedQuestionsCard(QWidget):
    """
    废弃问题卡片组件

    显示被用户打断废弃的确认问题。
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # 主布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 卡片容器
        self.card = QFrame()
        self.card.setObjectName("invalidated_questions_card")
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(16, 12, 16, 12)
        card_layout.setSpacing(8)

        # 警告标题
        warning_label = QLabel("⚠️ 以下问题已失效（用户提供了新的反馈）")
        warning_label.setObjectName("warning_label")
        warning_label.setWordWrap(True)
        card_layout.addWidget(warning_label)

        # 废弃问题列表容器
        self.questions_container = QWidget()
        self.questions_layout = QVBoxLayout(self.questions_container)
        self.questions_layout.setContentsMargins(0, 0, 0, 0)
        self.questions_layout.setSpacing(4)
        card_layout.addWidget(self.questions_container)

        layout.addWidget(self.card)

    def set_invalidated_questions(self, questions: List[Dict]):
        """
        设置废弃的问题列表

        Args:
            questions: 废弃问题列表，每个元素包含：
                - id: 问题 ID
                - answer: 用户之前的回答
        """
        # 清除旧内容
        while self.questions_layout.count():
            child = self.questions_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        # 添加废弃问题
        for q in questions:
            q_text = f'<s>问题 {q.get("id")}: 已选答案 - {q.get("answer", "")}</s>'
            q_label = QLabel(q_text)
            q_label.setObjectName("invalidated_question_label")
            q_label.setWordWrap(True)
            q_label.setTextFormat(Qt.TextFormat.RichText)
            self.questions_layout.addWidget(q_label)


class ConfirmationSummaryCard(QWidget):
    """
    确认进度摘要卡片组件

    显示已确认问题的摘要和进度。
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # 主布局
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 卡片容器
        self.card = QFrame()
        self.card.setObjectName("confirmation_summary_card")
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(16, 12, 16, 12)
        card_layout.setSpacing(8)

        # 标题
        self.title_label = QLabel("✅ 已确认的问题")
        self.title_label.setObjectName("summary_title_label")
        card_layout.addWidget(self.title_label)

        # 已确认问题列表容器
        self.answers_container = QWidget()
        self.answers_layout = QVBoxLayout(self.answers_container)
        self.answers_layout.setContentsMargins(0, 0, 0, 0)
        self.answers_layout.setSpacing(4)
        card_layout.addWidget(self.answers_container)

        # 剩余问题提示
        self.remaining_label = QLabel()
        self.remaining_label.setObjectName("remaining_label")
        card_layout.addWidget(self.remaining_label)

        layout.addWidget(self.card)

    def set_summary(self, answered: List[Dict], remaining: int, total: int):
        """
        设置确认摘要

        Args:
            answered: 已回答的问题列表
            remaining: 剩余问题数
            total: 总问题数
        """
        # 清除旧内容
        while self.answers_layout.count():
            child = self.answers_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        # 添加已回答的问题
        for ans in answered:
            ans_text = f"✓ {ans.get('id')}: {ans.get('answer', '')}"
            ans_label = QLabel(ans_text)
            ans_label.setObjectName("answered_question_label")
            ans_label.setWordWrap(True)
            self.answers_layout.addWidget(ans_label)

        # 更新剩余问题提示
        if remaining > 0:
            self.remaining_label.setText(f"📌 还有 {remaining} 个问题需要确认")
            self.remaining_label.show()
        else:
            self.remaining_label.hide()


class ConfirmButtonCard(QWidget):
    """
    确认按钮卡片组件

    统一的确认按钮，根据是否有确认问题动态改变行为：
    - 有问题：显示"提交问题"按钮
    - 无问题：显示"最终意图确认"按钮
    """

    # 定义信号
    confirm_clicked = pyqtSignal()  # 确认/提交按钮点击

    def __init__(self, parent=None):
        super().__init__(parent)

        # 内部状态
        self._has_questions = False
        self._enabled = True

        # 主布局
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(0, 16, 0, 0)
        self.main_layout.setSpacing(8)

        # 进度提示
        self.progress_label = QLabel("✅ 分析完成，请确认")
        self.progress_label.setObjectName("confirm_progress_label")
        self.progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.main_layout.addWidget(self.progress_label)

        # 确认按钮（单一按钮）
        self.confirm_button = QPushButton("最终意图确认")
        self.confirm_button.setObjectName("confirm_tool_button")
        self.confirm_button.setMinimumHeight(48)
        self.confirm_button.setMinimumWidth(180)
        self.confirm_button.clicked.connect(self._on_confirm_clicked)
        self.main_layout.addWidget(self.confirm_button)

    def _on_confirm_clicked(self):
        """处理确认按钮点击"""
        self.confirm_clicked.emit()

    def set_has_questions(self, has_questions: bool):
        """
        设置是否有确认问题，动态改变按钮文字和行为

        Args:
            has_questions: 是否有确认问题
        """
        self._has_questions = has_questions

        if has_questions:
            # 有问题：显示"提交问题"
            self.progress_label.setText("📝 请回答所有问题后提交")
            self.progress_label.setStyleSheet("color: #6c757d;")
            self.confirm_button.setText("提交问题")
            self.confirm_button.setObjectName("submit_questions_button")
        else:
            # 无问题：显示"最终意图确认"
            self.progress_label.setText("✅ 分析完成，请确认")
            self.progress_label.setStyleSheet("color: #28a745;")
            self.confirm_button.setText("最终意图确认")
            self.confirm_button.setObjectName("confirm_tool_button")

    def set_enabled(self, enabled: bool):
        """设置按钮启用状态"""
        self._enabled = enabled
        self.confirm_button.setEnabled(enabled)

        if not self._has_questions:
            # 无问题时，按钮始终可用
            self.progress_label.setText("✅ 分析完成，请确认")
            self.progress_label.setStyleSheet("color: #28a745;")
        elif enabled:
            # 有问题且已全部回答
            self.progress_label.setText("✅ 所有问题已回答，可以提交")
            self.progress_label.setStyleSheet("color: #28a745;")
        else:
            # 有问题但未全部回答
            self.progress_label.setText("📝 请回答所有问题后提交")
            self.progress_label.setStyleSheet("color: #6c757d;")

    def update_progress(self, answered: int, total: int):
        """更新进度提示"""
        if total == 0:
            # 无问题
            self._has_questions = False
            self.set_has_questions(False)
            self.set_enabled(True)
        elif answered < total:
            # 有问题，未全部回答
            self._has_questions = True
            self.set_has_questions(True)
            self.progress_label.setText(f"📝 已回答 {answered}/{total} 个问题")
            self.progress_label.setStyleSheet("color: #6c757d;")
            self.confirm_button.setEnabled(False)
        else:
            # 有问题，已全部回答
            self._has_questions = True
            self.set_has_questions(True)
            self.progress_label.setText("✅ 所有问题已回答，可以提交")
            self.progress_label.setStyleSheet("color: #28a745;")
            self.confirm_button.setEnabled(True)


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

    def get_answers(self) -> Dict[str, str]:
        """获取所有答案"""
        return self._answers.copy()

    def get_total_questions(self) -> int:
        """获取问题总数"""
        return len(self._questions)

    def is_all_answered(self) -> bool:
        """检查是否所有问题都已回答"""
        return len(self._answers) == len(self._questions)

    def get_unanswered_questions(self) -> List[str]:
        """获取未回答问题的 ID 列表"""
        answered_ids = set(self._answers.keys())
        all_ids = {q.get("id") for q in self._questions}
        return list(all_ids - answered_ids)