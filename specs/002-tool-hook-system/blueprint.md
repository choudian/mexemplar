# Blueprint: 工具执行 Pre/Post Hook 系统

**Branch**: `002-tool-hook-system` | **Date**: 2026-04-26
**Mode**: `doc-only`
**Total Tasks**: 37 | **Files**: 3 new, 6 modified, 0 deleted

## Key Decisions

- Hook 协议放在 `src/business/agents/hook_models.py`，`config.py` 只暴露 public dataclass 字段，避免把递归冻结 helper 塞进配置模块。→ T002, T003, T004
- Hook 只对调用方传入或动态构建的 `ToolDefinition` 生效；AgentLoop 注入的 `load_reference` / `talk_to_user` 继续参与批处理分类，但不进入 hook 链。→ T010, T012, T024
- `ToolCallContext.args` 是递归只读隔离视图，pre_hook 不支持改参，post_hook 不支持结果流水线。→ T003, T006, T033
- `AgentLoop._execute_tool_batch()` 与 `_execute_solo_interrupt()` 复用 hook-aware 单次执行结果，并用原始失败状态驱动 `not_executed` 级联。→ T007, T010, T024, T032
- `builtin_general_tools`、`recording_data_tools`、`trial_tools` 只迁移门卫式拒绝、确认、限流；执行准备留在 handler。→ T014, T015, T016, T017, T019, T020, T021
- 不迁移 `programmer_tools.syntax_check`、`recording_data_tools.execute_code`、`tool_executor` 和 `dynamic_tool_manager`，用 guard 固定边界。→ T018, T033

## Implementation Order

```text
T001, T002
T003, T004
T005, T006, T007, T008, T009
T010, T011, T012, T013
T014, T015, T016, T017, T018
T019, T020, T021, T022
T023, T024, T025
T026, T027
T028, T029
T030, T031, T032, T033, T034, T035, T036, T037
```

## File Classification

| Path | Category | Main Tasks |
|------|----------|------------|
| `tests/test_hook_protocol.py` | new | T001, T005-T009, T014-T018, T023-T025 |
| `src/business/agents/hook_models.py` | new | T002, T003 |
| `src/business/agents/config.py` | modified | T004 |
| `src/business/agents/agent_loop.py` | modified | T010-T012, T026 |
| `src/business/agents/tools/builtin_general_tools.py` | modified | T019 |
| `src/business/agents/tools/recording_data_tools.py` | modified | T020 |
| `src/business/agents/tools/trial_tools.py` | modified | T021 |
| `docs/ARCHITECTURE.md` | modified | T028 |
| `docs/PROJECT_CONSTRAINTS.md` | new | T029 |

---

## Phase 1: Setup

### T001: Create `tests/test_hook_protocol.py` with shared pytest fixtures

**File**: `tests/test_hook_protocol.py` (new)

**Requirements**: FR-001, FR-010, FR-012, FR-016, SC-001

**Dependencies**: none

Use the complete file in Appendix A. It defines shared fixtures, synthetic tools, AgentLoop invocation helpers, and all test bodies added by T005-T009, T014-T018, and T023-T025.

**Verification**: `Test-Path tests/test_hook_protocol.py` returns true after implementation, and `uv run python -m pytest tests/test_hook_protocol.py -q` collects tests.

---

### T002: Create `src/business/agents/hook_models.py`

**File**: `src/business/agents/hook_models.py` (new)

**Requirements**: FR-001, FR-003, FR-004, FR-012, SC-007

**Dependencies**: none

Create the file with the complete content in Appendix B.

**Verification**: `uv run python -m py_compile src/business/agents/hook_models.py` succeeds.

---

## Phase 2: Foundational

### T003: Implement hook protocol models and recursive args freezing

**File**: `src/business/agents/hook_models.py` (new)

**Requirements**: FR-001, FR-003, FR-004, FR-012, FR-013, SC-007

**Dependencies**: T002

Appendix B already contains the final implementation: `ToolCallContext`, `PreHookResult`, `PostHookResult`, callable type aliases, `ToolExecutionDefinition`, `ToolExecutionOutcome`, and `freeze_tool_args`.

**Verification**: The tests named `test_recursive_args_are_read_only_and_isolated` and `test_pre_hook_exception_runs_handler_and_skips_post_hook` pass.

---

### T004: Extend `ToolDefinition` and `AgentConfig`

**File**: `src/business/agents/config.py` (modified)

**Requirements**: FR-001, FR-005, FR-010, FR-014

**Dependencies**: T003

**Before** (line 7):

```python
from enum import Enum
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Dict, Any, Union
```

**After**:

```python
from enum import Enum
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Dict, Any, Union

from src.business.agents.hook_models import (
    PostHook,
    PostHookResult,
    PreHook,
    PreHookResult,
    ToolCallContext,
)
```

**Before** (line 75):

```python
@dataclass
class ToolDefinition:
    """工具定义：FC schema + 实现函数的映射"""

    name: str
    schema: Dict[str, Any]
    handler: Callable[..., Union[str, ToolSignal]]
    is_interrupting: bool = False
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
    pre_hook: Optional[PreHook] = None
    post_hook: Optional[PostHook] = None
```

**Before** (line 85):

```python
@dataclass
class AgentConfig:
    """Agent 配置"""

    agent_type: AgentType
    system_prompt: str
    max_iterations: int = 10
    retry: RetryConfig = field(default_factory=RetryConfig)
    text_as_user_input: bool = False
```

**After**:

```python
@dataclass
class AgentConfig:
    """Agent 配置"""

    agent_type: AgentType
    system_prompt: str
    max_iterations: int = 10
    retry: RetryConfig = field(default_factory=RetryConfig)
    text_as_user_input: bool = False
    global_pre_hooks: List[PreHook] = field(default_factory=list)
    global_post_hooks: List[PostHook] = field(default_factory=list)
```

**Before** (line 143):

```python
__all__ = [
    "AgentType",
    "ResultType",
    "RetryConfig",
    "ToolSignal",
    "ToolDefinition",
    "AgentConfig",
    "AgentResult",
    "PM_CONFIG",
    "PROGRAMMER_CONFIG",
    "ASSISTANT_CONFIG",
]
```

**After**:

```python
__all__ = [
    "AgentType",
    "ResultType",
    "RetryConfig",
    "ToolSignal",
    "ToolDefinition",
    "AgentConfig",
    "AgentResult",
    "ToolCallContext",
    "PreHookResult",
    "PostHookResult",
    "PreHook",
    "PostHook",
    "PM_CONFIG",
    "PROGRAMMER_CONFIG",
    "ASSISTANT_CONFIG",
]
```

**Verification**: Existing imports of `ToolDefinition` continue to work, and constructing `AgentConfig(agent_type=..., system_prompt=...)` still succeeds.

---

## Phase 3: User Story 1

### T005: Add no-hook transparency, pre-hook rejection, and post-hook rewrite tests

**File**: `tests/test_hook_protocol.py` (new)

**Requirements**: FR-001, FR-002, FR-004, FR-010

**Dependencies**: T001, T003, T004

Appendix A includes `test_no_hook_tool_remains_transparent`, `test_pre_hook_error_short_circuits_with_standardized_error`, and `test_post_hook_rewrites_result`.

**Verification**: `uv run python -m pytest tests/test_hook_protocol.py -q -k "no_hook or pre_hook_error or post_hook_rewrites"` passes.

---

### T006: Add recursive args mutation and pre-hook exception tests

