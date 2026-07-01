from __future__ import annotations

from src.business.self_improvement.execution_trace_builder import build_skeleton


class _Msg:
    def __init__(self, role, tool_calls=None, content=""):
        self.role = role
        self.tool_calls = tool_calls
        self.content = content


class _Repo:
    def __init__(self, messages):
        self._messages = messages

    def get_all(self, session_id):
        return self._messages


def test_skeleton_detects_two_fetches_same_url():
    messages = [
        _Msg(
            "assistant",
            tool_calls=[{"function": {"name": "web_fetch", "arguments": '{"url":"https://x"}'}}],
        ),
        _Msg(
            "tool",
            content='{"limits":{"visibleChars":68347},"references":[{"referenceId":"out_a"}]}',
        ),
        _Msg(
            "assistant",
            tool_calls='[{"function":{"name":"web_fetch","arguments":"{\\"url\\":\\"https://x\\"}"}}]',
        ),
        _Msg(
            "tool",
            content='{"limits":{"visibleChars":68000},"references":[{"referenceId":"out_b"}]}',
        ),
    ]

    skeleton = build_skeleton("ast_x", _Repo(messages))

    fetches = [step for step in skeleton["steps"] if step["tool"] == "web_fetch"]
    assert len(fetches) == 2
    assert all("https://x" in step["args_summary"] for step in fetches)
    assert skeleton["steps"][0]["output_ref"] == "out_a"
