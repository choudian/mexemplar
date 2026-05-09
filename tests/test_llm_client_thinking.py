"""thinking_level 翻译与注入单元测试。

通过 sys.modules 注入 stub 替代真实的 langchain_anthropic / langchain_openai，
避免依赖外部 SDK，并断言传给 ChatXxx 构造的 kwargs。
"""

from __future__ import annotations

import sys
import types
from typing import Any
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def stub_langchain(monkeypatch: pytest.MonkeyPatch):
    """在 sys.modules 注入 stub，并返回 (ChatAnthropic mock, ChatOpenAI mock)。"""
    fake_anthropic = types.ModuleType("langchain_anthropic")
    chat_anthropic = MagicMock(return_value=MagicMock(name="anthropic_llm"))
    fake_anthropic.ChatAnthropic = chat_anthropic

    fake_openai = types.ModuleType("langchain_openai")
    chat_openai = MagicMock(return_value=MagicMock(name="openai_llm"))
    fake_openai.ChatOpenAI = chat_openai

    monkeypatch.setitem(sys.modules, "langchain_anthropic", fake_anthropic)
    monkeypatch.setitem(sys.modules, "langchain_openai", fake_openai)
    return chat_anthropic, chat_openai


def _make_client(thinking_level: str, **overrides: Any):
    from src.business.ai.llm_client import LangChainLLMClient

    defaults = dict(
        provider="anthropic",
        model="claude-sonnet-4-20250514",
        api_key="sk-test-1234",
        temperature=0.7,
        max_tokens=4096,
        thinking_level=thinking_level,
    )
    defaults.update(overrides)
    return LangChainLLMClient(**defaults)


# ===== Anthropic =====


def test_anthropic_off_does_not_inject_thinking(stub_langchain):
    chat_anthropic, _ = stub_langchain
    _make_client("off")
    kwargs = chat_anthropic.call_args.kwargs
    assert "thinking" not in kwargs
    assert kwargs["temperature"] == 0.7  # 用户 temperature 保留
    assert kwargs["max_tokens"] == 4096


@pytest.mark.parametrize(
    "level,expected_budget",
    [("low", 2048), ("medium", 8192), ("high", 16384)],
)
def test_anthropic_levels_inject_correct_budget(stub_langchain, level, expected_budget):
    chat_anthropic, _ = stub_langchain
    _make_client(level, max_tokens=32000)
    kwargs = chat_anthropic.call_args.kwargs
    assert kwargs["thinking"] == {"type": "enabled", "budget_tokens": expected_budget}
    # Anthropic thinking 启用时 temperature 强制 1
    assert kwargs["temperature"] == 1


def test_anthropic_high_bumps_max_tokens_when_too_small(stub_langchain):
    chat_anthropic, _ = stub_langchain
    # max_tokens=4096 < budget=16384，应自动 bump
    _make_client("high", max_tokens=4096)
    kwargs = chat_anthropic.call_args.kwargs
    assert kwargs["max_tokens"] == 16384 + 1024
    assert kwargs["thinking"]["budget_tokens"] == 16384


def test_anthropic_invalid_level_falls_back_to_off(stub_langchain):
    chat_anthropic, _ = stub_langchain
    _make_client("ultra")  # 非法值
    kwargs = chat_anthropic.call_args.kwargs
    assert "thinking" not in kwargs
    assert kwargs["temperature"] == 0.7


# ===== OpenAI =====


@pytest.mark.parametrize(
    "level", ["low", "medium", "high"],
)
def test_openai_levels_inject_reasoning_effort(stub_langchain, level):
    _, chat_openai = stub_langchain
    _make_client(level, provider="openai", model="gpt-5")
    kwargs = chat_openai.call_args.kwargs
    assert kwargs["reasoning_effort"] == level


def test_openai_off_does_not_inject_reasoning(stub_langchain):
    _, chat_openai = stub_langchain
    _make_client("off", provider="openai", model="gpt-5")
    kwargs = chat_openai.call_args.kwargs
    assert "reasoning_effort" not in kwargs


# ===== 兼容 provider（DeepSeek/Qwen/Zhipu/Moonshot）应静默忽略 =====


@pytest.mark.parametrize("provider", ["deepseek", "qwen", "zhipu", "moonshot"])
def test_openai_compatible_providers_silently_ignore_thinking(stub_langchain, provider):
    _, chat_openai = stub_langchain
    _make_client("high", provider=provider, model="some-model")
    kwargs = chat_openai.call_args.kwargs
    assert "reasoning_effort" not in kwargs
    # 其他 kwargs 保持完整（不影响 base_url/temperature/max_tokens）
    assert kwargs["temperature"] == 0.7
    assert kwargs["max_tokens"] == 4096
