# Tasks: MCP Management

**Input**: Design documents from `/specs/027-mcp-management/`
**Prerequisites**: plan.md (required), spec.md (required), data-model.md, research.md, contracts/, quickstart.md

**Tests**: Included — Constitution IV (可验证交付) requires test coverage; plan.md explicitly lists test files.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Constitution-Driven Minimums

- ✅ Repository + migration tasks (`src/data/repos/`, `src/data/migrations.py`) for SQLite/business-data changes
- ✅ Configuration (`UnifiedConfigManager`), secret masking/redaction tasks for credential handling
- ✅ Wiring smoke tests and guard tests for architecture constraints
- ✅ Active-document updates (`docs/ARCHITECTURE.md`, root `AGENTS.md`/`CLAUDE.md`/`GEMINI.md`, `src/AGENTS.md`, `frontend/AGENTS.md`)

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Project Paths

- **Python source**: `src/` at repository root (business, desktop_api, data, recording, execution, utils)
- **Frontend source**: `frontend/src/` for React UI, typed API clients, stores, and styles
- **Desktop shell**: `src-tauri/` for Tauri window commands, sidecar lifecycle, and capabilities
- **Python tests**: `tests/` at repository root (desktop_api, guardrails, integration, data, business)
- **Frontend tests**: `frontend/tests/unit/` and `frontend/tests/e2e/`
- **Python test runner**: `uv run pytest tests/`
- **Python formatter/linter**: `uv run black src/ tests/` and `uv run flake8 src/ tests/`
- **Frontend validation**: `npm run lint`, `npm run test`, and `npm run test:e2e` from `frontend/`
- **Tauri validation**: `cargo check` or `npm run tauri build` when shell/packaging changes

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Add MCP SDK dependency and create module structure

- [X] T001 Add `mcp>=1.27,<2` dependency to pyproject.toml (pin upper bound per CC-008)
- [X] T002 Create `src/business/mcp/` module with `__init__.py` (exports key public types)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

### Data Layer

- [X] T003 Add `McpServer` ORM model (server_id/name/transport/command/args_json/url/headers_json/secret_header_keys_json/env_json/secret_env_keys_json/enabled/last_known_status/last_error_message/suggestion/circuit_breaker_open/tool_count/tools_json/is_preset/preset_slug/created_at/updated_at) and `ID_PREFIX_MCP_SERVER = "mcs_"` in `src/data/models_sqlite.py`
- [X] T004 Add v24 migration (CREATE TABLE mcp_servers + unique index uq_mcp_servers_name + downgrade DROP TABLE + DELETE app_settings LIKE 'mcp.servers.%') in `src/data/migrations.py`
- [X] T005 Implement `McpServerRepository` (create_server/get_by_id/get_by_name/list_all/list_enabled/list_preset_slugs/update_config/set_enabled/update_status/delete_server) extending BaseRepository in `src/data/repos/mcp_server_repository.py`
- [X] T006 Unit test McpServerRepository (CRUD + name uniqueness + list filters + status update) in `tests/data/test_mcp_server_repository.py`

### Business Models

- [X] T007 [P] Create business models (McpServerConfigPublic with from_row/McpLaunchPayload with field(repr=False) + class-level __repr__/McpToolInfo/McpCallResult/McpServerStatus enum) in `src/business/mcp/models.py`
- [X] T008 [P] Create `McpSessionProtocol` (initialize/list_tools/call_tool/send_ping, all return business types per N9) in `src/business/mcp/mcp_session_protocol.py`

### Utility Modules

