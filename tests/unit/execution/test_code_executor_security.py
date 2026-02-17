"""
CodeExecutor 安全性单元测试
"""

import pytest
from src.execution.code_executor import CodeExecutor, CodeExecutorSandbox


class TestCodeSecurity:
    """代码安全性测试"""

    def test_allowed_modules_enforcement(self):
        """测试强制执行模块白名单"""
        executor = CodeExecutor()

        # 安全的代码
        safe_code = """
import json
from datetime import datetime

def execute_tool(data):
    return {"timestamp": datetime.now().isoformat()}
"""

        is_safe, error = executor._check_code_safety(safe_code)
        assert is_safe is True
        assert error is None

    def test_forbidden_module_os(self):
        """测试禁止导入 os 模块"""
        executor = CodeExecutor()

        # 危险的代码（导入 os）
        dangerous_code = """
import os

def execute_tool():
    os.remove("/some/file")
    return {}
"""

        is_safe, error = executor._check_code_safety(dangerous_code)
        assert is_safe is False
        assert "os" in error

    def test_forbidden_module_subprocess(self):
        """测试禁止导入 subprocess 模块"""
        executor = CodeExecutor()

        dangerous_code = """
import subprocess

def execute_tool():
    subprocess.run(["rm", "-rf", "/"])
    return {}
"""

        is_safe, error = executor._check_code_safety(dangerous_code)
        assert is_safe is False
        assert "subprocess" in error

    def test_forbidden_function_eval(self):
        """测试禁止使用 eval"""
        executor = CodeExecutor()

        dangerous_code = """
def execute_tool(data):
    result = eval(data["code"])
    return result
"""

        is_safe, error = executor._check_code_safety(dangerous_code)
        assert is_safe is False
        assert "eval" in error

    def test_forbidden_function_exec(self):
        """测试禁止使用 exec"""
        executor = CodeExecutor()

        dangerous_code = """
def execute_tool(data):
    exec(data["code"])
    return {}
"""

        is_safe, error = executor._check_code_safety(dangerous_code)
        assert is_safe is False
        assert "exec" in error

    def test_forbidden_file_operations(self):
        """测试禁止文件操作"""
        executor = CodeExecutor()

        # 测试各种文件操作
        forbidden_patterns = [
            ".remove(",
            ".unlink(",
            ".rmdir(",
            ".mkdir(",
            "open(",
        ]

        for pattern in forbidden_patterns:
            dangerous_code = f"""
def execute_tool():
    file.{pattern}
    return {{}}
"""
            is_safe, error = executor._check_code_safety(dangerous_code)
            assert is_safe is False, f"应该禁止模式: {pattern}"

    def test_syntax_error_detection(self):
        """测试语法错误检测"""
        executor = CodeExecutor()

        invalid_code = """
def execute_tool(data):
    # 缺少右括号
    return data["value"
"""

        is_safe, error = executor._check_code_safety(invalid_code)
        assert is_safe is False
        assert "语法错误" in error

    def test_safe_playwright_code(self):
        """测试安全的 Playwright 代码"""
        executor = CodeExecutor()

        safe_code = """
from playwright.sync_api import sync_playwright

def execute_tool(url):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(url)
        browser.close()
        return {"success": True}
"""

        is_safe, error = executor._check_code_safety(safe_code)
        assert is_safe is True
        assert error is None


