"""
Windows 系统代理管理器。

通过修改当前用户注册表设置和还原系统代理，使浏览器流量经过本地 mitmproxy。
"""

import ctypes
import logging
from typing import Optional

try:
    import winreg

    WINREG_AVAILABLE = True
except ImportError:  # pragma: no cover - 非 Windows 环境兜底
    winreg = None
    WINREG_AVAILABLE = False

logger = logging.getLogger(__name__)

PROXY_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
INTERNET_OPTION_REFRESH = 37
INTERNET_OPTION_SETTINGS_CHANGED = 39


class SystemProxyManager:
    """Windows 系统代理设置/还原管理器。"""

    def __init__(self) -> None:
        self._original_proxy: Optional[str] = None
        self._was_enabled: bool = False
        self._snapshot_taken: bool = False

    def enable(self, host: str, port: int) -> None:
        """启用系统代理，并记录原始值用于后续恢复。"""
        if not WINREG_AVAILABLE:
            raise RuntimeError("系统代理设置仅支持 Windows")

        proxy_server = f"{host}:{port}"
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            PROXY_KEY_PATH,
            0,
            winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE,
        ) as key:
            self._was_enabled = bool(self._query_value(key, "ProxyEnable", default=0))
            self._original_proxy = self._query_value(key, "ProxyServer", default=None)
            self._snapshot_taken = True

            winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
            winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, proxy_server)

        self._refresh_internet_options()
        logger.info(f"[SystemProxy] 已设置系统代理: {proxy_server}")

    def disable(self) -> None:
        """恢复 enable() 之前的系统代理状态。"""
        if not WINREG_AVAILABLE:
            return

        if not self._snapshot_taken:
            logger.debug("[SystemProxy] 无需还原（没有可恢复的快照）")
            return

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                PROXY_KEY_PATH,
                0,
                winreg.KEY_SET_VALUE,
            ) as key:
                restored_proxy = self._original_proxy or ""
                if self._was_enabled:
                    winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 1)
                else:
                    winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, 0)
                winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, restored_proxy)
            self._refresh_internet_options()
            logger.info("[SystemProxy] 已还原系统代理")
        finally:
            self._snapshot_taken = False
            self._original_proxy = None
            self._was_enabled = False

    @staticmethod
    def _query_value(key, name: str, default):
        try:
            value, _ = winreg.QueryValueEx(key, name)
            return value
        except FileNotFoundError:
            return default

    @staticmethod
    def _refresh_internet_options() -> None:
        wininet = getattr(getattr(ctypes, "windll", None), "wininet", None)
        if wininet is None:
            logger.debug("[SystemProxy] WinINet 不可用，跳过 InternetSetOption 刷新")
            return

        for option in (INTERNET_OPTION_SETTINGS_CHANGED, INTERNET_OPTION_REFRESH):
            result = wininet.InternetSetOptionW(None, option, None, 0)
            if not result:
                raise OSError(f"InternetSetOptionW 失败，option={option}")
