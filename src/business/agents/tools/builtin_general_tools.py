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
import re
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import List

from src.business.agents.config import ToolDefinition
from src.business.agents.hook_models import PreHookResult, ToolCallContext
from src.business.agents.tool_helpers import make_tool_schema, error_json

logger = logging.getLogger(__name__)

# =============================================================================
# 常量
# =============================================================================

# 用户确认超时（秒）
_CONFIRM_TIMEOUT = 120
CONFIRM_TIMEOUT_MS = _CONFIRM_TIMEOUT * 1000

CONFIRM_DECISION_ACCEPTED = "accepted"
CONFIRM_DECISION_REJECTED = "rejected"
CONFIRM_DECISION_TIMEOUT = "timeout"
CONFIRM_DECISION_AUTO_APPROVED = "auto_approved"
CONFIRM_DECISION_ERROR = "confirm_error"

CONFIRM_SOURCE_TOAST = "toast"
CONFIRM_SOURCE_TOAST_ACCEPT = "toast_accept"
CONFIRM_SOURCE_TOAST_REJECT = "toast_reject"
CONFIRM_SOURCE_TOAST_ALLOW_ALL = "toast_allow_all"
CONFIRM_SOURCE_TOAST_TIMEOUT = "toast_timeout"
CONFIRM_SOURCE_TOP_TOGGLE = "top_toggle"
CONFIRM_SOURCE_AUTO_SCOPE = "auto_scope"
CONFIRM_SOURCE_SYSTEM_ERROR = "system_error"
CONFIRM_SOURCE_NEW_CHAT_RESET = "new_chat_reset"

_SUMMARY_SNIPPET_MAX = 80
_SUMMARY_TOTAL_MAX = 240

# web_fetch 返回内容最大字符数
_WEB_FETCH_MAX_LENGTH = 5000

# read_file 最大读取字节数
_READ_FILE_MAX_BYTES = 50000

# exec 输出截断（stdout / stderr 最大字符数）
_EXEC_STDOUT_MAX = 5000
_EXEC_STDERR_MAX = 2000

# exec 安全白名单（无需用户确认即可执行的命令）
EXEC_SAFE_COMMANDS = frozenset(
    [
        "dir",
        "ls",
        "ls -la",
        "ls -l",
        "ls -a",
        "pwd",
        "echo",
        "type",
        "cat",
        "ping",
        "ipconfig",
        "ifconfig",
        "python --version",
        "python3 --version",
        "pip list",
        "pip3 list",
        "date",
        "time",
        "whoami",
        "hostname",
        "tasklist",
        "ps",
        "ps aux",
    ]
)

# =========================================================================
# 用户确认机制（高危工具，线程安全）
# 每个 worker 线程用独立的 threading.Event 等待，结果按 request_id 隔离。
# =========================================================================

_confirm_signal = None  # pyqtSignal(str, str)，(request_id, message)
_pending_confirms: dict = {}  # request_id → PendingConfirmation
_confirm_lock = threading.Lock()
_auto_approve_enabled = False
_auto_approve_source = "startup_default"


@dataclass
class PendingConfirmation:
    """等待 UI 决策的高危工具确认请求。"""

    request_id: str
    tool_name: str
    summary: str
    created_at: float
    event: threading.Event
    result: bool = False
    decision: str | None = None
    source: str | None = None


def register_confirm_mechanism(signal):
    """
    注入跨线程确认信号（由 MainWindow 在初始化时调用）。

    Args:
        signal: pyqtSignal(str, str)，emit(request_id, message) 后 UI 线程弹框
    """
    global _confirm_signal
    _confirm_signal = signal


def set_confirm_result(
    request_id: str,
    result: bool,
    source: str = CONFIRM_SOURCE_TOAST,
) -> None:
    """UI 线程设置确认结果并唤醒对应的 worker 线程"""
    with _confirm_lock:
        pending = _pending_confirms.get(request_id)
        if pending is None:
            logger.debug("[builtin_tools] 忽略未知确认请求: request_id=%s, source=%s", request_id, source)
            return
        if pending.event.is_set():
            return
        pending.result = result
        pending.source = source
        pending.decision = _decision_from_result_source(result, source)
        pending.event.set()
    _log_confirmation_decision(pending)