- [X] T009 [P] Implement mcp_errors.py (McpServerDisconnectedError/McpToolTimeoutError/McpToolSchemaValidationError/McpCircuitBreakerOpenError + classify_startup_error/classify_runtime_error → suggestion mapping per N14/RC3) in `src/business/mcp/mcp_errors.py`
- [X] T010 [P] Implement mcp_env_resolver.py (resolve_env_vars: ${VAR} → os.environ → mark "pending"; check_missing_placeholders; merge with UnifiedConfigManager secrets) in `src/business/mcp/mcp_env_resolver.py`
- [X] T011 [P] Implement mcp_json_import.py (parse 3 formats: nested mcpServers/裸 stdio/裸 HTTP + secret auto-detection heuristic TOKEN/KEY/SECRET/PASSWORD/CREDENTIAL/AUTH + ${VAR} placeholder detection) in `src/business/mcp/mcp_json_import.py`
- [X] T012 [P] Implement mcp_presets.py (PRESET_SERVERS: GitHub + filesystem defaults with command/args/non_secret_env/preset_slug) in `src/business/mcp/mcp_presets.py`
- [X] T013 [P] Unit test mcp_json_import (3-format parsing + batch import + secret detection + fuzz testing per E12) in `tests/business/mcp/test_mcp_json_import.py`
- [X] T014 [P] Unit test mcp_env_resolver (${VAR} resolution + system env fallback + missing placeholder detection) in `tests/business/mcp/test_mcp_env_resolver.py`
- [X] T015 [P] Unit test mcp_errors (startup error classification + runtime error classification + suggestion mapping per N14) in `tests/business/mcp/test_mcp_errors.py`

### Core Infrastructure

- [X] T016 Implement `McpProcessManager` in `src/business/mcp/mcp_process_manager.py`:
  - `_check_sdk_available()` — delayed import detection, sets `sdk_available` flag (E7)
  - Event loop thread (`_run_loop` with crash recovery per E6/N15)
  - `_start_server_coro` — StdioServerParameters + stdio_client(errlog=tempfile) + AsyncExitStack + ClientSession(async with per RC2) + _SdkSessionAdapter(RC4) + stderr tempfile reader(RC1) + stop_event.wait() long connection
  - `_build_launch_payload` — McpServerConfigPublic → McpLaunchPayload (merge secrets from UnifiedConfigManager, N17)
  - `_stop_server_coro` — stop_event.set() + stack.aclose() (SDK Job Object per N2) + 15s timeout fallback
  - `_call_tool_coro` — via McpSessionProtocol, 30s read_timeout_seconds=timedelta, McpToolSchemaValidationError(RC3)
  - `_health_check_coro` — session.send_ping() returning bool
  - `_mark_disconnected` — update status + cleanup + emit backend.resync_required(RC11)
  - `_stderr_reader` — periodic tempfile read + _mask_secrets + logging
  - `_SdkSessionAdapter` — wraps SDK ClientSession as McpSessionProtocol (RC4)
  - `_convert_sdk_call_result` / `_convert_sdk_tool` — SDK→business type conversion (RC8/RC9)
  - Sync entry points: `start_server`/`stop_server`/`call_tool_sync`/`reconnect_server` using `run_coroutine_threadsafe`
- [X] T017 Implement `McpToolRegistry` in `src/business/mcp/mcp_tool_registry.py`:
  - Dual-track: `_preset_tool_names` (full injection) + `_activated_custom` (independent LRU, max 10)
  - Thread-safe: `_lock: threading.RLock`, snapshot semantics on all getters
  - `register_server_tools` / `unregister_server_tools` — server_id→tool_full_name mapping
  - `get_preset_tools` / `get_activated_custom_tools` — snapshot lists
  - `activate_custom_tool` — LRU eviction
  - `get_catalog_items` / `find_tool`
  - `NullRegistry` — empty implementation when SDK unavailable (RC10)
  - `get_mcp_tool_registry()` — singleton factory, returns NullRegistry on SDK import failure
- [X] T018 Implement `McpServerService` in `src/business/mcp/mcp_server_service.py`:
  - Orchestrates McpProcessManager + McpToolRegistry + McpServerRepository + UnifiedConfigManager
  - `add_server` — validate + save config (secrets→app_settings) + auto-start if enabled
  - `update_server` — merge fields + update secrets + auto-restart if running
  - `delete_server` — stop if running + cleanup app_settings + delete DB row
  - `start_server` / `stop_server` / `reconnect_server` — delegate to ProcessManager
  - `start_all_enabled` — async gather, failures→failed status, non-blocking
  - `stop_all` — concurrent stop with 10s timeout
  - `get_server_status` — merge DB status + runtime status
  - `call_tool_sync` — delegate to ProcessManager, circuit breaker check (E8: 3 consecutive failures → open)
  - `_on_server_started` / `_on_server_stopped` — update DB + registry + emit tools.changed
  - `get_or_create_event_loop` — access to ProcessManager's event loop
