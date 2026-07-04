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
import html as html_lib
import ipaddress
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections import OrderedDict
from contextvars import ContextVar
from dataclasses import dataclass
from http import HTTPStatus

from src.utils.bounded_lru_cache import BoundedLruCache
from pathlib import Path
from typing import List

from markdownify import markdownify as html_to_markdown

from src.business.agents.config import ToolDefinition
from src.business.agents.hook_models import PreHookResult, ToolCallContext
from src.business.agents.tool_helpers import make_tool_schema, error_json
from src.business.agents.tools import (
    command_tools,
    file_tools,
    output_governance,
    search_tools,
    web_search_providers,
)
from src.business.agents.tools.builtin_contracts import (
    BUILTIN_WEB_USER_AGENT,
    OUTCOME_REJECTED,
    current_tool_runtime,
    error_json as builtin_error_json,
    runtime_session_id,
    runtime_workspace_root,
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

# web_fetch behavior follows Claude Code WebFetch limits.
_WEB_FETCH_MAX_LENGTH = 100_000
_WEB_FETCH_ALLOWED_SCHEMES = {"http", "https"}
_WEB_FETCH_MAX_URL_LENGTH = 2000
_WEB_FETCH_MAX_BYTES = 10 * 1024 * 1024
_WEB_FETCH_TIMEOUT = 60
_WEB_FETCH_DOMAIN_CHECK_TIMEOUT = 10
_WEB_FETCH_MAX_REDIRECTS = 10
_WEB_FETCH_CACHE_TTL_SECONDS = 15 * 60
_WEB_FETCH_CACHE_MAX_BYTES = 50 * 1024 * 1024
_WEB_FETCH_DOMAIN_CHECK_CACHE_TTL_SECONDS = 5 * 60
_WEB_FETCH_DOMAIN_CHECK_CACHE_MAX_ENTRIES = 128
_WEB_FETCH_PROMPT_PREVIEW_CHARS = 900
_WEB_FETCH_TITLE_FALLBACK_CHARS = 600
_WEB_FETCH_REDIRECT_STATUSES = {301, 302, 307, 308}
_WEB_FETCH_LOCAL_HOSTNAMES = {"localhost", "localhost.localdomain"}
_WEB_FETCH_DOMAIN_INFO_URL = "https://api.anthropic.com/api/web/domain_info"
_LIST_DIR_MAX_ITEMS = 1000


@dataclass(frozen=True)
class _FetchedWebContent:
    final_url: str
    content: str
    bytes: int
    code: int | None
    code_text: str
    content_type: str
    title: str | None = None
    persisted_reference_id: str | None = None
    persisted_size: int | None = None


@dataclass(frozen=True)
class _WebFetchRedirect:
    original_url: str
    redirect_url: str
    status_code: int


@dataclass(frozen=True)
class _WebFetchCacheEntry:
    content: _FetchedWebContent
    size_bytes: int
    expires_at: float


_web_fetch_cache: OrderedDict[str, _WebFetchCacheEntry] = OrderedDict()
_web_fetch_cache_size_bytes = 0
_web_fetch_cache_lock = threading.RLock()
_web_fetch_domain_check_cache = BoundedLruCache[str, float](_WEB_FETCH_DOMAIN_CHECK_CACHE_MAX_ENTRIES)

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


def web_search_handler(query: str, num_results: int = 5) -> str:
    """Search the web using the configured provider backend."""
    try:
        result = web_search_providers.search_web(query, num_results)
        return json.dumps(result, ensure_ascii=False)
    except Exception as e:
        logger.error(f"[web_search] 失败: {e}")
        return json.dumps(
            {
                "success": False,
                "error": f"搜索执行失败: {e}。建议直接使用 web_fetch 抓取目标网页内容",
                "data": {"web": []},
            },
            ensure_ascii=False,
        )


# =========================================================================
# web_fetch
# =========================================================================

WEB_FETCH_SCHEMA = make_tool_schema(
    name="web_fetch",
    description=(
        "抓取指定 URL 的内容；HTTP 自动升级 HTTPS，HTML 转 Markdown，"
        "同域重定向自动跟随，并带 15 分钟 LRU 缓存。"
    ),
    properties={
        "url": {"type": "string", "description": "要抓取的网页 URL"},
        "max_length": {
            "type": "integer",
            "description": (
                f"返回内容最大字符数，默认 {_WEB_FETCH_MAX_LENGTH}。抓取列表页、聚合页、"
                "trending 页时不要主动降低该值，否则会遗漏条目。"
            ),
        },
        "prompt": {
            "type": "string",
            "description": "可选：基于网页内容生成一个轻量结果，例如标题或摘要。",
        },
    },
    required=["url"],
)


def web_fetch_handler(
    url: str,
    max_length: int = _WEB_FETCH_MAX_LENGTH,
    prompt: str | None = None,
) -> str:
    """Fetch URL content and return Markdown/text in the legacy JSON shape."""
    try:
        original_url = str(url or "").strip()
        safe_url = _validate_web_fetch_url(original_url)
        max_length = _normalize_web_fetch_max_length(max_length)
        max_length, max_length_adjusted = _adjust_web_fetch_max_length(safe_url, max_length)
        started = time.monotonic()
        fetched = _get_url_markdown_content(original_url, safe_url)

        if isinstance(fetched, _WebFetchRedirect):
            return _web_fetch_redirect_json(fetched, prompt, started)

        full_text = fetched.content
        text = full_text[:max_length]

        response = {
            "success": True,
            "url": fetched.final_url,
            "content": text,
            "truncated": len(full_text) > max_length,
            "status": fetched.code,
            "status_text": fetched.code_text,
            "bytes": fetched.bytes,
            "duration_ms": int((time.monotonic() - started) * 1000),
            "content_type": fetched.content_type,
        }
        if max_length_adjusted:
            response["max_length_adjusted"] = True
        if fetched.persisted_reference_id:
            response["binary"] = {
                "reference_id": fetched.persisted_reference_id,
                "size_bytes": fetched.persisted_size or fetched.bytes,
                "content_type": fetched.content_type,
            }
        prompt_result = _summarize_web_fetch_for_prompt(
            fetched.final_url,
            prompt,
            full_text,
            fetched.title,
            fetched.persisted_reference_id,
            fetched.content_type,
            fetched.persisted_size or fetched.bytes,
        )
        if prompt_result is not None:
            response["result"] = prompt_result
        return json.dumps(response, ensure_ascii=False)
    except Exception as e:
        logger.error(f"[web_fetch] 失败: {e}")
        return error_json(e)


def _normalize_web_fetch_max_length(max_length: int) -> int:
    try:
        parsed = int(max_length)
    except (TypeError, ValueError):
        return _WEB_FETCH_MAX_LENGTH
    return max(1, min(parsed, _WEB_FETCH_MAX_LENGTH))


def _adjust_web_fetch_max_length(safe_url: str, max_length: int) -> tuple[int, bool]:
    if _is_known_web_fetch_list_page(safe_url) and max_length < _WEB_FETCH_MAX_LENGTH:
        return _WEB_FETCH_MAX_LENGTH, True
    return max_length, False


def _is_known_web_fetch_list_page(safe_url: str) -> bool:
    parsed = urllib.parse.urlsplit(safe_url)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    path = (parsed.path or "/").rstrip("/") or "/"
    return host == "github.com" and path == "/trending"


class _DomainBlockedError(RuntimeError):
    def __init__(self, domain: str) -> None:
        super().__init__(f"Claude Code is unable to fetch from {domain}")


class _DomainCheckFailedError(RuntimeError):
    def __init__(self, domain: str) -> None:
        super().__init__(
            "Unable to verify if domain "
            f"{domain} is safe to fetch. This may be due to network restrictions "
            "or enterprise security policies blocking claude.ai."
        )


class _EgressBlockedError(RuntimeError):
    def __init__(self, domain: str) -> None:
        super().__init__(
            json.dumps(
                {
                    "error_type": "EGRESS_BLOCKED",
                    "domain": domain,
                    "message": f"Access to {domain} is blocked by the network egress proxy.",
                },
                ensure_ascii=False,
            )
        )


def _validate_web_fetch_url(url: str) -> str:
    candidate = str(url or "").strip()
    if len(candidate) > _WEB_FETCH_MAX_URL_LENGTH:
        raise ValueError("web_fetch URL 超过 2000 字符限制")
    parsed = urllib.parse.urlsplit(candidate)
    if parsed.scheme.lower() not in _WEB_FETCH_ALLOWED_SCHEMES:
        raise ValueError("web_fetch 只允许 http/https URL")
    if not parsed.hostname:
        raise ValueError("web_fetch URL 缺少主机名")
    if parsed.username or parsed.password:
        raise ValueError("web_fetch URL 不允许包含 username/password")
    _web_fetch_port(parsed)
    _reject_private_web_fetch_host(parsed.hostname)
    return _normalize_web_fetch_url(parsed)


def _normalize_web_fetch_url(parsed) -> str:
    scheme = parsed.scheme.lower()
    host = _encode_web_fetch_host(parsed.hostname or "")
    if scheme == "http":
        scheme = "https"
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"

    port = parsed.port
    default_port = 443 if scheme == "https" else 80
    port_part = "" if port is None or port == default_port else f":{port}"
    netloc = f"{host}{port_part}"
    path = urllib.parse.quote(parsed.path or "/", safe="/:%@!$&'()*+,;=")
    query = urllib.parse.quote(parsed.query, safe="=&?/:;+,%@!$'()*")
    return urllib.parse.urlunsplit((scheme, netloc, path, query, ""))


def _encode_web_fetch_host(host: str) -> str:
    host = host.strip("[]").rstrip(".")
    if ":" in host:
        return host
    try:
        return host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ValueError(f"web_fetch URL 主机名非法: {host}") from exc


def _reject_private_web_fetch_host(host: str) -> None:
    normalized = host.strip("[]").rstrip(".").lower()
    if normalized in _WEB_FETCH_LOCAL_HOSTNAMES or normalized.endswith(".localhost"):
        raise ValueError("web_fetch 拒绝 localhost 或内网地址")
    try:
        ip = ipaddress.ip_address(normalized)
    except ValueError:
        if len([part for part in normalized.split(".") if part]) < 2:
            raise ValueError("web_fetch URL 主机名必须是公开域名")
        return
    mapped = getattr(ip, "ipv4_mapped", None)
    if not ip.is_global or (mapped is not None and not mapped.is_global):
        raise ValueError("web_fetch 拒绝 localhost 或内网地址")


def _get_url_markdown_content(
    original_url: str,
    safe_url: str,
) -> _FetchedWebContent | _WebFetchRedirect:
    cached = _get_web_fetch_cache(original_url)
    if cached is not None:
        return cached

    parsed = urllib.parse.urlsplit(safe_url)
    hostname = parsed.hostname or ""
    _check_web_fetch_domain_blocklist(hostname)

    response = _get_with_permitted_redirects(safe_url)
    if isinstance(response, _WebFetchRedirect):
        return response

    final_url, raw, status, status_text, content_type = response
    decoded = _decode_web_fetch_bytes(raw, content_type)
    title = _extract_web_fetch_title(decoded) if "text/html" in content_type.lower() else None
    if "text/html" in content_type.lower():
        content = _extract_text_from_html(decoded)
    else:
        content = decoded

    persisted_reference_id = None
    persisted_size = None
    if _is_binary_web_fetch_content_type(content_type):
        persisted_reference_id = _persist_web_fetch_binary(raw, content_type)
        persisted_size = len(raw) if persisted_reference_id else None

    fetched = _FetchedWebContent(
        final_url=final_url,
        content=content,
        bytes=len(raw),
        code=status,
        code_text=status_text,
        content_type=content_type,
        title=title,
        persisted_reference_id=persisted_reference_id,
        persisted_size=persisted_size,
    )
    _set_web_fetch_cache(original_url, fetched)
    return fetched


def _get_with_permitted_redirects(
    url: str,
    depth: int = 0,
) -> tuple[str, bytes, int | None, str, str] | _WebFetchRedirect:
    if depth > _WEB_FETCH_MAX_REDIRECTS:
        raise ValueError(f"Too many redirects (exceeded {_WEB_FETCH_MAX_REDIRECTS})")

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": BUILTIN_WEB_USER_AGENT,
            "Accept": "text/markdown, text/html, */*",
            "Accept-Encoding": "identity",
        },
        method="GET",
    )
    try:
        deadline = time.monotonic() + _WEB_FETCH_TIMEOUT
        with _open_web_fetch_url(request, timeout=_WEB_FETCH_TIMEOUT) as resp:
            raw = _read_web_fetch_response_bytes(resp, deadline)
            status = getattr(resp, "status", None)
            return (
                resp.geturl(),
                raw,
                status,
                str(getattr(resp, "reason", "") or _http_status_text(status)),
                str(resp.headers.get("Content-Type", "") or ""),
            )
    except urllib.error.HTTPError as exc:
        if exc.code in _WEB_FETCH_REDIRECT_STATUSES:
            location = exc.headers.get("Location")
            if not location:
                raise ValueError("Redirect missing Location header") from exc
            redirect_url = urllib.parse.urljoin(url, location)
            if _is_permitted_web_fetch_redirect(url, redirect_url):
                return _get_with_permitted_redirects(redirect_url, depth + 1)
            return _WebFetchRedirect(
                original_url=url,
                redirect_url=redirect_url,
                status_code=exc.code,
            )
        if exc.code == 403 and exc.headers.get("X-Proxy-Error") == "blocked-by-allowlist":
            domain = urllib.parse.urlsplit(url).hostname or ""
            raise _EgressBlockedError(domain) from exc
        raise


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_WEB_FETCH_OPENER = urllib.request.build_opener(_NoRedirectHandler)


