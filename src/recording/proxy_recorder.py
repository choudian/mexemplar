"""
代理录制器模块。

用 mitmproxy 拦截 HTTP/HTTPS 请求，转成 browser_action JSONL 写入队列文件。
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from pathlib import Path
from typing import List, Optional

from src.data.unified_config import get_unified_config

from .system_proxy import SystemProxyManager

logger = logging.getLogger(__name__)

try:
    from mitmproxy import options
    from mitmproxy.tools.dump import DumpMaster

    MITMPROXY_AVAILABLE = True
except ImportError:  # pragma: no cover - 依赖缺失时兜底
    options = None
    DumpMaster = None
    MITMPROXY_AVAILABLE = False
    logger.warning("mitmproxy 未安装，代理录制功能不可用")


class RecordingAddon:
    """mitmproxy addon：将完整请求/响应写入 JSONL 队列文件。"""

    def __init__(
        self,
        recording_id: str,
        queue_file: Path,
        ignore_hosts: Optional[List[str]] = None,
        max_body_size: int = 5 * 1024 * 1024,
        queue_write_lock: Optional[threading.Lock] = None,
    ) -> None:
        self.recording_id = recording_id
        self.queue_file = Path(queue_file)
        self.queue_file.parent.mkdir(parents=True, exist_ok=True)
        self.ignore_hosts = set(ignore_hosts or ["127.0.0.1", "localhost"])
        self.max_body_size = max_body_size
        self.queue_write_lock = queue_write_lock

    def response(self, flow) -> None:
        """mitmproxy 在收到完整响应后调用。"""
        try:
            host = getattr(flow.request, "host", "")
            if host in self.ignore_hosts:
                return

            record = {
                "type": "browser_action",
                "recording_id": self.recording_id,
                "action": {
                    "action_type": "network_request",
                    "url": getattr(flow.request, "url", ""),
                    "timestamp": getattr(flow.request, "timestamp_start", time.time()),
                    "parameters": {
                        "method": getattr(flow.request, "method", "GET"),
                        "request_type": "proxy",
                        "request_headers": dict(getattr(flow.request, "headers", {}) or {}),
                        "request_body": self._decode_body(getattr(flow.request, "content", b"")),
                        "response_status": getattr(flow.response, "status_code", None),
                        "response_headers": dict(getattr(flow.response, "headers", {}) or {}),
                        "response_body": self._decode_body(getattr(flow.response, "content", b"")),
                    },
                    "network_requests": [],
                    "dom_element": None,
                },
                "timestamp": time.time(),
            }

            if self.queue_write_lock:
                with self.queue_write_lock:
                    with open(self.queue_file, "a", encoding="utf-8") as handle:
                        handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            else:
                with open(self.queue_file, "a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as exc:
            logger.error(f"[Proxy] 写入队列文件失败: {exc}")

    def _decode_body(self, body: bytes) -> Optional[str]:
        if body is None:
            return None
        if len(body) > self.max_body_size:
            body = body[: self.max_body_size]
        return body.decode("utf-8", errors="replace")


def _remove_mitmproxy_log_handlers() -> None:
    """移除 mitmproxy 安装到 root logger 的日志 handler。

    DumpMaster 构造时会注册一个全局 handler，其 emit() 依赖
    master.event_loop.call_soon_threadsafe()。若 event_loop 缺失，
    所有日志调用（包括无关模块）都会崩溃。主动移除以避免污染。
    """
    root = logging.getLogger()
    for handler in root.handlers[:]:
        if type(handler).__module__ and "mitmproxy" in type(handler).__module__:
            root.removeHandler(handler)


class ProxyRecorder:
    """封装 mitmproxy 生命周期和系统代理设置。"""

    def __init__(self, host: Optional[str] = None, port: Optional[int] = None) -> None:
        config = get_unified_config()
        self.host = host or config.get_proxy_host()
        self.port = port or config.get_proxy_port()
        self._master: Optional["DumpMaster"] = None
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._addon: Optional[RecordingAddon] = None
        self._system_proxy = SystemProxyManager()

    def start(self, recording_id: str, queue_file: Path, queue_write_lock: Optional[threading.Lock] = None) -> bool:
        """启动 mitmproxy 并启用系统代理。"""
        if not MITMPROXY_AVAILABLE:
            logger.error("[Proxy] mitmproxy 未安装")
            return False

        self._addon = RecordingAddon(recording_id=recording_id, queue_file=queue_file, queue_write_lock=queue_write_lock)
        ready = threading.Event()
        errors: List[Exception] = []

        def run_proxy() -> None:
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)

            async def _init_and_run() -> None:
                opts = options.Options(listen_host=self.host, listen_port=self.port)
                self._master = DumpMaster(
                    opts, with_termlog=False, with_dumper=False,
                )
                self._master.addons.add(self._addon)
                ready.set()
                _remove_mitmproxy_log_handlers()
                await self._master.run()

            try:
                self._loop.run_until_complete(_init_and_run())
            except Exception as exc:
                _remove_mitmproxy_log_handlers()
                errors.append(exc)
                if not ready.is_set():
                    ready.set()

        self._thread = threading.Thread(target=run_proxy, daemon=True)
        self._thread.start()
        ready.wait(timeout=5)

        if errors:
            logger.error(f"[Proxy] 启动失败: {errors[0]}")
            self._reset_runtime_state()
            return False

        try:
            self._system_proxy.enable(self.host, self.port)
        except Exception as exc:
            logger.error(f"[Proxy] 设置系统代理失败: {exc}")
            try:
                self._system_proxy.disable()
            except Exception as rollback_exc:
                logger.warning(f"[Proxy] 回滚系统代理失败: {rollback_exc}")
            finally:
                self._shutdown_master()
                self._reset_runtime_state()
            return False

        logger.info(f"[Proxy] 已启动: {self.host}:{self.port}")
        return True

    def stop(self) -> None:
        """停止 mitmproxy 并还原系统代理。"""
        try:
            self._system_proxy.disable()
        finally:
            self._shutdown_master()
            self._reset_runtime_state()
            logger.info("[Proxy] 已停止")

    def _shutdown_master(self) -> None:
        if self._master and self._loop:
            try:
                self._loop.call_soon_threadsafe(self._master.shutdown)
            except Exception as exc:
                logger.warning(f"[Proxy] 停止 mitmproxy 失败: {exc}")

        if self._thread:
            self._thread.join(timeout=5)

    def _reset_runtime_state(self) -> None:
        self._master = None
        self._thread = None
        self._loop = None
