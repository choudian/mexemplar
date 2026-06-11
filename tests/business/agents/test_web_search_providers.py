from __future__ import annotations

from email.message import Message
import json

import pytest

from src.business.agents.tools import builtin_general_tools
from src.business.agents.tools.web_search_providers import (
    BraveSearchProvider,
    DdgHtmlSearchProvider,
    DdgsSearchProvider,
    WebSearchProvider,
    WebSearchProviderError,
    WebSearchProviderRegistry,
    WebSearchProviderUnavailable,
    _EMPTY_RESULT_BREAKER,
    search_web,
)


class FakeConfig:
    def __init__(self, backend: str = "auto", brave_key: str | None = None) -> None:
        self.backend = backend
        self.brave_key = brave_key

    def get_web_search_backend(self) -> str:
        return self.backend

    def get_web_brave_api_key(self) -> str | None:
        return self.brave_key


class FakeProvider(WebSearchProvider):
    def __init__(
        self,
        name: str,
        *,
        available: bool = True,
        results: list[dict] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.name = name
        self.available = available
        self.results = results or []
        self.error = error
        self.calls = 0

    def is_available(self) -> bool:
        return self.available

    def search(self, query: str, num_results: int) -> list[dict]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.results


class FakeWebResponse:
    def __init__(self, body: bytes) -> None:
        self._body = body
        self.headers = Message()
        self.headers["Content-Type"] = "application/json; charset=utf-8"

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self, size=-1) -> bytes:
        if size is None or size < 0:
            return self._body
        return self._body[:size]


def test_auto_backend_falls_back_in_order() -> None:
    registry = WebSearchProviderRegistry()
    brave = FakeProvider("brave-free", available=False)
    ddg = FakeProvider("ddg-html", error=WebSearchProviderError("blocked"))
    ddgs = FakeProvider(
        "ddgs",
        results=[{"title": "Result", "url": "https://example.test", "description": "Body"}],
    )
    for provider in (brave, ddg, ddgs):
        registry.register_provider(provider)

    result = search_web("query", config=FakeConfig("auto"), registry=registry)

    assert result == {
        "success": True,
        "data": {
            "web": [
                {
                    "title": "Result",
                    "url": "https://example.test",
                    "description": "Body",
                    "position": 1,
                }
            ]
        },
    }
    assert brave.calls == 0
    assert ddg.calls == 1
    assert ddgs.calls == 1


def test_explicit_backend_does_not_fallback() -> None:
    registry = WebSearchProviderRegistry()
    brave = FakeProvider("brave-free", available=False)
    ddg = FakeProvider(
        "ddg-html",
        results=[{"title": "Should not run", "url": "https://example.test"}],
    )
    registry.register_provider(brave)
    registry.register_provider(ddg)

    result = search_web("query", config=FakeConfig("brave-free"), registry=registry)

    assert result["success"] is False
    assert result["data"] == {"web": []}
    assert "brave-free" in result["error"]
    assert ddg.calls == 0


def test_unknown_backend_returns_stable_failure() -> None:
    result = search_web("query", config=FakeConfig("unknown"), registry=WebSearchProviderRegistry())

    assert result["success"] is False
    assert result["data"] == {"web": []}
    assert "未知 web.search_backend" in result["error"]


def test_ddg_html_decodes_redirects_dedupes_and_truncates(monkeypatch) -> None:
    html = """
    <a class="result__a" href="/l/?uddg=https%3A%2F%2Fexample.test%2Fa">One &amp; Title</a>
    <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.test%2Fa">Duplicate</a>
    <a class="result__a" href="https://second.test/path#frag">Second</a>
    <a class="result__a" href="ftp://ignored.test/file">Ignored</a>
    <a class="result__a" href="https://third.test/">Third</a>
    """
    monkeypatch.setattr(DdgHtmlSearchProvider, "_request_html", staticmethod(lambda _query: html))

    results = DdgHtmlSearchProvider().search("query", 2)

    assert results == [
        {"title": "One & Title", "url": "https://example.test/a", "description": ""},
        {"title": "Second", "url": "https://second.test/path", "description": ""},
    ]


