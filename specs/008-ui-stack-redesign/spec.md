# Feature Specification: UI Stack Redesign

**Feature Branch**: `008-ui-stack-redesign`
**Created**: 2026-05-10
**Status**: Verified
**Input**: User description: "docs\\local\\2026-05-10-ui-tech-stack-decision.md + C:\\Users\\gaopan\\Downloads\\mexamplar design prototype; since the UI stack is being redesigned, implement the full desktop UI from this design in one feature."

## Clarifications

### Session 2026-05-10

- Q: Once the redesigned UI is accepted, what should happen to the legacy PyQt UI? → A: Remove the legacy PyQt UI entry points and primary UI code; no fallback remains.
- Q: How much of the five-screen redesign must be backed by real product data and actions? → A: All five primary screens must use real business data and real actions; no design placeholders are allowed.
- Q: Should the redesigned desktop shell preserve the design prototype's macOS-style red/yellow/green window controls on Windows? → A: Preserve the macOS-style controls as branded custom window chrome.
- Q: If the design prototype shows settings or actions that current product behavior does not yet support, are those controls in scope? → A: Yes; every design-visible setting and action must become a real supported product capability.
- Q: Must the redesigned app migrate or remain compatible with existing local user data? → A: No; this feature may target a fresh-install experience and is not required to migrate existing local data.

## Scope, Baseline, And Acceptance Definitions

### Primary Product Areas

| Area | User-facing purpose | Completion boundary |
|------|---------------------|---------------------|
| AI Assistant | Start and continue conversations, run skill-aware assistant work, inspect progress, and manage conversation history. | Conversation create/select/search/rename/delete, send/receive timeline, safe assistant markdown, compact execution summaries, and non-modal high-risk confirmations are backed by real assistant services. |
| Skill Teaching | Guide the user through recording, intent confirmation, skill learning, and trial validation. | Browser, extension, and desktop modes show real readiness; start/stop/health decisions, PM clarification, learning progress, failure states, and trial threshold all route through existing teaching/recording workflows. |
| Skill List | Manage learned skills and teaching failures. | Pending, published, and failed categories show real counts/items and support trial start, metadata actions, retry, and dismiss through business services. |
| Skill Composition | Create and maintain range and ordered compositions from published skills. | Composition list/create/edit/member selection/reorder/applicability/trial/publish/review states use real composition validation and business workflows. |
| Settings | Configure AI, recording, data, and product information safely. | All visible non-secret settings, secret updates/tests, and action buttons use `get_unified_config()`, keyring-backed secret paths, or real business action handlers. |

All five areas are one required release scope for acceptance. A release that ships only a subset of these areas, or keeps a normal-user PyQt fallback for missing areas, does not satisfy this feature.

### Binding Design Baseline

The binding 2026-05-09 Mexemplar prototype consists of:

- `C:\Users\gaopan\Downloads\mexamplar\Mexemplar.html`
- `C:\Users\gaopan\Downloads\mexamplar\uploads\FEATURES.md`
- `C:\Users\gaopan\Downloads\mexamplar\src\app.jsx`
- `C:\Users\gaopan\Downloads\mexamplar\src\components.jsx`
- `C:\Users\gaopan\Downloads\mexamplar\src\icons.jsx`
- `C:\Users\gaopan\Downloads\mexamplar\src\screen-chat.jsx`
- `C:\Users\gaopan\Downloads\mexamplar\src\screen-teach.jsx`
- `C:\Users\gaopan\Downloads\mexamplar\src\screen-skills.jsx`
- `C:\Users\gaopan\Downloads\mexamplar\src\screen-combos.jsx`
- `C:\Users\gaopan\Downloads\mexamplar\src\screen-settings.jsx`
- `C:\Users\gaopan\Downloads\mexamplar\starters\macos-window.jsx`
- `C:\Users\gaopan\Downloads\mexamplar\starters\tweaks-panel.jsx`