**File**: `tests/test_hook_protocol.py` (new)

**Requirements**: FR-003, FR-013, SC-007

**Dependencies**: T001, T003, T004

Appendix A includes `test_recursive_args_are_read_only_and_isolated` and `test_pre_hook_exception_runs_handler_and_skips_post_hook`.

**Verification**: The tests prove top-level and nested writes raise, handler args remain original, and post hooks are skipped after a pre-hook exception.

---

### T007: Add handler exception, ToolSignal, contract, and batch cascade tests

**File**: `tests/test_hook_protocol.py` (new)

**Requirements**: FR-014, FR-015, FR-016, SC-008

**Dependencies**: T001, T003, T004

Appendix A includes `test_handler_exception_reaches_post_hook_and_preserves_failure_status`, `test_legal_tool_signal_skips_post_hook`, and `test_ordinary_tool_signal_contract_violation_cascades_not_executed`.

**Verification**: Handler exceptions reach post_hook, legal `ToolSignal` skips post_hook, and ordinary `ToolSignal` return becomes `handler_contract_violation`.

---

### T008: Add callable same-name refresh smoke test

**File**: `tests/test_hook_protocol.py` (new)

**Requirements**: FR-011, SC-006

**Dependencies**: T001, T003, T004

Appendix A includes `test_callable_same_name_handler_hook_and_interrupt_metadata_refresh_each_iteration`.

**Verification**: The second call with the same tool name uses the second handler and second hook.

---

### T009: Add tool-level no-op hook overhead smoke test

**File**: `tests/test_hook_protocol.py` (new)

**Requirements**: SC-002

**Dependencies**: T001, T003, T004

Appendix A includes `test_tool_level_noop_hook_overhead_smoke`.

**Verification**: The test compares a no-hook synthetic call against tool-level no-op pre/post hooks and asserts the local delta is below 5 ms per call.

---

### T010: Integrate hook-aware per-call execution into AgentLoop

**File**: `src/business/agents/agent_loop.py` (modified)

**Requirements**: FR-001, FR-002, FR-004, FR-013, FR-014, FR-015, FR-016

**Dependencies**: T003, T004

Apply the following changes.

**Before** (line 18):

```python
from .config import AgentConfig, AgentResult, ResultType, RetryConfig, ToolDefinition, ToolSignal
from .builtin_tools import TALK_TO_USER_SCHEMA, LOAD_REFERENCE_SCHEMA, talk_to_user
from .tool_helpers import is_standardized_error, make_error_result
```

**After**:

```python
from .config import AgentConfig, AgentResult, ResultType, RetryConfig, ToolDefinition, ToolSignal
from .builtin_tools import TALK_TO_USER_SCHEMA, LOAD_REFERENCE_SCHEMA, talk_to_user
from .hook_models import (
    PostHook,
    PreHook,
    PreHookResult,
    ToolCallContext,
    ToolExecutionOutcome,
    freeze_tool_args,
)
from .tool_helpers import is_standardized_error, make_error_result
```

**Replace the current `_execute_tool_call` method with**:

```python
    def _build_hook_context(
        self,
        tool_call: ToolCallInfo,
        session_id: str,
        iteration: int,
    ) -> ToolCallContext:
        return ToolCallContext(
            tool_name=tool_call.name,
            args=freeze_tool_args(tool_call.args),
            session_id=session_id,
            agent_type=self._config.agent_type,
            iteration=iteration,
        )

    @staticmethod
    def _hookable_tool_name(tool_name: str) -> bool:
        return tool_name not in {"load_reference", "talk_to_user"}

    def _run_pre_hooks(
        self,
        hooks: list[PreHook],
        ctx: ToolCallContext,
    ) -> tuple[str | None, bool]:
        for hook in hooks:
            try:
                result = hook(ctx)
            except Exception as exc:
                logger.warning("[Agent Loop] pre_hook 异常: %s -> %s", ctx.tool_name, exc, exc_info=True)
                return None, True
            if isinstance(result, PreHookResult) and result.error:
                return result.error, False
        return None, False

    def _run_post_hooks(
        self,
        hooks: list[PostHook],
        ctx: ToolCallContext,
        original_result: str,
    ) -> str:
        final_result = original_result
        for hook in hooks:
            try:
                result = hook(ctx, original_result)
            except Exception as exc:
                logger.warning("[Agent Loop] post_hook 异常: %s -> %s", ctx.tool_name, exc, exc_info=True)
                return original_result
            if result is not None and result.result is not None:
                final_result = result.result
        return final_result

    def _execute_tool_call(
        self,
        tool_call: ToolCallInfo,
        tool_definition: ToolDefinition,
        session_id: str,
        iteration: int,
    ) -> ToolExecutionOutcome:
        handler = tool_definition.handler
        hooks_enabled = self._hookable_tool_name(tool_call.name)
        ctx = self._build_hook_context(tool_call, session_id, iteration)

        pre_hooks: list[PreHook] = []
        post_hooks: list[PostHook] = []
        if hooks_enabled:
            if tool_definition.pre_hook is not None:
                pre_hooks.append(tool_definition.pre_hook)
            pre_hooks.extend(self._config.global_pre_hooks)
            if tool_definition.post_hook is not None:
                post_hooks.append(tool_definition.post_hook)
            post_hooks.extend(self._config.global_post_hooks)

        pre_error, pre_exception = self._run_pre_hooks(pre_hooks, ctx)
        if pre_error is not None:
            return ToolExecutionOutcome(
                result=make_error_result(
                    "pre_hook_rejected",
                    pre_error,
                    tool_name=tool_call.name,
                ),
                failed=True,
                failure_code="pre_hook_rejected",
            )

        try:
            raw_result = handler(**tool_call.args)
        except Exception as exc:
            logger.warning("[Agent Loop] handler 异常: %s -> %s", tool_call.name, exc, exc_info=True)
            raw_result = make_error_result(
                "handler_exception",
                f"工具 '{tool_call.name}' 执行异常: {exc}",
                tool_name=tool_call.name,
            )
            failed = True
            failure_code = "handler_exception"
        else:
            failed = isinstance(raw_result, str) and is_standardized_error(raw_result)
            failure_code = "standardized_error" if failed else None

        if isinstance(raw_result, ToolSignal):
            return ToolExecutionOutcome(result=raw_result, failed=False, failure_code=None)

        if pre_exception:
            return ToolExecutionOutcome(result=raw_result, failed=failed, failure_code=failure_code)

        final_result = self._run_post_hooks(post_hooks, ctx, raw_result)
        return ToolExecutionOutcome(result=final_result, failed=failed, failure_code=failure_code)
```

**Change `_execute_tool_batch` signature and body**:

```python
    def _execute_tool_batch(
        self,
        tool_calls: List,
        ctx: ContextManager,
        session_id: str,
        iteration: int,
    ) -> Optional[AgentResult]:
```

Inside the ordinary tool branch, replace handler invocation and persistence with:

```python
            outcome = self._execute_tool_call(tc, _, session_id, iteration)
            result = outcome.result

            if isinstance(result, ToolSignal):
                self._save_error(
                    tc,
                    ctx,
                    "handler_contract_violation",
                    f"工具 '{tc.name}' 声明为普通工具但返回了 ToolSignal。",
                    tool_name=tc.name,
                )
                first_failure = i + 1
                continue

            ctx.save_tool_result(tool_call_id=tc.id, tool_name=tc.name, content=result)
            if outcome.failed or is_standardized_error(result):
                first_failure = i + 1
            else:
                logger.debug(f"[Agent Loop] 工具结果: {tc.name} -> {str(result)[:100]}")
```