def test_ddg_html_empty_response_reports_possible_network_block(monkeypatch) -> None:
    monkeypatch.setattr(DdgHtmlSearchProvider, "_request_html", staticmethod(lambda _query: ""))
    registry = WebSearchProviderRegistry()
    registry.register_provider(DdgHtmlSearchProvider())

    result = search_web("query", config=FakeConfig("ddg-html"), registry=registry)

    assert result["success"] is False
    assert result["data"] == {"web": []}
    assert "ddg-html: 搜索被网络屏蔽或返回空结果" in result["error"]
    assert "请求成功但未解析到搜索结果" in result["error"]


def test_ddgs_empty_subprocess_result_returns_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.execution.tool_executor.run_tool_code",
        lambda **_kwargs: {"success": True, "data": {"web": []}},
    )
    registry = WebSearchProviderRegistry()
    registry.register_provider(DdgsSearchProvider())

    result = search_web("query", config=FakeConfig("ddgs"), registry=registry)

    assert result["success"] is False
    assert result["data"] == {"web": []}
    assert "ddgs: 搜索被网络屏蔽或返回空结果" in result["error"]
    assert "ddgs 搜索返回空结果，可能被网络屏蔽" in result["error"]


def test_all_empty_providers_return_actionable_failure() -> None:
    registry = WebSearchProviderRegistry()
    providers = [
        FakeProvider("brave-free", results=[]),
        FakeProvider("ddg-html", results=[]),
        FakeProvider("ddgs", results=[]),
    ]
    for provider in providers:
        registry.register_provider(provider)

    result = search_web("query", config=FakeConfig("auto"), registry=registry)

    assert result["success"] is False
    assert result["data"] == {"web": []}
    assert "web_search 搜索失败" in result["error"]
    assert "配置 Brave API Key" in result["error"]
    assert "web_fetch" in result["error"]
    assert [provider.calls for provider in providers] == [1, 1, 1]


def test_brave_provider_requires_key() -> None:
    provider = BraveSearchProvider(config=FakeConfig(brave_key=None))

    assert provider.is_available() is False
    with pytest.raises(WebSearchProviderUnavailable):
        provider.search("query", 1)


