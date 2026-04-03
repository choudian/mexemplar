"""
内置通用工具

助理 Agent 始终可用的通用工具，包括：
- web_search: 网页搜索
- web_fetch: 抓取网页内容
- read_file: 读本地文件
- write_file: 写本地文件（高危，需用户确认）
- edit_file: 编辑本地文件（局部替换）
- list_dir: 列目录
- exec: 执行 shell 命令（高危，白名单限制）

注：cron、image_generate、browser、image、pdf、memory_search 在后续 Step 实现。
"""

import json
import logging
import subprocess
import threading
from html.parser import HTMLParser
from pathlib import Path
from typing import List

from src.business.agents.config import ToolDefinition

logger = logging.getLogger(__name__)

# exec 安全白名单（无需用户确认即可执行的命令）
EXEC_SAFE_COMMANDS = frozenset([
    "dir", "ls", "ls -la", "ls -l", "ls -a",
    "pwd", "echo", "type", "cat",
    "ping", "ipconfig", "ifconfig",
    "python --version", "python3 --version",
    "pip list", "pip3 list",
    "date", "time", "whoami", "hostname",
    "tasklist", "ps", "ps aux",
])

# =========================================================================
# 用户确认机制（高危工具，线程安全）
# 每个 worker 线程用独立的 threading.Event 等待，结果按 request_id 隔离。
# =========================================================================

_confirm_signal = None  # pyqtSignal(str, str)，(request_id, message)
_pending_confirms: dict = {}  # request_id → {"event": Event, "result": bool}
_confirm_lock = threading.Lock()


def register_confirm_mechanism(signal):
    """
    注入跨线程确认信号（由 MainWindow 在初始化时调用）。

    Args:
        signal: pyqtSignal(str, str)，emit(request_id, message) 后 UI 线程弹框
    """
    global _confirm_signal
    _confirm_signal = signal


def set_confirm_result(request_id: str, result: bool):
    """UI 线程设置确认结果并唤醒对应的 worker 线程"""
    with _confirm_lock:
        pending = _pending_confirms.get(request_id)
    if pending:
        pending["result"] = result
        pending["event"].set()


def _ask_user_confirm(message: str) -> bool:
    """
    请求用户确认高危操作（线程安全，支持多 worker 并发）。

    每次请求生成唯一 request_id，worker 线程各自阻塞在独立的 Event 上。
    """
    if _confirm_signal is None:
        logger.warning("[builtin_tools] 确认机制未注册，拒绝高危操作")
        return False

    import uuid
    request_id = str(uuid.uuid4())
    event = threading.Event()
    with _confirm_lock:
        _pending_confirms[request_id] = {"event": event, "result": False}

    _confirm_signal.emit(request_id, message)
    event.wait(timeout=120)

    with _confirm_lock:
        pending = _pending_confirms.pop(request_id, None)
    return pending["result"] if pending else False


# =========================================================================
# web_search
# =========================================================================

WEB_SEARCH_SCHEMA = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "在网页上搜索信息。返回搜索结果标题和摘要。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词"},
                "num_results": {
                    "type": "integer",
                    "description": "返回结果数量，默认 5",
                },
            },
            "required": ["query"],
        },
    },
}


def web_search_handler(query: str, num_results: int = 5) -> str:
    """使用 DuckDuckGo 进行网页搜索（不需要 API Key）"""
    try:
        from duckduckgo_search import DDGS

        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=num_results):
                results.append({
                    "title": r.get("title", ""),
                    "url": r.get("href", ""),
                    "snippet": r.get("body", ""),
                })
        return json.dumps(
            {"success": True, "results": results, "count": len(results)},
            ensure_ascii=False,
        )
    except ImportError:
        return json.dumps(
            {"success": False, "message": "需要安装 duckduckgo-search：pip install duckduckgo-search"},
            ensure_ascii=False,
        )
    except Exception as e:
        logger.error(f"[web_search] 失败: {e}")
        return json.dumps({"success": False, "message": str(e)}, ensure_ascii=False)


# =========================================================================
# web_fetch
# =========================================================================

WEB_FETCH_SCHEMA = {
    "type": "function",
    "function": {
        "name": "web_fetch",
        "description": "抓取指定网页的文本内容（自动去除 HTML 标签）。",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "要抓取的网页 URL"},
                "max_length": {
                    "type": "integer",
                    "description": "返回内容最大字符数，默认 5000",
                },
            },
            "required": ["url"],
        },
    },
}


def web_fetch_handler(url: str, max_length: int = 5000) -> str:
    """抓取网页文本内容"""
    try:
        import urllib.request

        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            html = resp.read().decode("utf-8", errors="replace")

        text = _extract_text_from_html(html)[:max_length]

        return json.dumps(
            {"success": True, "url": url, "content": text, "truncated": len(text) == max_length},
            ensure_ascii=False,
        )
    except Exception as e:
        logger.error(f"[web_fetch] 失败: {e}")
        return json.dumps({"success": False, "message": str(e)}, ensure_ascii=False)


