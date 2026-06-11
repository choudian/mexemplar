from __future__ import annotations

from email.message import Message
import json
import urllib.error

import pytest

from src.business.agents.tools import builtin_general_tools as general_tools
from src.business.agents.tools.builtin_general_tools import web_fetch_handler

_REAL_DOMAIN_BLOCKLIST_CHECK = general_tools._check_web_fetch_domain_blocklist


class FakeWebResponse:
    def __init__(
        self,
        body: bytes,
        *,
        url: str = "https://example.test/",
        content_type: str = "text/html; charset=utf-8",
        status: int = 200,
        reason: str = "OK",
    ) -> None:
        self._body = body
        self._url = url
        self.status = status
        self.reason = reason
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        self.headers["Content-Length"] = str(len(body))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self, size=-1) -> bytes:
        if size is None or size < 0:
            return self._body
        return self._body[:size]

    def geturl(self) -> str:
        return self._url


@pytest.fixture(autouse=True)
def isolate_web_fetch(monkeypatch) -> None:
    general_tools.clear_web_fetch_cache()
    monkeypatch.setattr(general_tools, "_check_web_fetch_domain_blocklist", lambda domain: None)


def test_web_fetch_rejects_file_scheme_without_fetching() -> None:
    result = json.loads(web_fetch_handler("file:///C:/Windows/win.ini"))

    assert result["success"] is False
    assert "http/https" in result["message"]


def test_web_fetch_rejects_loopback_without_fetching() -> None:
    result = json.loads(web_fetch_handler("http://127.0.0.1:8000/internal"))

    assert result["success"] is False
    assert "localhost" in result["message"] or "内网" in result["message"]


def test_web_fetch_percent_encodes_non_ascii_url(monkeypatch) -> None:
    captured: dict[str, str] = {}

    def fake_open(request, timeout):
        captured["url"] = request.full_url
        return FakeWebResponse(b"<html><body>OK</body></html>", url=request.full_url)

    monkeypatch.setattr(general_tools, "_open_web_fetch_url", fake_open)

    result = json.loads(web_fetch_handler("https://zh.wikipedia.org/wiki/安德烈·卡帕斯?q=人工智能"))

    assert result["success"] is True
    assert result["content"] == "OK"
    assert "%E5%AE%89" in captured["url"]
    assert "%E4%BA%BA" in captured["url"]
    assert all(ord(ch) < 128 for ch in captured["url"])


