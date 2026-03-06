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
import time

from PyQt6.QtCore import Qt, QSize, pyqtSignal
from PyQt6.QtGui import QAction, QIcon, QPixmap, QPainter
from PyQt6.QtWidgets import (
    QMainWindow,
    QWidget,
    QHBoxLayout,
    QMessageBox,
    QPushButton,
)

from src.business.ai.preprocessing import CompressionLevel
from src.business.ai.workflow_orchestrator import WorkflowOrchestrator
from src.recording.browser_recorder import BrowserRecorder
from src.business.intent.intent_analyzer import IntentAnalyzer
from src.business.intent.intent_repository import IntentRepository
from src.business.intent.intent_confirmer import IntentConfirmer
from src.communication.websocket_manager import WebSocketServerManager
from src.ui.widgets.chat_widget import ChatWidget
from src.ui.widgets.main_content_widget import MainContentWidget
from src.ui.widgets.recording_widget import RecordingWidget
from src.ui.widgets.settings_page import SettingsPage
from src.ui.widgets.sidebar_widget import SidebarWidget
from src.ui.widgets.tools_list_page import ToolsListPage
from src.ui.resources.icons.sidebar_icons import (
    FILE_ICON,
    HELP_ICON,
    SIDEBAR_CLOSE_ICON,
    SIDEBAR_OPEN_ICON,
)
from src.utils.logger import get_logger


class OrchestratorInitStatus(Enum):
    """WorkflowOrchestrator 初始化状态枚举"""
    NOT_STARTED = "not_started"
    INITIALIZING = "initializing"
    READY = "ready"
    FAILED = "failed"


