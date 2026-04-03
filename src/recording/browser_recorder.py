"""
浏览器录制器模块（Native Messaging集成版本）

实现通过Native Messaging连接浏览器插件和Mexemplar，使用Playwright启动浏览器并自动加载插件。

【架构约束】本模块属于驱动层，只能被上层调用，不能调用业务层。
如需通知业务层处理录制完成，必须使用事件系统（见 stop_recording 方法）。
详见 CLAUDE.md 核心约束 #2 和 #3
"""

import logging
import json
import time
import os
import asyncio  # ⭐ 新增：异步支持
from contextlib import contextmanager  # ⭐ 新增：上下文管理器支持
from typing import Optional, List, Dict, Any, Callable
from dataclasses import dataclass, field
from pathlib import Path

from src.data.unified_config import get_unified_config

logger = logging.getLogger(__name__)

# 导入调试日志工具
try:
    from src.utils.debug_log import debug_log, set_debug_log_enabled, set_project_root

    _DEBUG_LOG_AVAILABLE = True
except ImportError:
    # 如果导入失败（某些环境可能没有 utils），定义一个空函数
    _DEBUG_LOG_AVAILABLE = False

    def debug_log(*args, **kwargs):
        pass

    def set_debug_log_enabled(enabled):
        pass

    def set_project_root(root):
        pass


try:
    from playwright.async_api import (
        async_playwright,
        Browser,
        BrowserContext,
        Page,
    )  # ⭐ 改为异步 API

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    logger.warning("Playwright未安装，浏览器录制功能将不可用")


@dataclass
class BrowserAction:
    """浏览器操作事件"""

    action_type: str  # 'click', 'dblclick', 'contextmenu', 'fill', 'select', 'submit',
    # 'keydown', 'keyup', 'navigate', 'scroll', 'dragstart', 'dragend',
    # 'drop', 'mousemove'
    timestamp: float
    dom_element: Optional[Dict[str, Any]] = None
    network_requests: List[Dict[str, Any]] = field(default_factory=list)
    url: Optional[str] = None
    parameters: Dict[str, Any] = field(default_factory=dict)


