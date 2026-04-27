# Implementation Plan: 工具执行 Pre/Post Hook 系统

**Branch**: `002-tool-hook-system` | **Date**: 2026-04-26 | **Spec**: `specs/002-tool-hook-system/spec.md`
**Input**: Feature specification from `specs/002-tool-hook-system/spec.md`

**Note**: This plan is filled by `/speckit.plan` and stops after Phase 2 planning. `tasks.md` is generated later by `/speckit.tasks`.

## Summary

在现有 `ToolDefinition` 工具执行路径上新增同步 pre/post hook 协议：`pre_hook` 只负责放行、拒绝、观测，不改写 handler 入参；`post_hook` 可改写普通字符串结果但不处理合法 `ToolSignal`。实现集中在业务层 Agent 运行时与工具定义，不新增配置项、持久化表、UI 或事件。当前 AgentLoop 已有多工具批处理与 `is_interrupting` 分类，hook 必须挂在批处理验证之后、实际 handler 执行之前/之后，不能破坏混合中断批次拒绝、失败级联和单中断语义。被迁移的门卫式校验从 `builtin_general_tools`、`recording_data_tools`、`trial_tools` 的 handler 中前移到 hook，同时保持 handler 执行必需的解析、规范化、查询准备与结果转换。

## Technical Context

**Language/Version**: Python 3.11+ 项目，当前运行时面向 Python 3.12  
**Primary Dependencies**: 现有 dataclasses / typing / pathlib / logging；现有 PyQt6、DuckDB、sqlglot、blinker、LangChain、pytest 继续沿用；本 feature 不新增第三方依赖  
**Storage**: N/A；不新增 SQLite、DuckDB、配置文件、迁移或 keyring 字段  
**Testing**: `uv run python -m pytest ...`，新增 `tests/test_hook_protocol.py`，并复用录制数据过滤 guard/回归测试；交付前运行 `uv run black --check src tests` 与 `uv run flake8 src tests`，或在计划/交付说明中记录明确例外  
**Target Platform**: Windows 优先的桌面应用运行环境，保持现有跨平台路径检查语义  
**Project Type**: Python desktop app 的业务层 Agent runtime / internal library change  
**Performance Goals**: 单次工具调用挂载工具 pre + 1 个 global pre + 工具 post + 1 个 global post 的额外开销不超过 5 ms；无 hook 工具路径保持近似现状  
**Constraints**: 同步 handler 不改异步；pre/post 链不做 args/result 流水线；`ToolCallContext.args` 递归只读隔离；AgentLoop 内建 `talk_to_user` / `load_reference` 不进 hook 管线；callable 动态工具路径每轮刷新执行映射与 `is_interrupting` 分类元数据；保留 003 多工具批处理语义  
**Scale/Scope**: 覆盖所有经 `ToolDefinition` 进入 AgentLoop 的 PM / Programmer / Trial / Assistant 工具；迁移 5 个 builtin general 工具、`query_data`、`analyze_image`、`run_command` 的门卫式校验

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate result | Evidence |
|-----------|-------------|----------|
| I. Layered Boundaries & Event Coordination | PASS | 只改业务层 `src/business/agents/**` 与业务层测试；不新增 UI、执行层反调、数据层反调或 blinker 事件。用户确认继续复用 `builtin_general_tools` 现有 helper，不把 UI 回调塞进通用 context。 |
| II. Data Boundary & Persistence Discipline | PASS | 不新增 SQLite/DuckDB schema、Repository、迁移或业务 SQL。`query_data` 仍经 `rewrite()` / DuckDBManager / 过滤边界，handler 可保留执行必需的 `rewrite(sql)` 以生成实际执行 SQL。 |
| III. Unified Config & Secret Handling | PASS | 不新增运行时配置、密钥或示例配置字段；hook 挂载在 `AgentConfig` 构造期固定，不通过 unified_config 热改。 |
| IV. Verifiable Delivery | PASS | 新增 hook 协议单元测试、动态 callable 工具链路烟测、无 hook 透明性回归、ToolSignal/post_hook guard、多工具批处理兼容测试、迁移后门卫校验覆盖、SC-005 挂载成本验证、非迁移边界 guard、静态 guard 检查旧拒绝判断不残留，并在交付前运行 black/flake8 gate。 |
| V. Living Docs & Spec-Driven Delivery | PASS | 生成本计划、research/data-model/contracts/quickstart；实现后更新 `docs/ARCHITECTURE.md` 与 `docs/PROJECT_CONSTRAINTS.md` 中的 Agent tool hook 约束，`AGENTS.md` 的 Speckit 指向在本计划阶段更新。 |

No constitution violations. Complexity Tracking remains empty.

## Project Structure

### Documentation (this feature)

```text
specs/002-tool-hook-system/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── tool-hook-protocol.md
└── tasks.md              # generated later by /speckit.tasks
```