Reviewers compare the redesigned product against this baseline for layout, navigation, visual density, component hierarchy, page flow, custom window chrome, and visible workflow vocabulary. The visible control inventory for implementation traceability is maintained in [control-inventory.md](./control-inventory.md).

### Acceptance Definitions

- **Real product data** means values returned by approved Python business services, bridge DTOs, configuration services, keyring-backed secret status, recording services, or controlled test fixtures. It excludes prototype constants, fake counts, static sample names, decorative rows, and enabled no-op controls. Supported empty, loading, degraded, and error states are real product states when they come from the bridge or fixture contract.
- **Same-window state preservation** means navigation keeps local UI state that would otherwise cause user work loss: assistant draft text and selected conversation, open/closed assistant history panel, teaching mode and active stage, selected skill/composition tabs, composition draft fields and member order, settings section, dirty values, validation messages, and expanded/collapsed details. State may reset only after an explicit user reset/delete action, app reload, route-owned workflow completion, or backend invalidation event.
- **Compact execution summary** means assistant progress is collapsed by default into one row or chip group containing status, concise headline, skill/tool count when available, elapsed or finished state, and any user-action requirement. Details are expandable on demand; raw prompts, internal archive/compression terms, full file contents, multiline command bodies, and implementation-only traces are not shown in the compact state.
- **Visible control disposition** must be one of: fully wired to a real workflow, disabled with explicit unavailable-state feedback from a real validation/business condition, or removed because the approved design no longer contains it. An enabled control that silently no-ops or mutates only frontend mock state fails acceptance.
- **Prototype/product conflict resolution**: the prototype is binding for visible surface and workflow vocabulary; existing product semantics and the Constitution are binding for data, security, configuration, recording, repository, and event behavior. If a prototype-visible control conflicts with safe product semantics, implementation must preserve the visible intent while mapping it to an existing business workflow or adding a real capability that obeys the architecture rules. A conflict may not be resolved by weakening layer, storage, secret, event, or confirmation constraints.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Use The Redesigned App Shell (Priority: P1)

As a desktop user, I want the application to open into the redesigned Mexemplar shell with the five primary product areas available from a persistent navigation rail, so that the new product experience replaces the current widget-based interface as one coherent desktop app.

**Why this priority**: This is the foundation for the full redesign. Without the new shell and navigation model, the individual screens cannot be evaluated as one product.

**Independent Test**: Launch the application and verify that the redesigned shell opens, displays the product identity, and allows navigation among AI Assistant, Skill Teaching, Skill List, Skill Composition, and Settings without falling back to the old UI.

**Acceptance Scenarios**:

1. **Given** the user launches Mexemplar, **When** the desktop window becomes ready, **Then** the redesigned app shell is visible with AI Assistant selected by default.
2. **Given** the redesigned app shell is open, **When** the user selects each primary navigation item, **Then** the matching redesigned screen is shown in the same desktop window.
3. **Given** the user switches between primary screens, **When** they return to a screen with in-progress UI state, **Then** the screen preserves the same-window state defined in this specification unless the user explicitly reset it or the backend invalidated it.
4. **Given** the redesigned app shell is running on Windows, **When** the user uses the branded red/yellow/green window controls, **Then** red closes, yellow minimizes, and green toggles maximize/restore through real window behavior.

---

### User Story 2 - Work In The Redesigned AI Assistant (Priority: P1)

As a user, I want the AI Assistant screen to support everyday conversations, skill-aware task execution, visible execution progress, and conversation management in the new design, so that the main assistant workflow is usable without the legacy chat UI.

**Why this priority**: AI Assistant is the default entry point and the highest-frequency workflow. It also exercises the most important backend integration path.

**Independent Test**: Start a new conversation, send a message, receive an assistant response, inspect a folded execution summary, and manage the conversation list entirely from the redesigned screen.

**Acceptance Scenarios**:

