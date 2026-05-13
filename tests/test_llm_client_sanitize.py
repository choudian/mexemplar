from src.business.ai.llm_client import LangChainLLMClient


def test_sanitize_message_content_removes_control_chars():
    raw = "a\u0001\u0002b\n\tc\r"
    assert LangChainLLMClient._sanitize_message_content(raw) == "ab\n\tc\r"


def test_sanitize_message_content_accepts_none():
    assert LangChainLLMClient._sanitize_message_content(None) == ""