def _open_web_fetch_url(request: urllib.request.Request, timeout: int):
    return _WEB_FETCH_OPENER.open(request, timeout=timeout)


_READ_CHUNK = 65536


def _read_web_fetch_response_bytes(resp, deadline: float) -> bytes:
    content_length = resp.headers.get("Content-Length")
    if content_length:
        try:
            if int(content_length) > _WEB_FETCH_MAX_BYTES:
                raise ValueError("web_fetch 响应超过 10MB 下载限制")
        except ValueError as exc:
            if "10MB" in str(exc):
                raise
    chunks: list[bytes] = []
    total = 0
    while True:
        if time.monotonic() > deadline:
            raise TimeoutError(f"web_fetch 响应读取超过 {_WEB_FETCH_TIMEOUT} 秒总超时限制")
        to_read = min(_READ_CHUNK, _WEB_FETCH_MAX_BYTES + 1 - total)
        chunk = resp.read(to_read)
        if not chunk:
            break
        total += len(chunk)
        if total > _WEB_FETCH_MAX_BYTES:
            raise ValueError("web_fetch 响应超过 10MB 下载限制")
        chunks.append(chunk)
    return b"".join(chunks)


def _decode_web_fetch_bytes(raw: bytes, content_type: str) -> str:
    charset = _charset_from_web_fetch_content_type(content_type) or _sniff_web_fetch_charset(raw)
    charset = charset or "utf-8"
    return raw.decode(charset, errors="replace")