- [X] T019 Unit test McpProcessManager (FakeMcpSession injection per RC4 + start/stop/call_tool/ping normal+failure + RC3 schema error + event loop crash recovery) in `tests/business/mcp/test_mcp_process_manager.py`
- [X] T020 [P] Unit test McpToolRegistry (dual-track: preset full injection + custom LRU + unregister by mapping + thread-safe snapshot + NullRegistry fallback) in `tests/business/mcp/test_mcp_tool_registry.py`
- [X] T021 Unit test McpServerService (add/update/delete server lifecycle + auto-start/stop + circuit breaker + secret storage via UnifiedConfigManager + tools.changed emission) in `tests/business/mcp/test_mcp_server_service.py`
- [X] T022 [P] Thread safety + event loop crash recovery test (Barrier sync + concurrent call_tool + loop rebuild after exception per E15) in `tests/business/mcp/test_sync_bridge_threading.py`
- [X] T023 [P] Config repr guard test (assert secret not in repr(McpLaunchPayload) + McpServerConfigPublic safe per RC5) in `tests/business/mcp/test_mcp_config_repr.py`
- [X] T024 Guard tests in `tests/guardrails/test_mcp_guardrails.py`:
  - MCP tools use deferred loading (not full injection for custom servers)
  - SDK types do not cross business layer boundary (no `from mcp.types` in service/registry)
  - Credentials never leak to DTO/logs (McpServerConfigPublic + McpLaunchPayload repr)
  - McpToolRegistry snapshot semantics (no `dictionary changed size during iteration`)
  - tool_factory includes MCP preset + activated custom tools

**Checkpoint**: Foundation ready — data layer, business models, process manager, tool registry, and service all functional with unit tests passing

---

## Phase 3: User Story 1 - AI 自动调用 MCP 工具完成任务 (Priority: P1) 🎯 MVP

**Goal**: 用户配置 MCP server 后，AI 在对话中自动发现并调用 MCP 工具完成任务，无需手动选择

**Independent Test**: 配置预置文件系统 server（直接 API 调用添加），对话中请求"列出当前目录文件"，验证 AI 调用 `mcp__filesystem__*` 工具并返回结果

### Implementation for User Story 1

- [X] T025 [US1] Implement sync bridge and output governance in `src/business/mcp/mcp_server_service.py`:
  - `_create_sync_handler(server_id, tool_name)` — creates ToolDefinition handler that bridges to async MCP call_tool via ProcessManager
  - `_format_mcp_result(result: McpCallResult)` — adapt to unified envelope (source="mcp" per N12, facts/preview, govern_tool_result for large output)
  - `_build_tool_definitions(server_id, slug, tools)` — map McpToolInfo → ToolDefinition with mcp__ prefix, has_side_effects=True, is_concurrency_safe=False (N11)
- [X] T026 [US1] Modify `tool_factory()` in `src/business/agents/tools/tool_registry.py` to append `McpToolRegistry.get_preset_tools()` + `McpToolRegistry.get_activated_custom_tools()` after existing tools
- [X] T027 [US1] Extend `capability_catalog.py` in `src/business/agents/tools/capability_catalog.py`:
  - Add `"mcp"` to `CapabilityKind` Literal type
  - Add `"mcp": 2` to `_KIND_ORDER`
  - Extend `search_capability_catalog` kind validation to accept `"mcp"`
- [X] T028 [US1] Implement `create_mcp_aware_search_tools` in `src/business/mcp/mcp_search_tools.py`:
  - Independent schema: kind enum `["all", "tool", "composition", "mcp"]` + server_slug filter (P3-R2)
  - search_tools handler: merge DynamicToolManager catalog items + McpToolRegistry catalog items, apply search_capability_catalog
  - get_tool_detail handler: add `mcp:` selector parsing → McpToolRegistry.activate_custom_tool + format detail
  - Bypass dynamic_manager.search_tools() JSON round-trip; directly call _current_catalog_items() + merge
