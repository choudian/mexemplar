from unittest.mock import MagicMock

from src.business.memory.reference_handler import ReferenceHandler


def test_reference_handler_keeps_large_old_tool_result(make_message):
    """会话内引用替换停用后，大工具结果即使超过阈值也保留原文。"""
    config = MagicMock()
    config.get_memory_reference_steps_threshold.return_value = 1
    config.get_memory_reference_size_threshold.return_value = 10
    handler = ReferenceHandler(config)
    large_content = "x" * 100
    messages = [
        make_message(
            role="assistant",
            content=None,
            tool_calls=[{"id": "call_1", "name": "web_fetch", "args": {}}],
        ),
        make_message(
            role="tool",
            content=large_content,
            tool_call_id="call_1",
            tool_name="web_fetch",
            message_id="msg_large_tool",
        ),
        make_message(role="assistant", content="我已经读取完成。"),
    ]

    llm_messages = handler.apply_replacements(messages)

    assert llm_messages[1]["content"] == large_content
    assert "REF::" not in llm_messages[1]["content"]
    assert llm_messages[1]["tool_call_id"] == "call_1"
    assert llm_messages[1]["name"] == "web_fetch"
