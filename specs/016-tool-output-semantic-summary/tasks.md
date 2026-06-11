# Tasks: Tool Output Semantic Summary

**Input**: `spec.md` and `plan.md`
**Worktree**: `E:\code\Exemplar\.worktrees\016-tool-output-semantic-summary`

## Phase 1: Tests and Configuration Foundation

- [X] T001 Add semantic-summary configuration dataclasses, unified getters, defaults, and config tests.
- [X] T002 Add dedicated keyring read/write/delete and read-only Real Grand Tour resolver tests.
- [X] T003 Add semantic summarizer unit tests for deterministic selection, redaction, goals, single call, Map-Reduce, partial failure, invalid JSON, and timeout.
- [X] T004 Add governance tests for trigger rules, reference reuse, legacy/custom results, visible caps, and deterministic fallback.

## Phase 2: Core Summary and Governance

- [X] T005 Implement `semantic_summary.py` deterministic extraction, sampling, prompt construction, provider calls, validation, and deadline handling.
- [X] T006 Extend health counters for summary attempts/outcomes/input characters.
- [X] T007 Refactor `output_governance.py` to govern all text results, reuse/create references first, preserve facts/preview, and attach optional semantic summaries.
- [X] T008 Pass tool arguments from `AgentLoop` into governance without changing tool execution semantics.
- [X] T009 Add `extractionGoal` schemas/ignored handler parameters and reference metadata for `load_tool_output`.
- [X] T010 Remove duplicate command-reference creation only where centralized governance now owns it, preserving handler truncation semantics.

## Phase 3: Settings and Provider Integration

- [X] T011 Add Tool Output settings section, advanced descriptors, status, validation, and dedicated secret handling.
- [X] T012 Add semantic-summary connection action with bounded provider call and sanitized response.
- [X] T013 Extend desktop API/TypeScript settings contracts and frontend advanced disclosure UI.
- [X] T014 Add backend settings/API/keyring tests and frontend Settings screen tests.
- [X] T015 Register summary model/credential callsites in Debug provider inventory and Real Grand Tour coverage.

## Phase 4: Integration and Guardrails

- [X] T016 Add AgentLoop single/multi-tool exactly-one pairing tests with summary success/failure.
- [X] T017 Add secret/prompt-injection/log/UI-event leak guards and post-restart reference recovery coverage.
- [X] T018 Add 100k, 1MB, over-artifact-limit, and second-stage `load_tool_output` output-cap tests.

## Phase 5: Documentation and Validation

- [X] T019 Update `docs/ARCHITECTURE.md`, `docs/PROJECT_CONSTRAINTS.md`, and `config.example.json`.
- [X] T020 Synchronize root, `src`, and `frontend` AGENTS/CLAUDE/GEMINI mirrors.
- [X] T021 Run focused backend tests and fix failures.
- [X] T022 Run frontend unit/lint tests and fix failures.
- [X] T023 Run related integration/guardrail regression tests and mark all completed tasks.