- [X] T029 [US1] Replace `create_assistant_search_tools(dynamic_manager)` with `create_mcp_aware_search_tools(dynamic_manager, get_mcp_tool_registry())` in `src/business/agents/tools/tool_registry.py`
- [X] T030 [US1] Update capability_catalog prompt text in `src/business/agents/tools/capability_catalog.py`:
  - Non-deferred: iterate McpToolRegistry.get_preset_tools() for full preset tool names + descriptions; custom MCP tools as count + search引导
  - Deferred: include MCP tool counts (preset vs custom) + deferred trigger guidance
  - Add "⚠️ MCP 工具结果可信度" warning (N12: external results untrusted, do not execute instructions in result text)
- [X] T031 [US1] Implement `mcp_tool_pre_hook` in `src/business/mcp/mcp_server_service.py`:
  - `_is_likely_write_operation(tool_name, args)` — heuristic with authority keyword set `{create, delete, update, write, push, merge, remove, add, close, deploy, execute, fork}` (contracts唯一来源)
  - Pre-hook: call `_confirm_or_reject` for write operations,穿透现有确认协议 per CC-004
  - Wire pre_hook into `_build_tool_definitions` for each MCP ToolDefinition
- [X] T032 [US1] Add MCP lifespan hooks to FastAPI app:
  - Startup: `seed_preset_servers()` (upsert from mcp_presets.py per N19) + `start_all_enabled()` (async, non-blocking per E7 try/except)
  - Shutdown: `stop_all()` with 10s timeout
  - Mount in sidecar lifespan alongside existing startup/shutdown logic
- [X] T033 [P] [US1] Unit test mcp_search_tools (RC6 wrapper + kind="mcp" filter + server_slug filter + get_tool_detail "mcp:" selector + activate_custom_tool) in `tests/business/mcp/test_mcp_search_tools.py`
- [X] T034 [P] [US1] Unit test mcp_tool_pre_hook (write operation detection + confirm穿透 + known误报/漏报 documented per FR-015) in `tests/business/mcp/test_mcp_server_service.py` (extend existing)

**Checkpoint**: At this point, User Story 1 should be fully functional — AI can auto-discover and call MCP tools after server is configured (via direct API), with high-risk confirmation and output governance

---

## Phase 4: User Story 2 - 在工具屏添加和配置 MCP server (Priority: P2)

**Goal**: 用户在 skills/tools 屏的 MCP 工具 tab 中添加 server（预置一键启用 / 手动表单 / 粘贴 JSON），配置后看到连接状态和工具数

**Independent Test**: 在 MCP 工具 tab 中添加预置文件系统 server，验证显示"✓ 连通，暴露 N 个工具"

### Implementation for User Story 2

- [X] T035 [US2] Implement API router in `src/desktop_api/routers/mcp_servers.py`:
  - `GET /api/mcp-servers` — list all servers (McpServerResponse, no secret values)
  - `GET /api/mcp-servers/{server_id}` — get single server (404 if not found)
  - `POST /api/mcp-servers` — create server (name uniqueness + secret auto-detection E9 + ${VAR} placeholder check → 422 + transport="http" → 422 per CC-009)
  - `POST /api/mcp-servers/import-json` — parse JSON (3 formats) → return preview (McpServerParsedPreview with detectedSecretKeys + placeholderKeys)
  - `POST /api/mcp-servers/{server_id}/test-connection` — temporary start + initialize + list_tools, 60s timeout (P3-MA3), cleanup after test
  - Pydantic schemas: McpServerCreateRequest/McpServerUpdateRequest/McpServerJsonImportRequest/McpServerResponse/McpServerTestConnectionResponse/McpServerJsonImportResponse/McpServerParsedPreview
