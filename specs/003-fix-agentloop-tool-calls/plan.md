# Implementation Plan: AgentLoop 多工具调用结果配对修复

**Branch**: `003-fix-agentloop-tool-calls` | **Date**: 2026-04-25 | **Spec**: [spec.md](spec.md) | **Status**: Completed
**Input**: Feature specification from `specs/003-fix-agentloop-tool-calls/spec.md`

## Summary

修复 AgentLoop 对模型返回多个 tool call 的历史配对缺陷：同一轮普通工具调用按顺序执行并逐一保存结果；普通工具失败后停止后续真实执行并写入未执行结果；中断型工具与其他工具混合时保存原响应并为每个 tool call 写入非法输出错误结果；恢复路径按原始顺序补齐缺失结果。新增声明式中断型工具分类（`ToolDefinition.is_interrupting`），运行时强校验声明与 handler 返回类型一致，不一致按标准化错误结构处理。核心变更落在 Agent 运行循环、会话消息恢复逻辑和行为测试，不新增用户可见工具、配置或数据表。

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: LangChain message/tool-call abstraction, SQLAlchemy-backed SQLite repositories, existing AgentLoop / ToolDefinition / ToolSignal classes
**Storage**: SQLite message/session records through existing Repository APIs; no schema migration expected
**Testing**: pytest with in-memory SQLite fixture and MockLLMClient; targeted integration tests under `tests/integration/`
**Target Platform**: Existing Mexemplar desktop runtime on Windows/Linux
**Project Type**: Single-project desktop app with business-layer Agent runtime
**Performance Goals**: No extra LLM request for a valid multi-tool ordinary batch; execution overhead scales linearly with tool_call count in the current response
**Constraints**:
- Provider-facing history must never contain an assistant tool_call without a matching tool result after AgentLoop finishes a processing step
- Unknown tools, handler exceptions, standardized error structures, and handler contract violations are the only reliable ordinary-tool failure triggers
- Plain text containing "错误" or `error` is not failure by itself
- Interrupting tools are classified by `ToolDefinition.is_interrupting` before any handler runs; classification must agree with handler return type at execution time
- Solo interrupting tool handler exceptions and contract violations follow ordinary-failure semantics (continue loop, not terminate)
- No new config keys, secrets, events, SQLite schema, or DuckDB reads
**Scale/Scope**: Tool-call batches are per single model response; tests cover 2-3 tool calls plus recovery/invalidation/contract-violation cases, while implementation must preserve order for any returned list length

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate question | Evidence required |
|-----------|---------------|-------------------|
| I. Layered Boundaries & Event Coordination | Does the design preserve `UI -> business -> execution -> data/driver` direction, and are all cross-module notifications routed through `src/utils/events.py`? | Touched layers: `src/business/agents/`, `src/business/memory/`, existing `src/data/repositories` usage. No UI changes, no new events, no lower-layer reverse calls. |
| II. Data Boundary & Persistence Discipline | Are SQLite and DuckDB responsibilities explicit, are Repository boundaries preserved, and do `network_requests` reads keep filtering/desensitization contracts? | SQLite message history remains accessed through `ContextManager`/`MessageRepository`; no raw business SQL planned. DuckDB and `network_requests` are not touched. |
| III. Unified Config & Secret Handling | Do all new settings flow through `UnifiedConfigManager`, and do all secrets stay out of code/config files? | No new settings or secrets. Existing `UnifiedConfigManager` use remains for ContextManager construction. |
| IV. Verifiable Delivery | Does the plan include automated coverage for deterministic logic plus wiring smoke/guard tests for architecture rewires? | Add deterministic AgentLoop integration tests for: ordered multi-tool execution; invalid mixed/multi-interrupt responses; failure stop/not-executed semantics; handler contract violation (both directions); solo interrupt handler exception; recovery partial results; missing handler recovery; plain-text not-failure; single-tool regression. Guard assertion: next LLM messages have no unmatched tool calls. |
| V. Living Docs & Spec-Driven Delivery | Are required active docs identified for update, and are temporary notes confined to `docs/local/`? | Update `docs/design/agent_loop_design.md`, `docs/ARCHITECTURE.md`, and this worktree's `AGENTS.md` plan pointer. `docs/PROJECT_CONSTRAINTS.md` is referenced by AGENTS but is not present in this checkout, so it is not listed as an editable target. |