def _charset_from_web_fetch_content_type(content_type: str) -> str | None:
    lowered = str(content_type or "").lower()
    marker = "charset="
    idx = lowered.find(marker)
    if idx < 0:
        return None
    value = str(content_type)[idx + len(marker) : idx + len(marker) + 80]
    value = value.strip(" \t\r\n'\";/>")
    chars = []
    for ch in value:
        if ch.isalnum() or ch in {"-", "_", "."}:
            chars.append(ch)
        else:
            break
    return "".join(chars) or None


def _check_web_fetch_domain_blocklist(domain: str) -> None:
    if _web_fetch_domain_check_cache_has(domain):
        return

    url = f"{_WEB_FETCH_DOMAIN_INFO_URL}?domain=" f"{urllib.parse.quote(domain, safe='')}"
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": BUILTIN_WEB_USER_AGENT,
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=_WEB_FETCH_DOMAIN_CHECK_TIMEOUT) as resp:
            status = getattr(resp, "status", None)
            body = resp.read(1_000_000)
    except Exception:
        logger.debug(
            "[web_fetch] domain blocklist check failed for %s, defaulting to allow",
            domain,
            exc_info=True,
        )
        _set_web_fetch_domain_check_cache(domain)
        return

    if status == 200:
        try:
            data = json.loads(body.decode("utf-8", errors="replace"))
        except json.JSONDecodeError:
            logger.debug(
                "[web_fetch] domain_info response parse error for %s, defaulting to allow", domain
            )
            _set_web_fetch_domain_check_cache(domain)
            return
        if data.get("can_fetch") is True:
            _set_web_fetch_domain_check_cache(domain)
            return
        raise _DomainBlockedError(domain)
    # 非 200 响应也默认放行（可能是代理/拦截返回的非标准状态码）
    logger.debug(
        "[web_fetch] domain_info returned status %s for %s, defaulting to allow", status, domain
    )
    _set_web_fetch_domain_check_cache(domain)