- [X] T036 [US2] Register mcp_servers router (prefix `/api/mcp-servers`) in FastAPI app setup
- [X] T037 [P] [US2] Create typed API client (listServers/getServer/createServer/importJson/testConnection) in `frontend/src/api/mcpServers.ts`
- [X] T038 [P] [US2] Create Zustand store `mcpStore.ts` in `frontend/src/state/mcpStore.ts`:
  - State: servers list, loading/error states, selected server for editing
  - Actions: fetchServers, addServer, importJson, testConnection
  - Subscribe to tools.changed event for auto-refresh
- [X] T039 [US2] Implement McpServerTab component in `frontend/src/screens/skills/McpServerTab.tsx`:
  - Server list with McpServerCard components
  - Empty state: 2 preset server cards (GitHub/filesystem) + guide text "添加 MCP server 后，AI 助手可以自动使用这些工具完成任务"
  - Add button (➕) → open McpServerDialog
  - Integrate as new tab in existing skills/tools screen (CC-006: keep existing 教学工具 tab untouched)
- [X] T040 [US2] Implement McpServerCard component in `frontend/src/screens/skills/McpServerCard.tsx`:
  - Display: server name, connection status badge, tool count
  - Dual-track status badge: preset → "✓ AI 可直接调用", custom → "AI 通过 search 按需发现"
  - One-time tooltip on custom server first add: "工具较多,AI 会在需要时搜索发现"
  - Disconnected state: greyed out, tool count hidden
  - Actions: edit, enable/disable toggle, reconnect, delete
- [X] T041 [US2] Implement McpServerDialog component in `frontend/src/screens/skills/McpServerDialog.tsx`:
  - Three entry paths unified to same form: preset one-click / manual form / paste JSON
  - Preset selection: list PRESET_SERVERS with one-click enable (no-credential server → immediate; credential server → stop at credential step)
  - JSON import: textarea + parse button → auto-fill form fields
  - Form fields: name, transport (stdio only for MVP), command, args, env (key-value pairs with secret toggle), headers
  - Secret fields: masked display, separate input for values
  - ${VAR} placeholder fields: show "将读取系统环境变量 VAR；或直接输入 token"
  - Test connection button with progress hint "首次启动可能需 30s+ 下载"
  - Save button (validates no pending placeholders before save)
- [X] T042 [US2] Add preset server seeding to lifespan startup (before start_all_enabled): check existing preset_slug rows, upsert missing presets from mcp_presets.py defaults (user-modified presets not overwritten per N19)
- [X] T043 [P] [US2] Unit test mcpStore (fetchServers/addServer/importJson/state transitions + tools.changed refresh) in `frontend/tests/unit/mcpStore.test.ts`
- [X] T044 [P] [US2] Unit test API router (create + import-json + test-connection + list + get + name conflict + placeholder rejection + HTTP transport 422 + secret auto-detection) in `tests/desktop_api/test_mcp_servers_router.py`

**Checkpoint**: At this point, User Stories 1 AND 2 should both work independently — users can add/configure MCP servers via UI and AI auto-calls MCP tools

---

## Phase 5: User Story 3 - 管理已配置的 MCP server (Priority: P3)

**Goal**: 用户查看已配置 server 列表（名称/工具数/连接状态），可启用/禁用/删除/重连 server

**Independent Test**: 添加 server 后禁用它，验证 AI 不再调用该 server 的工具

### Implementation for User Story 3

- [X] T045 [US3] Add management API endpoints in `src/desktop_api/routers/mcp_servers.py`:
  - `PATCH /api/mcp-servers/{server_id}` — update server config (merge fields + update secrets + auto-restart if running)
  - `POST /api/mcp-servers/{server_id}/enable` — set enabled=True + start_server
  - `POST /api/mcp-servers/{server_id}/disable` — stop_server + set enabled=False
  - `POST /api/mcp-servers/{server_id}/reconnect` — reconnect_server (stop+start, emit tools.changed on success per P2-MA5)
  - `DELETE /api/mcp-servers/{server_id}` — stop if running + cleanup app_settings + delete DB row (204 response)