def settle_pending_confirmations(
    result: bool,
    source: str,
    created_before: float | None = None,
) -> list[str]:
    """结算仍在等待 UI 决策的确认请求，返回实际触达的 request_id。"""
    with _confirm_lock:
        request_ids = [
            request_id
            for request_id, pending in _pending_confirms.items()
            if not pending.event.is_set()
            and (created_before is None or pending.created_at <= created_before)
        ]

    for request_id in request_ids:
        set_confirm_result(request_id, result, source)
    return request_ids


def get_pending_confirmation(request_id: str) -> PendingConfirmation | None:
    """返回 pending confirmation 的只读元数据引用，供 UI 展示安全摘要。"""
    with _confirm_lock:
        pending = _pending_confirms.get(request_id)
    return pending if isinstance(pending, PendingConfirmation) else None


def get_confirmation_remaining_timeout_ms(request_id: str) -> int | None:
    """返回从 Worker 创建确认请求开始计算的剩余 UI 超时时间。"""
    with _confirm_lock:
        pending = _pending_confirms.get(request_id)
    if not isinstance(pending, PendingConfirmation):
        return None
    if pending.event.is_set():
        return 0
    elapsed_ms = int((time.monotonic() - pending.created_at) * 1000)
    return CONFIRM_TIMEOUT_MS - elapsed_ms


def set_auto_approve_enabled(enabled: bool, source: str) -> None:
    """设置当前进程会话级高危工具自动放行状态。"""
    global _auto_approve_enabled, _auto_approve_source
    with _confirm_lock:
        _auto_approve_enabled = bool(enabled)
        _auto_approve_source = source
    logger.info(
        "[builtin_tools] auth_auto_approve_state=%s source=%s",
        _auto_approve_enabled,
        source,
    )


def is_auto_approve_enabled() -> bool:
    """返回当前会话级自动放行状态。"""
    with _confirm_lock:
        return _auto_approve_enabled


def reset_auto_approve(source: str = CONFIRM_SOURCE_NEW_CHAT_RESET) -> None:
    """复位当前会话级自动放行状态。"""
    set_auto_approve_enabled(False, source)


def reset_confirmation_state_for_tests() -> None:
    """测试用：清空确认状态、pending 请求和自动放行标记。"""
    global _confirm_signal, _auto_approve_enabled, _auto_approve_source
    with _confirm_lock:
        _pending_confirms.clear()
        _auto_approve_enabled = False
        _auto_approve_source = "startup_default"
    _confirm_signal = None


def _ask_user_confirm(message: str, tool_name: str = "unknown") -> bool:
    """
    请求用户确认高危操作（线程安全，支持多 worker 并发）。

    每次请求生成唯一 request_id，worker 线程各自阻塞在独立的 Event 上。
    """
    if _confirm_signal is None:
        logger.warning("[builtin_tools] 确认机制未注册，拒绝高危操作")
        return False

    request_id = str(uuid.uuid4())
    event = threading.Event()
    pending = PendingConfirmation(
        request_id=request_id,
        tool_name=tool_name,
        summary=_truncate_summary(message),
        created_at=time.monotonic(),
        event=event,
    )
    with _confirm_lock:
        _pending_confirms[request_id] = pending

    try:
        _confirm_signal.emit(request_id, message)
        completed = event.wait(timeout=_CONFIRM_TIMEOUT)
    except Exception:
        with _confirm_lock:
            _pending_confirms.pop(request_id, None)
        pending.decision = CONFIRM_DECISION_ERROR
        pending.source = CONFIRM_SOURCE_SYSTEM_ERROR
        pending.result = False
        _log_confirmation_decision(pending)
        raise

    if not completed:
        set_confirm_result(request_id, False, CONFIRM_SOURCE_TOAST_TIMEOUT)

    with _confirm_lock:
        pending = _pending_confirms.pop(request_id, None)
    if isinstance(pending, PendingConfirmation):
        return pending.result
    return False


