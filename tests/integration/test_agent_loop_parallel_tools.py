"""AgentLoop parallel tool partitioning and persistence tests."""

from __future__ import annotations

import json
import threading
import time

import pytest

from src.business.agents.agent_loop import AgentLoop
from src.business.agents.config import AgentConfig, AgentType, ToolDefinition
from src.business.agents.tools.builtin_general_tools import BUILTIN_GENERAL_TOOLS
from src.business.agents.tools.dynamic_tool_manager import create_assistant_search_tools
from src.business.agents.tools.skill_methodology_tools import LOAD_SKILL_METHODOLOGY
from src.business.ai.llm_client import ToolCallInfo
from tests.conftest import MockLLMClient


class _RecordingContext:
    def __init__(self) -> None:
        self.session_id = "parallel-tools-session"
        self.results: list[dict[str, str]] = []
        self.save_thread_ids: list[int] = []

    def save_tool_result(self, *, tool_call_id: str, tool_name: str, content: str):
        self.save_thread_ids.append(threading.get_ident())
        self.results.append(
            {
                "tool_call_id": tool_call_id,
                "tool_name": tool_name,
                "content": content,
            }
        )


@pytest.fixture
def loop(mock_config, in_memory_db):
    config = AgentConfig(
        agent_type=AgentType.PM,
        system_prompt="parallel tool test",
    )
    return AgentLoop(config, MockLLMClient([]), mock_config)


def _definition(
    name: str,
    handler,
    *,
    safe: bool,
    side_effects: bool = False,
) -> ToolDefinition:
    return ToolDefinition(
        name=name,
        schema={"type": "object", "properties": {}},
        handler=handler,
        has_side_effects=side_effects,
        is_concurrency_safe=safe,
    )


def _execute(loop: AgentLoop, tools: list[ToolDefinition], names: list[str]):
    ctx = _RecordingContext()
    loop._current_tool_defs = {tool.name: tool for tool in tools}
    calls = [
        ToolCallInfo(id=f"call-{index}", name=name, args={})
        for index, name in enumerate(names, start=1)
    ]
    result = loop._execute_tool_batch(
        calls,
        ctx,
        session_id=ctx.session_id,
        iteration=1,
    )
    assert result is None
    return ctx


def test_safe_tools_overlap_and_persist_in_original_order(loop):
    lock = threading.Lock()
    active = 0
    max_active = 0

    def handler(name: str, delay: float):
        def run():
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(delay)
            with lock:
                active -= 1
            return name

        return run

    tools = [
        _definition("slow_first", handler("first", 0.12), safe=True),
        _definition("fast_second", handler("second", 0.02), safe=True),
    ]
    main_thread_id = threading.get_ident()

    ctx = _execute(loop, tools, ["slow_first", "fast_second"])

    assert max_active == 2
    assert [item["tool_call_id"] for item in ctx.results] == ["call-1", "call-2"]
    assert ctx.save_thread_ids == [main_thread_id, main_thread_id]


def test_output_governance_runs_concurrently(loop, monkeypatch):
    lock = threading.Lock()
    active = 0
    max_active = 0
    governance_thread_ids: set[int] = set()

    def governed(**kwargs):
        nonlocal active, max_active
        governance_thread_ids.add(threading.get_ident())
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.08)
        with lock:
            active -= 1
        return kwargs["content"]

    monkeypatch.setattr(
        "src.business.agents.agent_loop.govern_tool_result",
        governed,
    )
    tools = [
        _definition("read_a", lambda: "a", safe=True),
        _definition("read_b", lambda: "b", safe=True),
    ]
    main_thread_id = threading.get_ident()

    ctx = _execute(loop, tools, ["read_a", "read_b"])

    assert max_active == 2
    assert main_thread_id not in governance_thread_ids
    assert ctx.save_thread_ids == [main_thread_id, main_thread_id]


def test_mixed_batch_preserves_partition_boundaries(loop):
    first_done = threading.Event()
    second_done = threading.Event()
    unsafe_done = threading.Event()
    observations: list[tuple[str, bool, bool]] = []

    def first():
        time.sleep(0.05)
        first_done.set()
        return "first"

    def second():
        time.sleep(0.05)
        second_done.set()
        return "second"

    def unsafe():
        observations.append(("unsafe", first_done.is_set(), second_done.is_set()))
        unsafe_done.set()
        return "unsafe"

    def final_read():
        observations.append(("final", unsafe_done.is_set(), True))
        return "final"

    tools = [
        _definition("read_a", first, safe=True),
        _definition("read_b", second, safe=True),
        _definition("write", unsafe, safe=False, side_effects=True),
        _definition("read_c", final_read, safe=True),
    ]

    ctx = _execute(loop, tools, ["read_a", "read_b", "write", "read_c"])

    assert observations == [("unsafe", True, True), ("final", True, True)]
    assert [item["tool_call_id"] for item in ctx.results] == [
        "call-1",
        "call-2",
        "call-3",
        "call-4",
    ]


def test_safe_failure_is_isolated_from_siblings_and_later_serial_tool(loop):
    executed: list[str] = []

    def failed_read():
        executed.append("failed_read")
        return json.dumps({"error": "read_failed"})

    def successful_read():
        executed.append("successful_read")
        return "ok"

    def serial_tool():
        executed.append("serial_tool")
        return "ok"

    tools = [
        _definition("failed_read", failed_read, safe=True),
        _definition("successful_read", successful_read, safe=True),
        _definition("serial_tool", serial_tool, safe=False, side_effects=True),
    ]

    ctx = _execute(
        loop,
        tools,
        ["failed_read", "successful_read", "serial_tool"],
    )

    assert sorted(executed[:2]) == ["failed_read", "successful_read"]
    assert executed[-1] == "serial_tool"
    assert len(ctx.results) == 3


def test_serial_side_effect_failure_still_cascades_to_later_safe_tool(loop):
    executed: list[str] = []

    def failed_write():
        executed.append("failed_write")
        return json.dumps({"error": "write_failed"})

    def later_read():
        executed.append("later_read")
        return "must not run"

    tools = [
        _definition("failed_write", failed_write, safe=False, side_effects=True),
        _definition("later_read", later_read, safe=True),
    ]

    ctx = _execute(loop, tools, ["failed_write", "later_read"])

    assert executed == ["failed_write"]
    assert json.loads(ctx.results[1]["content"])["error"] == "not_executed"


def test_tool_concurrency_flags_are_conservative():
    default_tool = ToolDefinition(
        name="default",
        schema={"type": "object", "properties": {}},
        handler=lambda: "ok",
    )
    assert default_tool.is_concurrency_safe is False

    builtin_by_name = {tool.name: tool for tool in BUILTIN_GENERAL_TOOLS}
    expected_safe = {
        "web_search",
        "web_fetch",
        "read_file",
        "search_files",
        "search_content",
        "list_dir",
        "load_tool_output",
    }
    assert {
        name for name, tool in builtin_by_name.items() if tool.is_concurrency_safe
    } == expected_safe

    class Manager:
        def search_tools(self, _query):
            return "ok"

        def get_tool_detail(self, _tool_name):
            return "ok"

    discovery = {tool.name: tool for tool in create_assistant_search_tools(Manager())}
    assert discovery["search_tools"].is_concurrency_safe is True
    assert discovery["get_tool_detail"].is_concurrency_safe is False
    assert LOAD_SKILL_METHODOLOGY.is_concurrency_safe is False