### Source Code (repository root)

```text
src/business/agents/
├── agent_loop.py                 # inject hook execution into batch/solo-interrupt ToolDefinition execution
├── config.py                     # extend ToolDefinition and AgentConfig while preserving is_interrupting
├── hook_models.py                # new hook protocol dataclasses/types and args freezing helper
├── builtin_tools.py              # built-in AgentLoop injected tools remain excluded
└── tools/
    ├── builtin_general_tools.py  # migrate read/write/edit/list/exec gate checks into pre_hooks
    ├── recording_data_tools.py   # migrate query_data/analyze_image gate checks into pre_hooks
    └── trial_tools.py            # migrate run_command attempt limit into per-run pre_hook closure

docs/
├── ARCHITECTURE.md               # update runtime AgentLoop tool execution description
└── PROJECT_CONSTRAINTS.md        # document hook boundaries and no-args-pipeline constraint

tests/
├── test_hook_protocol.py         # new focused protocol and migration tests
├── integration/
│   ├── test_agent_loop_multi_tool_calls.py
│   └── test_assistant_new_session.py
└── recording/
    ├── test_recording_data_tools_noise_filtering.py
    └── filtering/test_recording_tools_no_sqlglot.py
```

**Structure Decision**: keep the protocol inside `src/business/agents/` because hook execution is part of Agent runtime, not UI, data, or execution sandbox. Add one new module (`hook_models.py`) for protocol types/helpers to avoid bloating `config.py`; extend `config.py` only where the public dataclasses need new fields.

## Phase 0: Research

Research output: `specs/002-tool-hook-system/research.md`

Decisions resolved:
- Hook protocol location and dependency shape
- Recursive read-only `ToolCallContext.args` implementation strategy
- Handler exception, hook exception, `ToolSignal`, and post_hook execution matrix
- Dynamic callable tool mapping refresh strategy
- Multi-tool batch, failure cascade, and `is_interrupting` compatibility
- Migration boundaries for existing handler gate logic

## Phase 1: Design & Contracts

Design outputs:
- `specs/002-tool-hook-system/data-model.md`
- `specs/002-tool-hook-system/contracts/tool-hook-protocol.md`
- `specs/002-tool-hook-system/quickstart.md`
- `AGENTS.md` Speckit plan pointer updated

Core design:
1. Add `ToolCallContext`, `PreHookResult`, `PostHookResult`, `PreHook`, `PostHook`, and a recursive args-freezing helper in `hook_models.py`.
2. Extend `ToolDefinition` with optional `pre_hook` / `post_hook` while preserving existing `is_interrupting`; extend `AgentConfig` with `global_pre_hooks` / `global_post_hooks` using `default_factory=list`.
3. Route `_execute_tool_batch()` and `_execute_solo_interrupt()` through hook-aware per-call execution that receives the current `ToolDefinition`, `session_id`, and `iteration`, executes hook chains in the specified order, and returns both final content and reliable failure/control-flow status for batch decisions.
4. For callable tools, rebuild execution mapping and `_current_tool_defs` metadata every iteration while retaining schema rebuild only when tool names change.
5. Exclude AgentLoop injected `talk_to_user` / `load_reference` from hook execution while keeping the metadata required for existing batch classification and solo-interrupt behavior.
6. Move gate-style rejection, confirmation, rate-limit, and security-policy decisions into pre_hooks while leaving handler execution prep and result conversion in place; for `edit_file`, keep `old_text` target lookup and uniqueness validation in the handler as execution prep.

### Post-Design Constitution Check

| Principle | Gate result | Evidence |
|-----------|-------------|----------|
| I. Layered Boundaries & Event Coordination | PASS | Design remains business-layer only; no event additions; no UI/data reverse dependency. |
| II. Data Boundary & Persistence Discipline | PASS | No persistence changes; DuckDB query execution keeps existing filtering/rewrite path. |
| III. Unified Config & Secret Handling | PASS | No runtime config or secrets. |
| IV. Verifiable Delivery | PASS | Contract maps directly to focused unit/guard tests in `tests/test_hook_protocol.py`, including full-chain overhead, global hook mounting cost, multi-tool batch compatibility, non-migration boundaries, and formatting/lint gates. |
| V. Living Docs & Spec-Driven Delivery | PASS | Plan artifacts and active-doc update targets are explicit. |

## Phase 2: Task Planning Scope

`/speckit.tasks` should generate dependency-ordered tasks for:
- protocol model/helper implementation
- AgentLoop execution-map, batch/solo-interrupt integration, and hook-chain changes
- tool module pre_hook migrations
- focused protocol/migration tests
- active docs updates
- final targeted test run, non-migration guard, SC-005 mounting-cost verification, static scans, `black --check`, and `flake8`

## Complexity Tracking

No constitution violations or complexity exceptions.
