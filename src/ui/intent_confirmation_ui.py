"""
Intent 确认 UI 组件

提供意图确认界面，包括：
1. 结构化选项展示（勾选框）
2. 对话框（与 AI 聊天）
3. 实时更新意图展示
"""

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QCheckBox,
    QTextEdit,
    QFrame,
    QProgressBar,
    QMessageBox,
    QRadioButton,
    QButtonGroup,
    QGroupBox,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QThread
from PyQt6.QtGui import QKeyEvent
from typing import List, Dict, Any, Optional
import uuid

from src.business.intent.intent_models import Intent, IntentStatus
from src.utils.logger import get_logger


class MessageInputEdit(QTextEdit):
    """支持 Ctrl+Enter 发送的自定义输入框"""

    send_requested = pyqtSignal()  # 发送请求信号

    def keyPressEvent(self, event: QKeyEvent):
        """处理按键事件"""
        # Ctrl+Enter 或 Ctrl+Return 发送消息
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
                self.send_requested.emit()
                return

        # 其他按键正常处理
        super().keyPressEvent(event)


class IntentConfirmationUI(QWidget):
    """Intent 确认 UI 组件"""

    # 定义信号
    intent_confirmed = pyqtSignal(str)  # intent_id
    intent_cancelled = pyqtSignal(str)  # intent_id

    # 新增：用于与后端通信的信号
    analyze_intent_request = pyqtSignal(str, str)  # intent_id, user_message
    confirm_intent_request = pyqtSignal(str)  # intent_id

    # Agent 模式信号
    agent_resume_request = pyqtSignal(str, dict)  # thread_id, resume_data

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger(__name__)

        # 当前意图数据
        self.current_intent: Optional[Intent] = None

        # 聊天消息历史
        self.chat_messages: List[Dict[str, str]] = []  # {"role": "user"|"assistant", "content": "..."}

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

        main_layout.addWidget(self.status_bar)

        # === 主内容区（左右分栏） ===
        content_widget = QWidget()
        content_layout = QHBoxLayout(content_widget)
        content_layout.setSpacing(0)
        content_layout.setContentsMargins(0, 0, 0, 0)

        # 左侧：结构化选项展示区
        left_panel = self._create_left_panel()
        content_layout.addWidget(left_panel, 1)

        # 右侧：对话框区
        right_panel = self._create_right_panel()
        content_layout.addWidget(right_panel, 1)

        main_layout.addWidget(content_widget, 1)

        # === 底部操作栏 ===
        bottom_bar = QWidget()
        bottom_bar.setObjectName("intent_bottom_bar")
        bottom_layout = QHBoxLayout(bottom_bar)
        bottom_layout.setContentsMargins(24, 16, 24, 16)
        bottom_layout.setSpacing(12)

        bottom_layout.addStretch()

        # 取消按钮
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setObjectName("intent_cancel_button")
        self.cancel_button.setMinimumWidth(120)
        self.cancel_button.setMinimumHeight(40)
        self.cancel_button.clicked.connect(self._on_cancel_clicked)
        bottom_layout.addWidget(self.cancel_button)

        # 确认按钮
        self.confirm_button = QPushButton("确认并继续")
        self.confirm_button.setObjectName("intent_confirm_button")
        self.confirm_button.setMinimumWidth(140)
        self.confirm_button.setMinimumHeight(40)
        self.confirm_button.setEnabled(False)
        self.confirm_button.clicked.connect(self._on_confirm_clicked)
        bottom_layout.addWidget(self.confirm_button)

        main_layout.addWidget(bottom_bar)

        # 初始化状态
        self._set_analyzing_state()

    def _create_left_panel(self) -> QWidget:
        """创建左侧面板（结构化选项展示）"""
        panel = QWidget()
        panel.setObjectName("intent_left_panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(24, 24, 12, 24)
        layout.setSpacing(16)

        # 标题
        title = QLabel("📋 意图确认")
        title.setObjectName("intent_section_title")
        layout.addWidget(title)

        # 滚动区域
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setObjectName("intent_scroll_area")
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        # 内容容器
        self.options_container = QWidget()
        self.options_container.setObjectName("intent_options_container")
        self.options_layout = QVBoxLayout(self.options_container)
        self.options_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.options_layout.setSpacing(12)
        self.options_layout.setContentsMargins(0, 0, 0, 0)
        scroll_area.setWidget(self.options_container)

        layout.addWidget(scroll_area, 1)

        # 提示信息
        self.hint_label = QLabel("💡 请勾选确认的操作项，或通过对话框与 AI 沟通调整")
        self.hint_label.setObjectName("intent_hint_label")
        self.hint_label.setWordWrap(True)
        layout.addWidget(self.hint_label)

        return panel

    def _create_right_panel(self) -> QWidget:
        """创建右侧面板（对话框）"""
        panel = QWidget()
        panel.setObjectName("intent_right_panel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 24, 24, 24)
        layout.setSpacing(16)

        # 标题
        title = QLabel("💬 与 AI 对话")
        title.setObjectName("intent_section_title")
        layout.addWidget(title)

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
        self.messages_layout.setContentsMargins(0, 0, 0, 0)
        messages_scroll.setWidget(self.messages_container)

        layout.addWidget(messages_scroll, 1)

        # 输入区域
        input_container = QWidget()
        input_container.setObjectName("intent_input_container")
        input_layout = QVBoxLayout(input_container)
        input_layout.setContentsMargins(0, 0, 0, 0)
        input_layout.setSpacing(12)

        # 输入框
        self.message_input = MessageInputEdit()
        self.message_input.setObjectName("intent_message_input")
        self.message_input.setPlaceholderText("输入消息与 AI 沟通... (Ctrl+Enter 发送)")
        self.message_input.setMinimumHeight(80)
        self.message_input.setMaximumHeight(150)
        self.message_input.textChanged.connect(self._on_input_changed)
        self.message_input.send_requested.connect(self._on_send_message)
        input_layout.addWidget(self.message_input)

        # 底部操作栏
        bottom_bar = QHBoxLayout()
        bottom_bar.setSpacing(12)

        hint_label = QLabel("💡 Ctrl+Enter 快速发送")
        hint_label.setObjectName("intent_input_hint")
        bottom_bar.addWidget(hint_label)

        bottom_bar.addStretch()

        self.send_button = QPushButton("发送")
        self.send_button.setObjectName("intent_send_button")
        self.send_button.setEnabled(False)
        self.send_button.setMinimumWidth(100)
        self.send_button.setMinimumHeight(36)
        self.send_button.clicked.connect(self._on_send_message)
        bottom_bar.addWidget(self.send_button)

        input_layout.addLayout(bottom_bar)
        layout.addWidget(input_container)

        return panel

    def _set_analyzing_state(self):
        """设置分析中状态"""
        self.status_label.setText("正在分析您的操作...")
        self.status_icon.setText("🔍")
        self.confirm_button.setEnabled(False)

        # 清空选项
        self._clear_options()

        # 添加加载提示
        loading_label = QLabel("⏳ AI 正在分析您的录制操作，请稍候...")
        loading_label.setObjectName("intent_loading_label")
        loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.options_layout.addWidget(loading_label)

    def _set_confirmation_state(self, intent: Intent):
        """设置确认状态"""
        self.current_intent = intent

        # 更新状态栏
        self.status_label.setText("请确认以下操作：")
        self.status_icon.setText("✅")

        # 清空选项并重新加载
        self._clear_options()

        # 添加信息卡片
        if intent.target:
            target_label = QLabel(f"🎯 目标：{intent.target}")
            target_label.setObjectName("intent_info_label")
            self.options_layout.addWidget(target_label)

        if intent.business_scenario:
            scenario_label = QLabel(f"📌 场景：{intent.business_scenario}")
            scenario_label.setObjectName("intent_info_label")
            self.options_layout.addWidget(scenario_label)

        # 添加分隔线
        separator = QFrame()
        separator.setObjectName("intent_separator")
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        self.options_layout.addWidget(separator)

        # 添加操作选项（勾选框）
        self.operation_checkboxes: List[QCheckBox] = []

        for i, operation in enumerate(intent.core_operations):
            checkbox = QCheckBox(f"✓ {operation}")
            checkbox.setObjectName("intent_operation_checkbox")
            checkbox.setChecked(True)  # 默认全部选中
            checkbox.stateChanged.connect(self._on_checkbox_changed)
            self.options_layout.addWidget(checkbox)
            self.operation_checkboxes.append(checkbox)

        # 添加预期结果展示
        if intent.expected_results:
            separator2 = QFrame()
            separator2.setObjectName("intent_separator")
            separator2.setFrameShape(QFrame.Shape.HLine)
            separator2.setFrameShadow(QFrame.Shadow.Sunken)
            self.options_layout.addWidget(separator2)

            results_title = QLabel("🎉 预期结果：")
            results_title.setObjectName("intent_subsection_title")
            self.options_layout.addWidget(results_title)

            for result in intent.expected_results:
                result_label = QLabel(f"  • {result}")
                result_label.setObjectName("intent_result_label")
                result_label.setWordWrap(True)
                self.options_layout.addWidget(result_label)

        # 启用确认按钮
        self.confirm_button.setEnabled(True)

        # 添加欢迎消息到对话框
        self._add_assistant_message(
            f"我已分析完成您的操作！\n\n"
            f"**目标**：{intent.target or '未识别'}\n"
            f"**场景**：{intent.business_scenario or '未识别'}\n\n"
            f"请确认左侧的操作列表是否正确。如有任何问题，随时告诉我！"
        )

    def _clear_options(self):
        """清空选项区域"""
        while self.options_layout.count():
            child = self.options_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def _on_checkbox_changed(self):
        """勾选框状态变化"""
        # 检查是否至少有一个操作被选中
        has_checked = any(cb.isChecked() for cb in self.operation_checkboxes)
        self.confirm_button.setEnabled(has_checked)

    def _on_input_changed(self):
        """输入框内容变化"""
        text = self.message_input.toPlainText().strip()
        self.send_button.setEnabled(len(text) > 0)

    def _on_send_message(self):
        """发送消息"""
        message = self.message_input.toPlainText().strip()
        if not message:
            return

        self.logger.info(f"发送消息: {message[:50]}...")

        # 添加用户消息
        self._add_user_message(message)

        # 清空输入框
        self.message_input.clear()

        # 发送信号到后端（通过 MainWindow 转发到 WebSocket）
        if self.current_intent:
            self.analyze_intent_request.emit(
                self.current_intent.intent_id,
                message
            )

    def _add_user_message(self, content: str):
        """添加用户消息到对话框"""
        self._add_message("user", content)
        self.chat_messages.append({"role": "user", "content": content})

    def _add_assistant_message(self, content: str):
        """添加 AI 助手消息到对话框"""
        self._add_message("assistant", content)
        self.chat_messages.append({"role": "assistant", "content": content})

    def _add_message(self, role: str, content: str):
        """添加消息到对话区域

        Args:
            role: 消息角色 ("user" 或 "assistant")
            content: 消息内容
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
        message_bubble.setMaximumWidth(400)

        bubble_layout = QVBoxLayout(message_bubble)
        bubble_layout.setContentsMargins(16, 12, 16, 12)
        bubble_layout.setSpacing(0)

        # 消息内容
        content_label = QLabel(content)
        content_label.setObjectName(f"intent_message_content_{role}")
        content_label.setWordWrap(True)
        content_label.setTextFormat(Qt.TextFormat.PlainText)
        content_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        bubble_layout.addWidget(content_label)

        container_layout.addWidget(message_bubble)

        if role == "assistant":
            container_layout.addStretch()

        # 添加到消息容器
        self.messages_layout.addWidget(message_container)

        # 滚动到底部
        QTimer.singleShot(100, self._scroll_to_bottom)

    def _scroll_to_bottom(self):
        """滚动消息区域到底部"""
        scroll_area = self.findChild(QScrollArea, "intent_messages_scroll")
        if scroll_area:
            scrollbar = scroll_area.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def _on_confirm_clicked(self):
        """确认按钮点击（支持 Agent 模式）"""
        if not self.current_intent:
            return

        self.logger.info(f"确认意图: {self.current_intent.intent_id}")

        # 检查是否是 Agent 模式
        if hasattr(self, '_agent_thread_id') and self._agent_thread_id:
            # Agent 模式：收集确认回答并恢复 Agent
            confirmations = self.get_confirmation_answers()
            self.logger.info(f"用户确认回答: {confirmations}")

            # 通过 MainWindow 恢复 Agent
            self._resume_agent_with_confirmation(confirmations)

            # 更新状态
            self.status_label.setText("✅ 意图已确认！正在生成代码...")
            self.confirm_button.setEnabled(False)
            self.cancel_button.setText("关闭")
        else:
            # 传统模式：保持原有逻辑
            confirmed_operations = []
            if hasattr(self, 'operation_checkboxes'):
                confirmed_operations = [
                    cb.text()[2:]  # 移除 "✓ " 前缀
                    for cb in self.operation_checkboxes
                    if cb.isChecked()
                ]

            if not confirmed_operations:
                QMessageBox.warning(self, "提示", "请至少选择一个操作项")
                return

            self.logger.info(f"确认的操作: {confirmed_operations}")

            # 更新意图状态
            self.current_intent.confirm(
                confirmed_operations=confirmed_operations,
                user_message=self.message_input.toPlainText().strip() or None
            )

            # 发送确认信号到后端
            self.confirm_intent_request.emit(self.current_intent.intent_id)

            # 发射信号
            self.intent_confirmed.emit(self.current_intent.intent_id)

            # 更新状态
            self.status_label.setText("✅ 意图已确认！")
            self.confirm_button.setEnabled(False)
            self.cancel_button.setText("关闭")

    def _resume_agent_with_confirmation(self, confirmations: Dict[str, str]):
        """恢复 Agent 并传递用户确认"""
        try:
            # 构建恢复数据
            resume_data = {
                "action": "confirm",
                "confirmations": confirmations,
                "user_message": self.message_input.toPlainText().strip() or None
            }

            self.logger.info(f"恢复 Agent: {self._agent_thread_id}, 数据: {resume_data}")

            # 发射信号，让 MainWindow 处理 Agent 恢复
            # 这里需要 MainWindow 连接这个信号并调用 AgentUIBridge.resume()
            if hasattr(self, 'agent_resume_request'):
                self.agent_resume_request.emit(self._agent_thread_id, resume_data)
            else:
                self.logger.warning("没有 agent_resume_request 信号，无法恢复 Agent")

        except Exception as e:
            self.logger.error(f"恢复 Agent 失败: {e}", exc_info=True)

    def _on_cancel_clicked(self):
        """取消按钮点击"""
        if self.current_intent:
            self.logger.info(f"取消意图: {self.current_intent.intent_id}")

            # 更新意图状态
            self.current_intent.cancel()

            # 发射信号
            self.intent_cancelled.emit(self.current_intent.intent_id)

        # 关闭对话框（如果在对话框中）
        self.parent().close() if self.parent() else None

    # ===== 公共方法（供外部调用）=====

    def on_intent_analyzed(self, intent_data: dict):
        """
        处理意图分析完成消息（公共方法，供外部调用）

        Args:
            intent_data: 意图数据字典
        """
        try:
            # 创建 Intent 对象
            intent = Intent.from_dict(intent_data)

            self.logger.info(f"收到意图分析结果: {intent.intent_id}")

            # 更新 UI（线程安全）
            QTimer.singleShot(0, lambda: self._set_confirmation_state(intent))

        except Exception as e:
            self.logger.error(f"处理意图分析消息失败: {e}")

    def on_intent_updated(self, data: dict):
        """
        处理意图更新消息（公共方法，供外部调用）

        Args:
            data: 包含 intent 和 ai_message 的字典
        """
        try:
            intent_data = data.get("intent", {})

            # 创建 Intent 对象
            intent = Intent.from_dict(intent_data)

            self.logger.info(f"收到意图更新: {intent.intent_id}")

            # 更新 UI（线程安全）
            QTimer.singleShot(0, lambda: self._set_confirmation_state(intent))

            # 添加 AI 消息
            ai_message = data.get("ai_message", "意图已更新")
            QTimer.singleShot(0, lambda: self._add_assistant_message(ai_message))

        except Exception as e:
            self.logger.error(f"处理意图更新消息失败: {e}")

    def on_intent_confirmed(self, intent_id: str):
        """
        处理意图确认消息（公共方法，供外部调用）

        Args:
            intent_id: 意图 ID
        """
        try:
            self.logger.info(f"意图已确认: {intent_id}")

            # 更新状态
            self.status_label.setText("✅ 意图已确认！正在生成工作流...")

        except Exception as e:
            self.logger.error(f"处理意图确认消息失败: {e}")

    def load_intent(self, intent: Intent):
        """
        加载意图数据

        Args:
            intent: Intent 对象
        """
        self.current_intent = intent

        if intent.status == IntentStatus.ANALYZING:
            self._set_analyzing_state()
        elif intent.status == IntentStatus.PENDING_CONFIRMATION:
            self._set_confirmation_state(intent)
        elif intent.status == IntentStatus.CONFIRMED:
            self.status_label.setText("✅ 意图已确认")
            self.status_icon.setText("✅")

    def get_confirmed_operations(self) -> List[str]:
        """
        获取用户确认的操作列表

        Returns:
            List[str]: 确认的操作列表
        """
        if not self.current_intent:
            return []

        return self.current_intent.confirmed_operations

    def load_intent_from_agent(
        self, intent_data: dict, message: str, thread_id: str
    ) -> None:
        """
        从 Agent 加载意图数据（支持完整分析结果）

        Args:
            intent_data: Agent 传来的意图数据（包含完整分析结果）
            message: 确认消息
            thread_id: Agent 会话 ID（用于后续恢复）
        """
        self.logger.info(f"从 Agent 加载意图数据，keys: {intent_data.keys()}")

        # 保存 thread_id 用于后续恢复 Agent
        self._agent_thread_id = thread_id

        # 保存完整数据用于后续确认
        self._full_intent_data = intent_data

        try:
            # 提取基本信息
            intent_info = intent_data.get("intent", {})
            parameters = intent_info.get("parameters", {})

            # 处理 parameters 字段（可能是列表或字典）
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

            # 保存完整分析数据到 intent 对象
            intent._description = intent_info.get("description", "")
            intent._intent_type = intent_info.get("intent_type", "unknown")
            intent._pattern_recognition = intent_data.get("pattern_recognition", {})
            intent._intent_analysis = intent_data.get("intent_analysis", {})
            intent._parameterization_analysis = intent_data.get("parameterization_analysis", [])
            intent._confirmation_questions = intent_data.get("confirmation_questions", [])
            intent._tool_description = intent_data.get("tool_description", {})

            # 更新 UI（线程安全）
            QTimer.singleShot(0, lambda: self._set_confirmation_state_from_agent(intent, message))

        except Exception as e:
            self.logger.error(f"从 Agent 加载意图失败: {e}", exc_info=True)

    def _set_confirmation_state_from_agent(self, intent: Intent, message: str):
        """设置来自 Agent 的确认状态（支持完整分析结果）"""
        self.current_intent = intent

        # 更新状态栏
        self.status_label.setText("请确认以下分析结果：")
        self.status_icon.setText("✅")

        # 清空选项并重新加载
        self._clear_options()

        # 初始化确认问题的回答存储
        self._confirmation_answers: Dict[str, str] = {}
        self._question_button_groups: Dict[str, QButtonGroup] = {}

        # === 1. 模式识别 ===
        pattern = getattr(intent, "_pattern_recognition", {})
        if pattern:
            pattern_label = QLabel(f"🔍 操作模式：{pattern.get('primary_pattern', '未知')}")
            pattern_label.setObjectName("intent_info_label")
            self.options_layout.addWidget(pattern_label)

            confidence = pattern.get("confidence", 0)
            if confidence > 0:
                conf_label = QLabel(f"   置信度：{confidence:.0%}")
                conf_label.setObjectName("intent_result_label")
                self.options_layout.addWidget(conf_label)

        # === 2. 深层意图 ===
        intent_analysis = getattr(intent, "_intent_analysis", {})
        if intent_analysis:
            deep_intent = intent_analysis.get("deep_intent", "")
            if deep_intent:
                intent_label = QLabel(f"🎯 深层意图：{deep_intent}")
                intent_label.setObjectName("intent_info_label")
                intent_label.setWordWrap(True)
                self.options_layout.addWidget(intent_label)

            final_goal = intent_analysis.get("final_goal", "")
            if final_goal:
                goal_label = QLabel(f"🏁 最终目标：{final_goal}")
                goal_label.setObjectName("intent_result_label")
                goal_label.setWordWrap(True)
                self.options_layout.addWidget(goal_label)

        # === 3. 工具描述 ===
        tool_desc = getattr(intent, "_tool_description", {})
        if tool_desc:
            separator = QFrame()
            separator.setObjectName("intent_separator")
            separator.setFrameShape(QFrame.Shape.HLine)
            separator.setFrameShadow(QFrame.Shadow.Sunken)
            self.options_layout.addWidget(separator)

            tool_name = tool_desc.get("name", "")
            if tool_name:
                name_label = QLabel(f"🔧 工具名称：{tool_name}")
                name_label.setObjectName("intent_info_label")
                self.options_layout.addWidget(name_label)

            nat_desc = tool_desc.get("natural_language_description", "")
            if nat_desc:
                desc_label = QLabel(f"📝 描述：{nat_desc}")
                desc_label.setObjectName("intent_result_label")
                desc_label.setWordWrap(True)
                self.options_layout.addWidget(desc_label)

        # === 4. 参数化分析（可选展示） ===
        param_analysis = getattr(intent, "_parameterization_analysis", [])
        if param_analysis:
            separator2 = QFrame()
            separator2.setObjectName("intent_separator")
            separator2.setFrameShape(QFrame.Shape.HLine)
            separator2.setFrameShadow(QFrame.Shadow.Sunken)
            self.options_layout.addWidget(separator2)

            params_title = QLabel("⚙️ 参数分析：")
            params_title.setObjectName("intent_subsection_title")
            self.options_layout.addWidget(params_title)

            for param in param_analysis[:3]:  # 只显示前3个
                if param.get("should_parameterize"):
                    param_text = f"  • {param.get('parameter_name', '?')}: {param.get('element', '')}"
                    param_label = QLabel(param_text)
                    param_label.setObjectName("intent_result_label")
                    param_label.setWordWrap(True)
                    self.options_layout.addWidget(param_label)

        # === 5. 确认问题（重点！） ===
        questions = getattr(intent, "_confirmation_questions", [])
        if questions:
            separator3 = QFrame()
            separator3.setObjectName("intent_separator")
            separator3.setFrameShape(QFrame.Shape.HLine)
            separator3.setFrameShadow(QFrame.Shadow.Sunken)
            self.options_layout.addWidget(separator3)

            questions_title = QLabel("❓ 请确认以下问题：")
            questions_title.setObjectName("intent_subsection_title")
            self.options_layout.addWidget(questions_title)

            for q in questions:
                self._add_confirmation_question(q)

        # 启用确认按钮
        self.confirm_button.setEnabled(True)

        # 添加 AI 消息到对话框
        self._add_assistant_message(message)

    def _add_confirmation_question(self, question: dict):
        """添加一个确认问题及其选项"""
        q_id = question.get("id", "")
        q_text = question.get("question", "")
        q_context = question.get("context", "")
        q_options = question.get("options", [])
        q_recommended = question.get("recommended", "")
        q_priority = question.get("priority", "medium")

        # 创建问题组
        group_box = QGroupBox()
        group_box.setObjectName(f"confirmation_question_{q_priority}")

        group_layout = QVBoxLayout(group_box)
        group_layout.setSpacing(8)
        group_layout.setContentsMargins(12, 12, 12, 12)

        # 问题文本
        question_label = QLabel(f"📌 {q_text}")
        question_label.setObjectName("confirmation_question_text")
        question_label.setWordWrap(True)
        group_layout.addWidget(question_label)

        # 上下文说明（如果有）
        if q_context:
            context_label = QLabel(f"   💡 {q_context}")
            context_label.setObjectName("confirmation_question_context")
            context_label.setWordWrap(True)
            group_layout.addWidget(context_label)

        # 选项（使用 Radio Button）
        button_group = QButtonGroup(group_box)
        self._question_button_groups[q_id] = button_group

        for idx, opt in enumerate(q_options):
            opt_value = opt.get("value", "")
            opt_label = opt.get("label", "")
            opt_impact = opt.get("impact", "")

            radio = QRadioButton(opt_label)
            radio.setObjectName("confirmation_option")

            # 如果是推荐选项，默认选中
            if opt_value == q_recommended:
                radio.setChecked(True)
                self._confirmation_answers[q_id] = opt_value

            # 存储选项值
            radio.setProperty("option_value", opt_value)
            radio.setProperty("question_id", q_id)

            # 连接信号
            radio.toggled.connect(lambda checked, r=radio: self._on_option_selected(r, checked))

            button_group.addButton(radio, idx)
            group_layout.addWidget(radio)

            # 选项影响说明（缩进显示）
            if opt_impact:
                impact_label = QLabel(f"      → {opt_impact}")
                impact_label.setObjectName("confirmation_option_impact")
                impact_label.setWordWrap(True)
                group_layout.addWidget(impact_label)

        self.options_layout.addWidget(group_box)

    def _on_option_selected(self, radio: QRadioButton, checked: bool):
        """处理选项选中"""
        if checked:
            q_id = radio.property("question_id")
            opt_value = radio.property("option_value")
            self._confirmation_answers[q_id] = opt_value
            self.logger.info(f"问题 {q_id} 选择: {opt_value}")

    def get_confirmation_answers(self) -> Dict[str, str]:
        """获取所有确认问题的回答"""
        return self._confirmation_answers.copy()

    def cleanup(self):
        """清理资源"""
        # 不再需要清理 WebSocket 客户端
        pass