def _is_permitted_web_fetch_redirect(original_url: str, redirect_url: str) -> bool:
    try:
        original = urllib.parse.urlsplit(original_url)
        redirect = urllib.parse.urlsplit(redirect_url)
        if redirect.scheme != original.scheme:
            return False
        if _web_fetch_port(redirect) != _web_fetch_port(original):
            return False
        if redirect.username or redirect.password:
            return False
        original_host = (original.hostname or "").lower().removeprefix("www.")
        redirect_host = (redirect.hostname or "").lower().removeprefix("www.")
        return original_host == redirect_host
    except Exception:
        return False


def _http_status_text(status: int | None) -> str:
    if status is None:
        return ""
    try:
        return HTTPStatus(int(status)).phrase
    except ValueError:
        return ""


def _web_fetch_redirect_json(
    redirect: _WebFetchRedirect,
    prompt: str | None,
    started: float,
) -> str:
    status_text = _http_status_text(redirect.status_code)
    prompt_text = str(prompt or "")
    message = (
        "REDIRECT DETECTED: The URL redirects to a different host.\n\n"
        f"Original URL: {redirect.original_url}\n"
        f"Redirect URL: {redirect.redirect_url}\n"
        f"Status: {redirect.status_code} {status_text}\n\n"
        "To complete your request, fetch content from the redirected URL with:\n"
        f'- url: "{redirect.redirect_url}"\n'
        f'- prompt: "{prompt_text}"'
    )
    return json.dumps(
        {
            "success": True,
            "url": redirect.original_url,
            "content": message,
            "result": message,
            "redirect": True,
            "redirect_url": redirect.redirect_url,
            "status": redirect.status_code,
            "status_text": status_text,
            "bytes": len(message.encode("utf-8")),
            "duration_ms": int((time.monotonic() - started) * 1000),
        },
        ensure_ascii=False,
    )


