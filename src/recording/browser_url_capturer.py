"""
浏览器URL捕获模块

用于在录制过程中捕获浏览器地址栏的URL和被点击元素的URL
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class BrowserURLCapturer:
    """浏览器URL捕获器"""

    def __init__(self):
        """初始化浏览器URL捕获器"""
        self._pywinauto_available = False

        # 尝试导入pywinauto
        try:
            from pywinauto import Application

            self.Application = Application
            self._pywinauto_available = True
            logger.debug("pywinauto可用，将尝试使用浏览器URL捕获功能")
        except ImportError:
            logger.debug("pywinauto不可用，浏览器URL捕获功能受限")

    def get_browser_url(
        self, process_id: Optional[int], process_name: Optional[str] = None
    ) -> Optional[str]:
        """
        获取浏览器当前URL

        Args:
            process_id: 浏览器进程ID
            process_name: 进程名（如chrome.exe）

        Returns:
            当前URL，如果无法获取则返回None
        """
        if not process_id:
            return None

        # 使用pywinauto获取地址栏内容
        if self._pywinauto_available:
            url = self._get_url_via_pywinauto(process_id)
            if url:
                return url

        # 尝试从窗口标题提取URL（备用方法）
        url_from_title = self._extract_url_from_window_title(process_id)
        if url_from_title:
            return url_from_title

        return None

    def _get_url_via_pywinauto(self, process_id: int) -> Optional[str]:
        """
        通过pywinauto获取浏览器地址栏内容

        这是最可行的方法，支持Chrome和Edge
        """
        try:
            from pywinauto import Application

            # 连接到浏览器进程
            app = Application(backend="uia").connect(process=process_id)

            # 查找主窗口
            # Chrome/Edge的窗口类名通常是Chrome_WidgetWin_1
            try:
                # 尝试获取窗口对象
                windows = app.windows()
                if not windows:
                    return None

                # 通常第一个窗口是主窗口
                main_window = windows[0]

                # Chrome/Edge地址栏的AutomationId通常是"地址和搜索栏"或"address and search bar"
                # 也可能是"Address and search bar"（英文）
                address_bar_candidates = [
                    "地址和搜索栏",
                    "address and search bar",
                    "Address and search bar",
                    "地址栏",
                    "address bar",
                    "Address bar",
                ]

                for candidate_id in address_bar_candidates:
                    try:
                        # 尝试通过AutomationId查找
                        address_bar = main_window.child_window(
                            auto_id=candidate_id, control_type="Edit"
                        )
                        if address_bar.exists():
                            url = address_bar.get_value()
                            if url and (url.startswith("http://") or url.startswith("https://")):
                                return url
                    except Exception:
                        continue

                # 如果通过AutomationId找不到，尝试查找所有Edit控件
                # 通常地址栏是第一个Edit控件
                try:
                    edit_controls = main_window.descendants(control_type="Edit")
                    for edit in edit_controls:
                        try:
                            value = edit.get_value()
                            if value and (
                                value.startswith("http://") or value.startswith("https://")
                            ):
                                return value
                        except Exception:
                            continue
                except Exception:
                    pass

            except Exception as e:
                logger.debug(f"通过pywinauto获取地址栏失败: {e}")
                return None

        except Exception as e:
            logger.debug(f"pywinauto连接浏览器失败 (PID: {process_id}): {e}")
            return None

        return None

    def _extract_url_from_window_title(self, process_id: int) -> Optional[str]:
        """
        从窗口标题中提取URL（如果标题包含URL信息）

        注意：大多数浏览器不会在窗口标题中显示完整URL
        此方法主要用于处理特殊情况
        """
        try:
            import win32gui
            import win32process

            # 获取进程的所有窗口
            windows = []

            def enum_windows_callback(hwnd, _):
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if pid == process_id:
                    title = win32gui.GetWindowText(hwnd)
                    if title:
                        windows.append(title)

            win32gui.EnumWindows(enum_windows_callback, None)

            # 检查标题中是否包含URL模式
            for title in windows:
                # 检查是否包含http://或https://
                if "http://" in title or "https://" in title:
                    # 尝试提取URL部分
                    import re

                    url_pattern = r"https?://[^\s]+"
                    match = re.search(url_pattern, title)
                    if match:
                        return match.group(0)
        except Exception as e:
            logger.debug(f"从窗口标题提取URL失败: {e}")

        return None

