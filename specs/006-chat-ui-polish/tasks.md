# Tasks: 聊天界面体验完善（Chat UI Polish）

**Input**: Design documents from `specs/006-chat-ui-polish/`
**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/chat-ui-contract.md`, `quickstart.md`
**Tests**: Included because the feature specification defines independent tests and the constitution requires automated coverage for user-visible UI flow, deterministic filtering, and architecture boundaries.

**Organization**: Tasks are grouped by user story so Markdown rendering (P1), full history replay (P2), and Toggle visibility (P3) can be implemented and validated independently.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Prepare small shared surfaces without changing behavior.

- [x] T001 Create `src/ui/widgets/markdown_message_view.py` with a minimal `MarkdownMessageView` class shell and keep `pyproject.toml` free of new Markdown parser dependencies.
- [x] T002 [P] Create `tests/ui/chat_widget_test_helpers.py` with reusable offscreen `QApplication`, `ChatWidget` factory, and widget lookup helpers based on `tests/ui/test_chat_widget_auth_toggle.py`.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Establish cross-story guardrails before implementing user-visible behavior.

**CRITICAL**: No user story work should begin until these guardrails exist.

- [x] T003 [P] Add UI layering guard tests in `tests/ui/test_chat_widget_layering.py` asserting `src/ui/widgets/chat_widget.py` imports `ChatService` and does not import `MessageRepository`, `SessionRepository`, or `src.data.repos`.
- [x] T004 [P] Add shared SQLite message seed helpers in `tests/data/chat_history_test_helpers.py` for user, assistant, tool, summary/compressed, archived, and empty-content `Message` rows.

**Checkpoint**: Test helpers and layer guards are ready; user story tasks can now proceed.

---

## Phase 3: User Story 1 - AI 回复消息以富文本展示 Markdown (Priority: P1) - MVP

**Goal**: Assistant/AI replies render Markdown as safe rich text while user messages remain plain text.

**Independent Test**: Add an assistant reply containing headings, lists, code block, bold/italic, inline code, quote, link, remote image, and GitHub pipe table; verify rich text rendering hides raw Markdown markers, while a user message containing Markdown-like text remains plain text.

### Tests for User Story 1

- [x] T005 [US1] Add Markdown rendering coverage in `tests/ui/test_chat_widget_markdown.py` for headings, ordered/unordered lists, code blocks, inline code, bold/italic, quote, divider, and GitHub pipe table.
- [x] T006 [US1] Add Markdown safety and partial-render coverage in `tests/ui/test_chat_widget_markdown.py` for raw HTML/script downgrade, remote `http(s)` image render or alt fallback, non-remote image downgrade, link click no-op, image click no-op, incomplete code fence/emphasis interim rendering without exceptions or style jitter, final streaming convergence matching one-shot rendering, and plain assistant text visual compatibility.
- [x] T007 [US1] Add user-message plain-text coverage in `tests/ui/test_chat_widget_markdown.py` proving `role="user"` content with backticks, stars, headings, and pipe characters is not parsed as Markdown.

### Implementation for User Story 1

- [x] T008 [US1] Implement `MarkdownMessageView` in `src/ui/widgets/markdown_message_view.py` using `QTextDocument.setMarkdown(... MarkdownDialectGitHub)` or equivalent Qt Markdown support.
- [x] T009 [US1] Implement Markdown safety downgrade, stable partial Markdown rendering, remote `http(s)` image allow-list with load-failure alt fallback, and navigation blocking in `src/ui/widgets/markdown_message_view.py` for raw HTML/script, `file:`/`javascript:`/non-remote image targets, `anchorClicked`, and image resources.
- [x] T010 [US1] Integrate `MarkdownMessageView` into assistant branches of `ChatWidget._add_message` in `src/ui/widgets/chat_widget.py` while keeping user branches on `QLabel` with `Qt.TextFormat.PlainText`.
- [x] T011 [US1] Add rich-text visual styles for assistant Markdown code blocks, inline code, block quotes, links, tables, and image fallback text in `src/ui/resources/styles.qss`.
- [x] T012 [US1] Validate User Story 1 with `tests/ui/test_chat_widget_markdown.py`, `src/ui/widgets/markdown_message_view.py`, and `src/ui/widgets/chat_widget.py`, including streaming partial Markdown convergence and image fallback cases.

**Checkpoint**: User Story 1 is independently functional and satisfies SC-001, SC-002, and SC-008.

---

## Phase 4: User Story 2 - 压缩后的旧聊天记录仍可回看 (Priority: P2)

**Goal**: Archived user/assistant messages remain visible in the same chat timeline through paged history loading, without exposing compression internals.

**Independent Test**: Seed a session with archived user/assistant messages, tool calls/results, compressed summary rows, and current messages; open the session and verify only the latest 10 user/assistant display messages appear first, then earlier user/assistant messages load when scrolling upward, with no archive/compression labels or tool/summary rows.

### Tests for User Story 2

- [x] T013 [P] [US2] Add repository pagination tests in `tests/data/test_message_repository.py` covering `sequence` ordering, latest-10 initial page, `before_sequence` older page, `has_more_before`, archived inclusion, and tool/summary/empty-content exclusion.
- [x] T014 [P] [US2] Add ChatService contract tests in `tests/business/test_chat_service_history.py` for `DisplayChatMessage`, `ChatHistoryPage`, no `is_archived`/`message_type` exposure, and no direct UI access to Repository data.
- [x] T015 [P] [US2] Add ChatWidget history UI tests in `tests/ui/test_chat_widget_history.py` for initial latest-10 render, top-scroll older-page prepend, preserved scroll position, no "归档"/"压缩" labels, and >=1000-message timing coverage asserting initial display completes within 2s, one top-scroll load handler blocks the UI for no more than 100ms, and one input/send-path handler under long-history state blocks the UI for no more than 100ms.

### Implementation for User Story 2

- [x] T016 [US2] Add `MessageRepository.get_display_page(session_id, limit, before_sequence)` in `src/data/repos/message_repository.py` using SQLAlchemy keyset pagination on `sequence` and filtering out `role="tool"`, `role="summary"`, `message_type="compressed"`, assistant tool-call-only rows, and empty content.
- [x] T017 [US2] Add `DisplayChatMessage` and `ChatHistoryPage` DTOs plus `ChatService.get_display_messages()` in `src/business/services/chat_service.py`, mapping repository rows to user-visible display data without exposing `is_archived`, `compressed_range`, or `message_type`.
- [x] T018 [US2] Replace `ChatWidget._load_session_messages()` in `src/ui/widgets/chat_widget.py` to call `ChatService.get_display_messages(session_id, limit=10)` instead of `ChatService.get_session_messages()`.
- [x] T019 [US2] Track `_oldest_loaded_sequence`, `_has_more_history`, and `_loading_history_page` state in `src/ui/widgets/chat_widget.py` for the active conversation view.
- [x] T020 [US2] Connect `messages_scroll.verticalScrollBar().valueChanged` to a top-threshold loader in `src/ui/widgets/chat_widget.py` that requests older pages with `before_sequence`.
- [x] T021 [US2] Extend `ChatWidget._add_message()` or add a sibling helper in `src/ui/widgets/chat_widget.py` to prepend older message widgets without auto-scrolling to bottom and while preserving current viewport position.
- [x] T022 [US2] Ensure new chat, clear/welcome state, and session switching reset history pagination state in `src/ui/widgets/chat_widget.py`.
- [x] T023 [US2] Validate User Story 2 with `tests/data/test_message_repository.py`, `tests/business/test_chat_service_history.py`, and `tests/ui/test_chat_widget_history.py`, recording the long-history <=2s initial render, <=100ms scroll-handler, and <=100ms input/send-path performance evidence or any documented local fallback.

**Checkpoint**: User Story 2 is independently functional and satisfies SC-003, SC-004, and SC-007 without changing LLM context compression behavior.

---

## Phase 5: User Story 3 - 新对话/欢迎界面不展示"免确认"Toggle (Priority: P3)

**Goal**: The session-scoped "免确认" Toggle is visible only after the current conversation has started an Agent session, while existing 004-auth-toast synchronization behavior remains unchanged.

**Independent Test**: Start on the welcome page and create a new empty chat; the Toggle is hidden. Send the first message; the Toggle appears and remains visible after the response. Switching back to the session list, welcome/new chat, or cleared state hides the Toggle without emitting extra `auto_approve_toggled` events.

### Tests for User Story 3

- [x] T024 [P] [US3] Extend `tests/ui/test_chat_widget_auth_toggle.py` to assert Toggle hidden on welcome/session list/new-chat empty states and visible after first send or existing non-empty session load.
- [x] T025 [P] [US3] Extend `tests/ui/test_agent_handler_mixin.py` to assert hidden Toggle state does not break `set_auto_approve_enabled()`, `auto_approve_toggled`, new-chat reset, pending confirmation settlement, or source semantics.

### Implementation for User Story 3

- [x] T026 [US3] Add `ChatWidget._set_auto_approve_toggle_visible()` and `ChatWidget._mark_conversation_started()` helpers in `src/ui/widgets/chat_widget.py` that change visibility without emitting `auto_approve_toggled`.
- [x] T027 [US3] Update `ChatWidget._prepare_new_chat()`, `ChatWidget._add_welcome_message()`, `ChatWidget.show_session_list()`, and `ChatWidget.on_new_chat()` in `src/ui/widgets/chat_widget.py` to hide the Toggle for welcome/list/new-chat empty states.
- [x] T028 [US3] Update `ChatWidget._do_send()` and `ChatWidget._switch_to_session()` in `src/ui/widgets/chat_widget.py` to show the Toggle after first message send and for existing non-empty conversations.
- [x] T029 [US3] Adjust header layout handling in `src/ui/widgets/chat_widget.py` and `src/ui/resources/styles.qss` so hiding the Toggle leaves no residual disabled control, flicker, or header layout deformation.
- [x] T030 [US3] Validate User Story 3 with `tests/ui/test_chat_widget_auth_toggle.py` and `tests/ui/test_agent_handler_mixin.py`.

**Checkpoint**: User Story 3 is independently functional and satisfies SC-005 and SC-006 without changing 004-auth-toast confirmation protocol.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final validation, documentation, and architecture guard coverage across stories.

- [x] T031 [P] Update `docs/ARCHITECTURE.md` with the durable `ChatWidget -> ChatService -> MessageRepository` display-history pagination path and Markdown rendering boundary.
- [x] T032 [P] Add or update an architecture smoke test in `tests/integration/test_assistant_new_session.py` proving assistant conversations still create sessions and emit `ChatWidget.send_message_requested` after Markdown/history changes.
- [x] T033 Run `uv run python -m pytest tests/ui/test_chat_widget_markdown.py tests/ui/test_chat_widget_history.py tests/ui/test_chat_widget_auth_toggle.py tests/ui/test_agent_handler_mixin.py -q` and use `.venv\Scripts\python.exe` fallback if `uv run` hits the documented cache permission issue in `specs/006-chat-ui-polish/quickstart.md`.
- [x] T034 Run `uv run python -m pytest tests/data/test_message_repository.py tests/business/test_chat_service_history.py tests/integration/test_assistant_new_session.py -q` and use `.venv\Scripts\python.exe` fallback if needed per `specs/006-chat-ui-polish/quickstart.md`.
- [x] T035 Run `uv run python -m py_compile src/ui/widgets/chat_widget.py src/ui/widgets/markdown_message_view.py src/business/services/chat_service.py src/data/repos/message_repository.py` and `git diff --check`.
- [x] T036 Verify `specs/006-chat-ui-polish/quickstart.md` manual acceptance items against the implemented GUI behavior and record any validation caveat in the final implementation response.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 Setup**: no dependencies.
- **Phase 2 Foundational**: depends on Phase 1 and blocks story implementation.
- **Phase 3 US1**: depends on Phase 2.
- **Phase 4 US2**: depends on Phase 2; can be implemented without US1, but ChatWidget edits must be coordinated if US1 is active in parallel.
- **Phase 5 US3**: depends on Phase 2; can be implemented without US1/US2, but ChatWidget edits must be coordinated if other stories are active in parallel.
- **Phase 6 Polish**: depends on all implemented stories.

### User Story Dependencies

- **US1 (P1)**: MVP; no dependency on US2 or US3.
- **US2 (P2)**: no semantic dependency on US1 or US3; shares `src/ui/widgets/chat_widget.py` edit surface.
- **US3 (P3)**: no semantic dependency on US1 or US2; shares `src/ui/widgets/chat_widget.py` edit surface and must preserve 004-auth-toast behavior.

### Within Each User Story

- Write tests first and confirm they fail for the missing behavior.
- Implement data/Service code before UI code for US2.
- Implement standalone Markdown view before integrating it into ChatWidget for US1.
- Keep Toggle visibility helpers separate from Toggle state synchronization for US3.

---

## Parallel Opportunities

- T002, T003, and T004 can run in parallel because they touch separate test helper/guard files.
- US1 tests T005-T007 are in one file and should be done by one worker, while T008-T009 in `markdown_message_view.py` can start after tests are drafted.
- US2 tests T013, T014, and T015 can run in parallel because they touch data, business, and UI test files separately.
- US3 tests T024 and T025 can run in parallel because they touch separate UI test files.
- T031 and T032 can run in parallel during polish because docs and integration tests are separate files.

## Parallel Example: User Story 2

```text
Task: "Add repository pagination tests in tests/data/test_message_repository.py"
Task: "Add ChatService contract tests in tests/business/test_chat_service_history.py"
Task: "Add ChatWidget history UI tests in tests/ui/test_chat_widget_history.py"
```

## Parallel Example: User Story 3

```text
Task: "Extend tests/ui/test_chat_widget_auth_toggle.py for Toggle visibility states"
Task: "Extend tests/ui/test_agent_handler_mixin.py for existing confirmation synchronization semantics"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 and Phase 2.
2. Complete Phase 3 (US1 Markdown rendering).
3. Validate `tests/ui/test_chat_widget_markdown.py` and `py_compile` for `src/ui/widgets/markdown_message_view.py` / `src/ui/widgets/chat_widget.py`.
4. Stop and review the rendered assistant message behavior before starting history pagination.

### Incremental Delivery

1. Deliver US1 Markdown rendering first because it is highest priority and independent.
2. Deliver US2 history pagination next, preserving `ContextManager` and compression contracts.
3. Deliver US3 Toggle visibility last, preserving existing 004-auth-toast state synchronization.
4. Run Phase 6 validation after the desired story set is complete.

### Parallel Team Strategy

With multiple implementers:

1. One implementer owns `src/ui/widgets/markdown_message_view.py` and `tests/ui/test_chat_widget_markdown.py` for US1.
2. One implementer owns `src/data/repos/message_repository.py`, `src/business/services/chat_service.py`, and history tests for US2.
3. One implementer owns Toggle visibility tests and the `ChatWidget` visibility helpers for US3.
4. Coordinate final `src/ui/widgets/chat_widget.py` integration because all three stories may touch that file.

## Notes

- `[P]` marks tasks that touch distinct files and can run in parallel.
- `[US1]`, `[US2]`, and `[US3]` map directly to the prioritized user stories in `spec.md`.
- `src/ui/widgets/chat_widget.py` is the main shared edit surface; avoid concurrent conflicting edits there.
- Do not add config keys, migrations, DuckDB access, or direct UI Repository calls for this feature.