def _decision_from_result_source(result: bool, source: str) -> str:
    if source in {CONFIRM_SOURCE_TOAST_TIMEOUT, CONFIRM_SOURCE_NEW_CHAT_RESET}:
        return CONFIRM_DECISION_TIMEOUT
    if source in {
        CONFIRM_SOURCE_TOAST_ALLOW_ALL,
        CONFIRM_SOURCE_TOP_TOGGLE,
        CONFIRM_SOURCE_AUTO_SCOPE,
    }:
        return CONFIRM_DECISION_AUTO_APPROVED if result else CONFIRM_DECISION_REJECTED
    return CONFIRM_DECISION_ACCEPTED if result else CONFIRM_DECISION_REJECTED


def _truncate_summary(summary: str, max_len: int = _SUMMARY_TOTAL_MAX) -> str:
    normalized = " ".join(str(summary).split())
    if len(normalized) <= max_len:
        return normalized
    return normalized[: max_len - 3] + "..."


_SENSITIVE_PATTERNS = [
    re.compile(r"(?<!\w)sk-\S+", re.IGNORECASE),
    re.compile(r"api_key=\S+", re.IGNORECASE),
    re.compile(r"token=\S+", re.IGNORECASE),
    re.compile(r"password=\S+", re.IGNORECASE),
    re.compile(r"secret=\S+", re.IGNORECASE),
]
_SENSITIVE_REPLACEMENTS = {
    "sk-": "sk-***",
    "api_key=": "api_key=***",
    "token=": "token=***",
    "password=": "password=***",
    "secret=": "secret=***",
}


def _sanitize_fragment(value: object, max_len: int = _SUMMARY_SNIPPET_MAX) -> str:
    text = " ".join(str(value).replace("\r", "\n").split())
    for pattern in _SENSITIVE_PATTERNS:
        matched = pattern.search(text)
        if matched:
            match_text = matched.group()
            for prefix, replacement in _SENSITIVE_REPLACEMENTS.items():
                if match_text.lower().startswith(prefix):
                    text = text[: matched.start()] + replacement + text[matched.end() :]
                    break
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


def _build_write_summary(path: Path) -> str:
    return _truncate_summary(f"目标文件: {path}")


def _build_edit_summary(path: Path, old_text: str, new_text: str) -> str:
    old_preview = _sanitize_fragment(old_text)
    new_preview = _sanitize_fragment(new_text)
    return _truncate_summary(f"目标文件: {path}; 替换片段: {old_preview}; 新片段: {new_preview}")


def _build_exec_summary(command: str) -> str:
    lines = str(command).splitlines()
    first_line = lines[0] if lines else ""
    return _truncate_summary(f"命令首行: {_sanitize_fragment(first_line, 120)}")


def _log_confirmation_decision(pending: PendingConfirmation) -> None:
    elapsed_ms = max(0, int((time.monotonic() - pending.created_at) * 1000))
    payload = {
        "request_id": pending.request_id,
        "tool_name": pending.tool_name,
        "decision": pending.decision
        or _decision_from_result_source(pending.result, pending.source or CONFIRM_SOURCE_TOAST),
        "source": pending.source or CONFIRM_SOURCE_TOAST,
        "elapsed_ms": elapsed_ms,
        "summary": pending.summary,
    }
    logger.info(
        "[builtin_tools] auth_confirmation_decision %s",
        json.dumps(payload, ensure_ascii=False),
    )


# =========================================================================
# web_search
# =========================================================================

WEB_SEARCH_SCHEMA = make_tool_schema(
    name="web_search",
    description="在网页上搜索信息。返回搜索结果标题和摘要。",
    properties={
        "query": {"type": "string", "description": "搜索关键词"},
        "num_results": {
            "type": "integer",
            "description": "返回结果数量，默认 5",
        },
    },
    required=["query"],
)


