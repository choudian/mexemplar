"""
PyQt6 主窗口

职责：
1. 创建主界面框架（侧边栏 + 主内容区 + 菜单栏）
2. 页面导航与切换
3. Toast 通知

Agent、录制、工具试用等业务逻辑分别由以下 Mixin 承载：
- RecordingMixin      — 录制生命周期
- AgentBridgeMixin    — AgentUIBridge 初始化管理
- AgentHandlerMixin   — Agent 事件处理
"""

import threading
from pathlib import Path

from PyQt6.QtCore import Qt, QTimer, QSize, pyqtSignal
from PyQt6.QtGui import QAction, QIcon, QResizeEvent
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QWidget,
)

from src.ui.mixins import AgentBridgeMixin, AgentHandlerMixin, OrchestratorInitStatus, RecordingMixin
from src.ui.page_ids import CONVERSATIONS, INTENT_CONFIRMATION, SETTINGS, SKILLS, TEACHING
from src.ui.resources.icons.sidebar_icons import (
    FILE_ICON,
    HELP_ICON,
    SIDEBAR_CLOSE_ICON,
    SIDEBAR_OPEN_ICON,
)
from src.ui.utils import create_svg_icon
from src.ui.widgets.chat_widget import ChatWidget
from src.ui.widgets.main_content_widget import MainContentWidget
from src.ui.widgets.recording_widget import RecordingWidget
from src.ui.widgets.settings_page import SettingsPage
from src.ui.widgets.sidebar_widget import SidebarWidget
from src.utils.logger import get_logger


