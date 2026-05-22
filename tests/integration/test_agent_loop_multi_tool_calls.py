"""
AgentLoop 多工具调用集成测试

覆盖：
- 普通多工具成功配对 (US1)
- 普通多工具失败级联 (US1)
- 纯文本 "error" 不是失败 (US1)
- 中断型混合拒绝 (US2)
- 多中断型拒绝 (US2)
- Solo 中断异常 (US2)
- Handler 合同违约 (US2)
- 恢复路径 (US3)
- callable tools 路径 (US1/US3)
- 单工具回归 (regression)
"""

import json
import pytest

from src.business.agents.agent_loop import AgentLoop
from src.business.agents.config import (
    AgentConfig,
    AgentType,
    ToolDefinition,
    ToolSignal,
    ResultType,
)
from src.business.ai.llm_client import LLMResponse, ToolCallInfo
from src.business.memory.context_manager import ContextManager
from tests.conftest import MockLLMClient

# -- Shared fixtures --


@pytest.fixture
def loop_config():
    return AgentConfig(
        agent_type=AgentType.PM,
        system_prompt="You are a test agent.",
        max_iterations=10,
    )


def _tool_a(**kwargs):
    return json.dumps({"result": "a_success"})


def _tool_b(**kwargs):
    return json.dumps({"result": "b_success"})


def _make_tools():
    return [
        ToolDefinition(name="tool_a", schema={"type": "object", "properties": {}}, handler=_tool_a),
        ToolDefinition(name="tool_b", schema={"type": "object", "properties": {}}, handler=_tool_b),
    ]


def _seed_session(session_id, mock_config, tool_calls_dicts, existing_results=None):
    """通过 ContextManager 直接填充会话种子数据，避免依赖 AgentLoop 私有 API。"""
    ctx = ContextManager(session_id, mock_config)
    ctx.save_message(role="system", content="You are a test agent.")
    ctx.save_user_message("test")
    ctx.save_assistant_message(content=None, tool_calls=json.dumps(tool_calls_dicts))
    for result in existing_results or []:
        ctx.save_tool_result(**result)


# =============================================================================
# US1: 普通多工具调用完整配对
# =============================================================================


def test_ordinary_two_tool_success(loop_config, mock_config, in_memory_db):
    """SC-001: Two ordinary tool calls -> both executed in order, both results persisted."""
    responses = [
        LLMResponse(
            content=None,
            tool_calls=[
                ToolCallInfo(id="call_1", name="tool_a", args={}),
                ToolCallInfo(id="call_2", name="tool_b", args={}),
            ],
        ),
        LLMResponse(content="done", tool_calls=[]),
    ]
    llm = MockLLMClient(responses)
    loop = AgentLoop(loop_config, llm, mock_config)
    result = loop.run(
        session_id="test-multi-2",
        user_input="test",
        tools=_make_tools(),
    )
    assert result.result_type == ResultType.COMPLETED
    ctx = loop._get_context_manager("test-multi-2")
    messages = ctx._msg_repo.get_context("test-multi-2")
    tool_results = [m for m in messages if m.role == "tool"]
    assert len(tool_results) == 2
    assert tool_results[0].tool_call_id == "call_1"
    assert tool_results[1].tool_call_id == "call_2"


def test_ordinary_three_tool_order(loop_config, mock_config, in_memory_db):
    """SC-002: Three ordinary tool calls execute in model-provided order."""
    execution_order = []

    def _tracking_handler(name):
        def handler(**kwargs):
            execution_order.append(name)
            return json.dumps({"result": f"{name}_ok"})

        return handler

    tools = [
        ToolDefinition(
            name="t1", schema={"type": "object", "properties": {}}, handler=_tracking_handler("t1")
        ),
        ToolDefinition(
            name="t2", schema={"type": "object", "properties": {}}, handler=_tracking_handler("t2")
        ),
        ToolDefinition(
            name="t3", schema={"type": "object", "properties": {}}, handler=_tracking_handler("t3")
        ),
    ]

    responses = [
        LLMResponse(
            content=None,
            tool_calls=[
                ToolCallInfo(id="c1", name="t1", args={}),
                ToolCallInfo(id="c2", name="t2", args={}),
                ToolCallInfo(id="c3", name="t3", args={}),
            ],
        ),
        LLMResponse(content="done", tool_calls=[]),
    ]
    llm = MockLLMClient(responses)
    loop = AgentLoop(loop_config, llm, mock_config)
    result = loop.run(session_id="test-order-3", user_input="test", tools=tools)
    assert result.result_type == ResultType.COMPLETED
    assert execution_order == ["t1", "t2", "t3"]