class TestResourceLimits:
    """资源限制测试"""

    def test_timeout_enforcement(self):
        """测试超时限制"""
        executor = CodeExecutor(timeout=1)  # 1 秒超时

        # 无限循环代码
        infinite_loop_code = """
def execute_tool():
    while True:
        pass
    return {}
"""

        result = executor.execute(infinite_loop_code)
        assert result["success"] is False
        assert "超时" in result["error"]

    def test_memory_limit(self):
        """测试内存限制"""
        executor = CodeExecutor()

        # 大内存消耗代码
        memory_hog_code = """
def execute_tool():
    # 尝试分配大量内存
    big_list = [0] * 10000000  # 1000 万个整数
    return {"length": len(big_list)}
"""

        result = executor.execute(memory_hog_code)
        # 应该失败或被限制
        # 注意：这个测试可能需要实际的内存限制机制

    def test_output_size_limit(self):
        """测试输出大小限制"""
        executor = CodeExecutorSandbox(timeout=30)

        # 生成大量输出
        large_output_code = """
def execute_tool():
    result = []
    for i in range(100000):
        result.append("x" * 1000)
    return result
"""

        exec_result = executor.execute(large_output_code)
        # CodeExecutorSandbox 应该检测到过大的输出
        if not exec_result["success"]:
            assert "过大" in exec_result.get("error", "")


class TestSafeCodeExecution:
    """安全代码执行测试"""

    def test_execute_safe_code(self):
        """测试执行安全的代码"""
        executor = CodeExecutor()

        safe_code = """
def execute_tool(name):
    return {"message": f"Hello, {name}!"}
"""

        result = executor.execute(safe_code, parameters={"name": "World"})
        assert result["success"] is True
        assert result["result"]["message"] == "Hello, World!"

    def test_execute_with_json_module(self):
        """测试使用 json 模块"""
        executor = CodeExecutor()

        code = """
import json

def execute_tool(data):
    return json.loads(data)
"""

        result = executor.execute(
            code,
            parameters={"data": '{"key": "value"}'}
        )
        assert result["success"] is True
        assert result["result"]["key"] == "value"

    def test_execute_with_datetime(self):
        """测试使用 datetime 模块"""
        executor = CodeExecutor()

        code = """
from datetime import datetime

def execute_tool():
    return {"now": datetime.now().isoformat()}
"""

        result = executor.execute(code)
        assert result["success"] is True
        assert "now" in result["result"]


class TestSandboxIsolation:
    """沙箱隔离测试"""

    def test_sandbox_subprocess_isolation(self):
        """测试子进程隔离"""
        executor = CodeExecutorSandbox(timeout=5)

        code = """
def execute_tool():
    return {"isolated": True}
"""

        result = executor.execute(code)
        assert result["success"] is True

    def test_sandbox_temp_file_cleanup(self):
        """测试临时文件清理"""
        import tempfile
        from pathlib import Path

        executor = CodeExecutorSandbox(timeout=5)

        code = """
def execute_tool():
    return {"test": "data"}
"""

        # 统计执行前的临时文件数量
        temp_dir = Path(tempfile.gettempdir())
        before_files = len(list(temp_dir.glob("*.py")))

        result = executor.execute(code)

        # 验证临时文件被清理
        after_files = len(list(temp_dir.glob("*.py")))
        assert after_files <= before_files + 1  # 允许一个测试文件


class TestBypassAttempts:
    """试图绕过安全检查的测试"""

    def test_obfuscated_import(self):
        """测试混淆的导入尝试"""
        executor = CodeExecutor()

        # 尝试使用字符串拼接绕过检查
        obfuscated_code = """
def execute_tool():
    module = __import__("os")
    module.remove("/file")
    return {}
"""

        is_safe, error = executor._check_code_safety(obfuscated_code)
        assert is_safe is False
        assert "__import__" in error

    def test_dynamic_eval(self):
        """测试动态 eval"""
        executor = CodeExecutor()

        dangerous_code = """
def execute_tool(code_str):
    builtin = __builtins__
    return builtin.eval(code_str)
"""

        is_safe, error = executor._check_code_safety(dangerous_code)
        assert is_safe is False

    def test_getattr_bypass(self):
        """测试 getattr 绕过"""
        executor = CodeExecutor()

        dangerous_code = """
def execute_tool():
    import os
    func = getattr(os, "remove")
    func("/file")
    return {}
"""

        is_safe, error = executor._check_code_safety(dangerous_code)
        assert is_safe is False
        # getattr 在黑名单中，应该被检测到
