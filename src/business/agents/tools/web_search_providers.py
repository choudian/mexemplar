"""Provider registry and built-in backends for the web_search tool."""

from __future__ import annotations

from abc import ABC, abstractmethod
from html.parser import HTMLParser
import html
import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Iterable

from src.business.agents.tools.builtin_contracts import BUILTIN_WEB_USER_AGENT
from src.data.unified_config import get_unified_config

logger = logging.getLogger(__name__)

WEB_SEARCH_BACKEND_AUTO = "auto"
BRAVE_FREE_BACKEND = "brave-free"
DDG_HTML_BACKEND = "ddg-html"
DDGS_BACKEND = "ddgs"

SUPPORTED_WEB_SEARCH_BACKENDS = (
    WEB_SEARCH_BACKEND_AUTO,
    BRAVE_FREE_BACKEND,
    DDG_HTML_BACKEND,
    DDGS_BACKEND,
)
AUTO_WEB_SEARCH_ORDER = (BRAVE_FREE_BACKEND, DDG_HTML_BACKEND, DDGS_BACKEND)

_MAX_RESULTS = 20
_DDG_HTML_MAX_RESULTS = 8
_DEFAULT_RESULTS = 5
_SEARCH_TIMEOUT_SECONDS = 10

# Circuit breaker: 连续 N 次返回空结果后暂时禁用 provider
_EMPTY_RESULT_THRESHOLD = 2
_EMPTY_RESULT_COOLDOWN_SECONDS = 600  # 10 分钟


class WebSearchProviderError(RuntimeError):
    """Base provider failure."""


class WebSearchProviderUnavailable(WebSearchProviderError):
    """Provider cannot run with the current configuration."""


class WebSearchEmptyResultError(WebSearchProviderError):
    """Provider completed the request but produced no usable search results."""


class _EmptyResultCircuitBreaker:
    """Track consecutive empty results per provider; temporarily disable after threshold."""

    def __init__(self) -> None:
        self._consecutive_empties: dict[str, int] = {}
        self._disabled_until: dict[str, float] = {}
        self._lock = threading.Lock()

    def is_open(self, provider_name: str) -> bool:
        """Return True if provider is circuit-broken (should skip)."""
        with self._lock:
            until = self._disabled_until.get(provider_name, 0)
            if until and time.monotonic() < until:
                return True
            # Cooldown expired, reset
            if until:
                self._disabled_until.pop(provider_name, None)
                self._consecutive_empties.pop(provider_name, None)
            return False

    def record_success(self, provider_name: str) -> None:
        """Record that provider returned results — reset counter."""
        with self._lock:
            self._consecutive_empties.pop(provider_name, None)
            self._disabled_until.pop(provider_name, None)

    def record_empty(self, provider_name: str) -> None:
        """Record an empty result; trip breaker if threshold reached."""
        with self._lock:
            count = self._consecutive_empties.get(provider_name, 0) + 1
            self._consecutive_empties[provider_name] = count
            if count >= _EMPTY_RESULT_THRESHOLD:
                self._disabled_until[provider_name] = (
                    time.monotonic() + _EMPTY_RESULT_COOLDOWN_SECONDS
                )
                logger.warning(
                    "[web_search] provider %s 连续 %d 次返回空结果，暂停 %d 秒",
                    provider_name,
                    count,
                    _EMPTY_RESULT_COOLDOWN_SECONDS,
                )

    def reset(self) -> None:
        with self._lock:
            self._consecutive_empties.clear()
            self._disabled_until.clear()


_EMPTY_RESULT_BREAKER = _EmptyResultCircuitBreaker()


class WebSearchProvider(ABC):
    """Search provider interface for the web_search tool."""

    name: str

    def supports_search(self) -> bool:
        return True

    def supports_extract(self) -> bool:
        return False

    @abstractmethod
    def is_available(self) -> bool:
        """Return whether this provider can be used right now."""

    @abstractmethod
    def search(self, query: str, num_results: int) -> list[dict[str, Any]]:
        """Return normalized-ish result dictionaries for *query*."""

    def extract(self, _url: str) -> dict[str, Any]:
        raise NotImplementedError(f"{self.name} does not support extract")


