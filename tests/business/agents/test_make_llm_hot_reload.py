"""Part ②（配置热生效）行为契约：``AgentOrchestrator._make_llm()`` 现组装、不缓存。

LLM 客户端原先在 ``build_default_orchestrator`` 处一次性冻结，配置（model / api_key /
base_url 等）改了要重启 sidecar 才生效。现在下沉到 orchestrator 的 ``_make_llm()``
工厂，每个工作单元边界基于最新配置现组装。这里锁定三条硬保证：

- 不缓存：连续两次调用返回不同对象，构造器被调用两次。
- 热生效：调用之间改配置里的 model，下一次 ``_make_llm()`` 立即拾取新值。
- 注入优先：``_llm_override``（测试 mock）短路现组装路径，不触发真实构造。
"""

from unittest.mock import MagicMock, patch

import pytest

from src.business.orchestration.agent import orchestrator as orchestrator_module
from src.business.orchestration.agent.orchestrator import AgentOrchestrator
from src.data.unified_config import UnifiedConfigManager


class _RecordingLLM:
    """记录每次构造的 kwargs，每个实例独立——用于断言“每次都新建”。"""

    def __init__(self, **kwargs):
        self.kwargs = kwargs


def _build_orchestrator(config: UnifiedConfigManager) -> AgentOrchestrator:
    # 生产构造走 keyword ``config=``，不传 llm_client（走现组装路径）。
    return AgentOrchestrator(config=config)


def _stub_config(*, model="model-a", api_key="sk-test"):
    """最小可用的 MagicMock config：仅满足 ``_make_llm`` 读取的 getter。"""
    config = MagicMock(spec=UnifiedConfigManager)
    config.get_ai_provider.return_value = "openai"
    config.get_ai_model.return_value = model
    config.get_ai_api_key.return_value = api_key
    config.get_ai_base_url.return_value = None
    config.get_ai_temperature.return_value = 0.7
    config.get_ai_max_tokens.return_value = 1024
    config.get_ai_thinking_level.return_value = "off"
    config.get_ai_request_timeout.return_value = None
    return config


def test_make_llm_does_not_cache_between_calls(in_memory_db):
    """``_make_llm`` 连续两次返回不同对象，构造器各调一次（无进程级缓存）。"""
    config = _stub_config()
    orch = _build_orchestrator(config)
    with patch.object(orchestrator_module, "LangChainLLMClient", _RecordingLLM):
        first = orch._make_llm()
        second = orch._make_llm()

    assert first is not second
    assert first.kwargs["model"] == "model-a"
    assert second.kwargs["model"] == "model-a"


def test_make_llm_picks_up_config_change_without_restart(in_memory_db):
    """改配置里的 model 后，下一次 ``_make_llm()`` 立即用新值——无需重启。"""
    config = _stub_config(model="model-old")
    orch = _build_orchestrator(config)
    with patch.object(orchestrator_module, "LangChainLLMClient", _RecordingLLM):
        before = orch._make_llm()
        # 用户在设置里换了 model（配置层每次热读 SQLite）
        config.get_ai_model.return_value = "model-new"
        after = orch._make_llm()

    assert before.kwargs["model"] == "model-old"
    assert after.kwargs["model"] == "model-new"
    assert before is not after


def test_make_llm_short_circuits_on_test_override(in_memory_db):
    """``_llm_override`` 非空时直接返回注入实例，不触发真实构造。"""
    config = _stub_config()
    injected = _RecordingLLM(model="injected")
    orch = _build_orchestrator(config)
    orch._llm_override = injected

    with patch.object(
        orchestrator_module, "LangChainLLMClient", side_effect=AssertionError("不应构造新 client")
    ):
        result = orch._make_llm()

    assert result is injected
