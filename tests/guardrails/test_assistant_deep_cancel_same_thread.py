"""014 门卫：助理深度取消依赖"同线程同步委派"承重不变量（E1）。

深度取消（停止一次父子皆停）成立的前提是：助理委派出的子代理 / 专员与父在**同一线程
同步**执行子 loop——只有这样 `run_context` 的 ContextVar 才能沿同步调用栈传播，子 loop
`get_current()` 读到的才是父助理那一份 `cancel_event`。

一旦委派改走线程 / 异步执行（ThreadPool、asyncio.to_thread、新 Thread 等），ContextVar 不再
传播，子 loop 读不到父的 cancel_event，"停止父→子也停"失效。本门卫一旦失败，即提示重审取消机制。
"""

import threading
from unittest.mock import MagicMock, patch

from src.business.agents import run_context
from src.business.agents.config import AgentResult, AgentType, ResultType
from src.business.orchestration.agent.orchestrator import AgentOrchestrator


def test_subagent_delegation_runs_in_parent_thread_and_inherits_cancel_context(
    mock_config, in_memory_db
):
    run_context.reset_for_tests()
    orch = AgentOrchestrator(MagicMock(), mock_config)
    parent = "parent-guard-001"
    # 模拟 worker 线程入口登记父运行上下文
    parent_ctx = run_context.begin(parent)

    captured: dict = {}

    def fake_run(session_id, user_input=None, tools=None, system_prompt_override=None):
        # 记录子 loop 实际执行时所在线程与可见的运行上下文
        captured["thread_ident"] = threading.get_ident()
        captured["seen_ctx"] = run_context.get_current()
        return AgentResult(result_type=ResultType.COMPLETED)

    try:
        with (
            patch("src.business.orchestration.agent.orchestrator.AgentLoop") as MockLoop,
            patch.object(orch, "_build_delegated_executor_tools", return_value=[]),
            patch.object(orch, "_resolve_user_tool_ids", return_value=set()),
            patch.object(orch, "_extract_latest_assistant_text", return_value="done"),
            patch.object(orch, "_record_delegation_signal"),
        ):
            MockLoop.return_value.run.side_effect = fake_run
            res = orch._delegate_to_subagent(parent_session_id=parent, task_description="做点事")
    finally:
        run_context.end()
        run_context.reset_for_tests()

    assert res["success"] is True
    # 承重不变量①：子 loop 在父线程同步执行（不得改走线程/异步）
    assert captured["thread_ident"] == threading.get_ident()
    # 承重不变量②：ContextVar 沿同步调用栈传播——子 loop 读到父的 cancel_event，深度取消可生效
    seen = captured["seen_ctx"]
    assert seen is not None, "子 loop 未继承父运行上下文——委派疑似改走了线程/异步，深度取消将失效"
    assert seen.root_session_id == parent
    assert seen.cancel_event is parent_ctx.cancel_event