def test_ordinary_failure_cascade(loop_config, mock_config, in_memory_db):
    """SC-003: Second tool returns standardized error -> third gets not_executed."""
    call_count = {"t1": 0, "t2": 0, "t3": 0}

    def _t1(**kwargs):
        call_count["t1"] += 1
        return "success"

    def _t2(**kwargs):
        call_count["t2"] += 1
        return json.dumps({"error": "something_failed"})

    def _t3(**kwargs):
        call_count["t3"] += 1
        return "should not run"

    tools = [
        ToolDefinition(name="t1", schema={"type": "object", "properties": {}}, handler=_t1),
        ToolDefinition(name="t2", schema={"type": "object", "properties": {}}, handler=_t2),
        ToolDefinition(name="t3", schema={"type": "object", "properties": {}}, handler=_t3),
    ]

    responses = [
        LLMResponse(
            content=None,
            tool_calls=[
                ToolCallInfo(id="c1", name="t1", args={}),
                ToolCallInfo(id="c2", name="t2", args={}),
                ToolCallInfo(id="c3", name="t3", args={}),
            ],
        ),
        LLMResponse(content="replanned", tool_calls=[]),
    ]
    llm = MockLLMClient(responses)
    loop = AgentLoop(loop_config, llm, mock_config)
    loop.run(session_id="test-cascade", user_input="test", tools=tools)
    assert call_count == {"t1": 1, "t2": 1, "t3": 0}
    ctx = loop._get_context_manager("test-cascade")
    messages = ctx._msg_repo.get_context("test-cascade")
    tool_results = [m for m in messages if m.role == "tool"]
    assert len(tool_results) == 3
    t3_result = json.loads(tool_results[2].content)
    assert t3_result["error"] == "not_executed"


def test_plain_text_error_not_failure(loop_config, mock_config, in_memory_db):
    """SC-003a: Plain text containing 'error' does not stop later tools."""
    call_count = {"t1": 0, "t2": 0}

    def _t1(**kwargs):
        call_count["t1"] += 1
        return "An error occurred during processing"

    def _t2(**kwargs):
        call_count["t2"] += 1
        return "second tool ran"

    tools = [
        ToolDefinition(name="t1", schema={"type": "object", "properties": {}}, handler=_t1),
        ToolDefinition(name="t2", schema={"type": "object", "properties": {}}, handler=_t2),
    ]

    responses = [
        LLMResponse(
            content=None,
            tool_calls=[
                ToolCallInfo(id="c1", name="t1", args={}),
                ToolCallInfo(id="c2", name="t2", args={}),
            ],
        ),
        LLMResponse(content="done", tool_calls=[]),
    ]
    llm = MockLLMClient(responses)
    loop = AgentLoop(loop_config, llm, mock_config)
    result = loop.run(session_id="test-plain-err", user_input="test", tools=tools)
    assert call_count == {"t1": 1, "t2": 1}
    assert result.result_type == ResultType.COMPLETED


# =============================================================================
# US2: 中断型工具行为可预期
# =============================================================================