class _HtmlTextExtractor(HTMLParser):
    """从 HTML 中提取纯文本（去除 script/style/head 标签内容）"""

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "head"):
            self._skip = True

    def handle_endtag(self, tag):
        if tag in ("script", "style", "head"):
            self._skip = False

    def handle_data(self, data):
        if not self._skip:
            stripped = data.strip()
            if stripped:
                self.parts.append(stripped)


def _extract_text_from_html(html: str) -> str:
    parser = _HtmlTextExtractor()
    parser.feed(html)
    return "\n".join(parser.parts)


# =========================================================================
# read_file
# =========================================================================

READ_FILE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "读取本地文件的内容。支持文本文件。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径（绝对路径或相对路径）"},
                "encoding": {
                    "type": "string",
                    "description": "文件编码，默认 utf-8",
                },
                "max_bytes": {
                    "type": "integer",
                    "description": "最多读取字节数，默认 50000",
                },
            },
            "required": ["path"],
        },
    },
}


def read_file_handler(path: str, encoding: str = "utf-8", max_bytes: int = 50000) -> str:
    """读取本地文件"""
    try:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return json.dumps({"success": False, "message": f"文件不存在: {p}"}, ensure_ascii=False)
        if not p.is_file():
            return json.dumps({"success": False, "message": f"不是文件: {p}"}, ensure_ascii=False)

        size = p.stat().st_size
        with open(p, "r", encoding=encoding, errors="replace") as f:
            content = f.read(max_bytes)

        return json.dumps(
            {
                "success": True,
                "path": str(p),
                "content": content,
                "truncated": size > max_bytes,
                "size": size,
            },
            ensure_ascii=False,
        )
    except Exception as e:
        logger.error(f"[read_file] 失败: {e}")
        return json.dumps({"success": False, "message": str(e)}, ensure_ascii=False)


# =========================================================================
# write_file（高危，需用户确认）
# =========================================================================

WRITE_FILE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "write_file",
        "description": "将内容写入本地文件（覆盖写）。写入前会请求用户确认。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径"},
                "content": {"type": "string", "description": "要写入的内容"},
                "encoding": {"type": "string", "description": "文件编码，默认 utf-8"},
            },
            "required": ["path", "content"],
        },
    },
}


def write_file_handler(path: str, content: str, encoding: str = "utf-8") -> str:
    """写入本地文件（需用户确认）"""
    try:
        p = Path(path).expanduser().resolve()

        # 安全检查：禁止写入系统目录
        system_dirs = [Path("C:/Windows"), Path("C:/System32"), Path("/etc"), Path("/usr")]
        for sys_dir in system_dirs:
            try:
                p.relative_to(sys_dir)
                return json.dumps(
                    {"success": False, "message": "禁止写入系统目录"},
                    ensure_ascii=False,
                )
            except ValueError:
                pass

        # 请求用户确认
        confirmed = _ask_user_confirm(f"将向文件写入内容：\n{p}\n\n是否确认？")
        if not confirmed:
            return json.dumps({"success": False, "message": "用户取消了该操作"}, ensure_ascii=False)

        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding=encoding) as f:
            f.write(content)

        return json.dumps(
            {"success": True, "path": str(p), "bytes_written": len(content.encode(encoding))},
            ensure_ascii=False,
        )
    except Exception as e:
        logger.error(f"[write_file] 失败: {e}")
        return json.dumps({"success": False, "message": str(e)}, ensure_ascii=False)


# =========================================================================
# edit_file（局部替换）
# =========================================================================

EDIT_FILE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "edit_file",
        "description": "替换文件中的指定文本片段。精确替换，要求 old_text 在文件中唯一存在。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "文件路径"},
                "old_text": {"type": "string", "description": "要替换的原始文本"},
                "new_text": {"type": "string", "description": "替换后的新文本"},
            },
            "required": ["path", "old_text", "new_text"],
        },
    },
}


def edit_file_handler(path: str, old_text: str, new_text: str) -> str:
    """替换文件中的指定文本"""
    try:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return json.dumps({"success": False, "message": f"文件不存在: {p}"}, ensure_ascii=False)

        content = p.read_text(encoding="utf-8", errors="replace")
        count = content.count(old_text)
        if count == 0:
            return json.dumps({"success": False, "message": "未找到指定文本"}, ensure_ascii=False)
        if count > 1:
            return json.dumps(
                {"success": False, "message": f"文本出现 {count} 次，请提供更多上下文确保唯一性"},
                ensure_ascii=False,
            )

        confirmed = _ask_user_confirm(
            f"将编辑文件：{p}\n替换：{old_text[:80]}...\n为：{new_text[:80]}...\n是否确认？"
        )
        if not confirmed:
            return json.dumps({"success": False, "message": "用户取消了该操作"}, ensure_ascii=False)

        new_content = content.replace(old_text, new_text, 1)
        p.write_text(new_content, encoding="utf-8")
        return json.dumps({"success": True, "path": str(p)}, ensure_ascii=False)
    except Exception as e:
        logger.error(f"[edit_file] 失败: {e}")
        return json.dumps({"success": False, "message": str(e)}, ensure_ascii=False)