1. **Given** the user is on AI Assistant, **When** they start a new conversation and send a message, **Then** the message appears in a continuous chat timeline and the assistant response appears in the same timeline.
2. **Given** an assistant response uses internal reasoning or skills, **When** the response is displayed, **Then** the user sees a compact execution summary that can be expanded for details without overwhelming the answer.
3. **Given** historical conversations exist, **When** the user opens the conversation list, searches, selects, renames, or deletes a conversation, **Then** the visible result matches the requested conversation action.
4. **Given** a high-risk assistant action requires confirmation, **When** the confirmation is requested, **Then** the redesigned UI presents the existing non-modal confirmation behavior without blocking normal toast notifications or restoring modal question dialogs.

---

### User Story 3 - Teach A Skill In The Redesigned Flow (Priority: P1)

As a user, I want skill teaching to guide me through recording, intent confirmation, learning, and trial validation in the redesigned flow, so that I can teach a new skill without understanding internal implementation details.

**Why this priority**: Skill teaching is the core "teach once, automate later" product promise and must be first-class in the redesigned UI.

**Independent Test**: Walk through each visible teaching stage using at least one recording mode and verify that the UI advances only when the expected user or system result is available.

**Acceptance Scenarios**:

1. **Given** the user opens Skill Teaching, **When** they choose Browser Recording, Extension Recording, or Desktop Recording, **Then** the selected mode clearly explains readiness, setup needs, and the action to start recording.
2. **Given** recording is active, **When** the user stops recording, **Then** the UI advances to intent confirmation with a summary and any necessary questions.
3. **Given** the user confirms the intended skill, **When** learning begins, **Then** progress and failures are shown in the redesigned flow and the user can understand whether the system is learning, retrying, or blocked.
4. **Given** a skill is generated, **When** the user runs trial validation, **Then** the UI shows the trial count and publishes only after the configured success requirement is met.

---

### User Story 4 - Manage Skills And Skill Compositions (Priority: P1)

As a user, I want the redesigned Skill List and Skill Composition screens to manage individual skills and multi-skill combinations, so that the new UI covers the complete learned-skill lifecycle.

**Why this priority**: These screens make learned automation visible, reusable, and maintainable after teaching.

**Independent Test**: Use the redesigned Skill List to inspect pending, mastered, and failed skills; then create and inspect both range and ordered skill compositions from published skills.

**Acceptance Scenarios**:

1. **Given** the user opens Skill List, **When** they switch between pending, mastered, and failure tabs, **Then** each tab shows the correct category, count, actions, and empty state.
2. **Given** a pending skill exists, **When** the user starts trial validation from Skill List, **Then** the system routes to the appropriate trial workflow.
3. **Given** a failed teaching record exists, **When** the user retries or ignores it, **Then** the visible status updates consistently with the existing failure-resolution behavior.
4. **Given** the user opens Skill Composition, **When** they create a composition, **Then** the range/ordered mode choice is visible, members can be selected, ordered compositions can be reordered, and the applicable scenario is required before publish-ready state.
5. **Given** a published member skill changes, **When** a composition depends on it, **Then** the composition is marked for review and is not silently exposed as current.

---

### User Story 5 - Configure The App In The Redesigned Settings (Priority: P1)

As a user, I want Settings to expose AI, recording, data, and product information through the redesigned UI while preserving existing configuration safety rules, so that configuration changes feel native but remain safe.

**Why this priority**: A full UI replacement is incomplete if users must return to the old UI or edit files for normal app settings.

**Independent Test**: View and modify supported settings from the redesigned Settings screen, verify validation feedback, and confirm that sensitive values are never shown or stored unsafely.

**Acceptance Scenarios**:

1. **Given** the user opens Settings, **When** they navigate AI, Recording, Data, and About sections, **Then** each section shows current product state rather than static design placeholders.
2. **Given** the user edits a supported non-secret setting, **When** the value is valid, **Then** the setting is saved through the existing configuration path and takes effect according to the current product contract.
3. **Given** the user edits or tests a secret value, **When** the UI displays or stores the value, **Then** the value is masked in the UI and stored through the existing secret-storage path.
4. **Given** a setting value is invalid or unavailable, **When** the user attempts to save or test it, **Then** the UI gives clear feedback and preserves the last valid state.
5. **Given** the approved design exposes a setting or action that the current product does not yet support, **When** the redesigned Settings screen is accepted, **Then** that setting or action is implemented as a real product capability rather than removed, hidden, or left as a demo control.