class WebSearchProviderRegistry:
    """Thread-safe provider registry."""

    def __init__(self) -> None:
        self._providers: dict[str, WebSearchProvider] = {}
        self._lock = threading.RLock()

    def register_provider(self, provider: WebSearchProvider) -> None:
        if not isinstance(provider.name, str) or not provider.name:
            raise ValueError("provider.name must be a non-empty string")
        with self._lock:
            self._providers[provider.name] = provider

    def get_provider(self, name: str) -> WebSearchProvider | None:
        with self._lock:
            return self._providers.get(name)

    def provider_names(self) -> list[str]:
        with self._lock:
            return sorted(self._providers)

    def clear(self) -> None:
        with self._lock:
            self._providers.clear()


class BraveSearchProvider(WebSearchProvider):
    name = BRAVE_FREE_BACKEND

    def __init__(self, config: Any | None = None) -> None:
        self._config = config

    def is_available(self) -> bool:
        return bool(self._api_key())

    def search(self, query: str, num_results: int) -> list[dict[str, Any]]:
        api_key = self._api_key()
        if not api_key:
            raise WebSearchProviderUnavailable("Brave API Key 未设置")

        payload = self._request_json(query, api_key, _normalize_num_results(num_results))
        web_results = payload.get("web", {}).get("results", [])
        if not isinstance(web_results, list):
            raise WebSearchProviderError("Brave Search API 返回格式不正确")

        results: list[dict[str, Any]] = []
        for item in web_results:
            if not isinstance(item, dict):
                continue
            results.append(
                {
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "description": item.get("description", ""),
                }
            )
        return results

    def _api_key(self) -> str | None:
        config = self._config or get_unified_config()
        getter = getattr(config, "get_web_brave_api_key", None)
        if not callable(getter):
            return None
        value = getter()
        if not isinstance(value, str):
            return None
        value = value.strip()
        return value or None

    @staticmethod
    def _request_json(query: str, api_key: str, count: int) -> dict[str, Any]:
        params = urllib.parse.urlencode({"q": query, "count": count})
        request = urllib.request.Request(
            f"https://api.search.brave.com/res/v1/web/search?{params}",
            headers={
                "Accept": "application/json",
                "Accept-Encoding": "identity",
                "User-Agent": BUILTIN_WEB_USER_AGENT,
                "X-Subscription-Token": api_key,
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=_SEARCH_TIMEOUT_SECONDS) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raise WebSearchProviderError(f"Brave Search API 请求失败: HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise WebSearchProviderError(f"Brave Search API 网络失败: {exc.reason}") from exc

        try:
            decoded = raw.decode("utf-8")
            payload = json.loads(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WebSearchProviderError("Brave Search API 返回了无法解析的 JSON") from exc
        if not isinstance(payload, dict):
            raise WebSearchProviderError("Brave Search API 返回格式不正确")
        return payload


class _DdgHtmlResultParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[dict[str, str]] = []
        self._href: str | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a" or self._href is not None:
            return
        attr_map = {key.lower(): value or "" for key, value in attrs}
        classes = set(attr_map.get("class", "").split())
        if "result__a" not in classes:
            return
        self._href = attr_map.get("href", "")
        self._parts = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or self._href is None:
            return
        title = " ".join("".join(self._parts).split())
        self.results.append({"title": title, "url": self._href})
        self._href = None
        self._parts = []


class DdgHtmlSearchProvider(WebSearchProvider):
    name = DDG_HTML_BACKEND

    def is_available(self) -> bool:
        return True

    def search(self, query: str, num_results: int) -> list[dict[str, Any]]:
        limit = min(_normalize_num_results(num_results), _DDG_HTML_MAX_RESULTS)
        html_text = self._request_html(query)
        parser = _DdgHtmlResultParser()
        parser.feed(html_text)

        results: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in parser.results:
            url = _decode_ddg_redirect(item.get("url", ""))
            if not url or url in seen:
                continue
            seen.add(url)
            results.append(
                {
                    "title": item.get("title", ""),
                    "url": url,
                    "description": "",
                }
            )
            if len(results) >= limit:
                break
        if not results:
            raise WebSearchEmptyResultError(
                "DuckDuckGo HTML 请求成功但未解析到搜索结果，可能被网络屏蔽"
            )
        return results

    @staticmethod
    def _request_html(query: str) -> str:
        params = urllib.parse.urlencode({"q": query})
        request = urllib.request.Request(
            f"https://html.duckduckgo.com/html/?{params}",
            headers={
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.2",
                "Accept-Encoding": "identity",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "User-Agent": BUILTIN_WEB_USER_AGENT,
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=_SEARCH_TIMEOUT_SECONDS) as response:
                raw = response.read(1_000_000)
                charset = response.headers.get_content_charset() or "utf-8"
                return raw.decode(charset, errors="replace")
        except urllib.error.HTTPError as exc:
            raise WebSearchProviderError(f"DuckDuckGo HTML 请求失败: HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise WebSearchProviderError(f"DuckDuckGo HTML 网络失败: {exc.reason}") from exc


class DdgsSearchProvider(WebSearchProvider):
    name = DDGS_BACKEND

    def is_available(self) -> bool:
        return True

    def search(self, query: str, num_results: int) -> list[dict[str, Any]]:
        from src.execution.tool_executor import run_tool_code

        result = run_tool_code(
            code=_DDGS_SEARCH_CODE,
            parameters={"query": query, "num_results": _normalize_num_results(num_results)},
            dependencies=["duckduckgo-search"],
        )
        if not result.get("success"):
            raise WebSearchProviderError(str(result.get("message") or "ddgs 搜索执行失败"))
        data = result.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("web"), list):
            raise WebSearchProviderError("ddgs 搜索返回格式不正确")
        if not data["web"]:
            raise WebSearchEmptyResultError("ddgs 搜索返回空结果，可能被网络屏蔽")
        return data["web"]


_DDGS_SEARCH_CODE = """\
async def execute(**kwargs):
    from duckduckgo_search import DDGS

    query = kwargs["query"]
    num_results = int(kwargs.get("num_results", 5))

    results = []
    with DDGS() as ddgs:
        for index, r in enumerate(ddgs.text(query, max_results=num_results), start=1):
            results.append({
                "title": r.get("title", ""),
                "url": r.get("href", ""),
                "description": r.get("body", ""),
                "position": index,
            })
    return {"success": True, "data": {"web": results}}
"""


def search_web(
    query: str,
    num_results: int = _DEFAULT_RESULTS,
    *,
    config: Any | None = None,
    registry: WebSearchProviderRegistry | None = None,
) -> dict[str, Any]:
    query_text = str(query or "").strip()
    if not query_text:
        return _failure_response("搜索关键词不能为空")

    limit = _normalize_num_results(num_results)
    active_registry = registry or DEFAULT_WEB_SEARCH_REGISTRY
    backend = _configured_backend(config)
    provider_names = active_registry.provider_names()

    if backend == WEB_SEARCH_BACKEND_AUTO:
        candidates = [name for name in AUTO_WEB_SEARCH_ORDER if name in provider_names]
    elif backend in provider_names:
        candidates = [backend]
    else:
        return _failure_response(
            f"未知 web.search_backend: {backend}。支持: {', '.join(SUPPORTED_WEB_SEARCH_BACKENDS)}"
        )

    failures: list[str] = []
    explicit = backend != WEB_SEARCH_BACKEND_AUTO
    for provider_name in candidates:
        # Auto 模式下跳过 circuit-broken 的 provider
        if not explicit and _EMPTY_RESULT_BREAKER.is_open(provider_name):
            failures.append(f"{provider_name}: 连续空结果，暂时跳过")
            continue

        provider = active_registry.get_provider(provider_name)
        if provider is None:
            failures.append(f"{provider_name}: provider 未注册")
            continue
        try:
            if not provider.supports_search():
                raise WebSearchProviderUnavailable("provider 不支持 search")
            if not provider.is_available():
                raise WebSearchProviderUnavailable("provider 当前不可用")
            raw_results = provider.search(query_text, limit)
            normalized = _normalize_results(raw_results, limit)
            if normalized:
                _EMPTY_RESULT_BREAKER.record_success(provider_name)
                return _success_response(normalized)
            _EMPTY_RESULT_BREAKER.record_empty(provider_name)
            failures.append(_empty_result_message(provider_name))
            if explicit:
                break
        except WebSearchEmptyResultError as exc:
            _EMPTY_RESULT_BREAKER.record_empty(provider_name)
            failures.append(_empty_result_message(provider_name, str(exc)))
            if explicit:
                break
        except WebSearchProviderUnavailable as exc:
            failures.append(f"{provider_name}: {exc}")
            if explicit:
                break
        except Exception as exc:
            logger.warning("[web_search] provider failed: %s", provider_name, exc_info=True)
            failures.append(f"{provider_name}: {exc}")
            if explicit:
                break

    if not candidates:
        failures.append("未注册可用 provider")
    return _failure_response(
        "web_search 搜索失败: "
        + "; ".join(failures)
        + "。建议配置 Brave API Key，或直接使用 web_fetch 抓取已知目标网页内容"
    )


def register_provider(provider: WebSearchProvider) -> None:
    DEFAULT_WEB_SEARCH_REGISTRY.register_provider(provider)


def get_registered_provider_names() -> list[str]:
    return DEFAULT_WEB_SEARCH_REGISTRY.provider_names()


def _configured_backend(config: Any | None = None) -> str:
    cfg = config or get_unified_config()
    getter = getattr(cfg, "get_web_search_backend", None)
    raw = (
        getter()
        if callable(getter)
        else cfg.get("web.search_backend", default=WEB_SEARCH_BACKEND_AUTO)
    )
    backend = str(raw or WEB_SEARCH_BACKEND_AUTO).strip().lower()
    return backend or WEB_SEARCH_BACKEND_AUTO


def _normalize_num_results(num_results: int | str | None) -> int:
    try:
        parsed = int(num_results or _DEFAULT_RESULTS)
    except (TypeError, ValueError):
        parsed = _DEFAULT_RESULTS
    return max(1, min(parsed, _MAX_RESULTS))


def _normalize_results(results: Iterable[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in results:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or item.get("href") or "").strip()
        if not _is_http_url(url) or url in seen:
            continue
        seen.add(url)
        title = str(item.get("title") or "").strip() or url
        description = str(
            item.get("description") or item.get("snippet") or item.get("body") or ""
        ).strip()
        normalized.append(
            {
                "title": title,
                "url": url,
                "description": description,
                "position": len(normalized) + 1,
            }
        )
        if len(normalized) >= limit:
            break
    return normalized


def _decode_ddg_redirect(href: str) -> str:
    value = html.unescape(str(href or "").strip())
    if not value:
        return ""
    absolute = urllib.parse.urljoin("https://duckduckgo.com", value)
    parsed = urllib.parse.urlsplit(absolute)
    params = urllib.parse.parse_qs(parsed.query)
    uddg = params.get("uddg", [""])[0]
    candidate = urllib.parse.unquote(uddg) if uddg else absolute
    candidate = html.unescape(candidate)
    if not _is_http_url(candidate):
        return ""
    return urllib.parse.urldefrag(candidate)[0]


def _is_http_url(url: str) -> bool:
    parsed = urllib.parse.urlsplit(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _success_response(results: list[dict[str, Any]]) -> dict[str, Any]:
    return {"success": True, "data": {"web": results}}


def _empty_result_message(provider_name: str, detail: str | None = None) -> str:
    message = f"{provider_name}: 搜索被网络屏蔽或返回空结果"
    if detail:
        return f"{message}（{detail}）"
    return message


def _failure_response(message: str) -> dict[str, Any]:
    return {"success": False, "error": str(message), "data": {"web": []}}


DEFAULT_WEB_SEARCH_REGISTRY = WebSearchProviderRegistry()
DEFAULT_WEB_SEARCH_REGISTRY.register_provider(BraveSearchProvider())
DEFAULT_WEB_SEARCH_REGISTRY.register_provider(DdgHtmlSearchProvider())
DEFAULT_WEB_SEARCH_REGISTRY.register_provider(DdgsSearchProvider())


__all__ = [
    "AUTO_WEB_SEARCH_ORDER",
    "BRAVE_FREE_BACKEND",
    "DDG_HTML_BACKEND",
    "DDGS_BACKEND",
    "SUPPORTED_WEB_SEARCH_BACKENDS",
    "WEB_SEARCH_BACKEND_AUTO",
    "BraveSearchProvider",
    "DdgHtmlSearchProvider",
    "DdgsSearchProvider",
    "WebSearchProvider",
    "WebSearchEmptyResultError",
    "WebSearchProviderError",
    "WebSearchProviderRegistry",
    "WebSearchProviderUnavailable",
    "get_registered_provider_names",
    "register_provider",
    "search_web",
]
