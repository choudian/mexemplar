"""Part ②（配置热生效）行为契约：``CompressionHandler._get_llm_client()`` 现组装、不缓存。

``_get_llm_client`` 原先是懒初始化冻结模式（``if self._llm_client is None`` 一次构造、
永久持有），压缩模型配置改了不生效。现改为 override 短路 + 每次现组装。这里锁定：

- 不缓存：连续两次返回不同对象。
- 热生效：调用之间改配置里的 model，下一次立即拾取新值。
- 注入优先：``llm_client`` 构造参数非空时短路现组装路径。
"""

from unittest.mock import MagicMock, patch

import pytest

from src.business.ai import llm_client as llm_client_module
from src.business.memory.compression_handler import CompressionHandler
from src.data.unified_config import UnifiedConfigManager


class _RecordingLLM:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def _stub_config(*, model="compress-a", api_key="sk-compress"):
    config = MagicMock(spec=UnifiedConfigManager)
    config.get_memory_compression_keep_recent.return_value = 5
    config.get_memory_reference_size_threshold.return_value = 10000
    # __init__ 会构造触发策略：token 策略只需 token_threshold，避开 count/combined 分支
    config.get_memory_compression_trigger_strategy.return_value = "token"
    config.get_memory_compression_token_threshold.return_value = 999_999
    config.get_memory_compression_count_threshold.return_value = None
    config.get_compression_model_provider.return_value = "openai"
    config.get_compression_model_name.return_value = model
    config.get_compression_model_api_key.return_value = api_key
    config.get_compression_model_base_url.return_value = None
    config.get_compression_model_temperature.return_value = 0.3
    config.get_compression_model_max_tokens.return_value = 2048
    config.get_ai_request_timeout.return_value = None
    return config


def test_compression_get_llm_client_does_not_cache():
    config = _stub_config()
    handler = CompressionHandler(config)
    with patch.object(llm_client_module, "LangChainLLMClient", _RecordingLLM):
        first = handler._get_llm_client()
        second = handler._get_llm_client()

    assert first is not second
    assert first.kwargs["model"] == "compress-a"


def test_compression_get_llm_client_picks_up_config_change():
    config = _stub_config(model="compress-old")
    handler = CompressionHandler(config)
    with patch.object(llm_client_module, "LangChainLLMClient", _RecordingLLM):
        before = handler._get_llm_client()
        config.get_compression_model_name.return_value = "compress-new"
        after = handler._get_llm_client()

    assert before.kwargs["model"] == "compress-old"
    assert after.kwargs["model"] == "compress-new"


def test_compression_get_llm_client_short_circuits_on_override():
    config = _stub_config()
    injected = _RecordingLLM(model="injected")
    handler = CompressionHandler(config, llm_client=injected)

    with patch.object(
        llm_client_module, "LangChainLLMClient", side_effect=AssertionError("不应构造新 client")
    ):
        result = handler._get_llm_client()

    assert result is injected