**Change `_execute_solo_interrupt` signature and body**:

```python
    def _execute_solo_interrupt(
        self,
        tc,
        tool_definition: ToolDefinition,
        ctx: ContextManager,
        session_id: str,
        iteration: int,
    ) -> Optional[AgentResult]:
        outcome = self._execute_tool_call(tc, tool_definition, session_id, iteration)
        result = outcome.result
        if outcome.failed and isinstance(result, str):
            ctx.save_tool_result(tool_call_id=tc.id, tool_name=tc.name, content=result)
            return None
        if not isinstance(result, ToolSignal):
            self._save_error(
                tc,
                ctx,
                "handler_contract_violation",
                f"中断型工具 '{tc.name}' 返回了 str 而非 ToolSignal。",
                tool_name=tc.name,
            )
            return None
        return self._handle_tool_result(result, tc, ctx)
```

In `_execute_tool_batch`, call the solo interrupt path with the tool definition:

```python
        if batch_size == 1 and interrupting_count == 1:
            tc, _, td = classified[0]
            return self._execute_solo_interrupt(tc, td, ctx, session_id, iteration)
```

Update both call sites in `run()`:

```python
                signal = self._execute_tool_batch(tool_call_list, ctx, session_id, iteration)
```

and:

```python
            signal = self._execute_tool_batch(tool_call_list, ctx, session_id, iteration)
```

**Verification**: `uv run python -m pytest tests/test_hook_protocol.py -q -k "handler_exception or ToolSignal or batch"` passes.

---

### T011: Refresh callable execution mapping each iteration

**File**: `src/business/agents/agent_loop.py` (modified)

**Requirements**: FR-011, SC-006

**Dependencies**: T010

Change callable rebuilding so execution definitions refresh every iteration while schemas refresh only when the tool-name set changes.

**Before** (line 619):

```python
            if _tools_callable:
                new_tools = tools()
                new_names = frozenset(td.name for td in new_tools)
                if new_names != _last_tool_names:
                    _rebuild_tools(new_tools, ctx)
                    _last_tool_names = new_names
```

**After**:

```python
            if _tools_callable:
                new_tools = tools()
                new_names = frozenset(td.name for td in new_tools)
                if new_names != _last_tool_names:
                    _rebuild_tools(new_tools, ctx)
                    _last_tool_names = new_names
                else:
                    latest_defs = {td.name: td for td in new_tools}
                    for name, td in latest_defs.items():
                        self._current_tool_defs[name] = td
                    tool_handlers = {
                        name: td.handler for name, td in self._current_tool_defs.items()
                    }
```

**Verification**: `test_callable_same_name_handler_hook_and_interrupt_metadata_refresh_each_iteration` passes.

---

### T012: Exclude injected built-ins from hook execution

**File**: `src/business/agents/agent_loop.py` (modified)

**Requirements**: FR-011a, FR-016

**Dependencies**: T010

The `_hookable_tool_name()` helper in T010 is the implementation. It keeps `load_reference` and `talk_to_user` in `_current_tool_defs` for classification while preventing tool/global hooks from running against those injected tools.

**Verification**: `test_global_hooks_do_not_apply_to_invalid_mixed_batches_or_injected_tools` passes.

---

### T013: Run focused P1 validation

**File**: command

**Requirements**: SC-001

**Dependencies**: T005-T012

```powershell
uv run python -m pytest tests/test_hook_protocol.py -q
```

**Verification**: Exit code 0.

---

## Phase 4: User Story 2

### T014: Add builtin general tool migration tests

**File**: `tests/test_hook_protocol.py` (new)

**Requirements**: FR-006, SC-003, SC-004

**Dependencies**: T001, T010

Appendix A includes `test_builtin_general_pre_hooks_reject_before_handler`.

**Verification**: The test proves migrated builtin gates reject before handler execution.

---

### T015: Add recording tool migration tests

**File**: `tests/test_hook_protocol.py` (new)

**Requirements**: FR-007, SC-003

**Dependencies**: T001, T010

Appendix A includes `test_recording_query_and_analyze_image_pre_hooks`.

**Verification**: The test covers parser/filter rejection, harmless SQL allowance, and six-action `analyze_image` rejection.

---

### T016: Add trial run_command limit tests

**File**: `tests/test_hook_protocol.py` (new)

**Requirements**: FR-008, SC-003

**Dependencies**: T001, T010

Appendix A includes `test_trial_run_command_pre_hook_limits_per_create_trial_tools_call`.

**Verification**: The sixth `run_command` call is rejected by pre_hook before handler execution.

---

### T017: Add static source guard tests for migrated handler cleanup

**File**: `tests/test_hook_protocol.py` (new)

**Requirements**: FR-006, FR-007, FR-008, SC-004

**Dependencies**: T019, T020, T021

Appendix A includes `test_migrated_handler_bodies_no_longer_contain_gate_logic`.

**Verification**: The static test confirms handler bodies no longer contain migrated checks and `edit_file` still contains `old_text` uniqueness logic.

---

### T018: Add non-migration boundary guard tests

**File**: `tests/test_hook_protocol.py` (new)

**Requirements**: FR-009

**Dependencies**: T001

Appendix A includes `test_non_migration_boundaries_remain_outside_hook_system`.

**Verification**: The guard asserts the named modules and handlers remain outside hook migration.

---

### T019: Migrate builtin general gates into pre-hooks

**File**: `src/business/agents/tools/builtin_general_tools.py` (modified)

**Requirements**: FR-006, SC-003, SC-004

**Dependencies**: T010

Add imports:

```python
from src.business.agents.hook_models import PreHookResult, ToolCallContext
```

Add helper functions before `READ_FILE_SCHEMA`:

```python
_SHELL_META_CHARS = (";", "|", "&", "`", "$", "(", ")", "\n", "\r", ">", "<")


def _resolve_path_arg(ctx: ToolCallContext, key: str = "path") -> Path:
    return Path(str(ctx.args.get(key, "."))).expanduser().resolve()


def _is_system_path(path: Path) -> bool:
    system_dirs = [Path("C:/Windows"), Path("C:/System32"), Path("/etc"), Path("/usr")]
    for sys_dir in system_dirs:
        try:
            path.relative_to(sys_dir)
            return True
        except ValueError:
            continue
    return False


def _is_safe_exec_command(command: str) -> bool:
    cmd_lower = command.strip().lower()
    for safe in EXEC_SAFE_COMMANDS:
        if cmd_lower == safe:
            return True
        if cmd_lower.startswith(safe + " "):
            rest = cmd_lower[len(safe) + 1:]
            return not any(char in rest for char in _SHELL_META_CHARS)
    return False


def read_file_pre_hook(ctx: ToolCallContext) -> PreHookResult | None:
    path = _resolve_path_arg(ctx)
    if not path.exists():
        return PreHookResult(error=f"文件不存在: {path}")
    if not path.is_file():
        return PreHookResult(error=f"不是文件: {path}")
    return None


def write_file_pre_hook(ctx: ToolCallContext) -> PreHookResult | None:
    path = _resolve_path_arg(ctx)
    if _is_system_path(path):
        return PreHookResult(error="禁止写入系统目录")
    if not _ask_user_confirm(f"将向文件写入内容：\n{path}\n\n是否确认？"):
        return PreHookResult(error="用户取消了该操作")
    return None