def test_web_fetch_upgrades_public_http_like_claw_code(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_open(request, timeout):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        return FakeWebResponse(b"<html><body>OK</body></html>", url=request.full_url)

    monkeypatch.setattr(general_tools, "_open_web_fetch_url", fake_open)

    result = json.loads(web_fetch_handler("http://example.test/path"))

    assert result["success"] is True
    assert captured["url"] == "https://example.test/path"
    assert captured["timeout"] == general_tools._WEB_FETCH_TIMEOUT
    assert result["status"] == 200
    assert result["status_text"] == "OK"
    assert result["bytes"] > 0
    assert isinstance(result["duration_ms"], int)


def test_web_fetch_prompt_title_result(monkeypatch) -> None:
    def fake_open(request, timeout):
        return FakeWebResponse(
            b"<html><head><title>Example &amp; Title</title></head>"
            b"<body><p>Body text</p></body></html>",
            url=request.full_url,
        )

    monkeypatch.setattr(general_tools, "_open_web_fetch_url", fake_open)

    result = json.loads(web_fetch_handler("https://example.test", prompt="title"))

    assert result["success"] is True
    assert "Body text" in result["content"]
    assert result["result"] == "Fetched https://example.test/\nTitle: Example & Title"


def test_web_fetch_prompt_summary_result(monkeypatch) -> None:
    def fake_open(request, timeout):
        return FakeWebResponse(
            b"<html><body><p>First paragraph.</p><p>Second paragraph.</p></body></html>",
            url=request.full_url,
        )

    monkeypatch.setattr(general_tools, "_open_web_fetch_url", fake_open)

    result = json.loads(web_fetch_handler("https://example.test", prompt="summary"))

    assert result["success"] is True
    assert result["result"] == ("Fetched https://example.test/\nFirst paragraph. Second paragraph.")


def test_web_fetch_converts_html_to_markdown(monkeypatch) -> None:
    html = b"""
    <html><body>
      <h1>Main</h1>
      <ul><li>One</li><li>Two</li></ul>
      <pre><code>print("ok")</code></pre>
      <table><tr><th>Name</th></tr><tr><td>Ada</td></tr></table>
      <a href="https://example.test/docs">Docs</a>
    </body></html>
    """

    def fake_open(request, timeout):
        return FakeWebResponse(html, url=request.full_url)

    monkeypatch.setattr(general_tools, "_open_web_fetch_url", fake_open)

    result = json.loads(web_fetch_handler("https://example.test/markdown"))

    assert result["success"] is True
    assert "# Main" in result["content"]
    assert "* One" in result["content"]
    assert 'print("ok")' in result["content"]
    assert "| Name |" in result["content"]
    assert "[Docs](https://example.test/docs)" in result["content"]


def test_web_fetch_cache_hit_skips_network(monkeypatch) -> None:
    calls = 0

    def fake_open(request, timeout):
        nonlocal calls
        calls += 1
        return FakeWebResponse(
            f"response-{calls}".encode(), url=request.full_url, content_type="text/plain"
        )

    monkeypatch.setattr(general_tools, "_open_web_fetch_url", fake_open)

    first = json.loads(web_fetch_handler("https://cache.test/item"))
    second = json.loads(web_fetch_handler("https://cache.test/item"))

    assert calls == 1
    assert first["content"] == "response-1"
    assert second["content"] == "response-1"


def test_web_fetch_cache_expires(monkeypatch) -> None:
    clock = [1_000.0]
    calls = 0

    monkeypatch.setattr(general_tools.time, "monotonic", lambda: clock[0])

    def fake_open(request, timeout):
        nonlocal calls
        calls += 1
        return FakeWebResponse(
            f"response-{calls}".encode(), url=request.full_url, content_type="text/plain"
        )

    monkeypatch.setattr(general_tools, "_open_web_fetch_url", fake_open)

    first = json.loads(web_fetch_handler("https://cache.test/expire"))
    clock[0] += general_tools._WEB_FETCH_CACHE_TTL_SECONDS + 1
    second = json.loads(web_fetch_handler("https://cache.test/expire"))

    assert calls == 2
    assert first["content"] == "response-1"
    assert second["content"] == "response-2"


def test_web_fetch_cache_evicts_lru_when_size_exceeded(monkeypatch) -> None:
    calls: dict[str, int] = {}
    monkeypatch.setattr(general_tools, "_WEB_FETCH_CACHE_MAX_BYTES", 20)

    def fake_open(request, timeout):
        url = request.full_url
        calls[url] = calls.get(url, 0) + 1
        return FakeWebResponse(b"123456789012345", url=url, content_type="text/plain")

    monkeypatch.setattr(general_tools, "_open_web_fetch_url", fake_open)

    json.loads(web_fetch_handler("https://cache.test/a"))
    json.loads(web_fetch_handler("https://cache.test/b"))
    json.loads(web_fetch_handler("https://cache.test/a"))

    assert calls["https://cache.test/a"] == 2
    assert calls["https://cache.test/b"] == 1


def test_web_fetch_follows_same_host_redirect(monkeypatch) -> None:
    calls: list[str] = []

    def fake_open(request, timeout):
        calls.append(request.full_url)
        if request.full_url == "https://example.test/start":
            headers = Message()
            headers["Location"] = "/next"
            raise urllib.error.HTTPError(request.full_url, 302, "Found", headers, None)
        return FakeWebResponse(b"redirected", url=request.full_url, content_type="text/plain")

    monkeypatch.setattr(general_tools, "_open_web_fetch_url", fake_open)

    result = json.loads(web_fetch_handler("https://example.test/start"))

    assert result["success"] is True
    assert result["content"] == "redirected"
    assert result["url"] == "https://example.test/next"
    assert calls == ["https://example.test/start", "https://example.test/next"]


def test_web_fetch_reports_cross_host_redirect_without_following(monkeypatch) -> None:
    calls: list[str] = []

    def fake_open(request, timeout):
        calls.append(request.full_url)
        headers = Message()
        headers["Location"] = "https://other.test/landing"
        raise urllib.error.HTTPError(request.full_url, 302, "Found", headers, None)

    monkeypatch.setattr(general_tools, "_open_web_fetch_url", fake_open)

    result = json.loads(web_fetch_handler("https://example.test/start"))

    assert result["success"] is True
    assert result["redirect"] is True
    assert result["redirect_url"] == "https://other.test/landing"
    assert calls == ["https://example.test/start"]


def test_web_fetch_domain_blocklist_preflight(monkeypatch) -> None:
    calls: list[str] = []

    class DomainResponse:
        status = 200
        headers = Message()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def read(self, size=-1) -> bytes:
            return b'{"can_fetch": true}'

    def fake_domain_open(request, timeout):
        calls.append(request.full_url)
        assert timeout == general_tools._WEB_FETCH_DOMAIN_CHECK_TIMEOUT
        return DomainResponse()

    def fake_fetch_open(request, timeout):
        return FakeWebResponse(b"ok", url=request.full_url, content_type="text/plain")

    monkeypatch.setattr(
        general_tools,
        "_check_web_fetch_domain_blocklist",
        _REAL_DOMAIN_BLOCKLIST_CHECK,
    )
    monkeypatch.setattr(general_tools.urllib.request, "urlopen", fake_domain_open)
    monkeypatch.setattr(general_tools, "_open_web_fetch_url", fake_fetch_open)

    result = json.loads(web_fetch_handler("https://preflight.test/page"))

    assert result["success"] is True
    assert calls == ["https://api.anthropic.com/api/web/domain_info?domain=preflight.test"]


def test_web_fetch_rejects_large_content_by_header(monkeypatch) -> None:
    def fake_open(request, timeout):
        response = FakeWebResponse(b"", url=request.full_url, content_type="text/plain")
        response.headers.replace_header(
            "Content-Length", str(general_tools._WEB_FETCH_MAX_BYTES + 1)
        )
        return response

    monkeypatch.setattr(general_tools, "_open_web_fetch_url", fake_open)

    result = json.loads(web_fetch_handler("https://large.test/file"))

    assert result["success"] is False
    assert "10MB" in result["message"]


def test_web_fetch_binary_content_returns_private_reference(monkeypatch) -> None:
    def fake_open(request, timeout):
        return FakeWebResponse(b"%PDF-1.7", url=request.full_url, content_type="application/pdf")

    monkeypatch.setattr(general_tools, "_open_web_fetch_url", fake_open)
    monkeypatch.setattr(
        general_tools, "_persist_web_fetch_binary", lambda raw, content_type: "out_ref"
    )

    result = json.loads(web_fetch_handler("https://binary.test/file.pdf", prompt="summary"))

    assert result["success"] is True
    assert result["binary"] == {
        "reference_id": "out_ref",
        "size_bytes": 8,
        "content_type": "application/pdf",
    }
    assert "tool output reference out_ref" in result["result"]


def test_list_dir_returns_bounded_envelope_without_absolute_path(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "b.txt").write_text("b", encoding="utf-8")
    (tmp_path / "a.txt").write_text("a", encoding="utf-8")
    (tmp_path / ".hidden").write_text("hidden", encoding="utf-8")

    result = json.loads(general_tools.list_dir_handler("."))

    assert result["schemaVersion"] == 1
    assert result["tool"] == "list_dir"
    assert result["outcome"] == "success"
    assert result["payload"]["path"] == "."
    assert [item["name"] for item in result["payload"]["items"]] == ["a.txt", "b.txt"]
    assert str(tmp_path) not in json.dumps(result, ensure_ascii=False)


def test_list_dir_rejects_outside_workspace_without_confirmation(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    result = json.loads(general_tools.list_dir_handler(str(tmp_path.parent)))

    assert result["outcome"] == "rejected"
    assert result["error"]["code"] == "path_outside_workspace"
