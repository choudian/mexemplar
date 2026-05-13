# Design Control Inventory: UI Stack Redesign

**Baseline**: 2026-05-09 Mexemplar prototype under `C:\Users\gaopan\Downloads\mexamplar`
**Purpose**: Trace visible prototype controls to real product behavior, validation, or approved removal before acceptance.

## Disposition Rules

- `wire`: enabled control invokes a real backend API, Tauri command, or business workflow.
- `validate`: control remains visible but returns a real validation/business error when prerequisites are missing.
- `disable`: control is visibly unavailable with user-facing reason from product state.
- `remove`: control is removed only when the approved baseline is revised and this inventory records the reason.

No accepted control may use prototype-only sample state, fake counts, static rows, or a silent no-op.

## App Shell And Window

| ID | Source | Visible control/state | Required disposition | Trace |
|----|--------|-----------------------|----------------------|-------|
| SHELL-001 | `src/app.jsx` | Persistent navigation: AI Assistant, Skill Teaching, Skill List, Skill Composition, Settings | `wire` route changes and preserve same-window local state | FR-001, FR-003, FR-020, T033-T038 |
| SHELL-002 | `src/app.jsx` | Navigation badges/counts | `wire` real backend counts or hide count if product state has no value | FR-004, FR-012, SC-009, T029-T034 |
| SHELL-003 | `src/components.jsx`, `starters/macos-window.jsx` | Red/yellow/green custom window controls | `wire` red close, yellow minimize, green maximize/restore | FR-025, SC-010, T018, T032 |
| SHELL-004 | `src/app.jsx` | User/status card and backend readiness label | `wire` bootstrap and health state; no static names/status | FR-019, SC-007, T029-T036 |
| SHELL-005 | `src/app.jsx` | Theme, dark mode, font, radius, density tweaks | `wire` through Settings/config when retained as product controls; otherwise remove tweaks panel from accepted shell | FR-017, FR-026, T095-T104 |

## AI Assistant

| ID | Source | Visible control/state | Required disposition | Trace |
|----|--------|-----------------------|----------------------|-------|
| AI-001 | `src/screen-chat.jsx` | Conversation list panel toggle | `wire` to same-window UI state | FR-005, T050-T052 |
| AI-002 | `src/screen-chat.jsx` | New conversation | `wire` create session, reset draft/session confirmations as required | FR-005, FR-008, T044-T056 |
| AI-003 | `src/screen-chat.jsx` | Search conversations | `wire` real search through ChatService/API | FR-005, T044-T052 |
| AI-004 | `src/screen-chat.jsx` | Rename conversation | `wire` real rename validation/update | FR-005, T044-T052 |
| AI-005 | `src/screen-chat.jsx` | Delete conversation | `wire` delete/archive according to business semantics | FR-005, T044-T052 |
| AI-006 | `src/screen-chat.jsx` | Select historical conversation | `wire` paged display history with old/current messages merged by sequence | FR-006, CC-006, T044-T052 |
| AI-007 | `src/screen-chat.jsx` | Message composer and send button | `wire` send user message and display assistant response | FR-005, SC-002, T045-T053 |
| AI-008 | `src/screen-chat.jsx` | Attachment button | `wire`, `validate`, or remove before acceptance; no enabled no-op | FR-024, FR-026, T053 |
| AI-009 | `src/screen-chat.jsx` | Voice input button | `wire`, `validate`, or remove before acceptance; no enabled no-op | FR-024, FR-026, T053 |
| AI-010 | `src/screen-chat.jsx` | Skill availability pill/count | `wire` real published skill count | FR-004, FR-012, T029-T050 |
| AI-011 | `src/screen-chat.jsx` | Empty-state suggestion buttons | `wire` fill/send real prompts or route to teaching/composition workflows | FR-004, FR-024, T051-T053 |
| AI-012 | `src/screen-chat.jsx` | Repetition suggestion: start teaching / dismiss | `wire` to teaching route or persistent dismiss state when retained | FR-021, FR-024, T051-T056 |
| AI-013 | `src/screen-chat.jsx` | Compact execution strip and expanded process details | `wire` real assistant progress events and safe summaries | FR-007, CC-006, T046-T056 |
| AI-014 | Product requirement | High-risk confirmation toast | `wire` existing non-modal confirmation protocol, independent from normal toasts | FR-008, CC-006, T047-T056 |