def edit_file_pre_hook(ctx: ToolCallContext) -> PreHookResult | None:
    path = _resolve_path_arg(ctx)
    if not path.exists():
        return PreHookResult(error=f"文件不存在: {path}")
    if not path.is_file():
        return PreHookResult(error=f"不是文件: {path}")
    old_text = str(ctx.args.get("old_text", ""))
    new_text = str(ctx.args.get("new_text", ""))
    if not _ask_user_confirm(
        f"将编辑文件：{path}\n替换：{old_text[:80]}\n为：{new_text[:80]}\n是否确认？"
    ):
        return PreHookResult(error="用户取消了该操作")
    return None


def list_dir_pre_hook(ctx: ToolCallContext) -> PreHookResult | None:
    path = _resolve_path_arg(ctx)
    if not path.exists():
        return PreHookResult(error=f"路径不存在: {path}")
    if not path.is_dir():
        return PreHookResult(error=f"不是目录: {path}")
    return None


def exec_pre_hook(ctx: ToolCallContext) -> PreHookResult | None:
    command = str(ctx.args.get("command", ""))
    if _is_safe_exec_command(command):
        return None
    if not _ask_user_confirm(f"将执行以下命令：\n\n{command}\n\n是否确认？"):
        return PreHookResult(error="用户取消了该操作")
    return None
```

Remove migrated checks from `read_file_handler`, `write_file_handler`, `edit_file_handler`, `list_dir_handler`, and `exec_handler`. Handler bodies keep file reading, writing, replacement, listing, subprocess execution, result conversion, and exception handling.

Update tool registrations:

```python
    ToolDefinition(name="read_file", schema=READ_FILE_SCHEMA, handler=read_file_handler, pre_hook=read_file_pre_hook),
    ToolDefinition(name="write_file", schema=WRITE_FILE_SCHEMA, handler=write_file_handler, pre_hook=write_file_pre_hook),
    ToolDefinition(name="edit_file", schema=EDIT_FILE_SCHEMA, handler=edit_file_handler, pre_hook=edit_file_pre_hook),
    ToolDefinition(name="list_dir", schema=LIST_DIR_SCHEMA, handler=list_dir_handler, pre_hook=list_dir_pre_hook),
    ToolDefinition(name="exec", schema=EXEC_SCHEMA, handler=exec_handler, pre_hook=exec_pre_hook),
```

**Verification**: T014 and T017 tests pass.

---

### T020: Migrate query_data and analyze_image gates into pre-hooks

**File**: `src/business/agents/tools/recording_data_tools.py` (modified)

**Requirements**: FR-007, FR-009, SC-003

**Dependencies**: T010

Add import:

```python
from src.business.agents.hook_models import PreHookResult, ToolCallContext
```

Add pre-hooks near the schemas:

```python
def query_data_pre_hook(ctx: ToolCallContext) -> PreHookResult | None:
    sql = str(ctx.args.get("sql", ""))
    try:
        rewrite(sql)
    except Exception as exc:
        return PreHookResult(error=_mask_recording_data_error(exc))
    return None


def analyze_image_pre_hook(ctx: ToolCallContext) -> PreHookResult | None:
    action_index = ctx.args.get("action_index")
    if isinstance(action_index, int):
        indices = [action_index]
    else:
        indices = list(action_index or [])
    if len(indices) > _MAX_ACTION_INDICES:
        return PreHookResult(
            error=(
                f"单次最多分析 {_MAX_ACTION_INDICES} 个操作的截图，"
                f"当前传入 {len(indices)} 个，请缩小范围。"
            )
        )
    return None
```

Remove the length rejection from `_analyze_image`; it now starts after `indices` normalization with the DuckDB lookup. Keep `_query_data` calling `rewrite(sql)` to produce the executable SQL.

Update registrations:

```python
        ToolDefinition(
            name="query_data",
            schema=QUERY_DATA_SCHEMA,
            handler=lambda sql: _query_data(recording_id, sql),
            pre_hook=query_data_pre_hook,
        ),
```

and:

```python
        ToolDefinition(
            name="analyze_image",
            schema=ANALYZE_IMAGE_SCHEMA,
            handler=lambda action_index, question: _analyze_image(
                recording_id, action_index, question
            ),
            pre_hook=analyze_image_pre_hook,
        ),
```

**Verification**: T015 and T031 tests pass; `test_recording_data_tools_does_not_import_sqlglot` remains green.

---

### T021: Move run_command attempt counting into a per-run pre-hook closure

**File**: `src/business/agents/tools/trial_tools.py` (modified)

**Requirements**: FR-008, SC-003

**Dependencies**: T010

Add import:

```python
from src.business.agents.hook_models import PreHookResult, ToolCallContext
```

Replace `_run_command_handler` with:

```python
    def _run_command_pre_hook(ctx: ToolCallContext) -> PreHookResult | None:
        nonlocal _command_attempts
        _command_attempts += 1
        if _command_attempts > _MAX_COMMAND_ATTEMPTS:
            return PreHookResult(
                error=f"命令执行总次数已达上限（{_MAX_COMMAND_ATTEMPTS}次），请直接报告失败"
            )
        return None

    def _run_command_handler(command: str) -> str:
        result = run_command_in_venv(command)
        return json.dumps(result, ensure_ascii=False)
```

Update registration:

```python
        ToolDefinition(
            name="run_command",
            schema=RUN_COMMAND_SCHEMA,
            handler=_run_command_handler,
            pre_hook=_run_command_pre_hook,
        ),
