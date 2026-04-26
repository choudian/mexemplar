# Blueprint: AgentLoop 多工具调用结果配对修复

**Branch**: `003-fix-agentloop-tool-calls` | **Date**: 2026-04-25
**Mode**: doc-only
**Total Tasks**: 33 | **Files**: 2 new, 3 modified

## Key Decisions

- 声明式中断型工具分类 `ToolDefinition.is_interrupting`，执行前查表而非事后 `isinstance(ToolSignal)` → T001, T002, T003
- 标准化错误结构复用：所有 AgentLoop 发出的配对结果采用统一 JSON `{"error": "...", "message": "..."}` → T004
- 主循环从单 tool_call 改为 full tool_calls list 迭代，batch-level validation 在执行前拦截 → T005, T006, T007
- Handler contract validation：运行时校验 `is_interrupting` 与返回类型一致，不一致按失败处理 → T008, T021
- Recovery 从 `get_pending_tool_call` 单条改为 `get_pending_tool_calls` 列表 → T026, T027

## Implementation Order

```
Phase 1 (Setup):
  T001 → T002 [P]
  T003 → T004 [P]

Phase 2 (Foundational):
  T005 → T006 → T007 → T008

Phase 3 (US1 - MVP):
  T009 [P] T010 [P] T011 [P] T012 [P]  (tests first)
  T013 → T014

Phase 4 (US2):
  T015 [P] T016 [P] T017 [P] T018 [P] T019 [P]  (tests first)
  T020 → T021

Phase 5 (US3):
  T022 [P] T023 [P] T024 [P] T025 [P]  (tests first)
  T026 → T027 → T028

Phase 6 (Polish):
  T029 [P] T030 [P] T031 [P] T032 → T033
```

---

## Phase 1: Setup (Shared Infrastructure)

---

### T001: Add `is_interrupting: bool = False` field to `ToolDefinition` dataclass

**File**: `src/business/agents/config.py` (modify)

**Requirements**: FR-014

**Dependencies**: none

**Before** (~line 76):

```python
@dataclass
class ToolDefinition:
    """工具定义：FC schema + 实现函数的映射"""

    name: str
    schema: Dict[str, Any]
    handler: Callable[..., Union[str, ToolSignal]]
```

**After**:

```python
@dataclass
class ToolDefinition:
    """工具定义：FC schema + 实现函数的映射"""

    name: str
    schema: Dict[str, Any]
    handler: Callable[..., Union[str, ToolSignal]]
    is_interrupting: bool = False
```

**Verification**: `ToolDefinition(name="x", schema={}, handler=lambda: "")` works without passing `is_interrupting`. Existing callers are not broken.

---

### T002: Set `is_interrupting=True` on interrupting tool `ToolDefinition`s

**File**: `src/business/agents/tools/pm_output_tools.py`, `src/business/agents/tools/programmer_tools.py`, `src/business/agents/tools/trial_tools.py` (modify)

**Requirements**: FR-014

**Dependencies**: T001

**Before** in `src/business/agents/tools/pm_output_tools.py` (~line 101):

```python
submit_requirements = ToolDefinition(
    name="submit_requirements",
    schema=SUBMIT_REQUIREMENTS_SCHEMA,
    handler=make_signal_handler("[需求已提交]"),
)

report_code_issue = ToolDefinition(
    name="report_code_issue",
    schema=REPORT_CODE_ISSUE_SCHEMA,
    handler=make_signal_handler("[代码问题已报告]"),
)
```

**After**:

```python
submit_requirements = ToolDefinition(
    name="submit_requirements",
    schema=SUBMIT_REQUIREMENTS_SCHEMA,
    handler=make_signal_handler("[需求已提交]"),
    is_interrupting=True,
)

report_code_issue = ToolDefinition(
    name="report_code_issue",
    schema=REPORT_CODE_ISSUE_SCHEMA,
    handler=make_signal_handler("[代码问题已报告]"),
    is_interrupting=True,
)
```

**Before** in `src/business/agents/tools/programmer_tools.py` (~line 191):

```python
submit_code = ToolDefinition(
    name="submit_code",
    schema=SUBMIT_CODE_SCHEMA,
    handler=make_signal_handler("[代码已提交]"),
)
```

**After**:

```python
submit_code = ToolDefinition(
    name="submit_code",
    schema=SUBMIT_CODE_SCHEMA,
    handler=make_signal_handler("[代码已提交]"),
    is_interrupting=True,
)
```

**Before** in `src/business/agents/tools/trial_tools.py` (~line 129):

```python
        ToolDefinition(
            name="submit_trial_result",
            schema=SUBMIT_TRIAL_RESULT_SCHEMA,
            handler=make_signal_handler("[试用结果已提交]"),
        ),
```

**After**:

```python
        ToolDefinition(
            name="submit_trial_result",
            schema=SUBMIT_TRIAL_RESULT_SCHEMA,
            handler=make_signal_handler("[试用结果已提交]"),
            is_interrupting=True,
        ),
```

