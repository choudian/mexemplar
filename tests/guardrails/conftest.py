"""guardrail 工具集测试共享 fixture。"""

from types import SimpleNamespace

import pytest

from src.business.orchestration.agent import AgentOrchestrator


@pytest.fixture
def orchestrator(mock_config):
    """最小装配的 AgentOrchestrator——guardrail 工具集测试复用。

    替代各测试文件里逐字复制的 ``_orchestrator(mock_config)`` 本地 helper：
    统一 AgentOrchestrator 构造方式，未来 __init__ 签名变更只改这一处。
    """
    return AgentOrchestrator(
        llm_client=SimpleNamespace(),
        config=mock_config,
        llm_reviewer=SimpleNamespace(),
    )