### Edge Cases

- Backend startup is slow, unavailable, or exits after the desktop shell opens.
- The user has no conversations, no learned skills, no pending skills, no failed teaching records, or no published skills for composition.
- A conversation contains long history, prior compressed context, markdown assistant output, or tool execution traces.
- A high-risk assistant action is queued while the user starts a new conversation or switches screens.
- Browser, extension, or desktop recording prerequisites are missing, partially configured, or denied by the operating system.
- Desktop recording sanity check fails after stop and the user chooses continue, discard, or re-record.
- A skill composition loses a member skill or a member becomes unpublished.
- Settings contain unavailable providers, missing secrets, invalid data directories, or values changed outside the UI.
- The redesigned app is packaged but the backend process fails to start, fails health checks, or cannot be shut down cleanly.
- Existing local data from the legacy UI is present on disk; the redesigned app may ignore it, but must not silently corrupt, delete, or mutate it.
- A keyboard-only user navigates the shell, screens, dialogs/toasts, custom chrome controls, and all form/action controls without pointer input.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST launch into a redesigned desktop app shell that covers the full primary UI surface in the same release: AI Assistant, Skill Teaching, Skill List, Skill Composition, and Settings.
- **FR-002**: System MUST use the 2026-05-09 Mexemplar design prototype as the visual and interaction baseline for layout, navigation, density, component hierarchy, and page flow.
- **FR-003**: Users MUST be able to navigate among the five primary screens from a persistent navigation rail without opening separate legacy windows for normal workflows.
- **FR-004**: System MUST replace all static design sample data and placeholder controls with real product data, real empty/loading/error states, and real business actions before any of the five primary screens is considered complete.
- **FR-005**: AI Assistant MUST support new conversation creation, conversation selection, conversation search, rename/delete actions, message composition, message sending, continuous timeline display, and assistant response rendering.
- **FR-006**: AI Assistant MUST preserve current chat-history semantics: old and current messages appear as one continuous user-facing timeline, and the UI MUST NOT expose archive/compression partition terminology.
- **FR-007**: AI Assistant MUST show assistant execution progress as compact summaries by default, with a way to inspect details when the user asks for them, following the compact execution summary definition above.
- **FR-008**: AI Assistant MUST preserve the existing non-modal high-risk confirmation model for assistant file/edit/exec actions, including queued confirmations and new-conversation cleanup semantics.
- **FR-009**: Skill Teaching MUST present Browser Recording, Extension Recording, and Desktop Recording as selectable modes with readiness/setup guidance and mode-specific start behavior.
- **FR-010**: Skill Teaching MUST guide the user through selection, recording, intent confirmation, skill learning, and trial validation as visible stages in one redesigned flow.
- **FR-011**: Skill Teaching MUST preserve existing recording and trial semantics, including desktop recording health review, syntax-gate retry feedback, and the configured trial success threshold before publish.
- **FR-012**: Skill List MUST display pending validation skills, mastered/published skills, and failure records as distinct user-facing categories with accurate counts and category-specific actions.
- **FR-013**: Skill List MUST support starting trial validation for pending skills and retrying or ignoring failure records through existing business workflows.
- **FR-014**: Skill Composition MUST support listing compositions, creating a new composition, selecting range or ordered mode, selecting published member skills, ordering members for ordered mode, writing an applicable scenario, trying the composition, and publishing it when valid.
- **FR-015**: Skill Composition MUST preserve the product meaning of range mode as a bounded skill toolbox where the assistant may use one, many, or none of the members, and ordered mode as an explicit ordered execution contract.
- **FR-016**: Skill Composition MUST mark affected compositions for review when member changes make their published behavior stale.
- **FR-017**: Settings MUST display and update all AI, recording, data, and product information exposed by the approved design through real configuration, secret-storage, or business workflows rather than direct file edits from the UI.
- **FR-018**: System MUST package the redesigned UI and existing backend capabilities as one desktop product so normal users do not manually start or monitor a backend process.
- **FR-019**: System MUST detect backend connection, health, startup, and shutdown failures and present recoverable user-facing states in the redesigned shell.
- **FR-020**: System MUST preserve the current architectural boundary that UI calls business services/bridges and never directly accesses repositories or storage engines.
- **FR-021**: System MUST keep existing business, execution, data, recording, memory, and assistant orchestration behavior semantically compatible for existing capabilities while adding any new real capabilities required by the approved design.
- **FR-022**: System MUST remove the legacy PyQt UI entry points and primary UI code when the redesigned UI passes acceptance; normal users and developers must not rely on a maintained legacy UI fallback after this feature is complete.
- **FR-023**: System MUST include regression coverage for each migrated screen's primary workflow and for the bridge between the redesigned UI and existing backend behavior.
- **FR-024**: System MUST remove, disable with explicit unavailable-state feedback, or fully wire every visible action control from the design; no clickable control may imply a supported workflow unless it invokes a real business path or returns a real validation/business error.
- **FR-025**: System MUST preserve the design prototype's red/yellow/green window controls as branded custom chrome in the accepted desktop shell; red MUST close, yellow MUST minimize, and green MUST toggle maximize/restore on Windows.
- **FR-026**: System MUST implement every setting, command, and action visible in the approved design as a real supported capability by feature acceptance, including capabilities not present in the legacy UI, and each visible control MUST trace to [control-inventory.md](./control-inventory.md).
- **FR-027**: System is NOT required to migrate or remain compatible with legacy local user data for this feature, but it MUST avoid silently corrupting, deleting, or mutating any legacy data it does not migrate.
- **FR-028**: The redesigned desktop shell and all interactive controls MUST be keyboard operable, expose accessible names/states through web semantics, show visible focus, preserve readable contrast in light and dark modes, and respect reduced-motion preferences for non-essential animations.

