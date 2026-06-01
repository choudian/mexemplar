from __future__ import annotations

import json

from src.business.agents.tools.builtin_general_tools import web_fetch_handler


def test_web_fetch_rejects_file_scheme_without_fetching() -> None:
    result = json.loads(web_fetch_handler("file:///C:/Windows/win.ini"))

    assert result["success"] is False
    assert "http/https" in result["message"]


def test_web_fetch_rejects_loopback_without_fetching() -> None:
    result = json.loads(web_fetch_handler("http://127.0.0.1:8000/internal"))

    assert result["success"] is False
    assert "内网" in result["message"] or "本机" in result["message"]