def test_mixed_interrupt_ordinary_batch(loop_config, mock_config, in_memory_db):
    """SC-004: interrupting + ordinary -> zero handlers, invalid_model_output for all."""
    call_count = {"interrupt_tool": 0, "tool_a": 0}

    def _interrupt_handler(**kwargs):
        call_count["interrupt_tool"] += 1
        return ToolSignal(result_type=ResultType.COMPLETED, display_text="[done]")

    tools = [
        ToolDefinition(
            name="interrupt_tool",
            schema={"type": "object", "properties": {}},
            handler=_interrupt_handler,
            is_interrupting=True,
        ),
        ToolDefinition(
            name="tool_a",
            schema={"type": "object", "properties": {}},
            handler=lambda **kw: (
                call_count.__setitem__("tool_a", call_count["tool_a"] + 1) or "ok"
            ),
        ),
    ]

    responses = [
        LLMResponse(
            content=None,
            tool_calls=[
                ToolCallInfo(id="c1", name="interrupt_tool", args={}),
                ToolCallInfo(id="c2", name="tool_a", args={}),
            ],
        ),
        LLMResponse(content="replanned", tool_calls=[]),
    ]
    llm = MockLLMClient(responses)
    loop = AgentLoop(loop_config, llm, mock_config)
    loop.run(session_id="test-mixed", user_input="test", tools=tools)
    assert call_count == {"interrupt_tool": 0, "tool_a": 0}
    ctx = loop._get_context_manager("test-mixed")
    messages = ctx._msg_repo.get_context("test-mixed")
    tool_results = [m for m in messages if m.role == "tool"]
    assert len(tool_results) == 2
    for tr in tool_results:
        parsed = json.loads(tr.content)
        assert parsed["error"] == "invalid_model_output"


def test_multi_interrupt_batch(loop_config, mock_config, in_memory_db):
    """FR-006: Two interrupting tools -> zero handlers, invalid_model_output for all."""
    call_count = 0

    def _interrupt_handler(**kwargs):
        nonlocal call_count
        call_count += 1
        return ToolSignal(result_type=ResultType.COMPLETED, display_text="[done]")

    tools = [
        ToolDefinition(
            name="interrupt_a",
            schema={"type": "object", "properties": {}},
            handler=_interrupt_handler,
            is_interrupting=True,
        ),
        ToolDefinition(
            name="interrupt_b",
            schema={"type": "object", "properties": {}},
            handler=_interrupt_handler,
            is_interrupting=True,
        ),
    ]

    responses = [
        LLMResponse(
            content=None,
            tool_calls=[
                ToolCallInfo(id="c1", name="interrupt_a", args={}),
                ToolCallInfo(id="c2", name="interrupt_b", args={}),
            ],
        ),
        LLMResponse(content="replanned", tool_calls=[]),
    ]
    llm = MockLLMClient(responses)
    loop = AgentLoop(loop_config, llm, mock_config)
    loop.run(session_id="test-multi-int", user_input="test", tools=tools)
    assert call_count == 0
    ctx = loop._get_context_manager("test-multi-int")
    messages = ctx._msg_repo.get_context("test-multi-int")
    tool_results = [m for m in messages if m.role == "tool"]
    assert len(tool_results) == 2
    for tr in tool_results:
        parsed = json.loads(tr.content)
        assert parsed["error"] == "invalid_model_output"


def test_solo_interrupt_handler_exception(loop_config, mock_config, in_memory_db):
    """Decision 10: Solo interrupt handler raises -> handler_exception, loop continues."""

    def _failing_interrupt(**kwargs):
        raise RuntimeError("handler exploded")

    tools = [
        ToolDefinition(
            name="failing_interrupt",
            schema={"type": "object", "properties": {}},
            handler=_failing_interrupt,
            is_interrupting=True,
        ),
    ]

    responses = [
        LLMResponse(
            content=None,
            tool_calls=[ToolCallInfo(id="c1", name="failing_interrupt", args={})],
        ),
        LLMResponse(content="replanned after error", tool_calls=[]),
    ]
    llm = MockLLMClient(responses)
    loop = AgentLoop(loop_config, llm, mock_config)
    result = loop.run(session_id="test-int-exc", user_input="test", tools=tools)
    assert result.result_type == ResultType.COMPLETED
    ctx = loop._get_context_manager("test-int-exc")
    messages = ctx._msg_repo.get_context("test-int-exc")
    tool_results = [m for m in messages if m.role == "tool"]
    assert len(tool_results) == 1
    parsed = json.loads(tool_results[0].content)
    assert parsed["error"] == "handler_exception"


