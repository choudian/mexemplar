"""Orchestrator ASSISTANT 类型守卫回归测试。

验证 run_agent 对 ASSISTANT 类型的 user_input 校验：
- str 输入正常通过
- dict 输入（带 role+content）正常通过（reentry 路径依赖）
- dict 缺少 role/content 返回 ERROR
- 空 str 返回 ERROR
"""

import uuid

from src.business.agents.config import AgentType
from src.business.ai.llm_client import LLMResponse
from src.business.orchestration.agent import AgentOrchestrator
from src.data.models_sqlite import Session
from src.data.repositories import SessionRepository

from tests.conftest import MockLLMClient


def _create_session() -> str:
    session_id = f"ast_{uuid.uuid4().hex[:12]}"
    repo = SessionRepository()
    repo.create(
        Session(
            session_id=session_id,
            workflow_id=None,
            agent_type=AgentType.ASSISTANT,
            status="active",
        )
    )
    return session_id


def test_assistant_str_input_passes_guard(in_memory_db, mock_config):
    """str user_input 正常通过守卫，agent loop 执行并返回结果。"""
    mock_llm = MockLLMClient([LLMResponse(content="你好", tool_calls=[])])
    orch = AgentOrchestrator(mock_llm, mock_config)

    session_id = _create_session()
    result = orch.run_agent(AgentType.ASSISTANT, "你好", session_id=session_id)

    assert result is not None
    assert result.result_type.value == "completed"


def test_assistant_dict_input_passes_guard(in_memory_db, mock_config):
    """dict user_input（带 role+content）通过守卫，以 program 角色注入上下文。"""
    mock_llm = MockLLMClient([LLMResponse(content="收到", tool_calls=[])])
    orch = AgentOrchestrator(mock_llm, mock_config)

    session_id = _create_session()
    result = orch.run_agent(
        AgentType.ASSISTANT,
        {"role": "program", "content": "子代理结果：任务完成"},
        session_id=session_id,
    )

    assert result is not None
    assert result.result_type.value == "completed"


def test_assistant_dict_missing_role_returns_error(in_memory_db, mock_config):
    """dict 缺少 role 键 → 返回 ERROR。"""
    mock_llm = MockLLMClient([])
    orch = AgentOrchestrator(mock_llm, mock_config)
    session_id = _create_session()

    result = orch.run_agent(
        AgentType.ASSISTANT,
        {"content": "只有 content"},
        session_id=session_id,
    )

    assert result is not None
    assert result.result_type.value == "error"
    assert "role" in result.error


def test_assistant_dict_missing_content_returns_error(in_memory_db, mock_config):
    """dict 缺少 content 键 → 返回 ERROR。"""
    mock_llm = MockLLMClient([])
    orch = AgentOrchestrator(mock_llm, mock_config)
    session_id = _create_session()

    result = orch.run_agent(
        AgentType.ASSISTANT,
        {"role": "program"},
        session_id=session_id,
    )

    assert result is not None
    assert result.result_type.value == "error"
    assert "content" in result.error


def test_assistant_empty_str_returns_error(in_memory_db, mock_config):
    """空字符串 → 返回 ERROR。"""
    mock_llm = MockLLMClient([])
    orch = AgentOrchestrator(mock_llm, mock_config)
    session_id = _create_session()

    result = orch.run_agent(AgentType.ASSISTANT, "", session_id=session_id)

    assert result is not None
    assert result.result_type.value == "error"


def test_assistant_none_input_skips_guard(in_memory_db, mock_config):
    """None user_input（reuse 模式或无输入续跑）不触发守卫。"""
    mock_llm = MockLLMClient([LLMResponse(content="续跑", tool_calls=[])])
    orch = AgentOrchestrator(mock_llm, mock_config)
    session_id = _create_session()

    result = orch.run_agent(
        AgentType.ASSISTANT,
        None,
        session_id=session_id,
        assistant_reuse_user_message=True,
    )

    assert result is not None
