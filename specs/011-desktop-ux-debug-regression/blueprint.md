# Blueprint: Desktop UX, Debug Inspector, and Grand Tour Acceptance

**Branch**: `011-desktop-ux-debug-regression` | **Date**: 2026-05-24  
**Mode**: `doc-only`  
**Total Tasks**: 104 | **Files**: 55 new, 38 modified, 0 deleted

## Key Decisions

- Long-paste behavior is a shared frontend concern: one hook owns paste qualification, exact draft construction, presentation state, keyboard behavior, and reset triggers; Assistant and Teaching only wire their existing send flows to that shared contract. → T008, T009, T010, T011, T012, T013, T014, T015, T016, T017, T018, T019
- Debug inspection is business-owned and runtime-only: routers remain adapters, raw diagnostic data stays in `src/business/debug/`, and `debug.trace.enabled` is armed only through authenticated warning-gated control with epoch purge. → T021, T022, T023, T034, T035, T038, T040, T054, T055, T056
- Model observation is fail-isolated: text, tool, and vision LLM calls pass through a shared observation boundary; capture, redaction, correlation, or buffer failures cannot change provider success or failure semantics. → T024, T025, T039, T043, T044, T045, T046, T047, T048, T049, T050
- Agent Flow shows authoritative persisted transitions first and overlays only current-epoch ephemeral delegated task/result detail when tracing is armed; unlinked transitions remain visible. → T028, T042, T051, T052, T060, T061
- Raw diagnostic material never enters ordinary public events, ordinary logs, HTTP/WebView cache, URLs, frontend persisted state, or real-tour artifacts. → T029, T031, T032, T053, T057, T059, T063, T064, T065, T071
- Real Grand Tour is an explicit manual exception isolated from default E2E: it uses a random sidecar runtime, temporary business data, read-only keyring access, fixed safe live journey, budgets, cleanup, and sanitized reports. → T067, T068, T069, T070, T072, T073, T074, T075, T083, T084, T085, T086, T087, T088, T089, T090, T091, T092, T093, T094, T095
- Living documentation must describe only current runtime truth and mirror AI entry files in each affected module. → T096, T097, T098, T099, T100, T101

## Implementation Order

```text
Phase 1 scaffolds
  -> US1 tests
  -> US1 hook and preview component
  -> US1 composer wiring and reset integration
  -> US1 controlled E2E

Phase 1 scaffolds
  -> US2 debug config and business models
  -> US2 redaction, context, trace buffer, observation, reference and flow services
  -> US2 LLM, orchestration, repository and logging integrations
  -> US2 schemas, router, API client, hidden route and DebugScreen panels
  -> US2 leakage, provider inventory and E2E guards

Phase 1 scaffolds
  -> US3 credential resolver and provider inventory
  -> US3 runner helpers, event watcher, budget, report and credential audit
  -> US3 real-tour spec, Playwright config, default-suite separation and artifact policy

All implemented slices
  -> Living documentation and module AI entry mirrors
  -> Quickstart validation commands and evidence expectations
```

---

## Phase 1: Setup

### T001: Create shared long-paste fixtures in `frontend/tests/fixtures/longPasteFixtures.ts`

**File**: `frontend/tests/fixtures/longPasteFixtures.ts` (new)

**Requirements**:

FR-001, FR-002, SC-001, SC-002

**Dependencies**:

None.

**Required changes**:

Create exported fixture constants for six-line text, seven-line text, exactly 1200-code-unit single-line text, 1201-code-unit single-line text, mixed-newline text, selected-prefix text, selected-suffix text, and the expected middle-selection result. Keep all fixtures ASCII and deterministic. Use names that tests can import directly, such as `SEVEN_LINE_PASTE`, `LONG_SINGLE_LINE_PASTE`, and `MIDDLE_SELECTION_EXPECTED`.

**Verification**:

The file imports cleanly from Vitest tests and every fixture has a deterministic length or line-count assertion in T008.

---

### T002: Create debug package marker in `src/business/debug/__init__.py`

**File**: `src/business/debug/__init__.py` (new)

**Requirements**:

CC-001, CC-002, CC-006

**Dependencies**:

None.

**Required changes**:

Create the package marker with a concise module docstring stating that debug inspection is business-owned, process-local, and not a persistence boundary. Do not import service singletons from this file; consumers import concrete modules directly to avoid side effects.

**Verification**:

`uv run python -m py_compile src/business/debug/__init__.py` succeeds after the package exists.

---

### T003: Create debug API router scaffold in `src/desktop_api/routers/debug.py`

**File**: `src/desktop_api/routers/debug.py` (new)

**Requirements**:

CC-001, CC-002, CC-003

**Dependencies**:

T002.

**Required changes**:

Create a FastAPI router under prefix `/api/debug` with endpoint names matching `contracts/debug-api.md`: control get/put, traces list/detail/delete, flows list/detail, and reference expansion. Each endpoint delegates to `DebugInspectorService`; no repository, config-file, keyring, or reference-store access appears in the router. Raw-data endpoints must add `Cache-Control: no-store` when implemented.

**Verification**:

Router imports without side effects and can be registered by T056.

---

### T004: Create typed debug API client scaffold in `frontend/src/api/debug.ts`

**File**: `frontend/src/api/debug.ts` (new)

**Requirements**:

CC-002, SC-003, SC-005, SC-012

**Dependencies**:

T003.

**Required changes**:

Define TypeScript DTOs that mirror `contracts/debug-api.md`: control state, limits, trace summary/detail, flow summary/detail, reference response, provenance and availability enums. Export request functions that call `requestJson` from `frontend/src/api/client.ts`. Keep raw response values in returned promises only; do not use local storage, session storage, URL state, or a persisted store.

**Verification**:

`npm run test -- debug` can import the client and mock `requestJson` without constructing real Tauri state.

---

### T005: Create hidden debug screen scaffold in `frontend/src/screens/debug/DebugScreen.tsx`

**File**: `frontend/src/screens/debug/DebugScreen.tsx` (new)

**Requirements**:

FR-007, FR-008, FR-010, SC-003, SC-015

**Dependencies**:

T004.

**Required changes**:

Create a screen component that fetches control state, displays warning-gated arm controls when disabled, clears local raw state when disabled or unmounted, and hosts trace, flow, and reference panels once those panels exist. The screen must be reachable only by hidden route resolution, not by the ordinary NavRail route list.

**Verification**:

T031 can render the screen in disabled mode and find the warning text without raw diagnostic detail.

---

### T006: Create real Grand Tour runtime helper scaffold in `frontend/tests/e2e/helpers/real-grand-tour-runtime.ts`

**File**: `frontend/tests/e2e/helpers/real-grand-tour-runtime.ts` (new)

**Requirements**:

FR-032, FR-036, FR-037, SC-006, SC-007, SC-014

**Dependencies**:

None.

**Required changes**:

Define runtime helper types for opt-in flags, run identity, temporary data directory, random sidecar port, session token, live-capture consent, cleanup callback list, and sanitized report path. The helper must expose explicit skip reasons when opt-in flags are absent and must not start the sidecar in default regression runs.

**Verification**:

T069 can unit-test disabled default behavior without launching a real sidecar.

---

### T007: Create provider inventory scaffold in `tests/guardrails/debug_provider_inventory.json`

**File**: `tests/guardrails/debug_provider_inventory.json` (new)

**Requirements**:

CC-004, CC-006, SC-004, SC-012

**Dependencies**:

None.

**Required changes**:

Create a JSON array of inventory entries with `path`, `pattern`, `classification`, `traceRecordBehavior`, `realTourCredentialBehavior`, and `owner` fields. Initial entries must cover `orchestrator_runtime.py`, `tool_helpers.py`, `background_worker.py`, `skill_composition/service.py`, `compression_handler.py`, `assistant_memory.py`, `settings_actions_service.py`, and planned `src/business/debug/` redactor paths.

**Verification**:

T030 parses the JSON and fails for unregistered provider or credential callsites.

---

## Phase 2: Foundational

No file-producing task exists in this phase. The implementation rule is that US1 may proceed after Phase 1, while US2 and US3 build their local foundations inside their own phases.

---

## Phase 3: User Story 1 - Long Paste Keeps Chat Input Lightweight

### T008: Add paste qualification threshold boundary, mixed-newline counting, and selection-preservation hook tests

**File**: `frontend/tests/unit/long-paste-hook.test.ts` (new)

**Requirements**:

FR-001, FR-002, FR-003, SC-001, SC-002

**Dependencies**:

T001, T012.

**Required changes**:

Add Vitest coverage for qualifying paste at seven logical lines, qualifying paste at 1201 JavaScript code units, non-qualifying paste at six lines and 1200 code units, mixed `CRLF` and `LF` counting without text normalization, selected-range replacement, manual typing beyond thresholds without auto-collapse, expand and collapse transitions, clear reset, and accepted send reset.

**Verification**:

`cd frontend; npm run test -- long-paste-hook` passes and proves the hook owns all threshold math.

---

