"""AgentLoop._call_llm_with_retry 行为测试。

覆盖：
- 首次成功直接返回，不 sleep
- 任何异常都触发重试（不再有 retryable_errors 白名单）
- 重试用尽返回 None
- 指数退避：delay = retry_delay * 2 ** retry_count
- 最终失败不再 sleep
- retry 配置由 unified_config 提供（max_retries / retry_delay）
"""

from unittest.mock import MagicMock, patch

import pytest

from src.business.agents.agent_loop import AgentLoop
from src.business.agents.config import AgentConfig, AgentType
from src.business.ai.llm_client import LLMResponse


@pytest.fixture
def make_loop(mock_config):
    def _make(max_retries: int = 3, retry_delay: float = 1.0):
        # retry 配置由 unified_config 提供（agent_loop 从这里读）
        mock_config.get_ai_retry_max_retries.return_value = max_retries
        mock_config.get_ai_retry_delay.return_value = retry_delay
        config = AgentConfig(
            agent_type=AgentType.PM,
            system_prompt="test",
            max_iterations=10,
        )
        llm = MagicMock()
        return AgentLoop(config, llm, mock_config), llm

    return _make


def test_first_attempt_succeeds_no_sleep(make_loop):
    loop, llm = make_loop()
    expected = LLMResponse(content="ok", tool_calls=[])
    llm.chat_with_tools.return_value = expected

    with patch("src.business.agents.agent_loop.time.sleep") as sleep_mock:
        response, recoverable = loop._call_llm_with_retry([], [], iteration=1)

    assert response is expected
    assert recoverable is False
    assert llm.chat_with_tools.call_count == 1
    sleep_mock.assert_not_called()


def test_retries_business_exception(make_loop):
    """任意异常都重试——旧实现下这种字符串不在白名单内会直接放弃。"""
    loop, llm = make_loop()
    expected = LLMResponse(content="ok", tool_calls=[])
    llm.chat_with_tools.side_effect = [
        ValueError("invalid_request: malformed json"),
        expected,
    ]

    with patch("src.business.agents.agent_loop.time.sleep"):
        response, recoverable = loop._call_llm_with_retry([], [], iteration=1)

    assert response is expected
    assert recoverable is False
    assert llm.chat_with_tools.call_count == 2


def test_retries_real_world_rate_limit_message(make_loop):
    """真实 Anthropic/OpenAI 报错文本（含空格）也会重试——旧白名单匹配不上。"""
    loop, llm = make_loop()
    expected = LLMResponse(content="ok", tool_calls=[])
    llm.chat_with_tools.side_effect = [
        RuntimeError("Error code: 429 - Rate limit exceeded for organization"),
        expected,
    ]

    with patch("src.business.agents.agent_loop.time.sleep"):
        response, recoverable = loop._call_llm_with_retry([], [], iteration=1)

    assert response is expected
    assert recoverable is False
    assert llm.chat_with_tools.call_count == 2


def test_returns_none_after_max_retries(make_loop):
    loop, llm = make_loop(max_retries=2)
    llm.chat_with_tools.side_effect = RuntimeError("boom")

    with patch("src.business.agents.agent_loop.time.sleep"):
        response, recoverable = loop._call_llm_with_retry([], [], iteration=1)

    assert response is None
    assert recoverable is False
    # max_retries=2 → 一次原始 + 两次重试 = 3 次总调用
    assert llm.chat_with_tools.call_count == 3


def test_exponential_backoff(make_loop):
    """delay = retry_delay * 2 ** (attempt - 1)。"""
    loop, llm = make_loop(max_retries=3, retry_delay=2.0)
    llm.chat_with_tools.side_effect = RuntimeError("boom")

    with patch("src.business.agents.agent_loop.time.sleep") as sleep_mock:
        loop._call_llm_with_retry([], [], iteration=1)

    sleep_calls = [c.args[0] for c in sleep_mock.call_args_list]
    assert sleep_calls == [2.0, 4.0, 8.0]


def test_no_sleep_after_final_failure(make_loop):
    """最后一次失败后直接返回 None，不再 sleep。"""
    loop, llm = make_loop(max_retries=2, retry_delay=1.0)
    llm.chat_with_tools.side_effect = RuntimeError("boom")

    with patch("src.business.agents.agent_loop.time.sleep") as sleep_mock:
        loop._call_llm_with_retry([], [], iteration=1)

    # 3 次调用 → 失败 1/2 后 sleep，失败 3 不 sleep
    assert sleep_mock.call_count == 2


def test_max_retries_zero_no_retry(make_loop):
    """max_retries=0 时单次失败即返回 None，不重试。"""
    loop, llm = make_loop(max_retries=0)
    llm.chat_with_tools.side_effect = RuntimeError("boom")

    with patch("src.business.agents.agent_loop.time.sleep") as sleep_mock:
        response, recoverable = loop._call_llm_with_retry([], [], iteration=1)

    assert response is None
    assert recoverable is False
    assert llm.chat_with_tools.call_count == 1
    sleep_mock.assert_not_called()


def test_retry_config_sourced_from_unified_config(mock_config):
    """AgentLoop 应从 unified_config 读取 retry 配置（覆盖任何 AgentConfig.retry 默认）。"""
    mock_config.get_ai_retry_max_retries.return_value = 5
    mock_config.get_ai_retry_delay.return_value = 2.5

    config = AgentConfig(agent_type=AgentType.PM, system_prompt="test", max_iterations=10)
    loop = AgentLoop(config, MagicMock(), mock_config)

    assert loop._retry.max_retries == 5
    assert loop._retry.retry_delay == 2.5


def test_unified_config_invalid_values_fallback(monkeypatch):
    """unified_config 提供非法 retry 值时应回退到默认（3 / 1.0）。"""
    from src.data.unified_config import UnifiedConfigManager

    config = UnifiedConfigManager.__new__(UnifiedConfigManager)

    # 直接 mock get() 返回非法值
    monkeypatch.setattr(
        config,
        "get",
        lambda key, default=None: {
            "ai.retry_max_retries": "not_a_number",
            "ai.retry_delay": -1.5,
        }.get(key, default),
    )

    assert config.get_ai_retry_max_retries() == 3
    assert config.get_ai_retry_delay() == 1.0
