from src.business.agents.tools.recording_data_tools import (
    _MAX_QUERY_CELL_CHARS,
    _sanitize_query_value,
)
from src.utils.llm_helpers import sanitize_text_for_llm


def test_sanitize_text_for_llm_removes_control_chars():
    raw = "ok\u0001\u0002line\n\tkeep\rend"
    cleaned = sanitize_text_for_llm(raw)
    assert cleaned == "okline\n\tkeep\rend"


def test_sanitize_query_value_truncates_long_text():
    raw = "a" * (_MAX_QUERY_CELL_CHARS + 10)
    cleaned = _sanitize_query_value(raw)
    assert cleaned.startswith("a" * _MAX_QUERY_CELL_CHARS)
    assert cleaned.endswith("...[TRUNCATED 10 chars]")


def test_sanitize_query_value_keeps_non_string():
    assert _sanitize_query_value(123) == 123
    assert _sanitize_query_value({"k": "v"}) == {"k": "v"}

