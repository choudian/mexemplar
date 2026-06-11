# Feature Specification: Tool Output Semantic Summary

**Feature Branch**: `016-tool-output-semantic-summary`
**Created**: 2026-06-11
**Status**: Completed
**Input**: Add deterministic, recoverable, goal-aware semantic summaries for large text tool results while preserving exactly-one tool result pairing and authorized raw-output recovery.

## User Scenarios & Testing

### User Story 1 - Keep Large Tool Results Actionable (Priority: P1)

As an Agent, I need large or truncated tool results to retain verified facts and high-signal context so I can continue without scanning an unbounded payload.

**Independent Test**: Produce large success and failure outputs with important diagnostics at the beginning, middle, and end. The visible result stays bounded and contains deterministic `facts`, `preview`, raw size, payload keys, and a recoverable reference when storage permits.

**Acceptance Scenarios**:

1. Large legacy, custom, and upgraded text results are converted to one compact envelope after reaching the configured trigger.
2. Small legacy/custom results preserve their original format.
3. Existing raw references are reused instead of duplicated.
4. Governance, artifact, or summary failures still persist exactly one paired result.

### User Story 2 - Add Advisory Semantic Understanding (Priority: P1)

As an Agent, I need a concise semantic explanation of large output so I can understand findings, errors, important data, and likely next actions.

**Independent Test**: Exercise single-call and Map-Reduce paths with valid JSON, invalid JSON, provider failure, partial map failure, reduce failure, and total timeout.

**Acceptance Scenarios**:

1. Valid summaries use the fixed structure `overview`, `keyFindings`, `errors`, `importantData`, `nextActions`, `extractionGoal`, `coverage`, `mode`, and `advisory`.
2. Inputs above the configured maximum use bounded head/error/uniform/tail sampling.
3. Partial map success can reduce; total map failure, invalid output, reduce failure, and timeout deterministically omit `semanticSummary`.
4. Tool output is treated as untrusted data and cannot override the summary protocol.

### User Story 3 - Guide Extraction Toward the Current Task (Priority: P2)

As an Agent, I need summaries to focus on the reason I called the tool.

**Independent Test**: Call supported built-ins with `extractionGoal`, call `web_fetch` with `prompt`, and invoke custom tools with common goal/query/prompt/pattern arguments.

**Acceptance Scenarios**:

1. `exec`, `read_file`, `search_files`, `search_content`, `process_logs`, `process_wait`, and `load_tool_output` accept an optional `extractionGoal` of at most 1000 characters.
2. `web_fetch.prompt` is reused as the extraction goal.
3. Custom tools conservatively infer a goal from common argument names without changing handler arguments or permission behavior.

### User Story 4 - Configure a Separate Low-Cost Summary Model (Priority: P2)

As a user, I need a dedicated Tool Output settings section so semantic summaries can use an independent provider, model, endpoint, temperature, secret, and advanced budgets.

**Independent Test**: Load the settings schema, save values, write/delete the dedicated secret, run connection validation, and verify the frontend shows masked secret state and actionable failures.

**Acceptance Scenarios**:

1. Summary configuration lives under `agent_tools.output.semantic_summary.*`.
2. The API key is stored only in keyring as `tool_output_summary_api_key`.
3. Empty model, missing secret, disabled feature, or invalid compatible endpoint degrades without a provider call.
4. The connection action returns only status plus provider/model metadata, never model output.

## Requirements

### Functional Requirements

- **FR-001**: Governance MUST process every text tool result while preserving exact small legacy/custom output.
- **FR-002**: Compaction MUST trigger when raw text reaches `trigger_chars`, `limits.truncated` is true, a raw reference already exists, or handler metadata reports clipping/truncation.
- **FR-003**: Governance MUST preserve deterministic `preview`, `facts`, `rawChars`, `originalPayloadKeys`, and authorized references independently of LLM availability.
- **FR-004**: Raw output MUST be persisted before semantic summarization when no reusable reference exists and artifact limits allow it.
- **FR-005**: Semantic summary failure MUST remove `semanticSummary` rather than replacing deterministic facts or creating another tool result.
- **FR-006**: Semantic model input and output MUST be redacted, bounded, and treated as untrusted data.
- **FR-007**: Inputs above `max_input_chars` MUST use the 15% head, 35% error context, 35% uniform sample, and 15% tail selection budget.
- **FR-008**: Map-Reduce MUST honor configured chunk size, map count, concurrency, token budgets, and total timeout without business-layer retries.
- **FR-009**: The semantic result MUST be advisory and MUST NOT override verified facts.
- **FR-010**: Extraction goals MUST influence summary prompts only and MUST NOT change execution, permissions, or handler semantics.
- **FR-011**: Summary settings and all advanced limits MUST use `get_unified_config()`.
- **FR-012**: The dedicated summary API key MUST use keyring and MUST NOT fall back to plaintext configuration.
- **FR-013**: Supported providers MUST include Anthropic, OpenAI, DeepSeek, Qwen, Zhipu, Moonshot, and custom OpenAI-compatible endpoints.
- **FR-014**: Runtime health counters MUST cover attempts, successes, timeouts, partial summaries, invalid summaries, map/reduce failures, and input characters.
- **FR-015**: New provider callsites MUST be registered in Debug provider inventory and Real Grand Tour credential/budget coverage with trace source `tool_output_summary`.
- **FR-016**: No database migration is introduced; summaries remain part of persisted tool-result messages and raw output remains owned by `ToolOutputRepository`.

## Architecture Impact

- [x] **UI**: Settings section, advanced disclosure, masked secret, connection action.
- [x] **Desktop API Bridge**: Existing generic settings contracts gain one section and descriptor metadata.
- [x] **Business**: Output governance, semantic summarizer, settings services/actions.
- [ ] **Execution**: No execution semantics change.
- [x] **Data**: Unified config and keyring helpers only; no migration.
- [ ] **Recording**: No change.
- [x] **Utils**: Health counters.

## Success Criteria

- **SC-001**: 100k, 1MB, and over-artifact-limit fixtures always produce visible output within the configured cap.
- **SC-002**: Diagnostics placed at the start, middle, or end are retained by deterministic preview/facts fixtures.
- **SC-003**: Every success, failure, invalid summary, timeout, and fallback fixture persists exactly one result per tool call.
- **SC-004**: Raw secrets do not appear in semantic prompts, summaries, ordinary logs, UI events, or visible compact envelopes.
- **SC-005**: Existing references are reused and remain loadable after repository re-instantiation.
- **SC-006**: Backend settings, keyring, connection action, frontend save/delete/test, and error-display tests pass.