class MainWindow(QMainWindow):
    """Mexemplar 主窗口"""

    # 类常量
    _POLL_INTERVAL = 0.1  # 轮询间隔（秒）
    _DEFAULT_INIT_TIMEOUT = 5.0  # 默认初始化超时（秒）

    # 定义信号（线程安全的 UI 通信）
    recording_start_success = pyqtSignal()
    recording_start_failed = pyqtSignal(str)  # 参数：错误消息
    recording_error = pyqtSignal(str)  # 参数：错误详情
    workflow_error = pyqtSignal(str, str)  # 参数：错误消息，错误类型

    def __init__(self) -> None:
        """初始化主窗口"""
        self.logger = get_logger(__name__)
        self.logger.info("[MainWindow] __init__ 开始")
        super().__init__()
        self.logger.info("[MainWindow] super().__init__() 完成")

        self.sidebar = None  # 侧边栏
        self.main_content = None  # 主内容区
        self.browser_recorder = None  # 浏览器录制器
        self.workflow_orchestrator = None  # 工作流编排器（懒加载）

        # 意图确认相关组件
        self.intent_confirmer = None  # 意图确认器
        self.ws_manager = None  # WebSocket 服务器管理器

        # WorkflowOrchestrator 异步初始化状态
        self._orchestrator_init_lock = threading.Lock()
        self._orchestrator_init_condition = threading.Condition(
            self._orchestrator_init_lock
        )
        self._orchestrator_init_status = OrchestratorInitStatus.NOT_STARTED
        self._orchestrator_init_error = None  # 初始化错误信息
        self._orchestrator_warmup_thread = None  # 预热线程引用

        self._sidebar_visible = True  # 跟踪侧边栏状态（统一使用 _ 前缀）
        self.menubar = None  # 菜单栏引用

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
        from PyQt6.QtCore import QTimer
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

    def _create_svg_icon(
        self,
        svg_string: str,
        color: str = "#666666",
        size: int = 20
    ) -> QIcon:
        """从 SVG 字符串创建 QIcon

        Args:
            svg_string: SVG 字符串
            color: 图标颜色（十六进制）
            size: 图标尺寸

        Returns:
            QIcon 对象
        """
        try:
            from PyQt6.QtSvg import QSvgRenderer

            # 替换 currentColor 为指定颜色
            svg_with_color = svg_string.replace('fill="currentColor"', f'fill="{color}"')

            # 创建 SVG 渲染器
            renderer = QSvgRenderer(svg_with_color.encode())

            # 创建 pixmap
            pixmap = QPixmap(size, size)
            pixmap.fill(Qt.GlobalColor.transparent)

            # 渲染 SVG
            painter = QPainter(pixmap)
            renderer.render(painter)
            painter.end()

            return QIcon(pixmap)
        except ImportError:
            # 如果没有 QSvgRenderer，使用备用方案（简单箭头）
            self.logger.warning("QSvgRenderer 不可用，使用备用图标方案")
            # 创建一个简单的 pixmap 作为备用
            pixmap = QPixmap(size, size)
            pixmap.fill(Qt.GlobalColor.transparent)
            return QIcon(pixmap)

    def init_ui(self) -> None:
        """初始化用户界面"""
        # 设置窗口属性
        self.setWindowTitle("Mexemplar")
        self.setMinimumSize(1000, 700)
        self.resize(1200, 800)  # 显式设置初始大小
        self.logger.info(f"窗口几何信息: x={self.x()}, y={self.y()}, width={self.width()}, height={self.height()}")

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
        self.sidebar_visible = True
        main_layout.addWidget(self.sidebar)

        # ============ 创建主内容区 ============
        self.main_content = MainContentWidget()
        main_layout.addWidget(self.main_content, 1)  # stretch=1

        # ============ 添加页面到主内容区 ============
        # AI 对话页面
        chat_page = ChatWidget()
        self.main_content.add_page("chat", chat_page)

        # 录制页面
        self.recording_page = RecordingWidget()
        self.recording_page.recording_started.connect(self._on_recording_started)
        self.recording_page.recording_stopped.connect(self._on_recording_stopped)
        self.main_content.add_page("recording", self.recording_page)

        # 工具列表页面
        tools_page = ToolsListPage()
        self.main_content.add_page("tools", tools_page)

        # 意图确认页面
        from src.ui.intent_confirmation_ui import IntentConfirmationUI
        self.intent_confirmation_page = IntentConfirmationUI()
        self.main_content.add_page("intent_confirmation", self.intent_confirmation_page)

        # 待试用工具列表页面
        from src.ui.tools_management_ui import ToolsManagementUI
        self.pending_tools_page = ToolsManagementUI()
        self.main_content.add_page("pending_tools", self.pending_tools_page)

        # 设置页面
        settings_page = SettingsPage()
        self.main_content.add_page("settings", settings_page)

        # ============ 连接信号和槽 ============
        # 侧边栏导航 -> 主内容区页面切换
        self.sidebar.navigation_requested.connect(self.main_content.switch_page)

        # ⭐ 连接 IntentConfirmationUI 的信号到 MainWindow 处理
        if hasattr(self, 'intent_confirmation_page'):
            self.intent_confirmation_page.analyze_intent_request.connect(
                self._on_intent_analyze_request
            )
            self.intent_confirmation_page.confirm_intent_request.connect(
                self._on_intent_confirm_request
            )
            # Agent 模式信号：恢复 Agent
            self.intent_confirmation_page.agent_resume_request.connect(
                self._on_agent_resume_request
            )

        # ⭐ 连接 ToolsManagementUI 的信号到 MainWindow 处理
        if hasattr(self, 'pending_tools_page'):
            self.pending_tools_page.trial_start_request.connect(
                self._on_trial_start_request
            )
            self.pending_tools_page.tool_delete_request.connect(
                self._on_tool_delete_request
            )
            self.pending_tools_page.tool_update_request.connect(
                self._on_tool_update_request
            )

        # 侧边栏新建对话 -> AI 对话页面新建对话
        self.sidebar.new_chat_requested.connect(self._on_new_chat_requested)

        # ⭐ 连接录制错误信号（线程安全的错误处理）
        self.recording_start_success.connect(self._on_recording_start_success)
        self.recording_start_failed.connect(self._on_recording_start_failed)
        self.recording_error.connect(self._on_recording_error)
        self.workflow_error.connect(self._on_workflow_error)

        # ⭐ 连接工作流处理失败事件（用于显示压缩模型错误等）
        from src.utils.events import workflow_processing_failed
        workflow_processing_failed.connect(self._on_workflow_processing_failed)

        # 默认显示 AI 对话页面
        self.main_content.switch_page("chat")

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
            self._create_svg_icon(SIDEBAR_OPEN_ICON),
            "折叠侧边栏"
        )
        self.toggle_sidebar_btn.clicked.connect(self._toggle_sidebar)
        left_layout.addWidget(self.toggle_sidebar_btn)

        # ============ 文件按钮 ============
        file_menu = self.menubar.addMenu("")  # 空标题，纯按钮

        exit_action = QAction("退出(&X)", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        btn_file = create_toolbar_btn(
            self._create_svg_icon(FILE_ICON),
            "文件"
        )
        btn_file.setMenu(file_menu)
        left_layout.addWidget(btn_file)

        # ============ 帮助按钮 ============
        help_menu = self.menubar.addMenu("")  # 空标题，纯按钮

        about_action = QAction("关于(&A)", self)
        about_action.triggered.connect(self._show_about_dialog)
        help_menu.addAction(about_action)

        btn_help = create_toolbar_btn(
            self._create_svg_icon(HELP_ICON),
            "帮助"
        )
        btn_help.setMenu(help_menu)
        left_layout.addWidget(btn_help)

        # ============ 将工具区放入菜单栏左上角 ============
        self.menubar.setCornerWidget(left_tools, Qt.Corner.TopLeftCorner)

    def _warmup_orchestrator_async(self) -> None:
        """
        异步预热 WorkflowOrchestrator（后台线程）

        在应用启动时自动调用，在后台准备资源，避免首次使用时卡顿
        """
        def warmup() -> None:
            """后台预热任务"""
            try:
                with self._orchestrator_init_condition:
                    # 双重检查：避免重复初始化
                    if self._orchestrator_init_status == OrchestratorInitStatus.READY:
                        self.logger.info("WorkflowOrchestrator already ready, skipping warmup")
                        return

                    self._orchestrator_init_status = OrchestratorInitStatus.INITIALIZING
                    self.logger.info("Warming up WorkflowOrchestrator in background...")

                # 在锁外执行初始化（避免阻塞其他检查）
                orchestrator = self._create_orchestrator()

                with self._orchestrator_init_condition:
                    self.workflow_orchestrator = orchestrator
                    self._orchestrator_init_status = OrchestratorInitStatus.READY
                    self.logger.info("WorkflowOrchestrator warmup completed")
                    # 通知所有等待的线程
                    self._orchestrator_init_condition.notify_all()

            except Exception as e:
                with self._orchestrator_init_condition:
                    self._orchestrator_init_status = OrchestratorInitStatus.FAILED
                    self._orchestrator_init_error = str(e)
                    # 通知所有等待的线程（即使失败了也要通知）
                    self._orchestrator_init_condition.notify_all()
                self.logger.error(f"WorkflowOrchestrator warmup failed: {e}", exc_info=True)

        # 启动后台线程（非 daemon，确保初始化完成）
        self._orchestrator_warmup_thread = threading.Thread(
            target=warmup,
            daemon=False,  # 修复：使用非 daemon 线程，避免初始化被中断
            name="OrchestratorWarmup"
        )
        self._orchestrator_warmup_thread.start()
        self.logger.info("WorkflowOrchestrator warmup thread started")

    def _init_intent_confirmer(self) -> None:
        """
        初始化意图确认组件

        使用 WebSocketServerManager 自动启动和管理 WebSocket 服务器
        """
        try:
            # 创建 LLM 客户端
            from src.business.ai.llm_client import LangChainLLMClient
            from src.data.unified_config import get_unified_config

            config = get_unified_config()
            provider = config.get_ai_provider()  # 获取提供商

            llm_client = LangChainLLMClient(
                provider=provider,
                model=config.get_ai_model(),
                api_key=config.get_ai_api_key(),
                base_url=config.get_ai_base_url(),
                temperature=0.7,
            )

            # 创建意图分析器
            analyzer = IntentAnalyzer(llm_client=llm_client)

            # 创建意图仓库（需要 DatabaseManager）
            from src.data.database import DatabaseManager
            db_manager = DatabaseManager()
            repository = IntentRepository(db_manager=db_manager)

            # 创建 WebSocket 服务器管理器（不自动启动，避免阻塞）
            self.ws_manager = WebSocketServerManager(
                host="127.0.0.1",
                port=8766,
                auto_start=False,  # 改为 False，避免阻塞
                startup_timeout=5.0,
            )

            # 在后台启动服务器
            import threading
            def start_ws_server():
                try:
                    self.ws_manager.start()
                except Exception as e:
                    self.logger.error(f"WebSocket 服务器启动失败: {e}", exc_info=True)

            ws_thread = threading.Thread(target=start_ws_server, daemon=True)
            ws_thread.start()
            self.logger.info("WebSocket 服务器启动线程已创建")

            # 注册错误回调
            def on_ws_error(manager, error_msg):
                self.logger.error(f"WebSocket 服务器错误: {error_msg}")
                QMessageBox.warning(
                    self,
                    "WebSocket 服务器启动失败",
                    f"WebSocket 服务器启动失败：\n\n{error_msg}\n\n"
                    f"意图确认功能将不可用。"
                )

            self.ws_manager.on_error(on_ws_error)

            # ❌ 不再等待服务器启动完成，避免阻塞
            # WebSocket 服务器在后台线程中启动，稍后可用

            # 获取 WebSocket 处理器（可能暂时为 None）
            ws_handler = self.ws_manager.get_handler()
            if not ws_handler:
                self.logger.warning("WebSocket 处理器尚未就绪，将等待服务器启动")
                # 不 return，继续初始化其他组件

            # 创建意图确认器
            self.intent_confirmer = IntentConfirmer(
                analyzer=analyzer,
                repository=repository,
                ws_handler=ws_handler,
            )

            # 注册意图分析完成的消息处理器
            from src.communication.message_types import MessageType
            ws_handler.register_handler(
                MessageType.INTENT_ANALYZED,
                self._on_intent_analyzed
            )

            self.logger.info("✅ 意图确认组件初始化成功")

        except Exception as e:
            self.logger.error(f"初始化意图确认组件失败: {e}", exc_info=True)
            # 不抛出异常，允许主窗口继续运行

    def _delayed_init_intent_confirmer(self) -> None:
        """
        延迟初始化意图确认组件（在窗口显示后执行）

        使用后台线程启动 WebSocket 服务器，避免阻塞 UI
        """
        import threading

        def init_in_background():
            """在后台线程中初始化"""
            try:
                self.logger.info("[延迟初始化] 开始在后台线程中初始化意图确认组件")

                # 创建 LLM 客户端
                from src.business.ai.llm_client import LangChainLLMClient
                from src.data.unified_config import get_unified_config

                config = get_unified_config()
                provider = config.get_ai_provider()  # 获取提供商

                llm_client = LangChainLLMClient(
                    provider=provider,
                    model=config.get_ai_model(),
                    api_key=config.get_ai_api_key(),
                    base_url=config.get_ai_base_url(),
                    temperature=0.7,
                )

                # 创建意图分析器
                analyzer = IntentAnalyzer(llm_client=llm_client)

                # 创建意图仓库（需要 DatabaseManager）
                from src.data.database import DatabaseManager
                db_manager = DatabaseManager()
                repository = IntentRepository(db_manager=db_manager)

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

                # 创建意图确认器
                self.intent_confirmer = IntentConfirmer(
                    analyzer=analyzer,
                    repository=repository,
                    ws_handler=ws_handler,
                )

                # 注册意图分析完成的消息处理器
                from src.communication.message_types import MessageType
                ws_handler.register_handler(
                    MessageType.INTENT_ANALYZED,
                    self._on_intent_analyzed
                )

                self.logger.info("✅ [延迟初始化] 意图确认组件初始化成功")

            except Exception as e:
                self.logger.error(f"[延迟初始化] 初始化意图确认组件失败: {e}", exc_info=True)

        thread = threading.Thread(target=init_in_background, daemon=True)
        thread.start()
        self.logger.info("[延迟初始化] 后台初始化线程已启动")

    def _on_intent_analyzed(self, msg) -> dict:
        """处理意图分析完成的消息"""
        try:
            data = msg.data
            intent_id = data.get("intent_id")
            recording_id = data.get("recording_id")

            self.logger.info(f"收到意图分析完成消息: {intent_id}, 录制ID: {recording_id}")

            # 切换到意图确认页面
            self.main_content.switch_page("intent_confirmation")

            return {"status": "success"}

        except Exception as e:
            self.logger.error(f"处理意图分析消息失败: {e}", exc_info=True)
            return {"status": "error", "message": str(e)}

    def _create_orchestrator(self) -> WorkflowOrchestrator:
        """
        创建 WorkflowOrchestrator 实例（内部方法）

        Returns:
            WorkflowOrchestrator: 创建的实例

        Raises:
            Exception: 初始化失败时抛出异常
        """
        orchestrator = WorkflowOrchestrator(
            compression_level=CompressionLevel.MODERATE,
            auto_process=False,  # 手动启动监听
            use_agent=True,  # 使用 Agent 模式
            use_persistence=False,
        )
        # 启动监听录制完成事件
        orchestrator.start_listening()

        # 连接 AgentUIBridge 信号
        if orchestrator.agent_bridge:
            orchestrator.agent_bridge.interrupt_requested.connect(
                self._on_agent_interrupt
            )
            orchestrator.agent_bridge.session_completed.connect(
                self._on_agent_session_completed
            )
            orchestrator.agent_bridge.error_occurred.connect(
                self._on_agent_error
            )
            self.logger.info("AgentUIBridge 信号已连接")

        return orchestrator

    def _on_agent_interrupt(self, thread_id: str, interrupt_data: dict) -> None:
        """
        处理 Agent interrupt（用户交互请求）

        Args:
            thread_id: Agent 会话 ID
            interrupt_data: interrupt 数据（格式：{"interrupts": [{"value": {...}, "id": ...}]}）
        """
        self.logger.info(f"Agent interrupt 收到: {interrupt_data}")

        # 检查是否有 AI 回复（用于反馈对话）
        ai_response = interrupt_data.get("ai_response", "")

        # 从 interrupts 列表中提取实际数据
        interrupts = interrupt_data.get("interrupts", [])
        if not interrupts:
            self.logger.warning("收到空的 interrupts 数据")
            return

        # 获取第一个 interrupt 的 value（实际数据）
        actual_data = interrupts[0].get("value", {})
        interrupt_type = actual_data.get("type")
        self.logger.info(f"Agent interrupt 类型: {interrupt_type}")

        if interrupt_type == "intent_confirmation":
            # 保存当前 thread_id 用于后续恢复
            self._current_agent_thread_id = thread_id

            # 传递完整的 actual_data（包含所有确认问题）
            intent_data = actual_data
            message = actual_data.get("message", "请确认意图")

            # 如果有 AI 回复，添加到 intent_data 中
            if ai_response:
                intent_data["ai_response"] = ai_response

            # 切换到意图确认页面并显示内容
            self._show_intent_confirmation_from_agent(intent_data, message, thread_id)

    def _on_agent_session_completed(self, thread_id: str, tool_draft: object = None) -> None:
        """
        处理 Agent 会话完成

        Args:
            thread_id: Agent 会话 ID
            tool_draft: 生成的工具草稿（可选）
        """
        self.logger.info(f"Agent 会话完成: {thread_id}")

        if tool_draft:
            self.logger.info(f"工具已生成: {getattr(tool_draft, 'tool_name', 'Unknown')}")

            # 在意图确认页面显示成功消息
            intent_page = self.main_content.get_page("intent_confirmation")
            if intent_page and hasattr(intent_page, 'show_success_message'):
                intent_page.show_success_message(tool_draft)

            # 延迟后自动切换到待试用工具页面
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(1500, self._switch_to_pending_tools)

    def _on_agent_error(self, thread_id: str, error_message: str) -> None:
        """处理 Agent 错误"""
        self.logger.error(f"Agent 错误: {thread_id} - {error_message}")

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
        # 保存当前 thread_id 用于后续恢复
        self._current_agent_thread_id = thread_id

        # 切换到意图确认页面
        self.main_content.switch_page("intent_confirmation")

        # 获取意图确认页面并更新内容
        intent_page = self.main_content.get_page("intent_confirmation")
        if intent_page and hasattr(intent_page, 'load_intent_from_agent'):
            intent_page.load_intent_from_agent(intent_data, message, thread_id)

        self.logger.info("已切换到意图确认页面")

    def _on_agent_resume_request(self, thread_id: str, resume_data: dict) -> None:
        """
        处理 Agent 恢复请求（来自 IntentConfirmationUI）

        Args:
            thread_id: Agent 会话 ID
            resume_data: 恢复数据（包含用户的确认回答）
        """
        self.logger.info(f"收到 Agent 恢复请求: thread_id={thread_id}")

        # 获取 AgentUIBridge 并恢复 Agent
        if self.workflow_orchestrator and self.workflow_orchestrator.agent_bridge:
            try:
                self.workflow_orchestrator.agent_bridge.resume(thread_id, resume_data)
                self.logger.info(f"已恢复 Agent: {thread_id}")
            except Exception as e:
                self.logger.error(f"恢复 Agent 失败: {e}", exc_info=True)
        else:
            self.logger.warning("没有可用的 AgentUIBridge")

    def _switch_to_pending_tools(self) -> None:
        """切换到待试用工具页面"""
        self.logger.info("自动切换到待试用工具页面")
        self.main_content.switch_page("pending_tools")

        # 刷新工具列表
        pending_tools_page = self.main_content.get_page("pending_tools")
        if pending_tools_page and hasattr(pending_tools_page, 'load_tools'):
            pending_tools_page.load_tools()

    def _toggle_sidebar(self) -> None:
        """切换侧边栏状态"""
        if self._sidebar_visible:
            # 折叠侧边栏
            self.sidebar.hide()
            self.toggle_sidebar_btn.setIcon(self._create_svg_icon(SIDEBAR_CLOSE_ICON))
            self.toggle_sidebar_btn.setToolTip("展开侧边栏")
            self._sidebar_visible = False
            self.logger.info("Sidebar collapsed")
        else:
            # 展开侧边栏
            self.sidebar.show()
            self.toggle_sidebar_btn.setIcon(self._create_svg_icon(SIDEBAR_OPEN_ICON))
            self.toggle_sidebar_btn.setToolTip("折叠侧边栏")
            self._sidebar_visible = True
            self.logger.info("Sidebar expanded")

    def _on_new_chat_requested(self) -> None:
        """新建对话请求"""
        self.logger.info("新建对话")
        chat_page = self.main_content.get_page("chat")
        if chat_page:
            chat_page.on_new_chat()

    def _on_record_clicked(self) -> None:
        """录制按钮点击 - 切换到录制页面"""
        self.logger.info("用户点击录制按钮")
        self.main_content.switch_page("recording")

    def _on_chat_clicked(self) -> None:
        """AI 助手按钮点击 - 切换到对话页面"""
        self.logger.info("用户点击 AI 助手按钮")
        self.main_content.switch_page("chat")

    def _on_execute_clicked(self) -> None:
        """执行按钮点击事件"""
        QMessageBox.information(
            self,
            "执行工具",
            "执行功能即将推出！\n\n请使用命令行模式：\nuv run python -m src.main interactive",
        )

    def _on_tools_clicked(self) -> None:
        """工具列表按钮点击事件"""
        QMessageBox.information(
            self,
            "工具列表",
            "工具列表即将推出！\n\n请使用命令行模式：\nuv run python -m src.main interactive",
        )

    def _on_settings_clicked(self) -> None:
        """设置按钮点击事件"""
        QMessageBox.information(
            self,
            "设置",
            "设置功能即将推出！\n\n请使用命令行模式：\nuv run python -m src.main interactive",
        )

    def go_back_to_home(self) -> None:
        """返回主页面"""
        self.logger.info("用户返回主页面")
        self.main_content.switch_page("chat")

    def _on_recording_started(self, mode: str, url: str) -> None:
        """开始录制处理函数"""
        self.logger.info(f"开始录制: mode={mode}, url={url}")

        if mode == "browser":
            # 在后台线程中启动浏览器录制
            self._start_browser_recording(url)
        else:
            self.logger.warning(f"暂不支持 {mode} 录制模式")
            QMessageBox.warning(
                self,
                "不支持的模式",
                f"暂不支持 {mode} 录制模式\n\n当前仅支持浏览器录制。"
            )
            # 重置录制界面状态
            self.recording_page.reset()

    def _ensure_workflow_orchestrator(self, timeout: float = _DEFAULT_INIT_TIMEOUT) -> bool:
        """
        智能确保 WorkflowOrchestrator 已初始化（懒加载 + 预热支持）

        支持三种状态处理：
        1. 已完成 → 直接使用
        2. 正在初始化 → 等待完成（最多 timeout 秒）
        3. 未开始/失败 → 立即创建

        Args:
            timeout: 等待预热完成的最大时间（秒），默认 5 秒

        Returns:
            bool: 是否成功获取到可用的 WorkflowOrchestrator
        """
        with self._orchestrator_init_condition:
            # 情况1: 已经准备好了
            if self._orchestrator_init_status == OrchestratorInitStatus.READY and self.workflow_orchestrator:
                self.logger.debug("WorkflowOrchestrator ready (warmup completed)")
                return True

            # 情况2: 正在初始化中 → 等待完成
            if self._orchestrator_init_status == OrchestratorInitStatus.INITIALIZING:
                self.logger.info(f"WorkflowOrchestrator is warming up, waiting up to {timeout} seconds...")
                # 使用 Condition.wait() 代替轮询，更高效
                waited = self._orchestrator_init_condition.wait(timeout=timeout)

                if self._orchestrator_init_status == OrchestratorInitStatus.READY:
                    self.logger.info("WorkflowOrchestrator warmup completed")
                    return True
                else:
                    # 超时或失败
                    if self._orchestrator_init_status == OrchestratorInitStatus.FAILED:
                        self.logger.warning(f"Warmup failed: {self._orchestrator_init_error}, recreating...")
                    else:
                        self.logger.warning(f"Warmup timeout ({timeout}s), creating immediately...")
                    # 继续下面的立即创建逻辑

            # 情况3: 未开始或失败 → 立即创建
            if self._orchestrator_init_status == OrchestratorInitStatus.NOT_STARTED:
                self.logger.info("No warmup initiated, creating immediately...")
            elif self._orchestrator_init_status == OrchestratorInitStatus.FAILED:
                self.logger.warning(f"Previous warmup failed: {self._orchestrator_init_error}, recreating...")

            # 双重检查：避免重复创建
            if self.workflow_orchestrator is not None:
                return True

            # 立即创建（懒加载兜底）
            self._orchestrator_init_status = OrchestratorInitStatus.INITIALIZING

        try:
            self.logger.info("Creating WorkflowOrchestrator immediately...")
            orchestrator = self._create_orchestrator()

            with self._orchestrator_init_condition:
                self.workflow_orchestrator = orchestrator
                self._orchestrator_init_status = OrchestratorInitStatus.READY
                self.logger.info("WorkflowOrchestrator created and ready")
                # 通知可能等待的线程
                self._orchestrator_init_condition.notify_all()

            return True

        except Exception as e:
            with self._orchestrator_init_condition:
                self._orchestrator_init_status = OrchestratorInitStatus.FAILED
                self._orchestrator_init_error = str(e)
                self.workflow_orchestrator = None
                self._orchestrator_init_condition.notify_all()

            self.logger.error(f"WorkflowOrchestrator initialization failed: {e}", exc_info=True)
            # 使用信号而非直接调用 QMessageBox（线程安全）
            self.recording_error.emit(
                f"工作流编排器初始化失败：\n{str(e)}\n\n录制功能仍可使用，但不会自动生成工作流。"
            )
            return False

    def _start_browser_recording(self, url: str) -> None:
        """
        ⭐ 启动浏览器录制（在后台线程中）

        优化：WorkflowOrchestrator 初始化也移到后台线程，避免阻塞 UI
        """
        def start_recording():
            """在后台线程中执行录制启动"""
            browser_recorder = None
            try:
                # ⭐ 优化1：在后台线程中确保 WorkflowOrchestrator 已初始化
                self.logger.info("确保 WorkflowOrchestrator 已就绪...")
                if not self._ensure_workflow_orchestrator(timeout=5.0):
                    self.logger.error("WorkflowOrchestrator 不可用，但录制仍可继续")
                    # 不返回，继续录制（AI 处理功能不可用）

                self.logger.info("正在启动浏览器录制器...")

                # ⭐ 优化2：捕获所有初始化错误，确保不会卡死
                try:
                    browser_recorder = BrowserRecorder()
                except Exception as init_error:
                    error_msg = f"浏览器录制器初始化失败：\n{str(init_error)}\n\n可能的原因：\n" \
                                f"1. DuckDB 数据库文件被其他程序占用（如 PyCharm）\n" \
                                f"2. 数据库文件损坏\n" \
                                f"3. 磁盘空间不足\n\n" \
                                f"解决方案：\n" \
                                f"1. 关闭 PyCharm 或其他可能占用数据库的程序\n" \
                                f"2. 检查 data/mexemplar.duckdb 文件是否存在\n" \
                                f"3. 查看日志获取详细信息"

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
                import threading
                from src.utils.events import emit, RecordingEventData

                def stop_recording():
                    try:
                        result = self.browser_recorder.stop_recording()
                        recording_id = result.get('recording_id')
                        action_count = result.get('action_count', 0)

                        self.logger.info(f"录制已停止: {recording_id}")
                        self.logger.info(f"捕获了 {action_count} 个操作")

                        # 切换到意图确认页面（显示"正在分析..."）
                        # 注意：实际的意图内容会在 Agent interrupt 后通过 _on_agent_interrupt 更新
                        self.main_content.switch_page("intent_confirmation")

                        # 发射录制完成事件，触发 WorkflowOrchestrator 处理
                        # WorkflowOrchestrator 会启动 Agent，Agent interrupt 后更新 UI
                        emit(
                            'recording_completed',
                            event_data=RecordingEventData(
                                session_id=recording_id,
                                recording_mode='browser',
                                start_time=result.get('start_time'),
                                end_time=result.get('end_time'),
                                action_count=action_count,
                            )
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
                <li>📹 浏览器/桌面操作录制</li>
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
        QMessageBox.critical(
            self,
            "录制失败",
            error_message
        )

    def _on_recording_error(self, error_message: str) -> None:
        """录制错误的槽函数（主线程中执行）"""
        self.logger.error(f"❌ 录制错误: {error_message}")
        # ⭐ 在主线程中显示错误消息（线程安全）
        QMessageBox.critical(
            self,
            "录制错误",
            error_message
        )

    def _on_workflow_error(self, error_message: str, error_type: str) -> None:
        """工作流错误的槽函数（主线程中执行）"""
        self.logger.warning(f"⚠️ 工作流错误 ({error_type}): {error_message}")

        # 根据错误类型决定提示方式
        if error_type == "compression_model_fallback":
            # 压缩模型降级：显示警告提示（不阻断流程）
            QMessageBox.warning(
                self,
                "压缩模型警告",
                f"{error_message}\n\n已自动回退到规则引擎，工具生成将继续进行。"
            )
        else:
            # 其他错误：显示普通提示
            QMessageBox.warning(
                self,
                "工作流提示",
                error_message
            )

    def _on_workflow_processing_failed(self, sender, **kwargs) -> None:
        """处理工作流处理失败事件（从 blinker 信号）"""
        error = kwargs.get("error", "未知错误")
        error_type = kwargs.get("error_type", "unknown")

        self.logger.info(f"收到工作流处理失败事件: {error}, type={error_type}")

        # 如果是警告类型（如压缩模型降级），不阻断流程
        if error and error.startswith("[警告]"):
            # 通过信号发送到主线程显示提示
            self.workflow_error.emit(error[5:].strip(), error_type)  # 去掉 "[警告]" 前缀
        else:
            # 真正的错误，显示错误提示
            self.workflow_error.emit(error, error_type)

    # ===== UI 组件信号处理（替代 WebSocket 客户端）=====

    def _on_intent_analyze_request(self, intent_id: str, user_message: str) -> None:
        """
        处理意图分析请求（IntentConfirmationUI 信号）

        将用户消息传递给 Agent 进行处理
        """
        self.logger.info(f"收到意图分析请求: {intent_id}, 消息: {user_message[:50]}...")

        # Agent 模式：将用户消息作为 feedback 传递给 Agent
        if hasattr(self, '_current_agent_thread_id') and self._current_agent_thread_id:
            # 构建 feedback 数据
            resume_data = {
                "action": "feedback",
                "feedback": user_message
            }

            # 恢复 Agent，传递用户反馈
            if self.workflow_orchestrator and self.workflow_orchestrator.agent_bridge:
                try:
                    self.workflow_orchestrator.agent_bridge.resume(
                        self._current_agent_thread_id,
                        resume_data
                    )
                    self.logger.info(f"已传递用户反馈给 Agent: {self._current_agent_thread_id}")

                    # 更新 UI 状态
                    intent_page = self.main_content.get_page("intent_confirmation")
                    if intent_page and hasattr(intent_page, 'status_label'):
                        intent_page.status_label.setText("正在处理您的反馈...")

                except Exception as e:
                    self.logger.error(f"传递用户反馈失败: {e}", exc_info=True)
            else:
                self.logger.warning("AgentUIBridge 不可用")
        else:
            self.logger.warning("没有活跃的 Agent 会话")

    def _on_intent_confirm_request(self, intent_id: str) -> None:
        """
        处理意图确认请求（IntentConfirmationUI 信号）

        通过 WebSocket 转发到后端
        """
        self.logger.info(f"收到意图确认请求: {intent_id}")
        # TODO: 转发到 WebSocket 或直接调用后端 API

    def _on_trial_start_request(self, pending_tool_id: str) -> None:
        """
        处理工具试用请求（PendingToolsUI 信号）

        通过 WebSocket 转发到后端
        """
        self.logger.info(f"收到工具试用请求: {pending_tool_id}")
        # TODO: 转发到 WebSocket 或直接调用后端 API

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
