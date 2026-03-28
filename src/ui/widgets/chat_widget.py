"""
AI 助手对话界面组件 (现代风格改进版)

提供 AI 对话交互界面,包括:
- 左侧会话列表（侧边栏）
- 右侧消息展示 + 输入框
- 接通 AgentUIBridge 进行真实 AI 对话
"""

import json
import uuid

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QTextEdit,
    QScrollArea,
    QFrame,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QMenu,
    QDialog,
    QCheckBox,
    QDialogButtonBox,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QSize
from PyQt6.QtGui import QKeyEvent
from src.business.agents.config import AgentType
from src.utils.logger import get_logger


class MessageInputEdit(QTextEdit):
    """支持 Ctrl+Enter 发送的自定义输入框"""

    send_requested = pyqtSignal()  # 发送请求信号

    def keyPressEvent(self, event: QKeyEvent):
        """处理按键事件"""
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() == Qt.KeyboardModifier.ControlModifier:
                self.send_requested.emit()
                return
        super().keyPressEvent(event)


class ChatWidget(QWidget):
    """AI 助手对话界面组件（含侧边栏会话列表）"""

    # 发出信号给 MainWindow，让它通过 UIBridge 启动 Agent
    send_message_requested = pyqtSignal(str, str, str)  # session_id, agent_type, user_input

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger(__name__)
        self._session_id = None  # 当前会话 ID
        self._loading = False  # 是否正在等待 Agent 响应
        self.init_ui()

    def init_ui(self):
        """初始化用户界面"""
        root_layout = QHBoxLayout(self)
        root_layout.setSpacing(0)
        root_layout.setContentsMargins(0, 0, 0, 0)

        # =====================================================================
        # 左侧：会话列表侧边栏
        # =====================================================================
        sidebar = QWidget()
        sidebar.setObjectName("chat_sidebar")
        sidebar.setMinimumWidth(180)
        sidebar.setMaximumWidth(240)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(8, 12, 8, 8)
        sidebar_layout.setSpacing(8)

        # 标题 + 新建按钮（带下拉选择工具）
        sidebar_header = QHBoxLayout()
        sidebar_title = QLabel("会话")
        sidebar_title.setObjectName("sidebar_title")
        sidebar_header.addWidget(sidebar_title)
        sidebar_header.addStretch()
        self.new_chat_btn = QPushButton("+")
        self.new_chat_btn.setObjectName("new_chat_btn")
        self.new_chat_btn.setToolTip("新建对话（右键选择工具）")
        self.new_chat_btn.setFixedSize(QSize(28, 28))
        self.new_chat_btn.clicked.connect(self._on_new_chat_clicked)
        self.new_chat_btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.new_chat_btn.customContextMenuRequested.connect(self._on_new_chat_menu)
        sidebar_header.addWidget(self.new_chat_btn)
        sidebar_layout.addLayout(sidebar_header)

        # 会话列表
        self.session_list = QListWidget()
        self.session_list.setObjectName("session_list")
        self.session_list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.session_list.itemClicked.connect(self._on_session_item_clicked)
        sidebar_layout.addWidget(self.session_list, 1)

        root_layout.addWidget(sidebar)

        # 分隔线
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.VLine)
        separator.setObjectName("sidebar_separator")
        root_layout.addWidget(separator)

        # =====================================================================
        # 右侧：对话区域
        # =====================================================================
        chat_area = QWidget()
        chat_area.setObjectName("chat_area")
        chat_layout = QVBoxLayout(chat_area)
        chat_layout.setSpacing(0)
        chat_layout.setContentsMargins(0, 0, 0, 0)

        # 消息展示区域
        messages_scroll = QScrollArea()
        messages_scroll.setWidgetResizable(True)
        messages_scroll.setObjectName("messages_scroll")
        messages_scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        messages_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.messages_container = QWidget()
        self.messages_container.setObjectName("messages_container")
        self.messages_layout = QVBoxLayout(self.messages_container)
        self.messages_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.messages_layout.setSpacing(24)
        self.messages_layout.setContentsMargins(32, 24, 32, 24)
        messages_scroll.setWidget(self.messages_container)

        chat_layout.addWidget(messages_scroll, 1)

        # 输入框区域
        input_container = QWidget()
        input_container.setObjectName("input_container")
        input_layout = QVBoxLayout(input_container)
        input_layout.setContentsMargins(32, 24, 32, 24)
        input_layout.setSpacing(16)

        input_wrapper = QWidget()
        input_wrapper.setObjectName("input_wrapper")
        input_wrapper_layout = QVBoxLayout(input_wrapper)
        input_wrapper_layout.setContentsMargins(0, 0, 0, 0)
        input_wrapper_layout.setSpacing(0)

        self.message_input = MessageInputEdit(self)
        self.message_input.setObjectName("message_input")
        self.message_input.setPlaceholderText("输入消息... (Ctrl+Enter 发送)")
        self.message_input.setMinimumHeight(100)
        self.message_input.setMaximumHeight(300)
        self.message_input.textChanged.connect(self._on_input_changed)
        self.message_input.send_requested.connect(self.on_send_message)
        input_wrapper_layout.addWidget(self.message_input)
        input_layout.addWidget(input_wrapper)

        bottom_bar = QHBoxLayout()
        bottom_bar.setSpacing(12)
        hint_label = QLabel("按 Ctrl+Enter 快速发送")
        hint_label.setObjectName("input_hint")
        bottom_bar.addWidget(hint_label)
        bottom_bar.addStretch()
        self.send_button = QPushButton("发送")
        self.send_button.setObjectName("send_button")
        self.send_button.clicked.connect(self.on_send_message)
        self.send_button.setEnabled(False)
        self.send_button.setMinimumWidth(120)
        self.send_button.setMinimumHeight(40)
        bottom_bar.addWidget(self.send_button)
        input_layout.addLayout(bottom_bar)

        chat_layout.addWidget(input_container)
        root_layout.addWidget(chat_area, 1)

        # 初始化：加载会话列表并创建/恢复第一个会话
        self._refresh_session_list()
        if self._session_id is None:
            self._new_session()

    # =========================================================================
    # 侧边栏会话管理
    # =========================================================================

    def _refresh_session_list(self):
        """从数据库加载助理会话列表到侧边栏"""
        self.session_list.clear()
        try:
            from src.data.repositories import SessionRepository
            repo = SessionRepository()
            sessions = repo.get_by_agent_type(AgentType.ASSISTANT, limit=50)
            for s in sessions:
                label = self._session_label(s.session_id, s.created_at)
                item = QListWidgetItem(label)
                item.setData(Qt.ItemDataRole.UserRole, s.session_id)
                self.session_list.addItem(item)
        except Exception as e:
            self.logger.error(f"加载会话列表失败: {e}")

        # 高亮当前会话
        self._highlight_current_session()

    def _highlight_current_session(self):
        """高亮当前活动会话"""
        for i in range(self.session_list.count()):
            item = self.session_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == self._session_id:
                self.session_list.setCurrentItem(item)
                return

    def _session_label(self, session_id: str, created_at) -> str:
        """生成会话列表显示名称"""
        if created_at:
            return created_at.strftime("%m/%d %H:%M")
        return session_id[:12]

    def _on_session_item_clicked(self, item: QListWidgetItem):
        """切换到选中的会话"""
        session_id = item.data(Qt.ItemDataRole.UserRole)
        if session_id == self._session_id:
            return
        self._switch_to_session(session_id)

    def _on_new_chat_clicked(self):
        """新建会话（使用全部工具）"""
        self._new_session(tool_ids=None)

    def _on_new_chat_menu(self, pos):
        """新建按钮右键菜单"""
        menu = QMenu(self)
        menu.addAction("新建对话（全部工具）", lambda: self._new_session(tool_ids=None))
        menu.addAction("新建对话（选择工具）", self._new_session_with_tool_selection)
        menu.exec(self.new_chat_btn.mapToGlobal(pos))

    def _new_session_with_tool_selection(self):
        """弹出工具选择 dialog，然后新建会话"""
        tool_ids = self._show_tool_selection_dialog()
        if tool_ids is not None:
            self._new_session(tool_ids=tool_ids)

    def _new_session(self, tool_ids=None):
        """创建新会话并切换到它。tool_ids=None 表示使用全部工具。"""
        session_id = self._create_session(tool_ids=tool_ids)
        self._session_id = session_id
        self._clear_messages()
        self._add_welcome_message()
        self._refresh_session_list()

        # 触发跨会话记忆生成（后台异步，不阻塞 UI）
        try:
            from src.business.memory.assistant_memory import get_memory_manager
            get_memory_manager().trigger_on_new_session(session_id)
        except Exception as e:
            self.logger.warning(f"触发记忆生成失败: {e}")

    def _switch_to_session(self, session_id: str):
        """切换到指定会话（加载历史消息）"""
        self._session_id = session_id
        self._loading = False
        self.send_button.setEnabled(False)
        self.send_button.setText("发送")
        self._clear_messages()
        self._load_session_messages(session_id)
        self._highlight_current_session()

    def _load_session_messages(self, session_id: str):
        """从数据库加载会话历史消息（只加载非归档消息）"""
        try:
            from src.data.repositories import MessageRepository
            repo = MessageRepository()
            messages = repo.get_context(session_id)  # 只返回非 archived 消息
            if not messages:
                self._add_welcome_message()
                return
            for msg in messages:
                if msg.role in ("user", "assistant") and msg.content:
                    self._add_message(msg.role, msg.content)
        except Exception as e:
            self.logger.error(f"加载会话消息失败: {e}")
            self._add_welcome_message()

    # =========================================================================
    # 消息区域
    # =========================================================================

    def _clear_messages(self):
        """清空消息区域"""
        while self.messages_layout.count():
            child = self.messages_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def _add_welcome_message(self):
        """添加欢迎消息"""
        self._add_message(
            "assistant",
            "你好! 我是你的办公助理。\n\n有什么可以帮助你的吗?"
        )

    def _add_message(self, role: str, content: str):
        """添加消息到对话区域"""
        message_container = QWidget()
        message_container.setObjectName("message_row")
        container_layout = QHBoxLayout(message_container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.setSpacing(12)

        if role == "user":
            container_layout.addStretch()

        bubble_container = QWidget()
        bubble_container.setObjectName(f"bubble_container_{role}")
        bubble_layout = QVBoxLayout(bubble_container)
        bubble_layout.setContentsMargins(0, 0, 0, 0)
        bubble_layout.setSpacing(8)

        role_row = QHBoxLayout()
        role_row.setSpacing(8)
        role_icon = QLabel("U" if role == "user" else "A")
        role_icon.setObjectName("role_icon")
        role_row.addWidget(role_icon)
        role_name = QLabel("你" if role == "user" else "AI 助手")
        role_name.setObjectName(f"role_name_{role}")
        role_row.addWidget(role_name)
        role_row.addStretch()
        bubble_layout.addLayout(role_row)

        message_bubble = QWidget()
        message_bubble.setObjectName(f"message_bubble_{role}")
        message_bubble.setMaximumWidth(700)
        bubble_content_layout = QVBoxLayout(message_bubble)
        bubble_content_layout.setContentsMargins(20, 16, 20, 16)
        bubble_content_layout.setSpacing(0)

        content_label = QLabel(content)
        content_label.setObjectName(f"content_{role}")
        content_label.setWordWrap(True)
        content_label.setTextFormat(Qt.TextFormat.PlainText)
        content_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        bubble_content_layout.addWidget(content_label)
        bubble_layout.addWidget(message_bubble)
        container_layout.addWidget(bubble_container)

        if role == "assistant":
            container_layout.addStretch()

        self.messages_layout.addWidget(message_container)
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
        self.send_button.setEnabled(len(text) > 0 and not self._loading)

    # =========================================================================
    # Public API — 供 MainWindow / UIBridge 调用
    # =========================================================================

    def get_session_id(self) -> str:
        """获取当前会话 ID"""
        if not self._session_id:
            self._new_session()
        return self._session_id

    def set_loading(self, loading: bool):
        """设置加载状态"""
        self._loading = loading
        self.send_button.setEnabled(not loading and bool(self.message_input.toPlainText().strip()))
        self.send_button.setText("思考中..." if loading else "发送")

    def add_assistant_message(self, content: str):
        """添加 AI 助手消息（供 MainWindow 的信号 handler 调用）"""
        self._add_message("assistant", content)

    def add_error_message(self, error: str):
        """添加错误消息"""
        self._add_message("assistant", f"出了点问题: {error}")

    def on_new_chat(self):
        """新建对话（外部调用入口）"""
        self._new_session()

    def on_send_message(self):
        """发送消息"""
        if self._loading:
            return

        message = self.message_input.toPlainText().strip()
        if not message:
            return

        self.logger.info(f"发送消息: {message[:50]}...")
        self._add_message("user", message)
        self.message_input.clear()
        self.set_loading(True)

        session_id = self.get_session_id()
        self.send_message_requested.emit(session_id, AgentType.ASSISTANT, message)

    # =========================================================================
    # Private
    # =========================================================================

    def _create_session(self, tool_ids=None) -> str:
        """创建新的助理会话。tool_ids: list[str] 或 None（全部工具）"""
        from src.data.models_sqlite import Session
        from src.data.repositories import SessionRepository

        session_id = f"ast_{uuid.uuid4().hex[:12]}"
        try:
            repo = SessionRepository()
            tool_ids_str = json.dumps(tool_ids) if tool_ids is not None else None
            repo.create(
                Session(
                    session_id=session_id,
                    workflow_id=None,
                    agent_type=AgentType.ASSISTANT,
                    status="active",
                    tool_ids=tool_ids_str,
                )
            )
            self.logger.info(f"创建助理会话: {session_id}, tool_ids={tool_ids}")
        except Exception as e:
            self.logger.error(f"创建会话失败: {e}")
        return session_id

    def _show_tool_selection_dialog(self):
        """弹出工具选择 dialog，返回选中的 tool_id 列表，用户取消则返回 None"""
        try:
            from src.data.repositories import ToolRepository
            tools = ToolRepository().get_published()
        except Exception as e:
            self.logger.error(f"获取工具列表失败: {e}")
            return None

        if not tools:
            return None

        dialog = QDialog(self)
        dialog.setWindowTitle("选择工具")
        dialog.setMinimumWidth(360)
        layout = QVBoxLayout(dialog)

        hint = QLabel("勾选本次会话要使用的工具（默认全选）：")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        checkboxes = []
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(300)
        tool_list_widget = QWidget()
        tool_list_layout = QVBoxLayout(tool_list_widget)
        for tool in tools:
            cb = QCheckBox(f"{tool.tool_name}  —  {tool.description or ''}")
            cb.setChecked(True)
            cb.setProperty("tool_id", tool.tool_id)
            checkboxes.append(cb)
            tool_list_layout.addWidget(cb)
        scroll.setWidget(tool_list_widget)
        layout.addWidget(scroll)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None

        selected = [cb.property("tool_id") for cb in checkboxes if cb.isChecked()]
        # 未选中任何工具时等同于取消
        if not selected:
            return None
        # 如果全选则等同于 None（全部）
        if len(selected) == len(tools):
            return None
        return selected
