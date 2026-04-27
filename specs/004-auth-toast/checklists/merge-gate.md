# Merge Gate Checklist: 高危操作确认 Toast 化（Auth Toast）

**Purpose**: Release gate — validate that all requirements artifacts are consistent, complete, and constitution-compliant before merge
**Created**: 2026-04-27
**Feature**: [spec.md](../spec.md)

**Depth**: Release Gate (合并门禁)
**Focus**: 全维度 — UX 需求质量、并发/线程安全、安全/脱敏、架构合规、文档一致性
**Actor**: Reviewer (PR merge decision)

## Spec ↔ Implementation Alignment

- [ ] CHK001 Are the spec's Key Entity names (AuthConfirmationRequest, AutoApproveScope, AuthToastQueue) reconciled with the code's actual names (PendingConfirmation, module-level variables, inline deque), so a reviewer can trace each spec entity to its implementation? [Traceability, Spec §Key Entities, data-model.md]
- [ ] CHK002 Are the confirmation decision enum values in contracts/auth-confirmation-ui.md (accepted, rejected, timeout, auto_approved, confirm_error) consistent with the code's CONFIRM_DECISION_* constants and the spec's FR-015? [Consistency, contracts/auth-confirmation-ui.md §Logging Contract]
- [ ] CHK003 Are the confirmation source enum values in the contracts doc consistent with the code's CONFIRM_SOURCE_* constants, including `new_chat_reset` used in settle calls? [Consistency, contracts/auth-confirmation-ui.md §Business Result API]
- [ ] CHK004 Is `new_chat_reset` documented as an expected source in the Business Result API table, or only implicitly referenced via the Auto-Approve Scope API? [Completeness, contracts/auth-confirmation-ui.md]
- [ ] CHK005 Does data-model.md's AutoApproveScope entity match the implementation's actual fields — specifically, the `session_id` field is in data-model but absent from code? [Consistency, data-model.md, Spec §Key Entities]

## Requirement Traceability

- [ ] CHK006 Can each of the 17 functional requirements (FR-001 through FR-017) be traced to at least one task ID in tasks.md? [Traceability, tasks.md]
- [ ] CHK007 Can each of the 7 success criteria (SC-001 through SC-007) be traced to at least one task that implements or tests it? [Traceability, tasks.md]
- [ ] CHK008 Are the three user stories (US1/US2/US3) each traceable to a distinct phase in tasks.md with independent validation checkpoints? [Traceability, tasks.md §Phase Dependencies]
- [ ] CHK009 Are Phase 6 guard/regression tasks (T032-T033) explicitly linked back to FR-014 (no impact on PM/Trial/ToolExecutionDialog)? [Traceability, Spec §FR-014, tasks.md §Phase 6]

## Constitution Compliance (Merge Gate)

- [ ] CHK010 Is the layered dependency direction preserved with no evidence of business importing UI, or UI importing data/Repository? [Constitution I, Spec §Layer Impact, Plan §Constitution Check]
- [ ] CHK011 Is there confirmation that no new cross-module blinker events were introduced — the feature uses intra-UI signals and function calls only? [Constitution I, Spec §Event Impact, Plan §Structure Decision]
- [ ] CHK012 Is there confirmation that no SQLite/DuckDB migrations, Repository changes, or raw SQL were introduced? [Constitution II, Spec §Data Store Impact]
- [ ] CHK013 Is there confirmation that no new config keys or secrets were introduced (auto-approve is session memory only)? [Constitution III, Spec §Data Store Impact, Spec §Constraints]
- [ ] CHK014 Are there automated tests for deterministic logic (confirmation state, queue, auto-approve, logging) AND wiring smoke/guard tests for the QMessageBox removal? [Constitution IV, Plan §Constitution Check, tasks.md §Phase 6]
- [ ] CHK015 Are AGENTS.md and docs/PROJECT_CONSTRAINTS.md updated to reflect the new confirmation UX? [Constitution V, tasks.md §T034, §T035]

## UX Requirements Quality