def _get_web_fetch_cache(key: str) -> _FetchedWebContent | None:
    now = time.monotonic()
    with _web_fetch_cache_lock:
        entry = _web_fetch_cache.get(key)
        if entry is None:
            return None
        if entry.expires_at <= now:
            _delete_web_fetch_cache_entry(key)
            return None
        _web_fetch_cache.move_to_end(key)
        return entry.content


def _set_web_fetch_cache(key: str, content: _FetchedWebContent) -> None:
    size_bytes = max(1, len(content.content.encode("utf-8", errors="replace")))
    if size_bytes > _WEB_FETCH_CACHE_MAX_BYTES:
        return
    with _web_fetch_cache_lock:
        _delete_web_fetch_cache_entry(key)
        _web_fetch_cache[key] = _WebFetchCacheEntry(
            content=content,
            size_bytes=size_bytes,
            expires_at=time.monotonic() + _WEB_FETCH_CACHE_TTL_SECONDS,
        )
        _add_web_fetch_cache_size(size_bytes)
        while _web_fetch_cache_size_bytes > _WEB_FETCH_CACHE_MAX_BYTES and _web_fetch_cache:
            oldest_key = next(iter(_web_fetch_cache))
            _delete_web_fetch_cache_entry(oldest_key)


def _delete_web_fetch_cache_entry(key: str) -> None:
    entry = _web_fetch_cache.pop(key, None)
    if entry is not None:
        _add_web_fetch_cache_size(-entry.size_bytes)


