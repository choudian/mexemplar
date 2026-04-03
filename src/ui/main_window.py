"""
PyQt6 主窗口

职责：
1. 创建主界面框架
2. 提供功能按钮和菜单栏
3. 集成各个功能模块
"""

from enum import Enum
from pathlib import Path
import threading

from PyQt6.QtCore import Qt, QTimer, QSize, pyqtSignal
from PyQt6.QtGui import QResizeEvent

from src.ui.page_ids import (
    CONVERSATIONS,
    INTENT_CONFIRMATION,
    SETTINGS,
    SKILLS,
    TEACHING,
)
from PyQt6.QtGui import QAction, QIcon
from PyQt6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QWidget,
)

from src.ui.utils import create_svg_icon
from src.recording.browser_recorder import BrowserRecorder
from src.business.agents.config import AgentType
from src.communication.websocket_manager import WebSocketServerManager
from src.ui.widgets.chat_widget import ChatWidget
from src.ui.widgets.main_content_widget import MainContentWidget
from src.ui.widgets.recording_widget import RecordingWidget
from src.ui.widgets.settings_page import SettingsPage
from src.ui.widgets.sidebar_widget import SidebarWidget
from src.ui.resources.icons.sidebar_icons import (
    FILE_ICON,
    HELP_ICON,
    SIDEBAR_CLOSE_ICON,
    SIDEBAR_OPEN_ICON,
)
from src.utils.logger import get_logger


class OrchestratorInitStatus(Enum):
    """AgentUIBridge 初始化状态枚举"""

    NOT_STARTED = "not_started"
    INITIALIZING = "initializing"
    READY = "ready"
    FAILED = "failed"