**Gate result**: PASS. No constitution exception required.

## Project Structure

### Documentation (this feature)

```text
specs/003-fix-agentloop-tool-calls/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   └── agentloop-multi-tool-call-contract.md
├── checklists/
│   └── requirements.md
└── tasks.md             # Created by /speckit-tasks, not by this command
```

### Source Code (repository root)

```text
src/
├── business/
│   ├── agents/
│   │   ├── config.py                    # add is_interrupting to ToolDefinition
│   │   └── agent_loop.py                # multi-tool batch processing, failure policy, ToolSignal policy, contract validation
│   ├── ai/
│   │   └── llm_client.py                # preserve/expose full tool_calls; logging may be adjusted
│   └── memory/
│       └── context_manager.py           # pending unmatched tool-call recovery across multi-call responses
└── data/
    └── repositories/                    # existing MessageRepository access only, no schema change expected

tests/
├── integration/
│   └── test_agent_loop_multi_tool_calls.py
└── conftest.py                          # reuse MockLLMClient; may extend capturing helper if needed

docs/
├── ARCHITECTURE.md
└── design/
    └── agent_loop_design.md
```

**Structure Decision**: Keep the fix in the existing Agent runtime boundaries. AgentLoop owns execution sequencing, ToolSignal handling, and handler contract validation; ContextManager owns message-history inspection/recovery; LLMClient continues to normalize provider messages without enforcing business policy. Tests use in-memory SQLite and mock LLM responses to verify persisted history and the messages passed to subsequent LLM calls.

## Phase 0 Status

`research.md` contains 10 decisions:
1. AgentLoop treats one model response as an ordered tool-call batch
2. Any multi-tool response containing an interrupting tool is invalid model output (includes multi-interrupt)
3. Ordinary-tool failures stop later real execution
4. Failure detection must be structural, not keyword-based
5. Recovery resumes missing pairings, not just the first tool call
6. No schema, config, or user-facing tool changes
7. Interrupting tools are classified declaratively on `ToolDefinition`
8. `not_executed` and `invalid_model_output` results reuse the standardized error structure
9. `is_interrupting` and handler return type must be strongly consistent
10. Solo interrupt-tool handler exceptions follow ordinary-failure semantics

## Phase 1 Status

Generated artifacts:
- `data-model.md`: message pairing entities, state transitions (with pre-execution classification, contract violation paths, and solo-interrupt exception handling)
- `contracts/agentloop-multi-tool-call-contract.md`: AgentLoop behavior contract covering batch classification, ordinary batch, solo interrupt, invalid output, handler contract consistency, and recovery
- `quickstart.md`: targeted validation path and expected scenarios

## Post-Design Constitution Re-check

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Layered Boundaries & Event Coordination | PASS | No new events; UI/orchestrator result contract preserved. |
| II. Data Boundary & Persistence Discipline | PASS | Existing repositories only; no raw SQL or DuckDB impact. |
| III. Unified Config & Secret Handling | PASS | No config or secret change. |
| IV. Verifiable Delivery | PASS | Test targets enumerate deterministic runtime and recovery branches including contract violation and solo-interrupt exception paths. |
| V. Living Docs & Spec-Driven Delivery | PASS | Active design/runtime docs and AGENTS plan pointer identified. |

## Complexity Tracking

> No constitution violations. No complexity exception required.
> FR-014 through FR-016 add `ToolDefinition.is_interrupting`, standardized error content for AgentLoop-emitted results, and handler contract validation — these are additive constraints on existing dataclass/loop logic, not new infrastructure.