## Skill Teaching

| ID | Source | Visible control/state | Required disposition | Trace |
|----|--------|-----------------------|----------------------|-------|
| TEACH-001 | `src/screen-teach.jsx` | Recording mode segmented selector: browser, extension, desktop | `wire` real readiness/setup state for all modes | FR-009, CC-007, T061-T068 |
| TEACH-002 | `src/screen-teach.jsx` | Extension certificate one-click install | `wire` real certificate action or real unavailable validation | FR-009, FR-026, T062-T068, T096 |
| TEACH-003 | `src/screen-teach.jsx` | Start recording | `wire` mode-specific recording start; desktop waits for minimize callback | FR-010, FR-011, T061-T069 |
| TEACH-004 | `src/screen-teach.jsx` | Recording HUD/timer/captured counts/event stream | `wire` real recording progress events and counts | FR-004, FR-011, T063-T069 |
| TEACH-005 | `src/screen-teach.jsx` | Pause recording | `wire`, `validate`, or remove before acceptance; no enabled no-op | FR-024, FR-026, T063-T069 |
| TEACH-006 | `src/screen-teach.jsx` | Stop and continue | `wire` recording stop, summary, and desktop health review path | FR-010, FR-011, T063-T069 |
| TEACH-007 | `src/screen-teach.jsx` | Intent questions, answer options, supplemental note | `wire` PM clarification and answer submission | FR-010, T061-T070 |
| TEACH-008 | `src/screen-teach.jsx` | Confirm intent and start learning | `wire` learning workflow start | FR-010, T061-T071 |
| TEACH-009 | `src/screen-teach.jsx` | Learning progress/retry/blocked/failure states | `wire` Agent and teaching failure events | FR-010, FR-011, T061-T071 |
| TEACH-010 | `src/screen-teach.jsx` | Trial validation, retry, view details, use in chat | `wire` configured success threshold, trial start/progress, publish route | FR-011, SC-003, T061-T072 |

## Skill List

| ID | Source | Visible control/state | Required disposition | Trace |
|----|--------|-----------------------|----------------------|-------|
| SKILL-001 | `src/screen-skills.jsx` | Tabs: pending, mastered/published, failed | `wire` real categories, counts, empty states | FR-012, SC-004, T077-T087 |
| SKILL-002 | `src/screen-skills.jsx` | Search skills | `wire` real category search/filter or disable with unavailable reason | FR-024, FR-026, T077-T087 |
| SKILL-003 | `src/screen-skills.jsx` | Teach new skill | `wire` route to Skill Teaching | FR-013, T086 |
| SKILL-004 | `src/screen-skills.jsx` | Pending skill trial start | `wire` trial validation workflow | FR-013, T077-T087 |
| SKILL-005 | `src/screen-skills.jsx` | Published skill cards and usage metadata | `wire` real SkillsService DTOs | FR-012, T077-T087 |
| SKILL-006 | `src/screen-skills.jsx` | Failure retry | `wire` existing retry coordinator behavior | FR-013, T077-T087 |
| SKILL-007 | `src/screen-skills.jsx` | Failure ignore/dismiss | `wire` existing failure dismissal behavior | FR-013, T077-T087 |

## Skill Composition

