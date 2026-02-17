"""
AI 助手对话界面组件 (现代风格改进版)

提供 AI 对话交互界面,包括:
- 对话消息展示 + 输入框
- 改进的视觉设计和交互体验
"""

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QTextEdit,
    QScrollArea,
    QFrame,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QKeyEvent
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


class ChatWidget(QWidget):
    """AI 助手对话界面组件 (现代风格改进版)"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger(__name__)
        self.init_ui()

    def init_ui(self):
        """初始化用户界面"""
        # 创建主布局
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(0)  # 改为0,通过组件自身控制间距
        main_layout.setContentsMargins(0, 0, 0, 0)

        # === 消息展示区域 ===
        messages_scroll = QScrollArea()
        messages_scroll.setWidgetResizable(True)
        messages_scroll.setObjectName("messages_scroll")
        messages_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        messages_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.messages_container = QWidget()
        self.messages_container.setObjectName("messages_container")
        self.messages_layout = QVBoxLayout(self.messages_container)
        self.messages_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.messages_layout.setSpacing(24)  # 增加消息间距
        self.messages_layout.setContentsMargins(32, 24, 32, 24)  # 增加左右边距
        messages_scroll.setWidget(self.messages_container)

        main_layout.addWidget(messages_scroll, 1)  # stretch=1

        # === 输入框区域 ===
        input_container = QWidget()
        input_container.setObjectName("input_container")
        input_layout = QVBoxLayout(input_container)
        input_layout.setContentsMargins(32, 24, 32, 24)  # 统一边距
        input_layout.setSpacing(16)

        # 输入框外层容器(用于添加阴影效果)
        input_wrapper = QWidget()
        input_wrapper.setObjectName("input_wrapper")
        input_wrapper_layout = QVBoxLayout(input_wrapper)
        input_wrapper_layout.setContentsMargins(0, 0, 0, 0)
        input_wrapper_layout.setSpacing(0)

        # 输入框 - 使用自定义类支持快捷键
        self.message_input = MessageInputEdit(self)
        self.message_input.setObjectName("message_input")
        self.message_input.setPlaceholderText("输入消息... (Ctrl+Enter 发送)")
        self.message_input.setMinimumHeight(100)
        self.message_input.setMaximumHeight(300)
        self.message_input.textChanged.connect(self._on_input_changed)
        self.message_input.send_requested.connect(self.on_send_message)
        input_wrapper_layout.addWidget(self.message_input)

        input_layout.addWidget(input_wrapper)

        # 底部操作栏
        bottom_bar = QHBoxLayout()
        bottom_bar.setSpacing(12)
        
        # 提示文字
        hint_label = QLabel("💡 按 Ctrl+Enter 快速发送")
        hint_label.setObjectName("input_hint")
        bottom_bar.addWidget(hint_label)
        
        bottom_bar.addStretch()

        # 发送按钮
        self.send_button = QPushButton("发送")
        self.send_button.setObjectName("send_button")
        self.send_button.clicked.connect(self.on_send_message)
        self.send_button.setEnabled(False)
        self.send_button.setMinimumWidth(120)
        self.send_button.setMinimumHeight(40)
        bottom_bar.addWidget(self.send_button)

        input_layout.addLayout(bottom_bar)

        main_layout.addWidget(input_container)

        # 初始化消息
        self._add_welcome_message()

    def _add_welcome_message(self):
        """添加欢迎消息"""
        self._add_message(
            "assistant", 
            "你好!我是 Mexemplar AI 助手 👋\n\n有什么可以帮助你的吗?你可以问我任何问题!"
        )

    def _add_message(self, role: str, content: str):
        """添加消息到对话区域

        Args:
            role: 消息角色 ("user" 或 "assistant")
            content: 消息内容
        """
        # 创建外层容器用于对齐
        message_container = QWidget()
        message_container.setObjectName("message_row")
        container_layout = QHBoxLayout(message_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(12)

        # 根据角色添加头像和对齐
        if role == "user":
            container_layout.addStretch()
        
        # 创建消息气泡容器
        bubble_container = QWidget()
        bubble_container.setObjectName(f"bubble_container_{role}")
        bubble_layout = QVBoxLayout(bubble_container)
        bubble_layout.setContentsMargins(0, 0, 0, 0)
        bubble_layout.setSpacing(8)
        
        # 角色标签行(头像+名称)
        role_row = QHBoxLayout()
        role_row.setSpacing(8)
        
        role_icon = QLabel("👤" if role == "user" else "🤖")
        role_icon.setObjectName("role_icon")
        role_row.addWidget(role_icon)
        
        role_name = QLabel("你" if role == "user" else "AI 助手")
        role_name.setObjectName(f"role_name_{role}")
        role_row.addWidget(role_name)
        role_row.addStretch()
        
        bubble_layout.addLayout(role_row)

        # 消息气泡
        message_bubble = QWidget()
        message_bubble.setObjectName(f"message_bubble_{role}")
        message_bubble.setMaximumWidth(700)  # 增加最大宽度

        bubble_content_layout = QVBoxLayout(message_bubble)
        bubble_content_layout.setContentsMargins(20, 16, 20, 16)  # 增加内边距
        bubble_content_layout.setSpacing(0)

        # 消息内容
        content_label = QLabel(content)
        content_label.setObjectName(f"content_{role}")
        content_label.setWordWrap(True)
        content_label.setTextFormat(Qt.TextFormat.PlainText)
        content_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        bubble_content_layout.addWidget(content_label)

        bubble_layout.addWidget(message_bubble)
        container_layout.addWidget(bubble_container)

        if role == "assistant":
            container_layout.addStretch()

        # 添加到消息容器
        self.messages_layout.addWidget(message_container)
        
        # 滚动到底部
        QTimer.singleShot(100, self._scroll_to_bottom)

    def _scroll_to_bottom(self):
        """滚动消息区域到底部"""
        scroll_area = self.findChild(QScrollArea, "messages_scroll")
        if scroll_area:
            scrollbar = scroll_area.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

    def _on_input_changed(self):
        """输入框内容变化"""
        text = self.message_input.toPlainText().strip()
        self.send_button.setEnabled(len(text) > 0)

    def on_new_chat(self):
        """新建对话"""
        self.logger.info("新建对话")
        # 清空消息区域
        while self.messages_layout.count():
            child = self.messages_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        # 添加欢迎消息
        self._add_welcome_message()

    def on_send_message(self):
        """发送消息"""
        message = self.message_input.toPlainText().strip()
        if not message:
            return

        self.logger.info(f"发送消息: {message[:50]}...")

        # 添加用户消息
        self._add_message("user", message)

        # 清空输入框
        self.message_input.clear()

        # 模拟 AI 响应
        self._simulate_ai_response(message)

    def _simulate_ai_response(self, user_message: str):
        """模拟 AI 响应(占位实现)"""
        # TODO: 集成实际的 AI API
        response = f"我收到了你的消息:\n「{user_message[:100] + '...' if len(user_message) > 100 else user_message}」\n\n这是一个演示响应。AI 对话功能正在开发中,敬请期待! ✨"

        # 添加 AI 响应
        self._add_message("assistant", response)