def test_handler_contract_violation_interrupt_returns_str(loop_config, mock_config, in_memory_db):
    """FR-016: is_interrupting=True handler returns str -> handler_contract_violation."""

    def _str_returning_interrupt(**kwargs):
        return "I should have returned ToolSignal"

    tools = [
        ToolDefinition(
            name="bad_interrupt",
            schema={"type": "object", "properties": {}},
            handler=_str_returning_interrupt,
            is_interrupting=True,
        ),
    ]

    responses = [
        LLMResponse(
            content=None,
            tool_calls=[ToolCallInfo(id="c1", name="bad_interrupt", args={})],
        ),
        LLMResponse(content="replanned", tool_calls=[]),
    ]
    llm = MockLLMClient(responses)
    loop = AgentLoop(loop_config, llm, mock_config)
    result = loop.run(session_id="test-int-str", user_input="test", tools=tools)
    assert result.result_type == ResultType.COMPLETED
    ctx = loop._get_context_manager("test-int-str")
    messages = ctx._msg_repo.get_context("test-int-str")
    tool_results = [m for m in messages if m.role == "tool"]
    assert len(tool_results) == 1
    parsed = json.loads(tool_results[0].content)
    assert parsed["error"] == "handler_contract_violation"


def test_handler_contract_violation_ordinary_returns_signal(loop_config, mock_config, in_memory_db):
    """FR-016: is_interrupting=False returns ToolSignal in multi-call batch -> cascade."""
    call_count = {"bad_ordinary": 0, "t2": 0}

    def _signal_returning_ordinary(**kwargs):
        call_count["bad_ordinary"] += 1
        return ToolSignal(result_type=ResultType.COMPLETED, display_text="[unexpected]")

    def _t2(**kwargs):
        call_count["t2"] += 1
        return "should not run"

    tools = [
        ToolDefinition(
            name="bad_ordinary",
            schema={"type": "object", "properties": {}},
            handler=_signal_returning_ordinary,
            is_interrupting=False,
        ),
        ToolDefinition(
            name="t2",
            schema={"type": "object", "properties": {}},
            handler=_t2,
        ),
    ]

    responses = [
        LLMResponse(
            content=None,
            tool_calls=[
                ToolCallInfo(id="c1", name="bad_ordinary", args={}),
                ToolCallInfo(id="c2", name="t2", args={}),
            ],
        ),
        LLMResponse(content="replanned", tool_calls=[]),
    ]
    llm = MockLLMClient(responses)
    loop = AgentLoop(loop_config, llm, mock_config)
    loop.run(session_id="test-ord-signal", user_input="test", tools=tools)
    assert call_count == {"bad_ordinary": 1, "t2": 0}
    ctx = loop._get_context_manager("test-ord-signal")
    messages = ctx._msg_repo.get_context("test-ord-signal")
    tool_results = [m for m in messages if m.role == "tool"]
    assert len(tool_results) == 2
    parsed_c1 = json.loads(tool_results[0].content)
    assert parsed_c1["error"] == "handler_contract_violation"
    parsed_c2 = json.loads(tool_results[1].content)
    assert parsed_c2["error"] == "not_executed"


# =============================================================================
# US3: 会话恢复不重复或遗漏工具
# =============================================================================


def test_recovery_partial_results(loop_config, mock_config, in_memory_db):
    """SC-005: session has 3-call assistant msg + 1 result -> recovery runs only calls 2, 3."""
    execution_order = []

    def _tracking_handler(name):
        def handler(**kwargs):
            execution_order.append(name)
            return json.dumps({"result": f"{name}_ok"})

        return handler

    tools = [
        ToolDefinition(
            name="t1", schema={"type": "object", "properties": {}}, handler=_tracking_handler("t1")
        ),
        ToolDefinition(
            name="t2", schema={"type": "object", "properties": {}}, handler=_tracking_handler("t2")
        ),
        ToolDefinition(
            name="t3", schema={"type": "object", "properties": {}}, handler=_tracking_handler("t3")
        ),
    ]

    _seed_session(
        "test-recovery",
        mock_config,
        [
            {"id": "c1", "name": "t1", "args": {}},
            {"id": "c2", "name": "t2", "args": {}},
            {"id": "c3", "name": "t3", "args": {}},
        ],
        existing_results=[{"tool_call_id": "c1", "tool_name": "t1", "content": "already done"}],
    )

    responses = [
        LLMResponse(content="done after recovery", tool_calls=[]),
    ]
    llm = MockLLMClient(responses)
    loop = AgentLoop(loop_config, llm, mock_config)
    result = loop.run(session_id="test-recovery", user_input=None, tools=tools)
    assert result.result_type == ResultType.COMPLETED
    assert execution_order == ["t2", "t3"]