### Key Entities *(include if feature involves data)*

- **Design Baseline**: The approved 2026-05-09 Mexemplar prototype and feature list that define the intended visual direction, page set, and user-facing workflow vocabulary.
- **App Shell**: The top-level desktop experience containing product identity, window chrome, persistent navigation, user/status area, and the active screen.
- **Chat Session**: A user conversation with ordered messages, display history, assistant responses, execution summaries, and high-risk confirmation state.
- **Skill Teaching Run**: A user-guided teaching workflow with selected recording mode, captured recording result, intent clarification state, learning progress, and trial progress.
- **Skill**: A learned automation capability with validation state, publication state, source mode, usage metadata, and failure or retry context.
- **Skill Composition**: A reusable grouping of published skills with range or ordered mode, member list, applicability description, review status, trial state, and publication state.
- **App Setting**: A user-visible configuration item with current value, validation rules, storage safety requirements, and effective-change behavior.
- **Backend Connection State**: The user-visible readiness of the existing backend capabilities behind the redesigned desktop UI, including starting, ready, degraded, failed, and shutting down states.

### Constraints & Compatibility *(include when relevant)*

- **CC-001**: The feature is a full primary UI replacement, not a single-page experiment; all five main screens in the approved design are in scope for the first accepted release of this feature.
- **CC-002**: The redesigned UI must follow Exemplar's existing layer rules: UI -> business layer -> execution layer -> data/driver layer; lower layers must not call back into UI.
- **CC-003**: Business data access must continue through repositories and services; UI code must not directly query or mutate SQLite, DuckDB, config files, or keyring.
- **CC-004**: Configuration must continue through the unified configuration entry point, and secrets must continue through secret storage.
- **CC-005**: Cross-module notifications must preserve the existing event/worker boundaries, including the controlled assistant task exception for report/codify workflows.
- **CC-006**: The redesigned AI Assistant must preserve markdown safety behavior, display history pagination, and non-modal high-risk action confirmation semantics.
- **CC-007**: The redesigned recording UI must preserve browser, extension, and desktop recording mode contracts, including desktop monitor/DPI and health-review behavior.
- **CC-008**: Product vocabulary must stay user-facing: "技能教学", "技能列表", "技能组合", "范围型", and "顺序型" are visible concepts; archive/compression and internal method names are not user-facing concepts.
- **CC-009**: The design prototype is binding for visible settings and actions: sample data and fake counts must not ship, and design-visible controls must be implemented as real supported behavior by acceptance.
- **CC-010**: The accepted end state is a single redesigned UI surface; legacy PyQt UI entry points and primary UI code are removed rather than exposed as a maintained fallback.
- **CC-011**: Windows remains the primary validation platform, but the accepted product shell intentionally uses the design prototype's branded custom window controls rather than native-looking Windows caption buttons.
- **CC-012**: New capabilities introduced to make design-visible controls real must still obey existing layer, repository, configuration, secret-storage, and event boundaries.
- **CC-013**: Existing local data migration is out of scope for this feature; acceptance may be validated against a fresh-install profile.
- **CC-014**: Prototype-visible controls and existing product semantics must be reconciled through the conflict-resolution rule in this specification; implementation must not hide a required control merely because the legacy UI did not expose it.

