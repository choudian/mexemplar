# Data Model: UI Stack Redesign

This model describes user-facing and bridge-facing entities for the redesigned Tauri/React desktop UI. Existing persistence models remain the source of truth unless this document explicitly marks a new DTO or derived view.

## Design Baseline

**Purpose**: Immutable reference for visual and workflow acceptance.

**Fields**:

- `baseline_id`: stable identifier, `2026-05-09-mexamplar-prototype`
- `prototype_root`: `C:\Users\gaopan\Downloads\mexamplar`
- `screens`: `assistant`, `teaching`, `skills`, `compositions`, `settings`
- `feature_document`: `uploads/FEATURES.md`
- `approved_controls`: inventory of visible settings, commands, buttons, tabs, and window controls from `control-inventory.md`

**Validation rules**:

- All accepted UI screens must trace to this baseline.
- Sample records, fake counts, and no-op controls from the prototype cannot ship.

## Design Control

**Purpose**: Trace one visible prototype control to its accepted product behavior.

**Fields**:

- `control_id`: stable inventory identifier such as `AI-007` or `SET-003`
- `source_file`: prototype file containing the visible control
- `screen`: `shell | assistant | teaching | skills | compositions | settings | cross_cutting`
- `visible_label_or_affordance`
- `required_disposition`: `wire | validate | disable | remove`
- `requirement_refs`: FR/CC/SC identifiers that govern the control
- `implementation_refs`: task IDs, endpoint names, Tauri commands, or business services

**Validation rules**:

- Every visible enabled action in the accepted UI must map to exactly one inventory row.
- `wire` controls call real backend APIs, Tauri commands, or business workflows.
- `validate` and `disable` controls must expose user-facing product state and must not silently no-op.
- `remove` requires an approved baseline update before acceptance.

## App Shell

**Purpose**: Top-level desktop experience and navigation container.

**Fields**:

- `route`: `assistant | teaching | skills | compositions | settings`
- `window_state`: `normal | minimized | maximized | closing`
- `backend_state`: reference to `BackendConnectionState`
- `navigation_counts`: real counts for skills/compositions/failures where shown
- `user_display`: display name/status from business services, never static prototype sample names
- `theme_state`: non-secret UI settings supported by product configuration

**Validation rules**:

- Default route is `assistant`.
- Red/yellow/green controls must call real minimize/maximize/restore/close actions.
- Navigation state may be local, but displayed counts and statuses must come from backend DTOs.
- Navigation, custom chrome, and screen-level actions must expose keyboard focus and accessible names/states.

## Backend Connection State

**Purpose**: User-visible readiness of the Python sidecar.

**Fields**:

- `status`: `starting | ready | degraded | failed | shutting_down`
- `port`: localhost port selected for the sidecar, not persisted
- `auth_token_state`: `issued | rejected | expired`, token value never exposed in UI
- `health_checks`: list of component checks such as config, SQLite, recording recovery, event stream
- `message`: user-facing recovery or failure message
- `last_checked_at`: timestamp

**State transitions**:

```text
starting -> ready
starting -> degraded
starting -> failed
ready -> degraded
ready -> shutting_down
degraded -> ready
degraded -> failed
failed -> starting
shutting_down -> stopped
```

**Validation rules**:

- 95% of normal launches should reach `ready` within 10 seconds.
- `failed` and `degraded` must preserve recoverable UI states and must not silently exit.

## Chat Session

**Purpose**: User-facing assistant conversation.

**Existing source**: `sessions`, `messages`, assistant memory repositories, `ChatService`.

**Fields**:

- `session_id`
- `title`
- `preview`
- `created_at`
- `updated_at`
- `messages`: paged `ChatMessage` values
- `has_more_before`
- `execution_summaries`: compact assistant progress summaries
- `pending_confirmations`: active high-risk confirmations

**Relationships**:

- Has many `ChatMessage`.
- May have many `HighRiskConfirmation`.
- Uses assistant memory summaries internally, but archive/compression terms are not user-facing.

**Validation rules**:

- Display history must merge old and current messages by `sequence`.
- UI must not show tool-only, summary, compressed, or archived implementation messages.
- Rename/delete/search actions must route through business/API contracts.

## Chat Message

**Purpose**: Displayable timeline item.

**Existing source**: `DisplayChatMessage`, `MessageRepository.get_display_page()`.

**Fields**:

- `sequence`
- `role`: `user | assistant`
- `content`
- `created_at`
- `rendering`: `plain_text | safe_markdown`
- `execution_summary_id`: optional compact execution summary reference

**Validation rules**:

- User messages render as plain text.
- Assistant markdown must preserve current raw HTML/script safety behavior.

## Assistant Execution Summary

**Purpose**: Compact, expandable representation of tool/reasoning progress.

**Fields**:

- `summary_id`
- `session_id`
- `status`: `queued | running | waiting_for_user | succeeded | failed | cancelled`
- `headline`
- `steps`: ordered `ExecutionTraceStep`
- `started_at`
- `finished_at`

**Validation rules**:

- Summary is compact by default and expandable on demand.
- Internal prompt, archive, or compression implementation terms are not shown.

## High-Risk Confirmation

**Purpose**: Non-modal assistant confirmation for file/edit/exec actions.

**Existing source**: `builtin_general_tools` confirmation protocol and AuthToast semantics.

**Fields**:

- `request_id`
- `session_id`
- `action_type`: `write_file | edit_file | exec`
- `sanitized_summary`
- `status`: `queued | active | approved | denied | timed_out | cancelled`
- `created_at`
- `expires_at`

**State transitions**:

```text
queued -> active -> approved
queued -> active -> denied
queued -> active -> timed_out
queued -> cancelled
active -> cancelled
```

**Validation rules**:

- Preserve `request_id + threading.Event + signal/request routing` semantics in backend.
- Normal toast notifications remain independent.
- Starting a new conversation must reset auto-approve and settle old active/queued confirmations as deny/timeout semantics require.

## Skill Teaching Run

**Purpose**: Redesigned teaching workflow from recording mode selection to trial validation.

**Existing source**: recording repositories, `DesktopRecordingService`, `AgentOrchestrator`, workflow transitions, teaching failure tracker.

**Fields**:

- `workflow_id`
- `mode`: `browser | extension | desktop`
- `stage`: `selecting | recording | intent_confirmation | learning | trial_validation | published | failed | abandoned`
- `readiness`: mode-specific prerequisites and setup actions
- `recording_summary`
- `intent_questions`
- `learning_progress`
- `trial_progress`
- `failure`: optional `TeachingFailure`

**State transitions**:

```text
selecting -> recording
recording -> intent_confirmation
intent_confirmation -> learning
learning -> trial_validation
trial_validation -> published
recording -> abandoned
any active stage -> failed
failed -> selecting
failed -> recording
failed -> learning
```

**Validation rules**:

- Desktop recording starts only after the app window minimize callback completes.
- Desktop sanity check choices remain continue/discard/re-record.
- Trial publish is blocked until configured success threshold is met.

## Skill

**Purpose**: Learned automation capability visible in Skill List and composition member selection.

**Existing source**: `tools` table, `SkillsService`, `ToolRepository`.

**Fields**:

- `tool_id`
- `tool_name`
- `description`
- `parameters`
- `source`
- `workflow_id`
- `status`: `pending | published | failed | offline`
- `trial_success_count`
- `created_at`
- `updated_at`
- `usage_metadata`: derived for display

**Relationships**:

- May be referenced by many `SkillCompositionMember`.
- May have one active `TeachingFailure`.

**Validation rules**:

- Pending skills expose trial validation.
- Published skills can be used by Assistant and selected for compositions.
- Skills referenced by compositions cannot be deleted without business validation.

## Teaching Failure

**Purpose**: Failure record shown in Skill List failure tab.

**Existing source**: `teaching_failure_records`, `TeachingFailureRepository`.

**Fields**:

- `record_id`
- `workflow_id`
- `tool_name`
- `failed_stage`: `pm | programmer | trial`
- `error_summary`
- `error_type`
- `status`: `active | retrying | resolved | dismissed`
- `retry_count`
- `created_at`
- `updated_at`

**Validation rules**:

- Retry uses existing retry coordinator strategies.
- Ignore/dismiss must update visible status and not delete underlying diagnostic history unless business service explicitly allows it.

## Skill Composition

**Purpose**: Reusable grouping of published skills.

**Existing source**: `skill_compositions`, `skill_composition_members`, `SkillCompositionService`.

**Fields**:

- `composition_id`
- `composition_name`
- `description`
- `applicability`
- `mode`: `range | ordered`
- `status`: persisted lifecycle, `draft | published | offline`
- `displayStatus`: API/UI presentation, `draft | published | offline | needs_review`
- `assistant_enabled`
- `recommend_order`
- `needs_review`: persisted review flag, not a lifecycle status
- `members`
- `created_at`
- `updated_at`

**Relationships**:

- Has many `SkillCompositionMember`.
- Members reference published `Skill` entities.

**State transitions**:

```text
draft -> published
published -> offline
offline -> published
```

**Validation rules**:

- `applicability` is required before publish-ready state.
- `range` mode is a bounded skill toolbox where Assistant may use one, many, or none.
- `ordered` mode is an explicit ordered execution contract.
- If a member skill changes or becomes unpublished, dependent published compositions set `needs_review = true`, return `displayStatus = "needs_review"`, and are hidden from Assistant until re-reviewed.

## Skill Composition Member

**Purpose**: Many-to-many relation between composition and skill.

**Existing source**: `skill_composition_members`.

**Fields**:

- `member_id`
- `composition_id`
- `tool_id`
- `selected_order`
- `execution_order`
- `created_at`

**Validation rules**:

- A skill may appear only once per composition in V1.
- `execution_order` is required and contiguous for ordered mode.
- Members must reference published skills when publishing.

## App Setting

**Purpose**: User-visible configuration exposed through redesigned Settings.

**Existing source**: `UnifiedConfigManager`, `app_settings`, config defaults, keyring.

**Fields**:

- `key`
- `label`
- `section`: `ai | recording | data | about`
- `value_kind`: `string | integer | boolean | enum | path | secret | action`
- `value`
- `masked_display_value`
- `validation_rules`
- `effective_change`: `immediate | next_operation | restart_required`
- `status`: `available | missing_secret | invalid | unavailable`

**Validation rules**:

- Non-secret values are saved through `UnifiedConfigManager.set()`.
- Secrets use keyring-backed methods and are never returned in plaintext.
- Design-visible actions such as test connection, backup, export, clear memory, update check, docs, and changelog must call real supported workflows or return a real business validation/error response.

## Sidecar API Session

**Purpose**: Runtime-only authorization and connectivity state between Tauri and Python.

**Fields**:

- `port`: random localhost port
- `auth_token`: random per-launch token, never persisted
- `tauri_origin`: allowed frontend origin
- `started_at`
- `expires_at`: process lifetime

**Validation rules**:

- Token must be required for all backend API and event-stream requests.
- Token must not be written to config, logs, SQLite, DuckDB, or keyring.
