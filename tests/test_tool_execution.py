"""
测试工具执行功能

测试内容：
1. 工具执行对话框
2. 工具执行器
3. 执行结果对话框
"""

import sys
import pytest
from datetime import datetime
from PyQt6.QtWidgets import QApplication

from src.data.models import Tool
from src.ui.tool_execution_dialog import ToolExecutionDialog, ToolExecutor, ExecutionResultDialog
from src.execution.code_executor import CodeExecutor


class TestToolExecution:
    """测试工具执行功能"""

    @pytest.fixture(autouse=True)
    def setup_qt(self):
        """设置 Qt 应用"""
        if not QApplication.instance():
            app = QApplication(sys.argv)
        else:
            app = QApplication.instance()
        yield app

    def test_tool_executor_with_code(self):
        """测试工具执行器（带执行代码）"""
        # 创建测试工具
        tool = Tool(
            tool_name="测试工具",
            description="这是一个测试工具",
            execution_code="""
def execute_tool():
    return {"status": "success", "message": "Hello, World!"}
""",
            parameters=[],
            source="manual",
        )

        # 创建执行器
        executor = ToolExecutor()

        # 执行工具
        success, result, error = executor.execute_tool(tool, {})

        # 验证结果
        assert success is True
        assert error is None
        assert result is not None
        print(f"✅ 工具执行成功，结果: {result}")

    def test_tool_executor_with_parameters(self):
        """测试工具执行器（带参数）"""
        # 创建测试工具（带参数）
        tool = Tool(
            tool_name="参数测试工具",
            description="测试参数传递",
            execution_code="""
def execute_tool(name, count):
    return {"message": f"Hello {name}!", "count": count}
""",
            parameters=[
                {"name": "name", "type": "text", "description": "名称", "default": "World"},
                {"name": "count", "type": "number", "description": "次数", "default": "1"},
            ],
            source="manual",
        )

        # 创建执行器
        executor = ToolExecutor()

        # 执行工具（带参数）
        parameters = {"name": "Alice", "count": 5}
        success, result, error = executor.execute_tool(tool, parameters)

        # 验证结果
        assert success is True
        assert error is None
        assert result["message"] == "Hello Alice!"
        assert result["count"] == 5
        print(f"✅ 带参数工具执行成功，结果: {result}")

    def test_code_executor_directly(self):
        """直接测试 CodeExecutor"""
        executor = CodeExecutor()

        # 测试代码
        code = """
def execute_tool():
    return {"status": "ok", "data": [1, 2, 3]}
"""

        # 执行代码
        result = executor.execute(code, {})

        # 验证结果
        assert result["success"] is True
        assert result["result"]["status"] == "ok"
        assert result["result"]["data"] == [1, 2, 3]
        print(f"✅ CodeExecutor 执行成功，结果: {result}")

    def test_execution_result_dialog_success(self, qtbot):
        """测试执行结果对话框（成功）"""
        dialog = ExecutionResultDialog(
            tool_name="测试工具",
            success=True,
            result={"message": "执行成功！"},
            parent=None,
        )

        # 显示对话框
        dialog.show()
        qtbot.addWidget(dialog)

        # 验证对话框标题
        assert "执行成功" in dialog.windowTitle()
        print("✅ 执行结果对话框（成功）测试通过")

    def test_execution_result_dialog_failure(self, qtbot):
        """测试执行结果对话框（失败）"""
        dialog = ExecutionResultDialog(
            tool_name="测试工具",
            success=False,
            error="执行失败：网络错误",
            parent=None,
        )

        # 显示对话框
        dialog.show()
        qtbot.addWidget(dialog)

        # 验证对话框标题
        assert "执行失败" in dialog.windowTitle()
        print("✅ 执行结果对话框（失败）测试通过")


if __name__ == "__main__":
    # 运行测试
    pytest.main([__file__, "-v", "-s"])