def test_brave_provider_uses_subscription_header_and_normalizes_results(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["headers"] = {key.lower(): value for key, value in request.header_items()}
        return FakeWebResponse(
            json.dumps(
                {
                    "web": {
                        "results": [
                            {
                                "title": "Brave Result",
                                "url": "https://brave.example/result",
                                "description": "Description",
                            }
                        ]
                    }
                },
                ensure_ascii=False,
            ).encode("utf-8")
        )

    monkeypatch.setattr(
        "src.business.agents.tools.web_search_providers.urllib.request.urlopen",
        fake_urlopen,
    )

    results = BraveSearchProvider(config=FakeConfig(brave_key="brave-secret")).search(
        "machine learning", 3
    )

    assert results == [
        {
            "title": "Brave Result",
            "url": "https://brave.example/result",
            "description": "Description",
        }
    ]
    assert "brave-secret" not in str(captured["url"])
    assert "q=machine+learning" in str(captured["url"])
    assert "count=3" in str(captured["url"])
    assert captured["headers"]["x-subscription-token"] == "brave-secret"


def test_web_search_handler_returns_new_format_without_legacy_keys(monkeypatch) -> None:
    monkeypatch.setattr(
        builtin_general_tools.web_search_providers,
        "search_web",
        lambda query, num_results: {
            "success": True,
            "data": {
                "web": [
                    {
                        "title": "Title",
                        "url": "https://example.test",
                        "description": "Description",
                        "position": 1,
                    }
                ]
            },
        },
    )

    result = json.loads(builtin_general_tools.web_search_handler("query"))

    assert result["success"] is True
    assert result["data"]["web"][0]["description"] == "Description"
    assert "results" not in result
    assert "count" not in result
    assert "snippet" not in json.dumps(result, ensure_ascii=False)


def test_web_search_handler_failure_format_is_stable(monkeypatch) -> None:
    def fail(_query, _num_results):
        raise RuntimeError("boom")

    monkeypatch.setattr(builtin_general_tools.web_search_providers, "search_web", fail)

    result = json.loads(builtin_general_tools.web_search_handler("query"))

    assert result["success"] is False
    assert result["data"] == {"web": []}
    assert "boom" in result["error"]
    assert "建议直接使用 web_fetch 抓取目标网页内容" in result["error"]


# --- Circuit breaker tests ---


@pytest.fixture(autouse=True)
def _reset_breaker():
    """Reset circuit breaker between tests."""
    _EMPTY_RESULT_BREAKER.reset()
    yield
    _EMPTY_RESULT_BREAKER.reset()


def test_circuit_breaker_trips_after_two_empty_results() -> None:
    """Two consecutive empty results should trip the breaker."""
    registry = WebSearchProviderRegistry()
    provider = FakeProvider("ddg-html", results=[])
    registry.register_provider(provider)

    # First empty — should still try provider
    result1 = search_web("query", config=FakeConfig("auto"), registry=registry)
    assert result1["success"] is False
    assert provider.calls == 1

    # Second empty — should trip breaker
    result2 = search_web("query", config=FakeConfig("auto"), registry=registry)
    assert result2["success"] is False
    assert provider.calls == 2

    # Third attempt — provider should be skipped (circuit open)
    result3 = search_web("query", config=FakeConfig("auto"), registry=registry)
    assert result3["success"] is False
    assert provider.calls == 2  # Not called again
    assert "ddg-html: 连续空结果，暂时跳过" in result3["error"]


def test_circuit_breaker_skips_to_next_provider() -> None:
    """Auto mode should skip circuit-broken provider and try the next one."""
    registry = WebSearchProviderRegistry()
    broken = FakeProvider("brave-free", results=[])
    fallback = FakeProvider(
        "ddg-html",
        results=[{"title": "Found", "url": "https://example.test", "description": "OK"}],
    )
    registry.register_provider(broken)
    registry.register_provider(fallback)

    # Trip the breaker for brave-free (2 consecutive empties)
    search_web("query", config=FakeConfig("auto"), registry=registry)
    search_web("query", config=FakeConfig("auto"), registry=registry)
    assert broken.calls == 2

    # Next call should skip brave-free and go straight to ddg-html
    result = search_web("query", config=FakeConfig("auto"), registry=registry)
    assert result["success"] is True
    assert result["data"]["web"][0]["title"] == "Found"
    assert broken.calls == 2  # Not called again — circuit open
    assert fallback.calls == 3  # Called all 3 times (was the successful one each time)


def test_circuit_breaker_does_not_apply_to_explicit_backend() -> None:
    """Explicit backend selection should not skip circuit-broken providers."""
    registry = WebSearchProviderRegistry()
    provider = FakeProvider("ddg-html", results=[])
    registry.register_provider(provider)

    # Trip the breaker
    search_web("query", config=FakeConfig("ddg-html"), registry=registry)
    search_web("query", config=FakeConfig("ddg-html"), registry=registry)

    # Explicit mode — should still try (and fail with empty), not skip
    result = search_web("query", config=FakeConfig("ddg-html"), registry=registry)
    assert result["success"] is False
    assert provider.calls == 3  # Called every time


def test_circuit_breaker_resets_on_success() -> None:
    """A successful search should reset the empty-result counter."""
    registry = WebSearchProviderRegistry()
    provider = FakeProvider(
        "ddg-html",
        results=[{"title": "OK", "url": "https://example.test", "description": ""}],
    )
    registry.register_provider(provider)

    # One empty result
    provider.results = []
    search_web("query", config=FakeConfig("auto"), registry=registry)
    assert provider.calls == 1

    # Successful result — resets counter
    provider.results = [{"title": "OK", "url": "https://example.test", "description": ""}]
    search_web("query", config=FakeConfig("auto"), registry=registry)
    assert provider.calls == 2

    # Another empty — counter starts from 1, not 2
    provider.results = []
    search_web("query", config=FakeConfig("auto"), registry=registry)
    assert provider.calls == 3

    # Provider should still be tried (only 1 empty since last success)
    search_web("query", config=FakeConfig("auto"), registry=registry)
    assert provider.calls == 4
