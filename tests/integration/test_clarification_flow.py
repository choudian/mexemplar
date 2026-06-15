"""澄清端到端链路集成测试（019）。

真实 ask_user_question handler + 真实 clarification_manager + AgentLoop +
desktop adapter（API 层 record_clarification_decision / settle stopped）。

覆盖：
- 模型发起澄清 → 用户提交 → tool result(answered) 入上下文 → 主助理同回合续跑
- pending 期间停止当前回合 → tool result(stopped) → 主助理续跑，不获得猜测答案
"""

import json
import threading
import time

import pytest

import src.business.agents.tools.clarification_manager as cm
from src.business.agents.agent_loop import AgentLoop
from src.business.agents.config import AgentConfig, AgentType, ResultType, ToolDefinition
from src.business.agents.tools.assistant_tools import (
    ASK_USER_QUESTION_SCHEMA,
    create_ask_user_question_handler,
)
from src.business.ai.llm_client import LLMResponse, ToolCallInfo
from src.desktop_api.clarifications import (
    install_clarification_signal,
    record_clarification_decision,
    settle_clarifications_for_session_stopped,
)
from tests.conftest import MockLLMClient


@pytest.fixture(autouse=True)
def reset_clarification():
    cm.reset_clarification_state_for_tests()
    install_clarification_signal()
    yield
    cm.reset_clarification_state_for_tests()


def _config():
    return AgentConfig(
        agent_type=AgentType.ASSISTANT,
        system_prompt="You are the assistant.",
        max_iterations=10,
    )


def _ask_tool(session_id):
    return ToolDefinition(
        name="ask_user_question",
        schema=ASK_USER_QUESTION_SCHEMA,
        handler=create_ask_user_question_handler(session_id),
        requires_exclusive_call=True,
        has_side_effects=False,
    )


def _ask_args():
    return {
        "questions": [
            {
                "question": "选择执行方式？",
                "header": "执行方式",
                "multiSelect": False,
                "options": [{"label": "按顺序"}, {"label": "并行"}],
            }
        ]
    }


def _run_loop_async(session_id, mock_config):
    responses = [
        LLMResponse(content=None, tool_calls=[ToolCallInfo(id="c1", name="ask_user_question", args=_ask_args())]),
        LLMResponse(content="已按你的选择继续", tool_calls=[]),
    ]
    loop = AgentLoop(_config(), MockLLMClient(responses), mock_config)
    holder = {}

    def worker():
        holder["result"] = loop.run(session_id=session_id, user_input="帮我处理", tools=[_ask_tool(session_id)])

    t = threading.Thread(target=worker)
    t.start()
    for _ in range(200):
        if cm.get_pending_for_session(session_id) is not None:
            break
        time.sleep(0.005)
    return loop, t, holder


def _tool_results(loop, session_id):
    ctx = loop._get_context_manager(session_id)
    return [m for m in ctx._msg_repo.get_context(session_id) if m.role == "tool"]


def test_clarification_answered_flow_continues(mock_config, in_memory_db):
    sid = "flow-answered"
    loop, t, holder = _run_loop_async(sid, mock_config)
    pending = cm.get_pending_for_session(sid)
    assert pending is not None

    # 经 API 层函数提交（模拟 POST decision）
    out = record_clarification_decision(
        sid, pending.request_id, "submit",
        [{"questionId": "q1", "selectedOptionIds": ["q1o2"], "otherText": None}],
    )
    assert out["status"] == "answered"

    t.join(timeout=3)
    assert holder["result"].result_type == ResultType.COMPLETED
    results = _tool_results(loop, sid)
    assert len(results) == 1
    parsed = json.loads(results[0].content)
    assert parsed["status"] == "answered"
    assert parsed["answers"][0]["selectedLabels"] == ["并行"]


def test_clarification_stop_settles_stopped(mock_config, in_memory_db):
    sid = "flow-stopped"
    loop, t, holder = _run_loop_async(sid, mock_config)
    pending = cm.get_pending_for_session(sid)
    assert pending is not None

    settled = settle_clarifications_for_session_stopped(sid)
    assert settled == [pending.request_id]

    t.join(timeout=3)
    results = _tool_results(loop, sid)
    assert len(results) == 1
    parsed = json.loads(results[0].content)
    # 模型拿到 stopped，绝不是猜测答案
    assert parsed["status"] == "stopped"
    assert parsed["answers"] == []