class MainWindow(AgentBridgeMixin, AgentHandlerMixin, RecordingMixin, QMainWindow):
    """Mexemplar 主窗口"""

    # 高危工具用户确认信号（跨线程：worker 线程 emit → UI 线程弹框）
    _confirm_action_signal = pyqtSignal(str, str)  # (request_id, message)

    # 定义信号（线程安全的 UI 通信）
    recording_start_success = pyqtSignal()
    recording_start_failed = pyqtSignal(str)
    recording_error = pyqtSignal(str)
    extension_recording_started = pyqtSignal(str)
    extension_recording_stopped = pyqtSignal()
    _agent_start_requested = pyqtSignal(str)       # recording_id，跨线程触发 start_agent
    _switch_to_intent_page = pyqtSignal()           # 跨线程切换到意图确认页
    _ensure_bridge_requested = pyqtSignal()         # 跨线程创建 AgentUIBridge

    def __init__(self) -> None:
        self.logger = get_logger(__name__)
        self.logger.info("[MainWindow] __init__ 开始")
        super().__init__()
        self.logger.info("[MainWindow] super().__init__() 完成")

        self.sidebar = None
        self.main_content = None
        self.browser_recorder = None
        self.agent_ui_bridge = None
        self._pending_bridge = None

        # AgentUIBridge 异步初始化状态
        self._orchestrator_init_lock = threading.Lock()
        self._orchestrator_init_condition = threading.Condition(self._orchestrator_init_lock)
        self._orchestrator_init_status = OrchestratorInitStatus.NOT_STARTED
        self._orchestrator_init_error = None
        self._orchestrator_warmup_thread = None

        self._sidebar_visible = True
        self._active_toast = None
        self.menubar = None

        # Agent 会话上下文
        self._current_agent_workflow_id = None
        self._current_agent_type = None
        self._current_composition_trial_session_id = None
        self._composition_trial_thread = None

        self._bridge_created_event = threading.Event()

        self.logger.info("[MainWindow] 开始加载样式")
        self._load_styles()
        self.logger.info("[MainWindow] 样式加载完成，开始初始化 UI")
        self.init_ui()
        self.logger.info("[MainWindow] UI 初始化完成")
        self._bind_recording_ui_events()

        if not self._initialize_browser_recorder():
            self.logger.warning("App 启动时 BrowserRecorder 初始化失败，后续将按需重试")

        self.logger.info("[MainWindow] 开始预热线程")
        self._warmup_orchestrator_async()
        self.logger.info("[MainWindow] __init__ 完成")

    # =========================================================================
    # UI 初始化
    # =========================================================================

    def _load_styles(self) -> None:
        """加载样式表"""
        try:
            style_path = Path(__file__).parent / "resources" / "styles.qss"
            if style_path.exists():
                with open(style_path, "r", encoding="utf-8") as f:
                    self.setStyleSheet(f.read())
                    self.logger.info(f"已加载样式表: {style_path}")
            else:
                self.logger.warning(f"样式表文件不存在: {style_path}")
        except Exception as e:
            self.logger.warning(f"加载样式表失败: {e}")

    def init_ui(self) -> None:
        """初始化用户界面"""
        self.setWindowTitle("Mexemplar")
        self.setMinimumSize(1000, 700)
        self.resize(1200, 800)
        self.logger.info(
            f"窗口几何信息: x={self.x()}, y={self.y()}, "
            f"width={self.width()}, height={self.height()}"
        )

        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QHBoxLayout(central_widget)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        self.sidebar = SidebarWidget()
        self.sidebar.setFixedWidth(260)
        main_layout.addWidget(self.sidebar)

        self.main_content = MainContentWidget()
        main_layout.addWidget(self.main_content, 1)

        # 页面
        chat_page = ChatWidget()
        chat_page.send_message_requested.connect(self._on_chat_send_message)
        self.main_content.add_page(CONVERSATIONS, chat_page)

        self.recording_page = RecordingWidget()
        self.recording_page.recording_started.connect(self._on_recording_started)
        self.recording_page.recording_stopped.connect(self._on_recording_stopped)
        self.extension_recording_started.connect(self.recording_page.on_extension_recording_started)
        self.extension_recording_stopped.connect(self.recording_page.on_extension_recording_stopped)
        self.main_content.add_page(TEACHING, self.recording_page)

        from src.ui.intent_confirmation_ui import IntentConfirmationUI
        self.intent_confirmation_page = IntentConfirmationUI()
        self.main_content.add_page(INTENT_CONFIRMATION, self.intent_confirmation_page)

        from src.ui.tools_management_ui import ToolsManagementUI
        self.pending_tools_page = ToolsManagementUI()
        self.main_content.add_page(SKILLS, self.pending_tools_page)

        settings_page = SettingsPage()
        self.main_content.add_page(SETTINGS, settings_page)

        # 信号连接
        self.sidebar.navigation_requested.connect(self.main_content.switch_page)
        self.main_content.page_changed.connect(self._on_page_changed)

        self.intent_confirmation_page.analyze_intent_request.connect(
            self._on_intent_analyze_request
        )
        self.intent_confirmation_page.agent_resume_request.connect(self._on_agent_resume_request)
        self.intent_confirmation_page.cancel_requested.connect(self._on_intent_cancel_requested)

        self.pending_tools_page.trial_start_request.connect(self._on_trial_start_request)
        self.pending_tools_page.composition_trial_request.connect(self._on_composition_trial_request)
        self.pending_tools_page.tool_delete_request.connect(self._on_tool_delete_request)
        self.pending_tools_page.tool_update_request.connect(self._on_tool_update_request)
        self.pending_tools_page.retry_requested.connect(self._on_retry_requested)

        self.sidebar.new_chat_requested.connect(self._on_new_chat_requested)

        self.recording_start_success.connect(self._on_recording_start_success)
        self.recording_start_failed.connect(self._on_recording_start_failed)
        self.recording_error.connect(self._on_recording_error)
        self._ensure_bridge_requested.connect(self._on_ensure_bridge_requested)

        self.main_content.switch_page(CONVERSATIONS)
        chat_page = self._get_chat_widget()
        if chat_page:
            chat_page.on_new_chat()

        self.create_menu_bar()

    def _bind_recording_ui_events(self) -> None:
        """监听录制事件并转发到主线程 UI。"""
        from src.utils.events import connect, event_value
        from src.recording.browser_recorder import RecordingMode

        def on_recording_started(sender, **kwargs):
            event_data = kwargs.get("event_data")
            if event_value(event_data, "recording_mode") != RecordingMode.EXTENSION_TRIGGERED:
                return
            recording_id = event_value(event_data, "recording_id", "session_id") or ""
            self.extension_recording_started.emit(str(recording_id))

        def on_recording_stopped(sender, **kwargs):
            event_data = kwargs.get("event_data")
            if event_value(event_data, "recording_mode") != RecordingMode.EXTENSION_TRIGGERED:
                return
            self.extension_recording_stopped.emit()

        self._on_extension_recording_started_handler = on_recording_started
        self._on_extension_recording_stopped_handler = on_recording_stopped
        connect("recording_started", self._on_extension_recording_started_handler)
        connect("recording_stopped", self._on_extension_recording_stopped_handler)

    def create_menu_bar(self) -> None:
        """创建菜单栏"""
        self.menubar = self.menuBar()

        def create_toolbar_btn(icon: QIcon, tooltip: str):
            btn = QPushButton()
            btn.setFixedSize(28, 28)
            btn.setIcon(icon)
            btn.setIconSize(QSize(20, 20))
            btn.setToolTip(tooltip)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setObjectName("menubar_tool_button")
            return btn

        left_tools = QWidget()
        left_tools.setObjectName("menubar_left_tools")
        left_layout = QHBoxLayout(left_tools)
        left_layout.setContentsMargins(8, 0, 0, 0)
        left_layout.setSpacing(4)
        left_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        self.toggle_sidebar_btn = create_toolbar_btn(
            create_svg_icon(SIDEBAR_OPEN_ICON), "折叠侧边栏"
        )
        self.toggle_sidebar_btn.clicked.connect(self._toggle_sidebar)
        left_layout.addWidget(self.toggle_sidebar_btn)

        file_menu = self.menubar.addMenu("")
        exit_action = QAction("退出(&X)", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)
        btn_file = create_toolbar_btn(create_svg_icon(FILE_ICON), "文件")
        btn_file.setMenu(file_menu)
        left_layout.addWidget(btn_file)

        help_menu = self.menubar.addMenu("")
        about_action = QAction("关于(&A)", self)
        about_action.triggered.connect(self._show_about_dialog)
        help_menu.addAction(about_action)
        btn_help = create_toolbar_btn(create_svg_icon(HELP_ICON), "帮助")
        btn_help.setMenu(help_menu)
        left_layout.addWidget(btn_help)

        self.menubar.setCornerWidget(left_tools, Qt.Corner.TopLeftCorner)

    # =========================================================================
    # 导航 / 页面切换
    # =========================================================================

    def _on_page_changed(self, page_name: str) -> None:
        """每次切换页面时触发各页面刷新"""
        if page_name == CONVERSATIONS:
            chat_page = self._get_chat_widget()
            if chat_page:
                chat_page.show_session_list()
        elif page_name == SKILLS:
            page = self.main_content.get_page(SKILLS)
            if page:
                page.refresh()

    def _switch_to_pending_tools(self) -> None:
        """切换到待试用工具页面"""
        self.logger.info("自动切换到待试用工具页面")
        self.main_content.switch_page(SKILLS)

    def _switch_to_welcome_page(self) -> None:
        """需求确认后自动切回欢迎页（仅当用户仍在意图确认页时）"""
        if self.main_content.get_current_page() != INTENT_CONFIRMATION:
            self.logger.info("用户已离开意图确认页，跳过自动切换")
            return
        self.logger.info("切换到欢迎页")
        try:
            self.main_content.blockSignals(True)
            self.main_content.switch_page(CONVERSATIONS)
        finally:
            self.main_content.blockSignals(False)
        chat_widget = self._get_chat_widget()
        if chat_widget:
            chat_widget.on_new_chat()

    def _get_chat_widget(self):
        """获取 ChatWidget 实例"""
        return self.main_content.get_page(CONVERSATIONS)

    def _toggle_sidebar(self) -> None:
        """切换侧边栏折叠/展开"""
        if self._sidebar_visible:
            self.sidebar.hide()
            self.toggle_sidebar_btn.setIcon(create_svg_icon(SIDEBAR_CLOSE_ICON))
            self.toggle_sidebar_btn.setToolTip("展开侧边栏")
            self._sidebar_visible = False
            self.logger.info("Sidebar collapsed")
        else:
            self.sidebar.show()
            self.toggle_sidebar_btn.setIcon(create_svg_icon(SIDEBAR_OPEN_ICON))
            self.toggle_sidebar_btn.setToolTip("折叠侧边栏")
            self._sidebar_visible = True
            self.logger.info("Sidebar expanded")

    def _on_new_chat_requested(self) -> None:
        """新建对话请求"""
        self.logger.info("新建对话")
        self.main_content.switch_page(CONVERSATIONS)
        chat_page = self._get_chat_widget()
        if chat_page:
            chat_page.on_new_chat()

    # =========================================================================
    # Toast 通知
    # =========================================================================

    @staticmethod
    def _truncate_error(msg: str, max_len: int = 80) -> str:
        """截断错误信息用于 toast 显示"""
        return msg[:max_len] + ("..." if len(msg) > max_len else "")

    def _show_toast(
        self, text: str, auto_dismiss_ms: int = 8000, toast_type: str = "success"
    ) -> None:
        """右下角浮层 toast 通知"""
        if self._active_toast is not None:
            self._active_toast.deleteLater()
            self._active_toast = None

        toast = QFrame(self.centralWidget())
        toast.setProperty("toastType", toast_type)
        toast.setObjectName("notification_toast")

        layout = QHBoxLayout(toast)
        layout.setContentsMargins(14, 8, 14, 8)

        icon = QLabel("❌" if toast_type == "error" else "✅")
        icon.setFixedWidth(20)
        layout.addWidget(icon)

        label = QLabel(text)
        label.setObjectName("notification_toast_text")
        label.setWordWrap(True)
        layout.addWidget(label, 1)

        close_btn = QPushButton("×")
        close_btn.setObjectName("notification_toast_close")
        close_btn.setFixedSize(18, 18)
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        layout.addWidget(close_btn)

        toast.setFixedWidth(320)
        toast.adjustSize()
        x = self.centralWidget().width() - toast.width() - 16
        y = self.centralWidget().height() - toast.height() - 16
        toast.move(x, y)
        toast.raise_()
        style = toast.style()
        for w in (toast, label):
            style.unpolish(w)
            style.polish(w)
        toast.show()

        self._active_toast = toast

        auto_timer = QTimer(toast)
        auto_timer.setSingleShot(True)

        def _dismiss():
            if self._active_toast is toast:
                self._active_toast = None
            toast.deleteLater()

        close_btn.clicked.connect(_dismiss)
        auto_timer.timeout.connect(_dismiss)
        auto_timer.start(auto_dismiss_ms)

    def resizeEvent(self, event: QResizeEvent):
        """窗口大小变化时重新定位 toast"""
        super().resizeEvent(event)
        if self._active_toast is not None:
            central = self.centralWidget()
            x = central.width() - self._active_toast.width() - 16
            y = central.height() - self._active_toast.height() - 16
            self._active_toast.move(x, y)

    # =========================================================================
    # 对话框 / 关闭
    # =========================================================================

    def _show_about_dialog(self) -> None:
        """显示关于对话框"""
        QMessageBox.about(
            self,
            "关于 Mexemplar",
            """
            <h2>Mexemplar</h2>
            <p><b>版本：</b>0.1.0</p>
            <p><b>桌面端智能办公助理</b></p>
            <p>基于示例驱动的自动化工具</p>
            <hr>
            <p>核心功能：</p>
            <ul>
                <li>📹 浏览器/桌面技能教学</li>
                <li>🤖 AI 智能工作流生成</li>
                <li>▶️ 自动化脚本执行</li>
                <li>📊 工具管理和分享</li>
            </ul>
            <hr>
            <p>© 2026 Mexemplar Project</p>
            """,
        )

    def closeEvent(self, event) -> None:
        """窗口关闭：确保资源正确释放"""
        self.logger.info("正在关闭应用程序...")

        if self.browser_recorder is not None:
            try:
                self.logger.info("停止正在进行的录制...")
                self.browser_recorder.stop_recording()
            except Exception as e:
                self.logger.error(f"停止录制失败: {e}")
            try:
                self.browser_recorder.cleanup()
            except Exception as e:
                self.logger.error(f"清理录制器失败: {e}")
            self.browser_recorder = None

        try:
            from src.data.duckdb_manager import DuckDBManager
            db_manager = DuckDBManager()
            if db_manager.conn is not None:
                db_manager.close()
                self.logger.info("DuckDB 连接已关闭")
        except Exception as e:
            self.logger.error(f"关闭 DuckDB 失败: {e}")

        event.accept()
        self.logger.info("应用程序已关闭")