**Verification**: Grep for `ToolDefinition(` and verify all handlers that call `make_signal_handler` have `is_interrupting=True`. Verify `talk_to_user` in `agent_loop.py` is also marked interrupting (it uses `ToolSignal` via `_handle_tool_result`).

---

### T003: Add helper function `classify_tool_calls`

**File**: `src/business/agents/agent_loop.py` (modify)

**Requirements**: FR-014, data-model Entity 2

**Dependencies**: T001

**Before** (~line 18, after imports):

```python
from .config import AgentConfig, AgentResult, ResultType, RetryConfig, ToolDefinition, ToolSignal
from .builtin_tools import TALK_TO_USER_SCHEMA, LOAD_REFERENCE_SCHEMA, talk_to_user

logger = logging.getLogger(__name__)
```

**After**:

```python
from .config import AgentConfig, AgentResult, ResultType, RetryConfig, ToolDefinition, ToolSignal
from .builtin_tools import TALK_TO_USER_SCHEMA, LOAD_REFERENCE_SCHEMA, talk_to_user

logger = logging.getLogger(__name__)


def classify_tool_calls(
    tool_calls: List,
    tool_registry: Dict[str, ToolDefinition],
) -> List[tuple]:
    """
    Classify each tool call by looking up its name in the tool registry.

    Returns a list of (ToolCallInfo, kind) tuples where kind is one of
    'ordinary', 'interrupting', or 'unknown'.
    """
    result = []
    for tc in tool_calls:
        td = tool_registry.get(tc.name)
        if td is None:
            kind = "unknown"
        elif td.is_interrupting:
            kind = "interrupting"
        else:
            kind = "ordinary"
        result.append((tc, kind))
    return result
```

**Verification**: Unit-testable in isolation. Given a list of `ToolCallInfo` objects and a `tool_registry` dict, returns correct kind strings.

---

### T004: Add `make_error_result` helper and `ERROR_CODES` constant

**File**: `src/business/agents/agent_loop.py` (modify)

**Requirements**: FR-015, Entity 5

**Dependencies**: none (parallel with T003)

**Before** (right after `classify_tool_calls` added in T003):

```python
def classify_tool_calls(
    tool_calls: List,
    tool_registry: Dict[str, ToolDefinition],
) -> List[tuple]:
```

**After** (insert between `classify_tool_calls` and the `AgentLoop` class):

```python
ERROR_CODES = frozenset({
    "unknown_tool",
    "handler_exception",
    "handler_contract_violation",
    "not_executed",
    "invalid_model_output",
})


def make_error_result(error_code: str, message: str, **extra) -> str:
    """Return a JSON string conforming to the StandardizedErrorStructure."""
    obj = {"error": error_code, "message": message}
    obj.update(extra)
    return json.dumps(obj, ensure_ascii=False)
```

**Verification**: `make_error_result("not_executed", "skipped", upstream_tool_call_id="c1")` returns valid JSON parseable by `json.loads()`.

---

## Phase 2: Foundational (Blocking Prerequisites)

---

### T005: Refactor `_process_llm_response` to return full tool call list

**File**: `src/business/agents/agent_loop.py` (modify)

**Requirements**: FR-001

**Dependencies**: T001

**Before** (~line 258-308):

```python
    def _process_llm_response(
        self,
        response: LLMResponse,
        ctx: ContextManager,
    ) -> Union[AgentResult, ToolCallInfo]:
        """
        处理 LLM 响应

        保存 assistant 消息，处理文本响应（转为用户输入或完成），
        解析工具调用。调用方根据返回类型判断下一步：
        - AgentResult: 终止循环并返回该结果
        - ToolCallInfo: 进入工具执行阶段

        Args:
            response: LLM 响应对象
            ctx: 上下文管理器

        Returns:
            AgentResult 表示终止循环，ToolCallInfo 表示需要执行的工具
        """
        ctx.save_assistant_message(
            content=response.content or "",
            tool_calls=(
                json.dumps(
                    [{"id": tc.id, "name": tc.name, "args": tc.args} for tc in response.tool_calls]
                )
                if response.has_tool_calls
                else None
            ),
        )

        if not response.has_tool_calls:
            if self._config.text_as_user_input and response.content:
                ctx.update_session_status("suspended")
                logger.info(f"[Agent Loop] 文字回复转为用户输入等待: {ctx.session_id}")
                return AgentResult(
                    result_type=ResultType.NEEDS_USER_INPUT,
                    question=response.content,
                )
            ctx.update_session_status("completed")
            logger.info(f"[Agent Loop] 完成（无工具调用）: {ctx.session_id}")
            return AgentResult(
                result_type=ResultType.COMPLETED,
            )

        tool_call = response.tool_calls[0]
        logger.debug(
            f"[Agent Loop] 工具调用: {tool_call.name} "
            f"args={json.dumps(tool_call.args, ensure_ascii=False)}"
        )
        return tool_call
```

**After**:

```python
    def _process_llm_response(
        self,
        response: LLMResponse,
        ctx: ContextManager,
    ) -> Union[AgentResult, List]:
        """
        处理 LLM 响应

        保存 assistant 消息，处理文本响应（转为用户输入或完成），
        解析工具调用。调用方根据返回类型判断下一步：
        - AgentResult: 终止循环并返回该结果
        - list[ToolCallInfo]: 完整的工具调用列表（可能包含多个）

        Args:
            response: LLM 响应对象
            ctx: 上下文管理器

        Returns:
            AgentResult 表示终止循环，list[ToolCallInfo] 表示需要执行的工具调用列表
        """
        ctx.save_assistant_message(
            content=response.content or "",
            tool_calls=(
                json.dumps(
                    [{"id": tc.id, "name": tc.name, "args": tc.args} for tc in response.tool_calls]
                )
                if response.has_tool_calls
                else None
            ),
        )

        if not response.has_tool_calls:
            if self._config.text_as_user_input and response.content:
                ctx.update_session_status("suspended")
                logger.info(f"[Agent Loop] 文字回复转为用户输入等待: {ctx.session_id}")
                return AgentResult(
                    result_type=ResultType.NEEDS_USER_INPUT,
                    question=response.content,
                )
            ctx.update_session_status("completed")
            logger.info(f"[Agent Loop] 完成（无工具调用）: {ctx.session_id}")
            return AgentResult(
                result_type=ResultType.COMPLETED,
            )

        tool_call_list = list(response.tool_calls)
        logger.debug(
            f"[Agent Loop] 工具调用 ({len(tool_call_list)} 个): "
            + ", ".join(tc.name for tc in tool_call_list)
        )
        return tool_call_list
```

**Verification**: `_process_llm_response` with a response containing 2 tool calls returns `list` of length 2, not a single `ToolCallInfo`. Single-tool-call response returns `list` of length 1.

---

### T006: Refactor `run()` main loop to iterate over full tool call list

**File**: `src/business/agents/agent_loop.py` (modify)

**Requirements**: FR-002, FR-003, FR-004

**Dependencies**: T005

**Before** (~line 470-491):

```python
                llm_outcome = self._process_llm_response(response, ctx)
                if isinstance(llm_outcome, AgentResult):
                    return llm_outcome
                tool_call = llm_outcome

            # 执行工具（统一路径，不区分内置/注册）
            try:
                result = self._execute_tool_call(tool_call, tool_handlers)
                signal = self._handle_tool_result(result, tool_call, ctx)
                if signal is not None:
                    return signal

            except Exception as e:
                error_msg = f"工具执行错误: {str(e)}"
                ctx.save_tool_result(
                    tool_call_id=tool_call.id,
                    tool_name=tool_call.name,
                    content=error_msg,
                )
                logger.warning(f"[Agent Loop] {error_msg}")
                # 不终止循环，让 LLM 决定下一步
```

**After**:

```python
                llm_outcome = self._process_llm_response(response, ctx)
                if isinstance(llm_outcome, AgentResult):
                    return llm_outcome
                tool_call_list = llm_outcome

            # 多工具调用：执行列表中的所有工具调用
            signal = self._execute_tool_batch(
                tool_call_list, tool_handlers, ctx
            )
            if signal is not None:
                return signal
```

Also add the new `_execute_tool_batch` method to `AgentLoop` (after `_handle_tool_result`):