def web_search_handler(query: str, num_results: int = 5) -> str:
    """使用 DuckDuckGo 进行网页搜索（不需要 API Key）"""
    try:
        from duckduckgo_search import DDGS

        results = []
        with DDGS() as ddgs:
            for r in ddgs.text(query, max_results=num_results):
                results.append(
                    {
                        "title": r.get("title", ""),
                        "url": r.get("href", ""),
                        "snippet": r.get("body", ""),
                    }
                )
        return json.dumps(
            {"success": True, "results": results, "count": len(results)},
            ensure_ascii=False,
        )
    except ImportError:
        return error_json("需要安装 duckduckgo-search：pip install duckduckgo-search")
    except Exception as e:
        logger.error(f"[web_search] 失败: {e}")
        return error_json(e)


# =========================================================================
# web_fetch
# =========================================================================

WEB_FETCH_SCHEMA = make_tool_schema(
    name="web_fetch",
    description="抓取指定网页的文本内容（自动去除 HTML 标签）。",
    properties={
        "url": {"type": "string", "description": "要抓取的网页 URL"},
        "max_length": {
            "type": "integer",
            "description": f"返回内容最大字符数，默认 {_WEB_FETCH_MAX_LENGTH}",
        },
    },
    required=["url"],
)


def web_fetch_handler(url: str, max_length: int = _WEB_FETCH_MAX_LENGTH) -> str:
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
        return error_json(e)


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


def _resolve_path_arg(ctx: ToolCallContext, key: str = "path", default: str | None = None) -> Path:
    raw = ctx.args.get(key, default)
    if raw is None:
        raise KeyError(key)
    return Path(str(raw)).expanduser().resolve()


def _is_system_path(path: Path) -> bool:
    system_dirs = [Path("C:/Windows"), Path("C:/System32"), Path("/etc"), Path("/usr")]
    for sys_dir in system_dirs:
        try:
            path.relative_to(sys_dir.resolve())
            return True
        except ValueError:
            continue
    return False


def _is_safe_exec_command(command: str) -> bool:
    cmd_lower = command.strip().lower()
    for safe in EXEC_SAFE_COMMANDS:
        if cmd_lower == safe:
            return True
        if cmd_lower.startswith(safe + " "):
            rest = cmd_lower[len(safe) + 1 :]
            if not any(
                c in rest for c in (";", "|", "&", "`", "$", "(", ")", "\n", "\r", ">", "<")
            ):
                return True
    return False


def _confirm_or_reject(tool_name: str, summary: str) -> PreHookResult | None:
    if is_auto_approve_enabled():
        pending = PendingConfirmation(
            request_id=str(uuid.uuid4()),
            tool_name=tool_name,
            summary=summary,
            created_at=time.monotonic(),
            event=threading.Event(),
            result=True,
            decision=CONFIRM_DECISION_AUTO_APPROVED,
            source=CONFIRM_SOURCE_AUTO_SCOPE,
        )
        _log_confirmation_decision(pending)
        return None

    try:
        confirmed = _ask_user_confirm(summary, tool_name=tool_name)
    except Exception as exc:
        logger.warning("[builtin_tools] 确认请求失败，拒绝高危操作: %s", exc, exc_info=True)
        return PreHookResult(error="确认请求失败，拒绝执行该高危操作")
    if not confirmed:
        return PreHookResult(error="用户取消了该操作")
    return None


def read_file_pre_hook(ctx: ToolCallContext) -> PreHookResult | None:
    p = _resolve_path_arg(ctx)
    if not p.exists():
        return PreHookResult(error=f"文件不存在: {p}")
    if not p.is_file():
        return PreHookResult(error=f"不是文件: {p}")
    return None


def write_file_pre_hook(ctx: ToolCallContext) -> PreHookResult | None:
    p = _resolve_path_arg(ctx)
    if _is_system_path(p):
        return PreHookResult(error="禁止写入系统目录")
    return _confirm_or_reject("write_file", _build_write_summary(p))


def edit_file_pre_hook(ctx: ToolCallContext) -> PreHookResult | None:
    p = _resolve_path_arg(ctx)
    if not p.exists():
        return PreHookResult(error=f"文件不存在: {p}")
    if not p.is_file():
        return PreHookResult(error=f"不是文件: {p}")
    old_text = str(ctx.args["old_text"])
    return _confirm_or_reject(
        "edit_file",
        _build_edit_summary(p, old_text, str(ctx.args["new_text"])),
    )