class BrowserRecorder:
    """
    浏览器录制器（WebSocket 架构版本）

    功能：
    1. 使用 Playwright 启动浏览器并加载插件
    2. 通过 WebSocket 接收插件事件（替代 Native Messaging）
    3. 事件写入队列文件（主要存储）
    """

    def __init__(self, config=None, storage_path: Optional[Path] = None):
        """
        初始化浏览器录制器

        Args:
            config: RecordingConfig 配置对象（已废弃，保留向后兼容）
            storage_path: 录制数据存储路径（可选，默认：项目根目录/data/recordings）

        注意：
            - config 参数已废弃，仅保留向后兼容
            - 所有配置现在通过 get_unified_config() 访问
        """
        # ⭐ 重构：不再直接实例化 RecordingConfig
        # 保留 config 参数以保持向后兼容，但不使用它
        # 所有配置访问都通过 get_unified_config()
        if config is not None:
            logger.warning(
                "[BrowserRecorder] config 参数已废弃，所有配置现在通过 get_unified_config() 访问"
            )

        # 使用统一配置管理器
        self._unified_config = get_unified_config()

        self._is_recording = False
        self._recording_id: Optional[str] = None
        self._recording_start_time: Optional[float] = None

        # ⭐ 异步事件循环（在后台线程中持续运行）
        self._event_loop = None
        self._loop_thread = None

        # Playwright 相关
        self._playwright = None  # Playwright API 对象
        self._playwright_context = None  # Playwright 上下文管理器（用于 async_playwright）
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._pages: List[Page] = []  # 跟踪所有打开的页面

        # ⭐ WebSocket 服务器（替代 Native Messaging）
        self._ws_server = None

        # 事件回调（用于实时处理）
        self.on_action: Optional[Callable[[BrowserAction], None]] = None

        # 文件队列路径
        self._action_queue_path: Optional[Path] = None

        # 存储路径
        if storage_path is None:
            # 默认路径：项目根目录/data/recordings
            project_root = Path(__file__).parent.parent.parent
            storage_path = project_root / "data" / "recordings"
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)

        # ⭐ 新增：DuckDB 支持（Phase 4）
        self._use_duckdb = True  # 默认启用 DuckDB 存储
        # ⭐ 提前初始化 RecordingRepository，避免多次创建导致连接冲突
        from src.data.recording_repository import RecordingRepository
        self._recording_repository = RecordingRepository()

        # 初始化调试日志工具
        if _DEBUG_LOG_AVAILABLE:
            project_root = Path(__file__).parent.parent.parent
            set_project_root(project_root)
            # 从配置中读取调试日志开关，或从环境变量读取
            debug_enabled = (
                self._unified_config.get_debug_log_enabled()
                or os.getenv("MEXEMPLAR_DEBUG_LOG", "false").lower() == "true"
            )
            set_debug_log_enabled(debug_enabled)

    @property
    def page(self) -> Optional[Page]:
        """
        获取当前页面（公共访问接口）

        Returns:
            Page: Playwright 页面对象，如果未初始化则返回 None
        """
        return self._page

    def cleanup(self):
        """
        清理资源（用于初始化失败时的资源释放）

        注意：
            - 只清理已初始化的资源
            - 不会抛出异常，确保安全调用
        """
        try:
            # 清理 WebSocket 服务器
            if self._ws_server:
                try:
                    self._ws_server.stop()
                    logger.info("WebSocket 服务器已停止")
                except Exception as e:
                    logger.warning(f"停止 WebSocket 服务器失败: {e}")

            # 清理浏览器资源
            if self._browser:
                try:
                    # 异步关闭浏览器
                    if self._event_loop and not self._event_loop.is_closed():
                        import asyncio
                        try:
                            asyncio.run_coroutine_threadsafe(
                                self._browser.close(),
                                self._event_loop
                            ).result(timeout=5)
                        except Exception as e:
                            logger.warning(f"关闭浏览器失败: {e}")
                except Exception as e:
                    logger.warning(f"清理浏览器资源失败: {e}")

            # 停止事件循环
            if self._event_loop and not self._event_loop.is_closed():
                try:
                    self._event_loop.call_soon_threadsafe(self._event_loop.stop)
                except Exception as e:
                    logger.warning(f"停止事件循环失败: {e}")

            # 清理 RecordingRepository
            if hasattr(self, '_recording_repository') and self._recording_repository:
                try:
                    if hasattr(self._recording_repository, 'db') and self._recording_repository.db:
                        if hasattr(self._recording_repository.db, 'close'):
                            self._recording_repository.db.close()
                            logger.info("DuckDB 连接已关闭")
                except Exception as e:
                    logger.warning(f"关闭数据库连接失败: {e}")

            logger.info("资源清理完成")
        except Exception as e:
            logger.error(f"清理资源时出错: {e}", exc_info=True)

    def _get_queue_paths(self, recording_id: str):
        """获取队列文件路径（WebSocket 模式只需要 action_queue）"""
        # 固定队列文件目录：data/queues/
        project_root = Path(__file__).parent.parent.parent
        queue_dir = project_root / "data" / "queues"
        queue_dir.mkdir(parents=True, exist_ok=True)

        action_queue = queue_dir / f"{recording_id}_actions.jsonl"

        return action_queue

    def _ensure_event_loop(self):
        """确保事件循环正在后台线程中运行"""
        if self._event_loop is None or self._event_loop.is_closed():
            # 创建新的事件循环
            import threading

            def run_loop():
                """在后台线程中运行事件循环"""
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                self._event_loop = loop
                loop.run_forever()

            # 启动后台线程
            self._loop_thread = threading.Thread(target=run_loop, daemon=True)
            self._loop_thread.start()

            # 等待事件循环创建完成
            while self._event_loop is None:
                import time

                time.sleep(0.01)

    def _run_async(self, coro):
        """在持久事件循环中运行异步任务"""
        self._ensure_event_loop()
        future = asyncio.run_coroutine_threadsafe(coro, self._event_loop)
        # 等待异步任务完成并返回结果
        return future.result(timeout=120)  # 设置 120 秒超时

    async def _launch_browser_with_subprocess(self, start_url: Optional[str] = None) -> bool:
        """
        使用 subprocess 启动系统 Chrome 并加载插件
        这种方式避免了 Playwright 的兼容性问题（新标签页卡住）
        """
        """使用Playwright启动浏览器并加载插件"""
        if not PLAYWRIGHT_AVAILABLE:
            logger.error("Playwright未安装，无法启动浏览器")
            return False

        try:
            # 获取插件路径
            extension_path = Path(__file__).parent / "browser_extension"
            extension_path = extension_path.resolve()

            # 🔒 安全验证：扩展路径
            extension_path_str = self._validate_extension_path(str(extension_path))

            logger.info(f"启动浏览器，加载插件: {extension_path_str}")

            # ⭐ 启动 Playwright（使用异步 API）
            self._playwright_context = async_playwright()
            self._playwright = await self._playwright_context.__aenter__()

            # 使用持久化上下文加载插件；launch() + new_context() 不会载入扩展
            # 根据 persistent_user_data 配置决定使用持久化还是临时目录
            persistent_user_data = self._unified_config.get(
                "recording.persistent_user_data", default=True
            )
            user_data_dir_config = self._unified_config.get("recording.user_data_dir", default=None)

            if persistent_user_data:
                # 持久化模式：保留登录状态、cookies 等
                if user_data_dir_config:
                    # 用户自定义路径
                    user_data_dir = Path(user_data_dir_config)
                    logger.info(f"使用自定义持久化 user_data_dir: {user_data_dir}")
                else:
                    # 默认持久化路径
                    user_data_dir = self.storage_path.parent / "playwright_user_data_persistent"
                    logger.info(f"使用默认持久化 user_data_dir: {user_data_dir} (保留登录状态)")
            else:
                # 临时模式：每次录制都使用新的临时目录
                import uuid

                unique_id = str(uuid.uuid4())[:8]
                user_data_dir = self.storage_path.parent / f"playwright_user_data_{unique_id}"
                logger.info(f"使用临时 user_data_dir: {user_data_dir} (录制结束后不保留)")
            user_data_dir.mkdir(parents=True, exist_ok=True)

            # 对于持久化模式，检查扩展是否已加载
            # 如果用户数据目录存在但扩展未安装，需要清理重建
            if persistent_user_data and user_data_dir.exists():
                extensions_dir = user_data_dir / "Default" / "Extensions"
                if extensions_dir.exists():
                    # 检查是否有我们的扩展（通过 manifest.json 中的 key 判断）
                    has_our_extension = False
                    for ext_dir in extensions_dir.iterdir():
                        if ext_dir.is_dir():
                            manifest_file = ext_dir / "manifest.json"
                            if manifest_file.exists():
                                try:
                                    import json

                                    with open(manifest_file, "r", encoding="utf-8") as f:
                                        manifest = json.load(f)
                                    if manifest.get("name") == "Mexemplar Recorder":
                                        has_our_extension = True
                                        logger.info(f"发现已安装的扩展: {ext_dir.name}")
                                        break
                                except (json.JSONDecodeError, IOError, OSError) as e:
                                    # 忽略损坏的扩展目录
                                    logger.debug(f"跳过损坏的扩展目录: {ext_dir.name}, 错误: {e}")
                                    pass

                    # 如果没有找到我们的扩展，清理并重建
                    if not has_our_extension:
                        logger.warning(f"持久化目录中未找到扩展，清理重建: {user_data_dir}")
                        import shutil

                        shutil.rmtree(user_data_dir)
                        user_data_dir.mkdir(parents=True, exist_ok=True)
                        logger.info("持久化目录已重建，扩展将被重新加载")

            # 保存 user_data_dir 到实例变量，用于后续清理
            self._user_data_dir = user_data_dir

            debug_log(
                location="browser_recorder.py:282",
                message="准备启动浏览器",
                data={"user_data_dir": str(user_data_dir), "extension_path": str(extension_path)},
                session_id="debug-session",
                run_id="run1",
                hypothesis_id="H6",
            )
            # 注意：Chrome 和 Edge 移除了侧载扩展所需的命令行标志
            # 因此 Chrome 通道不支持通过 --load-extension 加载扩展
            # 我们必须使用 Chromium（Playwright 捆绑的版本）来加载扩展
            # Chromium 可能不支持 Native Messaging，但我们可以尝试
            logger.info("使用 Chromium 启动浏览器（Chrome 通道不支持通过命令行加载扩展）")
            debug_log(
                location="browser_recorder.py:290",
                message="使用 Chromium 启动（Chrome 通道不支持扩展加载）",
                data={"extension_path": str(extension_path)},
                session_id="debug-session",
                run_id="run1",
                hypothesis_id="H8",
            )
            # 确保使用绝对路径
            extension_path_absolute = Path(extension_path_str).resolve()
            # 使用正斜杠路径（Chrome 在 Windows 上更倾向于正斜杠）
            extension_path_final = extension_path_absolute.as_posix()
            logger.info(f"扩展路径: {extension_path_final}")
            debug_log(
                location="browser_recorder.py:298",
                message="准备启动 Chromium",
                data={
                    "extension_path": extension_path_final,
                    "extension_path_exists": extension_path_absolute.exists(),
                    "manifest_exists": (extension_path_absolute / "manifest.json").exists(),
                },
                session_id="debug-session",
                run_id="run1",
                hypothesis_id="H8",
            )
            # 注意：系统 Chrome 不支持通过命令行加载扩展（Chrome 88+ 移除了此功能）
            # 必须使用 Playwright Chromium 才能通过 --load-extension 加载扩展
            # 因此我们不查找系统 Chrome，直接使用 Playwright Chromium

            logger.info("使用 Playwright Chromium 启动浏览器（持久化模式 + 异步 API）")

            # ⭐ 恢复持久化模式（可以加载扩展）
            # 使用异步 API 解决 target="_blank" 新标签页的问题
            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=False,
                accept_downloads=True,
                ignore_default_args=["--enable-automation"],
                args=[
                    f"--disable-extensions-except={extension_path_final}",
                    f"--load-extension={extension_path_final}",
                    "--disable-gpu",
                    "--no-sandbox",
                    "--disable-web-security",
                    "--disable-features=VizDisplayCompositor",
                    "--disable-popup-blocking",
                    "--disable-blink-features=AutomationControlled",
                ],
            )

            logger.info("浏览器已启动（持久化模式，扩展已加载）")

            # ⭐ 通过 CDP 注入配置到所有页面（在页面加载前执行）
            config = get_unified_config()
            ws_host = config.get_websocket_host()
            ws_port = config.get_websocket_port()
            max_body_size = config.get_websocket_max_response_body_size()

            init_script = f"""
            // 隐藏自动化特征，避免触发风控
            Object.defineProperty(navigator, 'webdriver', {{ get: () => undefined }});

            // Mexemplar 配置注入（由 Python 端通过 CDP 注入）
            window.MEXEMPLAR_CONFIG = {{
                websocketUrl: 'ws://{ws_host}:{ws_port}',
                recordingId: '{self._recording_id}',
                maxResponseBodySize: {max_body_size},
                version: '1.0'
            }};
            // 只在调试模式下输出日志
            if (typeof window !== 'undefined' && window.MEXEMPLAR_DEBUG) {{
                console.log('[Mexemplar] 配置已通过 CDP 注入:', window.MEXEMPLAR_CONFIG);
            }}
            """

            await self._context.add_init_script(init_script)
            logger.info(f"[CDP] 已注入配置到所有页面: ws://{ws_host}:{ws_port}")
            logger.info(f"[CDP] 最大响应体大小: {max_body_size / 1024 / 1024:.1f} MB")

            # ⭐ 监听新页面创建事件（使用异步 API 解决 target="_blank" 空白页问题）
            def handle_new_page(page: Page) -> None:
                """处理新创建的页面（通过 target="_blank" 等方式）"""
                logger.debug(f"检测到新页面创建，初始 URL: {page.url}")

                # 将页面添加到跟踪列表
                if page not in self._pages:  # 避免重复添加
                    self._pages.append(page)

                # ⭐ 关键：创建异步任务等待页面加载（异步 API 方式）
                async def wait_for_page_load():
                    try:
                        # 先等待 DOMContentLoaded
                        await page.wait_for_load_state("domcontentloaded", timeout=10000)
                        logger.debug(f"新页面 DOM 已加载: {page.url}")

                        # 再等待 load 事件（确保所有资源加载完成）
                        await page.wait_for_load_state("load", timeout=10000)
                        logger.debug(f"新页面完全加载成功: {page.url}")

                    except Exception as e:
                        logger.warning(f"新页面加载失败: {e}, URL: {page.url}")

                # 创建异步任务（不阻塞事件循环）
                asyncio.create_task(wait_for_page_load())

            self._context.on("page", handle_new_page)
            logger.info("已注册新页面监听器（支持 target='_blank' popup 页面，异步 API）")

            # ⭐ 添加定期检查机制（兜底方案：主动发现新标签页）
            import threading

            def check_new_pages():
                """定期检查是否有新页面未被跟踪"""
                last_page_count = len(self._pages)
                while self._browser and not self._browser.is_connected():
                    time.sleep(1)

                while self._browser and self._browser.is_connected():
                    try:
                        current_pages = self._context.pages
                        current_page_count = len(current_pages)

                        # 发现新页面
                        if current_page_count > last_page_count:
                            logger.info(
                                f"[POLLED] 发现新页面！总数: {last_page_count} → {current_page_count}"
                            )

                            # 找出新增的页面
                            for page in current_pages:
                                if page not in self._pages:
                                    logger.info(f"[POLLED] 发现未跟踪的页面: {page.url}")
                                    self._pages.append(page)

                                    # 等待页面加载
                                    try:
                                        if page.url == "about:blank" or not page.url:
                                            logger.info("[POLLED] 页面 URL 为空，等待导航...")
                                            page.wait_for_load_state(
                                                "domcontentloaded", timeout=10000
                                            )
                                        logger.info(f"[POLLED] 页面已加载: {page.url}")
                                    except Exception as e:
                                        logger.warning(f"[POLLED] 等待页面加载失败: {e}")

                            last_page_count = current_page_count

                        time.sleep(0.5)  # 每 0.5 秒检查一次

                    except Exception as e:
                        logger.debug(f"[POLLED] 检查页面时出错: {e}")
                        time.sleep(1)

            # 启动定期检查线程
            poll_thread = threading.Thread(target=check_new_pages, daemon=True)
            poll_thread.start()
            logger.info("已启动页面定期检查线程（兜底方案）")

            logger.info("Chromium 启动成功（支持扩展加载）")
            debug_log(
                location="browser_recorder.py:310",
                message="Chromium 启动成功",
                data={},
                session_id="debug-session",
                run_id="run1",
                hypothesis_id="H8",
            )

            debug_log(
                location="browser_recorder.py:347",
                message="浏览器启动完成，准备创建页面",
                data={
                    "extension_path": str(extension_path),
                    "extension_path_exists": Path(extension_path).exists(),
                },
                session_id="debug-session",
                run_id="run1",
                hypothesis_id="H7",
            )

            # ⭐ 使用浏览器启动时的默认页面，不再创建新页面
            # Playwright 启动时会自动创建一个标签页
            existing_pages = self._context.pages
            if existing_pages:
                self._page = existing_pages[0]
                self._pages.append(self._page)
                logger.info(f"使用默认页面，URL: {self._page.url}")
            else:
                # 兜底：如果没有默认页面，才创建一个
                self._page = await self._context.new_page()
                self._pages.append(self._page)
                logger.info(f"创建新页面，URL: {self._page.url}")

            debug_log(
                location="browser_recorder.py:351",
                message="页面已准备就绪",
                data={},
                session_id="debug-session",
                run_id="run1",
                hypothesis_id="H7",
            )

            # 导航到起始URL（如果提供）
            if start_url:
                await self._page.goto(start_url, wait_until="domcontentloaded", timeout=30000)
            else:
                # 不导航到任何页面，用户可以手动输入 URL
                logger.info("未提供起始 URL，浏览器保持在空白页")

            # 等待页面加载完成（不等待networkidle，因为某些页面可能有持续的网络请求）
            # 使用较短的超时时间，避免无限等待
            try:
                await self._page.wait_for_load_state("load", timeout=5000)
            except Exception as e:
                logger.debug(f"等待load状态超时，继续执行: {e}")
                # 即使超时也继续，因为domcontentloaded已经完成

            # 检查扩展是否加载
            logger.info("正在检查扩展加载状态...")
            debug_log(
                location="browser_recorder.py:287",
                message="checking extension loading status",
                data={"extension_path": str(extension_path)},
                session_id="debug-session",
                run_id="run1",
                hypothesis_id="A",
            )

            extension_loaded = False
            try:
                # 尝试获取扩展ID（通过检查扩展的background page）
                # 注意：Manifest V3使用service worker，可能无法通过background_pages访问
                extensions = list(self._context.background_pages)
                if extensions:
                    logger.info(f"检测到 {len(extensions)} 个扩展已加载")
                    for i, ext in enumerate(extensions):
                        logger.info(
                            f"  扩展 {i+1}: {ext.url if hasattr(ext, 'url') else 'unknown'}"
                        )
                    extension_loaded = True
                else:
                    logger.warning(
                        "未检测到扩展的background page（Manifest V3使用service worker，这是正常的）"
                    )

                # 尝试通过CDP检查扩展
                try:
                    cdp_session = await self._context.new_cdp_session(self._page)
                    # 获取所有targets
                    targets_result = await cdp_session.send("Target.getTargets")
                    all_targets = targets_result.get("targetInfos", [])
                    logger.info(f"通过CDP检测到 {len(all_targets)} 个targets")

                    debug_log(
                        location="browser_recorder.py:307",
                        message="CDP targets count",
                        data={"total_targets": len(all_targets)},
                        session_id="debug-session",
                        run_id="run1",
                        hypothesis_id="A",
                    )

                    # 检查service worker
                    extension_targets = [
                        t for t in all_targets if t.get("type") == "service_worker"
                    ]
                    if extension_targets:
                        logger.info(
                            f"通过CDP检测到 {len(extension_targets)} 个service worker（扩展background script）"
                        )
                        for i, target in enumerate(extension_targets):
                            logger.info(f"  Service Worker {i+1}: {target.get('url', 'unknown')}")
                        extension_loaded = True

                        debug_log(
                            location="browser_recorder.py:312",
                            message="service workers found",
                            data={
                                "count": len(extension_targets),
                                "urls": [t.get("url", "unknown") for t in extension_targets],
                            },
                            session_id="debug-session",
                            run_id="run1",
                            hypothesis_id="A",
                        )
                    else:
                        logger.warning("⚠ 未通过CDP检测到service worker（扩展可能未加载）")

                        debug_log(
                            location="browser_recorder.py:317",
                            message="no service workers found",
                            data={},
                            session_id="debug-session",
                            run_id="run1",
                            hypothesis_id="A",
                        )

                    # 列出所有target类型用于调试
                    target_types = {}
                    for target in all_targets:
                        t_type = target.get("type", "unknown")
                        target_types[t_type] = target_types.get(t_type, 0) + 1
                    logger.debug(f"Target类型统计: {target_types}")

                    debug_log(
                        location="browser_recorder.py:324",
                        message="target types statistics",
                        data={"target_types": target_types},
                        session_id="debug-session",
                        run_id="run1",
                        hypothesis_id="A",
                    )

                    await cdp_session.detach()
                except Exception as cdp_e:
                    logger.warning(f"通过CDP检查扩展失败: {cdp_e}")

                    debug_log(
                        location="browser_recorder.py:328",
                        message="CDP extension check failed",
                        data={"error": str(cdp_e)},
                        session_id="debug-session",
                        run_id="run1",
                        hypothesis_id="A",
                    )

            except Exception as e:
                logger.warning(f"检查扩展加载状态失败: {e}")

                debug_log(
                    location="browser_recorder.py:331",
                    message="extension loading check exception",
                    data={"error": str(e)},
                    session_id="debug-session",
                    run_id="run1",
                    hypothesis_id="A",
                )

            if not extension_loaded:
                logger.error("⚠ 警告：未检测到扩展已加载！")
                logger.error("  可能原因：")
                logger.error("  1. 扩展路径不正确")
                logger.error("  2. manifest.json配置错误")
                logger.error("  3. 扩展文件缺失或损坏")
                logger.error(f"  扩展路径: {extension_path}")
                logger.error("  请检查浏览器开发者工具中的扩展错误信息")

                debug_log(
                    location="browser_recorder.py:334",
                    message="extension not loaded warning",
                    data={"extension_path": str(extension_path)},
                    session_id="debug-session",
                    run_id="run1",
                    hypothesis_id="A",
                )
            else:
                logger.info("扩展加载检查完成")

            logger.info("浏览器启动成功")
            return True

        except Exception as e:
            logger.error(f"启动浏览器失败: {e}", exc_info=True)
            return False

    @staticmethod
    def _validate_extension_path(extension_path: str) -> str:
        """
        验证扩展路径安全性（防止命令注入）

        Args:
            extension_path: 待验证的扩展路径

        Returns:
            验证后的绝对路径字符串

        Raises:
            ValueError: 如果路径不安全
        """
        path = Path(extension_path).resolve()

        if not path.exists():
            raise ValueError(f"扩展路径不存在: {path}")

        if not path.is_dir():
            raise ValueError(f"扩展路径必须是目录: {path}")

        # 检查路径是否在项目目录内
        project_root = Path(__file__).parent.parent.parent.resolve()
        try:
            path.relative_to(project_root)
        except ValueError:
            logger.warning(f"扩展路径不在项目目录内: {path}")

        return str(path)

    @staticmethod
    @contextmanager
    def _suppress_playwright_logs():
        """临时抑制 Playwright 的关闭日志"""
        import logging
        playwright_logger = logging.getLogger('playwright')
        original_level = playwright_logger.level
        try:
            # 设置到比CRITICAL更高的级别，只抑制Playwright日志
            playwright_logger.setLevel(logging.CRITICAL + 1)
            yield
        finally:
            # 恢复原始日志级别
            playwright_logger.setLevel(original_level)

    async def _close_browser(self):
        """关闭浏览器（异步版本）"""
        # 使用上下文管理器临时抑制Playwright日志，而非全局禁用
        with self._suppress_playwright_logs():
            # ⭐ 关闭所有跟踪的页面
            if hasattr(self, "_pages") and self._pages:
                for page in self._pages:
                    try:
                        if not page.is_closed():
                            await page.close()
                    except Exception:
                        pass  # 静默忽略所有关闭时的错误
                self._pages.clear()

            if self._page:
                try:
                    if not self._page.is_closed():
                        await self._page.close()
                except Exception:
                    pass  # 静默忽略所有关闭时的错误

            if self._context:
                try:
                    await self._context.close()
                except Exception:
                    pass  # 静默忽略所有关闭时的错误

            # ⭐ 正确清理 Playwright 上下文管理器
            if self._playwright_context:
                try:
                    await self._playwright_context.__aexit__(None, None, None)
                except Exception:
                    pass  # 静默忽略所有关闭时的错误

    # ===== WebSocket 相关方法 =====

    def _start_websocket_server(self):
        """启动 WebSocket 服务器（后台线程）"""
        from .websocket_server import WebSocketServer

        logger.info("启动 WebSocket 服务器...")

        # ⭐ 创建 WebSocket 服务器（从配置读取）
        config = get_unified_config()
        self._ws_server = WebSocketServer(
            host=config.get_websocket_host(), port=config.get_websocket_port()
        )

        # 注册消息处理器（用于写入队列文件）
        self._ws_server.set_message_handler(self._handle_ws_message)

        # 使用内置方法在后台线程中启动（会正确设置 _loop）
        self._ws_server.start_in_thread()

        logger.info("WebSocket 服务器已启动（后台线程）")

    def _handle_ws_message(self, message: Dict[str, Any]):
        """
        处理 WebSocket 消息并写入队列文件

        Args:
            message: WebSocket 消息数据
        """
        msg_type = message.get("type")

        if msg_type == "browser_action":
            # 1. 写入队列文件（主要存储）
            self._write_browser_action_to_queue(message)

            # 2. 触发回调（实时处理）
            if self.on_action:
                action = BrowserAction(
                    action_type=message["action"]["action_type"],
                    timestamp=message["action"].get("timestamp", time.time()),
                    dom_element=message["action"].get("dom_element"),
                    network_requests=message["action"].get("network_requests", []),
                    url=message["action"].get("url"),
                    parameters=message["action"].get("parameters", {}),
                )
                self.on_action(action)

    def _write_browser_action_to_queue(self, message: Dict[str, Any]):
        """
        写入浏览器动作到队列文件（主要存储）

        Args:
            message: WebSocket 消息数据
        """
        if not self._action_queue_path:
            return

        try:
            # 添加外层包装（与 Native Messaging 格式一致）
            wrapped_message = {
                "type": "browser_action",
                "recording_id": self._recording_id,
                "action": message.get("action", {}),
                "timestamp": time.time(),
            }

            # 写入队列文件（JSONL 格式）
            with open(self._action_queue_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(wrapped_message, ensure_ascii=False) + "\n")

            logger.debug(f"[WS] 事件已写入队列文件: {message['action'].get('action_type')}")

        except Exception as e:
            logger.error(f"写入队列文件失败: {e}")

    def _wait_for_ws_connection(self, timeout: int = 20) -> bool:
        """
        等待 WebSocket 连接

        Args:
            timeout: 超时时间（秒）

        Returns:
            是否连接成功
        """
        start_time = time.time()

        while time.time() - start_time < timeout:
            if self._ws_server and self._ws_server.is_running:
                return True
            time.sleep(0.5)

        return False

    def _send_start_command_via_ws(self, recording_id: str):
        """
        通过 WebSocket 发送开始录制命令

        Args:
            recording_id: 录制 ID
        """
        import asyncio

        message = {"type": "control_start", "recording_id": recording_id, "timestamp": time.time()}

        # 使用 run_coroutine_threadsafe 从其他线程安全地调用异步函数
        if self._ws_server and self._ws_server._loop:
            future = asyncio.run_coroutine_threadsafe(
                self._ws_server.broadcast(message), self._ws_server._loop
            )
            # 等待发送完成（最多 5 秒）
            try:
                future.result(timeout=5)
                logger.info(f"已通过 WebSocket 发送开始录制命令: {recording_id}")
            except asyncio.TimeoutError:
                logger.error(f"[WS] 发送开始录制命令超时: {recording_id}")
            except Exception as e:
                logger.error(f"[WS] 发送开始录制命令失败: {e}")

    def _send_stop_command_via_ws(self):
        """通过 WebSocket 发送停止录制命令"""
        import asyncio

        message = {
            "type": "control_stop",
            "recording_id": self._recording_id,
            "timestamp": time.time(),
        }

        # 使用 run_coroutine_threadsafe 从其他线程安全地调用异步函数
        if self._ws_server and self._ws_server._loop:
            future = asyncio.run_coroutine_threadsafe(
                self._ws_server.broadcast(message), self._ws_server._loop
            )
            # 等待发送完成（最多 5 秒）
            try:
                future.result(timeout=5)
                logger.info("已通过 WebSocket 发送停止录制命令")
            except asyncio.TimeoutError:
                logger.error("[WS] 发送停止录制命令超时")
            except Exception as e:
                logger.error(f"[WS] 发送停止录制命令失败: {e}")

    def start_recording(
        self, start_url: Optional[str] = None, recording_id: Optional[str] = None
    ) -> bool:
        """
        开始录制（WebSocket 架构版本）- 同步包装器

        Args:
            start_url: 浏览器启动时的初始URL
            recording_id: 可选的录制ID，如果不提供则自动生成

        Returns:
            是否成功
        """
        return self._run_async(self._async_start_recording(start_url, recording_id))

    async def _async_start_recording(
        self, start_url: Optional[str] = None, recording_id: Optional[str] = None
    ) -> bool:
        """
        开始录制（WebSocket 架构版本）- 异步实现

        Args:
            start_url: 浏览器启动时的初始URL
            recording_id: 可选的录制ID，如果不提供则自动生成

        Returns:
            是否成功
        """
        if self._is_recording:
            logger.warning("录制已在进行中")
            return False

        import uuid

        # 使用提供的 recording_id 或生成新的
        self._recording_id = recording_id or str(uuid.uuid4())
        self._recording_start_time = time.time()

        logger.info(f"开始浏览器录制，会话ID: {self._recording_id}")

        # 1. 获取队列路径（WebSocket 模式使用）
        self._action_queue_path = self._get_queue_paths(self._recording_id)
        self._action_queue_path.parent.mkdir(parents=True, exist_ok=True)

        # 2. 启动 WebSocket 服务器
        logger.info("启动 WebSocket 服务器...")
        self._start_websocket_server()

        # 3. 启动浏览器（加载扩展）
        logger.info("启动浏览器并加载扩展...")
        if not await self._launch_browser_with_subprocess(start_url):
            logger.error("启动浏览器失败")
            return False

        # 4. 等待 WebSocket 连接（扩展自动连接）
        logger.info("等待浏览器扩展连接 WebSocket...")
        if not self._wait_for_ws_connection(timeout=20):
            logger.error("WebSocket 连接超时")
            logger.error("请检查：")
            logger.error("  1. Python WebSocket 服务器是否正常运行")
            logger.error("  2. 浏览器扩展是否正确加载")
            logger.error("  3. 防火墙是否阻止了连接")
            return False

        logger.info("WebSocket 连接成功")

        # 5. 等待标签页加载完成（确保 content_script 已注入）
        logger.info("等待标签页加载完成...")
        await asyncio.sleep(2)  # 给标签页 2 秒时间加载

        # 6. 通过 WebSocket 发送开始录制命令
        logger.info(f"发送开始录制命令: {self._recording_id}")
        self._send_start_command_via_ws(self._recording_id)

        # 7. 设置录制状态
        self._is_recording = True

        logger.info("浏览器录制已启动 (WebSocket 模式)")
        logger.info(f"   - recording_id: {self._recording_id}")
        logger.info(f"   - 队列文件: {self._action_queue_path}")
        # ⭐ 从配置读取 WebSocket 地址
        config = get_unified_config()
        logger.info(
            f"   - WebSocket: ws://{config.get_websocket_host()}:{config.get_websocket_port()}"
        )

        return True

    def stop_recording(self) -> Dict[str, Any]:
        """
        停止录制（WebSocket 架构版本）- 同步包装器

        Returns:
            录制结果字典，包含：
            {
                "recording_id": str,
                "queue_file": str,  # 队列文件路径
                "action_count": int,
                "start_time": float,
                "end_time": float,
                "recording_mode": str
            }
        """
        return self._run_async(self._async_stop_recording())

    async def _async_stop_recording(self) -> Dict[str, Any]:
        """
        停止录制（WebSocket 架构版本）- 异步实现

        Returns:
            录制结果字典，包含：
            {
                "recording_id": str,
                "queue_file": str,  # 队列文件路径
                "action_count": int,
                "start_time": float,
                "end_time": float,
                "recording_mode": str
            }
        """
        if not self._is_recording:
            return {
                "recording_id": self._recording_id,
                "queue_file": None,
                "action_count": 0,
                "start_time": self._recording_start_time,
                "end_time": time.time(),
                "recording_mode": "websocket",
            }

        logger.info("停止浏览器录制")
        end_time = time.time()

        # 1. 清除消息处理器（避免在浏览器关闭后还有新消息被处理）
        if self._ws_server:
            self._ws_server.set_message_handler(None)

        # 2. 通过 WebSocket 发送停止命令
        logger.info("发送停止录制命令...")
        self._send_stop_command_via_ws()

        # 3. 关闭浏览器
        logger.info("关闭浏览器...")
        await self._close_browser()

        # 4. WebSocket 服务器会自动停止（后台线程会结束）

        # 4. 统计队列文件中的事件数
        action_count = 0
        if self._action_queue_path and self._action_queue_path.exists():
            try:
                with open(self._action_queue_path, "r", encoding="utf-8") as f:
                    action_count = sum(1 for _ in f)
                logger.info(f"队列文件包含 {action_count} 个事件")
            except Exception as e:
                logger.warning(f"统计事件数量失败: {e}")

        # ⭐ 新增：Phase 4 - 保存到 DuckDB（即使没有事件也保存会话）
        if self._use_duckdb:
            try:
                logger.info("开始保存录制数据到 DuckDB...")
                self._save_to_duckdb(end_time, action_count)
                logger.info("DuckDB 保存完成")
            except Exception as e:
                logger.error(f"保存到 DuckDB 失败: {e}")
                # 不影响主流程，继续执行

        # 5. 清理临时用户数据目录（仅在临时模式下）
        if hasattr(self, "_user_data_dir") and self._user_data_dir:
            is_temp_dir = "playwright_user_data_" in str(
                self._user_data_dir
            ) and "_persistent" not in str(self._user_data_dir)
            persistent_user_data = self._unified_config.get(
                "recording.persistent_user_data", default=True
            )

            if not persistent_user_data and is_temp_dir and self._user_data_dir.exists():
                try:
                    import shutil

                    shutil.rmtree(self._user_data_dir)
                    logger.info(f"已清理临时用户数据目录: {self._user_data_dir}")
                except Exception as e:
                    logger.warning(f"清理临时目录失败: {e}")

        # 6. 重置状态
        self._is_recording = False
        self._browser = None
        self._context = None
        self._page = None
        self._playwright = None

        logger.info("浏览器录制已停止 (WebSocket 模式)")
        logger.info(f"   - recording_id: {self._recording_id}")
        logger.info(f"   - 队列文件: {self._action_queue_path}")
        logger.info(f"   - 事件数量: {action_count}")

        # 7. 返回录制结果
        return {
            "recording_id": self._recording_id,
            "queue_file": str(self._action_queue_path) if self._action_queue_path else None,
            "action_count": action_count,
            "start_time": self._recording_start_time,
            "end_time": end_time,
            "recording_mode": "websocket",
        }

    # ===== DuckDB 存储方法（Phase 4）=====

    def _save_to_duckdb(self, end_time: float, action_count: int):
        """
        保存录制数据到 DuckDB

        Args:
            end_time: 录制结束时间
            action_count: 操作数量
        """

        # RecordingRepository 在 __init__ 时已初始化，直接使用

        # 1. 保存录制会话
        session_data = {
            "recording_id": self._recording_id,
            "status": "completed",
            "recording_mode": "browser",
            "browser_type": "chromium",
            "start_time": self._recording_start_time,
            "end_time": end_time,
            "metadata": {
                "queue_file": str(self._action_queue_path) if self._action_queue_path else None,
                "action_count": action_count,
                "websocket_mode": True,
            },
        }
        self._recording_repository.save_recording_session(session_data)
        logger.info(f"录制会话已保存到 DuckDB: {self._recording_id}")

        # 2. 从队列文件读取事件并保存
        if not self._action_queue_path or not self._action_queue_path.exists():
            logger.warning("队列文件不存在，跳过操作保存")
            return

        actions_list = []
        network_requests_map = {}  # line_num -> network_requests
        standalone_network_requests = []  # ⭐ 新增：独立的网络请求（action_id 为 NULL）

        try:
            with open(self._action_queue_path, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    if not line.strip():
                        continue

                    try:
                        event_data = json.loads(line)
                        action_dict = self._convert_event_to_action_dict(event_data)

                        # ⭐ 过滤掉独立的 network_request action（只保存在 network_requests 表）
                        if action_dict.get("action_type") == "network_request":
                            # 提取网络请求，不添加到 actions_list
                            if action_dict.get("_extracted_network_request"):
                                standalone_network_requests.append(
                                    action_dict["_extracted_network_request"]
                                )
                            logger.debug(
                                "跳过独立的 network_request action，直接保存到 network_requests 表"
                            )
                        else:
                            actions_list.append(action_dict)

                        # ⭐ 收集网络请求（两种来源）
                        action = event_data.get("action", {})

                        # 来源1: 关联到 DOM 事件的网络请求
                        if action.get("network_requests"):
                            network_requests_map[line_num] = action["network_requests"]

                        # 来源2: 独立的 network_request 类型的 action
                        if action_dict.get("_extracted_network_request"):
                            network_requests_map[line_num] = [
                                action_dict["_extracted_network_request"]
                            ]

                    except json.JSONDecodeError as e:
                        logger.warning(f"解析事件 {line_num} 失败: {e}")
                        continue
                    except Exception as e:
                        logger.warning(f"处理事件 {line_num} 失败: {e}")
                        continue

        except Exception as e:
            logger.error(f"读取队列文件失败: {e}")
            return

        # 3. 批量保存操作
        if actions_list:
            # ⭐ 清理临时字段（避免保存到数据库）
            for action_dict in actions_list:
                action_dict.pop("_extracted_network_request", None)

            action_ids = self._recording_repository.save_actions(self._recording_id, actions_list)
            logger.info(f"已保存 {len(action_ids)} 条操作到 DuckDB")

            # 3.5 保存兄弟元素快照（sibling_snapshots）
            snapshot_count = 0
            for i, action_id in enumerate(action_ids):
                if i < len(actions_list) and actions_list[i].get("siblings_snapshot"):
                    try:
                        self._recording_repository.save_sibling_snapshot(
                            action_id,
                            actions_list[i]["siblings_snapshot"],
                            self._recording_id,
                        )
                        snapshot_count += 1
                    except Exception as e:
                        logger.warning(f"保存兄弟元素快照失败 (action_id={action_id}): {e}")
            if snapshot_count > 0:
                logger.info(f"已保存 {snapshot_count} 条兄弟元素快照到 DuckDB")

            # 4. 保存网络请求
            request_count = 0

            logger.info(f"网络请求统计: network_requests_map={len(network_requests_map)}, standalone={len(standalone_network_requests)}")

            # 4.1 关联到 action 的网络请求
            if network_requests_map and action_ids:
                for i, action_id in enumerate(action_ids):
                    if i + 1 in network_requests_map:
                        requests = network_requests_map[i + 1]
                        logger.debug(f"保存 action_id={action_id} 的 {len(requests)} 条网络请求")
                        self._recording_repository.save_network_requests(action_id, requests, self._recording_id)
                        request_count += len(requests)

            # 4.2 独立的网络请求（action_id 为 NULL），批量保存
            if standalone_network_requests:
                logger.debug(f"保存 {len(standalone_network_requests)} 条独立网络请求 (action_id=NULL)")
                saved = self._recording_repository.save_network_requests(
                    None, standalone_network_requests, self._recording_id
                )
                request_count += len(saved)

            if request_count > 0:
                logger.info(f"已保存 {request_count} 条网络请求到 DuckDB")
            else:
                logger.warning(f"未找到任何网络请求保存 (network_requests_map={len(network_requests_map)}, standalone={len(standalone_network_requests)})")

        # 注意：录制完成事件由 main_window.py 统一发送，这里不需要重复发送

    def _convert_event_to_action_dict(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        将扩展事件数据转换为 Action 字典格式

        Args:
            event_data: 扩展发送的事件数据
                       格式1: { action: { action_type, url, ... } } (DOM 事件)
                       格式2: { action_type, url, parameters, ... } (网络请求，扁平结构)

        Returns:
            Action 字典
        """
        # ⭐ 修复：支持两种事件格式
        # 格式1: action 数据在 event_data['action'] 里面（DOM 事件）
        # 格式2: action_type 在顶层（网络请求事件，扁平结构）
        action = event_data.get("action", {})

        # 如果 action 为空但 event_data 有 action_type，说明是扁平格式（网络请求）
        if not action and event_data.get("action_type"):
            action = event_data

        action_dict = {
            "action_type": action.get("action_type"),
            "recording_mode": "browser",
            "app_name": "Browser",
            "process_name": "browser",
            "window_title": action.get("page_title"),  # 使用页面标题
            "parameters": action.get("parameters", {}),
            "url": action.get("url"),
            "dom_element": action.get("dom_element"),
            "timestamp": action.get("timestamp"),
        }

        # 增强字段（Phase 3）
        if action.get("visual_features"):
            action_dict["visual_features"] = action["visual_features"]

        if action.get("siblings_snapshot"):
            action_dict["siblings_snapshot"] = action["siblings_snapshot"]

        if action.get("dom_tree_snapshot"):
            action_dict["dom_tree_snapshot"] = action["dom_tree_snapshot"]

        # ⭐ 新增：网络请求数据（Phase 4）
        if action.get("network_requests"):
            action_dict["network_requests"] = action["network_requests"]

        # ⭐ 修复：如果是 network_request 类型的 action，提取网络请求详细信息
        if action.get("action_type") == "network_request":
            params = action.get("parameters", {})
            action_dict["_extracted_network_request"] = {
                "url": action.get("url"),
                "method": params.get("method"),
                "request_type": params.get("request_type", "xhr"),  # ⭐ 新增：请求类型
                "request_headers": params.get("request_headers", {}),
                "request_body": params.get("request_body"),
                "response_status": params.get("response_status"),
                "response_headers": params.get("response_headers", {}),
                "response_body": params.get("response_body"),
                "duration": params.get("duration"),
                "timestamp": action.get("timestamp"),
            }
            logger.debug(f"提取到网络请求: {action.get('url')[:60]}...")

        return action_dict

    # ===== 其他辅助方法 =====

    def is_recording(self) -> bool:
        """检查是否正在录制"""
        return self._is_recording