```python
    def _execute_tool_batch(
        self,
        tool_calls: List,
        tool_handlers: Dict[str, Callable],
        ctx: ContextManager,
    ) -> Optional[AgentResult]:
        """
        Execute a batch of tool calls with multi-tool semantics.

        - Classify all calls before execution
        - Reject mixed/interrupt batches as invalid output
        - Execute ordinary tools in order; cascade on failure
        - Handle solo interrupting tools with contract validation

        Returns AgentResult only if a solo interrupting tool succeeds;
        None otherwise (loop continues).
        """
        # Build tool definitions lookup for classification
        tool_defs_by_name: Dict[str, ToolDefinition] = {}
        for name, handler in tool_handlers.items():
            pass
        # tool_handlers only has handler callables, not ToolDefinitions.
        # We need the definitions from the current tool list.
        # Access via self._current_tool_defs (set in _rebuild_tools)
        tool_defs_by_name = getattr(self, "_current_tool_defs", {})

        classified = classify_tool_calls(tool_calls, tool_defs_by_name)
        batch_size = len(classified)
        interrupting_count = sum(1 for _, k in classified if k == "interrupting")

        # T007: Invalid-output batch check
        if batch_size > 1 and interrupting_count > 0:
            logger.info(
                f"[Agent Loop] 非法混合工具调用: {batch_size} 个调用中有 "
                f"{interrupting_count} 个中断型，拒绝执行"
            )
            for tc, _ in classified:
                ctx.save_tool_result(
                    tool_call_id=tc.id,
                    tool_name=tc.name,
                    content=make_error_result(
                        "invalid_model_output",
                        f"同轮响应包含中断型工具与其他工具调用，不执行任何工具。请重新输出合法工具调用。",
                        tool_name=tc.name,
                    ),
                )
            return None

        # Solo interrupting tool
        if batch_size == 1 and interrupting_count == 1:
            tc, _ = classified[0]
            return self._execute_solo_interrupt(tc, tool_handlers, ctx)

        # Ordinary batch (all ordinary or unknown)
        failed = False
        for i, (tc, kind) in enumerate(classified):
            if failed:
                ctx.save_tool_result(
                    tool_call_id=tc.id,
                    tool_name=tc.name,
                    content=make_error_result(
                        "not_executed",
                        f"前序工具失败，跳过执行。请基于已有结果重新规划。",
                        tool_name=tc.name,
                        upstream_tool_call_id=classified[i - 1][0].id if i > 0 else None,
                    ),
                )
                continue

            # Unknown tool
            if kind == "unknown":
                ctx.save_tool_result(
                    tool_call_id=tc.id,
                    tool_name=tc.name,
                    content=make_error_result(
                        "unknown_tool",
                        f"未知工具 '{tc.name}'，无法执行。",
                        tool_name=tc.name,
                    ),
                )
                failed = True
                continue

            # Execute ordinary tool
            try:
                result = self._execute_tool_call(tc, tool_handlers)
            except Exception as e:
                ctx.save_tool_result(
                    tool_call_id=tc.id,
                    tool_name=tc.name,
                    content=make_error_result(
                        "handler_exception",
                        f"工具 '{tc.name}' 执行异常: {e}",
                        tool_name=tc.name,
                    ),
                )
                logger.warning(f"[Agent Loop] 工具执行异常: {tc.name} -> {e}")
                failed = True
                continue

            # T008: Contract validation
            td = tool_defs_by_name.get(tc.name)
            if td and not td.is_interrupting and isinstance(result, ToolSignal):
                ctx.save_tool_result(
                    tool_call_id=tc.id,
                    tool_name=tc.name,
                    content=make_error_result(
                        "handler_contract_violation",
                        f"工具 '{tc.name}' 声明为普通工具但返回了 ToolSignal。",
                        tool_name=tc.name,
                    ),
                )
                failed = True
                continue

            # Standardized error structure check
            if self._is_standardized_error(result):
                ctx.save_tool_result(
                    tool_call_id=tc.id,
                    tool_name=tc.name,
                    content=result,
                )
                failed = True
                continue

            # Success
            ctx.save_tool_result(
                tool_call_id=tc.id,
                tool_name=tc.name,
                content=result,
            )
            logger.debug(f"[Agent Loop] 工具结果: {tc.name} -> {str(result)[:100]}")

        return None

    def _execute_solo_interrupt(
        self,
        tc,
        tool_handlers: Dict[str, Callable],
        ctx: ContextManager,
    ) -> Optional[AgentResult]:
        """Execute a solo interrupting tool with contract validation."""
        try:
            result = self._execute_tool_call(tc, tool_handlers)
        except Exception as e:
            ctx.save_tool_result(
                tool_call_id=tc.id,
                tool_name=tc.name,
                content=make_error_result(
                    "handler_exception",
                    f"中断型工具 '{tc.name}' 执行异常: {e}",
                    tool_name=tc.name,
                ),
            )
            logger.warning(f"[Agent Loop] 中断型工具异常: {tc.name} -> {e}")
            return None

        # Contract validation: is_interrupting=True must return ToolSignal
        if not isinstance(result, ToolSignal):
            ctx.save_tool_result(
                tool_call_id=tc.id,
                tool_name=tc.name,
                content=make_error_result(
                    "handler_contract_violation",
                    f"中断型工具 '{tc.name}' 返回了 str 而非 ToolSignal。",
                    tool_name=tc.name,
                ),
            )
            return None

        # Valid interrupt: use existing _handle_tool_result path
        return self._handle_tool_result(result, tc, ctx)

    @staticmethod
    def _is_standardized_error(result: str) -> bool:
        """Check if a tool result is a standardized error structure."""
        if not isinstance(result, str):
            return False
        try:
            obj = json.loads(result)
            if isinstance(obj, dict):
                return "error" in obj or obj.get("success") is False
        except (json.JSONDecodeError, ValueError):
            pass
        return False
```

Also modify `_rebuild_tools` in `run()` to populate `self._current_tool_defs`:

**Before** (~line 422-432):

```python
        def _rebuild_tools(tool_defs: List[ToolDefinition], ctx: ContextManager):
            nonlocal all_tool_schemas, tool_handlers
            builtin_schemas = [LOAD_REFERENCE_SCHEMA]
            tool_handlers = {td.name: td.handler for td in tool_defs}
            tool_handlers["load_reference"] = lambda reference_id: ctx.load_reference(reference_id)
            if not self._config.text_as_user_input:
                builtin_schemas.append(TALK_TO_USER_SCHEMA)
                tool_handlers["talk_to_user"] = talk_to_user
            all_tool_schemas = [td.schema for td in tool_defs] + builtin_schemas
```

**After**:

```python
        def _rebuild_tools(tool_defs: List[ToolDefinition], ctx: ContextManager):
            nonlocal all_tool_schemas, tool_handlers
            builtin_schemas = [LOAD_REFERENCE_SCHEMA]
            tool_handlers = {td.name: td.handler for td in tool_defs}
            # Store definitions for classification (T003)
            self._current_tool_defs = {td.name: td for td in tool_defs}
            tool_handlers["load_reference"] = lambda reference_id: ctx.load_reference(reference_id)
            if not self._config.text_as_user_input:
                builtin_schemas.append(TALK_TO_USER_SCHEMA)
                tool_handlers["talk_to_user"] = talk_to_user
                self._current_tool_defs["talk_to_user"] = ToolDefinition(
                    name="talk_to_user",
                    schema=TALK_TO_USER_SCHEMA,
                    handler=talk_to_user,
                    is_interrupting=True,
                )
            all_tool_schemas = [td.schema for td in tool_defs] + builtin_schemas
```

**Verification**: `run()` with a 2-tool-call response processes both calls before next LLM turn. Single-tool-call path unchanged.

---

### T007: Add batch-level validation (mixed interrupt rejection)

**File**: `src/business/agents/agent_loop.py` (modify)

**Requirements**: FR-006, FR-007

**Dependencies**: T005, T006

This is already implemented inside `_execute_tool_batch` from T006 above (the `if batch_size > 1 and interrupting_count > 0` block).

**Verification**: Mock response with `talk_to_user` + ordinary tool → zero handler invocations, two `invalid_model_output` results persisted.

---

### T008: Add handler contract validation

**File**: `src/business/agents/agent_loop.py` (modify)

**Requirements**: FR-016

**Dependencies**: T006

This is already implemented inside `_execute_tool_batch` and `_execute_solo_interrupt` from T006 above (the contract validation blocks).

**Verification**: Ordinary tool returning `ToolSignal` → `handler_contract_violation` error result + cascade. Solo interrupt returning `str` → `handler_contract_violation` + continue loop.

---

## Phase 3: User Story 1 — 多工具调用完整配对 (Priority: P1) 🎯 MVP

---

### T009: [US1] Integration test `test_ordinary_two_tool_success`

**File**: `tests/integration/test_agent_loop_multi_tool_calls.py` (new)

**Requirements**: SC-001

**Dependencies**: Phase 2 complete

```python
"""
AgentLoop 多工具调用集成测试

覆盖：
- 普通多工具成功配对
- 普通多工具失败级联
- 纯文本 "error" 不是失败
- 中断型混合拒绝
- 多中断型拒绝
- Solo 中断异常
- Handler 合同违约
- 恢复路径
"""

import json
import pytest
from unittest.mock import MagicMock

from src.business.agents.agent_loop import AgentLoop
from src.business.agents.config import (
    AgentConfig,
    AgentType,
    ToolDefinition,
    ToolSignal,
    ResultType,
)
from src.business.ai.llm_client import LLMResponse, ToolCallInfo
from tests.conftest import MockLLMClient


# -- Shared fixtures --


@pytest.fixture
def loop_config():
    return AgentConfig(
        agent_type=AgentType.PM,
        system_prompt="You are a test agent.",
        max_iterations=10,
    )


@pytest.fixture
def mock_config():
    config = MagicMock()
    config.get_memory_reference_steps_threshold.return_value = 999
    config.get_memory_reference_size_threshold.return_value = 999_999
    config.get_memory_compression_trigger_strategy.return_value = "token"
    config.get_memory_compression_token_threshold.return_value = 999_999
    config.get_memory_compression_count_threshold.return_value = None
    config.get_memory_compression_keep_recent.return_value = 5
    return config


def _tool_a(**kwargs):
    return json.dumps({"result": "a_success"})


def _tool_b(**kwargs):
    return json.dumps({"result": "b_success"})


def _make_tools():
    return [
        ToolDefinition(name="tool_a", schema={"type": "object", "properties": {}}, handler=_tool_a),
        ToolDefinition(name="tool_b", schema={"type": "object", "properties": {}}, handler=_tool_b),
    ]


def test_ordinary_two_tool_success(loop_config, mock_config, in_memory_db):
    """SC-001: Two ordinary tool calls → both executed in order, both results persisted."""
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
    # Verify both results persisted by checking context
    ctx = loop._get_context_manager("test-multi-2")
    messages = ctx._msg_repo.get_context("test-multi-2")
    tool_results = [m for m in messages if m.role == "tool"]
    assert len(tool_results) == 2
    assert tool_results[0].tool_call_id == "call_1"
    assert tool_results[1].tool_call_id == "call_2"
```

**Verification**: `uv run pytest tests/integration/test_agent_loop_multi_tool_calls.py::test_ordinary_two_tool_success -x`

---

### T010: [US1] Integration test `test_ordinary_three_tool_order`

**File**: `tests/integration/test_agent_loop_multi_tool_calls.py` (modify — append)

**Requirements**: SC-002