def list_dir_pre_hook(ctx: ToolCallContext) -> PreHookResult | None:
    p = _resolve_path_arg(ctx, default=".")
    if not p.exists():
        return PreHookResult(error=f"路径不存在: {p}")
    if not p.is_dir():
        return PreHookResult(error=f"不是目录: {p}")
    return None


def exec_pre_hook(ctx: ToolCallContext) -> PreHookResult | None:
    command = str(ctx.args["command"])
    if _is_safe_exec_command(command):
        return None
    return _confirm_or_reject("exec", _build_exec_summary(command))


# =========================================================================
# read_file
# =========================================================================

READ_FILE_SCHEMA = make_tool_schema(
    name="read_file",
    description="读取本地文件的内容。支持文本文件。",
    properties={
        "path": {"type": "string", "description": "文件路径（绝对路径或相对路径）"},
        "encoding": {
            "type": "string",
            "description": "文件编码，默认 utf-8",
        },
        "max_bytes": {
            "type": "integer",
            "description": f"最多读取字节数，默认 {_READ_FILE_MAX_BYTES}",
        },
    },
    required=["path"],
)


def read_file_handler(
    path: str, encoding: str = "utf-8", max_bytes: int = _READ_FILE_MAX_BYTES
) -> str:
    """读取本地文件"""
    try:
        p = Path(path).expanduser().resolve()

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
        return error_json(e)


# =========================================================================
# write_file（高危，需用户确认）
# =========================================================================

WRITE_FILE_SCHEMA = make_tool_schema(
    name="write_file",
    description="将内容写入本地文件（覆盖写）。写入前会请求用户确认。",
    properties={
        "path": {"type": "string", "description": "文件路径"},
        "content": {"type": "string", "description": "要写入的内容"},
        "encoding": {"type": "string", "description": "文件编码，默认 utf-8"},
    },
    required=["path", "content"],
)


def write_file_handler(path: str, content: str, encoding: str = "utf-8") -> str:
    """写入本地文件（需用户确认）"""
    try:
        p = Path(path).expanduser().resolve()

        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding=encoding) as f:
            f.write(content)

        return json.dumps(
            {"success": True, "path": str(p), "bytes_written": len(content.encode(encoding))},
            ensure_ascii=False,
        )
    except Exception as e:
        logger.error(f"[write_file] 失败: {e}")
        return error_json(e)


# =========================================================================
# edit_file（局部替换）
# =========================================================================

EDIT_FILE_SCHEMA = make_tool_schema(
    name="edit_file",
    description="替换文件中的指定文本片段。精确替换，要求 old_text 在文件中唯一存在。",
    properties={
        "path": {"type": "string", "description": "文件路径"},
        "old_text": {"type": "string", "description": "要替换的原始文本"},
        "new_text": {"type": "string", "description": "替换后的新文本"},
    },
    required=["path", "old_text", "new_text"],
)


def edit_file_handler(path: str, old_text: str, new_text: str) -> str:
    """替换文件中的指定文本"""
    try:
        p = Path(path).expanduser().resolve()
        content = p.read_text(encoding="utf-8", errors="replace")
        count = content.count(old_text)
        if count == 0:
            return error_json("未找到指定文本")
        if count > 1:
            return error_json(f"文本出现 {count} 次，请提供更多上下文确保唯一性")
        new_content = content.replace(old_text, new_text, 1)
        p.write_text(new_content, encoding="utf-8")
        return json.dumps({"success": True, "path": str(p)}, ensure_ascii=False)
    except Exception as e:
        logger.error(f"[edit_file] 失败: {e}")
        return error_json(e)


# =========================================================================
# list_dir
# =========================================================================

LIST_DIR_SCHEMA = make_tool_schema(
    name="list_dir",
    description="列出目录中的文件和子目录。",
    properties={
        "path": {
            "type": "string",
            "description": "目录路径，默认为当前工作目录",
        },
        "show_hidden": {
            "type": "boolean",
            "description": "是否显示隐藏文件，默认 false",
        },
    },
    required=[],
)


