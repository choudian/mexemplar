from src.utils.llm_helpers import sanitize_text_for_llm


def test_sanitize_text_for_llm_removes_control_chars():
    raw = "okline\n\tkeep\rend"
    cleaned = sanitize_text_for_llm(raw)
    assert cleaned == "okline\n\tkeep\rend"
