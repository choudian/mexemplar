"""Token usage must survive the whole path: response → message row (1.1)."""

from __future__ import annotations

import json

from src.business.agents.agent_loop import _serialize_token_usage
from src.business.ai.llm_client import LLMResponse
from src.business.ai.token_usage import TokenUsage, extract_token_usage


class _AiMessage:
    """Stands in for a LangChain AIMessage."""

    def __init__(self, content, usage_metadata=None, tool_calls=None):
        self.content = content
        self.usage_metadata = usage_metadata
        self.tool_calls = tool_calls or []


def test_llm_response_carries_usage_so_it_is_not_discarded():
    response = LLMResponse(content="ok", tool_calls=[], usage=TokenUsage(1, 2, 3))

    assert response.usage is not None
    assert response.usage.total_tokens == 3


def test_llm_response_without_usage_stays_valid():
    # Providers that report nothing must not break the response contract.
    response = LLMResponse(content="ok", tool_calls=[])

    assert response.usage is None


def test_extract_then_serialize_produces_a_persistable_row_value():
    ai_message = _AiMessage(
        "done",
        usage_metadata={
            "input_tokens": 163,
            "output_tokens": 65,
            "total_tokens": 228,
            "input_token_details": {"cache_read": 0},
            "output_token_details": {"reasoning": 52},
        },
    )

    serialized = _serialize_token_usage(extract_token_usage(ai_message))

    assert serialized is not None
    stored = json.loads(serialized)
    assert stored["inputTokens"] == 163
    assert stored["reasoningTokens"] == 52
    assert stored["source"] == "actual"
    assert TokenUsage.from_dict(stored) is not None


def test_serialization_returns_none_rather_than_failing_the_turn():
    assert _serialize_token_usage(None) is None


def test_serialization_swallows_broken_usage_objects():
    class _Broken:
        def to_dict(self):
            raise RuntimeError("boom")

    # Accounting must never take down the conversation it is accounting for.
    assert _serialize_token_usage(_Broken()) is None