def test_recovery_all_complete(loop_config, mock_config, in_memory_db):
    """US3 Acceptance 2: all tool calls already have results -> no re-execution."""
    execution_order = []

    def _tracking_handler(name):
        def handler(**kwargs):
            execution_order.append(name)
            return json.dumps({"result": f"{name}_ok"})

        return handler

    tools = [
        ToolDefinition(
            name="t1", schema={"type": "object", "properties": {}}, handler=_tracking_handler("t1")
        ),
        ToolDefinition(
            name="t2", schema={"type": "object", "properties": {}}, handler=_tracking_handler("t2")
        ),
    ]

    _seed_session(
        "test-recovery-done",
        mock_config,
        [
            {"id": "c1", "name": "t1", "args": {}},
            {"id": "c2", "name": "t2", "args": {}},
        ],
        existing_results=[
            {"tool_call_id": "c1", "tool_name": "t1", "content": "done1"},
            {"tool_call_id": "c2", "tool_name": "t2", "content": "done2"},
        ],
    )

    responses = [
        LLMResponse(content="all done", tool_calls=[]),
    ]
    llm = MockLLMClient(responses)
    loop = AgentLoop(loop_config, llm, mock_config)
    result = loop.run(session_id="test-recovery-done", user_input=None, tools=tools)
    assert result.result_type == ResultType.COMPLETED
    assert execution_order == []


def test_recovery_missing_handler(loop_config, mock_config, in_memory_db):
    """SC-006: first missing call has no handler -> unknown_tool + not_executed cascade for later."""
    execution_order = []

    def _tracking_handler(name):
        def handler(**kwargs):
            execution_order.append(name)
            return json.dumps({"result": f"{name}_ok"})

        return handler

    tools = [
        # Note: 't1' is NOT in tools — it has no handler
        ToolDefinition(
            name="t2", schema={"type": "object", "properties": {}}, handler=_tracking_handler("t2")
        ),
        ToolDefinition(
            name="t3", schema={"type": "object", "properties": {}}, handler=_tracking_handler("t3")
        ),
    ]

    _seed_session(
        "test-recovery-missing",
        mock_config,
        [
            {"id": "c1", "name": "t1", "args": {}},
            {"id": "c2", "name": "t2", "args": {}},
            {"id": "c3", "name": "t3", "args": {}},
        ],
    )

    responses = [
        LLMResponse(content="replanned", tool_calls=[]),
    ]
    llm = MockLLMClient(responses)
    loop = AgentLoop(loop_config, llm, mock_config)
    loop.run(session_id="test-recovery-missing", user_input=None, tools=tools)
    assert execution_order == []
    ctx = loop._get_context_manager("test-recovery-missing")
    messages = ctx._msg_repo.get_context("test-recovery-missing")
    tool_results = [m for m in messages if m.role == "tool"]
    assert len(tool_results) == 3
    # t1: unknown_tool (no handler)
    parsed_c1 = json.loads(tool_results[0].content)
    assert parsed_c1["error"] == "unknown_tool", f"c1 expected unknown_tool, got {parsed_c1}"
    # t2: not_executed (cascade after t1 failure)
    parsed_c2 = json.loads(tool_results[1].content)
    assert parsed_c2["error"] == "not_executed", f"c2 expected not_executed, got {parsed_c2}"
    # t3: not_executed (cascade continues)
    parsed_c3 = json.loads(tool_results[2].content)
    assert parsed_c3["error"] == "not_executed", f"c3 expected not_executed, got {parsed_c3}"


def test_recovery_corrupted_tool_call(loop_config, mock_config, in_memory_db):
    """US3 Acceptance 4: tool call missing 'name' field -> explicit unknown_tool error result."""
    tools = [
        ToolDefinition(
            name="t1", schema={"type": "object", "properties": {}}, handler=lambda **kw: "ok"
        ),
    ]

    _seed_session(
        "test-recovery-corrupt",
        mock_config,
        [
            {"id": "c1", "args": {}},  # missing 'name' -> corrupted
        ],
    )

    responses = [
        LLMResponse(content="done", tool_calls=[]),
    ]
    llm = MockLLMClient(responses)
    loop = AgentLoop(loop_config, llm, mock_config)
    result = loop.run(session_id="test-recovery-corrupt", user_input=None, tools=tools)
    assert result.result_type == ResultType.COMPLETED
    # 损坏的 tool call 必须获得配对错误结果，不能遗留未配对 tool_call
    ctx = loop._get_context_manager("test-recovery-corrupt")
    messages = ctx._msg_repo.get_context("test-recovery-corrupt")
    tool_results = [m for m in messages if m.role == "tool"]
    assert len(tool_results) == 1, "corrupted tool call must get a paired error result"
    parsed = json.loads(tool_results[0].content)
    assert parsed["error"] == "unknown_tool", f"expected unknown_tool, got {parsed}"