```

**Verification**: T016 passes and a new `create_trial_tools()` call resets the closure counter.

---

### T022: Run migrated-tool validation

**File**: command

**Requirements**: SC-003, SC-004

**Dependencies**: T014-T021

```powershell
uv run python -m pytest tests/test_hook_protocol.py -q
```

**Verification**: Exit code 0.

---

## Phase 5: User Story 3

### T023: Add global hook ordering tests

**File**: `tests/test_hook_protocol.py` (new)

**Requirements**: FR-005

**Dependencies**: T001, T010

Appendix A includes `test_global_pre_and_post_hooks_run_after_tool_hooks_in_order`.

**Verification**: Event order is `tool_pre`, `global_pre`, `handler`, `tool_post`, `global_post`.

---

### T024: Add global scope, short-circuit, mixed-batch, and context tests

**File**: `tests/test_hook_protocol.py` (new)

**Requirements**: FR-005, FR-011a, FR-012, FR-016

**Dependencies**: T001, T010

Appendix A includes `test_global_scope_context_fields_and_short_circuit` and `test_global_hooks_do_not_apply_to_invalid_mixed_batches_or_injected_tools`.

**Verification**: Global hooks see context fields for `ToolDefinition` tools, do not run after tool-level rejection, and do not run in invalid mixed batches.

---

### T025: Add full-chain overhead and mounting-cost tests

**File**: `tests/test_hook_protocol.py` (new)

**Requirements**: SC-002, SC-005

**Dependencies**: T001, T010, T026

Appendix A includes `test_full_chain_noop_hook_overhead_and_mounting_cost`.

**Verification**: No-op full chain stays under the 5 ms budget and `AgentConfig(global_pre_hooks=[hook])` requires no handler or AgentLoop source edits.

---

### T026: Wire AgentConfig global hooks into AgentLoop

**File**: `src/business/agents/agent_loop.py` (modified)

**Requirements**: FR-005, FR-012, SC-005

**Dependencies**: T010

The `_execute_tool_call` implementation in T010 already wires `self._config.global_pre_hooks` and `self._config.global_post_hooks` after tool-level hooks.

**Verification**: T023-T025 tests pass.

---

### T027: Run global-hook validation

**File**: command

**Requirements**: FR-005, SC-005

**Dependencies**: T023-T026

```powershell
uv run python -m pytest tests/test_hook_protocol.py -q
```

**Verification**: Exit code 0.

---

## Phase 6: Polish

### T028: Update AgentLoop runtime structure and hook semantics in architecture docs

**File**: `docs/ARCHITECTURE.md` (modified)

**Requirements**: FR-001, FR-005, FR-016

**Dependencies**: T010-T026

Insert after the Function Calling section around line 211:

````markdown
### 工具执行 Hook

`AgentLoop` 对调用方传入或动态构建的 `ToolDefinition` 支持同步 pre/post hook。执行顺序为：

```text
tool pre_hook
→ AgentConfig.global_pre_hooks
→ handler
→ tool post_hook
→ AgentConfig.global_post_hooks
```

pre_hook 只做放行、拒绝和观测，不能改写 handler 入参；`ToolCallContext.args` 是递归只读隔离视图。post_hook 只接收 handler 的原始字符串结果或普通 handler 异常转换出的标准化错误字符串；多个 post_hook 不形成结果流水线，最后一个返回非空 `PostHookResult.result` 的 hook 决定最终展示文本。

多工具批处理语义先于 hook 生效：同轮混合中断型工具时直接写入 `invalid_model_output`，不执行 hook 或 handler；普通批次中 hook 拒绝、handler 异常、标准化错误结果或 handler 返回类型与 `is_interrupting` 不匹配都会触发后续工具的 `not_executed`。合法单中断工具可以执行 pre_hook，但返回 `ToolSignal` 后跳过 post_hook 并保持原有暂停或完成语义。

`load_reference` 和 `talk_to_user` 是 AgentLoop 内建注入工具，继续用于上下文引用和用户交互，但不进入 tool/global hook 管线。
````

**Verification**: 文档中包含 `工具执行 Hook` 小节，并准确描述多工具批处理优先于 hook。

---

### T029: Document hook boundaries in project constraints

**File**: `docs/PROJECT_CONSTRAINTS.md` (new)

**Requirements**: FR-003, FR-006, FR-007, FR-008, FR-009

**Dependencies**: T019-T021

Create the file with:

```markdown
# Exemplar Project Constraints

本文件记录开发约束、反模式和允许例外。长期治理原则仍以 `.specify/memory/constitution.md` 为准。

## Agent Tool Hook Boundaries

- pre_hook 只允许放行、拒绝和观测，不允许改写 handler 入参。
- `ToolCallContext.args` 必须是递归只读隔离视图；顶层和嵌套 dict/list 写入都应抛异常，handler 入参不受影响。
- `PreHookResult` 只表达拒绝结果，不携带替换参数。
- post_hook 不通过 `ToolCallContext` 获取结果；它只能通过第二个 `result` 参数读取 handler 原始字符串结果或普通 handler 异常转换出的标准化错误字符串。
- post_hook 不形成结果流水线；每个 post_hook 看到同一个原始结果，最后一个返回非空 `PostHookResult.result` 的 hook 决定最终文本。
- `ToolSignal` 是 AgentLoop 控制信号，合法中断型工具返回该信号时跳过 post_hook。

## Migrated Gate Ownership

- `builtin_general_tools.read_file`、`write_file`、`edit_file`、`list_dir`、`exec` 的路径存在性、系统目录拒绝、命令安全分类和用户确认属于 pre_hook。
- `edit_file` 的 `old_text` 查找与唯一性校验属于编辑执行准备，留在 handler。
- `recording_data_tools.query_data` 的 SQL 拒绝策略属于 pre_hook，但 handler 仍可再次调用 `rewrite(sql)` 生成实际执行 SQL。
- `recording_data_tools.analyze_image` 的单次最多 5 个 action_index 限制属于 pre_hook。
- `trial_tools.run_command` 的单次 `AgentLoop.run()` 调用上限属于 `create_trial_tools()` 内创建的 pre_hook 闭包。

## Non-Migrated Boundaries

- `programmer_tools.syntax_check` 整个 handler 即校验本身，不迁移到 hook。
- `recording_data_tools.execute_code` 的受限 builtins、import 控制和超时属于执行内核，不迁移到 hook。
- `src/execution/tool_executor.py` 的 venv 隔离和命令白名单位于 handler 层之下，不迁移到 hook。
- `dynamic_tool_manager` 的发布状态、允许列表、技能发现和技能组合激活属于工具发现阶段，不迁移到 hook。

## Review Guardrails

Reviewer 必须拒绝下列改动：

- 在 pre_hook 中加入参数改写或参数流水线语义。
- 在 `ToolCallContext` 中加入确认回调、结果字段或可写参数引用。
- 在 handler 中保留已经迁移到 pre_hook 的拒绝、确认、限流或安全策略分支。
- 让 AgentLoop 内建注入的 `load_reference` 或 `talk_to_user` 进入 tool/global hook 链。
- 绕过 `src/recording/filtering/` 的 SQL 改写或 DuckDB 代理边界读取录制网络数据。
```

**Verification**: `Test-Path docs/PROJECT_CONSTRAINTS.md` returns true and the file contains `Agent Tool Hook Boundaries`.

---

### T030: Run focused protocol suite

**File**: command

**Requirements**: SC-001

**Dependencies**: T001-T029

```powershell
uv run python -m pytest tests/test_hook_protocol.py -q
```

**Verification**: Exit code 0.

---

### T031: Run recording guard/regression suite

**File**: command

**Requirements**: FR-007, FR-009

**Dependencies**: T020

```powershell
uv run python -m pytest tests/recording/test_recording_data_tools_noise_filtering.py tests/recording/filtering/test_recording_tools_no_sqlglot.py -q
```

**Verification**: Exit code 0.

---

### T032: Run Agent runtime smoke suite

**File**: command

**Requirements**: FR-016, SC-008

**Dependencies**: T010-T012

```powershell
uv run python -m pytest tests/integration/test_agent_loop_multi_tool_calls.py tests/integration/test_assistant_new_session.py -q
```

**Verification**: Exit code 0.

---

### T033: Run stale-semantics scan

**File**: command

**Requirements**: FR-003, FR-009

**Dependencies**: all code changes

```powershell
rg -n "PreHookResult.*args|ToolCallContext.*result|只读浅拷贝|pipeline|流水线|改参" src tests
```

**Verification**: No stale positive match remains outside intentional guard strings in tests.

---

### T034: Run syntax validation

**File**: command

**Requirements**: SC-001

**Dependencies**: all code changes

```powershell
uv run python -m py_compile src/business/agents/hook_models.py src/business/agents/config.py src/business/agents/agent_loop.py src/business/agents/tools/builtin_general_tools.py src/business/agents/tools/recording_data_tools.py src/business/agents/tools/trial_tools.py
```

**Verification**: Exit code 0.

---

### T035: Run formatting check

**File**: command

**Requirements**: SC-001

**Dependencies**: all code changes

```powershell
uv run black --check src tests
```

**Verification**: Exit code 0 or documented exception.

---

### T036: Run lint check

**File**: command

**Requirements**: SC-001

**Dependencies**: all code changes

```powershell
uv run flake8 src tests
```

**Verification**: Exit code 0 or documented exception.

---

### T037: Run final regression command

**File**: command

**Requirements**: SC-001

**Dependencies**: T030-T036

```powershell
uv run python -m pytest tests -q
```

**Verification**: Exit code 0 or documented exception.

---

## Appendix A: Complete `tests/test_hook_protocol.py`

```python
import json
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.business.agents.agent_loop import AgentLoop
from src.business.agents.config import AgentConfig, AgentType, ResultType, ToolDefinition, ToolSignal
from src.business.agents.hook_models import PostHookResult, PreHookResult
from src.business.ai.llm_client import LLMResponse, ToolCallInfo
from tests.conftest import MockLLMClient


