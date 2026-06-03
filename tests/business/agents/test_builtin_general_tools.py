from __future__ import annotations

import io
import ipaddress
import json
import socket

from src.business.agents.tools import builtin_general_tools as general_tools
from src.business.agents.tools.builtin_general_tools import web_fetch_handler


def test_web_fetch_rejects_file_scheme_without_fetching() -> None:
    result = json.loads(web_fetch_handler("file:///C:/Windows/win.ini"))

    assert result["success"] is False
    assert "http/https" in result["message"]


def test_web_fetch_rejects_loopback_without_fetching() -> None:
    result = json.loads(web_fetch_handler("http://127.0.0.1:8000/internal"))

    assert result["success"] is False
    assert "内网" in result["message"] or "本机" in result["message"]


def test_web_fetch_connects_to_validated_ip_not_hostname(monkeypatch) -> None:
    """DNS validation and the actual request must use the same resolved address."""

    general_tools._DNS_CACHE.clear()
    connected_addresses: list[tuple[str, int]] = []

    def fake_getaddrinfo(host, port, *args, **kwargs):
        assert host == "example.test"
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                ("93.184.216.34", port or 80),
            )
        ]

    class FakeSocket:
        def sendall(self, _data: bytes) -> None:
            return None

        def makefile(self, *_args, **_kwargs):
            return io.BytesIO(
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Length: 18\r\n"
                b"Content-Type: text/html; charset=utf-8\r\n"
                b"\r\n"
                b"<html>Hello</html>"
            )

        def close(self) -> None:
            return None

    def fake_create_connection(address, timeout=None, source_address=None):
        connected_addresses.append(address)
        return FakeSocket()

    monkeypatch.setattr(general_tools.socket, "getaddrinfo", fake_getaddrinfo)
    monkeypatch.setattr(general_tools.socket, "create_connection", fake_create_connection)

    result = json.loads(web_fetch_handler("http://example.test/path"))

    assert result["success"] is True
    assert result["content"] == "Hello"
    assert connected_addresses == [("93.184.216.34", 80)]


def test_resolved_http_connection_sets_tcp_nodelay(monkeypatch) -> None:
    socket_options: list[tuple[int, int, int]] = []

    class FakeSocket:
        def setsockopt(self, level: int, option: int, value: int) -> None:
            socket_options.append((level, option, value))

    def fake_create_connection(address, timeout=None, source_address=None):
        assert address == ("93.184.216.34", 80)
        return FakeSocket()

    monkeypatch.setattr(general_tools.socket, "create_connection", fake_create_connection)

    conn = general_tools._ResolvedHTTPConnection(
        "example.test",
        80,
        ipaddress.ip_address("93.184.216.34"),
        timeout=1,
    )
    conn.connect()

    assert socket_options == [(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)]


def test_resolved_https_connection_reuses_module_ssl_context() -> None:
    conn_a = general_tools._ResolvedHTTPSConnection(
        "example.test",
        443,
        ipaddress.ip_address("93.184.216.34"),
        timeout=1,
    )
    conn_b = general_tools._ResolvedHTTPSConnection(
        "example.test",
        443,
        ipaddress.ip_address("93.184.216.34"),
        timeout=1,
    )

    assert conn_a._context is general_tools._WEB_FETCH_SSL_CONTEXT
    assert conn_b._context is general_tools._WEB_FETCH_SSL_CONTEXT


def test_redirect_response_body_is_drained_when_length_is_known() -> None:
    class FakeRedirectResponse:
        chunked = False
        length = 10_000

        def __init__(self) -> None:
            self.read_sizes: list[int] = []

        def read(self, size=None):
            self.read_sizes.append(size)
            return b"x" * int(size or 0)

    response = FakeRedirectResponse()

    general_tools._drain_redirect_response_body(response)

    assert response.read_sizes == [10_000]
