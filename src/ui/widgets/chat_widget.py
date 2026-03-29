"""
AI 助手对话界面组件 (Claude Chats 风格)

双视图设计:
- 会话列表视图：大搜索框 + 会话卡片 + 滚动加载
- 对话视图：消息展示 + 输入框（通过侧边栏导航返回列表）
"""

import json
import uuid
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QTextEdit,
    QScrollArea,
    QFrame,
    QLineEdit,
    QStackedWidget,
    QSizePolicy,
    QMenu,
    QDialog,
    QCheckBox,
    QDialogButtonBox,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QSize
from PyQt6.QtGui import QKeyEvent, QPixmap
from src.business.agents.config import AgentType
from src.utils.logger import get_logger


class MessageInputEdit(QTextEdit):
    """回车发送，Shift+Enter / Ctrl+Enter 换行的输入框"""

    send_requested = pyqtSignal()  # 发送请求信号

    def keyPressEvent(self, event: QKeyEvent):
        """处理按键事件：Enter 发送，Shift/Ctrl+Enter 换行"""
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            if event.modifiers() in (
                Qt.KeyboardModifier.NoModifier,
                Qt.KeyboardModifier.KeypadModifier,
            ):
                self.send_requested.emit()
                return
        super().keyPressEvent(event)


class SessionCard(QFrame):
    """会话卡片组件 — 显示在会话列表中"""

    clicked = pyqtSignal(str)  # session_id

    def __init__(self, session_id: str, title: str, preview: str, date_str: str, parent=None):
        super().__init__(parent)
        self._session_id = session_id
        self.setObjectName("session_card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)

        # 第一行：标题 + 日期
        top_row = QHBoxLayout()
        top_row.setSpacing(12)
        title_label = QLabel(title)
        title_label.setObjectName("session_card_title")
        top_row.addWidget(title_label, 1)

        date_label = QLabel(date_str)
        date_label.setObjectName("session_card_date")
        top_row.addWidget(date_label)
        layout.addLayout(top_row)

        # 第二行：预览文本
        if preview and preview != title:
            preview_label = QLabel(preview)
            preview_label.setObjectName("session_card_preview")
            preview_label.setWordWrap(False)
            layout.addWidget(preview_label)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._session_id)
        super().mousePressEvent(event)