### T009: Add Assistant composer long-paste RTL tests

**File**: `frontend/tests/unit/assistant-long-paste.test.tsx` (new)

**Requirements**:

FR-001, FR-002, FR-004, FR-005, SC-001, SC-002

**Dependencies**:

T001, T012, T013, T014.

**Required changes**:

Render `MessageComposer` with controlled draft state and assert that a qualifying paste shows preview metadata, exposes keyboard-focusable expand, collapse, clear and send controls, sends exact full text, preserves send-disabled semantics for blank drafts, and keeps file or non-text paste on the existing browser path.

**Verification**:

`cd frontend; npm run test -- assistant-long-paste` passes with user-event paste and keyboard assertions.

---

### T010: Add Teaching composer long-paste RTL tests

**File**: `frontend/tests/unit/teaching-long-paste.test.tsx` (new)

**Requirements**:

FR-001, FR-002, FR-004, FR-005, SC-001, SC-002

**Dependencies**:

T001, T012, T013, T015.

**Required changes**:

Render `ChatComposer` with controlled draft state and assert parity with Assistant for qualifying paste, preview metadata, expand, collapse, clear, send, disabled composer behavior, manual typing exclusion, and exact draft forwarding.

**Verification**:

`cd frontend; npm run test -- teaching-long-paste` passes.

---

### T011: Add controlled long-paste composer E2E coverage

**File**: `frontend/tests/e2e/long-paste-composer.spec.ts` (new)

**Requirements**:

FR-001, FR-002, FR-003, SC-001, SC-002

**Dependencies**:

T014, T015, T017, T018, T019.

**Required changes**:

Add controlled Playwright coverage for Assistant and Teaching routes using mock API state. Cover seven-line paste, 1201-code-unit paste, six-line and 1200-code-unit non-collapse boundaries, middle insertion, expanded send, clear, and route/session lifecycle reset.

**Verification**:

`cd frontend; npm run test:e2e -- long-paste-composer` passes without requiring a real Python sidecar.

---

### T012: Implement shared long-paste hook

**File**: `frontend/src/hooks/useLongPasteCollapse.ts` (new)

**Requirements**:

FR-001, FR-002, FR-003, SC-001, SC-002

**Dependencies**:

T001, T008.

**Required changes**:

Implement a hook that receives `draft`, `setDraft`, optional threshold overrides, and reset keys. Expose `collapsed`, `expanded`, `qualified`, `lineCount`, `characterCount`, `previewText`, `onPaste`, `expand`, `collapse`, `clear`, `resetPresentation`, and `markSendAccepted`. `onPaste` reads only text clipboard data, computes `nextDraft = before + paste + after` from selection start and end, qualifies on logical line count greater than six or code-unit length greater than 1200, prevents default only when qualifying, and never normalizes the text. Manual `onChange` input only updates draft and does not auto-collapse.

**Verification**:

T008 passes and manual TypeScript checking reports no implicit any types.

---

### T013: Implement accessible compact/expanded preview controls

**File**: `frontend/src/components/LongPastePreview.tsx` (new)

**Requirements**:

FR-004, FR-005, SC-002

**Dependencies**:

T012.

**Required changes**:

Create a controlled presentational component that receives preview metadata and handlers. Collapsed mode shows a clear label, line and character counts, omitted-content text, expand, clear, and send affordance support through the host form. Expanded mode renders the full textarea area supplied by the host or a controlled textarea with `aria-expanded`, `aria-controls`, and keyboard-accessible collapse and clear actions. Use existing primitive buttons when possible.

**Verification**:

T009 and T010 can query accessible names and states.

---

### T014: Wire shared long-paste handling into Assistant message sending

**File**: `frontend/src/screens/assistant/MessageComposer.tsx` (modified)

**Requirements**:

FR-001, FR-002, FR-004, FR-005, SC-001, SC-002

**Dependencies**:

T012, T013.

**Required changes**:

Replace the plain textarea paste path with `useLongPasteCollapse`. Keep the existing form submit and Enter-to-send behavior, but pass accepted sends through `markSendAccepted` only after the parent confirms a send was accepted or after the draft is externally cleared. Render `LongPastePreview` above the composer bar when the hook is qualified. Preserve existing disabled attachment and voice buttons.

**Verification**:

T009 passes and existing Assistant composer tests continue to pass.

---

### T015: Wire shared long-paste handling into Teaching ChatComposer sending

**File**: `frontend/src/screens/teaching/shared.tsx` (modified)

**Requirements**:

FR-001, FR-002, FR-004, FR-005, SC-001, SC-002

**Dependencies**:

T012, T013.

**Required changes**:

Integrate the hook into `ChatComposer` while keeping its existing `draft`, `setDraft`, `onSend`, disabled, placeholder and hint API. Use the same preview component and action names as Assistant. Disabled state must prevent send, paste presentation changes, and preview actions that mutate draft.

**Verification**:

T010 passes and Teaching screen imports remain stable.

---

### T016: Add long-paste preview layout, focus, and compact textarea styling

**File**: `frontend/src/styles/theme.css` (modified)

**Requirements**:

FR-004, FR-005, SC-002

**Dependencies**:

T013, T014, T015.

**Required changes**:

Add classes for compact preview, metadata row, preview text block, expanded long-paste textarea, action group, clear affordance, focus-visible states, and disabled host composer behavior. Styling must be dense and consistent with current app surfaces, avoid nested cards, and keep text from overflowing buttons at mobile and desktop widths.

**Verification**:

T009 and T010 pass and Playwright screenshots for T011 show no overlap.

---

### T017: Reset Assistant long-paste state on accepted send and session changes

**File**: `frontend/src/screens/assistant/AssistantScreen.tsx` (modified)

**Requirements**:

FR-002, FR-005, SC-001, SC-002

**Dependencies**:

T014.

**Required changes**:

Provide a reset key or accepted-send signal to `MessageComposer` based on active session id and successful send completion. Sending failure must preserve the full draft and current long-paste presentation state if the existing business flow keeps the draft.

**Verification**:

T009 and T011 cover accepted send, failed send and session switch reset behavior.

---

### T018: Reset Teaching long-paste state across intent conversation lifecycle changes

**File**: `frontend/src/screens/teaching/IntentStage.tsx` (modified)

**Requirements**:

FR-002, FR-005, SC-001, SC-002

**Dependencies**:

T015.

**Required changes**:

Pass lifecycle reset keys to `ChatComposer` when the intent workflow, active run, or conversation identity changes. Accepted send clears the qualified presentation state; failed send preserves the full draft if the existing flow preserves it.

**Verification**:

T010 and T011 cover intent-stage lifecycle reset.

---

### T019: Reset Teaching long-paste state across trial conversation lifecycle changes

**File**: `frontend/src/screens/teaching/TrialStage.tsx` (modified)

**Requirements**:

FR-002, FR-005, SC-001, SC-002

**Dependencies**:

T015.

**Required changes**:

Apply the same lifecycle reset contract to trial conversations using the trial tool id, workflow id, request id, or equivalent active conversation identity already present in the screen.

**Verification**:

T010 and T011 cover trial-stage lifecycle reset.

---

## Phase 4: User Story 2 - Inspect Model Calls and Agent Flow

### T020: Create debug business test fixtures and fake clock/provider helpers

**File**: `tests/business/debug/conftest.py` (new)

**Requirements**:

CC-002, CC-006, SC-004, SC-016

**Dependencies**:

T002.

**Required changes**:

Provide pytest fixtures for fake clock, deterministic trace ids, debug config manager stub, redactor with sentinel secrets, trace buffer factory, fake provider success, fake provider failure, and fake reference loader. Fixtures must not touch real keyring or database.

**Verification**:

All `tests/business/debug/` tests import fixtures without side effects.

---

### T021: Add runtime-only debug config default and invalid-value tests

**File**: `tests/data/test_unified_config_debug.py` (new)

**Requirements**:

CC-003, SC-013, SC-015

**Dependencies**:

T034.

**Required changes**:

Assert defaults for `debug.trace.enabled`, `debug.trace.max_records`, `debug.trace.max_record_bytes`, `debug.trace.max_total_bytes`, and `debug.reference.max_response_bytes`. Assert invalid values fall back to documented defaults and `set("debug.trace.enabled", value, persist="runtime")` does not persist across a new config instance.

**Verification**:

`uv run python -m pytest tests/data/test_unified_config_debug.py -q` passes.

---

### T022: Add trace arm warning, enable, disable, clear, and restart lifecycle tests

**File**: `tests/business/debug/test_debug_control.py` (new)

**Requirements**:

FR-007, FR-014, CC-002, SC-005, SC-015

**Dependencies**:

T020, T034, T038, T040.

**Required changes**:

Test disabled default, warning-required enable, successful arm creates a new epoch, repeated enable does not expose raw data, disable purges current epoch, clear purges trace and ephemeral flow detail while preserving disabled state, and simulated restart begins unarmed with no old epoch.

**Verification**:

The test fails if raw records survive disable, clear or restart.