# =============================================================================
# callable tools 路径 (assistant 动态工具)
# =============================================================================


def test_callable_tools_multi_tool_success(loop_config, mock_config, in_memory_db):
    """SC-008: callable tools factory path works with multi-tool batch."""
    responses = [
        LLMResponse(
            content=None,
            tool_calls=[
                ToolCallInfo(id="call_1", name="tool_a", args={}),
                ToolCallInfo(id="call_2", name="tool_b", args={}),
            ],
        ),
        LLMResponse(content="done", tool_calls=[]),
    ]
    llm = MockLLMClient(responses)
    loop = AgentLoop(loop_config, llm, mock_config)

    call_count = {"factory": 0}

    def tool_factory():
        call_count["factory"] += 1
        return _make_tools()

    result = loop.run(
        session_id="test-callable-multi",
        user_input="test",
        tools=tool_factory,
    )
    assert result.result_type == ResultType.COMPLETED
    assert call_count["factory"] >= 1
    ctx = loop._get_context_manager("test-callable-multi")
    messages = ctx._msg_repo.get_context("test-callable-multi")
    tool_results = [m for m in messages if m.role == "tool"]
    assert len(tool_results) == 2
    assert tool_results[0].tool_call_id == "call_1"
    assert tool_results[1].tool_call_id == "call_2"


def test_callable_tools_recovery(loop_config, mock_config, in_memory_db):
    """SC-009: callable tools recovery path rebuilds tools before processing pending calls."""
    execution_order = []

    def _tracking_handler(name):
        def handler(**kwargs):
            execution_order.append(name)
            return json.dumps({"result": f"{name}_ok"})

        return handler

    tools_list = [
        ToolDefinition(
            name="t1", schema={"type": "object", "properties": {}}, handler=_tracking_handler("t1")
        ),
        ToolDefinition(
            name="t2", schema={"type": "object", "properties": {}}, handler=_tracking_handler("t2")
        ),
    ]

    _seed_session(
        "test-callable-recovery",
        mock_config,
        [
            {"id": "c1", "name": "t1", "args": {}},
            {"id": "c2", "name": "t2", "args": {}},
        ],
        existing_results=[{"tool_call_id": "c1", "tool_name": "t1", "content": "already done"}],
    )

    responses = [
        LLMResponse(content="done after recovery", tool_calls=[]),
    ]
    llm = MockLLMClient(responses)
    loop = AgentLoop(loop_config, llm, mock_config)

    def tool_factory():
        return tools_list

    result = loop.run(
        session_id="test-callable-recovery",
        user_input=None,
        tools=tool_factory,
    )
    assert result.result_type == ResultType.COMPLETED
    assert execution_order == ["t2"]


# =============================================================================
# Regression: 单工具回归
# =============================================================================


def test_single_tool_unchanged(loop_config, mock_config, in_memory_db):
    """SC-007: Single-tool workflows unchanged after multi-tool fix."""
    responses = [
        LLMResponse(
            content=None,
            tool_calls=[ToolCallInfo(id="c1", name="tool_a", args={})],
        ),
        LLMResponse(content="done", tool_calls=[]),
    ]
    llm = MockLLMClient(responses)
    loop = AgentLoop(loop_config, llm, mock_config)
    result = loop.run(
        session_id="test-single-regression",
        user_input="test",
        tools=_make_tools(),
    )
    assert result.result_type == ResultType.COMPLETED
    ctx = loop._get_context_manager("test-single-regression")
    messages = ctx._msg_repo.get_context("test-single-regression")
    tool_results = [m for m in messages if m.role == "tool"]
    assert len(tool_results) == 1
    assert tool_results[0].tool_call_id == "c1"