| ID | Source | Visible control/state | Required disposition | Trace |
|----|--------|-----------------------|----------------------|-------|
| COMP-001 | `src/screen-combos.jsx` | Composition list, published/review badges, create tile | `wire` real composition list and review state | FR-014, FR-016, T079-T090 |
| COMP-002 | `src/screen-combos.jsx` | New composition / return list | `wire` draft creation and navigation state | FR-014, T080-T089 |
| COMP-003 | `src/screen-combos.jsx` | Range/ordered mode picker | `wire` real mode semantics and validation | FR-014, FR-015, T080-T090 |
| COMP-004 | `src/screen-combos.jsx` | Member selector and search | `wire` published skills only; real empty state | FR-014, T079-T090 |
| COMP-005 | `src/screen-combos.jsx` | Ordered member move up/down | `wire` contiguous order validation | FR-014, FR-015, T089-T090 |
| COMP-006 | `src/screen-combos.jsx` | AI recommend order | `wire` real helper or validation/business error | FR-014, FR-026, T080-T090 |
| COMP-007 | `src/screen-combos.jsx` | Name, description, required applicability | `wire` draft/update validation | FR-014, T080-T089 |
| COMP-008 | `src/screen-combos.jsx` | One-click applicability generation | `wire` real LLM/helper or validation/business error | FR-014, FR-026, T080-T089 |
| COMP-009 | `src/screen-combos.jsx` | Save draft, try, publish | `wire` real draft/trial/publish workflows | FR-014, SC-005, T080-T089 |
| COMP-010 | `src/screen-combos.jsx` | Edit and trial buttons on existing compositions | `wire` real edit/trial routes | FR-014, FR-016, T080-T089 |

## Settings

| ID | Source | Visible control/state | Required disposition | Trace |
|----|--------|-----------------------|----------------------|-------|
| SET-001 | `src/screen-settings.jsx` | Settings sections: AI, Recording, Data, About | `wire` schema and values from settings API | FR-017, T095-T104 |
| SET-002 | `src/screen-settings.jsx` | AI provider/model/temperature | `wire` unified config defaults, validation, and saves | FR-017, CC-004, T095-T104 |
| SET-003 | `src/screen-settings.jsx` | API key display/update/test | `wire` masked keyring state, write-only update, real test action | FR-017, SC-006, T091-T104 |
| SET-004 | `src/screen-settings.jsx` | Cross-session memory and repetition recognition toggles | `wire` unified config/business behavior or real unavailable state | FR-017, FR-026, T095-T104 |
| SET-005 | `src/screen-settings.jsx` | Recording quality, video, frame rate, browser type, desensitization, cache | `wire` recording config validation and saves | FR-017, CC-007, T095-T104 |
| SET-006 | `src/screen-settings.jsx` | Database type, data directory browse, backup, vector index | `wire` supported safe config/actions or real validation errors; no direct UI storage edits | FR-017, CC-003, T095-T104 |
| SET-007 | `src/screen-settings.jsx` | Immediate backup, export all data, clear all memory | `wire` real business actions with confirmation where destructive | FR-017, FR-026, T096-T104 |
| SET-008 | `src/screen-settings.jsx` | About version/build | `wire` package metadata | FR-004, FR-017, T095-T104 |
| SET-009 | `src/screen-settings.jsx` | Check updates, changelog, documentation | `wire` real action handlers or validation/business errors | FR-017, FR-026, T096-T104 |

## Cross-Cutting Controls

| ID | Source | Visible control/state | Required disposition | Trace |
|----|--------|-----------------------|----------------------|-------|
| X-001 | All screens | Loading, empty, degraded, failed, and validation states | `wire` product state; no sample records or fake counts | FR-004, FR-019, SC-009, T036-T039, T105-T107 |
| X-002 | All screens | Keyboard focus, accessible names/states, reduced motion, contrast | `wire` accessible frontend primitives and smoke tests | FR-028, SC-013, T015-T016, T026, T107 |
| X-003 | All screens | Backend bridge errors and unavailable actions | `validate` through typed errors; no frontend-only fake failures | FR-019, FR-024, SC-008, T009-T024 |
