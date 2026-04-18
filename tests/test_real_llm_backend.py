"""
真实 LLM 后端冒烟测试 — 不涉及 GUI，只验证 LLM 连接和 AgentLoop 链路

运行方式:
  pytest tests/test_real_llm_backend.py -xvs

标记:
  pytest.mark.real_llm — 需要 config.json 中有有效的 API Key
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from src.business.ai.llm_client import LLMResponse, LangChainLLMClient

pytestmark = pytest.mark.real_llm


def _read_llm_config() -> dict:
    """从项目根目录 config.json 读取 LLM 配置"""
    config_path = Path(__file__).resolve().parent.parent / "config.json"
    with open(config_path, encoding="utf-8") as f:
        cfg = json.load(f)
    ai = cfg.get("ai", {})
    if not ai.get("api_key"):
        pytest.skip("config.json 中没有 ai.api_key")
    return {
        "provider": ai.get("provider", "openai"),
        "model": ai.get("model", "gpt-4"),
        "api_key": ai["api_key"],
        "base_url": ai.get("base_url"),
        "temperature": ai.get("temperature", 0.7),
        "max_tokens": 256,
    }


@pytest.fixture(scope="module")
def real_llm():
    """创建真实 LLM 客户端（module 级复用）"""
    cfg = _read_llm_config()
    client = LangChainLLMClient(**cfg)
    return client


# ---------------------------------------------------------------------------
# Test 1: 基础 chat 连通性
# ---------------------------------------------------------------------------


def test_llm_chat_connection(real_llm):
    """验证 LLM 客户端能连上 API 并拿到非空回复"""
    resp = real_llm.chat("请用一句话介绍你自己，不超过30个字")
    assert resp and len(resp.strip()) > 0, f"LLM 返回了空回复: {repr(resp)}"
    print(f"\n[LLM chat 回复] {resp}")


# ---------------------------------------------------------------------------
# Test 2: chat_with_tools 连通性
# ---------------------------------------------------------------------------


def test_llm_chat_with_tools_connection(real_llm):
    """验证 chat_with_tools 能正常返回 LLMResponse"""
    tools: List[Dict[str, Any]] = [
        {
            "type": "function",
            "function": {
                "name": "get_weather",
                "description": "获取指定城市的天气",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {"type": "string", "description": "城市名称"},
                    },
                    "required": ["city"],
                },
            },
        }
    ]
    messages = [
        {"role": "user", "content": "今天北京天气怎么样？"},
    ]
    resp = real_llm.chat_with_tools(messages, tools)

    assert isinstance(resp, LLMResponse), f"返回类型不对: {type(resp)}"
    # 真实 LLM 应该会调用 get_weather 工具
    assert resp.has_tool_calls, f"LLM 没有调用工具，而是返回了文本: {resp.content}"
    assert resp.tool_calls[0].name == "get_weather"
    assert "city" in resp.tool_calls[0].args
    print(f"\n[LLM tool_call] name={resp.tool_calls[0].name}, args={resp.tool_calls[0].args}")


# ---------------------------------------------------------------------------
# Test 3: AgentLoop 端到端（带 talk_to_user 哨兵）
# ---------------------------------------------------------------------------


def test_agent_loop_with_real_llm(real_llm):
    """用真实 LLM 跑一次 AgentLoop，验证完整循环能走通"""
    from unittest.mock import MagicMock

    from src.business.agents.agent_loop import AgentLoop
    from src.business.agents.config import AgentConfig, AgentType, ToolDefinition
    from src.data.unified_config import UnifiedConfigManager

    # 创建一个简单的 echo 工具
    echo_tool = ToolDefinition(
        name="echo",
        schema={
            "type": "function",
            "function": {
                "name": "echo",
                "description": "把输入原样返回",
                "parameters": {
                    "type": "object",
                    "properties": {"text": {"type": "string", "description": "要回显的文本"}},
                    "required": ["text"],
                },
            },
        },
        handler=lambda text: json.dumps({"result": text}, ensure_ascii=False),
    )

    config = AgentConfig(
        agent_type=AgentType.ASSISTANT,
        system_prompt="你是一个测试助手。用户让你做什么你就做，做完后用 talk_to_user 告诉用户结果。",
        max_iterations=5,
    )

    mock_unified = MagicMock(spec=UnifiedConfigManager)
    mock_unified.get_memory_reference_steps_threshold.return_value = 999
    mock_unified.get_memory_reference_size_threshold.return_value = 999_999
    mock_unified.get_memory_compression_trigger_strategy.return_value = "token"
    mock_unified.get_memory_compression_token_threshold.return_value = 999_999
    mock_unified.get_memory_compression_count_threshold.return_value = None
    mock_unified.get_memory_compression_keep_recent.return_value = 5

    loop = AgentLoop(config=config, llm_client=real_llm, unified_config=mock_unified)

    result = loop.run(
        session_id="test-real-llm-session",
        user_input="请调用 echo 工具，传入 text='Hello Real LLM'，然后把结果告诉我。",
        tools=[echo_tool],
    )

    print(f"\n[AgentLoop 结果] type={result.result_type.value}, question={result.question}")
    assert result.result_type.value in ("completed", "needs_user_input"), (
        f"意外的结果类型: {result.result_type.value}, error={result.error}"
    )
    assert result.error is None, f"AgentLoop 出错: {result.error}"
