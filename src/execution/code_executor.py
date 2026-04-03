# ⚠️ TODO: 执行引擎正在开发中
# 代码执行器 - 安全执行 LLM 生成的 Python 代码

"""
代码执行器

安全执行 LLM 生成的 Python 代码
"""

import logging
import sys
import traceback
import re
from typing import Dict, Any, Optional
from pathlib import Path
import tempfile


logger = logging.getLogger(__name__)


class CodeExecutor:
    """
    代码执行器

    安全地执行 LLM 生成的 Python 代码
    """

    # ⚡ 允许导入的模块白名单（根据安全改进建议更新）
    ALLOWED_MODULES = {
        # ✅ 标准库（安全模块）
        "json",
        "re",
        "datetime",
        "time",
        "typing",
        "dataclasses",
        "enum",
        "collections",
        "itertools",
        "math",
        "random",
        "string",
        # ❌ 移除危险模块：os, pathlib, subprocess, shutil
        # ✅ 数据验证
        "pydantic",
        "pydantic.dataclasses",
        # ✅ 浏览器自动化
        "playwright",
        "playwright.sync_api",
        # ✅ 数据处理（只读）
        "csv",
        "xml.etree.ElementTree",
        "html",
        # ✅ 类型检查
        "typing_extensions",
        # ✅ HTTP 请求（仅读取）
        "requests",
        "urllib.parse",
        "urllib.request",
    }

    # ⚡ 禁止使用的函数和属性（黑名单）
    BLACKLISTED_NAMES = {
        "eval",
        # 移除 "exec" 因为 "execute_tool" 包含它，使用正则表达式精确匹配
        "compile",
        "__import__",
        "open",
        "file",
        "input",
        "exit",
        "quit",
        "globals",
        "locals",
        "vars",
        "getattr",
        "setattr",
        "delattr",
        "hasattr",
        "dir",
    }

    # ⚡ 禁止的正则表达式模式（根据安全改进建议）
    FORBIDDEN_PATTERNS = [
        r"\bimport\s+os\b",  # 禁止导入 os
        r"\bimport\s+subprocess\b",  # 禁止导入 subprocess
        r"\bfrom\s+os\s+import",
        r"\bfrom\s+subprocess\s+import",
        r"\bexec\s*\(",  # 禁止 exec 函数（但不匹配 execute_tool）
        r"\beval\s*\(",  # 禁止 eval 函数
        r"\.remove\s*\(",  # 禁止文件删除
        r"\.unlink\s*\(",  # 禁止文件删除
        r"\.rmdir\s*\(",  # 禁止目录删除
        r"\.mkdir\s*\(",  # 禁止目录创建（简单检查）
        r"\bmakedirs\s*\(",  # 禁止递归目录创建
        r"^\s*open\s*\(",  # 禁止 open 函数（行首）
        r"__builtins__",  # 禁止访问内置函数字典
        r"__import__\s*\(",  # 禁止动态导入
    ]

    def __init__(self, timeout: int = 30):
        """
        初始化执行器

        Args:
            timeout: 执行超时时间（秒）
        """
        self.timeout = timeout

    def execute(self, code: str, parameters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        执行代码

        Args:
            code: 要执行的 Python 代码
            parameters: 传递给 execute_tool 函数的参数

        Returns:
            执行结果
            {
                'success': bool,
                'result': Any,
                'error': str (失败时),
                'output': str (标准输出),
            }
        """
        parameters = parameters or {}

        # 1. 代码安全检查
        is_safe, error = self._check_code_safety(code)
        if not is_safe:
            return {
                "success": False,
                "error": f"代码安全检查失败: {error}",
                "output": "",
            }

        # 2. 准备执行环境
        exec_globals = self._prepare_exec_globals()

        # 3. 捕获标准输出
        import io
        from contextlib import redirect_stdout

        output_buffer = io.StringIO()

        try:
            # 4. 执行代码定义
            with redirect_stdout(output_buffer):
                exec(code, exec_globals)

            # 5. 调用 execute_tool 函数
            if "execute_tool" not in exec_globals:
                return {
                    "success": False,
                    "error": "代码中没有定义 execute_tool 函数",
                    "output": output_buffer.getvalue(),
                }

            execute_tool = exec_globals["execute_tool"]

            # 6. 调用函数
            with redirect_stdout(output_buffer):
                result = execute_tool(**parameters)

            # 7. 返回结果
            return {
                "success": True,
                "result": result,
                "output": output_buffer.getvalue(),
            }

        except Exception as e:
            error_msg = f"执行错误: {type(e).__name__}: {str(e)}"
            logger.error(f"{error_msg}\n{traceback.format_exc()}")

            return {
                "success": False,
                "error": error_msg,
                "output": output_buffer.getvalue(),
            }

    def _check_code_safety(self, code: str) -> tuple[bool, Optional[str]]:
        """
        检查代码安全性

        Args:
            code: 要检查的代码

        Returns:
            (是否安全, 错误信息)
        """
        # 1. 检查正则表达式模式（新增）
        for pattern in self.FORBIDDEN_PATTERNS:
            if re.search(pattern, code):
                return False, f"禁止使用的模式: {pattern}"

        # 2. 检查黑名单关键词
        for blacklisted in self.BLACKLISTED_NAMES:
            if blacklisted in code:
                return False, f"禁止使用 {blacklisted}"

        # 3. 检查导入语句
        import ast

        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            return False, f"语法错误: {e}"

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    module_name = alias.name.split(".")[0]
                    if module_name not in self.ALLOWED_MODULES:
                        return False, f"不允许导入模块: {module_name}"

            elif isinstance(node, ast.ImportFrom):
                module_name = node.module.split(".")[0] if node.module else ""
                if module_name not in self.ALLOWED_MODULES:
                    return False, f"不允许导入模块: {module_name}"

        return True, None

    def _validate_temp_file(self, temp_file: str) -> Path:
        """
        验证临时文件路径安全性（防止路径遍历攻击）

        Args:
            temp_file: 待验证的临时文件路径

        Returns:
            验证后的Path对象

        Raises:
            ValueError: 如果路径不安全
        """
        path = Path(temp_file)

        if not path.is_absolute():
            raise ValueError("临时文件必须是绝对路径")

        # 必须在系统临时目录内
        system_temp = Path(tempfile.gettempdir()).resolve()
        try:
            path.relative_to(system_temp)
        except ValueError:
            raise ValueError(f"临时文件必须在系统临时目录内: {path}")

        if path.suffix != '.py':
            raise ValueError(f"临时文件必须是 .py 文件: {path}")

        return path

    def _prepare_exec_globals(self) -> Dict[str, Any]:
        """
        准备执行环境（全局变量）

        Returns:
            全局变量字典
        """
        # 基础环境
        exec_globals = {
            "__builtins__": {
                "print": print,
                "len": len,
                "str": str,
                "int": int,
                "float": float,
                "bool": bool,
                "list": list,
                "dict": dict,
                "tuple": tuple,
                "set": set,
                "range": range,
                "enumerate": enumerate,
                "zip": zip,
                "map": map,
                "filter": filter,
                "sum": sum,
                "min": min,
                "max": max,
                "abs": abs,
                "round": round,
                "any": any,
                "all": all,
                "sorted": sorted,
                "reversed": reversed,
                "isinstance": isinstance,
                "issubclass": issubclass,
                "type": type,
                "Exception": Exception,
                "ValueError": ValueError,
                "TypeError": TypeError,
                "KeyError": KeyError,
                "IndexError": IndexError,
                "__import__": __import__,  # 允许 import 语句工作，但通过 AST 检查监控
            }
        }

        # 导入允许的模块
        for module_name in self.ALLOWED_MODULES:
            try:
                # 直接使用 __import__ 导入模块
                exec_globals[module_name] = __import__(module_name)
            except ImportError:
                # 模块不存在，跳过
                pass

        return exec_globals


class CodeExecutorSandbox(CodeExecutor):
    """
    代码执行器沙箱（更严格的安全限制）

    使用临时文件和进程隔离来执行代码
    """

    def execute(self, code: str, parameters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        在沙箱中执行代码

        使用临时文件和 subprocess 来隔离执行环境
        """
        import subprocess
        import json

        parameters = parameters or {}

        # 1. 代码安全检查
        is_safe, error = self._check_code_safety(code)
        if not is_safe:
            return {
                "success": False,
                "error": f"代码安全检查失败: {error}",
                "output": "",
            }

        # 2. 准备执行脚本
        script_template = """
import json
import sys

# 代码定义
{code}

# 调用函数
if __name__ == '__main__':
    params = json.loads('''{params}''')
    result = execute_tool(**params)
    print(json.dumps(result))
"""

        # 格式化代码（移除缩进）
        import textwrap

        code_dedented = textwrap.dedent(code)

        script = script_template.format(code=code_dedented, params=json.dumps(parameters))

        # 3. 写入临时文件
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            temp_file = f.name
            f.write(script)

        try:
            # 4. 验证临时文件路径安全性
            validated_temp_file = self._validate_temp_file(temp_file)

            # 5. 执行脚本
            result = subprocess.run(
                [sys.executable, str(validated_temp_file)],
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )

            # 6. 验证输出大小（防止DoS攻击）
            MAX_OUTPUT_SIZE = 10 * 1024 * 1024  # 10MB
            if len(result.stdout) > MAX_OUTPUT_SIZE or len(result.stderr) > MAX_OUTPUT_SIZE:
                raise ValueError("执行输出过大，可能存在异常")

            # 7. 解析结果
            if result.returncode == 0:
                try:
                    output = json.loads(result.stdout.strip())
                    return {
                        "success": True,
                        "result": output,
                        "output": result.stderr,
                    }
                except json.JSONDecodeError:
                    return {
                        "success": False,
                        "error": f"无法解析输出: {result.stdout}",
                        "output": result.stderr,
                    }
            else:
                return {
                    "success": False,
                    "error": f"执行失败 (退出码: {result.returncode}): {result.stderr}",
                    "output": result.stderr,
                }

        except subprocess.TimeoutExpired:
            return {
                "success": False,
                "error": f"执行超时 (>{self.timeout}秒)",
                "output": "",
            }
        finally:
            # 6. 清理临时文件
            try:
                Path(temp_file).unlink()
            except Exception:
                pass