class ChatWidget(QWidget):
    """AI 助手对话界面组件（双视图：会话列表 + 对话）"""

    # 发出信号给 MainWindow，让它通过 UIBridge 启动 Agent
    send_message_requested = pyqtSignal(str, str, str)  # session_id, agent_type, user_input

    # 视图索引常量
    VIEW_SESSION_LIST = 0
    VIEW_CONVERSATION = 1

    def __init__(self, parent=None):
        super().__init__(parent)
        self.logger = get_logger(__name__)
        self._session_id = None  # 当前会话 ID（None = 尚未创建）
        self._pending_tool_ids = None  # 延迟创建时暂存的 tool_ids
        self._loading = False  # 是否正在等待 Agent 响应
        self._sessions_page = 0  # 当前滚动加载页码
        self._sessions_page_size = 20  # 每页加载数
        self._all_sessions = []  # 缓存的会话数据
        self._search_text = ""  # 搜索关键词
        self._welcome_visible = False  # 欢迎页是否显示中
        self._welcome_input = None  # 欢迎页输入框引用
        self.init_ui()

    def init_ui(self):
        """初始化用户界面"""
        root_layout = QVBoxLayout(self)
        root_layout.setSpacing(0)
        root_layout.setContentsMargins(0, 0, 0, 0)

        self._stack = QStackedWidget()
        root_layout.addWidget(self._stack)

        # 视图 0：会话列表
        self._init_session_list_view()

        # 视图 1：对话
        self._init_conversation_view()

        # 默认显示会话列表
        self._stack.setCurrentIndex(self.VIEW_SESSION_LIST)
        self._load_sessions()

    # =========================================================================
    # 视图 0：会话列表
    # =========================================================================

    def _init_session_list_view(self):
        """初始化会话列表视图"""
        view = QWidget()
        view.setObjectName("chats_list_view")
        layout = QVBoxLayout(view)
        layout.setSpacing(0)
        layout.setContentsMargins(0, 0, 0, 0)

        # 顶部：标题 + 搜索框
        search_container = QWidget()
        search_container.setObjectName("chats_search_container")
        search_layout = QVBoxLayout(search_container)
        search_layout.setContentsMargins(48, 36, 48, 20)
        search_layout.setSpacing(16)

        title = QLabel("对话")
        title.setObjectName("chats_list_title")
        search_layout.addWidget(title)

        self._search_input = QLineEdit()
        self._search_input.setObjectName("chats_search_input")
        self._search_input.setPlaceholderText("搜索对话...")
        self._search_input.setMinimumHeight(46)
        self._search_input.textChanged.connect(self._on_search_changed)
        search_layout.addWidget(self._search_input)

        layout.addWidget(search_container)

        # 会话卡片滚动区域
        scroll = QScrollArea()
        scroll.setObjectName("chats_list_scroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.verticalScrollBar().valueChanged.connect(self._on_list_scroll)
        self._chats_scroll = scroll

        self._cards_container = QWidget()
        self._cards_container.setObjectName("session_cards_container")
        self._cards_layout = QVBoxLayout(self._cards_container)
        self._cards_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._cards_layout.setSpacing(2)
        self._cards_layout.setContentsMargins(48, 0, 48, 48)
        scroll.setWidget(self._cards_container)

        layout.addWidget(scroll, 1)
        self._stack.addWidget(view)

    # =========================================================================
    # 视图 1：对话
    # =========================================================================

    def _init_conversation_view(self):
        """初始化对话视图"""
        view = QWidget()
        view.setObjectName("chat_area")
        chat_layout = QVBoxLayout(view)
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
        self.input_container = QWidget()
        self.input_container.setObjectName("input_container")
        input_layout = QVBoxLayout(self.input_container)
        input_layout.setContentsMargins(32, 24, 32, 24)
        input_layout.setSpacing(16)

        input_wrapper = QWidget()
        input_wrapper.setObjectName("input_wrapper")
        input_wrapper_layout = QVBoxLayout(input_wrapper)
        input_wrapper_layout.setContentsMargins(0, 0, 0, 0)
        input_wrapper_layout.setSpacing(0)

        self.message_input = MessageInputEdit(self)
        self.message_input.setObjectName("message_input")
        self.message_input.setPlaceholderText("输入消息... (Enter 发送，Shift+Enter 换行)")
        self.message_input.setMinimumHeight(100)
        self.message_input.setMaximumHeight(300)
        self.message_input.textChanged.connect(self._on_input_changed)
        self.message_input.send_requested.connect(self.on_send_message)
        input_wrapper_layout.addWidget(self.message_input)
        input_layout.addWidget(input_wrapper)

        bottom_bar = QHBoxLayout()
        bottom_bar.setSpacing(12)
        hint_label = QLabel("Enter 发送，Shift+Enter 换行")
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

        chat_layout.addWidget(self.input_container)
        self._stack.addWidget(view)

    # =========================================================================
    # 会话列表：数据加载与渲染
    # =========================================================================

    def _load_sessions(self):
        """从数据库加载会话列表"""
        try:
            from src.data.repositories import SessionRepository, MessageRepository
            session_repo = SessionRepository()
            msg_repo = MessageRepository()
            sessions = session_repo.get_by_agent_type(AgentType.ASSISTANT, limit=200)

            self._all_sessions = []
            for s in sessions:
                # 获取第一条用户消息作为预览
                messages = msg_repo.get_context(s.session_id)
                first_user_msg = ""
                for m in messages:
                    if m.role == "user" and m.content:
                        first_user_msg = m.content
                        break

                title = first_user_msg[:50] if first_user_msg else "新对话"
                preview_text = first_user_msg[:120] if first_user_msg else ""

                self._all_sessions.append({
                    "session_id": s.session_id,
                    "title": title,
                    "preview": preview_text,
                    "date": s.created_at,
                    "date_str": s.created_at.strftime("%m/%d %H:%M") if s.created_at else "",
                })
        except Exception as e:
            self.logger.error(f"加载会话列表失败: {e}")
            self._all_sessions = []

        self._sessions_page = 0
        self._render_session_cards()

    def _get_filtered_sessions(self):
        """根据搜索关键词过滤会话"""
        if not self._search_text:
            return self._all_sessions
        keyword = self._search_text.lower()
        return [
            s for s in self._all_sessions
            if keyword in s["title"].lower() or keyword in s["preview"].lower()
        ]

    def _render_session_cards(self):
        """渲染会话卡片"""
        # 清空已有卡片
        while self._cards_layout.count():
            child = self._cards_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        filtered = self._get_filtered_sessions()
        show_count = min(
            (self._sessions_page + 1) * self._sessions_page_size,
            len(filtered),
        )

        for s in filtered[:show_count]:
            card = SessionCard(
                s["session_id"], s["title"], s["preview"], s["date_str"]
            )
            card.clicked.connect(self._on_session_card_clicked)
            self._cards_layout.addWidget(card)

        # 空状态提示
        if show_count == 0:
            hint_text = "没有找到匹配的对话" if self._search_text else "还没有对话，点击「新建对话」开始吧"
            empty_label = QLabel(hint_text)
            empty_label.setObjectName("chats_empty_hint")
            empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._cards_layout.addWidget(empty_label)

    def _on_search_changed(self, text: str):
        """搜索框内容变化"""
        self._search_text = text.strip()
        self._sessions_page = 0
        self._render_session_cards()

    def _on_list_scroll(self, value):
        """会话列表滚动 — 触底加载更多"""
        scrollbar = self._chats_scroll.verticalScrollBar()
        if value >= scrollbar.maximum() - 50:
            filtered = self._get_filtered_sessions()
            current_count = (self._sessions_page + 1) * self._sessions_page_size
            if current_count < len(filtered):
                self._sessions_page += 1
                self._render_session_cards()

    def _on_session_card_clicked(self, session_id: str):
        """点击会话卡片 → 切换到对话视图"""
        self._switch_to_session(session_id)
        self._stack.setCurrentIndex(self.VIEW_CONVERSATION)

    def _show_session_list(self):
        """返回会话列表视图"""
        self._load_sessions()
        self._stack.setCurrentIndex(self.VIEW_SESSION_LIST)

    # =========================================================================
    # 对话视图：会话管理
    # =========================================================================

    def _prepare_new_chat(self, tool_ids=None):
        """准备新对话界面（不立即创建 DB 会话，等用户发第一条消息时再创建）"""
        self._session_id = None
        self._pending_tool_ids = tool_ids
        self._clear_messages()
        self._add_welcome_message()
        self._stack.setCurrentIndex(self.VIEW_CONVERSATION)

    def _switch_to_session(self, session_id: str):
        """切换到指定会话（加载历史消息）"""
        self._session_id = session_id
        self._loading = False
        self.send_button.setEnabled(False)
        self.send_button.setText("发送")
        self._clear_messages()
        self.input_container.show()
        self._load_session_messages(session_id)

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
        self._welcome_visible = False
        self._welcome_input = None
        while self.messages_layout.count():
            child = self.messages_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

    def _add_welcome_message(self):
        """添加 Claude 风格的欢迎页面 — 居中输入框"""
        if self._welcome_visible:
            return
        self._welcome_visible = True

        # 隐藏底部输入区域，欢迎页自带居中输入框
        self.input_container.hide()

        welcome = QWidget()
        welcome.setObjectName("welcome_container")
        welcome.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        welcome_layout = QVBoxLayout(welcome)
        welcome_layout.setContentsMargins(0, 0, 0, 0)

        # 内容组：问候语 + 输入框作为整体一起居中
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(20)
        content_layout.setContentsMargins(0, 0, 0, 0)

        # 问候语 — 图标 + 文字
        greeting_row = QWidget()
        greeting_layout = QHBoxLayout(greeting_row)
        greeting_layout.setContentsMargins(0, 0, 0, 0)
        greeting_layout.setSpacing(10)
        greeting_layout.addStretch()

        icon_label = QLabel()
        icon_path = Path(__file__).parent.parent / "resources" / "icons" / "app_icon.png"
        if icon_path.exists():
            pixmap = QPixmap(str(icon_path)).scaled(
                32, 32, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
            )
            icon_label.setPixmap(pixmap)
        icon_label.setFixedSize(32, 32)

        display_name = self._get_display_name()
        greeting_text = f"Hi, {display_name}，接下来做什么？" if display_name else "接下来做什么？"
        greeting = QLabel(greeting_text)
        greeting.setObjectName("welcome_greeting")

        greeting_layout.addWidget(icon_label)
        greeting_layout.addWidget(greeting)
        greeting_layout.addStretch()
        greeting_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        content_layout.addWidget(greeting_row)

        # 居中输入框 — 圆角矩形
        self._welcome_input = MessageInputEdit()
        self._welcome_input.setObjectName("welcome_input")
        self._welcome_input.setPlaceholderText("问我任何问题，或让我帮你完成一项任务...")
        self._welcome_input.setMinimumWidth(640)
        self._welcome_input.setMinimumHeight(100)
        self._welcome_input.setMaximumHeight(160)
        self._welcome_input.setMaximumWidth(720)
        self._welcome_input.send_requested.connect(self._on_welcome_send)

        center_layout = QHBoxLayout()
        center_layout.addStretch()
        center_layout.addWidget(self._welcome_input)
        center_layout.addStretch()
        content_layout.addLayout(center_layout)

        welcome_layout.addStretch(2)
        welcome_layout.addWidget(content)
        welcome_layout.addStretch(3)

        # 使用 stretch 使欢迎页占据全部可用空间
        self.messages_layout.addWidget(welcome, 1)

        QTimer.singleShot(100, self._welcome_input.setFocus)

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
        """获取当前会话 ID（如果尚未创建则立即创建）"""
        if not self._session_id:
            self._session_id = self._create_session(tool_ids=self._pending_tool_ids)
            self._pending_tool_ids = None
            # 触发跨会话记忆生成（后台异步）
            try:
                from src.business.memory.assistant_memory import get_memory_manager
                get_memory_manager().trigger_on_new_session(self._session_id)
            except Exception as e:
                self.logger.warning(f"触发记忆生成失败: {e}")
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
        """新建对话（外部调用入口）— 只准备 UI，不创建 DB 会话"""
        self._prepare_new_chat()

    def show_session_list(self):
        """显示会话列表视图（供 MainWindow 在页面切换时调用）"""
        self._load_sessions()
        self._stack.setCurrentIndex(self.VIEW_SESSION_LIST)

    def on_send_message(self):
        """发送消息"""
        if self._loading:
            return

        message = self.message_input.toPlainText().strip()
        if not message:
            return

        self._dismiss_welcome()
        self._do_send(message)

    # =========================================================================
    # Private
    # =========================================================================

    def _get_display_name(self) -> str:
        """从用户偏好档案获取称呼"""
        try:
            from src.data.repositories import AssistantProfileRepository
            profile = AssistantProfileRepository().get_default()
            return profile.display_name if profile and profile.display_name else ""
        except Exception:
            return ""

    def _on_welcome_send(self):
        """从欢迎页输入框发送"""
        text = self._welcome_input.toPlainText().strip()
        if not text:
            return
        self._dismiss_welcome()
        self._do_send(text)

    def _dismiss_welcome(self):
        """清除欢迎页并恢复底部输入栏"""
        if not self._welcome_visible:
            return
        self._clear_messages()
        self.input_container.show()

    def _do_send(self, message: str):
        """核心发送逻辑"""
        self.logger.info(f"发送消息: {message[:50]}...")
        self._add_message("user", message)
        self.message_input.clear()
        self.set_loading(True)

        session_id = self.get_session_id()
        self.send_message_requested.emit(session_id, AgentType.ASSISTANT, message)

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
