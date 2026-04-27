# Contract: Tool Hook Protocol

This is an internal Python API contract for `src/business/agents`.

## Type Contract

```python
@dataclass(frozen=True)
class ToolCallContext:
    tool_name: str
    args: Mapping[str, Any]
    session_id: str
    agent_type: AgentType | str
    iteration: int


@dataclass(frozen=True)
class PreHookResult:
    error: str | None = None


@dataclass(frozen=True)
class PostHookResult:
    result: str | None = None


PreHook = Callable[[ToolCallContext], PreHookResult | None]
PostHook = Callable[[ToolCallContext, str], PostHookResult | None]


@dataclass
class ToolDefinition:
    name: str
    schema: dict[str, Any]
    handler: Callable[..., str | ToolSignal]
    is_interrupting: bool = False
    pre_hook: PreHook | None = None
    post_hook: PostHook | None = None


@dataclass
class AgentConfig:
    ...
    global_pre_hooks: list[PreHook] = field(default_factory=list)
    global_post_hooks: list[PostHook] = field(default_factory=list)
```

## Execution Order

For a `ToolDefinition` tool call:

```text
tool pre_hook
-> AgentConfig.global_pre_hooks in list order
-> handler
-> tool post_hook
-> AgentConfig.global_post_hooks in list order
```

AgentLoop injected `load_reference` and `talk_to_user` are excluded from hook execution. They may still appear in AgentLoop's internal tool registry for existing batch classification and solo-interrupt behavior.

## Batch Integration Contract

- AgentLoop classifies the full tool-call batch by current `ToolDefinition.is_interrupting` before running any hook or handler.
- Invalid mixed interrupting batches write `invalid_model_output` results and run no hooks or handlers.
- Unknown tools and `not_executed` results are AgentLoop control errors and run no hooks.
- In a valid ordinary batch, every executable ordinary tool call runs the hook chain independently and in original order.
- `PreHookResult(error=...)`, handler exception, handler contract violation, and standardized error results are reliable failures for batch cascade; later calls in the same ordinary batch receive `not_executed`.
- Batch failure detection uses the original execution outcome, not plain-text keyword matching and not a post_hook rewrite that masks the original failure.
- A legal solo interrupting call may run pre_hooks, then its handler. A successful `ToolSignal` skips post_hooks and preserves existing AgentResult behavior.
- Interrupting handler exception or return-type mismatch writes a standardized failure result and does not trigger pause/complete semantics.

## Args Contract

- `ctx.args` is a recursive read-only isolation view of LLM original arguments.
- Hook attempts to mutate top-level mapping entries must raise.
- Hook attempts to mutate nested dict/list data must raise.
- Handler receives the original LLM arguments unaffected by hook mutation attempts.
- No hook result can rewrite handler arguments.

## PreHook Result Contract

| PreHook outcome | Handler runs? | Remaining pre_hooks? | PostHooks run? | Tool result |
|-----------------|---------------|----------------------|----------------|-------------|
| `None` or `PreHookResult(error=None)` | Continue chain | Yes | If handler produces normal string | Handler/post result |
| `PreHookResult(error="...")` | No | No | No | Error string |
| Raises exception | Yes | No | No | Handler original result or handler exception error string |

## Handler Result Contract

| Handler outcome | PostHooks run? | Tool result |
|-----------------|----------------|-------------|
| Ordinary tool returns `str` | Yes, unless pre_hook exception already skipped them | Last post_hook rewrite or original string |
| Interrupting tool returns `ToolSignal` | No | Original `ToolSignal` |
| Ordinary tool returns `ToolSignal` | No | `handler_contract_violation` standardized error |
| Interrupting tool returns `str` | No | `handler_contract_violation` standardized error |
| Ordinary handler raises exception | Yes, unless pre_hook exception already skipped them | Standardized error string, optionally rewritten for final display while preserving failure status |
| Interrupting handler raises exception | No | `handler_exception` standardized error |

The handler exception error string must not propagate as a Python exception to the AgentLoop while loop.

## PostHook Result Contract

| PostHook outcome | Remaining post_hooks? | Tool result candidate |
|------------------|-----------------------|-----------------------|
| `None` or `PostHookResult(result=None)` | Yes | Existing candidate |
| `PostHookResult(result="...")` | Yes | Replace final candidate; later non-None rewrites may override |
| Raises exception | No | Handler original string result |

All post_hooks receive the handler original string result, not the previous post_hook rewrite.

## Dynamic Tool Contract

For `AgentLoop.run(..., tools=callable)`:

- The callable is evaluated each iteration.
- Tool schemas may remain cached while the set of tool names is unchanged.
- The execution map of handler/pre_hook/post_hook and the classification metadata including `is_interrupting` must refresh from the latest `ToolDefinition` objects every iteration.
- If a tool keeps the same name but replaces handler, hook, or `is_interrupting`, the next tool call must use the replacement.

## Migrated Gate Contract

### builtin_general_tools

- `read_file`: path existence and file-type rejection happen in pre_hook.
- `write_file`: system-directory rejection and user confirmation happen in pre_hook.
- `edit_file`: path existence/type rejection and user confirmation happen in pre_hook; `old_text` target lookup and uniqueness validation remain in the handler as edit execution preparation.
- `list_dir`: path existence and directory-type rejection happen in pre_hook.
- `exec`: safe-command classification and user confirmation happen in pre_hook.

### recording_data_tools

- `query_data`: existing SQL rewrite/filter policy is invoked in pre_hook for rejection; harmless comments and semicolons inside string literals are not rejected by raw text scan. Handler may invoke rewrite again to get executable SQL.
- `analyze_image`: single-call max 5 `action_index` gate happens in pre_hook.

### trial_tools

- `run_command`: per-run max 5 attempts gate happens in a pre_hook closure created by `create_trial_tools()`.

## Required Test Evidence

- No-hook `ToolDefinition` behavior remains unchanged.
- Tool pre and global pre execute before handler in order.
- Tool post and global post execute after handler in order.
- PreHook error skips handler/post.
- PreHook exception runs handler and skips post.
- Ordinary handler exception is converted to a standardized error string and reaches post_hook while preserving failure status.
- Legal interrupting `ToolSignal` skips post_hook.
- Recursive `ctx.args` write attempts raise and do not affect handler args.
- Callable tool factory same-name handler/hook/`is_interrupting` replacement takes effect on next iteration.
- Ordinary multi-tool batches preserve 003 behavior: hook rejection or handler failure cascades `not_executed` to later calls.
- Invalid mixed interrupting batches run no hooks or handlers.
- Solo interrupting `ToolSignal` preserves existing AgentResult behavior and skips post_hook.
- Migrated gate paths reject before handler invocation.
- A full no-op chain of tool pre + global pre + tool post + global post stays within the 5 ms overhead budget.
- A new global pre_hook can be mounted without changing any tool handler or AgentLoop engine code and within the SC-005 line budget.
- Non-migrated boundaries remain outside hook migration: `programmer_tools.syntax_check`, `recording_data_tools.execute_code` sandboxing, `tool_executor` venv isolation/command whitelist, and `dynamic_tool_manager` discovery/activation rules.