## Architecture Impact *(Mexemplar-specific)*

### Layer Impact

Which layers are affected? Check all that apply:

- [x] **UI** (`src/ui/`) — primary desktop UI is replaced by the redesigned shell and screens
- [x] **Business** (`src/business/`) — bridge/service contracts are needed for all redesigned screens
- [x] **Execution** (`src/execution/`) — trial and desktop execution status must surface through the redesigned UI
- [x] **Data** (`src/data/`) — config, settings, sessions, skills, and composition state are displayed and updated through existing access paths
- [x] **Recording** (`src/recording/`) — browser, extension, and desktop recording flows are exposed in the redesigned teaching screen
- [x] **Utils** (`src/utils/`) — app readiness, events, and cross-thread notifications may need bridge-safe UI delivery

### Agent Impact *(if touching Agent system)*

- Which Agent(s) are affected: PM, Programmer, Trial, Assistant
- New tools or modified tool handlers? New user-facing capabilities may be required where the approved design exposes actions not present in the legacy UI; the redesigned UI must still call agent/tool capabilities through approved business boundaries.
- System prompt changes needed? Only if planning finds prompt text that currently assumes legacy UI wording or screen flow.
- Orchestrator dispatch changes? Not required by the specification; preserve current orchestration semantics unless planning identifies a bridge contract gap.

### Data Store Impact *(if touching data layer)*

- **SQLite** (`src/data/repos/`): Fresh-install conversation, skill, composition, setting, failure, and trial data must be surfaced through repositories/services; legacy local data migration is not required for this feature.
- **DuckDB** (`src/recording/filtering/`): Recording-analysis data remains behind existing recording data tools and services; the redesigned UI must not query DuckDB directly.
- **Config** (`src/data/unified_config.py`): Settings must read/write all design-visible configuration through the unified configuration path and preserve startup sync behavior.
- **Secrets** (keyring): API keys and other sensitive values must be masked in UI and stored only through existing secret-storage behavior.

### Event Impact *(if adding/changing events)*

