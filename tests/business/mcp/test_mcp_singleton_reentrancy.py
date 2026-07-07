"""MCP 单例入口的可重入死锁回归测试。

根因：`get_mcp_server_service()` 和 `get_mcp_tool_registry()` 共用同一把
非可重入 `_singleton_lock`；而 `McpServerService.__init__` 在持锁期间又调
`get_mcp_tool_registry()`。当 `get_mcp_server_service()` 是进程里第一个 MCP
触点（两个单例都是 None）时，同线程重入同一把锁 → 永久死锁。

这正是孤立运行 `tests/desktop_api/test_app_startup.py` 时挂死的原因：lifespan
的 `get_mcp_server_service()` 是该进程首个 MCP 调用。

用线程 + join 超时把"永久挂起"转成"超时即失败"，避免测试本身挂死。
"""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest

from src.business.mcp import (
    get_mcp_server_service,
    get_mcp_tool_registry,
    reset_mcp_singletons,
)

_JOIN_TIMEOUT_SECONDS = 10.0


@pytest.fixture(autouse=True)
def _fresh_mcp_singletons():
    """每个用例前后都清空 MCP 单例，保证"首个触点"语义且不污染其他测试。"""
    reset_mcp_singletons()
    yield
    reset_mcp_singletons()


def _run_with_timeout(target) -> None:
    """在子线程里跑 target，join 超时未完成即判定死锁。"""
    result: dict[str, object] = {}

    def _worker():
        result["value"] = target()

    thread = threading.Thread(target=_worker, daemon=True)
    thread.start()
    thread.join(timeout=_JOIN_TIMEOUT_SECONDS)
    assert not thread.is_alive(), (
        "MCP 单例初始化在 %.0f 秒内未完成——疑似 _singleton_lock 可重入死锁" % _JOIN_TIMEOUT_SECONDS
    )
    assert result.get("value") is not None


def test_server_service_is_first_mcp_touch_does_not_deadlock():
    """get_mcp_server_service() 作为进程首个 MCP 调用时不得死锁。"""
    with patch("src.business.mcp.mcp_server_service.McpProcessManager", MagicMock()):
        _run_with_timeout(get_mcp_server_service)


def test_tool_registry_first_then_server_service():
    """先取 registry 再取 service（另一种顺序）同样不得死锁。"""
    with patch("src.business.mcp.mcp_server_service.McpProcessManager", MagicMock()):
        _run_with_timeout(get_mcp_tool_registry)
        _run_with_timeout(get_mcp_server_service)


def test_singletons_are_stable_across_calls():
    """修复不得破坏单例语义：同一入口多次调用返回同一实例。"""
    with patch("src.business.mcp.mcp_server_service.McpProcessManager", MagicMock()):
        first = get_mcp_server_service()
        second = get_mcp_server_service()
        assert first is second
        assert get_mcp_tool_registry() is get_mcp_tool_registry()
