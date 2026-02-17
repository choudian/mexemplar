"""
QThread 后台执行功能测试

测试工具执行线程和进度对话框
"""

import pytest
import time
from unittest.mock import Mock, patch

from PyQt6.QtCore import QMutex, QMutexLocker
from PyQt6.QtWidgets import QApplication

from src.ui.tool_execution_thread import ToolExecutionThread, ToolExecutionProgressDialog
from src.data.models import Tool


@pytest.fixture(scope="module")
def qapp():
    """创建 QApplication 实例"""
    app = QApplication.instance()
    if app is None:
        import sys
        app = QApplication(sys.argv)
    yield app
    # 不要退出 QApplication


class TestToolExecutionThread:
    """ToolExecutionThread 测试"""

    @pytest.fixture
    def mock_tool(self):
        """创建模拟工具"""
        return Tool(
            tool_id="test_tool",
            tool_name="测试工具",
            description="测试工具描述",
            parameters=[],
            execution_code='def execute_tool():\n    return {"result": "success"}',
            execution_strategy="api",
        )

    def test_thread_initialization(self, mock_tool):
        """测试线程初始化"""
        thread = ToolExecutionThread(mock_tool, {})

        assert thread.tool == mock_tool
        assert thread.parameters == {}
        assert not thread.is_cancelled()

    def test_thread_cancel(self, mock_tool):
        """测试取消线程"""
        thread = ToolExecutionThread(mock_tool, {})

        assert not thread.is_cancelled()
        thread.cancel()
        assert thread.is_cancelled()

    def test_thread_execution_with_simple_code(self, qapp, mock_tool):
        """测试简单代码的执行"""
        thread = ToolExecutionThread(mock_tool, {})

        # 记录信号
        started_signals = []
        progress_signals = []
        finished_signals = []

        thread.started_signal.connect(lambda: started_signals.append(True))
        thread.progress_signal.connect(lambda msg, pct: progress_signals.append((msg, pct)))
        thread.finished_signal.connect(lambda success, result, error: finished_signals.append((success, result, error)))

        # 运行线程
        thread.start()
        thread.wait(timeout=5000)  # 等待最多 5 秒

        # 验证结果
        assert len(started_signals) >= 1
        assert len(finished_signals) == 1
        assert len(progress_signals) >= 1

        success, result, error = finished_signals[0]
        assert success is True
        assert result is not None
        assert error == ""

    def test_thread_execution_with_error(self, qapp):
        """测试执行出错的代码"""
        error_tool = Tool(
            tool_id="error_tool",
            tool_name="错误工具",
            description="会抛出错误的工具",
            parameters=[],
            execution_code='def execute_tool():\n    raise ValueError("Test error")',
            execution_strategy="api",
        )

        thread = ToolExecutionThread(error_tool, {})

        # 记录信号
        error_signals = []
        finished_signals = []

        thread.error_signal.connect(lambda msg: error_signals.append(msg))
        thread.finished_signal.connect(lambda success, result, error: finished_signals.append((success, result, error)))

        # 运行线程
        thread.start()
        thread.wait(timeout=5000)

        # 验证结果
        assert len(finished_signals) == 1
        success, result, error = finished_signals[0]
        assert success is False
        assert error is not None

    def test_thread_get_result(self, qapp, mock_tool):
        """测试获取执行结果"""
        thread = ToolExecutionThread(mock_tool, {})

        # 运行线程
        thread.start()
        thread.wait(timeout=5000)

        # 获取结果
        success, result, error = thread.get_result()
        assert success is True
        assert result is not None