- New events to define in `src/utils/events.py`: Only if planning identifies new cross-module UI status needs that cannot reuse existing events.
- Modified event payloads: Existing payloads must remain backward compatible unless explicitly changed in plan/tasks.
- New event listeners: Redesigned UI bridge listeners may be needed for recording, trial, assistant progress, confirmations, and backend health.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All five primary screens from the approved design are reachable in the packaged desktop app and pass review with no blocker or major visual-flow deviations from the design baseline.
- **SC-002**: A user can complete the AI Assistant happy path in under 2 minutes: launch app, start a new conversation, send a message, receive a response, and inspect an execution summary.
- **SC-003**: A user can complete the Skill Teaching happy path through visible stages in under 5 minutes using a scripted or controlled recording fixture, ending at trial-ready state.
- **SC-004**: A user can inspect pending, mastered, and failed skill categories and start the correct next action for each category with no legacy UI fallback.
- **SC-005**: A user can create both a range composition and an ordered composition from published skills, including scenario text and member validation, with no direct data-store editing.
- **SC-006**: A user can view and update supported non-secret settings from the redesigned Settings screen, while secret values remain masked in 100% of normal UI states.
- **SC-007**: Backend startup, ready, degraded, failed, and shutdown states are represented in the redesigned UI, and at least 95% of normal launches reach an interactive ready state within 10 seconds on the target development machine.
- **SC-008**: Automated or scripted regression coverage exercises at least one primary workflow per redesigned screen and at least one backend bridge failure state.
- **SC-009**: A product review of all five redesigned screens finds zero visible sample records, fake counts, or pretend actions in accepted normal states.
- **SC-010**: On Windows, close, minimize, and maximize/restore pass manual and automated smoke checks through the branded red/yellow/green window controls.
- **SC-011**: A review of every visible design control finds 100% of settings, commands, and actions either successfully executing a real supported workflow or failing with a real validation/business error from that workflow.
- **SC-012**: Fresh-install acceptance runs complete without requiring any pre-existing local user data, and a safety check confirms legacy local data is not silently modified during launch.
- **SC-013**: Keyboard-only and accessibility smoke checks pass for route navigation, custom window controls, assistant compose/send, teaching mode selection, skill/composition tabs and actions, composition forms, settings forms, non-modal confirmations, and toast/action feedback.

### Measurement Rules

- **Design review severity** for SC-001: a blocker deviation prevents the primary workflow from being completed or contradicts the approved five-screen navigation model; a major visual-flow deviation changes screen hierarchy, navigation placement, information density, or page flow enough that a reviewer cannot map it to the baseline without explanation.
- **AI Assistant happy path timing** for SC-002 starts when the user launches the packaged desktop app and ends when an assistant response plus expandable execution summary is visible after sending the first message.
- **Skill Teaching happy path timing** for SC-003 starts when the user selects a recording mode in the packaged shell and ends when the controlled fixture reaches trial-ready state.
- **Launch readiness timing** for SC-007 starts when the packaged app process is started and ends when the shell is interactive and backend state is `ready` or an explicitly recoverable `degraded` state.
- **No sample/fake audit** for SC-009 checks normal, empty, loading, degraded, and error states across all five screens. Fixture data is allowed only when the test name and environment identify it as a controlled acceptance fixture.
- **Visible control audit** for SC-011 uses [control-inventory.md](./control-inventory.md) as the trace list and fails if any enabled visible control lacks a real endpoint, Tauri command, or business validation/error path.

## Assumptions

- The approved design baseline is the 2026-05-09 prototype under `C:\Users\gaopan\Downloads\mexamplar`, including `Mexemplar.html`, `src/screen-*.jsx`, shared components, `starters/`, and `uploads/FEATURES.md`; [control-inventory.md](./control-inventory.md) records the traceable visible control list derived from those files.
- The local decision document `docs/local/2026-05-10-ui-tech-stack-decision.md` records the implementation direction; this specification keeps implementation details for planning while preserving the user-visible scope and compatibility rules.
- "一次出锅" means the first accepted release of this feature covers all five primary screens, while plan/tasks may still split the work into independently testable implementation slices.
- Existing Python business, data, recording, memory, and agent behavior remains the source of truth for product semantics during the UI migration.
- Windows desktop is the primary packaging and validation target for this feature.
- The legacy PyQt UI may exist only during implementation, but the accepted end state removes its entry points and primary UI code.
- Acceptance can use a fresh-install profile; migration/import of existing local conversations, skills, settings, recordings, or memories is out of scope.