# =============================================================================
# 补充覆盖：solo interrupt 成功 + unknown tool 混合
# =============================================================================


def test_solo_interrupt_success(loop_config, mock_config, in_memory_db):
    """Solo interrupting tool returns ToolSignal -> AgentResult(COMPLETED)."""

    def _success_interrupt(**kwargs):
        return ToolSignal(result_type=ResultType.COMPLETED, display_text="[需求已提交]")

    tools = [
        ToolDefinition(
            name="submit_requirements",
            schema={"type": "object", "properties": {}},
            handler=_success_interrupt,
            is_interrupting=True,
        ),
    ]

    responses = [
        LLMResponse(
            content=None,
            tool_calls=[ToolCallInfo(id="c1", name="submit_requirements", args={})],
        ),
    ]
    llm = MockLLMClient(responses)
    loop = AgentLoop(loop_config, llm, mock_config)
    result = loop.run(session_id="test-solo-int-success", user_input="test", tools=tools)
    assert result.result_type == ResultType.COMPLETED
    ctx = loop._get_context_manager("test-solo-int-success")
    messages = ctx._msg_repo.get_context("test-solo-int-success")
    tool_results = [m for m in messages if m.role == "tool"]
    assert len(tool_results) == 1
    assert "[需求已提交]" in tool_results[0].content


def test_reply_to_user_interrupt_persists_display_message(loop_config, mock_config, in_memory_db):
    """reply_to_user ToolSignal should be visible in assistant display history."""

    def _reply_to_user(**kwargs):
        return ToolSignal(
            result_type=ResultType.NEEDS_USER_INPUT,
            display_text=kwargs["text"],
        )

    tools = [
        ToolDefinition(
            name="reply_to_user",
            schema={"type": "object", "properties": {}},
            handler=_reply_to_user,
            is_interrupting=True,
        ),
    ]

    responses = [
        LLMResponse(
            content=None,
            tool_calls=[
                ToolCallInfo(
                    id="reply-call-1",
                    name="reply_to_user",
                    args={"text": "这是用户应看到的回复。"},
                )
            ],
        ),
    ]
    llm = MockLLMClient(responses)
    loop = AgentLoop(loop_config, llm, mock_config)

    result = loop.run(session_id="test-reply-display", user_input="test", tools=tools)

    assert result.result_type == ResultType.NEEDS_USER_INPUT
    assert result.question == ""
    ctx = loop._get_context_manager("test-reply-display")
    messages = ctx._msg_repo.get_context("test-reply-display")
    assert any(
        message.role == "assistant" and message.content == "这是用户应看到的回复。"
        for message in messages
    )


def test_normal_flow_unknown_tool_mixed_with_known(loop_config, mock_config, in_memory_db):
    """LLM returns unknown tool + known tool in same batch -> unknown_tool cascade."""
    call_count = {"tool_a": 0}

    def _tool_a(**kwargs):
        call_count["tool_a"] += 1
        return "ok"

    tools = [
        ToolDefinition(name="tool_a", schema={"type": "object", "properties": {}}, handler=_tool_a),
    ]

    responses = [
        LLMResponse(
            content=None,
            tool_calls=[
                ToolCallInfo(id="c1", name="hallucinated_tool", args={}),
                ToolCallInfo(id="c2", name="tool_a", args={}),
            ],
        ),
        LLMResponse(content="replanned", tool_calls=[]),
    ]
    llm = MockLLMClient(responses)
    loop = AgentLoop(loop_config, llm, mock_config)
    loop.run(session_id="test-unknown-mixed", user_input="test", tools=tools)
    assert call_count["tool_a"] == 0  # unknown_tool cascade should suppress tool_a
    ctx = loop._get_context_manager("test-unknown-mixed")
    messages = ctx._msg_repo.get_context("test-unknown-mixed")
    tool_results = [m for m in messages if m.role == "tool"]
    assert len(tool_results) == 2
    parsed_c1 = json.loads(tool_results[0].content)
    assert parsed_c1["error"] == "unknown_tool"
    parsed_c2 = json.loads(tool_results[1].content)
    assert parsed_c2["error"] == "not_executed"