class TestToolExecutionProgressDialog:
    """ToolExecutionProgressDialog 测试"""

    @pytest.fixture
    def mock_tool(self):
        """创建模拟工具"""
        return Tool(
            tool_id="test_tool",
            tool_name="测试工具",
            description="测试工具描述",
            parameters=[],
            execution_code='def execute_tool():\n    return {"result": "success"}',
            execution_strategy="api",
        )

    def test_dialog_initialization(self, qapp, mock_tool):
        """测试对话框初始化"""
        dialog = ToolExecutionProgressDialog("测试工具")

        assert dialog.tool_name == "测试工具"
        assert dialog.dialog is not None
        assert dialog.dialog.windowTitle() == "执行工具: 测试工具"

    def test_dialog_with_thread(self, qapp, mock_tool):
        """测试对话框与线程的集成"""
        # 创建线程
        thread = ToolExecutionThread(mock_tool, {})

        # 创建对话框
        dialog = ToolExecutionProgressDialog("测试工具")
        dialog.set_execution_thread(thread)

        assert dialog.execution_thread == thread

    def test_dialog_get_result(self, qapp, mock_tool):
        """测试通过对话框获取结果"""
        # 创建并运行线程
        thread = ToolExecutionThread(mock_tool, {})
        thread.start()
        thread.wait(timeout=5000)

        # 创建对话框
        dialog = ToolExecutionProgressDialog("测试工具")
        dialog.execution_thread = thread

        # 获取结果
        success, result, error = dialog.get_result()
        assert success is True
        assert result is not None


class TestIntegrationScenarios:
    """集成测试场景"""

    @pytest.fixture
    def mock_tool(self):
        """创建模拟工具"""
        return Tool(
            tool_id="test_tool",
            tool_name="测试工具",
            description="测试工具描述",
            parameters=[],
            execution_code='def execute_tool():\n    import time\n    time.sleep(0.1)\n    return {"result": "success"}',
            execution_strategy="api",
        )

    def test_complete_execution_flow(self, qapp, mock_tool):
        """测试完整的执行流程"""
        # 创建线程
        thread = ToolExecutionThread(mock_tool, {})

        # 创建进度对话框
        progress_dialog = ToolExecutionProgressDialog(mock_tool.tool_name)
        progress_dialog.set_execution_thread(thread)

        # 记录进度
        progress_updates = []
        progress_dialog.progress_signal.connect(
            lambda msg, pct: progress_updates.append((msg, pct))
        )

        # 启动执行
        thread.start()
        thread.wait(timeout=5000)

        # 验证进度更新
        assert len(progress_updates) >= 1
        assert progress_updates[-1][1] == 100  # 最后一个应该是 100%

        # 验证结果
        success, result, error = thread.get_result()
        assert success is True
        assert result["result"] == "success"

    def test_execution_with_parameters(self, qapp):
        """测试带参数的执行"""
        tool_with_params = Tool(
            tool_id="param_tool",
            tool_name="参数工具",
            description="接受参数的工具",
            parameters=[
                {"name": "name", "type": "text", "description": "名称", "required": True},
            ],
            execution_code='def execute_tool(name="World"):\n    return {"greeting": f"Hello, {name}!"}',
            execution_strategy="api",
        )

        thread = ToolExecutionThread(tool_with_params, {"name": "Claude"})
        thread.start()
        thread.wait(timeout=5000)

        success, result, error = thread.get_result()
        assert success is True
        assert result["greeting"] == "Hello, Claude!"

    def test_concurrent_executions(self, qapp):
        """测试并发执行多个工具"""
        tools = []
        threads = []

        # 创建 3 个工具和线程
        for i in range(3):
            tool = Tool(
                tool_id=f"tool_{i}",
                tool_name=f"工具{i}",
                description=f"工具{i}描述",
                parameters=[],
                execution_code=f'def execute_tool():\n    import time\n    time.sleep(0.05)\n    return {{"result": "success_{i}"}}',
                execution_strategy="api",
            )
            tools.append(tool)

            thread = ToolExecutionThread(tool, {})
            threads.append(thread)

        # 同时启动所有线程
        for thread in threads:
            thread.start()

        # 等待所有线程完成
        for thread in threads:
            thread.wait(timeout=5000)

        # 验证所有线程都成功完成
        for i, thread in enumerate(threads):
            success, result, error = thread.get_result()
            assert success is True, f"Thread {i} failed"
            assert result is not None
