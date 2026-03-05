"""
测试独立脚本执行功能

测试工具执行器通过 subprocess 独立执行脚本的能力。
"""

import pytest
import tempfile
import json
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from src.data.models import Tool
from src.ui.tool_execution_dialog import ToolExecutor


class TestStandaloneScriptExecution:
    """测试独立脚本执行"""

    def test_standalone_script_execution_success(self):
        """测试独立脚本成功执行"""
        execution_code = '''
# -*- coding: utf-8 -*-
import asyncio
import json
import sys

async def execute(**kwargs):
    """测试执行函数"""
    return {
        "success": True,
        "message": "测试成功",
        "data": {"key": "value"}
    }

if __name__ == '__main__':
    result = asyncio.run(execute())
    print(json.dumps(result, ensure_ascii=False))
'''

        tool = Tool(
            tool_id="test-001",
            tool_name="测试工具",
            description="测试独立脚本执行",
            execution_code=execution_code,
            parameters=[],
            code_language="python",
        )

        executor = ToolExecutor()

        # 使用 mock 来模拟 subprocess.run
        with patch('subprocess.run') as mock_run:
            mock_result = Mock()
            mock_result.returncode = 0
            mock_result.stdout = json.dumps({
                "success": True,
                "message": "测试成功",
                "data": {"key": "value"}
            }, ensure_ascii=False)
            mock_run.return_value = mock_result

            success, result, error = executor.execute_tool(tool, {})

            # 验证结果
            assert success is True
            assert result is not None
            assert result.get("success") is True
            assert error is None

    def test_standalone_script_execution_with_parameters(self):
        """测试带参数的脚本执行"""
        execution_code = '''
# -*- coding: utf-8 -*-
import asyncio
import json
import sys

async def execute(**kwargs):
    """测试执行函数"""
    return {
        "success": True,
        "message": f"收到参数: {kwargs}",
        "data": kwargs
    }

if __name__ == '__main__':
    params = {}
    for arg in sys.argv[1:]:
        if '=' in arg:
            key, value = arg.split('=', 1)
            params[key] = value
    result = asyncio.run(execute(**params))
    print(json.dumps(result, ensure_ascii=False))
'''

        tool = Tool(
            tool_id="test-002",
            tool_name="参数测试工具",
            description="测试参数传递",
            execution_code=execution_code,
            parameters=[
                {"name": "url", "type": "text", "required": True},
                {"name": "timeout", "type": "number", "required": False},
            ],
            code_language="python",
        )

        executor = ToolExecutor()

        with patch('subprocess.run') as mock_run:
            mock_result = Mock()
            mock_result.returncode = 0
            mock_result.stdout = json.dumps({
                "success": True,
                "message": "收到参数",
                "data": {"url": "https://example.com", "timeout": "10"}
            }, ensure_ascii=False)
            mock_run.return_value = mock_result

            success, result, error = executor.execute_tool(
                tool,
                {"url": "https://example.com", "timeout": 10}
            )

            # 验证 subprocess 被调用
            assert mock_run.called
            # 验证参数传递
            args, kwargs = mock_run.call_args
            assert "url=https://example.com" in args[0]
            assert "timeout=10" in args[0]

            assert success is True
            assert result is not None

    def test_script_execution_with_error(self):
        """测试脚本执行错误处理"""
        execution_code = '''
# -*- coding: utf-8 -*-
import asyncio
import json

async def execute(**kwargs):
    raise ValueError("测试错误")

if __name__ == '__main__':
    try:
        result = asyncio.run(execute())
        print(json.dumps(result, ensure_ascii=False))
    except Exception as e:
        print(json.dumps({"success": False, "message": str(e)}, ensure_ascii=False))
'''

        tool = Tool(
            tool_id="test-003",
            tool_name="错误测试工具",
            description="测试错误处理",
            execution_code=execution_code,
            parameters=[],
            code_language="python",
        )

        executor = ToolExecutor()

        with patch('subprocess.run') as mock_run:
            mock_result = Mock()
            mock_result.returncode = 0
            mock_result.stdout = json.dumps({
                "success": False,
                "message": "测试错误"
            }, ensure_ascii=False)
            mock_run.return_value = mock_result

            success, result, error = executor.execute_tool(tool, {})

            # 应该捕获错误
            assert success is False
            assert result is not None
            assert result.get("success") is False

    def test_script_execution_return_code_error(self):
        """测试脚本返回非零退出码"""
        execution_code = '''
import sys
sys.exit(1)
'''

        tool = Tool(
            tool_id="test-004",
            tool_name="退出码测试工具",
            description="测试非零退出码",
            execution_code=execution_code,
            parameters=[],
            code_language="python",
        )

        executor = ToolExecutor()

        with patch('subprocess.run') as mock_run:
            mock_result = Mock()
            mock_result.returncode = 1
            mock_result.stderr = "脚本错误"
            mock_result.stdout = ""
            mock_run.return_value = mock_result

            success, result, error = executor.execute_tool(tool, {})

            assert success is False
            assert error is not None
            assert "脚本错误" in error or "未知错误" in error

    def test_script_execution_timeout(self):
        """测试脚本执行超时"""
        execution_code = '''
import time
time.sleep(600)  # 超过超时时间
'''

        tool = Tool(
            tool_id="test-005",
            tool_name="超时测试工具",
            description="测试超时处理",
            execution_code=execution_code,
            parameters=[],
            code_language="python",
        )

        executor = ToolExecutor()

        with patch('subprocess.run') as mock_run:
            from subprocess import TimeoutExpired
            mock_run.side_effect = TimeoutExpired("python", 300)

            success, result, error = executor.execute_tool(tool, {})

            assert success is False
            assert error == "执行超时"

    def test_script_execution_invalid_json(self):
        """测试脚本输出无效 JSON"""
        execution_code = '''
# -*- coding: utf-8 -*-
import asyncio

async def execute(**kwargs):
    return "这不是有效的 JSON"

if __name__ == '__main__':
    result = asyncio.run(execute())
    print(result)  # 直接打印字符串，不是 JSON
'''

        tool = Tool(
            tool_id="test-006",
            tool_name="无效JSON测试工具",
            description="测试无效JSON输出",
            execution_code=execution_code,
            parameters=[],
            code_language="python",
        )

        executor = ToolExecutor()

        with patch('subprocess.run') as mock_run:
            mock_result = Mock()
            mock_result.returncode = 0
            mock_result.stdout = "这不是有效的 JSON"
            mock_run.return_value = mock_result

            success, result, error = executor.execute_tool(tool, {})

            assert success is False
            assert error is not None
            assert "无法解析输出" in error

    def test_script_with_browser_operations(self):
        """测试包含浏览器操作的脚本"""
        execution_code = '''
# -*- coding: utf-8 -*-
import asyncio
import json
import sys
from playwright.async_api import async_playwright

async def execute(**kwargs):
    result = {"success": False, "message": "", "data": None}

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        page = await browser.new_page()

        try:
            url = kwargs.get("url", "https://example.com")
            await page.goto(url)
            title = await page.title()

            result["success"] = True
            result["message"] = "导航成功"
            result["data"] = {"title": title}
        except Exception as e:
            result["message"] = f"执行错误: {str(e)}"
        finally:
            await browser.close()

    return result

if __name__ == '__main__':
    params = {}
    for arg in sys.argv[1:]:
        if '=' in arg:
            key, value = arg.split('=', 1)
            params[key] = value

    result = asyncio.run(execute(**params))
    print(json.dumps(result, ensure_ascii=False))
'''

        tool = Tool(
            tool_id="test-007",
            tool_name="浏览器测试工具",
            description="测试浏览器操作",
            execution_code=execution_code,
            parameters=[
                {"name": "url", "type": "url", "required": True},
            ],
            code_language="python",
        )

        executor = ToolExecutor()

        with patch('subprocess.run') as mock_run:
            mock_result = Mock()
            mock_result.returncode = 0
            mock_result.stdout = json.dumps({
                "success": True,
                "message": "导航成功",
                "data": {"title": "Example Domain"}
            }, ensure_ascii=False)
            mock_run.return_value = mock_result

            success, result, error = executor.execute_tool(
                tool,
                {"url": "https://example.com"}
            )

            assert success is True
            assert result is not None
            assert result.get("success") is True
            assert result.get("data", {}).get("title") == "Example Domain"