def _add_web_fetch_cache_size(delta: int) -> None:
    global _web_fetch_cache_size_bytes
    _web_fetch_cache_size_bytes = max(0, _web_fetch_cache_size_bytes + delta)


def _web_fetch_domain_check_cache_has(domain: str) -> bool:
    now = time.monotonic()
    expires_at = _web_fetch_domain_check_cache.get(domain)
    if expires_at is None:
        return False
    if expires_at <= now:
        _web_fetch_domain_check_cache.remove(domain)
        return False
    return True


def _set_web_fetch_domain_check_cache(domain: str) -> None:
    _web_fetch_domain_check_cache.put(
        domain,
        time.monotonic() + _WEB_FETCH_DOMAIN_CHECK_CACHE_TTL_SECONDS,
    )


def clear_web_fetch_cache() -> None:
    global _web_fetch_cache_size_bytes
    with _web_fetch_cache_lock:
        _web_fetch_cache.clear()
        _web_fetch_cache_size_bytes = 0
    _web_fetch_domain_check_cache.clear()


def _sniff_web_fetch_charset(raw: bytes) -> str | None:
    head = raw[:4096].decode("ascii", errors="ignore")
    meta_match = urllib.parse.unquote(head).lower()
    for marker in ("charset=", "encoding="):
        idx = meta_match.find(marker)
        if idx < 0:
            continue
        value = meta_match[idx + len(marker) : idx + len(marker) + 40]
        value = value.strip(" \t\r\n'\";/>")
        charset = []
        for ch in value:
            if ch.isalnum() or ch in {"-", "_", "."}:
                charset.append(ch)
            else:
                break
        if charset:
            return "".join(charset)
    return None


def _web_fetch_port(parsed) -> int:
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("web_fetch URL 端口非法") from exc
    if port is not None:
        return port
    return 443 if parsed.scheme.lower() == "https" else 80


def _is_binary_web_fetch_content_type(content_type: str) -> bool:
    if not content_type:
        return False
    media_type = (content_type.split(";", 1)[0] or "").strip().lower()
    if media_type.startswith("text/"):
        return False
    if media_type.endswith("+json") or media_type == "application/json":
        return False
    if media_type.endswith("+xml") or media_type == "application/xml":
        return False
    if media_type.startswith("application/javascript"):
        return False
    if media_type == "application/x-www-form-urlencoded":
        return False
    return True


def _persist_web_fetch_binary(raw: bytes, content_type: str) -> str | None:
    try:
        from src.data.repos.tool_output_repository import ToolOutputRepository

        runtime = current_tool_runtime()
        model = ToolOutputRepository().create_reference(
            session_id=runtime_session_id(),
            tool_name="web_fetch",
            tool_call_id=runtime.tool_call_id if runtime is not None else None,
            kind="web_fetch_binary",
            data=raw,
            workspace_root=runtime_workspace_root(),
            content_type=content_type or "application/octet-stream",
            retention_days=14,
        )
        return model.reference_id
    except Exception:
        logger.warning("[web_fetch] binary content persistence failed", exc_info=True)
        return None


def _format_web_fetch_size(size_in_bytes: int) -> str:
    kb = size_in_bytes / 1024
    if kb < 1:
        return f"{size_in_bytes} bytes"
    if kb < 1024:
        return f"{kb:.1f}".rstrip("0").rstrip(".") + "KB"
    mb = kb / 1024
    if mb < 1024:
        return f"{mb:.1f}".rstrip("0").rstrip(".") + "MB"
    gb = mb / 1024
    return f"{gb:.1f}".rstrip("0").rstrip(".") + "GB"


def _extract_text_from_html(html: str) -> str:
    return html_to_markdown(
        html,
        heading_style="ATX",
        bullets="*+-",
    ).strip()