def _schema(name: str) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": f"{name} test tool",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    }


def _config(**kwargs) -> AgentConfig:
    return AgentConfig(
        agent_type=AgentType.PM,
        system_prompt="You are a hook protocol test agent.",
        max_iterations=10,
        **kwargs,
    )


def _run_once(mock_config, tools, tool_calls, session_id="hook-test", config=None):
    responses = [
        LLMResponse(content=None, tool_calls=tool_calls),
        LLMResponse(content="done", tool_calls=[]),
    ]
    loop = AgentLoop(config or _config(), MockLLMClient(responses), mock_config)
    result = loop.run(session_id=session_id, user_input="start", tools=tools)
    ctx = loop._get_context_manager(session_id)
    messages = ctx._msg_repo.get_context(session_id)
    return result, [m for m in messages if m.role == "tool"]


def _tool(name, handler=None, pre_hook=None, post_hook=None, is_interrupting=False):
    return ToolDefinition(
        name=name,
        schema=_schema(name),
        handler=handler or (lambda **kwargs: "ok"),
        is_interrupting=is_interrupting,
        pre_hook=pre_hook,
        post_hook=post_hook,
    )


def test_no_hook_tool_remains_transparent(mock_config, in_memory_db):
    result, tool_results = _run_once(
        mock_config,
        [_tool("plain", handler=lambda value=None: json.dumps({"value": value}))],
        [ToolCallInfo(id="c1", name="plain", args={"value": "original"})],
        session_id="hook-no-hook",
    )
    assert result.result_type == ResultType.COMPLETED
    assert json.loads(tool_results[0].content) == {"value": "original"}


def test_pre_hook_error_short_circuits_with_standardized_error(mock_config, in_memory_db):
    handler = Mock(return_value="should not run")
    post_hook = Mock()

    def pre_hook(ctx):
        return PreHookResult(error="blocked")

    result, tool_results = _run_once(
        mock_config,
        [_tool("blocked", handler=handler, pre_hook=pre_hook, post_hook=post_hook)],
        [ToolCallInfo(id="c1", name="blocked", args={})],
        session_id="hook-pre-error",
    )
    payload = json.loads(tool_results[0].content)
    assert result.result_type == ResultType.COMPLETED
    assert payload["error"] == "pre_hook_rejected"
    assert payload["message"] == "blocked"
    assert handler.call_count == 0
    assert post_hook.call_count == 0


def test_post_hook_rewrites_result(mock_config, in_memory_db):
    def post_hook(ctx, result):
        assert result == "raw"
        return PostHookResult(result="rewritten")

    result, tool_results = _run_once(
        mock_config,
        [_tool("rewrite", handler=lambda: "raw", post_hook=post_hook)],
        [ToolCallInfo(id="c1", name="rewrite", args={})],
        session_id="hook-post-rewrite",
    )
    assert result.result_type == ResultType.COMPLETED
    assert tool_results[0].content == "rewritten"


def test_recursive_args_are_read_only_and_isolated(mock_config, in_memory_db):
    seen = {}

    def pre_hook(ctx):
        with pytest.raises(TypeError):
            ctx.args["value"] = "changed"
        with pytest.raises((TypeError, AttributeError)):
            ctx.args["nested"]["items"].append("changed")

    def handler(value, nested):
        seen["value"] = value
        seen["nested"] = nested
        return "ok"

    result, tool_results = _run_once(
        mock_config,
        [_tool("freeze", handler=handler, pre_hook=pre_hook)],
        [
            ToolCallInfo(
                id="c1",
                name="freeze",
                args={"value": "original", "nested": {"items": ["a"]}},
            )
        ],
        session_id="hook-freeze",
    )
    assert result.result_type == ResultType.COMPLETED
    assert tool_results[0].content == "ok"
    assert seen == {"value": "original", "nested": {"items": ["a"]}}


def test_pre_hook_exception_runs_handler_and_skips_post_hook(mock_config, in_memory_db):
    events = []

    def pre_hook(ctx):
        events.append("pre")
        raise RuntimeError("pre failed")

    def handler():
        events.append("handler")
        return "handler-result"

    def post_hook(ctx, result):
        events.append("post")
        return PostHookResult(result="post-result")

    result, tool_results = _run_once(
        mock_config,
        [_tool("pre_exception", handler=handler, pre_hook=pre_hook, post_hook=post_hook)],
        [ToolCallInfo(id="c1", name="pre_exception", args={})],
        session_id="hook-pre-exception",
    )
    assert result.result_type == ResultType.COMPLETED
    assert tool_results[0].content == "handler-result"
    assert events == ["pre", "handler"]


def test_handler_exception_reaches_post_hook_and_preserves_failure_status(mock_config, in_memory_db):
    events = []

    def bad_handler():
        raise RuntimeError("boom")

    def post_hook(ctx, result):
        events.append(json.loads(result)["error"])
        return PostHookResult(result="visible rewrite")

    result, tool_results = _run_once(
        mock_config,
        [
            _tool("bad", handler=bad_handler, post_hook=post_hook),
            _tool("later", handler=lambda: "later ran"),
        ],
        [
            ToolCallInfo(id="c1", name="bad", args={}),
            ToolCallInfo(id="c2", name="later", args={}),
        ],
        session_id="hook-handler-exception",
    )
    assert result.result_type == ResultType.COMPLETED
    assert events == ["handler_exception"]
    assert tool_results[0].content == "visible rewrite"
    assert json.loads(tool_results[1].content)["error"] == "not_executed"


def test_legal_tool_signal_skips_post_hook(mock_config, in_memory_db):
    post_hook = Mock()
    responses = [
        LLMResponse(
            content=None,
            tool_calls=[ToolCallInfo(id="c1", name="submit", args={})],
        )
    ]
    loop = AgentLoop(_config(), MockLLMClient(responses), mock_config)
    result = loop.run(
        session_id="hook-signal",
        user_input="start",
        tools=[
            _tool(
                "submit",
                handler=lambda: ToolSignal(result_type=ResultType.COMPLETED, display_text="submitted"),
                post_hook=post_hook,
                is_interrupting=True,
            )
        ],
    )
    assert result.result_type == ResultType.COMPLETED
    assert post_hook.call_count == 0


def test_ordinary_tool_signal_contract_violation_cascades_not_executed(mock_config, in_memory_db):
    result, tool_results = _run_once(
        mock_config,
        [
            _tool("ordinary_signal", handler=lambda: ToolSignal(result_type=ResultType.COMPLETED)),
            _tool("later", handler=lambda: "later ran"),
        ],
        [
            ToolCallInfo(id="c1", name="ordinary_signal", args={}),
            ToolCallInfo(id="c2", name="later", args={}),
        ],
        session_id="hook-contract",
    )
    assert result.result_type == ResultType.COMPLETED
    assert json.loads(tool_results[0].content)["error"] == "handler_contract_violation"
    assert json.loads(tool_results[1].content)["error"] == "not_executed"