- [ ] CHK016 Is the non-blocking requirement (FR-002) specified with a measurable interaction delay threshold matching SC-001's ≤100ms? [Clarity, Spec §FR-002, Spec §SC-001]
- [ ] CHK017 Are the three button semantics ("全部允许"/"同意"/"拒绝") defined with non-overlapping scope: single-request vs current+future-session? [Clarity, Spec §FR-004, §FR-005, §FR-006, §FR-007]
- [ ] CHK018 Is the "visible cue" for auto-approve mode (FR-013) defined with concrete observable properties (toggle text, highlight color, property name) rather than just "可见提示"? [Measurability, Spec §FR-013, tasks.md §T030]
- [ ] CHK019 Is the manual-close prohibition (FR-016) specified for both close-button AND outside-click dismissal, leaving no ambiguity about what "关闭" means? [Completeness, Spec §FR-016, Spec §Edge Cases]
- [ ] CHK020 Are ordinary Toast and auth Toast coexistence requirements (FR-012) specified with enough detail to verify independent lifecycle management? [Completeness, Spec §FR-012, Spec §Edge Cases]

## Concurrency & Thread Safety Requirements

- [ ] CHK021 Is the FIFO queue ordering requirement (FR-011) specified as a strict guarantee or a best-effort policy? [Clarity, Spec §FR-011, Spec §SC-005]
- [ ] CHK022 Is the timeout convergence requirement (SC-006: UI-Worker diff ≤1s) specified with a clear mechanism — does the UI timer derive from the same source as the Worker timeout? [Clarity, Spec §SC-006, Spec §CC-003, Spec §FR-010]
- [ ] CHK023 Are requirements for the `_confirm_lock` scope explicit about which operations are atomic, especially for settle_pending_confirmations iterating over the pending dict? [Completeness, contracts/auth-confirmation-ui.md, data-model.md]
- [ ] CHK024 Is the "no request lost" requirement (FR-011/SC-005) defined for both normal FIFO processing and the auto-approve drain path? [Coverage, Spec §FR-007a, Spec §FR-011]

## Security & Sanitization Requirements

- [ ] CHK025 Are redaction requirements for structured logs specified per tool (write_file, edit_file, exec) with concrete field-level allowlists, not just "MUST NOT log full content"? [Clarity, Spec §FR-015, Plan §Implementation approach]
- [ ] CHK026 Is the sanitization boundary for summary truncation defined with specific character thresholds and fallback behavior? [Measurability, Spec §FR-003, data-model.md]
- [ ] CHK027 Are the sensitive pattern redaction rules (API keys, passwords, tokens, secrets) documented in the requirements, or are they purely implementation details not traceable to any spec section? [Completeness, Spec §FR-015]
- [ ] CHK028 Is the auto-approve session-memory-only constraint documented as a hard requirement across spec, plan, AND contracts? [Consistency, Spec §FR-008, Spec §Data Store Impact, contracts/auth-confirmation-ui.md §Auto-Approve Scope API]

## Edge Case & Boundary Requirements

- [ ] CHK029 Is the behavior when multiple confirmations arrive simultaneously specified: FIFO sequential display only, or could parallel display be acceptable? [Clarity, Spec §FR-011, Spec §Edge Cases]
- [ ] CHK030 Is the new-chat settlement boundary (FR-017) defined with a monotonic timestamp cutoff so late-arriving old-session signals are deterministically rejected? [Completeness, Spec §FR-017, Plan §Implementation approach]
- [ ] CHK031 Are requirements for Toggle-off-while-toast-visible explicit about whether the currently visible confirmation is affected (FR-009 says "后续" — is the active one included)? [Clarity, Spec §User Story 3, Spec §FR-009]
- [ ] CHK032 Is the assumption that `_CONFIRM_TIMEOUT = 120s` remains unchanged documented as a stability requirement for this feature? [Assumption, Spec §Assumptions, Plan §Technical Context]

## Documentation Completeness

- [ ] CHK033 Is contracts/auth-confirmation-ui.md complete for all decision sources, including `system_error` and `new_chat_reset` which appear in code but may be absent from the Business Result API table? [Completeness, contracts/auth-confirmation-ui.md]
- [ ] CHK034 Does data-model.md reflect the actual implemented state transitions, including the `new_chat_reset` settlement path? [Consistency, data-model.md, Plan §Phase 1 Design]
- [ ] CHK035 Is the spec's "Architecture Impact" section still accurate after implementation — specifically the claim that Execution/Data/Recording layers are unaffected? [Consistency, Spec §Architecture Impact]
- [ ] CHK036 Are all unchecked items from the pre-implementation state-nfr.md checklist resolved or explicitly carried forward with justification? [Traceability, state-nfr.md]

## Final Gate

- [ ] CHK037 Has T038 (black/flake8 lint) been completed or its exception documented in the PR? [Dependency, tasks.md §T038]
- [ ] CHK038 Are the `__all__` exports in builtin_general_tools.py consistent with the contracts doc's public API surface? [Consistency, contracts/auth-confirmation-ui.md]
