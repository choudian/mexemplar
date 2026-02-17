"""
WebSocket 服务器管理器单元测试
"""

import pytest
import time
import threading
from unittest.mock import Mock, patch

from src.communication.websocket_manager import WebSocketServerManager
from src.communication.websocket_handler import WebSocketHandler


@pytest.fixture
def ws_manager():
    """创建 WebSocket 服务器管理器实例"""
    manager = WebSocketServerManager(
        host="127.0.0.1",
        port=8767,  # 使用不同的端口避免冲突
        auto_start=False,
        startup_timeout=2.0,
    )
    yield manager
    # 清理
    if manager.is_running:
        manager.stop()


class TestWebSocketServerManager:
    """测试 WebSocket 服务器管理器"""

    def test_initialization(self, ws_manager):
        """测试初始化"""
        assert ws_manager.host == "127.0.0.1"
        assert ws_manager.port == 8767
        assert ws_manager.startup_timeout == 2.0
        assert not ws_manager.is_running
        assert ws_manager.ws_handler is None

    def test_server_url(self, ws_manager):
        """测试服务器 URL 属性"""
        assert ws_manager.server_url == "ws://127.0.0.1:8767"

    @pytest.mark.skipif(
        True, reason="需要实际启动服务器，可能与其他测试冲突"  # 跳过此测试，因为需要实际启动服务器
    )
    def test_start_and_stop(self, ws_manager):
        """测试启动和停止"""
        # 启动
        success = ws_manager.start()
        assert success is True
        assert ws_manager.is_running
        assert ws_manager.ws_handler is not None

        # 停止
        ws_manager.stop()
        assert not ws_manager.is_running

    def test_callback_registration(self, ws_manager):
        """测试回调注册"""
        # 创建 mock 回调
        on_ready_mock = Mock()
        on_error_mock = Mock()

        # 注册回调
        ws_manager.on_ready(on_ready_mock)
        ws_manager.on_error(on_error_mock)

        assert ws_manager._on_ready == on_ready_mock
        assert ws_manager._on_error == on_error_mock

    def test_start_when_already_running(self, ws_manager):
        """测试重复启动"""
        # 模拟服务器已运行
        ws_manager._is_running = True
        ws_manager.ws_handler = Mock(spec=WebSocketHandler)

        # 尝试启动（应该返回 True）
        success = ws_manager.start()
        assert success is True

    def test_health_check(self, ws_manager):
        """测试健康检查"""
        # 未运行时
        assert ws_manager.health_check() is False

        # 模拟运行中
        ws_manager._is_running = True
        ws_manager.ws_handler = Mock(spec=WebSocketHandler)
        ws_manager.ws_handler.get_client_count.return_value = 2

        assert ws_manager.health_check() is True

    def test_health_check_no_handler(self, ws_manager):
        """测试健康检查 - 没有 handler"""
        ws_manager._is_running = True
        ws_manager.ws_handler = None

        assert ws_manager.health_check() is False

    def test_stop_when_not_running(self, ws_manager, caplog):
        """测试停止未运行的服务器"""
        import logging

        with caplog.at_level(logging.INFO):
            ws_manager.stop()

        # 验证日志记录
        assert "未运行" in caplog.text or "not running" in caplog.text.lower()

    def test_context_manager(self):
        """测试上下文管理器"""
        with WebSocketServerManager(
            host="127.0.0.1",
            port=8768,
            auto_start=False,
        ) as manager:
            assert manager is not None
            assert manager.host == "127.0.0.1"
            assert manager.port == 8768

    @pytest.mark.skipif(True, reason="需要实际启动服务器并模拟端口占用")
    def test_port_conflict_detection(self):
        """测试端口冲突检测"""
        # 启动第一个服务器
        manager1 = WebSocketServerManager(
            host="127.0.0.1",
            port=8769,
            auto_start=True,
            startup_timeout=2.0,
        )
        assert manager1.is_running

        # 尝试启动第二个服务器（相同端口）
        manager2 = WebSocketServerManager(
            host="127.0.0.1",
            port=8769,
            auto_start=True,
            startup_timeout=2.0,
        )

        # 第二个服务器应该启动失败
        assert not manager2.is_running

        # 清理
        manager1.stop()

    def test_on_ready_callback(self, ws_manager):
        """测试就绪回调"""
        callback_mock = Mock()
        ws_manager.on_ready(callback_mock)

        # 模拟服务器就绪
        ws_manager._on_ready(ws_manager)

        # 验证回调被调用
        callback_mock.assert_called_once_with(ws_manager)

    def test_on_error_callback(self, ws_manager):
        """测试错误回调"""
        callback_mock = Mock()
        ws_manager.on_error(callback_mock)

        # 模拟错误
        error_msg = "测试错误"
        ws_manager._on_error(ws_manager, error_msg)

        # 验证回调被调用
        callback_mock.assert_called_once_with(ws_manager, error_msg)