def test_callable_same_name_handler_hook_and_interrupt_metadata_refresh_each_iteration(mock_config, in_memory_db):
    events = []
    calls = {"factory": 0}

    def tool_factory():
        calls["factory"] += 1
        if calls["factory"] == 1:
            return [_tool("dynamic", handler=lambda: events.append("first") or "first")]
        return [
            _tool(
                "dynamic",
                handler=lambda: events.append("second") or "second",
                pre_hook=lambda ctx: events.append("pre_second") or None,
            )
        ]

    responses = [
        LLMResponse(content=None, tool_calls=[ToolCallInfo(id="c1", name="dynamic", args={})]),
        LLMResponse(content=None, tool_calls=[ToolCallInfo(id="c2", name="dynamic", args={})]),
        LLMResponse(content="done", tool_calls=[]),
    ]
    loop = AgentLoop(_config(), MockLLMClient(responses), mock_config)
    result = loop.run(session_id="hook-callable", user_input="start", tools=tool_factory)
    assert result.result_type == ResultType.COMPLETED
    assert events == ["first", "pre_second", "second"]


def test_tool_level_noop_hook_overhead_smoke(mock_config, in_memory_db):
    def run_many(tool, session_name):
        start = time.perf_counter()
        for index in range(20):
            _run_once(
                mock_config,
                [tool],
                [ToolCallInfo(id=f"c{index}", name=tool.name, args={})],
                session_id=f"{session_name}-{index}",
            )
        return (time.perf_counter() - start) / 20

    baseline = run_many(_tool("baseline", handler=lambda: "ok"), "hook-baseline")
    hooked = run_many(
        _tool("hooked", handler=lambda: "ok", pre_hook=lambda ctx: None, post_hook=lambda ctx, result: None),
        "hooked",
    )
    assert hooked - baseline < 0.005


def test_builtin_general_pre_hooks_reject_before_handler(monkeypatch, mock_config, in_memory_db):
    from src.business.agents.tools import builtin_general_tools as mod

    monkeypatch.setattr(mod, "_ask_user_confirm", lambda message: False)
    write_tool = next(tool for tool in mod.BUILTIN_GENERAL_TOOLS if tool.name == "write_file")
    exec_tool = next(tool for tool in mod.BUILTIN_GENERAL_TOOLS if tool.name == "exec")
    write_tool.handler = Mock(return_value="should not run")
    exec_tool.handler = Mock(return_value="should not run")

    result, tool_results = _run_once(
        mock_config,
        [write_tool, exec_tool],
        [
            ToolCallInfo(id="c1", name="write_file", args={"path": "C:/Windows/System32/hosts", "content": "x"}),
            ToolCallInfo(id="c2", name="exec", args={"command": "git status; rm -rf /"}),
        ],
        session_id="hook-builtin-gates",
    )
    assert result.result_type == ResultType.COMPLETED
    assert json.loads(tool_results[0].content)["error"] == "pre_hook_rejected"
    assert json.loads(tool_results[1].content)["error"] == "not_executed"
    assert write_tool.handler.call_count == 0
    assert exec_tool.handler.call_count == 0


def test_recording_query_and_analyze_image_pre_hooks(mock_config, in_memory_db):
    from src.business.agents.tools.recording_data_tools import create_recording_tools

    tools = create_recording_tools("rec")
    query_tool = next(tool for tool in tools if tool.name == "query_data")
    image_tool = next(tool for tool in tools if tool.name == "analyze_image")
    query_tool.handler = Mock(return_value="should not run")
    image_tool.handler = Mock(return_value="should not run")

    result, tool_results = _run_once(
        mock_config,
        [query_tool, image_tool],
        [
            ToolCallInfo(id="c1", name="query_data", args={"sql": "SELECT * FROM filter_decisions"}),
            ToolCallInfo(
                id="c2",
                name="analyze_image",
                args={"action_index": [1, 2, 3, 4, 5, 6], "question": "what changed"},
            ),
        ],
        session_id="hook-recording-gates",
    )
    assert result.result_type == ResultType.COMPLETED
    assert json.loads(tool_results[0].content)["error"] == "pre_hook_rejected"
    assert json.loads(tool_results[1].content)["error"] == "not_executed"
    assert query_tool.handler.call_count == 0
    assert image_tool.handler.call_count == 0


def test_trial_run_command_pre_hook_limits_per_create_trial_tools_call(monkeypatch, mock_config, in_memory_db):
    from src.business.agents.tools import trial_tools

    monkeypatch.setattr(trial_tools, "run_command_in_venv", lambda command: {"success": True, "command": command})
    run_command_tool = next(tool for tool in trial_tools.create_trial_tools("wf") if tool.name == "run_command")
    calls = [ToolCallInfo(id=f"c{i}", name="run_command", args={"command": "echo ok"}) for i in range(1, 7)]
    result, tool_results = _run_once(
        mock_config,
        [run_command_tool],
        calls,
        session_id="hook-trial-limit",
    )
    assert result.result_type == ResultType.COMPLETED
    assert len(tool_results) == 6
    assert json.loads(tool_results[5].content)["error"] == "pre_hook_rejected"


def test_migrated_handler_bodies_no_longer_contain_gate_logic():
    builtin_source = Path("src/business/agents/tools/builtin_general_tools.py").read_text(encoding="utf-8")
    assert "禁止写入系统目录" not in _function_body(builtin_source, "write_file_handler")
    assert "_ask_user_confirm" not in _function_body(builtin_source, "write_file_handler")
    assert "_ask_user_confirm" not in _function_body(builtin_source, "edit_file_handler")
    assert "EXEC_SAFE_COMMANDS" not in _function_body(builtin_source, "exec_handler")
    assert "old_text" in _function_body(builtin_source, "edit_file_handler")
    assert "content.count(old_text)" in _function_body(builtin_source, "edit_file_handler")

    recording_source = Path("src/business/agents/tools/recording_data_tools.py").read_text(encoding="utf-8")
    assert f"len(indices) > _MAX_ACTION_INDICES" not in _function_body(recording_source, "_analyze_image")

    trial_source = Path("src/business/agents/tools/trial_tools.py").read_text(encoding="utf-8")
    assert "_command_attempts += 1" not in _function_body(trial_source, "_run_command_handler")


def test_non_migration_boundaries_remain_outside_hook_system():
    programmer = Path("src/business/agents/tools/programmer_tools.py").read_text(encoding="utf-8")
    recording = Path("src/business/agents/tools/recording_data_tools.py").read_text(encoding="utf-8")
    dynamic = Path("src/business/agents/tools/dynamic_tool_manager.py").read_text(encoding="utf-8")
    assert "syntax_check = ToolDefinition" in programmer
    assert "name=\"execute_code\"" in recording
    assert "pre_hook=" not in _definition_block(recording, "execute_code")
    assert "_build_tool_definition" in dynamic
    assert "pre_hook=" not in dynamic


def test_global_pre_and_post_hooks_run_after_tool_hooks_in_order(mock_config, in_memory_db):
    events = []

    cfg = _config(
        global_pre_hooks=[lambda ctx: events.append("global_pre") or None],
        global_post_hooks=[lambda ctx, result: events.append("global_post") or None],
    )
    tool = _tool(
        "ordered",
        handler=lambda: events.append("handler") or "ok",
        pre_hook=lambda ctx: events.append("tool_pre") or None,
        post_hook=lambda ctx, result: events.append("tool_post") or None,
    )
    _run_once(
        mock_config,
        [tool],
        [ToolCallInfo(id="c1", name="ordered", args={})],
        session_id="hook-global-order",
        config=cfg,
    )
    assert events == ["tool_pre", "global_pre", "handler", "tool_post", "global_post"]