---

### T023: Add trace buffer record-count, per-record bytes, aggregate bytes, eviction, and mid-flight epoch tests

**File**: `tests/business/debug/test_trace_buffer.py` (new)

**Requirements**:

CC-002, SC-005, SC-013

**Dependencies**:

T020, T038.

**Required changes**:

Cover max record count eviction, per-record oversized omission, aggregate byte eviction, media metadata accounting, clear, stale epoch rejection for mid-flight completion, and thread-safe concurrent captures.

**Verification**:

`uv run python -m pytest tests/business/debug/test_trace_buffer.py -q` passes.

---

### T024: Add fail-isolated observation boundary tests

**File**: `tests/business/debug/test_observation_boundary.py` (new)

**Requirements**:

CC-006, SC-016

**Dependencies**:

T020, T039.

**Required changes**:

Assert provider success is returned unchanged when pre-capture, redaction, correlation or buffer write fails. Assert provider failure propagates unchanged when diagnostic handling also fails. Assert successful diagnostic capture produces a trace record with source and outcome.

**Verification**:

Injected diagnostic exceptions never change provider call count, return value or raised provider exception type.

---

### T025: Add multimodal trace tests

**File**: `tests/business/debug/test_multimodal_trace.py` (new)

**Requirements**:

FR-016, CC-002, SC-004, SC-012

**Dependencies**:

T020, T036, T039, T044.

**Required changes**:

Test that multimodal calls retain textual input and output, record media type/count/byte metadata, and never retain or return base64 strings, data URLs, raw bytes, screenshots, or restorable media payloads. Include a sentinel media string and verify it is absent from stored and returned trace detail.

**Verification**:

The test fails on any restorable media content in trace records or logs.

---

### T026: Add reference expansion auth, response-budget, not-found, and redaction tests

**File**: `tests/business/debug/test_reference_expansion.py` (new)

**Requirements**:

FR-010, CC-002A, SC-005, SC-013

**Dependencies**:

T020, T036, T041.

**Required changes**:

Assert reference expansion requires tracing enabled, accepts references outside the selected trace, redacts registered secrets, returns explicit not-found errors, and enforces configured response budget via truncation, chunking, or too-large diagnostics.

**Verification**:

Large reference fixtures never return unbounded content.

---

### T027: Add debug REST auth, disabled fail-closed, warning-required, DTO, and no-store tests

**File**: `tests/desktop_api/test_debug_api.py` (new)

**Requirements**:

CC-001, CC-002, CC-003, SC-005, SC-012, SC-015

**Dependencies**:

T040, T054, T055, T056.

**Required changes**:

Use FastAPI test client to assert session-token auth, control status without raw detail, warning-required enable validation, raw endpoints fail closed while disabled, no-store headers on raw endpoints, stable error codes, clear behavior, and router delegation to business service rather than repositories.

**Verification**:

`uv run python -m pytest tests/desktop_api/test_debug_api.py -q` passes.

---

### T028: Add Teaching and Assistant Agent Flow transition matrix tests

**File**: `tests/integration/test_debug_flow_trace.py` (new)

**Requirements**:

FR-019, FR-020, FR-021, FR-022, FR-023, FR-025-FR-031, SC-010, SC-011

**Dependencies**:

T040, T042, T051, T052.

**Required changes**:

Create integration fixtures for PM to Programmer handoff, Programmer to Review to Programmer retry, review acceptance/publication, Trial to PM failure triage and reroute, Assistant to ephemeral subagent, Assistant to fixed specialist, executor return, linked trace and unlinked fallback. Assert chronology, provenance, linked trace ids, and visibility of unlinked transitions.

**Verification**:

The test fails if a transition is hidden because correlation is missing.

---

### T029: Add raw diagnostic leakage guard tests

**File**: `tests/guardrails/test_debug_boundaries.py` (new)

**Requirements**:

CC-002, CC-005, SC-005, SC-012

**Dependencies**:

T036, T053, T055, T057, T065.

**Required changes**:

Add guard assertions that diagnostic-only raw prompt, response, tool args, handoff text, media payloads, correlation ids and credential sentinels do not appear in ordinary logs, public UI event payloads, HTTP cacheable responses, URLs, local storage, session storage, persisted stores or debug-disabled responses. Keep `assistant.message.content` allowed as product output.

**Verification**:

`uv run python -m pytest tests/guardrails/test_debug_boundaries.py -q` passes.

---

### T030: Add static model/provider invocation inventory guard tests

**File**: `tests/guardrails/test_debug_provider_inventory.py` (new)

**Requirements**:

CC-004, CC-006, SC-004, SC-012

**Dependencies**:

T007, T066.

**Required changes**:

Scan repository source for `.invoke(`, `embed_query(`, `LangChainLLMClient(`, `OpenAIEmbeddings(`, and `get_ai_*api_key` patterns. Every callsite must be present in `debug_provider_inventory.json` as trace-covered, real-tour-provider-covered, ordinary-runtime-only, or explicitly out of scope.

**Verification**:

Adding a new unregistered model or credential callsite fails the guardrail.

---

### T031: Add DebugScreen warning, arm, trace list/detail, flow, reference, clear, and local purge tests

**File**: `frontend/tests/unit/debug-screen.test.tsx` (new)

**Requirements**:

FR-007-FR-018, SC-003, SC-005, SC-011, SC-015

**Dependencies**:

T004, T005, T057, T059, T060, T061, T062.

**Required changes**:

Mock debug API calls and assert disabled warning, warning acknowledgement, armed state, trace list and detail display, completed-trace locate and expand within a controlled 30-second budget, flow timeline, reference expansion, clear behavior, route-leave local purge and disabled-state raw purge.

**Verification**:

`cd frontend; npm run test -- debug-screen` passes.

---

### T032: Add hidden route and trace-active stop banner tests

**File**: `frontend/tests/unit/app-shell-debug.test.tsx` (new)

**Requirements**:

FR-014, CC-002, SC-015

**Dependencies**:

T058, T063.

**Required changes**:

Assert `/debug` resolves to DebugScreen without appearing in ordinary route list or NavRail, trace-active banner appears while armed, stop action calls debug control disable, and banner disappears after successful stop.

**Verification**:

`cd frontend; npm run test -- app-shell-debug` passes.

---

### T033: Add controlled Debug Inspector E2E smoke coverage

**File**: `frontend/tests/e2e/debug-inspector.spec.ts` (new)

**Requirements**:

SC-003, SC-005, SC-011, SC-015

**Dependencies**:

T057, T058, T059, T060, T061, T062, T063.

**Required changes**:

Create controlled mock API E2E that directly visits `/debug`, arms tracing, receives a prepared completed trace, expands it within 30 seconds, views linked and unlinked flow rows, clears state, disables tracing and confirms no raw detail remains in page state or URL.

**Verification**:

`cd frontend; npm run test:e2e -- debug-inspector` passes.

---

### T034: Add runtime-only debug config accessors/defaults

**File**: `src/data/unified_config.py` (modified)

**Requirements**:

CC-003, SC-013, SC-015

**Dependencies**:

T021.

**Required changes**:

Add typed accessor methods for debug trace enabled, max records, max record bytes, max total bytes and reference max response bytes. Accessors must validate integers, return documented defaults on invalid values, and use `set("debug.trace.enabled", value, persist="runtime", value_type="boolean")` for arm state. No new secret storage, migration or ordinary Settings exposure is introduced.

**Verification**:

T021 passes and existing config tests continue to pass.

---

### T035: Define trace, control, flow, reference, limit, and diagnostic availability models

**File**: `src/business/debug/models.py` (new)

**Requirements**:

FR-007-FR-018, FR-025-FR-031, CC-002, CC-002B

**Dependencies**:

T002.

**Required changes**:

Define dataclasses or Pydantic-compatible business models for trace control state, debug limits, capture context, trace summary, trace detail, media metadata, tool detail, diagnostic availability, flow summary, flow transition view, flow detail provenance, reference response and stable debug errors. Keep business names close to API DTO names but do not import desktop API schemas.

**Verification**:

`uv run python -m py_compile src/business/debug/models.py` succeeds.

---

### T036: Implement application-controlled secret and runtime-token redaction

**File**: `src/business/debug/redaction.py` (new)

**Requirements**:

CC-002, CC-004, SC-005, SC-012

**Dependencies**:

T035.

**Required changes**:

Implement a redactor that registers application-controlled secrets and runtime tokens from actual factories, stores only process-local snapshots, replaces exact secret strings in strings, dicts and lists, and never calls migration-capable credential getters. Redaction must be safe for nested JSON-like values and stable for repeated calls.

**Verification**:

T025, T026, T029 and T071 can use sentinel secrets and prove absence from returned values.

---

### T037: Implement nested and reset-safe trace capture context helpers

**File**: `src/business/debug/context.py` (new)

**Requirements**:

CC-006, SC-004, SC-010

**Dependencies**:

T035.

**Required changes**:

Use `contextvars` to implement `TraceCaptureContext` with scope helpers that set source, agent type, session id, workflow id, transition id, work unit id and iteration. Provide reset-safe context managers for nested calls and helpers for thread or background-worker propagation.

**Verification**:

T024 and later integration tests prove context is restored after exceptions and nested scopes.

---

### T038: Implement epoch-scoped thread-safe trace buffer

**File**: `src/business/debug/trace_buffer.py` (new)

**Requirements**:

CC-002, SC-005, SC-013, SC-015

**Dependencies**:

T023, T035, T036.

**Required changes**:

Implement a lock-protected buffer with current epoch, max record count, max record bytes, max total bytes, trace records, ephemeral flow details and correlation indexes. Enable creates an empty epoch, disable and clear purge all debug-only data, stale epoch writes are rejected, oversized records become safe omission records, aggregate overflow evicts oldest records and detail.

**Verification**:

T023 passes including mid-flight stale epoch tests.

---

### T039: Implement fail-isolated model observation helpers

**File**: `src/business/debug/observation.py` (new)

**Requirements**:

CC-006, SC-004, SC-016

**Dependencies**:

T024, T035, T036, T037, T038.

**Required changes**:

Provide wrappers for chat, chat-with-tools and multimodal provider calls. Each wrapper snapshots current context and epoch before provider invocation, invokes the provider exactly once, records redacted input/output or failure summary when possible, records media metadata only for multimodal inputs, and catches diagnostic-side exceptions without changing provider result or provider exception.

**Verification**:

T024 and T025 pass.

---

### T040: Implement DebugInspectorService control, trace query/detail, clear, status, and read gates

**File**: `src/business/debug/service.py` (new)

**Requirements**:

FR-007-FR-018, CC-001, CC-002, CC-003, SC-003, SC-005, SC-015

**Dependencies**:

T022, T034, T035, T038, T041, T042.

**Required changes**:

Create the business facade used by routers. It reads limits from unified config, enforces warning acknowledgement, writes runtime-only arm state, owns epoch enable/disable/clear, exposes safe control status, fails closed for raw reads when disabled, returns trace lists/details, flow lists/details and reference expansion through service-owned gates.

**Verification**:

T022 and T027 pass.

---

### T041: Implement reference expansion facade

**File**: `src/business/debug/references.py` (new)

**Requirements**:

FR-010, CC-002A, SC-005, SC-013

**Dependencies**:

T026, T035, T036.

**Required changes**:

Wrap existing reference-loading semantics behind a debug facade that requires tracing enabled through the service, accepts any currently addressable reference id in process scope, redacts response content, enforces response budget, and returns explicit not-found or too-large diagnostics.

**Verification**:

T026 passes.

---

### T042: Implement Agent Flow projection and trace mapping

**File**: `src/business/debug/flow.py` (new)

**Requirements**:

FR-019-FR-023, FR-025-FR-031, CC-002B, SC-010, SC-011

**Dependencies**:

T028, T035, T038, T052.

**Required changes**:

Project existing workflow transitions into flow summaries and ordered transition views. Classify event types into handoff, retry, failure, completion, publication and waiting statuses. Attach persisted payload details with `persisted_transition`, attach current-epoch delegated task/result detail with `ephemeral_debug_capture`, otherwise mark detail unavailable. Correlate trace ids from the process-local index and leave missing links as `unlinked`.

**Verification**:

T028 passes with the transition matrix.

---

### T043: Route chat and chat_with_tools through observation boundary and remove raw debug logging

**File**: `src/business/ai/llm_client.py` (modified)

**Requirements**:

CC-006, SC-004, SC-012, SC-016

**Dependencies**:

T039.

**Required changes**:

Wrap `chat()` and `chat_with_tools()` provider invocations through `observation.observe_chat` and `observation.observe_chat_with_tools`. Replace current raw prompt, raw content and raw tool args debug logging with safe summary logging: message count, roles, content lengths, tool names, outcome and error type. Register API key snapshots with the redactor when the client is constructed.

**Verification**:

T024, T029 and T030 pass.

---

### T044: Migrate vision/multimodal helper calls into the observation boundary

**File**: `src/business/agents/tool_helpers.py` (modified)

**Requirements**:

FR-016, CC-004, CC-006, SC-004, SC-012

**Dependencies**:

T025, T039.

**Required changes**:

Route vision helper model invocations through the multimodal observation helper. Register vision credential snapshots with the redactor and real-tour provider inventory. Retain only text blocks and media metadata in diagnostic records. Preserve existing vision business behavior and provider failure semantics.

**Verification**:

T025 and T030 pass.

---

### T045: Set session, agent, workflow, and iteration trace context around AgentLoop model calls

**File**: `src/business/agents/agent_loop.py` (modified)

**Requirements**:

FR-007, FR-019, CC-006, SC-004, SC-010

**Dependencies**:

T037, T039.

**Required changes**:

Wrap AgentLoop model calls with `TraceCaptureContext` carrying agent type, session id, workflow id and iteration where available. The context must reset on every loop exit, including tool interruption, provider failure and cancellation. Tool semantics and prompt content remain unchanged.

**Verification**:

T024 and T028 observe correct context and unchanged tool behavior.

---

### T046: Set review source trace context without changing reviewer behavior

**File**: `src/business/orchestration/llm_reviewer.py` (modified)

**Requirements**:

CC-006, SC-004, SC-010

**Dependencies**:

T037.

**Required changes**:

Wrap reviewer LLM calls with source and workflow context. Do not change reviewer prompts, thresholds, retry behavior or result interpretation.

**Verification**:

Provider inventory and trace tests classify reviewer calls correctly.

---

### T047: Propagate background brain source/work-unit trace context

**File**: `src/business/brain/background_worker.py` (modified)

**Requirements**:

CC-004, CC-006, SC-004, SC-012

**Dependencies**:

T037, T039.

**Required changes**:

Set trace context around background model construction and calls using work-unit identifiers. Register background model credential handling in the provider inventory and support real-tour read-only provider injection or scenario skip.

**Verification**:

T030 and T068 classify background calls.

---

### T048: Set compression source trace context and register compression credential/provider handling

**File**: `src/business/memory/compression_handler.py` (modified)

**Requirements**:

CC-004, CC-006, SC-004, SC-012

**Dependencies**:

T037, T039.

**Required changes**:

Wrap compression LLM calls with source context and register compression credential behavior for redaction and real-tour inventory. Keep compression trigger semantics and message-pairing behavior unchanged.

**Verification**:

T030 passes and existing compression tests remain green.

---

### T049: Register skill-composition LLM callsites in provider/redaction inventory

**File**: `src/business/services/skill_composition/service.py` (modified)

**Requirements**:

CC-004, CC-006, SC-004, SC-012

**Dependencies**:

T036, T066.

**Required changes**:

Classify skill-composition LLM factories as real-tour-provider-covered or scenario-skipped before real-tour entry. Register any credential snapshot used by composition or trial helpers with the redactor. Do not change composition semantics.

**Verification**:

T030 and T068 pass.

---

### T050: Register embedding credential/callsite coverage while keeping embedding out of LLM trace records

**File**: `src/business/memory/assistant_memory.py` (modified)

**Requirements**:

CC-004, CC-006, SC-004, SC-012

**Dependencies**:

T036, T066.

**Required changes**:

Mark embedding/vectorization calls as out of trace-record scope but covered by credential redaction and real-tour provider inventory. Register embedding credential snapshots without creating `LLMTraceRecord` entries. Preserve memory semantics.

**Verification**:

T030 passes and trace tests prove embedding is not expected as a trace record.

---

### T051: Capture Assistant delegated task/result as trace-gated ephemeral debug detail

**File**: `src/business/orchestration/agent/orchestrator.py` (modified)

**Requirements**:

FR-021, FR-022, CC-002B, SC-010, SC-011

**Dependencies**:

T038, T042.

**Required changes**:

At the Assistant delegation boundary, capture redacted delegated task and executor result into the current trace epoch only when tracing is enabled. Link by workflow id and transition id where available. Never write this raw detail back to durable workflow transition payloads.

**Verification**:

T028 proves `ephemeral_debug_capture` appears only while tracing is armed and disappears after disable or clear.

---

### T052: Add repository query helpers for flow summaries

**File**: `src/data/repos/workflow_transition_repository.py` (modified)

**Requirements**:

CC-001, CC-002B, SC-010, SC-011

**Dependencies**:

T028.

**Required changes**:

Add repository methods for recent workflows, filtering by workflow id or session id, and ordered transition retrieval with limits. Keep SQLAlchemy query logic in the repository and return model objects or simple data structures suitable for business projection.

**Verification**:

T028 passes without business code writing raw SQL.

---

### T053: Replace raw Assistant delegation ordinary logs with safe summaries

**File**: `src/business/agents/tools/assistant_tools.py` (modified)

**Requirements**:

CC-002, SC-012

**Dependencies**:

T036.

**Required changes**:

Audit delegation logging and remove raw task, result, prompt, tool argument and model reply text from ordinary logs. Replace with safe summaries: delegated target type, text length, status, workflow id where safe, and error type. Apply the same rule to exception paths.

