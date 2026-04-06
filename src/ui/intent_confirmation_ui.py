"""
Intent 确认 UI 组件

提供意图确认界面，采用统一交互模式：
1. 显示分析结果和确认问题（可能没有问题）
2. 有问题时显示"提交问题"按钮 → 提交后重新分析
3. 无问题时显示"最终意图确认"按钮 → 直接生成工具
"""

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpacerItem,
    QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from typing import List, Optional

from src.business.intent.intent_models import Intent, IntentStatus
from src.ui.widgets.message_option_card import (
    MultiQuestionCard,
)
from src.ui.widgets.message_input import MessageInputEdit
from src.ui.widgets.layout_utils import clear_layout, scroll_to_bottom
from src.utils.logger import get_logger


class IntentConfirmationUI(QWidget):
    """Intent 确认 UI 组件（列表式交互）"""

    # 用于与后端通信的信号
    analyze_intent_request = pyqtSignal(str, str)  # intent_id, user_message

    # Agent 模式信号
    agent_resume_request = pyqtSignal(str, dict)  # thread_id, resume_data

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger(__name__)

        # 当前意图数据
        self.current_intent: Optional[Intent] = None

        # Agent 模式相关
        self._agent_thread_id: Optional[str] = None

        # UI 组件引用
        self._multi_question_card: Optional[MultiQuestionCard] = None

        self.init_ui()

    def init_ui(self):
        """初始化用户界面"""
        # 创建主布局
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # === 顶部状态栏 ===
        self.status_bar = QWidget()
        self.status_bar.setObjectName("intent_status_bar")
        status_layout = QHBoxLayout(self.status_bar)
        status_layout.setContentsMargins(24, 16, 24, 16)
        status_layout.setSpacing(16)

        # 状态图标和文字
        self.status_icon = QLabel("🔍")
        self.status_icon.setObjectName("status_icon")
        status_layout.addWidget(self.status_icon)

        self.status_label = QLabel("等待分析...")
        self.status_label.setObjectName("status_label")
        status_layout.addWidget(self.status_label, 1)

        # 进度指示器
        self.progress_indicator = QLabel()
        self.progress_indicator.setObjectName("progress_indicator")
        status_layout.addWidget(self.progress_indicator)

        main_layout.addWidget(self.status_bar)

        # === 主内容区（全宽对话框） ===
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setSpacing(0)
        content_layout.setContentsMargins(0, 0, 0, 0)

        # 消息展示区域
        messages_scroll = QScrollArea()
        messages_scroll.setWidgetResizable(True)
        messages_scroll.setObjectName("intent_messages_scroll")
        messages_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        messages_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.messages_container = QWidget()
        self.messages_container.setObjectName("intent_messages_container")
        self.messages_layout = QVBoxLayout(self.messages_container)
        self.messages_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.messages_layout.setSpacing(16)
        self.messages_layout.setContentsMargins(24, 24, 24, 24)
        messages_scroll.setWidget(self.messages_container)

        content_layout.addWidget(messages_scroll, 1)

        main_layout.addWidget(content_widget, 1)

        # === 输入区域 ===
        input_container = QWidget()
        input_container.setObjectName("intent_input_container")
        input_layout = QVBoxLayout(input_container)
        input_layout.setContentsMargins(24, 16, 24, 16)
        input_layout.setSpacing(12)

        # 输入框
        self.message_input = MessageInputEdit()
        self.message_input.setObjectName("intent_message_input")
        self.message_input.setPlaceholderText(
            "输入消息与 AI 沟通... (Enter 发送，Shift+Enter 换行)"
        )
        self.message_input.setMinimumHeight(80)
        self.message_input.setMaximumHeight(150)
        self.message_input.textChanged.connect(self._on_input_changed)
        self.message_input.send_requested.connect(self._on_send_message)
        input_layout.addWidget(self.message_input)

        # 底部操作栏
        bottom_bar = QHBoxLayout()
        bottom_bar.setSpacing(12)

        hint_label = QLabel("💡 Enter 发送 | Shift+Enter 换行 | 可随时发送反馈")
        hint_label.setObjectName("intent_input_hint")
        bottom_bar.addWidget(hint_label)

        bottom_bar.addStretch()

        # 取消按钮
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setObjectName("intent_cancel_button")
        self.cancel_button.setMinimumWidth(100)
        self.cancel_button.setMinimumHeight(36)
        self.cancel_button.clicked.connect(self._on_cancel_clicked)
        bottom_bar.addWidget(self.cancel_button)

        # 发送按钮
        self.send_button = QPushButton("发送")
        self.send_button.setObjectName("intent_send_button")
        self.send_button.setEnabled(False)
        self.send_button.setMinimumWidth(100)
        self.send_button.setMinimumHeight(36)
        self.send_button.clicked.connect(self._on_send_message)
        bottom_bar.addWidget(self.send_button)

        input_layout.addLayout(bottom_bar)
        main_layout.addWidget(input_container)

        # 初始化状态
        self._set_analyzing_state()

    def reset(self):
        """重置页面状态，准备新的会话"""
        self._set_analyzing_state()

    def _setup_trial_input_state(self, workflow_id: str) -> None:
        """设置 trial 对话的输入就绪状态（去掉加载提示，启用输入框）"""
        self._agent_thread_id = workflow_id
        self.current_intent = None

        self._remove_loading_label()
        self.status_label.setText("等待您的回复...")
        self.status_icon.setText("💬")
        self.progress_indicator.setText("")
        self.message_input.setEnabled(True)
        self.message_input.clear()
        self.send_button.setEnabled(False)

    def preload_trial_history(self, messages: List[dict]) -> None:
        """清空旧消息，渲染试用历史，不启用输入框（由后续 add_trial_question 事件激活）"""
        self._clear_messages()
        for msg in messages:
            role = msg.get("role", "assistant")
            content = msg.get("content", "")
            if content:
                self._add_message(role, content, scroll=False)
        if messages:
            QTimer.singleShot(100, self._scroll_to_bottom)

    def load_trial_history(self, messages: List[dict], workflow_id: str) -> None:
        """加载并渲染 trial 历史对话，开启输入框等待用户继续"""
        self._clear_messages()
        self._setup_trial_input_state(workflow_id)

        # 批量添加消息，避免每条消息都触发一次滚动定时器
        for msg in messages:
            role = msg.get("role", "assistant")
            content = msg.get("content", "")
            if content:
                self._add_message(role, content, scroll=False)

        QTimer.singleShot(100, self._scroll_to_bottom)

    def add_trial_question(self, question: str, workflow_id: str) -> None:
        """添加单条 trial Agent 提问并开启输入框（Agent 实时提问时调用）"""
        self._setup_trial_input_state(workflow_id)
        self._add_message("assistant", question)

    def _set_analyzing_state(self):
        """设置分析中状态"""
        self.status_label.setText("正在分析您的操作...")
        self.status_icon.setText("🔍")
        self.progress_indicator.setText("")

        # 重新启用输入（可能被之前的会话禁用）
        self.message_input.setEnabled(True)
        self.message_input.clear()
        self.send_button.setEnabled(False)

        # 重置 Agent 模式上下文
        self._agent_thread_id = None
        self.current_intent = None

        # 清空消息区域
        self._clear_messages()

        # 添加加载提示
        loading_label = QLabel("⏳ AI 正在分析您的操作，请稍候...")
        loading_label.setObjectName("intent_loading_label")
        loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.messages_layout.addWidget(loading_label)

    def _clear_messages(self):
        """清空消息区域"""
        clear_layout(self.messages_layout)
        # 重置组件引用
        self._multi_question_card = None

    def _add_message(self, role: str, content: str, scroll: bool = True):
        """添加消息到对话区域

        Args:
            role: 消息角色 ("user" 或 "assistant")
            content: 消息内容
            scroll: 是否自动滚动到底部（批量添加时传 False，由调用方统一滚动）
        """
        # 创建消息容器
        message_container = QWidget()
        message_container.setObjectName(f"intent_message_row_{role}")
        container_layout = QHBoxLayout(message_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(8)

        # 根据角色添加头像和对齐
        if role == "user":
            container_layout.addStretch()

        # 创建消息气泡
        message_bubble = QWidget()
        message_bubble.setObjectName(f"intent_message_bubble_{role}")
        message_bubble.setMaximumWidth(600)

        bubble_layout = QVBoxLayout(message_bubble)
        bubble_layout.setContentsMargins(16, 12, 16, 12)
        bubble_layout.setSpacing(0)

        # 消息内容
        content_label = QLabel(content)
        content_label.setObjectName(f"intent_message_content_{role}")
        content_label.setWordWrap(True)
        content_label.setTextFormat(Qt.TextFormat.MarkdownText)
        content_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        bubble_layout.addWidget(content_label)

        container_layout.addWidget(message_bubble)

        if role == "assistant":
            container_layout.addStretch()

        # 添加到消息容器
        self.messages_layout.addWidget(message_container)

        # 滚动到底部
        if scroll:
            QTimer.singleShot(100, self._scroll_to_bottom)

    def _scroll_to_bottom(self):
        """滚动消息区域到底部"""
        scroll_to_bottom("intent_messages_scroll", self)

    def _on_input_changed(self):
        """输入框内容变化"""
        text = self.message_input.toPlainText().strip()
        self.send_button.setEnabled(len(text) > 0)

    def _on_send_message(self):
        """发送消息（用户反馈）"""
        message = self.message_input.toPlainText().strip()
        if not message:
            return

        self.logger.info(f"发送反馈消息: {message[:50]}...")

        # 添加用户消息
        self._add_message("user", message)

        # 清空输入框
        self.message_input.clear()

        # 发送反馈到后端
        if hasattr(self, "_agent_thread_id") and self._agent_thread_id:
            resume_data = {"action": "feedback", "feedback": message}
            self.agent_resume_request.emit(self._agent_thread_id, resume_data)

            # 更新状态
            self.status_label.setText("正在处理您的反馈...")

    def _on_cancel_clicked(self):
        """取消按钮点击"""
        if self.current_intent:
            self.logger.info(f"取消意图: {self.current_intent.intent_id}")
            self.current_intent.cancel()

        # 关闭对话框（如果在对话框中）
        self.parent().close() if self.parent() else None

    def set_status_text(self, text: str):
        """设置状态栏文本（供外部调用，避免直接访问内部 status_label）"""
        self.status_label.setText(text)

    def load_intent_from_agent(self, intent_data: dict, message: str, thread_id: str) -> None:
        """
        从 Agent 加载意图数据（一次性显示所有问题）

        Args:
            intent_data: Agent 传来的意图数据（包含所有问题）
            message: 确认消息
            thread_id: Agent 会话 ID（用于后续恢复）
        """
        self.logger.info(f"从 Agent 加载意图数据，keys: {intent_data.keys()}")

        # 保存 thread_id 用于后续恢复 Agent
        self._agent_thread_id = thread_id

        try:
            # 提取基本信息
            intent_info = intent_data.get("intent", {})
            parameters = intent_info.get("parameters", {})

            # 处理 parameters 字段
            if isinstance(parameters, list):
                core_operations = parameters
            elif isinstance(parameters, dict):
                core_operations = parameters.get("steps", [])
            else:
                core_operations = []

            # 构建 Intent 对象
            intent = Intent(
                intent_id=thread_id,
                core_operations=core_operations,
                target=intent_data.get("target"),
                business_scenario=intent_data.get("business_scenario"),
                expected_results=intent_info.get("expected_results", []),
                analysis_confidence=intent_info.get("confidence", 0.8),
            )
            intent.status = IntentStatus.PENDING_CONFIRMATION

            self.current_intent = intent

            # 更新 UI（线程安全）
            QTimer.singleShot(0, lambda: self._update_ui_from_agent(intent_data, message))

        except Exception as e:
            self.logger.error(f"从 Agent 加载意图失败: {e}", exc_info=True)

    def _update_ui_from_agent(self, intent_data: dict, message: str):
        """更新 UI（来自 Agent 的数据）- 根据是否有问题显示不同按钮"""
        # 统一使用一个 UI 方法，不再区分阶段
        self._update_confirmation_ui(intent_data, message)

    def _update_confirmation_ui(self, intent_data: dict, message: str):
        """显示分析结果并自动确认（问题已通过自然语言对话处理）"""
        # 更新状态栏
        self.status_label.setText("分析完成")
        self.progress_indicator.setText("")
        self.status_icon.setText("✅")

        # 移除 loading_label（如果存在）
        self._remove_loading_label()

        # 检查是否是反馈后的更新（有 AI 回复）
        ai_response = intent_data.get("ai_response")
        if ai_response and self._multi_question_card:
            self._multi_question_card.setEnabled(False)
            self._add_message("assistant", ai_response)

        # 显示分析摘要
        self._add_assistant_bubble_with_questions(intent_data, message, [])

        # 添加弹性空间
        spacer = QSpacerItem(0, 0, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding)
        self.messages_layout.addItem(spacer)

        # 滚动到底部
        QTimer.singleShot(100, self._scroll_to_bottom)

    def _remove_loading_label(self):
        """移除加载提示标签"""
        for i in range(self.messages_layout.count()):
            item = self.messages_layout.itemAt(i)
            if item and item.widget():
                widget = item.widget()
                if hasattr(widget, "objectName") and widget.objectName() == "intent_loading_label":
                    widget.deleteLater()
                    return

    def _add_assistant_bubble_with_questions(
        self, intent_data: dict, message: str, questions: list
    ):
        """创建包含分析摘要和问题的 AI 消息气泡"""
        # 创建消息容器
        message_container = QWidget()
        message_container.setObjectName("intent_message_row_assistant")
        container_layout = QHBoxLayout(message_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(8)

        # 创建消息气泡
        message_bubble = QWidget()
        message_bubble.setObjectName("intent_message_bubble_assistant")
        message_bubble.setMaximumWidth(900)  # 限制最大宽度

        bubble_layout = QVBoxLayout(message_bubble)
        bubble_layout.setContentsMargins(16, 14, 16, 14)
        bubble_layout.setSpacing(12)

        # === 1. 顶部消息 ===
        if message:
            msg_label = QLabel(message)
            msg_label.setObjectName("confirmation_message_label")
            msg_label.setWordWrap(True)
            msg_label.setTextFormat(Qt.TextFormat.MarkdownText)
            bubble_layout.addWidget(msg_label)

        # === 2. 分析摘要 ===
        summary_widget = self._create_analysis_summary_widget(intent_data)
        if summary_widget:
            bubble_layout.addWidget(summary_widget)

        # === 3. 确认问题 ===
        if questions:
            self._multi_question_card = MultiQuestionCard()
            self._multi_question_card.set_questions(questions)
            self._multi_question_card.all_questions_answered.connect(
                self._on_all_questions_answered
            )
            bubble_layout.addWidget(self._multi_question_card)

        container_layout.addWidget(message_bubble)
        container_layout.addStretch()

        # 添加到消息容器
        self.messages_layout.addWidget(message_container)

    def _create_analysis_summary_widget(self, intent_data: dict) -> QWidget:
        """创建分析摘要组件"""
        pattern = intent_data.get("pattern_recognition", {})
        intent_analysis = intent_data.get("intent_analysis", {})
        tool_desc = intent_data.get("tool_description", {})

        # 如果没有任何摘要信息，返回 None
        if not pattern and not intent_analysis and not tool_desc:
            return None

        summary_widget = QWidget()
        summary_layout = QVBoxLayout(summary_widget)
        summary_layout.setContentsMargins(0, 8, 0, 8)
        summary_layout.setSpacing(6)

        # 模式识别
        if pattern and pattern.get("primary_pattern"):
            pattern_text = f"📋 操作模式：{pattern['primary_pattern']}"
            if pattern.get("confidence"):
                pattern_text += f"（置信度 {pattern['confidence']:.0%}）"
            pattern_label = QLabel(pattern_text)
            pattern_label.setObjectName("summary_item_label")
            pattern_label.setWordWrap(True)
            summary_layout.addWidget(pattern_label)

        # 深层意图
        if intent_analysis and intent_analysis.get("deep_intent"):
            intent_label = QLabel(f"🎯 深层意图：{intent_analysis['deep_intent']}")
            intent_label.setObjectName("summary_item_label")
            intent_label.setWordWrap(True)
            summary_layout.addWidget(intent_label)

        # 工具描述
        if tool_desc and tool_desc.get("natural_language_description"):
            tool_label = QLabel(tool_desc["natural_language_description"])
            tool_label.setObjectName("summary_desc_label")
            tool_label.setWordWrap(True)
            tool_label.setTextFormat(Qt.TextFormat.MarkdownText)
            summary_layout.addWidget(tool_label)

        return summary_widget

    def _on_all_questions_answered(self, all_answered: bool):
        """所有确认问题已回答时的回调"""
        self.logger.debug(f"所有确认问题已回答: {all_answered}")

    def cleanup(self):
        """清理资源"""
        pass