```python
def test_ordinary_three_tool_order(loop_config, mock_config, in_memory_db):
    """SC-002: Three ordinary tool calls execute in model-provided order."""
    execution_order = []

    def _tracking_handler(name):
        def handler(**kwargs):
            execution_order.append(name)
            return json.dumps({"result": f"{name}_ok"})
        return handler

    tools = [
        ToolDefinition(name="t1", schema={"type": "object", "properties": {}}, handler=_tracking_handler("t1")),
        ToolDefinition(name="t2", schema={"type": "object", "properties": {}}, handler=_tracking_handler("t2")),
        ToolDefinition(name="t3", schema={"type": "object", "properties": {}}, handler=_tracking_handler("t3")),
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
```

---

### T011: [US1] Integration test `test_ordinary_failure_cascade`

**File**: `tests/integration/test_agent_loop_multi_tool_calls.py` (modify — append)

**Requirements**: SC-003

```python
def test_ordinary_failure_cascade(loop_config, mock_config, in_memory_db):
    """SC-003: Second tool returns standardized error → third gets not_executed."""
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
    result = loop.run(session_id="test-cascade", user_input="test", tools=tools)
    assert call_count == {"t1": 1, "t2": 1, "t3": 0}
    ctx = loop._get_context_manager("test-cascade")
    messages = ctx._msg_repo.get_context("test-cascade")
    tool_results = [m for m in messages if m.role == "tool"]
    assert len(tool_results) == 3
    t3_result = json.loads(tool_results[2].content)
    assert t3_result["error"] == "not_executed"
```

---

### T012: [US1] Integration test `test_plain_text_error_not_failure`

**File**: `tests/integration/test_agent_loop_multi_tool_calls.py` (modify — append)

**Requirements**: SC-003a

```python
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
```

---

### T013: [US1] Implement ordinary-tool failure cascade

**File**: `src/business/agents/agent_loop.py` (modify)

**Requirements**: FR-005, Decision 3

**Dependencies**: T006

Already implemented in `_execute_tool_batch` from T006. The cascade logic is in the `if failed:` branch that writes `not_executed` results for remaining calls.

**Verification**: T011 test passes.

---

### T014: [US1] Add structured logging for multi-tool batch processing

**File**: `src/business/agents/agent_loop.py` (modify)

**Requirements**: FR-012

**Dependencies**: T006

Add logging to `_execute_tool_batch`. The batch-level `logger.info` for invalid-output and per-call `logger.debug` for results are already in T006. Add entry/exit logging:

**Before** (start of `_execute_tool_batch`):

```python
        classified = classify_tool_calls(tool_calls, tool_defs_by_name)
        batch_size = len(classified)
        interrupting_count = sum(1 for _, k in classified if k == "interrupting")
```

**After**:

```python
        classified = classify_tool_calls(tool_calls, tool_defs_by_name)
        batch_size = len(classified)
        interrupting_count = sum(1 for _, k in classified if k == "interrupting")

        logger.info(
            f"[Agent Loop] 工具批次: {batch_size} 个调用 "
            f"(中断型={interrupting_count}, 普通={batch_size - interrupting_count})"
        )
```

Also add at the end of the ordinary batch loop:

```python
        if failed:
            logger.info(f"[Agent Loop] 批次执行中断: 在第 {failed_at} 个调用处失败")
        else:
            logger.info(f"[Agent Loop] 批次执行完成: {batch_size} 个调用全部处理")
```

**Verification**: Run a test and check log output contains batch size, interrupting count, and failure position.

---

## Phase 4: User Story 2 — 中断型工具行为可预期 (Priority: P1)

---

### T015-T019: [US2] Integration tests

**File**: `tests/integration/test_agent_loop_multi_tool_calls.py` (modify — append)

These tests follow the same fixture pattern as T009-T012. Key test scenarios:

**T015** `test_mixed_interrupt_ordinary_batch`: interrupting + ordinary → zero handlers, `invalid_model_output` for all

**T016** `test_multi_interrupt_batch`: two interrupting tools → zero handlers, `invalid_model_output` for all

**T017** `test_solo_interrupt_handler_exception`: solo interrupt handler raises → `handler_exception` result, loop continues

**T018** `test_handler_contract_violation_interrupt_returns_str`: `is_interrupting=True` returns `str` → `handler_contract_violation`, loop continues

**T019** `test_handler_contract_violation_ordinary_returns_signal`: `is_interrupting=False` returns `ToolSignal` in multi-call → `handler_contract_violation` + cascade `not_executed` for later calls

Each test uses the same `loop_config` / `mock_config` / `in_memory_db` fixtures and `MockLLMClient` pattern.

---

### T020: [US2] Implement solo-interrupt exception handling

**File**: `src/business/agents/agent_loop.py` (modify)

**Requirements**: FR-007, Decision 10

**Dependencies**: T006

Already implemented in `_execute_solo_interrupt` from T006 (the `try/except` block that catches handler exceptions and writes `handler_exception` error result, then returns `None` to continue the loop).

**Verification**: T017 test passes.

---

### T021: [US2] Implement solo-interrupt contract validation

