# Data Model: 工具执行 Pre/Post Hook 系统

本 feature 不新增持久化数据模型。以下是运行时协议模型，均位于业务层 Agent runtime。

## ToolCallContext

**Purpose**: 单次 `ToolDefinition` 工具调用的只读上下文，供 pre/post hook 观测调用信息。

**Fields**:
- `tool_name: str`
- `args: Mapping[str, Any]`，LLM 原始入参的递归只读隔离视图
- `session_id: str`
- `agent_type: AgentType | str`
- `iteration: int`

**Validation rules**:
- 不包含 `result` 字段。
- 不包含用户确认回调。
- `args` 顶层与嵌套 dict/list 均不可写；写入必须抛异常。
- `args` 写入失败不得改变 handler 实际收到的原始入参。

## PreHookResult

**Purpose**: 表达 pre_hook 是否拒绝本次工具调用。

**Fields**:
- `error: str | None = None`

**Validation rules**:
- 不包含 `args` 字段。
- `error` 有值时短路 handler 与全部 post_hook，并把错误文本作为工具结果返回给 LLM。
- `None` 或 `error is None` 表示放行。

## PostHookResult

**Purpose**: 表达 post_hook 是否改写普通字符串工具结果。

**Fields**:
- `result: str | None = None`

**Validation rules**:
- 只适用于 handler 返回普通 `str` 或 handler 异常转换后的 error 字符串。
- `ToolSignal` 不进入 post_hook。
- 多个 post_hook 均接收 handler 原始结果；最后一个非 None `result` 生效。

## PreHook

**Signature**:

```python
Callable[[ToolCallContext], PreHookResult | None]
```

**State transitions**:
- `None` / no error -> next pre_hook or handler
- `error` -> stop pre_hooks, skip handler and post_hooks, return error string
- raises -> log warning, stop remaining pre_hooks, run handler, skip posthooks

## PostHook

**Signature**:

```python
Callable[[ToolCallContext, str], PostHookResult | None]
```

**State transitions**:
- `None` / no result -> next post_hook
- `result` -> record candidate rewrite and continue
- raises -> log warning, stop remaining post_hooks, return handler original result

## ToolDefinition Extension

**Existing fields**:
- `name: str`
- `schema: dict[str, Any]`
- `handler: Callable[..., str | ToolSignal]`
- `is_interrupting: bool = False`

**New fields**:
- `pre_hook: PreHook | None = None`
- `post_hook: PostHook | None = None`

**Validation rules**:
- Absence of hooks preserves existing behavior.
- Only tools represented by `ToolDefinition` participate in hook execution.
- `is_interrupting` remains the sole declarative input for AgentLoop batch classification and handler return-type contract validation.

## AgentConfig Extension

**Existing relevant fields**:
- `agent_type: AgentType`
- `system_prompt: str`
- `max_iterations: int`
- `retry: RetryConfig`
- `text_as_user_input: bool`

**New fields**:
- `global_pre_hooks: list[PreHook] = field(default_factory=list)`
- `global_post_hooks: list[PostHook] = field(default_factory=list)`

**Validation rules**:
- Scope is the current `AgentConfig` instance only.
- No framework-level global registry.
- No effect on AgentLoop injected `talk_to_user` / `load_reference`.

## ToolExecutionDefinition

**Purpose**: Internal AgentLoop execution map entry derived from `ToolDefinition`.

**Fields**:
- `handler`
- `is_interrupting`
- `pre_hook`
- `post_hook`

**Validation rules**:
- Refreshed every AgentLoop iteration for callable tool factories.
- Schema cache may still refresh only when the callable factory's tool-name set changes.
- Classification metadata must refresh even when the name set is unchanged.

## ToolExecutionOutcome

**Purpose**: Internal AgentLoop result for one hook-aware tool execution, used by batch logic.

**Fields**:
- `result: str | ToolSignal`
- `failed: bool`
- `failure_code: str | None`

**Validation rules**:
- `failed=True` for pre_hook rejection, handler exception, handler contract violation, and standardized error results.
- Batch cascade uses `failed`, not keyword matching and not the final post_hook-rewritten text.
- `ToolSignal` is only valid when the active `ToolDefinition.is_interrupting` is true.

## Migrated Gate Hooks

### builtin_general_tools pre_hooks

**Tools**:
- `read_file`
- `write_file`
- `edit_file`
- `list_dir`
- `exec`

**Rules**:
- File/dir existence and type rejections move to pre_hooks.
- System-directory write rejection moves to `write_file` pre_hook.
- User confirmation for `write_file`, `edit_file`, and non-safe `exec` moves to prehooks and continues to use existing `_ask_user_confirm`.
- Safe-command classification for `exec` moves to pre_hook.
- `edit_file` `old_text` target lookup and uniqueness validation remain in the handler as edit execution preparation.

### recording_data_tools pre_hooks

**Tools**:
- `query_data`
- `analyze_image`

**Rules**:
- `query_data` pre_hook rejects SQL that existing rewrite/filter policy rejects.
- The pre_hook does not add raw-text bans for harmless comments or semicolons inside string literals.
- `query_data` handler may still call `rewrite(sql)` to generate executable SQL.
- `analyze_image` pre_hook rejects more than 5 `action_index` values in a single call.

### trial_tools pre_hooks

**Tool**:
- `run_command`

**Rules**:
- Per-run counter is captured in `create_trial_tools()` closure.
- Count increments in pre_hook.
- The 6th call returns the existing limit error and skips handler.