def _summarize_web_fetch_for_prompt(
    final_url: str,
    prompt: str | None,
    content: str,
    title: str | None,
    persisted_reference_id: str | None,
    content_type: str,
    persisted_size: int,
) -> str | None:
    prompt_text = str(prompt or "").strip()
    if not prompt_text:
        return None

    lower_prompt = prompt_text.lower()
    compact = _collapse_web_fetch_whitespace(content)
    if "title" in lower_prompt or "标题" in prompt_text:
        title = title or _first_nonempty_web_fetch_line(content)
        detail = (
            f"Title: {title}"
            if title
            else _preview_web_fetch_text(compact, _WEB_FETCH_TITLE_FALLBACK_CHARS)
        )
    elif any(
        keyword in lower_prompt
        for keyword in ("summary", "summarize", "摘要", "总结", "概括", "简介")
    ):
        detail = _preview_web_fetch_text(compact, _WEB_FETCH_PROMPT_PREVIEW_CHARS)
    else:
        preview = _preview_web_fetch_text(compact, _WEB_FETCH_PROMPT_PREVIEW_CHARS)
        detail = f"Prompt: {prompt_text}\nContent preview:\n{preview}"

    result = f"Fetched {final_url}\n{detail}"
    if persisted_reference_id:
        result += (
            f"\n\n[Binary content ({content_type or 'unknown type'}, "
            f"{_format_web_fetch_size(persisted_size)}) also saved as "
            f"tool output reference {persisted_reference_id}]"
        )
    return result


def _extract_web_fetch_title(raw_html: str) -> str | None:
    lowered = raw_html.lower()
    start = lowered.find("<title")
    if start < 0:
        return None
    start = lowered.find(">", start)
    if start < 0:
        return None
    end = lowered.find("</title>", start)
    if end < 0:
        return None
    title = html_lib.unescape(raw_html[start + 1 : end])
    title = _collapse_web_fetch_whitespace(title)
    return title or None


def _first_nonempty_web_fetch_line(content: str) -> str:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return ""


def _collapse_web_fetch_whitespace(value: str) -> str:
    return " ".join(value.split())


def _preview_web_fetch_text(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[:max_chars].rstrip() + "..."


def _resolve_path_arg(ctx: ToolCallContext, key: str = "path", default: str | None = None) -> Path:
    raw = ctx.args.get(key, default)
    if raw is None:
        raise KeyError(key)
    path = Path(str(raw)).expanduser()
    candidate = path if path.is_absolute() else runtime_workspace_root() / path
    try:
        return candidate.resolve(strict=False)
    except OSError:
        return candidate.absolute()


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
    workspace_root = runtime_workspace_root()
    check = permission_for_path(cwd, operation="execute", workspace_root=workspace_root)
    if not check.allowed:
        return PreHookResult(
            error=check.message or "命令执行目录被权限策略拒绝",
            error_code=check.error_code or "command_rejected",
        )
    path_check = command_path_policy_violation(
        command,
        workspace_root=workspace_root,
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
        "extractionGoal": {
            "type": "string",
            "maxLength": 1000,
            "description": "Optional goal used only to focus large-output summarization",
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
    extractionGoal: str | None = None,
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
        "extractionGoal": {
            "type": "string",
            "maxLength": 1000,
            "description": "Optional goal used only to focus large-output summarization",
        },
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
    extractionGoal: str | None = None,
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
        "extractionGoal": {"type": "string", "maxLength": 1000},
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
        "extractionGoal": {"type": "string", "maxLength": 1000},
    },
    required=["pattern"],
)


PROCESS_LIST_SCHEMA = make_tool_schema(
    name="process_list",
    description="List current sidecar-session background processes.",
    properties={"status": {"type": "string"}},
    required=[],
)


def _make_process_id_tool_schema(name: str, description: str) -> dict:
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
        "extractionGoal": {"type": "string", "maxLength": 1000},
    },
    required=["processId"],
)


PROCESS_WAIT_SCHEMA = make_tool_schema(
    name="process_wait",
    description="Wait up to timeoutMs for a current-session background process.",
    properties={
        "processId": {"type": "string"},
        "timeoutMs": {"type": "integer"},
        "extractionGoal": {"type": "string", "maxLength": 1000},
    },
    required=["processId"],
)


