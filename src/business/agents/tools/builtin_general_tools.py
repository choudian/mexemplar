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
"""

import json
import logging
import heapq
import http.client
import ipaddress
import socket
import ssl
import threading
import time
import urllib.parse
import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import List

from src.business.agents.config import ToolDefinition
from src.business.agents.hook_models import PreHookResult, ToolCallContext
from src.business.agents.tool_helpers import make_tool_schema, error_json
from src.business.agents.tools import command_tools, file_tools, output_governance, search_tools
from src.business.agents.tools.builtin_contracts import (
    OUTCOME_REJECTED,
    current_tool_runtime,
    error_json as builtin_error_json,
    success_json,
)
from src.business.agents.tools.builtin_permissions import (
    build_edit_summary,
    build_exec_summary,
    build_write_summary,
    clear_external_read_confirmations_for_tests,
    command_path_policy_violation,
    is_safe_exec_command,
    mark_external_read_confirmed,
    permission_for_path,
    _truncate_summary,
)
from src.utils.agent_tool_health import increment_agent_tool_health

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
_WEB_FETCH_ALLOWED_SCHEMES = {"http", "https"}
_WEB_FETCH_LOCALHOST_NAMES = {"localhost", "localhost.localdomain"}
_WEB_FETCH_MAX_REDIRECTS = 5
_WEB_FETCH_MAX_BYTES = 1_000_000
_WEB_FETCH_REDIRECT_DRAIN_BYTES = 64 * 1024
_WEB_FETCH_SSL_CONTEXT = ssl.create_default_context()
_LIST_DIR_MAX_ITEMS = 1000
# Short TTL prevents SSRF via DNS rebinding while reducing blocking DNS calls per agent turn.
_DNS_CACHE: dict[str, tuple[float, list]] = {}
_DNS_CACHE_LOCK = threading.Lock()
_DNS_CACHE_TTL = 30.0

# =========================================================================
# 用户确认机制（高危工具，线程安全）
# 每个 worker 线程用独立的 threading.Event 等待，结果按 request_id 隔离。
# =========================================================================

_confirm_signal = None  # emit-compatible signal: (request_id, message)
_pending_confirms: dict = {}  # request_id → PendingConfirmation
_confirm_lock = threading.Lock()
_auto_approve_enabled = False
_last_confirmation_source: ContextVar[str | None] = ContextVar(
    "builtin_last_confirmation_source",
    default=None,
)


@dataclass
class PendingConfirmation:
    """等待 UI 决策的高危工具确认请求。"""

    request_id: str
    tool_name: str
    summary: str
    created_at: float
    event: threading.Event
    extra_payload: dict[str, object] | None = None
    result: bool = False
    decision: str | None = None
    source: str | None = None
    # 归属会话（= 运行上下文 root_session_id）；"停止"据此 fail-closed 该会话 pending 确认（014）。
    session_id: str | None = None


def register_confirm_mechanism(signal):
    """
    注入跨线程确认信号（由 UI/sidecar adapter 在初始化时调用）。

    Args:
        signal: emit(request_id, message) 后由 UI 展示确认
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
            logger.debug(
                "[builtin_tools] 忽略未知确认请求: request_id=%s, source=%s", request_id, source
            )
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


