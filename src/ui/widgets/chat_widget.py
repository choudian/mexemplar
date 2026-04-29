"""
AI 助手对话界面组件 (Claude Chats 风格)

双视图设计:
- 会话列表视图：大搜索框 + 会话卡片 + 滚动加载
- 对话视图：消息展示 + 输入框（通过侧边栏导航返回列表）
"""

from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QLabel,
    QScrollArea,
    QFrame,
    QLineEdit,
    QStackedWidget,
    QSizePolicy,
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QPixmap
from src.business.agents.config import AgentType
from src.business.services import ChatService
from src.ui.widgets.message_input import MessageInputEdit
from src.ui.widgets.layout_utils import clear_layout, scroll_to_bottom
from src.ui.widgets.markdown_message_view import MarkdownMessageView
from src.utils.logger import get_logger


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
    auto_approve_toggled = pyqtSignal(bool)
    new_chat_started = pyqtSignal()

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
        self._oldest_loaded_sequence = None  # 当前最早加载的展示 sequence
        self._has_more_history = False  # 是否还能向上加载
        self._loading_history_page = False  # 正在加载历史分页
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

        header = QWidget()
        header.setObjectName("chat_header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(32, 14, 32, 14)
        header_layout.setSpacing(12)

        title = QLabel("AI 助手")
        title.setObjectName("chat_title")
        header_layout.addWidget(title)
        header_layout.addStretch()

        self.auto_approve_toggle = QPushButton()
        self.auto_approve_toggle.setObjectName("chat_auto_approve_toggle")
        self.auto_approve_toggle.setCheckable(True)
        self.auto_approve_toggle.setToolTip("当前会话内自动允许 Assistant 高危工具")
        self.auto_approve_toggle.clicked.connect(self._on_auto_approve_toggle_clicked)
        self._refresh_auto_approve_toggle_text(False)
        header_layout.addWidget(self.auto_approve_toggle)

        chat_layout.addWidget(header)

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

        self._messages_scroll = messages_scroll
        messages_scroll.verticalScrollBar().valueChanged.connect(self._on_messages_scroll)

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
            self._all_sessions = ChatService().get_sessions_with_preview()
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
            s
            for s in self._all_sessions
            if keyword in s["title"].lower() or keyword in s["preview"].lower()
        ]

    def _render_session_cards(self):
        """渲染会话卡片"""
        # 清空已有卡片
        clear_layout(self._cards_layout)

        filtered = self._get_filtered_sessions()
        show_count = min(
            (self._sessions_page + 1) * self._sessions_page_size,
            len(filtered),
        )

        for s in filtered[:show_count]:
            card = SessionCard(s["session_id"], s["title"], s["preview"], s["date_str"])
            card.clicked.connect(self._on_session_card_clicked)
            self._cards_layout.addWidget(card)

        # 空状态提示
        if show_count == 0:
            hint_text = (
                "没有找到匹配的对话" if self._search_text else "还没有对话，点击「新建对话」开始吧"
            )
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

    # =========================================================================
    # 对话视图：会话管理
    # =========================================================================

    def _prepare_new_chat(self, tool_ids=None):
        """准备新对话界面（不立即创建 DB 会话，等用户发第一条消息时再创建）"""
        self._session_id = None
        self._pending_tool_ids = tool_ids
        self._set_auto_approve_toggle_visible(False)
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
        """从数据库加载会话历史消息（使用展示分页，初始 10 条）"""
        try:
            page = ChatService().get_display_messages(session_id, limit=10)
            if not page.messages:
                self._set_auto_approve_toggle_visible(False)
                self._add_welcome_message()
                return
            for msg in page.messages:
                self._add_message(msg.role, msg.content)
            if page.messages:
                self._oldest_loaded_sequence = page.messages[0].sequence
            self._has_more_history = page.has_more_before
            self._mark_conversation_started()
        except Exception as e:
            self.logger.error(f"加载会话消息失败: {e}")
            self._set_auto_approve_toggle_visible(False)
            self._add_welcome_message()

    # =========================================================================
    # 消息区域
    # =========================================================================

    def _clear_messages(self):
        """清空消息区域并重置分页状态"""
        self._welcome_visible = False
        self._welcome_input = None
        self._oldest_loaded_sequence = None
        self._has_more_history = False
        self._loading_history_page = False
        clear_layout(self.messages_layout)

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
                32,
                32,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
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
        if role == "assistant":
            md_view = MarkdownMessageView(content)
            md_view.setObjectName("content_assistant")
            bubble_content_layout.addWidget(md_view)
            content_label.hide()
            bubble_content_layout.addWidget(content_label)
        else:
            bubble_content_layout.addWidget(content_label)
        bubble_layout.addWidget(message_bubble)
        container_layout.addWidget(bubble_container)

        if role == "assistant":
            container_layout.addStretch()

        self.messages_layout.addWidget(message_container)
        QTimer.singleShot(100, self._scroll_to_bottom)

    def _scroll_to_bottom(self):
        """滚动消息区域到底部"""
        scroll_to_bottom("messages_scroll", self)

    def _on_messages_scroll(self, value):
        """消息区域滚动 — 顶部加载更早历史"""
        if not self._has_more_history or self._loading_history_page:
            return
        scrollbar = self._messages_scroll.verticalScrollBar()
        if value <= scrollbar.minimum() + 50:
            self._load_older_history()

    def _load_older_history(self):
        """加载更早一页历史消息"""
        if not self._session_id or not self._oldest_loaded_sequence:
            return
        self._loading_history_page = True
        try:
            page = ChatService().get_display_messages(
                self._session_id, limit=10, before_sequence=self._oldest_loaded_sequence,
            )
            if page.messages:
                self._prepend_older_messages(page.messages)
                self._oldest_loaded_sequence = page.messages[0].sequence
            self._has_more_history = page.has_more_before
        except Exception as e:
            self.logger.error(f"加载更早历史失败: {e}")
        finally:
            self._loading_history_page = False

    def _prepend_older_messages(self, messages):
        """在消息区域顶部插入更早的历史消息，保持视口位置"""
        scrollbar = self._messages_scroll.verticalScrollBar()
        old_max = scrollbar.maximum()
        old_value = scrollbar.value()

        for msg in reversed(messages):
            self._insert_message_at_top(msg.role, msg.content)

        self.messages_layout.invalidate()
        self._messages_scroll.widget().adjustSize()
        new_max = scrollbar.maximum()
        scrollbar.setValue(new_max - old_max + old_value)

    def _insert_message_at_top(self, role: str, content: str):
        """在消息区域最前面插入一条消息（不自动滚动）"""
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
        if role == "assistant":
            md_view = MarkdownMessageView(content)
            md_view.setObjectName("content_assistant")
            bubble_content_layout.addWidget(md_view)
            content_label.hide()
            bubble_content_layout.addWidget(content_label)
        else:
            bubble_content_layout.addWidget(content_label)
        bubble_layout.addWidget(message_bubble)
        container_layout.addWidget(bubble_container)

        if role == "assistant":
            container_layout.addStretch()

        self.messages_layout.insertWidget(0, message_container)

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
        self.set_auto_approve_enabled(False)
        self._prepare_new_chat()
        self.new_chat_started.emit()

    def show_session_list(self):
        """显示会话列表视图（供 MainWindow 在页面切换时调用）"""
        self._set_auto_approve_toggle_visible(False)
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

    def set_auto_approve_enabled(self, enabled: bool):
        """同步顶栏免确认 Toggle 状态，不发出用户切换信号。"""
        self.auto_approve_toggle.blockSignals(True)
        try:
            self.auto_approve_toggle.setChecked(enabled)
            self._refresh_auto_approve_toggle_text(enabled)
        finally:
            self.auto_approve_toggle.blockSignals(False)

    def _set_auto_approve_toggle_visible(self, visible: bool):
        """改变 Toggle 可见性，不发出 auto_approve_toggled 信号。"""
        self.auto_approve_toggle.setVisible(visible)

    def _mark_conversation_started(self):
        """标记对话已启动，显示 Toggle。"""
        self._set_auto_approve_toggle_visible(True)

    # =========================================================================
    # Private
    # =========================================================================

    def _get_display_name(self) -> str:
        """从用户偏好档案获取称呼"""
        return ChatService().get_display_name()

    def _on_auto_approve_toggle_clicked(self, checked: bool) -> None:
        self._refresh_auto_approve_toggle_text(checked)
        self.auto_approve_toggled.emit(checked)

    def _refresh_auto_approve_toggle_text(self, enabled: bool) -> None:
        state = "开启" if enabled else "关闭"
        self.auto_approve_toggle.setText(f"免确认：{state}")
        self.auto_approve_toggle.setProperty("autoApproveEnabled", enabled)
        style = self.auto_approve_toggle.style()
        style.unpolish(self.auto_approve_toggle)
        style.polish(self.auto_approve_toggle)

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
        self._mark_conversation_started()

        session_id = self.get_session_id()
        self.send_message_requested.emit(session_id, AgentType.ASSISTANT, message)

    def _create_session(self, tool_ids=None) -> str:
        """创建新的助理会话。tool_ids: list[str] 或 None（全部工具）"""
        try:
            return ChatService().create_session(tool_ids)
        except Exception as e:
            self.logger.error(f"创建会话失败: {e}")
            return ChatService.generate_session_id()