WAIT_FOR_PROCESS_EVENT_SCHEMA = make_tool_schema(
    name="wait_for_process_event",
    description=(
        "Block until a new event on a current-session background process or "
        "timeout. Events are coarse signals (state_changed / log_chunked / "
        "stalled) without log content; read actual stdout/stderr via "
        "process_logs. On the first call omit sinceCursor; on subsequent "
        "calls pass the cursor from the previous response."
    ),
    properties={
        "processId": {"type": "string"},
        "sinceCursor": {"type": "integer", "minimum": 0},
        "timeoutMs": {"type": "integer"},
    },
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
    description=(
        "加载被压缩（compacted）的工具输出原始内容。"
        "仅当 compacted envelope 的 preview 不足以完成任务时使用。\n\n"
        "使用场景：\n"
        "- preview 中标注了内容被截断，且缺失的信息对完成任务必需\n"
        "- 你需要验证某个具体数据点，而 preview 中没有\n\n"
        "不要使用：\n"
        "- preview/facts 已包含足够信息（大多数情况如此）\n"
        '- 仅为了"确认"或"补充"已有信息\n\n'
        "注意：每次调用会触发额外一轮 LLM 推理，优先用 preview 完成任务。"
    ),
    properties={
        "referenceId": {"type": "string"},
        "offset": {"type": "integer"},
        "maxBytes": {"type": "integer"},
        "renderAs": {"type": "string", "enum": ["text"]},
        "extractionGoal": {"type": "string", "maxLength": 1000},
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
    extractionGoal: str | None = None,
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
    extractionGoal: str | None = None,
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
    extractionGoal: str | None = None,
) -> str:
    return output_governance.load_tool_output_handler(
        referenceId=referenceId,
        offset=offset,
        maxBytes=maxBytes,
        renderAs=renderAs,
        extractionGoal=extractionGoal,
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
        is_concurrency_safe=True,
    ),
    ToolDefinition(
        name="web_fetch",
        schema=WEB_FETCH_SCHEMA,
        handler=web_fetch_handler,
        has_side_effects=False,
        is_concurrency_safe=True,
    ),
    ToolDefinition(
        name="read_file",
        schema=READ_FILE_SCHEMA,
        handler=read_file_handler,
        pre_hook=read_file_pre_hook,
        has_side_effects=False,
        is_concurrency_safe=True,
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
        is_concurrency_safe=True,
    ),
    ToolDefinition(
        name="search_content",
        schema=SEARCH_CONTENT_SCHEMA,
        handler=search_content_handler,
        has_side_effects=False,
        is_concurrency_safe=True,
    ),
    ToolDefinition(
        name="list_dir",
        schema=LIST_DIR_SCHEMA,
        handler=list_dir_handler,
        pre_hook=list_dir_pre_hook,
        has_side_effects=False,
        is_concurrency_safe=True,
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
        schema=_make_process_id_tool_schema(
            "process_poll", "Poll a current-session background process."
        ),
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
        name="wait_for_process_event",
        schema=WAIT_FOR_PROCESS_EVENT_SCHEMA,
        handler=command_tools.wait_for_process_event_handler,
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
        schema=_make_process_id_tool_schema(
            "process_close", "Close a completed or stopped process record."
        ),
        handler=command_tools.process_close_handler,
    ),
    ToolDefinition(
        name="load_tool_output",
        schema=LOAD_TOOL_OUTPUT_SCHEMA,
        handler=load_tool_output_handler,
        has_side_effects=False,
        is_concurrency_safe=True,
    ),
]


# 主助理 builtin general 工具子集：100% 调度硬边界。
# main assistant 不直接读取网页/文件/目录/进程输出，也不直接执行用户动态工具；
# 这些工作必须委派给 ephemeral executor 或 specialist。协调类工具
# (delegate/build_task_graph/decide/load_task_result 等 assistant_tools)不在此列。
# executor/specialist 仍用全量 BUILTIN_GENERAL_TOOLS。
# 主助理禁止直接调用的 builtin general 工具名全集。
# 名称含义：这些工具名全部被禁止，而非「禁止集合只含部分」。
# 运行时拒绝由 agent_loop._assistant_forbidden_tool_reason 消费。
ALL_BUILTIN_GENERAL_TOOL_NAMES = frozenset(tool.name for tool in BUILTIN_GENERAL_TOOLS)


__all__ = [
    "ALL_BUILTIN_GENERAL_TOOL_NAMES",
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