def list_dir_handler(path: str = ".", show_hidden: bool = False) -> str:
    """列出目录内容"""
    try:
        p = Path(path).expanduser().resolve()

        items = []
        for item in sorted(p.iterdir()):
            if not show_hidden and item.name.startswith("."):
                continue
            items.append(
                {
                    "name": item.name,
                    "type": "dir" if item.is_dir() else "file",
                    "size": item.stat().st_size if item.is_file() else None,
                }
            )

        return json.dumps(
            {"success": True, "path": str(p), "items": items, "count": len(items)},
            ensure_ascii=False,
        )
    except Exception as e:
        logger.error(f"[list_dir] 失败: {e}")
        return error_json(e)


# =========================================================================
# exec（高危，白名单 + 用户确认）
# =========================================================================

EXEC_SCHEMA = make_tool_schema(
    name="exec",
    description="执行 shell 命令并返回输出。安全命令（如 ls、dir）无需确认，其他命令需用户确认。",
    properties={
        "command": {"type": "string", "description": "要执行的命令"},
        "timeout": {
            "type": "integer",
            "description": "超时秒数，默认 30",
        },
    },
    required=["command"],
)


def exec_handler(command: str, timeout: int = 30) -> str:
    """执行 shell 命令"""
    try:
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
                "stdout": result.stdout[:_EXEC_STDOUT_MAX],
                "stderr": result.stderr[:_EXEC_STDERR_MAX],
            },
            ensure_ascii=False,
        )
    except subprocess.TimeoutExpired:
        return error_json(f"命令超时（{timeout}s）")
    except Exception as e:
        logger.error(f"[exec] 失败: {e}")
        return error_json(e)


# =========================================================================
# 工具定义实例
# =========================================================================

BUILTIN_GENERAL_TOOLS: List[ToolDefinition] = [
    ToolDefinition(name="web_search", schema=WEB_SEARCH_SCHEMA, handler=web_search_handler),
    ToolDefinition(name="web_fetch", schema=WEB_FETCH_SCHEMA, handler=web_fetch_handler),
    ToolDefinition(
        name="read_file",
        schema=READ_FILE_SCHEMA,
        handler=read_file_handler,
        pre_hook=read_file_pre_hook,
    ),
    ToolDefinition(
        name="write_file",
        schema=WRITE_FILE_SCHEMA,
        handler=write_file_handler,
        pre_hook=write_file_pre_hook,
    ),
    ToolDefinition(
        name="edit_file",
        schema=EDIT_FILE_SCHEMA,
        handler=edit_file_handler,
        pre_hook=edit_file_pre_hook,
    ),
    ToolDefinition(
        name="list_dir",
        schema=LIST_DIR_SCHEMA,
        handler=list_dir_handler,
        pre_hook=list_dir_pre_hook,
    ),
    ToolDefinition(name="exec", schema=EXEC_SCHEMA, handler=exec_handler, pre_hook=exec_pre_hook),
]

__all__ = [
    "BUILTIN_GENERAL_TOOLS",
    "CONFIRM_DECISION_ACCEPTED",
    "CONFIRM_DECISION_TIMEOUT",
    "CONFIRM_SOURCE_AUTO_SCOPE",
    "CONFIRM_SOURCE_NEW_CHAT_RESET",
    "CONFIRM_SOURCE_TOAST",
    "CONFIRM_SOURCE_TOAST_ACCEPT",
    "CONFIRM_SOURCE_TOAST_ALLOW_ALL",
    "CONFIRM_SOURCE_TOAST_REJECT",
    "CONFIRM_SOURCE_TOAST_TIMEOUT",
    "CONFIRM_SOURCE_TOP_TOGGLE",
    "CONFIRM_TIMEOUT_MS",
    "PendingConfirmation",
    "get_confirmation_remaining_timeout_ms",
    "get_pending_confirmation",
    "is_auto_approve_enabled",
    "register_confirm_mechanism",
    "reset_auto_approve",
    "reset_confirmation_state_for_tests",
    "set_auto_approve_enabled",
    "set_confirm_result",
    "settle_pending_confirmations",
]