class TestToolExecutorIntegration:
    """测试 ToolExecutor 集成"""

    def test_execute_tool_with_no_code(self):
        """测试没有执行代码的工具"""
        tool = Tool(
            tool_id="test-008",
            tool_name="无代码工具",
            description="没有执行代码",
            execution_code=None,
            steps=[],
            code_language="python",
        )

        executor = ToolExecutor()
        success, result, error = executor.execute_tool(tool, {})

        assert success is False
        assert error is not None
        assert "没有执行代码" in error or "步骤定义" in error

    def test_execute_tool_with_steps(self):
        """测试有步骤的工具（需要 WorkflowExecutor 集成）"""
        tool = Tool(
            tool_id="test-009",
            tool_name="步骤工具",
            description="有步骤定义",
            execution_code=None,
            steps=[
                {"action_type": "navigate", "parameters": {"url": "https://example.com"}}
            ],
            code_language="python",
        )

        executor = ToolExecutor()
        success, result, error = executor.execute_tool(tool, {})

        # 当前 WorkflowExecutor 未集成，应该返回错误
        assert success is False
        assert error is not None
        assert "WorkflowExecutor" in error

    def test_execute_tool_exception_handling(self):
        """测试执行工具时的异常处理"""
        tool = Tool(
            tool_id="test-010",
            tool_name="异常测试工具",
            description="测试异常处理",
            execution_code="invalid code",
            parameters=[],
            code_language="python",
        )

        executor = ToolExecutor()

        with patch('subprocess.run') as mock_run:
            mock_run.side_effect = Exception("模拟异常")

            success, result, error = executor.execute_tool(tool, {})

            # _execute_standalone_script 内部已经捕获异常
            assert success is False
            assert error is not None
            assert "模拟异常" in error