class MainWindow(QMainWindow):
    """Mexemplar 主窗口"""

    # 高危工具用户确认信号（跨线程：worker 线程 emit → UI 线程弹框）
    _confirm_action_signal = pyqtSignal(str, str)  # (request_id, message)

    # 类常量
    _DEFAULT_INIT_TIMEOUT = 5.0  # 默认初始化超时（秒）

    # Agent 类型中文显示名
    _AGENT_TYPE_DISPLAY = {
        "pm": "需求分析",
        "programmer": "技能学习",
        "trial": "试用",
    }

    # 定义信号（线程安全的 UI 通信）
    recording_start_success = pyqtSignal()
    recording_start_failed = pyqtSignal(str)  # 参数：错误消息
    recording_error = pyqtSignal(str)  # 参数：错误详情
    workflow_error = pyqtSignal(str, str)  # 参数：错误消息，错误类型
    _agent_start_requested = pyqtSignal(str)  # 参数：recording_id，用于跨线程安全触发 start_agent
    _switch_to_intent_page = pyqtSignal()  # 跨线程安全切换到意图确认页面
    _ensure_bridge_requested = pyqtSignal()  # 跨线程安全创建 AgentUIBridge

    def __init__(self) -> None:
        """初始化主窗口"""
        self.logger = get_logger(__name__)
        self.logger.info("[MainWindow] __init__ 开始")
        super().__init__()
        self.logger.info("[MainWindow] super().__init__() 完成")

        self.sidebar = None  # 侧边栏
        self.main_content = None  # 主内容区
        self.browser_recorder = None  # 浏览器录制器
        self.agent_ui_bridge = None  # v2 Agent UI 桥接（懒加载）

        # 意图确认相关组件
        self.ws_manager = None  # WebSocket 服务器管理器

        # AgentUIBridge 异步初始化状态
        self._orchestrator_init_lock = threading.Lock()
        self._orchestrator_init_condition = threading.Condition(self._orchestrator_init_lock)
        self._orchestrator_init_status = OrchestratorInitStatus.NOT_STARTED
        self._orchestrator_init_error = None  # 初始化错误信息
        self._orchestrator_warmup_thread = None  # 预热线程引用

        self._sidebar_visible = True  # 跟踪侧边栏状态（统一使用 _ 前缀）
        self._active_toast = None  # 当前活跃的 toast 通知
        self.menubar = None  # 菜单栏引用

        # Agent 会话上下文
        self._current_agent_workflow_id = None  # 当前 Agent 工作流 ID
        self._current_agent_type = None  # 当前 Agent 类型

        # 用于跨线程安全创建 AgentUIBridge 的事件通知
        self._bridge_created_event = threading.Event()

        self.logger.info("[MainWindow] 开始加载样式")
        self._load_styles()
        self.logger.info("[MainWindow] 样式加载完成，开始初始化 UI")
        self.init_ui()
        self.logger.info("[MainWindow] UI 初始化完成")

        # ❌ 不在 __init__ 中启动 WebSocket 服务器，避免阻塞
        # 改为延迟启动，在窗口显示后再启动

        # 启动后台预热线程
        self.logger.info("[MainWindow] 开始预热线程")
        self._warmup_orchestrator_async()
        self.logger.info("[MainWindow] __init__ 完成")

        # 使用 QTimer 延迟启动 WebSocket 服务器
        QTimer.singleShot(100, self._delayed_init_intent_confirmer)

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
        # 设置窗口属性
        self.setWindowTitle("Mexemplar")
        self.setMinimumSize(1000, 700)
        self.resize(1200, 800)  # 显式设置初始大小
        self.logger.info(
            f"窗口几何信息: x={self.x()}, y={self.y()}, width={self.width()}, height={self.height()}"
        )

        # 创建中心部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # 创建主布局 (水平布局：Sidebar + MainContent)
        main_layout = QHBoxLayout(central_widget)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # ============ 创建侧边栏 ============
        self.sidebar = SidebarWidget()
        self.sidebar.setFixedWidth(260)
        main_layout.addWidget(self.sidebar)

        # ============ 创建主内容区 ============
        self.main_content = MainContentWidget()
        main_layout.addWidget(self.main_content, 1)  # stretch=1

        # ============ 添加页面到主内容区 ============
        # AI 对话页面
        chat_page = ChatWidget()
        chat_page.send_message_requested.connect(self._on_chat_send_message)
        self.main_content.add_page(CONVERSATIONS, chat_page)

        # 录制页面
        self.recording_page = RecordingWidget()
        self.recording_page.recording_started.connect(self._on_recording_started)
        self.recording_page.recording_stopped.connect(self._on_recording_stopped)
        self.main_content.add_page(TEACHING, self.recording_page)

        # 意图确认页面
        from src.ui.intent_confirmation_ui import IntentConfirmationUI

        self.intent_confirmation_page = IntentConfirmationUI()
        self.main_content.add_page(INTENT_CONFIRMATION, self.intent_confirmation_page)

        # 待试用工具列表页面
        from src.ui.tools_management_ui import ToolsManagementUI

        self.pending_tools_page = ToolsManagementUI()
        self.main_content.add_page(SKILLS, self.pending_tools_page)

        # 设置页面
        settings_page = SettingsPage()
        self.main_content.add_page(SETTINGS, settings_page)

        # ============ 连接信号和槽 ============
        # 侧边栏导航 -> 主内容区页面切换
        self.sidebar.navigation_requested.connect(self.main_content.switch_page)
        # 每次切页时触发各页面刷新
        self.main_content.page_changed.connect(self._on_page_changed)

        # ⭐ 连接 IntentConfirmationUI 的信号到 MainWindow 处理
        self.intent_confirmation_page.analyze_intent_request.connect(
            self._on_intent_analyze_request
        )
        # Agent 模式信号：恢复 Agent
        self.intent_confirmation_page.agent_resume_request.connect(
            self._on_agent_resume_request
        )

        # ⭐ 连接 ToolsManagementUI 的信号到 MainWindow 处理
        self.pending_tools_page.trial_start_request.connect(self._on_trial_start_request)
        self.pending_tools_page.tool_delete_request.connect(self._on_tool_delete_request)
        self.pending_tools_page.tool_update_request.connect(self._on_tool_update_request)
        self.pending_tools_page.retry_requested.connect(self._on_retry_requested)

        # 侧边栏新建对话 -> AI 对话页面新建对话
        self.sidebar.new_chat_requested.connect(self._on_new_chat_requested)

        # ⭐ 连接录制错误信号（线程安全的错误处理）
        self.recording_start_success.connect(self._on_recording_start_success)
        self.recording_start_failed.connect(self._on_recording_start_failed)
        self.recording_error.connect(self._on_recording_error)
        self.workflow_error.connect(self._on_workflow_error)

        # ⭐ 连接跨线程安全创建 AgentUIBridge 信号
        self._ensure_bridge_requested.connect(self._on_ensure_bridge_requested)

        # 默认显示 AI 对话页面（新建对话欢迎页）
        # 先 switch_page 让 main_content 切到 ChatWidget（内部栈默认显示会话列表），
        # 再调用 on_new_chat 翻转到欢迎页
        self.main_content.switch_page(CONVERSATIONS)
        chat_page = self._get_chat_widget()
        if chat_page:
            chat_page.on_new_chat()

        # 创建菜单栏
        self.create_menu_bar()

    def create_menu_bar(self) -> None:
        """创建菜单栏"""
        self.menubar = self.menuBar()

        # ============ 创建工具栏按钮辅助函数 ============
        def create_toolbar_btn(icon: QIcon, tooltip: str):
            """创建工具栏按钮"""
            btn = QPushButton()
            btn.setFixedSize(28, 28)
            btn.setIcon(icon)
            btn.setIconSize(QSize(20, 20))
            btn.setToolTip(tooltip)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setObjectName("menubar_tool_button")
            return btn

        # ============ 创建工具区容器 ============
        left_tools = QWidget()
        left_tools.setObjectName("menubar_left_tools")
        left_layout = QHBoxLayout(left_tools)
        left_layout.setContentsMargins(8, 0, 0, 0)
        left_layout.setSpacing(4)
        left_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # ============ 折叠按钮 ============
        self.toggle_sidebar_btn = create_toolbar_btn(
            create_svg_icon(SIDEBAR_OPEN_ICON), "折叠侧边栏"
        )
        self.toggle_sidebar_btn.clicked.connect(self._toggle_sidebar)
        left_layout.addWidget(self.toggle_sidebar_btn)

        # ============ 文件按钮 ============
        file_menu = self.menubar.addMenu("")  # 空标题，纯按钮

        exit_action = QAction("退出(&X)", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        btn_file = create_toolbar_btn(create_svg_icon(FILE_ICON), "文件")
        btn_file.setMenu(file_menu)
        left_layout.addWidget(btn_file)

        # ============ 帮助按钮 ============
        help_menu = self.menubar.addMenu("")  # 空标题，纯按钮

        about_action = QAction("关于(&A)", self)
        about_action.triggered.connect(self._show_about_dialog)
        help_menu.addAction(about_action)

        btn_help = create_toolbar_btn(create_svg_icon(HELP_ICON), "帮助")
        btn_help.setMenu(help_menu)
        left_layout.addWidget(btn_help)

        # ============ 将工具区放入菜单栏左上角 ============
        self.menubar.setCornerWidget(left_tools, Qt.Corner.TopLeftCorner)

    def _warmup_orchestrator_async(self) -> None:
        """
        异步预热 AgentUIBridge（后台线程）

        在应用启动时自动调用，在后台准备资源，避免首次使用时卡顿
        """

        def warmup() -> None:
            """后台预热任务"""
            try:
                with self._orchestrator_init_condition:
                    if self._orchestrator_init_status == OrchestratorInitStatus.READY:
                        self.logger.info("AgentUIBridge already ready, skipping warmup")
                        return

                    self._orchestrator_init_status = OrchestratorInitStatus.INITIALIZING
                    self.logger.info("Warming up AgentUIBridge in background...")

                bridge = self._create_agent_ui_bridge()

                with self._orchestrator_init_condition:
                    self.agent_ui_bridge = bridge
                    self._pending_bridge = None
                    self._orchestrator_init_status = OrchestratorInitStatus.READY
                    self.logger.info("AgentUIBridge warmup completed")
                    self._orchestrator_init_condition.notify_all()

            except Exception as e:
                with self._orchestrator_init_condition:
                    self._orchestrator_init_status = OrchestratorInitStatus.FAILED
                    self._orchestrator_init_error = str(e)
                    self._orchestrator_init_condition.notify_all()
                self.logger.error(f"AgentUIBridge warmup failed: {e}", exc_info=True)

        self._orchestrator_warmup_thread = threading.Thread(
            target=warmup, daemon=False, name="OrchestratorWarmup"
        )
        self._orchestrator_warmup_thread.start()
        self.logger.info("AgentUIBridge warmup thread started")

    def _delayed_init_intent_confirmer(self) -> None:
        """
        延迟初始化意图确认组件（在窗口显示后执行）

        使用后台线程启动 WebSocket 服务器，避免阻塞 UI
        """

        def init_in_background():
            """在后台线程中初始化"""
            try:
                self.logger.info("[延迟初始化] 开始在后台线程中初始化意图确认组件")

                # 创建 WebSocket 服务器管理器（不阻塞）
                self.ws_manager = WebSocketServerManager(
                    host="127.0.0.1",
                    port=8766,
                    auto_start=False,
                    startup_timeout=5.0,
                )

                # 启动服务器（阻塞式，但在后台线程中）
                self.ws_manager.start()

                # 获取 WebSocket 处理器
                ws_handler = self.ws_manager.get_handler()
                if not ws_handler:
                    self.logger.error("无法获取 WebSocket 处理器")
                    return

                # 注册意图分析完成的消息处理器
                from src.communication.message_types import MessageType

                ws_handler.register_handler(MessageType.INTENT_ANALYZED, self._on_intent_analyzed)

                self.logger.info("✅ [延迟初始化] 意图确认组件初始化成功")

            except Exception as e:
                self.logger.error(f"[延迟初始化] 初始化意图确认组件失败: {e}", exc_info=True)

        thread = threading.Thread(target=init_in_background, daemon=True)
        thread.start()
        self.logger.info("[延迟初始化] 后台初始化线程已启动")

    def _on_intent_analyzed(self, msg) -> dict:
        """处理意图分析完成的消息（WebSocket 回调，在后台线程执行）"""
        try:
            data = msg.data
            intent_id = data.get("intent_id")
            recording_id = data.get("recording_id")

            self.logger.info(f"收到意图分析完成消息: {intent_id}, 录制ID: {recording_id}")

            # 通过信号将页面切换投递到 UI 线程，避免在后台线程操作 Qt 控件
            self._switch_to_intent_page.emit()

            return {"status": "success"}

        except Exception as e:
            self.logger.error(f"处理意图分析消息失败: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    def _create_agent_ui_bridge(self):
        """
        创建 v2 AgentUIBridge 实例（内部方法）

        Returns:
            AgentUIBridge: 创建的实例

        Raises:
            Exception: 初始化失败时抛出异常
        """
        from src.business.ai.llm_client import LangChainLLMClient
        from src.business.orchestration.agent_orchestrator import AgentOrchestrator
        from src.ui.agent_ui_bridge import AgentUIBridge
        from src.data.unified_config import get_unified_config
        from src.utils.events import connect

        config = get_unified_config()
        llm_client = LangChainLLMClient(
            provider=config.get_ai_provider(),
            model=config.get_ai_model(),
            api_key=config.get_ai_api_key(),
            base_url=config.get_ai_base_url(),
            temperature=0.7,
        )

        orchestrator = AgentOrchestrator(llm_client=llm_client, config=config)
        bridge = AgentUIBridge(orchestrator)

        # 注册高危工具跨线程确认机制
        from src.business.agents.tools.builtin_general_tools import register_confirm_mechanism

        # 先 disconnect 再 connect，防止预热失败重建时信号重复连接
        try:
            self._confirm_action_signal.disconnect(self._on_confirm_action_requested)
        except TypeError:
            pass
        self._confirm_action_signal.connect(self._on_confirm_action_requested)
        register_confirm_mechanism(self._confirm_action_signal)

        # 启动后台任务队列 Worker
        orchestrator.start_task_worker()

        # 连接 v2 信号
        bridge.question_received.connect(self._on_agent_question)
        bridge.error_occurred.connect(self._on_agent_error)
        bridge.progress_updated.connect(self._on_agent_progress)
        bridge.tool_saved_signal.connect(self._on_tool_saved)
        bridge.tool_published_signal.connect(self._on_tool_published)
        bridge.retry_failed_signal.connect(self._on_retry_failed)
        bridge.failure_updated_signal.connect(self._on_failure_updated)
        self.logger.info("AgentUIBridge 信号已连接")

        # 监听录制完成事件，自动启动 PM Agent
        # 修复：blinker 回调在后台线程触发，不能直接调用 bridge.start_agent()。
        # 通过 _agent_start_requested 信号 + 真实 QObject slot 保证在主线程执行。
        # 注意：必须用真实方法作为 slot，lambda 没有 QObject 归属会退化为 DirectConnection。
        self._pending_bridge = bridge  # 让 slot 能访问到 bridge
        for sig, slot in [
            (self._agent_start_requested, self._on_agent_start_requested),
            (self._switch_to_intent_page, self._on_switch_to_intent_page),
        ]:
            try:
                sig.disconnect(slot)
            except TypeError:
                pass  # 首次调用时信号尚未连接，忽略
            sig.connect(slot)

        def on_recording_completed(sender, **kwargs):
            # event_data 可能是 RecordingEventData 对象（session_id 字段），也可能是 dict
            event_data = kwargs.get("event_data")
            if event_data is not None:
                recording_id = (
                    event_data.get("recording_id")
                    if isinstance(event_data, dict)
                    else getattr(event_data, "session_id", None)
                )
            else:
                recording_id = kwargs.get("recording_id")
            if not recording_id:
                return
            self.logger.info(f"[录制完成] 通过主线程信号启动 PM Agent 分析: {recording_id}")
            self._agent_start_requested.emit(recording_id)

        # 必须用实例属性持有强引用，否则 blinker 弱引用会在函数返回后被 GC 回收
        self._on_recording_completed_handler = on_recording_completed
        connect("recording_completed", self._on_recording_completed_handler)
        self.logger.info("已开始监听录制完成事件")

        return bridge

    def _on_switch_to_intent_page(self) -> None:
        """在主线程中重置意图确认页面并切换（由 _switch_to_intent_page 信号触发）"""
        self.intent_confirmation_page.reset()
        self.main_content.switch_page(INTENT_CONFIRMATION)

    def _on_agent_start_requested(self, recording_id: str) -> None:
        """在主线程中启动 PM Agent（由 _agent_start_requested 信号触发）"""
        bridge = getattr(self, "_pending_bridge", None) or self.agent_ui_bridge
        if not bridge:
            self.logger.error("AgentUIBridge 不可用，无法启动 Agent")
            return
        self.logger.info(f"[主线程] 启动 PM Agent 分析: {recording_id}")
        bridge.start_agent(
            "pm",
            f"请分析录制 {recording_id} 的操作流程，理解用户想要自动化的任务，并与用户确认需求。",
            recording_id,
        )

    def _on_agent_question(
        self, workflow_id: str, session_id: str, agent_type: str, question: str
    ) -> None:
        """
        处理 Agent 提问（需要用户回答）

        Args:
            workflow_id: 工作流 ID（= recording_id），assistant 类型为空字符串
            session_id: 会话 ID，assistant 类型使用此 ID 路由
            agent_type: Agent 类型（pm / programmer / trial / assistant）
            question: Agent 提出的问题
        """
        self.logger.info(
            f"Agent 提问: workflow={workflow_id}, session={session_id}, type={agent_type}, question={question[:80]}"
        )

        if agent_type == AgentType.ASSISTANT:
            # assistant 路由到 ChatWidget
            self._current_agent_type = agent_type
            chat_widget = self._get_chat_widget()
            if chat_widget:
                chat_widget.add_assistant_message(question)
                chat_widget.set_loading(False)
            return

        # 保存当前会话上下文，供用户回复时使用
        self._current_agent_workflow_id = workflow_id
        self._current_agent_type = agent_type

        if agent_type == AgentType.TRIAL:
            # Trial Agent：通过公共方法添加消息气泡，启用输入框
            self.main_content.switch_page(INTENT_CONFIRMATION)
            intent_page = self.main_content.get_page(INTENT_CONFIRMATION)
            if intent_page:
                intent_page.add_trial_question(question, workflow_id)
            return

        # PM Agent：使用结构化意图数据展示
        self._show_intent_confirmation_from_agent(
            {"message": question},
            question,
            workflow_id,
        )

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
        # unpolish/polish toast 及其子控件，确保动态属性 toastType 生效
        style = toast.style()
        for w in (toast, label):
            style.unpolish(w)
            style.polish(w)
        toast.show()

        self._active_toast = toast

        # timer 以 toast 为父对象——toast 删除时 timer 自动删除，信号自动断开
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
        """窗口大小变化时重新定位 toast 通知"""
        super().resizeEvent(event)
        if self._active_toast is not None:
            central = self.centralWidget()
            x = central.width() - self._active_toast.width() - 16
            y = central.height() - self._active_toast.height() - 16
            self._active_toast.move(x, y)

    def _on_agent_progress(self, workflow_id: str, event_name: str) -> None:
        """处理 Agent 进度事件"""
        self.logger.info(f"Agent 进度: workflow={workflow_id}, event={event_name}")

        if event_name == "requirement_confirmed":
            self._show_toast(
                "技能学习中，稍后回来…",
                auto_dismiss_ms=10000,
            )
            QTimer.singleShot(2000, self._switch_to_welcome_page)

    def _notify_skill_learned(self) -> None:
        """技能学习完毕后弹 toast 通知"""
        self._show_toast(
            "技能学习完毕！可以到「技能列表」查看并开始考核。",
            auto_dismiss_ms=10000,
        )

    def _on_tool_saved(self, workflow_id: str, tool_id: str, from_triage: bool = False) -> None:
        """工具入库后弹 toast 通知"""
        self.logger.info(
            f"工具已入库: workflow={workflow_id}, tool_id={tool_id}, from_triage={from_triage}"
        )
        if from_triage:
            # 分诊修复：保留用户对话，只切换到对话页面，等待 Agent 继续追加消息
            self.main_content.switch_page(INTENT_CONFIRMATION)
            return
        QTimer.singleShot(500, self._notify_skill_learned)

    def _on_tool_published(self, workflow_id: str, tool_id: str) -> None:
        """工具发布后切换到工具列表页"""
        self.logger.info(f"工具已发布: workflow={workflow_id}, tool_id={tool_id}")
        QTimer.singleShot(1500, self._switch_to_pending_tools)

    def _on_agent_error(
        self, workflow_id: str, session_id: str, agent_type: str, error_message: str
    ) -> None:
        """处理 Agent 错误"""
        self.logger.error(
            f"Agent 错误: workflow={workflow_id}, session={session_id}, type={agent_type} - {error_message}"
        )

        if agent_type == AgentType.ASSISTANT:
            chat = self._get_chat_widget()
            if chat:
                chat.add_error_message(error_message)
                chat.set_loading(False)
            return

        # agent_type 经 PyQt 信号传入，始终是 str（如 "pm"、"programmer"）
        display_type = self._AGENT_TYPE_DISPLAY.get(agent_type, agent_type)
        truncated = self._truncate_error(error_message)
        self._show_toast(
            f"{display_type}遇到问题：{truncated}",
            auto_dismiss_ms=15000,
            toast_type="error",
        )

        # PM Agent 失败时，切回欢迎页（否则用户会卡在意图确认页）
        if agent_type == AgentType.PM:
            self._switch_to_welcome_page()

    def _show_intent_confirmation_from_agent(
        self, intent_data: dict, message: str, thread_id: str
    ) -> None:
        """
        显示来自 Agent 的意图确认 UI

        Args:
            intent_data: 意图数据
            message: 确认消息
            thread_id: Agent 会话 ID
        """
        # 切换到意图确认页面
        self.main_content.switch_page(INTENT_CONFIRMATION)

        # 获取意图确认页面并更新内容
        intent_page = self.main_content.get_page(INTENT_CONFIRMATION)
        if intent_page and hasattr(intent_page, "load_intent_from_agent"):
            intent_page.load_intent_from_agent(intent_data, message, thread_id)

        self.logger.info("已切换到意图确认页面")

    def _on_agent_resume_request(self, thread_id: str, resume_data: dict) -> None:
        """
        处理 Agent 恢复请求（来自 IntentConfirmationUI）

        Args:
            thread_id: workflow_id（v2 中 thread_id 即 workflow_id）
            resume_data: 恢复数据（包含用户的确认回答）
        """
        self.logger.info(f"收到 Agent 恢复请求: workflow_id={thread_id}")

        user_input = resume_data.get("feedback") or resume_data.get("message", "")
        agent_type = self._current_agent_type

        if self.agent_ui_bridge:
            try:
                self.agent_ui_bridge.reply_to_agent(agent_type, user_input, thread_id)
                self.logger.info(f"已恢复 Agent: {thread_id}")
            except Exception as e:
                self.logger.error(f"恢复 Agent 失败: {e}", exc_info=True)
        else:
            self.logger.warning("AgentUIBridge 不可用")

    def _on_page_changed(self, page_name: str) -> None:
        """每次切换页面时触发各页面刷新"""
        if page_name == CONVERSATIONS:
            chat_page = self._get_chat_widget()
            if chat_page and hasattr(chat_page, "show_session_list"):
                chat_page.show_session_list()
        elif page_name == SKILLS:
            page = self.main_content.get_page(SKILLS)
            if page and hasattr(page, "load_tools"):
                page.load_tools()

    def _switch_to_pending_tools(self) -> None:
        """切换到待试用工具页面（switch_page 会触发 _on_page_changed 自动刷新）"""
        self.logger.info("自动切换到待试用工具页面")
        self.main_content.switch_page(SKILLS)

    def _toggle_sidebar(self) -> None:
        """切换侧边栏状态"""
        if self._sidebar_visible:
            # 折叠侧边栏
            self.sidebar.hide()
            self.toggle_sidebar_btn.setIcon(create_svg_icon(SIDEBAR_CLOSE_ICON))
            self.toggle_sidebar_btn.setToolTip("展开侧边栏")
            self._sidebar_visible = False
            self.logger.info("Sidebar collapsed")
        else:
            # 展开侧边栏
            self.sidebar.show()
            self.toggle_sidebar_btn.setIcon(create_svg_icon(SIDEBAR_OPEN_ICON))
            self.toggle_sidebar_btn.setToolTip("折叠侧边栏")
            self._sidebar_visible = True
            self.logger.info("Sidebar expanded")

    def _on_new_chat_requested(self) -> None:
        """新建对话请求 — 创建新会话并切换到对话视图"""
        self.logger.info("新建对话")
        self.main_content.switch_page(CONVERSATIONS)
        chat_page = self._get_chat_widget()
        if chat_page:
            chat_page.on_new_chat()

    def _get_chat_widget(self):
        """获取 ChatWidget 实例"""
        return self.main_content.get_page(CONVERSATIONS)

    def _on_confirm_action_requested(self, request_id: str, message: str):
        """
        UI 线程槽函数：收到 worker 线程的确认请求后弹框，
        结果通过 set_confirm_result(request_id, result) 唤醒对应 worker。
        """
        from src.business.agents.tools.builtin_general_tools import set_confirm_result

        reply = QMessageBox.question(
            self,
            "操作确认",
            message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        set_confirm_result(request_id, reply == QMessageBox.StandardButton.Yes)

    def _on_chat_send_message(self, session_id: str, agent_type: str, user_input: str):
        """ChatWidget 发送消息 → 通过 UIBridge 启动 Agent"""
        self.logger.info(f"Chat 发送消息: session={session_id}, input={user_input[:50]}...")
        if self.agent_ui_bridge is not None:
            self.agent_ui_bridge.start_agent(
                agent_type=agent_type,
                user_input=user_input,
                session_id=session_id,
            )
        else:
            self.logger.warning("[MainWindow] agent_ui_bridge 未初始化")
            chat = self._get_chat_widget()
            if chat:
                chat.add_error_message("AI 助手尚未初始化，请稍候...")
                chat.set_loading(False)

    def _on_recording_started(self, mode: str, url: str) -> None:
        """开始录制处理函数"""
        self.logger.info(f"开始录制: mode={mode}, url={url}")

        if mode == "browser":
            # 在后台线程中启动浏览器录制
            self._start_browser_recording(url)
        else:
            self.logger.warning(f"暂不支持 {mode} 录制模式")
            QMessageBox.warning(
                self, "不支持的模式", f"暂不支持 {mode} 模式\n\n当前仅支持浏览器操作。"
            )
            # 重置录制界面状态
            self.recording_page.reset()

    def _on_ensure_bridge_requested(self) -> None:
        """UI 线程槽函数：在 UI 线程中创建 AgentUIBridge（由 _ensure_bridge_requested 信号触发）"""
        try:
            self.logger.info("Creating AgentUIBridge on UI thread (via signal)...")
            bridge = self._create_agent_ui_bridge()

            with self._orchestrator_init_condition:
                self.agent_ui_bridge = bridge
                self._pending_bridge = None
                self._orchestrator_init_status = OrchestratorInitStatus.READY
                self.logger.info("AgentUIBridge created and ready (UI thread)")
                self._orchestrator_init_condition.notify_all()

        except Exception as e:
            with self._orchestrator_init_condition:
                self._orchestrator_init_status = OrchestratorInitStatus.FAILED
                self._orchestrator_init_error = str(e)
                self.agent_ui_bridge = None
                self._orchestrator_init_condition.notify_all()

            self.logger.error(f"AgentUIBridge initialization failed (UI thread): {e}", exc_info=True)
            self.recording_error.emit(
                f"Agent 编排器初始化失败：\n{str(e)}\n\n录制功能仍可使用，但不会自动启动 Agent。"
            )
        finally:
            self._bridge_created_event.set()

    def _ensure_agent_bridge(self, timeout: float = _DEFAULT_INIT_TIMEOUT) -> bool:
        """
        智能确保 AgentUIBridge 已初始化（懒加载 + 预热支持）

        如果在后台线程调用，会将 QObject 创建投递到 UI 线程执行。
        """
        with self._orchestrator_init_condition:
            if (
                self._orchestrator_init_status == OrchestratorInitStatus.READY
                and self.agent_ui_bridge
            ):
                return True

            if self._orchestrator_init_status == OrchestratorInitStatus.INITIALIZING:
                self.logger.info(f"AgentUIBridge is warming up, waiting up to {timeout} seconds...")
                self._orchestrator_init_condition.wait(timeout=timeout)

                if self._orchestrator_init_status == OrchestratorInitStatus.READY:
                    return True
                # 超时或失败，继续往下立即创建

            if self._orchestrator_init_status == OrchestratorInitStatus.FAILED:
                self.logger.warning(
                    f"Previous warmup failed: {self._orchestrator_init_error}, recreating..."
                )

            if self.agent_ui_bridge is not None:
                return True

            self._orchestrator_init_status = OrchestratorInitStatus.INITIALIZING

        # 检测是否在后台线程，如果是则投递到 UI 线程创建 QObject
        is_ui_thread = (
            threading.current_thread() is threading.main_thread()
        )
        if not is_ui_thread:
            self._bridge_created_event.clear()
            self._ensure_bridge_requested.emit()
            self._bridge_created_event.wait(timeout=timeout)
            with self._orchestrator_init_condition:
                return self._orchestrator_init_status == OrchestratorInitStatus.READY
        else:
            try:
                self.logger.info("Creating AgentUIBridge immediately...")
                bridge = self._create_agent_ui_bridge()

                with self._orchestrator_init_condition:
                    self.agent_ui_bridge = bridge
                    self._pending_bridge = None
                    self._orchestrator_init_status = OrchestratorInitStatus.READY
                    self.logger.info("AgentUIBridge created and ready")
                    self._orchestrator_init_condition.notify_all()

                return True

            except Exception as e:
                with self._orchestrator_init_condition:
                    self._orchestrator_init_status = OrchestratorInitStatus.FAILED
                    self._orchestrator_init_error = str(e)
                    self.agent_ui_bridge = None
                    self._orchestrator_init_condition.notify_all()

                self.logger.error(f"AgentUIBridge initialization failed: {e}", exc_info=True)
                self.recording_error.emit(
                    f"Agent 编排器初始化失败：\n{str(e)}\n\n录制功能仍可使用，但不会自动启动 Agent。"
                )
                return False

    def _start_browser_recording(self, url: str) -> None:
        """
        ⭐ 启动浏览器录制（在后台线程中）

        优化：AgentUIBridge 初始化也移到后台线程，避免阻塞 UI
        """

        def start_recording():
            """在后台线程中执行录制启动"""
            browser_recorder = None
            try:
                self.logger.info("正在启动浏览器录制器...")

                # ⭐ 优化2：捕获所有初始化错误，确保不会卡死
                try:
                    browser_recorder = BrowserRecorder()
                except Exception as init_error:
                    error_msg = (
                        f"浏览器录制器初始化失败：\n{str(init_error)}\n\n可能的原因：\n"
                        f"1. DuckDB 数据库文件被其他程序占用（如 PyCharm）\n"
                        f"2. 数据库文件损坏\n"
                        f"3. 磁盘空间不足\n\n"
                        f"解决方案：\n"
                        f"1. 关闭 PyCharm 或其他可能占用数据库的程序\n"
                        f"2. 检查 data/mexemplar.duckdb 文件是否存在\n"
                        f"3. 查看日志获取详细信息"
                    )

                    self.logger.error(f"浏览器录制器初始化失败: {init_error}", exc_info=True)
                    # ⭐ 使用信号而不是直接调用 QMessageBox（线程安全）
                    self.recording_start_failed.emit(error_msg)
                    return

                # 如果 URL 为空，传入 None，录制器会打开空白页
                start_url = url if url.strip() else None
                success = browser_recorder.start_recording(start_url=start_url)

                if success:
                    self.logger.info("浏览器录制已启动")
                    # ⭐ 保存到实例变量
                    self.browser_recorder = browser_recorder
                    # 发射成功信号
                    self.recording_start_success.emit()
                else:
                    self.logger.error("浏览器录制启动失败")
                    error_msg = "浏览器录制启动失败，请查看日志了解详情。"
                    # 发射失败信号
                    self.recording_start_failed.emit(error_msg)

            except Exception as e:
                self.logger.error(f"启动浏览器录制时出错: {e}", exc_info=True)
                # 发射错误信号（包含完整错误信息）
                error_msg = f"启动浏览器录制时出错：\n\n{str(e)}\n\n请查看日志了解详情。"
                self.recording_error.emit(error_msg)

                # ⭐ 清理资源
                if browser_recorder is not None:
                    try:
                        browser_recorder.cleanup()
                    except Exception as cleanup_error:
                        self.logger.error(f"清理录制器资源失败: {cleanup_error}", exc_info=True)

        # 在后台线程中启动录制，避免阻塞UI
        thread = threading.Thread(target=start_recording, daemon=True)
        thread.start()

    def _on_recording_stopped(self) -> None:
        """停止录制处理函数"""
        self.logger.info("停止录制")

        if self.browser_recorder:
            try:
                from src.utils.events import emit, RecordingEventData

                def stop_recording():
                    try:
                        result = self.browser_recorder.stop_recording()
                        recording_id = result.get("recording_id")
                        action_count = result.get("action_count", 0)

                        self.logger.info(f"录制已停止: {recording_id}")
                        self.logger.info(f"捕获了 {action_count} 个操作")

                        # 重置意图确认页面并切换（显示"正在分析..."）
                        # 注意：实际的意图内容会在 Agent interrupt 后通过 _on_agent_interrupt 更新
                        # 必须在 GUI 线程中操作 Qt 控件，通过 pyqtSignal 投递到主线程
                        self._switch_to_intent_page.emit()

                        # 确保 AgentUIBridge 已就绪（录制期间后台线程完成初始化）
                        if not self._ensure_agent_bridge(timeout=30.0):
                            self.logger.error("AgentUIBridge 不可用，无法启动 Agent 分析")
                            return

                        # 发射录制完成事件，AgentUIBridge 监听此事件后启动 PM Agent
                        emit(
                            "recording_completed",
                            event_data=RecordingEventData(
                                session_id=recording_id,
                                recording_mode="browser",
                                start_time=result.get("start_time"),
                                end_time=result.get("end_time"),
                                action_count=action_count,
                            ),
                        )
                        self.logger.info("已发射 recording_completed 事件，等待 Agent 处理...")
                    except Exception as e:
                        self.logger.error(f"停止录制时出错: {e}", exc_info=True)

                thread = threading.Thread(target=stop_recording, daemon=True)
                thread.start()
            except Exception as e:
                self.logger.error(f"停止录制时出错: {e}", exc_info=True)

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

    def _on_recording_start_success(self) -> None:
        """录制启动成功的槽函数（主线程中执行）"""
        self.logger.info("✅ 录制启动成功")
        # 可以在这里更新 UI 状态，比如禁用开始录制按钮

    def _on_recording_start_failed(self, error_message: str) -> None:
        """录制启动失败的槽函数（主线程中执行）"""
        self.logger.error(f"❌ 录制启动失败: {error_message}")
        # ⭐ 在主线程中显示错误消息（线程安全）
        QMessageBox.critical(self, "教学失败", error_message)

    def _on_recording_error(self, error_message: str) -> None:
        """录制错误的槽函数（主线程中执行）"""
        self.logger.error(f"❌ 录制错误: {error_message}")
        # ⭐ 在主线程中显示错误消息（线程安全）
        QMessageBox.critical(self, "教学错误", error_message)

    def _on_workflow_error(self, error_message: str, error_type: str) -> None:
        """工作流错误的槽函数（主线程中执行）"""
        self.logger.warning(f"⚠️ 工作流错误 ({error_type}): {error_message}")

        # 根据错误类型决定提示方式
        if error_type == "compression_model_fallback":
            # 压缩模型降级：显示警告提示（不阻断流程）
            QMessageBox.warning(
                self,
                "压缩模型警告",
                f"{error_message}\n\n已自动回退到规则引擎，工具生成将继续进行。",
            )
        else:
            # 其他错误：显示普通提示
            QMessageBox.warning(self, "工作流提示", error_message)

    # ===== UI 组件信号处理（替代 WebSocket 客户端）=====

    def _on_intent_analyze_request(self, intent_id: str, user_message: str) -> None:
        """
        处理意图分析请求（IntentConfirmationUI 信号）

        将用户消息传递给 Agent 进行处理
        """
        self.logger.info(f"收到意图分析请求: {intent_id}, 消息: {user_message[:50]}...")

        # Agent 模式：将用户消息作为 feedback 传递给 Agent
        workflow_id = self._current_agent_workflow_id
        agent_type = self._current_agent_type or AgentType.PM
        if workflow_id:
            if self.agent_ui_bridge:
                try:
                    self.agent_ui_bridge.reply_to_agent(agent_type, user_message, workflow_id)
                    self.logger.info(f"已传递用户反馈给 Agent: {workflow_id}")

                    intent_page = self.main_content.get_page(INTENT_CONFIRMATION)
                    if intent_page and hasattr(intent_page, "status_label"):
                        intent_page.status_label.setText("正在处理您的反馈...")

                except Exception as e:
                    self.logger.error(f"传递用户反馈失败: {e}", exc_info=True)
            else:
                self.logger.warning("AgentUIBridge 不可用")
        else:
            self.logger.warning("没有活跃的 Agent 会话")

    def _on_trial_start_request(self, pending_tool_id: str) -> None:
        """
        处理工具试用请求（PendingToolsUI 信号）

        pending_tool_id 即 tool_id，通过 ToolRepository 查 workflow_id，
        然后启动 trial Agent。
        """
        self.logger.info(f"收到工具试用请求: {pending_tool_id}")

        # 1. 查出 workflow_id
        try:
            from src.data.repositories import ToolRepository

            tool = ToolRepository().get_by_id(pending_tool_id)
            if not tool:
                self.logger.error(f"找不到工具: {pending_tool_id}")
                return
            workflow_id = tool.workflow_id
            if not workflow_id:
                self.logger.error(f"工具 {pending_tool_id} 没有 workflow_id，无法启动试用")
                return
        except Exception as e:
            self.logger.error(f"查询工具失败: {e}", exc_info=True)
            return

        # 2. 确保 AgentUIBridge 就绪
        if not self._ensure_agent_bridge():
            self.logger.error("AgentUIBridge 不可用，无法启动试用 Agent")
            return

        # 3. 保存当前会话上下文
        self._current_agent_workflow_id = workflow_id
        self._current_agent_type = AgentType.TRIAL

        # 4. 切页，预加载试用历史（无历史时清空旧消息）
        try:
            messages = self.agent_ui_bridge.get_trial_messages(workflow_id)
        except Exception as e:
            self.logger.error(f"查询 trial 历史消息失败: {e}", exc_info=True)
            messages = []

        self.main_content.switch_page(INTENT_CONFIRMATION)

        if messages:
            display_messages = messages[:-1] if messages[-1].get("role") == "assistant" else messages
            self.intent_confirmation_page.preload_trial_history(display_messages or [])
            self.logger.info(f"预加载 trial 历史: workflow_id={workflow_id}, count={len(display_messages or [])}")
        else:
            self.intent_confirmation_page.preload_trial_history([])

        self.logger.info(f"启动 trial Agent: workflow_id={workflow_id}")
        user_input = None if messages else "开始试用"
        self.agent_ui_bridge.start_agent(AgentType.TRIAL, user_input, workflow_id)

    def _on_tool_delete_request(self, pending_tool_id: str) -> None:
        """
        处理工具删除请求（PendingToolsUI 信号）

        通过 WebSocket 转发到后端
        """
        self.logger.info(f"收到工具删除请求: {pending_tool_id}")
        # TODO: 转发到 WebSocket 或直接调用后端 API

    def _on_tool_update_request(self, pending_tool_id: str, name: str, description: str) -> None:
        """
        处理工具更新请求（PendingToolsUI 信号）

        通过 WebSocket 转发到后端
        """
        self.logger.info(f"收到工具更新请求: {pending_tool_id}, {name}")
        # TODO: 转发到 WebSocket 或直接调用后端 API

    def _on_retry_requested(self, workflow_id: str, failed_stage: str) -> None:
        """处理失败记录重试请求"""
        self.logger.info(f"收到重试请求: workflow={workflow_id}, stage={failed_stage}")
        if not self._ensure_agent_bridge():
            self.logger.warning("Orchestrator 未就绪，无法重试")
            return
        if self.agent_ui_bridge:
            if failed_stage == AgentType.PM:
                # 加载上次 PM 会话历史，切换到意图确认页，禁用输入（PM 正在重新跑）
                history = self.agent_ui_bridge.get_pm_messages(workflow_id)
                self.intent_confirmation_page.load_trial_history(history, workflow_id)
                self.main_content.switch_page(INTENT_CONFIRMATION)
            self.agent_ui_bridge.retry_teaching(workflow_id)
        else:
            self.logger.warning("AgentUIBridge 不可用，无法重试")

    def _on_retry_failed(self, workflow_id: str, error: str) -> None:
        """重试失败：弹 toast + 如果当前在意图确认页则跳回欢迎页"""
        self.logger.error(f"重试失败: workflow={workflow_id}, error={error}")
        self._show_toast(
            f"重试失败：{self._truncate_error(error)}", auto_dismiss_ms=15000, toast_type="error"
        )
        self._switch_to_welcome_page()

    def _on_failure_updated(
        self, workflow_id: str, failed_stage: str, event_type: str, is_new: bool
    ) -> None:
        """失败记录状态变化：防抖刷新技能列表页的失败 tab"""
        if not hasattr(self, "_failure_refresh_timer"):
            self._failure_refresh_timer = QTimer(self)
            self._failure_refresh_timer.setSingleShot(True)
            self._failure_refresh_timer.timeout.connect(self._do_refresh_failures)
        self._failure_refresh_timer.start(200)

    def _do_refresh_failures(self):
        """实际刷新失败列表（由 debounce timer 触发）"""
        skills_page = self.main_content.get_page(SKILLS)
        if skills_page and hasattr(skills_page, "_load_failures"):
            skills_page._load_failures()

    def closeEvent(self, event) -> None:
        """
        窗口关闭事件处理

        确保资源正确释放，避免 DuckDB WAL 文件损坏
        """
        self.logger.info("正在关闭应用程序...")

        # 停止正在进行的录制
        if self.browser_recorder is not None:
            try:
                self.logger.info("停止正在进行的录制...")
                self.browser_recorder.stop_recording()
            except Exception as e:
                self.logger.error(f"停止录制失败: {e}")

        # ⭐ 优雅关闭 WebSocket 服务器
        if self.ws_manager is not None:
            try:
                self.logger.info("停止 WebSocket 服务器...")
                self.ws_manager.stop()
                self.logger.info("WebSocket 服务器已停止")
            except Exception as e:
                self.logger.error(f"停止 WebSocket 服务器失败: {e}")

        # 关闭 DuckDB 连接
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