# =========================================================================
# list_dir
# =========================================================================

LIST_DIR_SCHEMA = {
    "type": "function",
    "function": {
        "name": "list_dir",
        "description": "列出目录中的文件和子目录。",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "目录路径，默认为当前工作目录",
                },
                "show_hidden": {
                    "type": "boolean",
                    "description": "是否显示隐藏文件，默认 false",
                },
            },
            "required": [],
        },
    },
}


def list_dir_handler(path: str = ".", show_hidden: bool = False) -> str:
    """列出目录内容"""
    try:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return json.dumps({"success": False, "message": f"路径不存在: {p}"}, ensure_ascii=False)
        if not p.is_dir():
            return json.dumps({"success": False, "message": f"不是目录: {p}"}, ensure_ascii=False)

        items = []
        for item in sorted(p.iterdir()):
            if not show_hidden and item.name.startswith("."):
                continue
            items.append({
                "name": item.name,
                "type": "dir" if item.is_dir() else "file",
                "size": item.stat().st_size if item.is_file() else None,
            })

        return json.dumps(
            {"success": True, "path": str(p), "items": items, "count": len(items)},
            ensure_ascii=False,
        )
    except Exception as e:
        logger.error(f"[list_dir] 失败: {e}")
        return json.dumps({"success": False, "message": str(e)}, ensure_ascii=False)


# =========================================================================
# exec（高危，白名单 + 用户确认）
# =========================================================================

EXEC_SCHEMA = {
    "type": "function",
    "function": {
        "name": "exec",
        "description": "执行 shell 命令并返回输出。安全命令（如 ls、dir）无需确认，其他命令需用户确认。",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "要执行的命令"},
                "timeout": {
                    "type": "integer",
                    "description": "超时秒数，默认 30",
                },
            },
            "required": ["command"],
        },
    },
}


def exec_handler(command: str, timeout: int = 30) -> str:
    """执行 shell 命令"""
    try:
        # 检查是否在白名单中
        cmd_lower = command.strip().lower()
        is_safe = any(cmd_lower == safe or cmd_lower.startswith(safe + " ")
                      for safe in EXEC_SAFE_COMMANDS)

        if not is_safe:
            confirmed = _ask_user_confirm(f"将执行以下命令：\n\n{command}\n\n是否确认？")
            if not confirmed:
                return json.dumps({"success": False, "message": "用户取消了该操作"}, ensure_ascii=False)

        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )

        return json.dumps(
            {
                "success": result.returncode == 0,
                "returncode": result.returncode,
                "stdout": result.stdout[:5000],
                "stderr": result.stderr[:2000],
            },
            ensure_ascii=False,
        )
    except subprocess.TimeoutExpired:
        return json.dumps({"success": False, "message": f"命令超时（{timeout}s）"}, ensure_ascii=False)
    except Exception as e:
        logger.error(f"[exec] 失败: {e}")
        return json.dumps({"success": False, "message": str(e)}, ensure_ascii=False)


# =========================================================================
# 工具定义实例
# =========================================================================

BUILTIN_GENERAL_TOOLS: List[ToolDefinition] = [
    ToolDefinition(name="web_search", schema=WEB_SEARCH_SCHEMA, handler=web_search_handler),
    ToolDefinition(name="web_fetch", schema=WEB_FETCH_SCHEMA, handler=web_fetch_handler),
    ToolDefinition(name="read_file", schema=READ_FILE_SCHEMA, handler=read_file_handler),
    ToolDefinition(name="write_file", schema=WRITE_FILE_SCHEMA, handler=write_file_handler),
    ToolDefinition(name="edit_file", schema=EDIT_FILE_SCHEMA, handler=edit_file_handler),
    ToolDefinition(name="list_dir", schema=LIST_DIR_SCHEMA, handler=list_dir_handler),
    ToolDefinition(name="exec", schema=EXEC_SCHEMA, handler=exec_handler),
]

__all__ = [
    "BUILTIN_GENERAL_TOOLS",
    "register_confirm_mechanism",
    "set_confirm_result",
    "web_search_handler",
    "web_fetch_handler",
    "read_file_handler",
    "write_file_handler",
    "edit_file_handler",
    "list_dir_handler",
    "exec_handler",
]
