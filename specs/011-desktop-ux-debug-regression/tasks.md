# Tasks: Desktop UX, Debug Inspector, and Grand Tour Acceptance

**Input**: Design documents from `specs/011-desktop-ux-debug-regression/`
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/`
**Tests**: Required by the feature specification. Test tasks appear before implementation tasks in each user story.
**Organization**: Tasks are grouped by user story so each slice can be implemented and validated independently.

## Phase 1: Setup (Shared Scaffolding)

**Purpose**: Create missing files/directories needed by later story tasks without implementing behavior. US1 only depends on the long-paste fixture scaffold (T001); debug and real-tour scaffolds are story-local setup and must not block the P1 composer MVP.

- [x] T001 Create shared long-paste fixtures in frontend/tests/fixtures/longPasteFixtures.ts
- [x] T002 [P] Create debug package marker in src/business/debug/__init__.py
- [x] T003 [P] Create debug API router scaffold in src/desktop_api/routers/debug.py
- [x] T004 [P] Create typed debug API client scaffold in frontend/src/api/debug.ts
- [x] T005 [P] Create hidden debug screen scaffold in frontend/src/screens/debug/DebugScreen.tsx
- [x] T006 [P] Create real Grand Tour runtime helper scaffold in frontend/tests/e2e/helpers/real-grand-tour-runtime.ts
- [x] T007 [P] Create provider inventory scaffold in tests/guardrails/debug_provider_inventory.json with a record schema for callsite, category, trace handling, real-tour provider handling, redaction handling, owner, out-of-scope/skip rationale, and verification status

**US1 independence note**: After T001 exists, US1 tasks T008-T019 may proceed and be validated without waiting for T002-T007, US2, or US3 scaffolding.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: No cross-story implementation prerequisite is required beyond story-local scaffolding. US1 can be delivered after T001 without debug or real-tour infrastructure; US2 and US3 define their own story-local foundations below.

**Checkpoint**: Setup ready. User story implementation can proceed by priority or by staffed slice.

---

## Phase 3: User Story 1 - Long Paste Keeps Chat Input Lightweight (Priority: P1) MVP

**Goal**: Assistant and Skill Teaching composers collapse qualifying text paste into a compact preview while preserving and sending the exact full draft.

**Independent Test**: Paste 7-line and 1201-code-unit fixtures into both composers, verify 6-line and 1200-code-unit boundary cases do not collapse unless the other threshold qualifies, include mixed newline and middle-selection paste, and verify preview controls, keyboard access, reset behavior, and exact sent content.

### Tests for User Story 1

- [x] T008 [P] [US1] Add paste qualification threshold boundary, mixed-newline counting, and selection-preservation hook tests in frontend/tests/unit/long-paste-hook.test.ts
- [x] T009 [P] [US1] Add Assistant composer long-paste RTL tests in frontend/tests/unit/assistant-long-paste.test.tsx
- [x] T010 [P] [US1] Add Teaching composer long-paste RTL tests in frontend/tests/unit/teaching-long-paste.test.tsx
- [x] T011 [P] [US1] Add controlled long-paste composer E2E coverage for qualifying and non-qualifying threshold boundaries in frontend/tests/e2e/long-paste-composer.spec.ts

### Implementation for User Story 1

- [x] T012 [P] [US1] Implement paste qualification at 7 logical lines or more than 1200 JavaScript string code units, collapsed/expanded state, reset helpers, and exact draft construction in frontend/src/hooks/useLongPasteCollapse.ts
- [x] T013 [P] [US1] Implement accessible compact/expanded preview controls in frontend/src/components/LongPastePreview.tsx
- [x] T014 [US1] Wire shared long-paste handling into Assistant message sending in frontend/src/screens/assistant/MessageComposer.tsx
- [x] T015 [US1] Wire shared long-paste handling into Teaching ChatComposer sending in frontend/src/screens/teaching/shared.tsx
- [x] T016 [US1] Add long-paste preview layout, focus, and compact textarea styling in frontend/src/styles/theme.css
- [x] T017 [US1] Reset Assistant long-paste presentation state on accepted send and session changes in frontend/src/screens/assistant/AssistantScreen.tsx
- [x] T018 [US1] Reset Teaching long-paste presentation state across intent conversation lifecycle changes in frontend/src/screens/teaching/IntentStage.tsx
- [x] T019 [US1] Reset Teaching long-paste presentation state across trial conversation lifecycle changes in frontend/src/screens/teaching/TrialStage.tsx

**Checkpoint**: US1 is complete when `frontend/tests/unit/long-paste-hook.test.ts`, `frontend/tests/unit/assistant-long-paste.test.tsx`, `frontend/tests/unit/teaching-long-paste.test.tsx`, and `frontend/tests/e2e/long-paste-composer.spec.ts` pass and both composers send exact full drafts.

---

## Phase 4: User Story 2 - Inspect Model Calls and Agent Flow (Priority: P2)

**Goal**: Provide an authenticated, warning-gated, runtime-only local Debug Inspector for LLM trace records, reference expansion, and Agent Flow timelines without changing model or orchestration behavior.

**Independent Test**: Arm trace from hidden `/debug`, trigger text/tool/vision model calls plus Teaching and Assistant delegation transitions, inspect linked/unlinked flow details, stop and re-enable trace, and verify old raw details, logs, public events, caches, URLs, and frontend persisted state contain no diagnostic-only raw data or application-controlled secrets.

### Tests for User Story 2

- [x] T020 [P] [US2] Create debug business test fixtures and fake clock/provider helpers in tests/business/debug/conftest.py
- [x] T021 [P] [US2] Add runtime-only debug config default and invalid-value tests in tests/data/test_unified_config_debug.py
- [x] T022 [P] [US2] Add trace arm warning, minimum warning-copy checklist, enable, disable, clear, restart lifecycle, and fail-closed cleanup-error tests in tests/business/debug/test_debug_control.py
- [x] T023 [P] [US2] Add trace buffer record-count, redacted retained-byte accounting, per-record bytes, aggregate bytes, eviction, stale completion rejection, and mid-flight epoch tests in tests/business/debug/test_trace_buffer.py
- [x] T024 [P] [US2] Add fail-isolated observation boundary tests for provider success and provider failure in tests/business/debug/test_observation_boundary.py
- [x] T025 [P] [US2] Add multimodal trace tests for text retention, media metadata, and zero base64/raw bytes in tests/business/debug/test_multimodal_trace.py
- [x] T026 [P] [US2] Add reference expansion auth, response-budget, not-found, and redaction tests in tests/business/debug/test_reference_expansion.py
- [x] T027 [P] [US2] Add debug REST auth, disabled fail-closed, warning-required, DTO, and no-store tests in tests/desktop_api/test_debug_api.py
- [x] T028 [P] [US2] Add Teaching and Assistant Agent Flow transition matrix tests for PM->Programmer, Programmer->Review->Programmer retry, review acceptance/publication, Trial->PM failure triage/reroute, Assistant-to-ephemeral-subagent, Assistant-to-fixed-specialist, executor return, linked trace, unlinked fallback, and provenance in tests/integration/test_debug_flow_trace.py
- [x] T029 [P] [US2] Add raw diagnostic leakage guard tests for logs, public UI events, cache headers, URLs, and frontend storage in tests/guardrails/test_debug_boundaries.py
- [x] T030 [P] [US2] Add static model/provider invocation inventory guard tests in tests/guardrails/test_debug_provider_inventory.py
- [x] T031 [P] [US2] Add DebugScreen minimum warning-copy checklist, arm, trace list/detail, completed-trace locate/expand behavior within the 30-second UX budget, flow, reference, clear, and local purge tests in frontend/tests/unit/debug-screen.test.tsx
- [x] T032 [P] [US2] Add hidden route and trace-active stop banner tests in frontend/tests/unit/app-shell-debug.test.tsx
- [x] T033 [P] [US2] Add controlled Debug Inspector E2E smoke coverage for locating and expanding a completed trace within 30 seconds in frontend/tests/e2e/debug-inspector.spec.ts

### Implementation for User Story 2

- [x] T034 [US2] Add runtime-only `debug.trace.*` and `debug.reference.max_response_bytes` accessors/defaults in src/data/unified_config.py
- [x] T035 [P] [US2] Define trace, control, flow, reference, limit, and diagnostic availability models in src/business/debug/models.py
- [x] T036 [P] [US2] Implement application-controlled secret and runtime-token redaction in src/business/debug/redaction.py, including credential snapshot rotation coverage without migration-capable getters
- [x] T037 [P] [US2] Implement nested and reset-safe trace capture context helpers in src/business/debug/context.py
- [x] T038 [US2] Implement epoch-scoped thread-safe trace buffer, redacted-payload byte budgets, eviction, fail-closed clear, stale-epoch rejection, and a rule that pre-redaction payloads are never buffered in src/business/debug/trace_buffer.py
- [x] T039 [US2] Implement fail-isolated model observation helpers for chat, tool, and multimodal calls in src/business/debug/observation.py
- [x] T040 [US2] Implement DebugInspectorService control, trace query/detail, clear, status, and service-owned read gates in src/business/debug/service.py
- [x] T041 [US2] Implement reference expansion facade using existing reference-loading semantics in src/business/debug/references.py
- [x] T042 [US2] Implement Agent Flow projection, transition-matrix classification, detail provenance, and trace link/unlinked mapping in src/business/debug/flow.py
- [x] T043 [US2] Route `chat()` and `chat_with_tools()` through the observation boundary and remove raw prompt/response debug logging in src/business/ai/llm_client.py
- [x] T044 [US2] Migrate vision/multimodal helper calls into the observation boundary with media metadata only in src/business/agents/tool_helpers.py
- [x] T045 [US2] Set session, agent, workflow, and iteration trace context around AgentLoop model calls in src/business/agents/agent_loop.py
- [x] T046 [US2] Set review source trace context without changing reviewer behavior in src/business/orchestration/llm_reviewer.py
- [x] T047 [US2] Propagate background brain source/work-unit trace context into worker model construction in src/business/brain/background_worker.py
- [x] T048 [US2] Set compression source trace context and register compression credential/provider handling in src/business/memory/compression_handler.py
- [x] T049 [US2] Register skill-composition LLM callsites in provider/redaction inventory without changing composition semantics in src/business/services/skill_composition/service.py
- [x] T050 [US2] Register embedding credential/callsite coverage while keeping embedding out of LLM trace records in src/business/memory/assistant_memory.py
- [x] T051 [US2] Capture Assistant delegated task/result as trace-gated ephemeral debug detail at the orchestration boundary in src/business/orchestration/agent/orchestrator.py
- [x] T052 [US2] Add repository query helpers for flow summaries without exposing raw SQL to business code in src/data/repos/workflow_transition_repository.py
- [x] T053 [US2] Replace raw Assistant delegation ordinary logs with safe summaries in src/business/agents/tools/assistant_tools.py
- [x] T054 [US2] Add Debug Inspector request/response DTOs and stable error shapes in src/desktop_api/schemas.py
- [x] T055 [US2] Implement authenticated `/api/debug` control, trace, flow, reference, clear, and no-store responses in src/desktop_api/routers/debug.py
- [x] T056 [US2] Register the debug router under existing session-token middleware in src/desktop_api/app.py
- [x] T057 [US2] Implement typed debug control/data client methods with memory-only raw response handling in frontend/src/api/debug.ts
- [x] T058 [US2] Separate ordinary navigation routes from hidden `/debug` route resolution in frontend/src/app/routes.tsx
- [x] T059 [US2] Implement hidden DebugScreen warning with required minimum risk statements, arm, disabled state, clear, and purge-on-leave behavior in frontend/src/screens/debug/DebugScreen.tsx
- [x] T060 [P] [US2] Implement trace grouping, trace list, detail, oversized, and diagnostic-unavailable UI in frontend/src/screens/debug/TracePanel.tsx
- [x] T061 [P] [US2] Implement Agent Flow timeline, provenance labels, linked/unlinked status, and two-interaction-or-less trace navigation in frontend/src/screens/debug/AgentFlowPanel.tsx
- [x] T062 [P] [US2] Implement reference expansion, not-found, truncated/chunked, and clear handling in frontend/src/screens/debug/ReferencePanel.tsx
- [x] T063 [US2] Add trace-active shell indicator and stop action wired to debug control in frontend/src/app/AppShell.tsx
- [x] T064 [US2] Add Debug Inspector and trace-active banner styling without exposing the route in ordinary nav in frontend/src/styles/theme.css
- [x] T065 [US2] Extend UI event payload safety checks for diagnostic-only prompt, trace, handoff, media, and correlation fields in src/desktop_api/ui_events.py
- [x] T066 [US2] Populate the static provider/direct-invoke inventory with supported, covered, and out-of-scope callsites in tests/guardrails/debug_provider_inventory.json, including any skill-composition/trial helper callsites found by scan rather than only the service entry point

**Checkpoint**: US2 is complete when trace arm is warning-gated and runtime-only, all supported text/tool/vision calls are observable or explicitly marked, Agent Flow preserves real transitions even when unlinked, raw diagnostic data purges on disable/clear/restart, and leakage guards pass.

---

## Phase 5: User Story 3 - Manual Real Grand Tour Acceptance (Priority: P3)

**Goal**: Add a separate opt-in real Grand Tour that uses a real sidecar, real configured model capabilities, isolated business data, read-only credential access, event-driven progress, safe live recording warnings, budgets, cleanup, and non-sensitive reports without changing default controlled E2E.

**Independent Test**: With real-tour opt-in disabled, routine E2E runs stay mock/cost-free. With opt-in enabled on a prepared developer machine, the suite warns about cost and capture, runs the scripted safe journey, observes public state rather than fixed sleeps, enforces budgets, prevents keyring mutation, stops recording on all exits, and writes sanitized summary reports.

### Tests for User Story 3

- [x] T067 [P] [US3] Add read-only credential resolver and no-migration tests in tests/data/test_read_only_credential_resolver.py
- [x] T068 [P] [US3] Add real-tour provider injection and unmet-prerequisite tests in tests/desktop_api/test_real_tour_credentials.py
- [x] T069 [P] [US3] Add real-tour runtime gating and budget unit tests in frontend/tests/unit/real-grand-tour-runtime.test.ts
- [x] T070 [P] [US3] Add event watcher replay/resync and last-observable-state unit tests in frontend/tests/unit/real-grand-tour-event-watcher.test.ts
- [x] T071 [P] [US3] Add summary report and artifact sanitizer guard tests in tests/guardrails/test_real_grand_tour_artifacts.py
- [x] T072 [P] [US3] Add keyring mutation audit guard tests in tests/guardrails/test_real_tour_credential_mutation.py
- [x] T073 [P] [US3] Add default regression separation E2E coverage in frontend/tests/e2e/grand-tour-default.spec.ts
- [x] T074 [P] [US3] Add controlled real-tour failure injection coverage in frontend/tests/unit/real-grand-tour-failures.test.ts

### Implementation for User Story 3

- [x] T075 [US3] Implement side-effect-free keyring-only credential resolver and mutation guard hooks in src/data/credential_resolver.py
- [x] T076 [US3] Inject the read-only credential provider into main LLM construction for real-tour runtime in src/desktop_api/orchestrator_runtime.py
- [x] T077 [US3] Inject the read-only credential provider into vision model construction in src/business/agents/tool_helpers.py
- [x] T078 [US3] Inject or explicitly skip background brain model construction for real-tour runtime in src/business/brain/background_worker.py
- [x] T079 [US3] Route settings connection validation through a read-only credential snapshot during real-tour runtime in src/business/services/settings_actions_service.py
- [x] T080 [US3] Route or skip skill-composition and trial-helper LLM construction under real-tour provider inventory in src/business/services/skill_composition/service.py and any helper modules discovered by the inventory scan
- [x] T081 [US3] Route or avoid compression LLM construction under real-tour provider inventory in src/business/memory/compression_handler.py
- [x] T082 [US3] Route or disable embedding credential lookup under real-tour provider inventory in src/business/memory/assistant_memory.py
- [x] T083 [US3] Implement real-tour runtime bootstrap, random port/token, temporary data dir, opt-in gates, and cleanup in frontend/tests/e2e/helpers/real-grand-tour-runtime.ts
- [x] T084 [P] [US3] Implement authenticated public event watcher with replay/resync handling in frontend/tests/e2e/helpers/event-watcher.ts
- [x] T085 [P] [US3] Implement paid-call and elapsed-time budget accounting in frontend/tests/e2e/helpers/real-grand-tour-budget.ts
- [x] T086 [P] [US3] Implement sanitized summary report writer and sentinel scanner in frontend/tests/e2e/helpers/real-grand-tour-report.ts
- [x] T087 [P] [US3] Implement credential fingerprint and mutation audit helper in frontend/tests/e2e/helpers/real-grand-tour-credentials.ts
- [x] T088 [P] [US3] Implement scripted safe live journey page object with stable liveJourneyId, target fixture identity, fixed non-sensitive input text, fixed actions, and terminal-state assertions in frontend/tests/e2e/pages/real-grand-tour-safe-journey.ts
- [x] T089 [US3] Implement opt-in headed manual real Grand Tour scenarios with independently reportable scenario IDs for readiness, assistant-real-reply, teaching-live-recording, teaching-workflow-progress, skills-compositions-visibility, settings-non-secret-interaction, and cross-screen-stability plus controlled skip behavior in frontend/tests/e2e/grand-tour.real.spec.ts
- [x] T090 [US3] Add `test:e2e:grand-tour` script for the opt-in real suite in frontend/package.json
- [x] T091 [US3] Add real-tour Playwright config with trace/video/screenshot off by default in frontend/playwright.real-grand-tour.config.ts
- [x] T092 [US3] Keep existing default Grand Tour controlled, mock-backed, and cost-free in frontend/tests/e2e/grand-tour.spec.ts
- [x] T093 [US3] Add real-tour opt-in environment handling that does not affect default E2E in frontend/tests/e2e/global-setup.ts
- [x] T094 [US3] Document the concrete safe live journey steps, stable liveJourneyId, target fixture identity, fixed input text, terminal-state assertion, and operator boundaries for maintainers in docs/local/real-grand-tour-safe-journey.md
- [x] T095 [US3] Ensure local summary output remains under ignored Playwright test-results paths in .gitignore

**Checkpoint**: US3 is complete when default E2E produces zero paid calls and no live capture, controlled failure tests cover timeout/cancel/cleanup/budget/credential mutation, and manual real-tour runs can produce sanitized reports with zero keyring mutation.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Synchronize living documentation and run the feature validation gates.

- [x] T096 [P] Update architecture documentation for hidden Debug Inspector, trace lifecycle, Agent Flow provenance, and real-tour boundaries in docs/ARCHITECTURE.md
- [x] T097 [P] Update development constraints for runtime-only trace, no-store raw endpoints, provider inventory, and real Grand Tour exception in docs/PROJECT_CONSTRAINTS.md
- [x] T098 [P] Update frontend AI entry mirrors for long-paste, hidden debug route, memory-only raw state, and real-tour exception in frontend/AGENTS.md, frontend/CLAUDE.md, and frontend/GEMINI.md
- [x] T099 [P] Update backend AI entry mirrors for debug facade, observation boundary, redaction/provider inventory, and read-only credential resolver in src/AGENTS.md, src/CLAUDE.md, and src/GEMINI.md
- [x] T100 [P] Update the Grand Tour contract with final concrete safe-journey identity, required scenario IDs, independent report fields, and scenario boundaries in specs/011-desktop-ux-debug-regression/contracts/grand-tour.md
- [x] T101 [P] Update quickstart verification notes with final commands, baseline source-note closure checks, and manual evidence expectations including the three-run safe summary citation convention in specs/011-desktop-ux-debug-regression/quickstart.md
- [x] T102 Run backend validation commands from specs/011-desktop-ux-debug-regression/quickstart.md
- [x] T103 Run frontend lint/unit/E2E validation commands from specs/011-desktop-ux-debug-regression/quickstart.md
- [x] T104 Run real-tour controlled failure and sanitized report validation described in specs/011-desktop-ux-debug-regression/quickstart.md

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies. T001 is the only setup dependency for US1; T002-T007 are story-local scaffolds for US2/US3 and provider inventory work.
- **Foundational (Phase 2)**: No additional blocking implementation tasks.
- **US1 (Phase 3)**: Depends only on T001. Can be implemented and validated before T002-T007, US2, or US3.
- **US2 (Phase 4)**: Depends on Setup and its own tests. Does not require US3.
- **US3 (Phase 5)**: Depends on Setup and the credential/provider inventory concepts from US2 where shared; does not require DebugScreen UI to be complete except for shared redaction/provider inventory decisions.
- **Polish (Phase 6)**: Depends on the stories being implemented to keep living docs accurate.

### User Story Dependencies

- **US1 (P1)**: Independent MVP slice. No dependency on trace inspector or real Grand Tour.
- **US2 (P2)**: Independent from US1 except normal shared frontend build/test infrastructure.
- **US3 (P3)**: Depends on read-only credential and provider inventory discipline; it must remain separate from default E2E.

### Within Each User Story

- Write tests first and verify they fail for the missing behavior.
- Implement shared models/services before API routers and UI clients.
- Implement backend contracts before frontend integration for US2.
- Implement controlled failure tests before manual real-tour evidence for US3.
- Validate each checkpoint before starting the next higher-risk slice when working sequentially.

### Parallel Opportunities

- Phase 1 scaffold tasks marked `[P]` can run in parallel, but T002-T007 do not block US1.
- US1 hook/component tasks can run in parallel with RTL tests once T001 fixtures exist.
- US2 backend service internals, API DTO/router work, and frontend panels can be split after debug models are defined.
- US3 credential resolver, frontend runner helpers, event watcher, report sanitizer, and page objects can be built in parallel after the opt-in contract is agreed.
- Polish documentation updates can run in parallel after implementation details are stable.

---

## Parallel Example: User Story 1

```text
Task: T008 Add paste qualification and selection-preservation hook tests in frontend/tests/unit/long-paste-hook.test.ts
Task: T009 Add Assistant composer long-paste RTL tests in frontend/tests/unit/assistant-long-paste.test.tsx
Task: T010 Add Teaching composer long-paste RTL tests in frontend/tests/unit/teaching-long-paste.test.tsx
Task: T012 Implement paste qualification, collapsed/expanded state, reset helpers, and exact draft construction in frontend/src/hooks/useLongPasteCollapse.ts
Task: T013 Implement accessible compact/expanded preview controls in frontend/src/components/LongPastePreview.tsx
```

## Parallel Example: User Story 2

```text
Task: T035 Define trace, control, flow, reference, limit, and diagnostic availability models in src/business/debug/models.py
Task: T036 Implement application-controlled secret and runtime-token redaction in src/business/debug/redaction.py
Task: T037 Implement nested and reset-safe trace capture context helpers in src/business/debug/context.py
Task: T060 Implement trace grouping, trace list, detail, oversized, and diagnostic-unavailable UI in frontend/src/screens/debug/TracePanel.tsx
Task: T061 Implement Agent Flow timeline, provenance labels, linked/unlinked status, and trace navigation in frontend/src/screens/debug/AgentFlowPanel.tsx
Task: T062 Implement reference expansion, not-found, truncated/chunked, and clear handling in frontend/src/screens/debug/ReferencePanel.tsx
```

## Parallel Example: User Story 3

```text
Task: T075 Implement side-effect-free keyring-only credential resolver and mutation guard hooks in src/data/credential_resolver.py
Task: T084 Implement authenticated public event watcher with replay/resync handling in frontend/tests/e2e/helpers/event-watcher.ts
Task: T085 Implement paid-call and elapsed-time budget accounting in frontend/tests/e2e/helpers/real-grand-tour-budget.ts
Task: T086 Implement sanitized summary report writer and sentinel scanner in frontend/tests/e2e/helpers/real-grand-tour-report.ts
Task: T088 Implement scripted safe live journey page object with fixed non-sensitive actions in frontend/tests/e2e/pages/real-grand-tour-safe-journey.ts
```

---

## Implementation Strategy

### MVP First (US1 Only)

1. Complete Phase 1 scaffolding needed by US1.
2. Complete US1 tests and implementation.
3. Validate exact draft preservation and compact preview behavior in both composers.
4. Stop and demo/merge US1 if desired; it does not wait for debug or real-tour work.

### Incremental Delivery

1. Deliver US1 for immediate input experience value.
2. Deliver US2 backend trace/control/redaction first, then API/UI, then Agent Flow correlation.
3. Deliver US3 as a separate manual acceptance capability after controlled failure tests pass.
4. Finish Phase 6 documentation and validation gates before claiming the whole feature complete.

### Risk Controls

- Keep raw diagnostic data process-local, epoch-scoped, bounded, and unavailable after disable/clear/restart.
- Keep `desktop_api` as an adapter: routers call `src/business/debug/` facades and never read repositories or keyring directly.
- Keep ordinary public UI events free of diagnostic-only prompt, trace, media, handoff, and correlation payloads.
- Keep real Grand Tour opt-in, headed/manual, budgeted, credential read-only, and isolated from default E2E.