**Verification**:

T029 log-capture guard passes.

---

### T054: Add Debug Inspector request/response DTOs and stable error shapes

**File**: `src/desktop_api/schemas.py` (modified)

**Requirements**:

FR-007-FR-018, FR-025-FR-031, CC-002, SC-003, SC-005

**Dependencies**:

T035.

**Required changes**:

Add Pydantic DTOs for debug control request/response, debug limits, trace list response, trace summary, trace detail, media metadata, flow list response, flow detail response, flow transition, reference response, stable debug error codes and provenance enums. Keep camelCase field names consistent with existing desktop API schemas.

**Verification**:

T027 validates DTO shapes against the contract examples.

---

### T055: Implement authenticated `/api/debug` control, trace, flow, reference, clear, and no-store responses

**File**: `src/desktop_api/routers/debug.py` (new)

**Requirements**:

CC-001, CC-002, CC-003, SC-003, SC-005, SC-012

**Dependencies**:

T003, T040, T054.

**Required changes**:

Implement all debug endpoints by delegating to `DebugInspectorService`. Map business errors to stable `ErrorResponse` shapes. Add `Cache-Control: no-store` to trace, flow detail and reference responses. Return `204` for clear. Do not directly import repositories, keyring or config-file loaders.

**Verification**:

T027 passes.

---

### T056: Register debug router under existing session-token middleware

**File**: `src/desktop_api/app.py` (modified)

**Requirements**:

CC-001, CC-002, SC-015

**Dependencies**:

T055.

**Required changes**:

Import the debug router with existing desktop routers and call `app.include_router(debug.router)` inside `create_app`. Session-token middleware remains the only outer API auth gate; no new bypass path is introduced.

**Verification**:

T027 unauthorized tests pass for debug endpoints.

---

### T057: Implement typed debug control/data client methods

**File**: `frontend/src/api/debug.ts` (new)

**Requirements**:

CC-002, SC-003, SC-005, SC-012, SC-015

**Dependencies**:

T004, T054, T055.

**Required changes**:

Implement `getDebugControl`, `setDebugControl`, `listDebugTraces`, `getDebugTrace`, `clearDebugTraces`, `listDebugFlows`, `getDebugFlow`, and `expandDebugReference`. Use `requestJson`; do not cache raw responses beyond caller memory. Surface `DesktopApiError` codes unchanged for UI handling.

**Verification**:

T031 can mock every method.

---

### T058: Separate ordinary navigation routes from hidden `/debug` route resolution

**File**: `frontend/src/app/routes.tsx` (modified)

**Requirements**:

FR-014, CC-002, SC-015

**Dependencies**:

T005.

**Required changes**:

Keep existing `routes` array for ordinary NavRail items only. Add a hidden route resolver or direct path check for `/debug` that renders `DebugScreen` without adding it to `routes` or `RouteId` navigation state. Preserve existing fallback behavior for ordinary route ids.

**Verification**:

T032 passes and NavRail does not show Debug.

---

### T059: Implement hidden DebugScreen warning, arm, disabled state, clear, and purge-on-leave behavior

**File**: `frontend/src/screens/debug/DebugScreen.tsx` (new)

**Requirements**:

FR-007-FR-018, SC-003, SC-005, SC-015

**Dependencies**:

T057, T060, T061, T062.

**Required changes**:

Implement the full DebugScreen state machine. Disabled state shows warning and enable control only. Enable requires explicit acknowledgement. Armed state loads trace and flow summaries, supports clear, disables and purges raw local state, purges on unmount, and shows errors without persisting raw detail.

**Verification**:

T031 passes.

---

### T060: Implement trace grouping, trace list, detail, oversized, and diagnostic-unavailable UI

**File**: `frontend/src/screens/debug/TracePanel.tsx` (new)

**Requirements**:

FR-007-FR-009, FR-016, SC-003, SC-004, SC-013

**Dependencies**:

T057, T059.

**Required changes**:

Render trace groups, filters, list rows, selected trace detail, source, agent type, session or workflow ids, outcome, timing, retained bytes, tool names, input/output text, media metadata only, oversized omission and diagnostic unavailable states. Never put raw detail into URL or persisted state.

**Verification**:

T031 and T033 pass.

---

### T061: Implement Agent Flow timeline, provenance labels, linked/unlinked status, and trace navigation

**File**: `frontend/src/screens/debug/AgentFlowPanel.tsx` (new)

**Requirements**:

FR-019-FR-023, FR-025-FR-031, SC-010, SC-011

**Dependencies**:

T057, T059, T060.

**Required changes**:

Render flow summaries and ordered transition timelines. Show source/target agent or terminal state, event type, status, trigger reason, provenance labels, linked trace buttons, unlinked labels and unavailable detail. Linked trace navigation must select the trace in two interactions or fewer from a flow row.

**Verification**:

T031 and T033 pass.

---

### T062: Implement reference expansion, not-found, truncated/chunked, and clear handling

**File**: `frontend/src/screens/debug/ReferencePanel.tsx` (new)

**Requirements**:

FR-010, CC-002A, SC-005, SC-013

**Dependencies**:

T057, T059.

**Required changes**:

Provide a reference id input, expansion action, result display, not-found error state, truncated/chunked indicator and local clear. The panel must clear data when parent screen clears, disables or unmounts.

**Verification**:

T031 passes with reference success, not-found and oversized cases.

---

### T063: Add trace-active shell indicator and stop action wired to debug control

**File**: `frontend/src/app/AppShell.tsx` (modified)

**Requirements**:

FR-014, CC-002, SC-015

**Dependencies**:

T057.

**Required changes**:

Poll or subscribe to debug control state after bootstrap and after debug control changes. When armed, show a persistent trace-active banner or titlebar control with stop action. Stop calls `setDebugControl({ enabled: false })`, purges local debug screen state by shared event or store signal, and handles failure with a safe error message.

**Verification**:

T032 passes.

---

### T064: Add Debug Inspector and trace-active banner styling

**File**: `frontend/src/styles/theme.css` (modified)

**Requirements**:

FR-014, SC-003, SC-015

**Dependencies**:

T059, T060, T061, T062, T063.

**Required changes**:

Add restrained diagnostic UI styling for warning panel, filter rows, trace list, detail panes, flow timeline, provenance labels, reference panel, trace-active banner and stop button. Do not expose debug route in nav styling and do not create nested card stacks.

**Verification**:

T031, T032 and T033 pass.

---

### T065: Extend UI event payload safety checks

**File**: `src/desktop_api/ui_events.py` (modified)

**Requirements**:

CC-005, SC-012

**Dependencies**:

T029.

**Required changes**:

Add or tighten registry validation so public event payload contracts do not admit diagnostic-only raw prompt, trace detail, handoff text, media bytes, media data URLs or debug-only correlation fields. Keep existing user-visible product message content legal.

**Verification**:

T029 passes and existing UI event tests continue to pass.

---

### T066: Populate static provider/direct-invoke inventory

**File**: `tests/guardrails/debug_provider_inventory.json` (new)

**Requirements**:

CC-004, CC-006, SC-004, SC-012

**Dependencies**:

T007, T030, T043, T044, T047, T048, T049, T050.

**Required changes**:

Fill inventory entries with actual paths, patterns, classification and handling status for all known LLM, embedding, credential and direct provider callsites. Include explicit out-of-scope rationale for embedding trace records and ordinary-runtime-only paths.

**Verification**:

T030 passes.

---

## Phase 5: User Story 3 - Manual Real Grand Tour Acceptance

### T067: Add read-only credential resolver and no-migration tests

**File**: `tests/data/test_read_only_credential_resolver.py` (new)

**Requirements**:

CC-004, SC-006, SC-012

**Dependencies**:

T075.

**Required changes**:

Test keyring-only reads, no plaintext fallback, no migration, no set, no delete, sentinel redaction registration, missing credential diagnostics and mutation guard counting. Use fake keyring adapter fixtures only.

**Verification**:

`uv run python -m pytest tests/data/test_read_only_credential_resolver.py -q` passes.

---

### T068: Add real-tour provider injection and unmet-prerequisite tests

**File**: `tests/desktop_api/test_real_tour_credentials.py` (new)

**Requirements**:

CC-004, SC-006, SC-007, SC-012, SC-014

**Dependencies**:

T075, T076, T077, T078, T079, T080, T081, T082.

**Required changes**:

Assert real-tour runtime injects read-only provider into main, vision, background, settings validation, skill-composition, compression, embedding and redactor paths or marks scenarios skipped before construction. Missing injection must return unmet-prerequisite failure and never fall back to ordinary getters.

**Verification**:

`uv run python -m pytest tests/desktop_api/test_real_tour_credentials.py -q` passes.

---

### T069: Add real-tour runtime gating and budget unit tests

**File**: `frontend/tests/unit/real-grand-tour-runtime.test.ts` (new)

**Requirements**:

FR-032, FR-037, SC-006, SC-007, SC-014

**Dependencies**:

T006, T083, T085.

**Required changes**:

Test default skip with no opt-in, live-capture scenario skip with missing capture opt-in, random token and port generation, temporary data directory lifecycle, elapsed budget stop, paid-call budget stop and cleanup callback ordering.

**Verification**:

`cd frontend; npm run test -- real-grand-tour-runtime` passes.

---

### T070: Add event watcher replay/resync and last-observable-state unit tests

**File**: `frontend/tests/unit/real-grand-tour-event-watcher.test.ts` (new)

**Requirements**:

CC-005, SC-008, SC-014

**Dependencies**:

T084.

**Required changes**:

Test authenticated event connection headers, sequence cursor handling, replay/resync, timeout failure with last observed safe state, scenario-specific event filters and no dependency on debug raw material.

**Verification**:

`cd frontend; npm run test -- real-grand-tour-event-watcher` passes.

---

### T071: Add summary report and artifact sanitizer guard tests

**File**: `tests/guardrails/test_real_grand_tour_artifacts.py` (new)

**Requirements**:

FR-038, FR-039, SC-006, SC-012, SC-014

**Dependencies**:

T086, T091.

**Required changes**:

Validate report schema, scenario result fields, commit and journey identity, absence of raw prompt, response, trace, handoff, screenshot content, credential, runtime token, raw media and sensitive full paths. Assert Playwright real-tour config disables trace, video and screenshots by default.

**Verification**:

`uv run python -m pytest tests/guardrails/test_real_grand_tour_artifacts.py -q` passes.

---

### T072: Add keyring mutation audit guard tests

**File**: `tests/guardrails/test_real_tour_credential_mutation.py` (new)

**Requirements**:

CC-004, SC-006, SC-014

**Dependencies**:

T075, T087.

**Required changes**:

Test mutation guard rejects set, delete and migration attempts, records attempts without leaking secret values, and reports mutation count zero when no mutation occurs. Include sidecar-style adapter coverage.

**Verification**:

`uv run python -m pytest tests/guardrails/test_real_tour_credential_mutation.py -q` passes.

---

### T073: Add default regression separation E2E coverage

**File**: `frontend/tests/e2e/grand-tour-default.spec.ts` (new)

**Requirements**:

FR-036, SC-007

**Dependencies**:

T092, T093.

**Required changes**:

Assert default E2E does not require real credentials, does not start real live capture, does not launch the real-tour runtime, does not count paid calls and still uses controlled mock behavior.

**Verification**:

`cd frontend; npm run test:e2e -- grand-tour-default` passes.

---

### T074: Add controlled real-tour failure injection coverage

**File**: `frontend/tests/unit/real-grand-tour-failures.test.ts` (new)

**Requirements**:

FR-035, FR-037, FR-039, SC-008, SC-009, SC-014

**Dependencies**:

T083, T084, T085, T086, T087.

**Required changes**:

Inject model failure, event timeout, cancellation, recording stop failure, credential mutation attempt, missing provider injection, budget exhaustion and sanitizer failure. Assert cleanup runs and summary reports include safe last observable state.

**Verification**:

`cd frontend; npm run test -- real-grand-tour-failures` passes.

---

### T075: Implement side-effect-free keyring-only credential resolver and mutation guard hooks

**File**: `src/data/credential_resolver.py` (new)

**Requirements**:

CC-004, SC-006, SC-012

**Dependencies**:

T067, T072.

**Required changes**:

Implement a read-only resolver that reads existing keyring entries through an injected adapter, never reads plaintext config fallback, never performs migration, never calls set or delete, returns explicit missing-credential diagnostics, exposes fingerprint comparison using irreversible hashes or presence flags, and supports mutation guard hooks for test/runtime audit.

**Verification**:

T067 and T072 pass.

---

### T076: Inject read-only credential provider into main LLM construction for real-tour runtime

**File**: `src/desktop_api/orchestrator_runtime.py` (modified)

**Requirements**:

CC-004, SC-006, SC-007

**Dependencies**:

T075.

**Required changes**:

Allow real-tour runtime to supply the read-only credential provider to main LLM construction. Ordinary runtime continues to use existing secure config paths. Real-tour mode must fail unmet prerequisite if the provider is absent.

**Verification**:

T068 passes.

---

### T077: Inject read-only credential provider into vision model construction

**File**: `src/business/agents/tool_helpers.py` (modified)

**Requirements**:

CC-004, CC-006, SC-006, SC-012

**Dependencies**:

T075.

**Required changes**:

Thread the read-only credential provider into vision helpers when real-tour runtime is active. Prevent plaintext fallback or migration-capable getter usage in that mode.

**Verification**:

T068 and T030 pass.

---

### T078: Inject or explicitly skip background brain model construction for real-tour runtime

**File**: `src/business/brain/background_worker.py` (modified)

**Requirements**:

CC-004, SC-006, SC-014

**Dependencies**:

T075.

**Required changes**:

Support real-tour provider injection for background LLM calls or disable/skip background-brain scenarios before construction. The decision must be visible in inventory and report prerequisites.

**Verification**:

T068 passes.

---

### T079: Route settings connection validation through a read-only credential snapshot during real-tour runtime

**File**: `src/business/services/settings_actions_service.py` (modified)

**Requirements**:

CC-004, SC-006, SC-012

**Dependencies**:

T075.

**Required changes**:

Use the read-only credential snapshot for settings connection validation while real-tour runtime is active. Block secret POST/DELETE paths and avoid any migration or write side effects. Non-secret settings writes remain isolated to test configuration.

**Verification**:

T068 passes and real-tour mutation guards remain zero.

---

### T080: Route or skip skill-composition LLM construction under real-tour provider inventory

**File**: `src/business/services/skill_composition/service.py` (modified)

**Requirements**:

CC-004, SC-006, SC-014

**Dependencies**:

T075.

**Required changes**:

If real-tour scenarios trigger skill-composition LLM paths, they must use the read-only provider and count paid calls. If scenarios stay in visibility/create/read mode, mark LLM generation/trial paths skipped before construction.

**Verification**:

T068 and T089 pass.

---

### T081: Route or avoid compression LLM construction under real-tour provider inventory

**File**: `src/business/memory/compression_handler.py` (modified)

**Requirements**:

CC-004, SC-006, SC-014

**Dependencies**:

T075.

**Required changes**:

Use read-only provider for compression LLM if compression can trigger during real-tour. Otherwise seed the run to avoid compression and record an explicit scenario skip or ordinary-runtime-only classification.

**Verification**:

T068 and T030 pass.

---

### T082: Route or disable embedding credential lookup under real-tour provider inventory

**File**: `src/business/memory/assistant_memory.py` (modified)

**Requirements**:

CC-004, CC-006, SC-006, SC-012

**Dependencies**:

T075.

**Required changes**:

Ensure embedding credential lookup in real-tour mode uses read-only no-migration access or is disabled before the scenario reaches it. Embedding remains out of trace-record scope.

**Verification**:

T068 and T030 pass.

---

### T083: Implement real-tour runtime bootstrap, random port/token, temporary data dir, opt-in gates, and cleanup

**File**: `frontend/tests/e2e/helpers/real-grand-tour-runtime.ts` (new)

**Requirements**:

FR-032, FR-036, FR-037, SC-006, SC-007, SC-014

**Dependencies**:

T006, T069.

**Required changes**:

Implement runtime bootstrap that checks `MEXEMPLAR_REAL_GRAND_TOUR`, optional live-capture flag, creates temporary data dir, allocates random port and token, starts the real sidecar only in opt-in mode, configures frontend API base, registers cleanup functions and returns structured skip or failure reasons.

**Verification**:

T069 and T074 pass.

---

### T084: Implement authenticated public event watcher with replay/resync handling

**File**: `frontend/tests/e2e/helpers/event-watcher.ts` (new)

**Requirements**:

CC-005, SC-008, SC-014

**Dependencies**:

T070.

**Required changes**:

Implement an event watcher that connects to `/api/events` with session header, tracks cursor, handles replay/resync, filters public event domains, exposes waits with timeout and last observable safe state, and never reads debug raw endpoints or private database state.

**Verification**:

T070 passes.

---

### T085: Implement paid-call and elapsed-time budget accounting

**File**: `frontend/tests/e2e/helpers/real-grand-tour-budget.ts` (new)

**Requirements**:

FR-037, SC-014

**Dependencies**:

T069.

**Required changes**:

Implement a budget helper with defaults of 20 minutes and 30 paid calls. Expose `assertCanStartPaidCall`, `recordPaidCall`, elapsed-time checks, budget exceeded error type and final usage summary. Calls after budget exhaustion must fail before invoking model work.

**Verification**:

T069 and T074 pass.

---

### T086: Implement sanitized summary report writer and sentinel scanner

**File**: `frontend/tests/e2e/helpers/real-grand-tour-report.ts` (new)

**Requirements**:

FR-038, FR-039, SC-006, SC-008, SC-012

**Dependencies**:

T071, T074.

**Required changes**:

Write summary JSON under Playwright test-results with run id, commit sha, live journey id, scenario outcomes, last observable states, budget usage, cleanup status and credential mutation count. Add sentinel scanner for prompt, response, credential, token, raw media, data URL and sensitive path patterns.

**Verification**:

T071 and T074 pass.

---

### T087: Implement credential fingerprint and mutation audit helper

**File**: `frontend/tests/e2e/helpers/real-grand-tour-credentials.ts` (new)

**Requirements**:

CC-004, SC-006, SC-014

**Dependencies**:

T072, T075.

**Required changes**:

Implement test-side helper to capture credential presence/fingerprint before and after run, install mutation audit integration, assert mutation count zero, and redact fingerprint output from reports.

**Verification**:

T072 and T074 pass.

---

### T088: Implement scripted safe live journey page object

**File**: `frontend/tests/e2e/pages/real-grand-tour-safe-journey.ts` (new)

**Requirements**:

FR-033, FR-038, SC-006, SC-009

**Dependencies**:

T083, T084.

**Required changes**:

Define `liveJourneyId` and fixed non-sensitive actions for the prepared target window/page. Include setup checks, privacy confirmation handoff, action sequence, stop criteria and public event waits. Keep the sequence deterministic and free of personal data.

**Verification**:

T089 can call the page object and report the journey identity.

---

### T089: Implement opt-in headed manual real Grand Tour scenarios

**File**: `frontend/tests/e2e/grand-tour.real.spec.ts` (new)

**Requirements**:

FR-032-FR-039, SC-006-SC-009, SC-014

**Dependencies**:

T083, T084, T085, T086, T087, T088.

**Required changes**:

Create independent scenario units for readiness, assistant-real-reply, teaching-live-recording, teaching-workflow-progress, skills-compositions-visibility, settings-non-secret-interaction and cross-screen-stability. Each scenario records status, last observable state, budget usage, cleanup status and failure reason. The spec must be headed/manual, opt-in only and never part of default E2E.

**Verification**:

Manual command from quickstart produces sanitized reports on a prepared developer machine.

---

### T090: Add `test:e2e:grand-tour` script

**File**: `frontend/package.json` (modified)

**Requirements**:

FR-032, SC-006, SC-007

**Dependencies**:

T089, T091.

**Required changes**:

Add a script that runs Playwright with `playwright.real-grand-tour.config.ts`. Do not modify the default `test:e2e` script to include the real suite.

**Verification**:

`cd frontend; npm run test:e2e` remains controlled and `npm run test:e2e:grand-tour -- --headed` targets only the real config.

---

### T091: Add real-tour Playwright config with artifacts off by default

**File**: `frontend/playwright.real-grand-tour.config.ts` (new)

**Requirements**:

FR-039, SC-012, SC-014

**Dependencies**:

T071, T089.

**Required changes**:

Create a Playwright config that selects `grand-tour.real.spec.ts`, defaults trace/video/screenshot to off, uses a dedicated output directory under test-results, runs headed/manual-friendly settings, and does not share default mock setup unless explicitly safe.

**Verification**:

T071 validates config artifact defaults.

---

### T092: Keep existing default Grand Tour controlled, mock-backed, and cost-free

**File**: `frontend/tests/e2e/grand-tour.spec.ts` (modified)

**Requirements**:

FR-036, SC-007

**Dependencies**:

T073.

**Required changes**:

Remove or avoid API key save interactions and any real-model or live-recording behavior from the default suite. Keep it as controlled UI regression coverage with mock or safe test behavior.

**Verification**:

T073 passes and default `npm run test:e2e` requires no real credentials.

---

### T093: Add real-tour opt-in environment handling that does not affect default E2E

**File**: `frontend/tests/e2e/global-setup.ts` (modified)

**Requirements**:

FR-036, SC-007

**Dependencies**:

T083, T091.

**Required changes**:

Ensure global setup leaves default E2E unchanged. If real-tour env flags are present under real-tour config, prepare only real-tour runtime. If flags are absent, the real suite skips before starting sidecar/model/recorder.

**Verification**:

T069 and T073 pass.

---

### T094: Document concrete safe live journey steps

**File**: `docs/local/real-grand-tour-safe-journey.md` (new)

**Requirements**:

FR-033, FR-038, SC-006, SC-009

**Dependencies**:

T088, T089.

**Required changes**:

Document the fixed live journey identity, prepared target requirements, non-sensitive sample data, exact manual action sequence, privacy warning, stop/cleanup expectations, and evidence rule that three passing runs must use the same commit and journey id.

**Verification**:

Manual quickstart references this document and the page object uses the same journey identity.

---

### T095: Ensure local summary output remains ignored

**File**: `.gitignore` (modified)

**Requirements**:

FR-039, SC-012

**Dependencies**:

T086, T091.

**Required changes**:

Add ignore patterns for real-tour local summary output and sanitized attachments under Playwright test-results if not already covered. Do not ignore source specs, configs or contracts.

**Verification**:

`git status --short` does not show generated real-tour run reports after a local run.

---

## Phase 6: Polish & Cross-Cutting Concerns

### T096: Update architecture documentation

**File**: `docs/ARCHITECTURE.md` (modified)

**Requirements**:

CC-001, CC-002, CC-004, CC-006

**Dependencies**:

Implemented US1, US2 and US3 slices.

**Required changes**:

Document hidden Debug Inspector architecture, runtime-only trace lifecycle, business-owned debug facade, model observation boundary, Agent Flow provenance, no durable raw diagnostic storage, real-tour sidecar/runtime isolation and default E2E separation.

**Verification**:

Architecture docs match implemented module boundaries and do not describe retired PyQt paths as active UI.

---

### T097: Update development constraints

**File**: `docs/PROJECT_CONSTRAINTS.md` (modified)

**Requirements**:

CC-002, CC-003, CC-004, CC-005, CC-006

**Dependencies**:

Implemented US2 and US3 slices.

**Required changes**:

Add constraints for runtime-only trace arm, no-store raw debug endpoints, frontend memory-only raw state, provider inventory guard, no ordinary-log raw diagnostics, read-only real-tour credential provider, budgeted manual real-tour exception and artifact sanitization.

**Verification**:

Docs include the accepted exceptions and match tests.

---

### T098: Update frontend AI entry mirrors

**File**: `frontend/AGENTS.md`, `frontend/CLAUDE.md`, `frontend/GEMINI.md` (modified)

**Requirements**:

CC-001, CC-002, CC-004

**Dependencies**:

T096, T097.

**Required changes**:

Update all three files with identical content covering shared long-paste hook expectations, hidden `/debug` route, memory-only raw debug state, AppShell trace-active stop banner, default E2E separation and manual real-tour exception.

**Verification**:

File contents are identical and mention no tool-specific divergence.

---

### T099: Update backend AI entry mirrors

**File**: `src/AGENTS.md`, `src/CLAUDE.md`, `src/GEMINI.md` (modified)

**Requirements**:

CC-001, CC-002, CC-003, CC-004, CC-006

**Dependencies**:

T096, T097.

**Required changes**:

Update all three files with identical content covering business-owned debug facade, observation boundary, redaction/provider inventory, ephemeral flow detail, read-only credential resolver, and router/repository boundaries.

**Verification**:

File contents are identical and remain consistent with root AGENTS.

---

### T100: Update Grand Tour contract

**File**: `specs/011-desktop-ux-debug-regression/contracts/grand-tour.md` (modified)

**Requirements**:

FR-032-FR-039, SC-006-SC-014

**Dependencies**:

T088, T089.

**Required changes**:

Replace planning-level generic safe journey language with final concrete `liveJourneyId`, scenario ids, report fields, skip boundaries, artifact policy, budget accounting and scenario independence rules used by the implementation.

**Verification**:

Real-tour page object, quickstart and summary report use the same journey id and scenario ids.

---

### T101: Update quickstart verification notes

**File**: `specs/011-desktop-ux-debug-regression/quickstart.md` (modified)

**Requirements**:

All success criteria.

**Dependencies**:

T096, T097, T100.

**Required changes**:

Update commands for backend tests, frontend lint/unit/E2E, controlled real-tour failure tests and manual real-tour evidence. Include expected local report path, three-run evidence rule, credential mutation invariant and debug inspector manual smoke steps.

**Verification**:

A maintainer can follow the quickstart without reading implementation code.

---

### T102: Run backend validation commands

**File**: validation command set from `specs/011-desktop-ux-debug-regression/quickstart.md` (modified by execution)

**Requirements**:

SC-004, SC-005, SC-010, SC-012, SC-013, SC-015, SC-016

**Dependencies**:

Backend implementation and tests complete.

**Required changes**:

Run backend pytest suites for business debug, desktop API, integration and guardrails, then run py_compile for desktop API entrypoints. Record failures in the implementation notes or fix them before marking complete.

**Verification**:

Commands listed in quickstart complete successfully or carry explicit documented exceptions.

---

### T103: Run frontend lint/unit/E2E validation commands