- [X] T046 [US3] Implement health check ping loop in `src/business/mcp/mcp_process_manager.py`:
  - 60s periodic `send_ping()` for all running servers (N4)
  - Ping failure → mark disconnected + cleanup + emit backend.resync_required
  - Start ping loop in event loop thread at ProcessManager init; cancel on shutdown
- [X] T047 [US3] Implement circuit breaker in `src/business/mcp/mcp_server_service.py`:
  - Per-server consecutive failure counter (in-memory, process-level)
  - 3 consecutive failures → circuit_breaker_open=True, return McpCircuitBreakerOpenError
  - Manual reconnect resets counter + circuit_breaker_open=False
  - DB stores circuit_breaker_open snapshot; sidecar restart resets to False
- [X] T048 [US3] Add server management UI to McpServerCard in `frontend/src/screens/skills/McpServerCard.tsx`:
  - Enable/disable toggle with immediate API call
  - Reconnect button (visible when disconnected/failed)
  - Edit button → open McpServerDialog in edit mode
  - Delete button with impact warning ("AI 助手正在使用此 server 的工具，删除后相关功能将不可用") — no secondary confirmation dialog per edge case spec
  - Status display: running (green ✓) / starting (spinner) / disconnected (grey) / failed (red ✗ with suggestion)
  - Last error + suggestion display for failed servers
- [X] T049 [US3] Extend mcpStore with management actions (updateServer/enableServer/disableServer/reconnectServer/deleteServer + optimistic status updates) in `frontend/src/state/mcpStore.ts`
- [X] T050 [P] [US3] Unit test management API endpoints (update + enable/disable + reconnect + delete + auto-restart on config change + app_settings cleanup) in `tests/desktop_api/test_mcp_servers_router.py` (extend existing)

**Checkpoint**: All user stories should now be independently functional — full MCP server lifecycle management with AI integration

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Integration validation, documentation, and cross-cutting quality

- [X] T051 [P] Integration test with real filesystem server (start + list_tools + call_tool + RC2 async with + RC1 stderr tempfile + RC3 schema boundary + stop + reconnect) marked `@pytest.mark.integration` in `tests/integration/test_mcp_filesystem_server.py`
- [X] T052 [P] Update `docs/ARCHITECTURE.md` — add MCP section (dual-track registration, McpProcessManager lifecycle, credential flow, tools.changed integration)
- [X] T053 [P] Update root `CLAUDE.md`/`AGENTS.md`/`GEMINI.md` — add 027 to Recent Changes + add Known Issues (catalog deferred mode承诺降级 + 自定义 server激活态重启丢失 + server name不可改 + 长连接稳定性E20 + MCP result prompt injection N12 + 启发式误报漏报)
- [X] T054 [P] Update `src/AGENTS.md` — add MCP module constraints (SDK delayed import E7 + business types N9 + dual-track N8 + pre-hook穿透 + output governance)
- [X] T055 [P] Update `frontend/AGENTS.md` — add MCP tab constraints (CC-006 教学工具 tab不动 + dual-track badge + secret field masking + tools.changed subscription)
- [X] T056 Run quickstart.md validation (v24 migration + filesystem server connection + AI tool call + credential masking + high-risk confirmation + disconnect display)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 completion — BLOCKS all user stories
- **User Stories (Phase 3-5)**: All depend on Phase 2 completion
  - US1 (Phase 3): Can start after Phase 2 — no dependency on other stories
  - US2 (Phase 4): Can start after Phase 2 — integrates with US1 (uses tool_factory) but independently testable
  - US3 (Phase 5): Can start after Phase 2 — extends US2 API router and UI components
- **Polish (Phase 6)**: Depends on all user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Phase 2 — no dependencies on other stories
- **User Story 2 (P2)**: Can start after Phase 2 — extends US1's tool registration (adds UI to configure servers that US1 consumes), but independently testable via API
- **User Story 3 (P3)**: Can start after Phase 2 — extends US2's API and UI (management endpoints + card actions), independently testable

### Within Each User Story