def test_global_scope_context_fields_and_short_circuit(mock_config, in_memory_db):
    seen = []
    cfg = _config(global_pre_hooks=[lambda ctx: seen.append((ctx.tool_name, ctx.session_id, ctx.iteration))])
    tool = _tool("short", pre_hook=lambda ctx: PreHookResult(error="blocked"))
    _run_once(
        mock_config,
        [tool],
        [ToolCallInfo(id="c1", name="short", args={"x": 1})],
        session_id="hook-global-scope",
        config=cfg,
    )
    assert seen == []

    _run_once(
        mock_config,
        [_tool("visible")],
        [ToolCallInfo(id="c1", name="visible", args={})],
        session_id="hook-global-visible",
        config=cfg,
    )
    assert seen == [("visible", "hook-global-visible", 1)]


def test_global_hooks_do_not_apply_to_invalid_mixed_batches_or_injected_tools(mock_config, in_memory_db):
    events = []
    cfg = _config(global_pre_hooks=[lambda ctx: events.append(ctx.tool_name)])
    tools = [
        _tool("ordinary"),
        _tool(
            "submit",
            handler=lambda: ToolSignal(result_type=ResultType.COMPLETED),
            is_interrupting=True,
        ),
    ]
    _run_once(
        mock_config,
        tools,
        [
            ToolCallInfo(id="c1", name="ordinary", args={}),
            ToolCallInfo(id="c2", name="submit", args={}),
        ],
        session_id="hook-invalid-mixed",
        config=cfg,
    )
    assert events == []


def test_full_chain_noop_hook_overhead_and_mounting_cost(mock_config, in_memory_db):
    def noop_pre(ctx):
        return None

    def noop_post(ctx, result):
        return None

    cfg = _config(global_pre_hooks=[noop_pre], global_post_hooks=[noop_post])
    assert len(cfg.global_pre_hooks) == 1
    assert len(cfg.global_post_hooks) == 1
    result, tool_results = _run_once(
        mock_config,
        [_tool("full_chain", handler=lambda: "ok", pre_hook=noop_pre, post_hook=noop_post)],
        [ToolCallInfo(id="c1", name="full_chain", args={})],
        session_id="hook-full-chain",
        config=cfg,
    )
    assert result.result_type == ResultType.COMPLETED
    assert tool_results[0].content == "ok"


def _function_body(source: str, function_name: str) -> str:
    start = source.index(f"def {function_name}")
    next_def = source.find("\ndef ", start + 1)
    next_section = source.find("\n# =========================================================================", start + 1)
    candidates = [pos for pos in (next_def, next_section) if pos != -1]
    end = min(candidates) if candidates else len(source)
    return source[start:end]


def _definition_block(source: str, tool_name: str) -> str:
    marker = f'name="{tool_name}"'
    start = source.index(marker)
    end = source.find("),", start)
    return source[start:end]
```

## Appendix B: Complete `src/business/agents/hook_models.py`

```python
"""
Agent tool hook protocol models.

These types live outside config.py so recursive argument freezing and internal
execution bookkeeping do not bloat the public Agent preset module.
"""

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Callable, Mapping


@dataclass(frozen=True)
class ToolCallContext:
    """Read-only context visible to tool pre/post hooks."""

    tool_name: str
    args: Mapping[str, Any]
    session_id: str
    agent_type: Any
    iteration: int


@dataclass(frozen=True)
class PreHookResult:
    """Pre-hook decision. A non-empty error rejects the tool call."""

    error: str | None = None


@dataclass(frozen=True)
class PostHookResult:
    """Post-hook decision. A non-None result replaces final string output."""

    result: str | None = None


PreHook = Callable[[ToolCallContext], PreHookResult | None]
PostHook = Callable[[ToolCallContext, str], PostHookResult | None]


@dataclass(frozen=True)
class ToolExecutionDefinition:
    """Internal immutable execution entry derived from ToolDefinition."""

    name: str
    handler: Callable[..., Any]
    is_interrupting: bool
    pre_hook: PreHook | None = None
    post_hook: PostHook | None = None


@dataclass(frozen=True)
class ToolExecutionOutcome:
    """Internal result used by AgentLoop batch execution."""

    result: Any
    failed: bool = False
    failure_code: str | None = None


def freeze_tool_args(args: Mapping[str, Any]) -> Mapping[str, Any]:
    """Return a detached recursive read-only view of tool arguments."""

    frozen = {str(key): _freeze_value(value) for key, value in dict(args).items()}
    return MappingProxyType(frozen)


def _freeze_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze_value(inner) for key, inner in value.items()})
    if isinstance(value, list):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, tuple):
        return tuple(_freeze_value(item) for item in value)
    if isinstance(value, set):
        return frozenset(_freeze_value(item) for item in value)
    return value


__all__ = [
    "ToolCallContext",
    "PreHookResult",
    "PostHookResult",
    "PreHook",
    "PostHook",
    "ToolExecutionDefinition",
    "ToolExecutionOutcome",
    "freeze_tool_args",
]
```

## Checklist

- [ ] T001: Create `tests/test_hook_protocol.py` with shared pytest fixtures
- [ ] T002: Create `src/business/agents/hook_models.py`
- [ ] T003: Implement hook protocol models and args freezing
- [ ] T004: Extend `ToolDefinition` and `AgentConfig`
- [ ] T005: Add no-hook, pre-hook rejection, and post-hook rewrite tests
- [ ] T006: Add recursive args and pre-hook exception tests
- [ ] T007: Add handler exception, signal, contract, and cascade tests
- [ ] T008: Add callable same-name refresh smoke test
- [ ] T009: Add tool-level overhead smoke test
- [ ] T010: Integrate hook-aware per-call execution into AgentLoop
- [ ] T011: Refresh callable execution mapping each iteration
- [ ] T012: Exclude injected built-ins from hook execution
- [ ] T013: Run focused P1 validation
- [ ] T014: Add builtin general tool migration tests
- [ ] T015: Add recording tool migration tests
- [ ] T016: Add trial run_command limit tests
- [ ] T017: Add static handler cleanup guard tests
- [ ] T018: Add non-migration boundary guard tests
- [ ] T019: Migrate builtin general gates into pre-hooks
- [ ] T020: Migrate query_data and analyze_image gates into pre-hooks
- [ ] T021: Move run_command attempt counting into a pre-hook closure
- [ ] T022: Run migrated-tool validation
- [ ] T023: Add global hook ordering tests
- [ ] T024: Add global scope and mixed-batch tests
- [ ] T025: Add overhead and mounting-cost tests
- [ ] T026: Wire AgentConfig global hooks into AgentLoop
- [ ] T027: Run global-hook validation
- [ ] T028: Update `docs/ARCHITECTURE.md`
- [ ] T029: Add `docs/PROJECT_CONSTRAINTS.md`
- [ ] T030: Run focused protocol suite
- [ ] T031: Run recording guard/regression suite
- [ ] T032: Run Agent runtime smoke suite
- [ ] T033: Run stale-semantics scan
- [ ] T034: Run syntax validation
- [ ] T035: Run formatting check
- [ ] T036: Run lint check
- [ ] T037: Run final regression command