**File**: `src/business/agents/agent_loop.py` (modify)

**Requirements**: FR-016, Decision 9

**Dependencies**: T006

Already implemented in `_execute_solo_interrupt` from T006 (the `if not isinstance(result, ToolSignal)` block).

**Verification**: T018 test passes.

---

## Phase 5: User Story 3 — 会话恢复不重复或遗漏工具 (Priority: P2)

---

### T022-T025: [US3] Integration tests

**File**: `tests/integration/test_agent_loop_multi_tool_calls.py` (modify — append)

**T022** `test_recovery_partial_results`: seed session with 3-call assistant msg + 1 result → recovery runs only calls 2, 3

**T023** `test_recovery_all_complete`: all results present → no re-execution, normal LLM request

**T024** `test_recovery_missing_handler`: next missing call has no handler → `unknown_tool` error + `not_executed` for later

**T025** `test_recovery_corrupted_tool_call`: missing `name` field → explicit error logged

---

### T026: [US3] Extend `get_pending_tool_call` → `get_pending_tool_calls`

**File**: `src/business/memory/context_manager.py` (modify)

**Requirements**: FR-008, FR-009

**Dependencies**: Phase 2

**Before** (~line 153-179):

```python
    def get_pending_tool_call(self) -> Optional[dict]:
        """
        检测 session 是否有待重试的工具调用。

        当 execute_tool 失败且 save_result=False 时，最后一条消息是 assistant 的
        tool_calls（无对应 tool result）。重启后 AgentLoop 可直接重执行，无需再问 LLM。

        Returns:
            {"id": ..., "name": ..., "args": {...}} 或 None
        """
        last = self._msg_repo.get_last(self.session_id)
        if last and last.role == "assistant" and last.tool_calls:
            try:
                tcs = json.loads(last.tool_calls)
                if tcs:
                    if len(tcs) > 1:
                        logger.warning(
                            f"[上下文] session {self.session_id} 有多个待重试 tool call，只取第一个"
                        )
                    tc = tcs[0]
                    if "name" not in tc:
                        logger.warning(f"[上下文] 待重试 tool call 缺少 name 字段: {tc}")
                        return None
                    return tc
            except Exception:
                logger.debug(f"[上下文] 解析 tool_calls 失败: {last.tool_calls!r}")
        return None
```

**After**:

```python
    def get_pending_tool_call(self) -> Optional[dict]:
        """
        检测 session 是否有待重试的工具调用（兼容旧路径，返回第一个）。

        Returns:
            {"id": ..., "name": ..., "args": {...}} 或 None
        """
        pending = self.get_pending_tool_calls()
        return pending[0] if pending else None

    def get_pending_tool_calls(self) -> List[dict]:
        """
        检测 session 中所有未配对的工具调用。

        遍历活跃消息中的 assistant tool_calls，与已有的 tool result 按
        tool_call_id 匹配，返回缺失结果的调用列表（保持原始顺序）。

        Returns:
            [{"id": ..., "name": ..., "args": {...}}, ...] 或 []
        """
        messages = self._msg_repo.get_context(self.session_id)
        tool_result_ids = set()
        pending_assistant_msgs = []

        for msg in messages:
            if msg.role == "tool" and msg.tool_call_id:
                tool_result_ids.add(msg.tool_call_id)
            if msg.role == "assistant" and msg.tool_calls:
                pending_assistant_msgs.append(msg)

        pending_calls = []
        for msg in pending_assistant_msgs:
            try:
                tcs = json.loads(msg.tool_calls)
            except Exception:
                logger.debug(f"[上下文] 解析 tool_calls 失败: {msg.tool_calls!r}")
                continue
            for tc in tcs:
                if "name" not in tc:
                    logger.warning(f"[上下文] tool call 缺少 name 字段: {tc}")
                    continue
                if tc.get("id", "") not in tool_result_ids:
                    pending_calls.append(tc)

        return pending_calls
```

**Verification**: Seed DB with assistant message containing 3 tool calls and 1 tool result → `get_pending_tool_calls()` returns 2 entries in order.

---

### T027: [US3] Update pending-tool-call branch in `run()` to iterate over full pending list

**File**: `src/business/agents/agent_loop.py` (modify)

**Requirements**: FR-008, FR-009, FR-010

**Dependencies**: T026

**Before** (~line 442-459 in the original, now in the modified version):

```python
        # 检查是否有待重试的工具调用
        _pending_tc = ctx.get_pending_tool_call()
```

and in the loop body:

```python
            if _pending_tc is not None:
                # 待重试：直接使用上次的工具调用，跳过 LLM
                tool_call: ToolCallInfo = self._resolve_pending_tool_call(_pending_tc)
                _pending_tc = None
            else:
```

**After**:

```python
        # 检查是否有待重试的工具调用（多工具恢复）
        _pending_tcs = ctx.get_pending_tool_calls()
```

and in the loop body:

```python
            if _pending_tcs:
                # 恢复：逐个处理待重试的工具调用
                tc_dict = _pending_tcs.pop(0)
                tool_call_list = [self._resolve_pending_tool_call(tc_dict)]
                # Don't call LLM — process pending calls directly
                signal = self._execute_tool_batch(tool_call_list, tool_handlers, ctx)
                if signal is not None:
                    return signal
                continue
            else:
```

**Verification**: T022 test passes.

---

### T028: [US3] Add recovery logging

**File**: `src/business/agents/agent_loop.py` (modify)

**Requirements**: FR-012

**Dependencies**: T027

Add after `_pending_tcs = ctx.get_pending_tool_calls()`:

```python
        if _pending_tcs:
            logger.info(
                f"[Agent Loop] 恢复待执行工具: {len(_pending_tcs)} 个未配对调用 "
                f"({', '.join(tc.get('name', '?') for tc in _pending_tcs)})"
            )
```

**Verification**: Run recovery test, check log output.

---

## Phase 6: Polish & Cross-Cutting Concerns

---

### T029: [P] Regression test + existing test suite baseline

**File**: `tests/integration/test_agent_loop_multi_tool_calls.py` (modify — append)

**Requirements**: SC-007, FR-011

```python
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
```

Also run existing suites: `uv run pytest tests/integration/test_v2_full_flow.py tests/integration/test_assistant_new_session.py`

---

### T030: [P] Update `docs/design/agent_loop_design.md`

**File**: `docs/design/agent_loop_design.md` (modify)

**Requirements**: Principle V

Update the AgentLoop design doc to document: multi-tool batch processing model, batch classification rules (`classify_tool_calls`), failure cascade semantics, interrupt handling (solo vs mixed), and recovery behavior (`get_pending_tool_calls`).

---

### T031: [P] Update `docs/ARCHITECTURE.md`

**File**: `docs/ARCHITECTURE.md` (modify)

**Requirements**: Principle V

Update the AgentLoop section to reflect the multi-tool batch processing change. Add note about `ToolDefinition.is_interrupting` field and the new `_execute_tool_batch` method.

---

### T032: Run full quickstart.md validation

Run all 11 test scenarios from `specs/003-fix-agentloop-tool-calls/quickstart.md`:

```bash
uv run pytest tests/integration/test_agent_loop_multi_tool_calls.py -v
uv run pytest tests/integration/test_v2_full_flow.py tests/integration/test_assistant_new_session.py -v
```

---

### T033: Run formatter and linter

```bash
uv run black src/ tests/
uv run flake8 src/ tests/
```

---

## Checklist

- [ ] T001: Add `is_interrupting: bool = False` to `ToolDefinition` in `src/business/agents/config.py`
- [ ] T002: Set `is_interrupting=True` on interrupting tool registrations
- [ ] T003: Add `classify_tool_calls` helper in `src/business/agents/agent_loop.py`
- [ ] T004: Add `make_error_result` and `ERROR_CODES` in `src/business/agents/agent_loop.py`
- [ ] T005: Refactor `_process_llm_response` to return full tool call list
- [ ] T006: Refactor `run()` main loop + add `_execute_tool_batch` and `_execute_solo_interrupt`
- [ ] T007: Batch-level mixed/interrupt validation (in T006)
- [ ] T008: Handler contract validation (in T006)
- [ ] T009: [US1] Test `test_ordinary_two_tool_success`
- [ ] T010: [US1] Test `test_ordinary_three_tool_order`
- [ ] T011: [US1] Test `test_ordinary_failure_cascade`
- [ ] T012: [US1] Test `test_plain_text_error_not_failure`
- [ ] T013: [US1] Failure cascade implementation (in T006)
- [ ] T014: [US1] Structured batch logging
- [ ] T015: [US2] Test `test_mixed_interrupt_ordinary_batch`
- [ ] T016: [US2] Test `test_multi_interrupt_batch`
- [ ] T017: [US2] Test `test_solo_interrupt_handler_exception`
- [ ] T018: [US2] Test `test_handler_contract_violation_interrupt_returns_str`
- [ ] T019: [US2] Test `test_handler_contract_violation_ordinary_returns_signal`
- [ ] T020: [US2] Solo interrupt exception handling (in T006)
- [ ] T021: [US2] Solo interrupt contract validation (in T006)
- [ ] T022: [US3] Test `test_recovery_partial_results`
- [ ] T023: [US3] Test `test_recovery_all_complete`
- [ ] T024: [US3] Test `test_recovery_missing_handler`
- [ ] T025: [US3] Test `test_recovery_corrupted_tool_call`
- [ ] T026: [US3] Extend `get_pending_tool_call` → `get_pending_tool_calls`
- [ ] T027: [US3] Update `run()` recovery branch for multi-tool
- [ ] T028: [US3] Recovery logging
- [ ] T029: [P] Regression test + existing test suite
- [ ] T030: [P] Update `docs/design/agent_loop_design.md`
- [ ] T031: [P] Update `docs/ARCHITECTURE.md`
- [ ] T032: Run quickstart.md validation
- [ ] T033: Run formatter and linter