- Data layer before business layer
- Business models before services
- Services before API endpoints
- API endpoints before frontend components
- Core implementation before tests
- Story complete before moving to next priority

### Parallel Opportunities

- All Phase 1 tasks can run in parallel
- Within Phase 2: T007/T008 (models) can run in parallel; T009-T015 (utility modules + tests) can all run in parallel; T019-T023 (core tests) can run in parallel
- Within Phase 3: T033/T034 (US1 tests) can run in parallel
- Within Phase 4: T037/T038 (frontend API client + store) can run in parallel; T043/T044 (tests) can run in parallel
- Once Phase 2 completes, US1/US2/US3 can proceed in parallel by different developers

---

## Parallel Example: Phase 2 Foundational

```bash
# Data layer (sequential: ORM → migration → repository → test)
Task: "T003 Add McpServer ORM model in src/data/models_sqlite.py"
Task: "T004 Add v24 migration in src/data/migrations.py"
Task: "T005 Implement McpServerRepository in src/data/repos/mcp_server_repository.py"
Task: "T006 Unit test McpServerRepository in tests/data/test_mcp_server_repository.py"

# Business models (parallel with data layer)
Task: "T007 Create business models in src/business/mcp/models.py"
Task: "T008 Create McpSessionProtocol in src/business/mcp/mcp_session_protocol.py"

# Utility modules (all parallel)
Task: "T009 Implement mcp_errors.py"
Task: "T010 Implement mcp_env_resolver.py"
Task: "T011 Implement mcp_json_import.py"
Task: "T012 Implement mcp_presets.py"

# Utility tests (all parallel, after their modules)
Task: "T013 Unit test mcp_json_import"
Task: "T014 Unit test mcp_env_resolver"
Task: "T015 Unit test mcp_errors"

# Core tests (parallel, after core infrastructure)
Task: "T020 Unit test McpToolRegistry"
Task: "T022 Thread safety test"
Task: "T023 Config repr guard test"
```

## Parallel Example: User Story 1

```bash
# After Phase 2, launch US1 core implementation:
Task: "T025 Implement sync bridge and output governance"
Task: "T026 Modify tool_factory() injection"
Task: "T027 Extend capability_catalog.py"
# Then:
Task: "T028 Implement create_mcp_aware_search_tools"
Task: "T029 Integrate mcp_aware_search_tools into tool_registry.py"
Task: "T030 Update capability_catalog prompt text"
Task: "T031 Implement mcp_tool_pre_hook"
Task: "T032 Add MCP lifespan hooks"

# US1 tests (parallel):
Task: "T033 Unit test mcp_search_tools"
Task: "T034 Unit test mcp_tool_pre_hook"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (add mcp SDK + create module)
2. Complete Phase 2: Foundational (all infrastructure + tests)
3. Complete Phase 3: User Story 1 (AI auto-calls MCP tools)
4. **STOP and VALIDATE**: Configure a preset filesystem server via direct API call, test AI auto-calling MCP tools in conversation
5. Demo if ready

### Incremental Delivery

1. Complete Setup + Foundational → Foundation ready
2. Add User Story 1 → Test independently → Deploy/Demo (MVP! AI auto-calls MCP tools)
3. Add User Story 2 → Test independently → Deploy/Demo (UI for adding/configuring servers)
4. Add User Story 3 → Test independently → Deploy/Demo (full server management)
5. Polish → Integration tests + documentation → Production ready

### Parallel Team Strategy

With multiple developers:

1. Team completes Setup + Foundational together
2. Once Foundational is done:
   - Developer A: User Story 1 (tool registration + AI integration)
   - Developer B: User Story 2 (API router + frontend components)
   - Developer C: User Story 3 (management endpoints + health check)
3. Stories complete and integrate independently

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- MCP SDK `from mcp import ...` MUST be delayed imports inside functions (E7)
- All business layer types (McpCallResult/McpToolInfo) MUST NOT import SDK types (N9)
- Credential values MUST go through UnifiedConfigManager, never in DTO/logs/frontend state
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- Avoid: vague tasks, same file conflicts, cross-story dependencies that break independence