**File**: validation command set from `specs/011-desktop-ux-debug-regression/quickstart.md` (modified by execution)

**Requirements**:

SC-001, SC-002, SC-003, SC-005, SC-007, SC-015

**Dependencies**:

Frontend implementation and tests complete.

**Required changes**:

Run `npm run lint`, `npm run test` and controlled `npm run test:e2e` from `frontend/`. Fix failures before marking complete or document exceptions in the plan/PR context.

**Verification**:

Frontend validation commands complete successfully.

---

### T104: Run real-tour controlled failure and sanitized report validation

**File**: validation command set from `specs/011-desktop-ux-debug-regression/quickstart.md` (modified by execution)

**Requirements**:

SC-006, SC-008, SC-009, SC-012, SC-014

**Dependencies**:

US3 implementation complete.

**Required changes**:

Run controlled real-tour failure tests and artifact sanitizer tests without live capture or paid calls. Manual real-tour evidence remains opt-in and should be recorded only as sanitized summary reports tied to commit and journey identity.

**Verification**:

Controlled failure tests pass and generated reports pass sentinel scanning.

---

## Checklist

- [ ] T001: Create shared long-paste fixtures in `frontend/tests/fixtures/longPasteFixtures.ts`
- [ ] T002: Create debug package marker in `src/business/debug/__init__.py`
- [ ] T003: Create debug API router scaffold in `src/desktop_api/routers/debug.py`
- [ ] T004: Create typed debug API client scaffold in `frontend/src/api/debug.ts`
- [ ] T005: Create hidden debug screen scaffold in `frontend/src/screens/debug/DebugScreen.tsx`
- [ ] T006: Create real Grand Tour runtime helper scaffold in `frontend/tests/e2e/helpers/real-grand-tour-runtime.ts`
- [ ] T007: Create provider inventory scaffold in `tests/guardrails/debug_provider_inventory.json`
- [ ] T008: Add paste qualification threshold boundary, mixed-newline counting, and selection-preservation hook tests
- [ ] T009: Add Assistant composer long-paste RTL tests
- [ ] T010: Add Teaching composer long-paste RTL tests
- [ ] T011: Add controlled long-paste composer E2E coverage
- [ ] T012: Implement shared long-paste hook
- [ ] T013: Implement accessible compact/expanded preview controls
- [ ] T014: Wire shared long-paste handling into Assistant message sending
- [ ] T015: Wire shared long-paste handling into Teaching ChatComposer sending
- [ ] T016: Add long-paste preview layout, focus, and compact textarea styling
- [ ] T017: Reset Assistant long-paste state on accepted send and session changes
- [ ] T018: Reset Teaching long-paste state across intent conversation lifecycle changes
- [ ] T019: Reset Teaching long-paste state across trial conversation lifecycle changes
- [ ] T020: Create debug business test fixtures and fake clock/provider helpers
- [ ] T021: Add runtime-only debug config default and invalid-value tests
- [ ] T022: Add trace arm warning, enable, disable, clear, and restart lifecycle tests
- [ ] T023: Add trace buffer record-count, per-record bytes, aggregate bytes, eviction, and mid-flight epoch tests
- [ ] T024: Add fail-isolated observation boundary tests
- [ ] T025: Add multimodal trace tests
- [ ] T026: Add reference expansion auth, response-budget, not-found, and redaction tests
- [ ] T027: Add debug REST auth, disabled fail-closed, warning-required, DTO, and no-store tests
- [ ] T028: Add Teaching and Assistant Agent Flow transition matrix tests
- [ ] T029: Add raw diagnostic leakage guard tests
- [ ] T030: Add static model/provider invocation inventory guard tests
- [ ] T031: Add DebugScreen warning, arm, trace list/detail, flow, reference, clear, and local purge tests
- [ ] T032: Add hidden route and trace-active stop banner tests
- [ ] T033: Add controlled Debug Inspector E2E smoke coverage
- [ ] T034: Add runtime-only debug config accessors/defaults
- [ ] T035: Define trace, control, flow, reference, limit, and diagnostic availability models
- [ ] T036: Implement application-controlled secret and runtime-token redaction
- [ ] T037: Implement nested and reset-safe trace capture context helpers
- [ ] T038: Implement epoch-scoped thread-safe trace buffer
- [ ] T039: Implement fail-isolated model observation helpers
- [ ] T040: Implement DebugInspectorService control, trace query/detail, clear, status, and read gates
- [ ] T041: Implement reference expansion facade
- [ ] T042: Implement Agent Flow projection and trace mapping
- [ ] T043: Route chat and chat_with_tools through observation boundary and remove raw debug logging
- [ ] T044: Migrate vision/multimodal helper calls into the observation boundary
- [ ] T045: Set session, agent, workflow, and iteration trace context around AgentLoop model calls
- [ ] T046: Set review source trace context without changing reviewer behavior
- [ ] T047: Propagate background brain source/work-unit trace context
- [ ] T048: Set compression source trace context and register compression credential/provider handling
- [ ] T049: Register skill-composition LLM callsites in provider/redaction inventory
- [ ] T050: Register embedding credential/callsite coverage while keeping embedding out of LLM trace records
- [ ] T051: Capture Assistant delegated task/result as trace-gated ephemeral debug detail
- [ ] T052: Add repository query helpers for flow summaries
- [ ] T053: Replace raw Assistant delegation ordinary logs with safe summaries
- [ ] T054: Add Debug Inspector request/response DTOs and stable error shapes
- [ ] T055: Implement authenticated `/api/debug` control, trace, flow, reference, clear, and no-store responses
- [ ] T056: Register debug router under existing session-token middleware
- [ ] T057: Implement typed debug control/data client methods
- [ ] T058: Separate ordinary navigation routes from hidden `/debug` route resolution
- [ ] T059: Implement hidden DebugScreen warning, arm, disabled state, clear, and purge-on-leave behavior
- [ ] T060: Implement trace grouping, trace list, detail, oversized, and diagnostic-unavailable UI
- [ ] T061: Implement Agent Flow timeline, provenance labels, linked/unlinked status, and trace navigation
- [ ] T062: Implement reference expansion, not-found, truncated/chunked, and clear handling
- [ ] T063: Add trace-active shell indicator and stop action wired to debug control
- [ ] T064: Add Debug Inspector and trace-active banner styling
- [ ] T065: Extend UI event payload safety checks
- [ ] T066: Populate static provider/direct-invoke inventory
- [ ] T067: Add read-only credential resolver and no-migration tests
- [ ] T068: Add real-tour provider injection and unmet-prerequisite tests
- [ ] T069: Add real-tour runtime gating and budget unit tests
- [ ] T070: Add event watcher replay/resync and last-observable-state unit tests
- [ ] T071: Add summary report and artifact sanitizer guard tests
- [ ] T072: Add keyring mutation audit guard tests
- [ ] T073: Add default regression separation E2E coverage
- [ ] T074: Add controlled real-tour failure injection coverage
- [ ] T075: Implement side-effect-free keyring-only credential resolver and mutation guard hooks
- [ ] T076: Inject read-only credential provider into main LLM construction for real-tour runtime
- [ ] T077: Inject read-only credential provider into vision model construction
- [ ] T078: Inject or explicitly skip background brain model construction for real-tour runtime
- [ ] T079: Route settings connection validation through a read-only credential snapshot during real-tour runtime
- [ ] T080: Route or skip skill-composition LLM construction under real-tour provider inventory
- [ ] T081: Route or avoid compression LLM construction under real-tour provider inventory
- [ ] T082: Route or disable embedding credential lookup under real-tour provider inventory
- [ ] T083: Implement real-tour runtime bootstrap, random port/token, temporary data dir, opt-in gates, and cleanup
- [ ] T084: Implement authenticated public event watcher with replay/resync handling
- [ ] T085: Implement paid-call and elapsed-time budget accounting
- [ ] T086: Implement sanitized summary report writer and sentinel scanner
- [ ] T087: Implement credential fingerprint and mutation audit helper
- [ ] T088: Implement scripted safe live journey page object
- [ ] T089: Implement opt-in headed manual real Grand Tour scenarios
- [ ] T090: Add `test:e2e:grand-tour` script
- [ ] T091: Add real-tour Playwright config with artifacts off by default
- [ ] T092: Keep existing default Grand Tour controlled, mock-backed, and cost-free
- [ ] T093: Add real-tour opt-in environment handling that does not affect default E2E
- [ ] T094: Document concrete safe live journey steps
- [ ] T095: Ensure local summary output remains ignored
- [ ] T096: Update architecture documentation
- [ ] T097: Update development constraints
- [ ] T098: Update frontend AI entry mirrors
- [ ] T099: Update backend AI entry mirrors
- [ ] T100: Update Grand Tour contract
- [ ] T101: Update quickstart verification notes
- [ ] T102: Run backend validation commands
- [ ] T103: Run frontend lint/unit/E2E validation commands
- [ ] T104: Run real-tour controlled failure and sanitized report validation
