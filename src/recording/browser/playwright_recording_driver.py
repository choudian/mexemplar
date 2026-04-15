from __future__ import annotations

import asyncio
import json
import logging
import shutil
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


class PlaywrightRecordingDriver:
    def __init__(
        self,
        *,
        storage_path: Path,
        unified_config,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.storage_path = Path(storage_path)
        self._unified_config = unified_config
        self._logger = logger or logging.getLogger(__name__)

        self._playwright = None
        self._playwright_context = None
        self._browser = None
        self._context = None
        self._page = None
        self._pages: List[Any] = []
        self._pages_lock = threading.Lock()
        self._playwright_ws_client = None
        self._playwright_launch_token: Optional[str] = None
        self._playwright_extension_bundle_path: Optional[Path] = None
        self._user_data_dir: Optional[Path] = None

    @property
    def playwright(self):
        return self._playwright

    @playwright.setter
    def playwright(self, value) -> None:
        self._playwright = value

    @property
    def playwright_context(self):
        return self._playwright_context

    @playwright_context.setter
    def playwright_context(self, value) -> None:
        self._playwright_context = value

    @property
    def browser(self):
        return self._browser

    @browser.setter
    def browser(self, value) -> None:
        self._browser = value

    @property
    def context(self):
        return self._context

    @context.setter
    def context(self, value) -> None:
        self._context = value

    @property
    def page(self):
        return self._page

    @page.setter
    def page(self, value) -> None:
        self._page = value

    @property
    def pages(self) -> List[Any]:
        return self._pages

    @pages.setter
    def pages(self, value: List[Any]) -> None:
        self._pages = value

    @property
    def playwright_ws_client(self):
        return self._playwright_ws_client

    @playwright_ws_client.setter
    def playwright_ws_client(self, value) -> None:
        self._playwright_ws_client = value

    @property
    def playwright_launch_token(self) -> Optional[str]:
        return self._playwright_launch_token

    @playwright_launch_token.setter
    def playwright_launch_token(self, value: Optional[str]) -> None:
        self._playwright_launch_token = value

    @property
    def playwright_extension_bundle_path(self) -> Optional[Path]:
        return self._playwright_extension_bundle_path

    @playwright_extension_bundle_path.setter
    def playwright_extension_bundle_path(self, value: Optional[Path]) -> None:
        self._playwright_extension_bundle_path = value

    @property
    def user_data_dir(self) -> Optional[Path]:
        return self._user_data_dir

    @user_data_dir.setter
    def user_data_dir(self, value: Optional[Path]) -> None:
        self._user_data_dir = value

    async def launch_browser_with_subprocess(
        self,
        *,
        start_url: Optional[str],
        recording_id: Optional[str],
        playwright_available: bool,
        async_playwright_factory: Callable[[], Any],
        prepare_extension_bundle: Callable[[Path], Path],
        validate_extension_path: Callable[[str], str],
        classify_extension_targets: Callable[[List[Dict[str, Any]]], Dict[str, List[Dict[str, Any]]]],
        sleep_coro: Callable[[float], Any] = asyncio.sleep,
    ) -> bool:
        if not playwright_available:
            self._logger.error("Playwright未安装，无法启动浏览器")
            return False

        try:
            extension_source_path = (Path(__file__).parent.parent / "browser_extension").resolve()
            extension_path_str = validate_extension_path(str(extension_source_path))
            extension_path = prepare_extension_bundle(Path(extension_path_str))

            self._logger.info(f"启动浏览器，加载插件: {extension_path}")

            self._playwright_context = async_playwright_factory()
            self._playwright = await self._playwright_context.__aenter__()

            persistent_user_data = self._unified_config.get(
                "recording.persistent_user_data", default=True
            )
            user_data_dir_config = self._unified_config.get("recording.user_data_dir", default=None)

            if persistent_user_data:
                if user_data_dir_config:
                    user_data_dir = Path(user_data_dir_config)
                    self._logger.info(f"使用自定义持久化 user_data_dir: {user_data_dir}")
                else:
                    user_data_dir = self.storage_path.parent / "playwright_user_data_persistent"
                    self._logger.info(
                        f"使用默认持久化 user_data_dir: {user_data_dir} (保留登录状态)"
                    )
            else:
                unique_id = str(uuid.uuid4())[:8]
                user_data_dir = self.storage_path.parent / f"playwright_user_data_{unique_id}"
                self._logger.info(f"使用临时 user_data_dir: {user_data_dir} (录制结束后不保留)")
            user_data_dir.mkdir(parents=True, exist_ok=True)

            if persistent_user_data and user_data_dir.exists():
                extensions_dir = user_data_dir / "Default" / "Extensions"
                if extensions_dir.exists():
                    has_our_extension = False
                    for ext_dir in extensions_dir.iterdir():
                        if not ext_dir.is_dir():
                            continue

                        manifest_file = ext_dir / "manifest.json"
                        if not manifest_file.exists():
                            continue

                        try:
                            with open(manifest_file, "r", encoding="utf-8") as handle:
                                manifest = json.load(handle)
                            if manifest.get("name") == "Mexemplar Recorder":
                                has_our_extension = True
                                self._logger.info(f"发现已安装的扩展: {ext_dir.name}")
                                break
                        except (json.JSONDecodeError, IOError, OSError) as exc:
                            self._logger.debug(
                                f"跳过损坏的扩展目录: {ext_dir.name}, 错误: {exc}"
                            )

                    if not has_our_extension:
                        self._logger.warning(f"持久化目录中未找到扩展，清理重建: {user_data_dir}")
                        shutil.rmtree(user_data_dir)
                        user_data_dir.mkdir(parents=True, exist_ok=True)
                        self._logger.info("持久化目录已重建，扩展将被重新加载")

            self._user_data_dir = user_data_dir

            self._logger.info("使用 Chromium 启动浏览器（Chrome 通道不支持通过命令行加载扩展）")
            extension_path_final = Path(extension_path).resolve().as_posix()
            self._logger.info(f"扩展路径: {extension_path_final}")
            self._logger.info("使用 Playwright Chromium 启动浏览器（持久化模式 + 异步 API）")

            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=False,
                accept_downloads=True,
                ignore_default_args=["--enable-automation", "--disable-extensions"],
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
            self._browser = getattr(self._context, "browser", None)

            self._logger.info("浏览器已启动（持久化模式，扩展已加载）")

            ws_host = self._unified_config.get_websocket_host()
            ws_port = self._unified_config.get_websocket_port()
            max_body_size = self._unified_config.get_websocket_max_response_body_size()
            init_script = f"""
            Object.defineProperty(navigator, 'webdriver', {{ get: () => undefined }});
            window.MEXEMPLAR_CONFIG = {{
                websocketUrl: 'ws://{ws_host}:{ws_port}',
                recordingId: '{recording_id}',
                maxResponseBodySize: {max_body_size},
                version: '1.0'
            }};
            if (typeof window !== 'undefined' && window.MEXEMPLAR_DEBUG) {{
                console.log('[Mexemplar] 配置已通过 CDP 注入:', window.MEXEMPLAR_CONFIG);
            }}
            """
            await self._context.add_init_script(init_script)
            self._logger.info(f"[CDP] 已注入配置到所有页面: ws://{ws_host}:{ws_port}")
            self._logger.info(f"[CDP] 最大响应体大小: {max_body_size / 1024 / 1024:.1f} MB")

            def handle_new_page(page) -> None:
                self._logger.debug(f"检测到新页面创建，初始 URL: {page.url}")
                with self._pages_lock:
                    if page not in self._pages:
                        self._pages.append(page)

                async def wait_for_page_load():
                    try:
                        await page.wait_for_load_state("domcontentloaded", timeout=10000)
                        self._logger.debug(f"新页面 DOM 已加载: {page.url}")
                        await page.wait_for_load_state("load", timeout=10000)
                        self._logger.debug(f"新页面完全加载成功: {page.url}")
                    except Exception as exc:
                        self._logger.warning(f"新页面加载失败: {exc}, URL: {page.url}")

                asyncio.create_task(wait_for_page_load())

            self._context.on("page", handle_new_page)
            self._logger.info("已注册新页面监听器（支持 target='_blank' popup 页面，异步 API）")

            def check_new_pages() -> None:
                with self._pages_lock:
                    last_page_count = len(self._pages)
                while self._context is not None:
                    try:
                        current_pages = self._context.pages
                        current_page_count = len(current_pages)
                        if current_page_count > last_page_count:
                            self._logger.info(
                                f"[POLLED] 发现新页面！总数: {last_page_count} → {current_page_count}"
                            )
                            for page in current_pages:
                                with self._pages_lock:
                                    if page not in self._pages:
                                        self._logger.info(f"[POLLED] 发现未跟踪的页面: {page.url}")
                                        self._pages.append(page)
                            last_page_count = current_page_count
                        time.sleep(5)
                    except Exception as exc:
                        self._logger.debug(f"[POLLED] 检查页面时出错: {exc}")
                        time.sleep(1)

            threading.Thread(target=check_new_pages, daemon=True).start()
            self._logger.info("已启动页面定期检查线程（兜底方案）")
            self._logger.info("Chromium 启动成功（支持扩展加载）")

            existing_pages = self._context.pages
            if existing_pages:
                self._page = existing_pages[0]
                with self._pages_lock:
                    self._pages.append(self._page)
                self._logger.info(f"使用默认页面，URL: {self._page.url}")
            else:
                self._page = await self._context.new_page()
                with self._pages_lock:
                    self._pages.append(self._page)
                self._logger.info(f"创建新页面，URL: {self._page.url}")

            if start_url:
                await self._page.goto(start_url, wait_until="domcontentloaded", timeout=30000)
            else:
                self._logger.info("未提供起始 URL，浏览器保持在空白页")

            try:
                await self._page.wait_for_load_state("load", timeout=5000)
            except Exception as exc:
                self._logger.debug(f"等待load状态超时，继续执行: {exc}")

            self._logger.info("正在检查扩展加载状态...")
            extension_loaded = False
            extension_signals: List[str] = []

            try:
                extensions = list(self._context.background_pages)
                if extensions:
                    self._logger.info(f"检测到 {len(extensions)} 个扩展已加载")
                    for index, ext in enumerate(extensions, 1):
                        ext_url = ext.url if hasattr(ext, "url") else "unknown"
                        self._logger.info(f"  扩展 {index}: {ext_url}")
                    extension_loaded = True
                    extension_signals.append("background_page")
                else:
                    self._logger.info(
                        "未检测到扩展的background page（Manifest V3使用service worker，这是正常的）"
                    )

                cdp_session = None
                try:
                    cdp_session = await self._context.new_cdp_session(self._page)
                    all_targets: List[Dict[str, Any]] = []
                    target_types: Dict[str, int] = {}
                    extension_targets: List[Dict[str, Any]] = []
                    extension_service_workers: List[Dict[str, Any]] = []

                    for attempt in range(1, 4):
                        targets_result = await cdp_session.send("Target.getTargets")
                        all_targets = targets_result.get("targetInfos", [])
                        self._logger.info(
                            f"通过CDP检测到 {len(all_targets)} 个targets（第{attempt}/3次）"
                        )

                        target_types = {}
                        for target in all_targets:
                            target_type = target.get("type", "unknown")
                            target_types[target_type] = target_types.get(target_type, 0) + 1

                        classified_targets = classify_extension_targets(all_targets)
                        extension_targets = classified_targets["extension_targets"]
                        extension_service_workers = classified_targets[
                            "extension_service_workers"
                        ]

                        if extension_targets:
                            break

                        if attempt < 3:
                            await sleep_coro(0.5)

                    if extension_service_workers:
                        self._logger.info(
                            f"通过CDP检测到 {len(extension_service_workers)} 个扩展service worker（扩展background script）"
                        )
                        for index, target in enumerate(extension_service_workers, 1):
                            self._logger.info(
                                f"  Service Worker {index}: {target.get('url', 'unknown')}"
                            )
                        extension_loaded = True
                        extension_signals.append("cdp_extension_service_worker")
                    elif extension_targets:
                        self._logger.info(
                            f"通过CDP检测到 {len(extension_targets)} 个chrome-extension targets（未发现service worker，可能处于空闲）"
                        )
                        for index, target in enumerate(extension_targets, 1):
                            self._logger.info(
                                "  Extension Target "
                                f"{index}: type={target.get('type', 'unknown')}, "
                                f"url={target.get('url', 'unknown')}"
                            )
                        extension_loaded = True
                        extension_signals.append("cdp_extension_target")
                    else:
                        self._logger.warning(
                            "启动阶段未通过CDP检测到 chrome-extension:// targets（Manifest V3 service worker 可能延迟激活）"
                        )
                        self._logger.warning("将继续等待 WebSocket 连接确认扩展状态")

                    self._logger.debug(f"Target类型统计: {target_types}")
                except Exception as exc:
                    self._logger.warning(f"通过CDP检查扩展失败: {exc}")
                finally:
                    if cdp_session is not None:
                        try:
                            await cdp_session.detach()
                        except Exception as detach_error:
                            self._logger.debug(f"关闭CDP会话失败: {detach_error}")
            except Exception as exc:
                self._logger.warning(f"检查扩展加载状态失败: {exc}")

            if not extension_loaded:
                self._logger.warning("⚠ 启动阶段暂未确认扩展已加载")
                self._logger.warning("  Manifest V3 service worker 可能延迟激活，这是常见现象")
                self._logger.warning(f"  扩展路径: {extension_path}")
                self._logger.warning("  后续将以 WebSocket 握手结果作为最终确认")
            else:
                self._logger.info(f"扩展加载检查完成（检测信号: {', '.join(extension_signals)}）")

            self._logger.info("浏览器启动成功")
            return True
        except Exception as exc:
            self._logger.error(f"启动浏览器失败: {exc}", exc_info=True)
            if self._context is None:
                self.cleanup_playwright_extension_bundle()
            return False

    def prepare_playwright_extension_bundle(
        self,
        extension_source_path: Path,
        *,
        recording_id: Optional[str],
    ) -> Path:
        self.cleanup_playwright_extension_bundle()

        launch_token = str(uuid.uuid4())
        bundle_root = self.storage_path.parent / "playwright_extension_bundles"
        bundle_root.mkdir(parents=True, exist_ok=True)

        bundle_path = bundle_root / launch_token
        shutil.copytree(extension_source_path, bundle_path)

        launch_context = {
            "client_kind": "playwright_background",
            "launch_token": launch_token,
            "recording_id": recording_id,
        }
        (bundle_path / "launch_context.js").write_text(
            "self.MEXEMPLAR_LAUNCH_CONTEXT = "
            + json.dumps(launch_context, ensure_ascii=True, indent=2)
            + ";\n",
            encoding="utf-8",
        )

        self._playwright_launch_token = launch_token
        self._playwright_extension_bundle_path = bundle_path
        self._logger.info(f"[BrowserRecorder] 已生成 Playwright 扩展副本: {bundle_path}")
        return bundle_path

    def cleanup_playwright_extension_bundle(self) -> None:
        if self._playwright_extension_bundle_path and self._playwright_extension_bundle_path.exists():
            try:
                shutil.rmtree(self._playwright_extension_bundle_path)
            except Exception as exc:
                self._logger.warning(f"清理 Playwright 扩展副本失败: {exc}")

        self._playwright_extension_bundle_path = None
        self._playwright_launch_token = None

    def cleanup_user_data_dir(self) -> None:
        if not self._user_data_dir:
            return

        is_temp_dir = "playwright_user_data_" in str(self._user_data_dir)
        is_temp_dir = is_temp_dir and "_persistent" not in str(self._user_data_dir)
        persistent_user_data = self._unified_config.get(
            "recording.persistent_user_data", default=True
        )

        if not persistent_user_data and is_temp_dir and self._user_data_dir.exists():
            try:
                shutil.rmtree(self._user_data_dir)
                self._logger.info(f"已清理临时用户数据目录: {self._user_data_dir}")
            except Exception as exc:
                self._logger.warning(f"清理临时目录失败: {exc}")

        self._user_data_dir = None

    async def close_browser(
        self,
        *,
        suppress_logs: Callable[[], Any],
    ) -> None:
        with suppress_logs():
            if self._pages:
                for page in list(self._pages):
                    try:
                        if not page.is_closed():
                            await page.close()
                    except Exception:
                        pass
                self._pages.clear()

            self._page = None

            if self._context:
                try:
                    await self._context.close()
                except Exception:
                    pass
                self._context = None

            if self._playwright_context:
                try:
                    await self._playwright_context.__aexit__(None, None, None)
                except Exception:
                    pass
                self._playwright_context = None

            self._playwright = None
            self._browser = None
            self._playwright_ws_client = None

    @staticmethod
    def classify_extension_targets(
        all_targets: List[Dict[str, Any]],
    ) -> Dict[str, List[Dict[str, Any]]]:
        extension_targets: List[Dict[str, Any]] = []
        extension_service_workers: List[Dict[str, Any]] = []

        for target in all_targets:
            target_url = target.get("url")
            if not (isinstance(target_url, str) and target_url.startswith("chrome-extension://")):
                continue

            extension_targets.append(target)
            if target.get("type") == "service_worker":
                extension_service_workers.append(target)

        return {
            "extension_targets": extension_targets,
            "extension_service_workers": extension_service_workers,
        }

    @staticmethod
    def validate_extension_path(extension_path: str) -> str:
        path = Path(extension_path).resolve()

        if not path.exists():
            raise ValueError(f"扩展路径不存在: {path}")
        if not path.is_dir():
            raise ValueError(f"扩展路径必须是目录: {path}")

        project_root = Path(__file__).parent.parent.parent.parent.resolve()
        try:
            path.relative_to(project_root)
        except ValueError:
            logging.getLogger(__name__).warning(f"扩展路径不在项目目录内: {path}")

        return str(path)

    @staticmethod
    @contextmanager
    def suppress_playwright_logs():
        playwright_logger = logging.getLogger("playwright")
        original_level = playwright_logger.level
        try:
            playwright_logger.setLevel(logging.CRITICAL + 1)
            yield
        finally:
            playwright_logger.setLevel(original_level)