def settle_pending_confirmations_for_session(
    session_id: str,
    result: bool,
    source: str,
) -> list[str]:
    """结算属于指定会话、仍在等待 UI 决策的确认请求（"停止"时 fail-closed 拒绝用）。

    复用 set_confirm_result 的 first-decision-wins（event 已 set 则跳过），不破坏 CC-001 同步确认协议。
    """
    sid = (session_id or "").strip()
    if not sid:
        return []
    with _confirm_lock:
        request_ids = [
            request_id
            for request_id, pending in _pending_confirms.items()
            if not pending.event.is_set() and (pending.session_id or "") == sid
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
    global _auto_approve_enabled
    with _confirm_lock:
        _auto_approve_enabled = bool(enabled)
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
    global _confirm_signal, _auto_approve_enabled
    with _confirm_lock:
        _pending_confirms.clear()
        _auto_approve_enabled = False
    _confirm_signal = None
    clear_external_read_confirmations_for_tests()


def _ask_user_confirm(
    message: str,
    tool_name: str = "unknown",
    extra_payload: dict[str, object] | None = None,
) -> bool:
    """
    请求用户确认高危操作（线程安全，支持多 worker 并发）。

    每次请求生成唯一 request_id，worker 线程各自阻塞在独立的 Event 上。
    """
    if _confirm_signal is None:
        _last_confirmation_source.set(CONFIRM_SOURCE_SYSTEM_ERROR)
        logger.warning("[builtin_tools] 确认机制未注册，拒绝高危操作")
        return False

    request_id = str(uuid.uuid4())
    event = threading.Event()
    # 捕获当前运行的归属会话（root_session_id），供"停止"按会话 fail-closed 唤醒（FR-006b）。
    # 子代理高危确认的归属仍是父会话（ContextVar 持 root），停止父即可唤醒整链。
    try:
        from src.business.agents import run_context

        _run_ctx = run_context.get_current()
        _session_id = _run_ctx.root_session_id if _run_ctx is not None else None
    except Exception:
        _session_id = None
    pending = PendingConfirmation(
        request_id=request_id,
        tool_name=tool_name,
        summary=_truncate_summary(message),
        created_at=time.monotonic(),
        event=event,
        extra_payload=extra_payload,
        session_id=_session_id,
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
        _last_confirmation_source.set(CONFIRM_SOURCE_SYSTEM_ERROR)
        _log_confirmation_decision(pending)
        raise

    if not completed:
        set_confirm_result(request_id, False, CONFIRM_SOURCE_TOAST_TIMEOUT)

    with _confirm_lock:
        pending = _pending_confirms.pop(request_id, None)
    if isinstance(pending, PendingConfirmation):
        _last_confirmation_source.set(pending.source)
        return pending.result
    _last_confirmation_source.set(CONFIRM_SOURCE_SYSTEM_ERROR)
    return False


def _decision_from_result_source(result: bool, source: str) -> str:
    """Normalize UI confirmation result/source pairs into the persisted audit decision."""
    if source in {CONFIRM_SOURCE_TOAST_TIMEOUT, CONFIRM_SOURCE_NEW_CHAT_RESET}:
        return CONFIRM_DECISION_TIMEOUT
    if source in {
        CONFIRM_SOURCE_TOAST_ALLOW_ALL,
        CONFIRM_SOURCE_TOP_TOGGLE,
        CONFIRM_SOURCE_AUTO_SCOPE,
    }:
        return CONFIRM_DECISION_AUTO_APPROVED if result else CONFIRM_DECISION_REJECTED
    return CONFIRM_DECISION_ACCEPTED if result else CONFIRM_DECISION_REJECTED


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


_WEB_SEARCH_CODE = """\
import json

async def execute(**kwargs):
    from duckduckgo_search import DDGS

    query = kwargs["query"]
    num_results = kwargs.get("num_results", 5)

    results = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=num_results):
            results.append({
                "title": r.get("title", ""),
                "url": r.get("href", ""),
                "snippet": r.get("body", ""),
            })
    return {"success": True, "message": json.dumps({"success": True, "results": results, "count": len(results)}, ensure_ascii=False)}
"""


def web_search_handler(query: str, num_results: int = 5) -> str:
    """使用 DuckDuckGo 进行网页搜索（通过 tool_venv 子进程执行）"""
    try:
        from src.execution.tool_executor import run_tool_code

        result = run_tool_code(
            code=_WEB_SEARCH_CODE,
            parameters={"query": query, "num_results": num_results},
            dependencies=["duckduckgo-search"],
        )
        if result.get("success"):
            return result.get("message", json.dumps({"success": False, "error": "空结果"}))
        error_msg = result.get("message", "搜索执行失败")
        if "依赖安装失败" in error_msg:
            error_msg += "。可尝试手动安装: pip install duckduckgo-search"
        return error_json(error_msg)
    except Exception as e:
        logger.error(f"[web_search] 失败: {e}")
        return error_json(f"搜索执行失败: {e}。如持续失败，可尝试: pip install duckduckgo-search")


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
        safe_url = _validate_web_fetch_url(url)
        max_length = _normalize_web_fetch_max_length(max_length)
        final_url, html = _fetch_validated_web_url(safe_url)

        text = _extract_text_from_html(html)[:max_length]

        return json.dumps(
            {
                "success": True,
                "url": final_url,
                "content": text,
                "truncated": len(text) == max_length,
            },
            ensure_ascii=False,
        )
    except Exception as e:
        logger.error(f"[web_fetch] 失败: {e}")
        return error_json(e)


class _ResolvedHTTPConnection(http.client.HTTPConnection):
    """HTTP connection that connects to a pre-validated address, not a fresh DNS result."""

    def __init__(
        self, host: str, port: int, resolved_address: ipaddress._BaseAddress, timeout: float
    ):
        super().__init__(host, port=port, timeout=timeout)
        self._resolved_address = str(resolved_address)

    def connect(self) -> None:
        self.sock = _create_resolved_web_fetch_socket(
            (self._resolved_address, self.port),
            self.timeout,
            self.source_address,
        )


class _ResolvedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection that preserves SNI while dialing a pre-validated address."""

    def __init__(
        self, host: str, port: int, resolved_address: ipaddress._BaseAddress, timeout: float
    ):
        super().__init__(host, port=port, timeout=timeout, context=_WEB_FETCH_SSL_CONTEXT)
        self._resolved_address = str(resolved_address)

    def connect(self) -> None:
        sock = _create_resolved_web_fetch_socket(
            (self._resolved_address, self.port),
            self.timeout,
            self.source_address,
        )
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def _create_resolved_web_fetch_socket(address, timeout, source_address):
    sock = socket.create_connection(address, timeout, source_address)
    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    except (AttributeError, OSError):
        pass
    return sock


def _normalize_web_fetch_max_length(max_length: int) -> int:
    try:
        parsed = int(max_length)
    except (TypeError, ValueError):
        return _WEB_FETCH_MAX_LENGTH
    return max(1, min(parsed, _WEB_FETCH_MAX_LENGTH))


def _validate_web_fetch_url(url: str) -> str:
    candidate = str(url or "").strip()
    parsed = urllib.parse.urlparse(candidate)
    if parsed.scheme.lower() not in _WEB_FETCH_ALLOWED_SCHEMES:
        raise ValueError("web_fetch 只允许 http/https URL")
    if not parsed.hostname:
        raise ValueError("web_fetch URL 缺少主机名")
    _web_fetch_port(parsed)
    return urllib.parse.urlunparse(parsed._replace(scheme=parsed.scheme.lower()))


def _fetch_validated_web_url(
    url: str, *, redirects_remaining: int = _WEB_FETCH_MAX_REDIRECTS
) -> tuple[str, str]:
    parsed = urllib.parse.urlparse(_validate_web_fetch_url(url))
    addresses = _validated_web_fetch_addresses(parsed.hostname or "")
    address = addresses[0]
    port = _web_fetch_port(parsed)
    conn_cls = _ResolvedHTTPSConnection if parsed.scheme == "https" else _ResolvedHTTPConnection
    conn = conn_cls(parsed.hostname or "", port, address, timeout=15)
    path = urllib.parse.urlunparse(("", "", parsed.path or "/", parsed.params, parsed.query, ""))
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Host": _web_fetch_host_header(parsed),
        "Connection": "close",
    }
    try:
        conn.request("GET", path, headers=headers)
        resp = conn.getresponse()
        if resp.status in {301, 302, 303, 307, 308}:
            if redirects_remaining <= 0:
                raise ValueError("web_fetch 重定向次数过多")
            location = resp.getheader("Location")
            if not location:
                raise ValueError("web_fetch 重定向响应缺少 Location")
            next_url = urllib.parse.urljoin(urllib.parse.urlunparse(parsed), location)
            _drain_redirect_response_body(resp)
            conn.close()
            return _fetch_validated_web_url(next_url, redirects_remaining=redirects_remaining - 1)
        if resp.status >= 400:
            raise ValueError(f"web_fetch HTTP 请求失败: {resp.status}")
        raw = resp.read(_WEB_FETCH_MAX_BYTES + 1)
        if len(raw) > _WEB_FETCH_MAX_BYTES:
            raw = raw[:_WEB_FETCH_MAX_BYTES]
        charset = resp.headers.get_content_charset() or "utf-8"
        return urllib.parse.urlunparse(parsed), raw.decode(charset, errors="replace")
    finally:
        conn.close()


def _web_fetch_port(parsed: urllib.parse.ParseResult) -> int:
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("web_fetch URL 端口非法") from exc
    if port is not None:
        return port
    return 443 if parsed.scheme.lower() == "https" else 80


def _web_fetch_host_header(parsed: urllib.parse.ParseResult) -> str:
    host = (parsed.hostname or "").strip("[]")
    if ":" in host:
        host = f"[{host}]"
    port = _web_fetch_port(parsed)
    default_port = 443 if parsed.scheme.lower() == "https" else 80
    return host if port == default_port else f"{host}:{port}"


def _drain_redirect_response_body(resp: http.client.HTTPResponse) -> None:
    try:
        if getattr(resp, "chunked", False):
            resp.read()
            return
        remaining = getattr(resp, "length", None)
        if isinstance(remaining, int) and remaining > 0:
            resp.read(min(remaining, _WEB_FETCH_REDIRECT_DRAIN_BYTES))
    except Exception as exc:
        logger.debug("Failed to drain redirect response body: %s", exc)


def _cached_dns_lookup(host: str) -> list:
    now = time.monotonic()
    with _DNS_CACHE_LOCK:
        entry = _DNS_CACHE.get(host)
        if entry is not None and now < entry[0]:
            return entry[1]
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"web_fetch 无法解析主机名: {host}") from exc
    addresses = []
    for info in infos:
        sockaddr = info[4]
        if not sockaddr:
            continue
        try:
            addresses.append(ipaddress.ip_address(sockaddr[0]))
        except ValueError:
            continue
    with _DNS_CACHE_LOCK:
        _DNS_CACHE[host] = (now + _DNS_CACHE_TTL, addresses)
    return addresses


def _validated_web_fetch_addresses(hostname: str) -> list[ipaddress._BaseAddress]:
    host = hostname.strip("[]").rstrip(".").lower()
    if host in _WEB_FETCH_LOCALHOST_NAMES or host.endswith(".localhost"):
        raise ValueError("web_fetch 不允许访问本机地址")

    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        addresses = _cached_dns_lookup(host)

    if not addresses:
        raise ValueError(f"web_fetch 无法解析主机名: {hostname}")
    validated = []
    for address in addresses:
        if hasattr(address, "ipv4_mapped") and address.ipv4_mapped is not None:
            address = address.ipv4_mapped
        if not address.is_global:
            raise ValueError("web_fetch 不允许访问内网、本机或保留地址")
        validated.append(address)
    return validated


class _HtmlTextExtractor(HTMLParser):
    """从 HTML 中提取纯文本（去除 script/style/head 标签内容）"""

    def __init__(self):
        super().__init__()
        self.parts: list[str] = []
        self._skip = False

    def handle_starttag(self, tag, _attrs):
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
        _last_confirmation_source.set(None)
        confirmed = _ask_user_confirm(summary, tool_name=tool_name)
    except Exception as exc:
        logger.warning("[builtin_tools] 确认请求失败，拒绝高危操作: %s", exc, exc_info=True)
        increment_agent_tool_health(confirmation_fail_closed=1)
        return PreHookResult(
            error="确认请求失败，拒绝执行该高危操作",
            error_code="confirmation_failed_closed",
        )
    if not confirmed:
        source = _last_confirmation_source.get()
        if source in {
            CONFIRM_SOURCE_SYSTEM_ERROR,
            CONFIRM_SOURCE_TOAST_TIMEOUT,
            CONFIRM_SOURCE_NEW_CHAT_RESET,
        }:
            increment_agent_tool_health(confirmation_fail_closed=1)
            return PreHookResult(
                error="确认不可用或已超时，已拒绝执行该高危操作",
                error_code="confirmation_failed_closed",
            )
        return PreHookResult(error="用户取消了该操作", error_code="permission_denied")
    return None


def read_file_pre_hook(ctx: ToolCallContext) -> PreHookResult | None:
    p = _resolve_path_arg(ctx)
    check = permission_for_path(p, operation="read", session_id=ctx.session_id)
    if check.decision.decision == "confirmation_required":
        rejected = _confirm_or_reject("read_file", check.decision.summary or build_write_summary(p))
        if rejected is not None:
            return rejected
        mark_external_read_confirmed(p, session_id=ctx.session_id)
        return None
    if not check.allowed:
        return PreHookResult(
            error=check.message or "文件读取被权限策略拒绝",
            error_code=check.error_code or "permission_denied",
        )
    if not p.exists():
        return PreHookResult(error=f"文件不存在: {p}", error_code="path_not_found")
    if not p.is_file():
        return PreHookResult(error=f"不是文件: {p}", error_code="path_not_file")
    return None


def write_file_pre_hook(ctx: ToolCallContext) -> PreHookResult | None:
    p = _resolve_path_arg(ctx)
    check = permission_for_path(p, operation="write")
    if not check.allowed:
        return PreHookResult(
            error=check.message or "文件写入被权限策略拒绝",
            error_code=check.error_code or "permission_denied",
        )
    baseline = ctx.args.get("expectedBaselineId") or ctx.args.get("expected_baseline_id")
    return _confirm_or_reject("write_file", build_write_summary(p, baseline_id=str(baseline or "")))


def edit_file_pre_hook(ctx: ToolCallContext) -> PreHookResult | None:
    p = _resolve_path_arg(ctx)
    check = permission_for_path(p, operation="edit")
    if not check.allowed:
        return PreHookResult(
            error=check.message or "文件编辑被权限策略拒绝",
            error_code=check.error_code or "permission_denied",
        )
    if not p.exists():
        return PreHookResult(error=f"文件不存在: {p}", error_code="path_not_found")
    if not p.is_file():
        return PreHookResult(error=f"不是文件: {p}", error_code="path_not_file")
    old_text = str(ctx.args.get("old_text") or "")
    new_text = str(ctx.args.get("new_text") or "")
    replacements = ctx.args.get("replacements")
    if isinstance(replacements, tuple) and replacements:
        first = replacements[0]
        if hasattr(first, "get"):
            old_text = str(first.get("oldText") or "")
            new_text = str(first.get("newText") or "")
    baseline = ctx.args.get("expectedBaselineId") or ctx.args.get("expected_baseline_id")
    return _confirm_or_reject(
        "edit_file",
        build_edit_summary(p, old_text, new_text, baseline_id=str(baseline or "")),
    )


def list_dir_pre_hook(ctx: ToolCallContext) -> PreHookResult | None:
    p = _resolve_path_arg(ctx, default=".")
    show_hidden = bool(ctx.args.get("show_hidden", False))
    check = permission_for_path(
        p,
        operation="read",
        allow_hidden=show_hidden,
        session_id=ctx.session_id,
    )
    if check.decision.decision == "confirmation_required":
        rejected = _confirm_or_reject(
            "list_dir", check.decision.summary or f"Read outside workspace: {p.name}"
        )
        if rejected is not None:
            return rejected
        mark_external_read_confirmed(p, session_id=ctx.session_id)
        return None
    if not check.allowed:
        return PreHookResult(
            error=check.message or "目录读取被权限策略拒绝",
            error_code=check.error_code or "permission_denied",
        )
    if not p.exists():
        return PreHookResult(error=f"路径不存在: {p}", error_code="path_not_found")
    if not p.is_dir():
        return PreHookResult(error=f"不是目录: {p}", error_code="path_not_directory")
    return None


def exec_pre_hook(ctx: ToolCallContext) -> PreHookResult | None:
    command = str(ctx.args["command"])
    cwd = ctx.args.get("cwd", ".")
    check = permission_for_path(cwd, operation="execute")
    if not check.allowed:
        return PreHookResult(
            error=check.message or "命令执行目录被权限策略拒绝",
            error_code=check.error_code or "command_rejected",
        )
    path_check = command_path_policy_violation(
        command,
        workspace_root=Path.cwd(),
        base_dir=check.classification.resolved,
    )
    if path_check is not None:
        return PreHookResult(
            error=path_check.message or "命令路径参数被权限策略拒绝",
            error_code=path_check.error_code or "command_rejected",
        )
    if is_safe_exec_command(command):
        return None
    return _confirm_or_reject("exec", build_exec_summary(command))


# =========================================================================
# read_file
# =========================================================================

READ_FILE_SCHEMA = make_tool_schema(
    name="read_file",
    description=(
        "Read a bounded, redacted text window from a workspace file. "
        "Returns line metadata, continuation token, and a baseline for later safe mutation. "
        "Binary/media files are refused without raw bytes."
    ),
    properties={
        "path": {"type": "string", "description": "Workspace-relative or confirmed read-only path"},
        "startLine": {"type": "integer", "description": "1-based first line to return"},
        "maxLines": {
            "type": "integer",
            "description": "Maximum lines to return within configured caps",
        },
        "encoding": {
            "type": "string",
            "description": "文件编码，默认 utf-8",
        },
        "includeLineNumbers": {
            "type": "boolean",
            "description": "Whether to include structured line rows",
        },
    },
    required=["path"],
)


def read_file_handler(
    path: str,
    encoding: str = "utf-8",
    startLine: int | None = None,
    maxLines: int | None = None,
    includeLineNumbers: bool = True,
    max_bytes: int | None = None,
) -> str:
    return file_tools.read_file_handler(
        path=path,
        encoding=encoding,
        startLine=startLine,
        maxLines=maxLines,
        includeLineNumbers=includeLineNumbers,
        max_bytes=max_bytes,
    )


# =========================================================================
# write_file（高危，需用户确认）
# =========================================================================

WRITE_FILE_SCHEMA = make_tool_schema(
    name="write_file",
    description=(
        "Create a new text file or replace an existing workspace file. "
        "Existing files require expectedBaselineId from read_file; stale or missing baselines are rejected."
    ),
    properties={
        "path": {"type": "string", "description": "文件路径"},
        "content": {"type": "string", "description": "要写入的内容"},
        "expectedBaselineId": {
            "type": "string",
            "description": "Baseline id from read_file, required when replacing an existing file",
        },
        "expectedSha256": {
            "type": "string",
            "description": "Optional raw sha256 baseline alternative",
        },
        "encoding": {"type": "string", "description": "文件编码，默认 utf-8"},
    },
    required=["path", "content"],
)


def write_file_handler(
    path: str,
    content: str,
    encoding: str = "utf-8",
    expectedBaselineId: str | None = None,
    expectedSha256: str | None = None,
) -> str:
    return file_tools.write_file_handler(
        path=path,
        content=content,
        encoding=encoding,
        expectedBaselineId=expectedBaselineId,
        expectedSha256=expectedSha256,
    )


# =========================================================================
# edit_file（局部替换）
# =========================================================================

EDIT_FILE_SCHEMA = make_tool_schema(
    name="edit_file",
    description=(
        "Apply targeted replacements to an existing workspace text file. "
        "Requires expectedBaselineId from read_file; missing, stale, ambiguous, or overlapping edits are rejected."
    ),
    properties={
        "path": {"type": "string", "description": "文件路径"},
        "expectedBaselineId": {
            "type": "string",
            "description": "Current baseline id from read_file",
        },
        "replacements": {
            "type": "array",
            "description": "Replacement operations",
            "items": {
                "type": "object",
                "properties": {
                    "oldText": {"type": "string"},
                    "newText": {"type": "string"},
                    "replaceAll": {"type": "boolean"},
                },
                "required": ["oldText", "newText"],
            },
        },
    },
    required=["path", "expectedBaselineId", "replacements"],
)


def edit_file_handler(
    path: str,
    expectedBaselineId: str | None = None,
    replacements: list[dict] | None = None,
    old_text: str | None = None,
    new_text: str | None = None,
) -> str:
    return file_tools.edit_file_handler(
        path=path,
        expectedBaselineId=expectedBaselineId,
        replacements=replacements,
        old_text=old_text,
        new_text=new_text,
    )


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
    """Return a bounded structured directory listing."""
    runtime = current_tool_runtime()
    workspace_root = runtime.workspace_root if runtime is not None else Path.cwd()
    session_id = runtime.session_id if runtime is not None else None
    check = permission_for_path(
        path,
        operation="read",
        workspace_root=workspace_root,
        allow_hidden=show_hidden,
        session_id=session_id,
    )
    if not check.allowed:
        return builtin_error_json(
            "list_dir",
            check.error_code or "permission_denied",
            check.message or "Directory read is not authorized.",
            outcome=OUTCOME_REJECTED,
            permission=check.decision,
        )
    p = check.classification.resolved
    if not p.exists():
        return builtin_error_json(
            "list_dir",
            "path_not_found",
            "Directory does not exist.",
            outcome=OUTCOME_REJECTED,
            permission=check.decision,
        )
    if not p.is_dir():
        return builtin_error_json(
            "list_dir",
            "path_not_directory",
            "Path is not a directory.",
            outcome=OUTCOME_REJECTED,
            permission=check.decision,
        )
    try:
        candidates = (item for item in p.iterdir() if show_hidden or not item.name.startswith("."))
        visible = heapq.nsmallest(
            _LIST_DIR_MAX_ITEMS + 1,
            candidates,
            key=lambda item: (item.name.lower(), item.name),
        )
        truncated = len(visible) > _LIST_DIR_MAX_ITEMS
        items = []
        for item in visible[:_LIST_DIR_MAX_ITEMS]:
            is_link = item.is_symlink()
            items.append(
                {
                    "name": item.name,
                    "type": ("symlink" if is_link else "dir" if item.is_dir() else "file"),
                    "sizeBytes": (item.stat().st_size if not is_link and item.is_file() else None),
                }
            )

        return success_json(
            "list_dir",
            {
                "path": check.classification.display_path,
                "items": items,
                "count": len(items),
            },
            permission=check.decision,
            limits={
                "truncated": truncated,
                "pageSize": _LIST_DIR_MAX_ITEMS,
                "hasMore": truncated,
            },
        )
    except OSError as exc:
        logger.warning("[list_dir] directory read failed: %s", type(exc).__name__)
        return builtin_error_json(
            "list_dir",
            "internal_error",
            "Directory could not be read.",
            permission=check.decision,
        )


# =========================================================================
# exec（高危，白名单 + 用户确认）
# =========================================================================

EXEC_SCHEMA = make_tool_schema(
    name="exec",
    description=(
        "Run a command inside the workspace with bounded output, or start it as a managed "
        "current-session background process. Elevated commands require confirmation."
    ),
    properties={
        "command": {"type": "string", "description": "要执行的命令"},
        "cwd": {"type": "string", "description": "Workspace-relative working directory"},
        "timeoutMs": {
            "type": "integer",
            "description": "Timeout in milliseconds, bounded by configuration",
        },
        "mode": {"type": "string", "enum": ["sync", "background"], "description": "Execution mode"},
        "stdin": {"type": "string", "description": "Optional bounded stdin for sync commands"},
        "allowStdin": {"type": "boolean", "description": "Enable stdin for background process"},
    },
    required=["command"],
)


def exec_handler(
    command: str,
    timeout: int | None = None,
    timeoutMs: int | None = None,
    cwd: str = ".",
    mode: str = "sync",
    stdin: str | None = None,
    allowStdin: bool = False,
) -> str:
    return command_tools.exec_handler(
        command=command,
        timeout=timeout,
        timeoutMs=timeoutMs,
        cwd=cwd,
        mode=mode,
        stdin=stdin,
        allowStdin=allowStdin,
    )


APPLY_PATCH_SCHEMA = make_tool_schema(
    name="apply_patch",
    description=(
        "Validate and apply a multi-file workspace patch. Add operations target new files; "
        "update/delete operations require current baselines. Unsafe targets reject the whole patch."
    ),
    properties={
        "operations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "operationId": {"type": "string"},
                    "type": {"type": "string", "enum": ["add", "update", "delete"]},
                    "path": {"type": "string"},
                    "expectedBaselineId": {"type": "string"},
                    "content": {"type": "string"},
                    "replacements": {
                        "type": "array",
                        "items": {"type": "object"},
                    },
                },
                "required": ["type", "path"],
            },
        }
    },
    required=["operations"],
)


SEARCH_FILES_SCHEMA = make_tool_schema(
    name="search_files",
    description="Search workspace filenames with deterministic bounded pagination and default dependency/build ignores.",
    properties={
        "root": {"type": "string"},
        "pattern": {"type": "string"},
        "pageSize": {"type": "integer"},
        "pageToken": {"type": "string"},
        "includeHidden": {"type": "boolean"},
    },
    required=[],
)


SEARCH_CONTENT_SCHEMA = make_tool_schema(
    name="search_content",
    description="Search workspace text content in literal or regex mode with grouped line matches and bounded context.",
    properties={
        "root": {"type": "string"},
        "pattern": {"type": "string"},
        "mode": {"type": "string", "enum": ["literal", "regex"]},
        "includeGlobs": {"type": "array", "items": {"type": "string"}},
        "contextLines": {"type": "integer"},
        "pageSize": {"type": "integer"},
        "pageToken": {"type": "string"},
        "includeHidden": {"type": "boolean"},
    },
    required=["pattern"],
)


PROCESS_LIST_SCHEMA = make_tool_schema(
    name="process_list",
    description="List current sidecar-session background processes.",
    properties={"status": {"type": "string"}},
    required=[],
)


def _process_id_schema(name: str, description: str) -> dict:
    return make_tool_schema(
        name=name,
        description=description,
        properties={"processId": {"type": "string"}},
        required=["processId"],
    )


PROCESS_LOGS_SCHEMA = make_tool_schema(
    name="process_logs",
    description="Read bounded logs from a current-session background process.",
    properties={
        "processId": {"type": "string"},
        "stream": {"type": "string", "enum": ["stdout", "stderr", "combined"]},
        "tailChars": {"type": "integer"},
    },
    required=["processId"],
)


PROCESS_WAIT_SCHEMA = make_tool_schema(
    name="process_wait",
    description="Wait up to timeoutMs for a current-session background process.",
    properties={"processId": {"type": "string"}, "timeoutMs": {"type": "integer"}},
    required=["processId"],
)


PROCESS_STOP_SCHEMA = make_tool_schema(
    name="process_stop",
    description="Stop a current-session background process.",
    properties={"processId": {"type": "string"}, "force": {"type": "boolean"}},
    required=["processId"],
)


PROCESS_SEND_INPUT_SCHEMA = make_tool_schema(
    name="process_send_input",
    description="Send bounded stdin to a process that was started with allowStdin=true.",
    properties={"processId": {"type": "string"}, "text": {"type": "string"}},
    required=["processId", "text"],
)


LOAD_TOOL_OUTPUT_SCHEMA = make_tool_schema(
    name="load_tool_output",
    description="Load a bounded redacted text window from an authorized persistent raw-output reference.",
    properties={
        "referenceId": {"type": "string"},
        "offset": {"type": "integer"},
        "maxBytes": {"type": "integer"},
        "renderAs": {"type": "string", "enum": ["text"]},
    },
    required=["referenceId"],
)


def apply_patch_handler(operations: list[dict]) -> str:
    return file_tools.apply_patch_handler(operations)


def search_files_handler(
    root: str = ".",
    pattern: str = "*",
    pageSize: int | None = None,
    pageToken: str | None = None,
    includeHidden: bool = False,
) -> str:
    return search_tools.search_files_handler(
        root=root,
        pattern=pattern,
        pageSize=pageSize,
        pageToken=pageToken,
        includeHidden=includeHidden,
    )


def search_content_handler(
    root: str = ".",
    pattern: str = "",
    mode: str = "literal",
    includeGlobs: list[str] | None = None,
    contextLines: int = 0,
    pageSize: int | None = None,
    pageToken: str | None = None,
    includeHidden: bool = False,
) -> str:
    return search_tools.search_content_handler(
        root=root,
        pattern=pattern,
        mode=mode,
        includeGlobs=includeGlobs,
        contextLines=contextLines,
        pageSize=pageSize,
        pageToken=pageToken,
        includeHidden=includeHidden,
    )


def load_tool_output_handler(
    referenceId: str,
    offset: int = 0,
    maxBytes: int = 64000,
    renderAs: str = "text",
) -> str:
    return output_governance.load_tool_output_handler(
        referenceId=referenceId,
        offset=offset,
        maxBytes=maxBytes,
        renderAs=renderAs,
    )


# =========================================================================
# 工具定义实例
# =========================================================================

BUILTIN_GENERAL_TOOLS: List[ToolDefinition] = [
    ToolDefinition(
        name="web_search",
        schema=WEB_SEARCH_SCHEMA,
        handler=web_search_handler,
        has_side_effects=False,
    ),
    ToolDefinition(
        name="web_fetch",
        schema=WEB_FETCH_SCHEMA,
        handler=web_fetch_handler,
        has_side_effects=False,
    ),
    ToolDefinition(
        name="read_file",
        schema=READ_FILE_SCHEMA,
        handler=read_file_handler,
        pre_hook=read_file_pre_hook,
        has_side_effects=False,
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
        name="apply_patch",
        schema=APPLY_PATCH_SCHEMA,
        handler=apply_patch_handler,
    ),
    ToolDefinition(
        name="search_files",
        schema=SEARCH_FILES_SCHEMA,
        handler=search_files_handler,
        has_side_effects=False,
    ),
    ToolDefinition(
        name="search_content",
        schema=SEARCH_CONTENT_SCHEMA,
        handler=search_content_handler,
        has_side_effects=False,
    ),
    ToolDefinition(
        name="list_dir",
        schema=LIST_DIR_SCHEMA,
        handler=list_dir_handler,
        pre_hook=list_dir_pre_hook,
        has_side_effects=False,
    ),
    ToolDefinition(name="exec", schema=EXEC_SCHEMA, handler=exec_handler, pre_hook=exec_pre_hook),
    ToolDefinition(
        name="process_list",
        schema=PROCESS_LIST_SCHEMA,
        handler=command_tools.process_list_handler,
        has_side_effects=False,
    ),
    ToolDefinition(
        name="process_poll",
        schema=_process_id_schema("process_poll", "Poll a current-session background process."),
        handler=command_tools.process_poll_handler,
        has_side_effects=False,
    ),
    ToolDefinition(
        name="process_logs",
        schema=PROCESS_LOGS_SCHEMA,
        handler=command_tools.process_logs_handler,
        has_side_effects=False,
    ),
    ToolDefinition(
        name="process_wait",
        schema=PROCESS_WAIT_SCHEMA,
        handler=command_tools.process_wait_handler,
        has_side_effects=False,
    ),
    ToolDefinition(
        name="process_stop",
        schema=PROCESS_STOP_SCHEMA,
        handler=command_tools.process_stop_handler,
    ),
    ToolDefinition(
        name="process_send_input",
        schema=PROCESS_SEND_INPUT_SCHEMA,
        handler=command_tools.process_send_input_handler,
    ),
    ToolDefinition(
        name="process_close",
        schema=_process_id_schema("process_close", "Close a completed or stopped process record."),
        handler=command_tools.process_close_handler,
    ),
    ToolDefinition(
        name="load_tool_output",
        schema=LOAD_TOOL_OUTPUT_SCHEMA,
        handler=load_tool_output_handler,
        has_side_effects=False,
    ),
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
    "settle_pending_confirmations_for_session",
    "read_file_handler",
    "write_file_handler",
    "edit_file_handler",
    "apply_patch_handler",
    "search_files_handler",
    "search_content_handler",
    "exec_handler",
    "load_tool_output_handler",
]
