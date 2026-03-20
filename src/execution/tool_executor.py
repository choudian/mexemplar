"""
工具执行引擎

负责在独立线程+事件循环中执行工具代码（async def execute(**kwargs)）。
与 code_executor.py（数据探索，同步）完全独立，互不影响。
"""

import asyncio
import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

_TOOL_TIMEOUT = 120  # 秒，浏览器操作预留充足时间


def run_tool_code(code: str, parameters: dict) -> dict:
    """
    执行工具代码，返回标准结果字典。

    工具代码格式：
        async def execute(**kwargs) -> Dict[str, Any]:
            return {"success": True/False, "message": "...", "data": ...}

    Args:
        code: 工具完整 Python 源码
        parameters: 传给 execute() 的参数字典

    Returns:
        {"success": bool, "message": str, "data": Any}
        执行失败时 success=False，message 包含错误信息
    """
    result_holder: dict[str, Any] = {"output": None, "error": None}

    def _run():
        try:
            # 编译并在独立命名空间执行，获得 execute 函数
            namespace: dict[str, Any] = {}
            exec(compile(code, "<tool>", "exec"), namespace)  # noqa: S102

            execute_fn = namespace.get("execute")
            if execute_fn is None:
                result_holder["error"] = "工具代码中未找到 execute 函数"
                return

            # 在新事件循环中运行（避免与主线程事件循环冲突）
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                output = loop.run_until_complete(execute_fn(**parameters))
                result_holder["output"] = output
            finally:
                loop.close()
                asyncio.set_event_loop(None)

        except Exception as e:
            result_holder["error"] = f"{type(e).__name__}: {e}"

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=_TOOL_TIMEOUT)

    if thread.is_alive():
        return {
            "success": False,
            "message": f"工具执行超时（超过 {_TOOL_TIMEOUT} 秒）",
            "data": None,
        }

    if result_holder["error"]:
        logger.error(f"[ToolExecutor] 工具执行失败: {result_holder['error']}")
        return {
            "success": False,
            "message": result_holder["error"],
            "data": None,
        }

    output = result_holder["output"]

    # 兼容性处理：确保返回值符合标准格式
    if isinstance(output, dict):
        return output
    return {"success": True, "message": "执行完成", "data": output}
