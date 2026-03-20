"""
v2 集成测试配置

提供三个核心 fixture：
- in_memory_db : 将全局 SQLAlchemy singleton 替换为 in-memory 数据库（autouse）
- mock_config  : 预配置的 UnifiedConfigManager MagicMock
- events_collector : 捕获所有 blinker 事件，返回 dict[name -> list[kwargs]]

以及 MockLLMClient 工具类（直接在测试文件中使用）。
"""

import pytest
from unittest.mock import MagicMock

from src.business.ai.llm_client import LLMResponse, ToolCallInfo
from src.data.unified_config import UnifiedConfigManager


# =============================================================================
# MockLLMClient
# =============================================================================


class MockLLMClient:
    """
    按顺序返回预设响应的 Mock LLM 客户端。

    序列中的元素规则：
    - LLMResponse 对象  → chat_with_tools() 返回它（AgentLoop 用）
    - str 对象          → chat() 返回它（LLMReviewer 用）
    chat() 收到 LLMResponse 时提取 content；确保顺序与调用序列一致。
    """

    def __init__(self, responses: list):
        self._iter = iter(responses)

    def chat(self, prompt: str, **kwargs) -> str:
        r = next(self._iter)
        return r if isinstance(r, str) else (r.content or "")

    def chat_with_tools(self, messages, tools, **kwargs) -> LLMResponse:
        return next(self._iter)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def in_memory_db():
    """将全局 SQLAlchemy singleton 替换为 in-memory 数据库，测试结束后还原。"""
    import src.data.sqlalchemy_manager as sm_module
    from src.data.sqlalchemy_manager import SQLAlchemyManager

    original = sm_module._sqlalchemy_instance
    test_manager = SQLAlchemyManager(":memory:")
    test_manager.initialize()
    sm_module._sqlalchemy_instance = test_manager
    yield test_manager
    sm_module._sqlalchemy_instance = original


@pytest.fixture
def mock_config():
    """
    预配置的 UnifiedConfigManager MagicMock。

    阈值全部设为极大值，确保测试期间不触发引用替换或上下文压缩。
    """
    config = MagicMock(spec=UnifiedConfigManager)
    # 引用替换阈值（很高，不触发）
    config.get_memory_reference_steps_threshold.return_value = 999
    config.get_memory_reference_size_threshold.return_value = 999_999
    # 压缩配置（token 策略，阈值很高，不触发）
    config.get_memory_compression_trigger_strategy.return_value = "token"
    config.get_memory_compression_token_threshold.return_value = 999_999
    config.get_memory_compression_count_threshold.return_value = None
    config.get_memory_compression_keep_recent.return_value = 5
    return config


@pytest.fixture
def events_collector():
    """
    捕获所有业务 blinker 事件，返回 dict[event_name -> list[kwargs]]。

    测试结束后调用 clear_all() 清理所有监听器。
    """
    from src.utils.events import connect, clear_all

    captured: dict = {}
    event_names = [
        "requirement_confirmed",
        "code_completed",
        "review_passed",
        "review_failed",
        "tool_saved",
        "trial_success",
        "trial_failed",
        "triage_completed",
        "agent_needs_user_input",
        "agent_error",
    ]

    def make_handler(name: str):
        def handler(sender, **kwargs):
            captured.setdefault(name, []).append(kwargs)
        return handler

    # 必须保持强引用，否则 blinker 弱引用会被 GC，导致事件监听失效
    _strong_refs = []
    for name in event_names:
        h = make_handler(name)
        _strong_refs.append(h)
        connect(name, h)

    yield captured
    clear_all()
