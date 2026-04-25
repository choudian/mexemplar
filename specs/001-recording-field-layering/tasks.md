# Tasks: 录制数据大字段按需读取

**Input**: Design documents from `/specs/001-recording-field-layering/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/recording-large-field-tool-contract.md, quickstart.md

**Tests**: Constitution 要求改静默失败路径必须补测试；plan.md 列出全部测试文件；quickstart.md 含验证命令。以下包含测试任务。

**Organization**: 任务按 user story 分组，每个 story 可独立实现和验证。US1 + US2 合起来构成 MVP。

**Phase 与 plan.md 对应**: tasks Phase 1 (Setup) + Phase 2 (Foundational) = plan Phase 0 (research) + Phase 1 (design) 的实现展开；tasks Phase 3–6 = plan 未显式编号的按 story 实现阶段；tasks Phase 7 = plan Polish。

## Constitution-Driven Minimums

- DuckDB 录制分析层：`network_requests` 的占位与续读必须复用 `sql_rewriter` / `FilteredDuckDBConnection`，不得直连 raw DuckDB
- 新增 `recording.large_field.*` 配置走 `config_models.py` + `UnifiedConfigManager` + `config.example.json` + `config.example.comments.md`
- `recording_data_tools.py` 不直接 import `sqlglot`；SQL 血缘分析放在 `src/recording/filtering/query_projection_analyzer.py`
- 工具注册从 4→5，补 wiring smoke test + guard test
- 活文档、prompt、配置注释同步更新为 5 工具工作流

## Format: `[ID] [P?] [Story] Description`

- **[P]**: 可并行（不同文件、无未完成依赖）
- **[Story]**: 所属 user story（US1 / US2 / US3 / US4）
- 每个描述包含精确文件路径

---

## Phase 1: Setup（配置基础设施）

**Purpose**: 新增配置模型和默认值，确保实现阶段走统一配置入口

- [x] T001 Confirm `sqlglot` is declared in `pyproject.toml` and available to `src/recording/filtering/`
- [x] T002 Add `LargeFieldConfig` dataclass (`threshold_chars`, `preview_chars`, `max_chunk_chars`, all `int`, defaults 1000/1000/1000) and nested `RecordingConfig.large_field` field in `src/data/config_models.py`
- [x] T003 Add `UnifiedConfigManager.get_recording_large_field_config()` loading from `recording.large_field.*` keys in `src/data/unified_config.py`
- [x] T004 [P] Add `recording.large_field` default values to `config.example.json`
- [x] T005 [P] Document `recording.large_field.*` defaults and runtime effect in `config.example.comments.md`

---

## Phase 2: Foundational（SQL 列血缘分析 + 测试骨架）

**Purpose**: 核心分析组件和测试基础设施，所有 user story 的前提

**⚠️ CRITICAL**: US1–US4 全部依赖此阶段完成

- [x] T006 Implement `StableLocatorRule` definitions with both `recommended_id_field` (used for locator construction in read_field_chunk) and `describe_locator_fields` (used for describe_data hints) for network_requests/request_id, actions/action_id, sibling_snapshots/snapshot_id; `ProjectionBinding` dataclass; and `analyze_query_projections(sql, schema_info)` using sqlglot — in `src/recording/filtering/query_projection_analyzer.py`
- [x] T007 Add unit tests for projection analyzer (direct column, alias, join locator detection, computed expression, aggregate, uncovered table, ambiguous join) in `tests/recording/filtering/test_query_projection_analyzer.py`
- [x] T008 [P] Add import guard test proving `recording_data_tools.py` does not import `sqlglot` in `tests/recording/filtering/test_recording_tools_no_sqlglot.py`
- [x] T009 Add reusable large-field DuckDB test fixtures (network_requests with 1.2MB response_body, actions with dom_tree_snapshot, sibling_snapshots, filtered rows) in `tests/recording/test_recording_data_large_fields.py`

**Checkpoint**: 配置模型、投影分析器、guard test 和测试骨架就绪

---

## Phase 3: User Story 1 — Agent 在 query_data 中识别大字段 (Priority: P1) 🎯 MVP

**Goal**: `query_data` 对任意达到阈值的文本结果列返回结构化占位对象，取代旧 `_MAX_QUERY_CELL_CHARS = 12_000` 无差别截断

**Independent Test**: 构造包含 1.2MB 文本、等于阈值、小字段、计算列、缺少定位字段的查询；验证大字段返回占位对象，小字段原样返回，占位字段与 blocked reason 符合 contract

### Tests for User Story 1

- [x] T010 [US1] Add failing placeholder tests: any text `len >= threshold_chars` triggers placeholder, equal-threshold triggers, small-field passthrough, binary passthrough, row/column structure integrity, multiple independent placeholders per row in `tests/recording/test_recording_data_large_fields.py`
- [x] T011 [US1] Add failing locator/blocked tests: direct field + stable ID → readable locator, missing stable ID → `missing_locator_field`, computed column → `computed_or_aggregated_column`, aggregate → same, uncovered table → `unsupported_source_table`, ambiguous join → `ambiguous_locator_source` (see spec FR-003a for `read_blocked_reason` enumeration), with `read_blocked_reason` + optional `read_blocked_message` assertions in `tests/recording/test_recording_data_large_fields.py`
- [x] T012 [US1] Replace old 12KB truncation assertions with new large-field placeholder contract in `tests/recording/test_query_data_sanitization.py`

### Implementation for User Story 1

- [x] T013 [US1] Implement `LargeFieldPlaceholder` builder: construct placeholder dict with `__large_field__`, `field`, `size_chars`, `preview` (capped by `preview_chars`), `locator` (from ProjectionBinding + StableLocatorRule), `read_hint`, `read_blocked_reason`/`read_blocked_message` when locator is null — in `src/business/agents/tools/recording_data_tools.py`
- [x] T014 [US1] Integrate placeholder builder into `query_data` result post-processing: replace `_MAX_QUERY_CELL_CHARS = 12_000` truncation with threshold-based placeholder replacement for all text cells, using `analyze_query_projections` for locator extraction — in `src/business/agents/tools/recording_data_tools.py`
- [x] T015 [US1] Emit structured logs for blocked/unsupported placeholder continuation with table, field, and reason context (SC-006 partial) in `src/business/agents/tools/recording_data_tools.py`
- [x] T016 [US1] Run and fix User Story 1 tests until green in `tests/recording/test_recording_data_large_fields.py` and `tests/recording/test_query_data_sanitization.py`

**Checkpoint**: `query_data` 占位替换功能完成，大字段不再以截断原文进入 Agent 上下文

---

## Phase 4: User Story 2 — Agent 分段读取大字段内容 (Priority: P1) 🎯 MVP

**Goal**: 新增 `read_field_chunk` 工具，Agent 按 locator + field + offset + 可选 length 读取单段原文，`network_requests` 走 filtered path

**Independent Test**: 用已知 locator 调用 read_field_chunk，验证首段内容、默认 length、length cap、固定响应字段、filtered row 返回 `record_unavailable`

### Tests for User Story 2

- [x] T017 [US2] Add failing `read_field_chunk` contract tests: offset 0, omitted length defaults to `max_chunk_chars`, capped length, `returned_length == len(content)`, `total_length`, `has_more`, `next_offset`, `error == null` in `tests/recording/test_recording_data_large_fields.py`
- [x] T018 [P] [US2] Add failing filtered-access tests proving `network_requests` chunk reads cannot reveal filtered rows in `tests/recording/test_recording_data_tools_noise_filtering.py`

### Implementation for User Story 2

- [x] T019a [US2] Implement `read_field_chunk` request validation and error handling: parameter validation (offset ≥ 0, length > 0, length defaults to max_chunk_chars when null), locator/field/schema validation against StableLocatorRule + DuckDB schema, all 9 error codes (invalid_offset, invalid_length, unknown_table, field_not_found, non_text_field, unknown_id_field, record_unavailable, unsupported_continuation, internal_error), unified ChunkReadResponse shape — in `src/business/agents/tools/recording_data_tools.py`
- [x] T019b [US2] Implement `read_field_chunk` data reads and response construction: filtered read for network_requests via sql_rewriter, parameterized direct single-row read for other StableLocatorRule-covered tables, Python `str` character slicing, ChunkReadResponse field population (content, returned_length, total_length, has_more, next_offset) — in `src/business/agents/tools/recording_data_tools.py`
- [x] T020 [US2] Register `read_field_chunk` in `create_recording_tools()` so PM and programmer agents receive 5 recording-data tools in `src/business/agents/tools/recording_data_tools.py`
- [x] T021 [US2] Run and fix User Story 2 tests until green in `tests/recording/test_recording_data_large_fields.py` and `tests/recording/test_recording_data_tools_noise_filtering.py`

**Checkpoint**: `read_field_chunk` 可作为 ToolDefinition 调用，首段读取 + filter 边界验证通过

---

## Phase 5: User Story 3 — Agent 逐段查看完整字段 (Priority: P2)

**Goal**: 多次续读闭环、EOF empty-success、Unicode 切片、非法参数错误码全覆盖

**Independent Test**: 对 1MB+ 字段连续读取到结尾，不同 offset 不重复，EOF 形状明确，非法参数返回结构化错误

### Tests for User Story 3

- [x] T022 [US3] Add failing paging lifecycle tests: sequential next_offset reads to completion, arbitrary middle offset, EOF at exact total_length (content="", returned_length=0, has_more=false, next_offset=null), offset beyond total_length returns same EOF shape, Unicode code-point slicing correctness in `tests/recording/test_recording_data_large_fields.py`
- [x] T023 [US3] Add failing error-code tests for all 9 codes (see data-model.md entity 8 `ChunkReadError codes`): `invalid_offset` (offset < 0), `invalid_length` (length ≤ 0), `unknown_table`, `field_not_found`, `non_text_field`, `unknown_id_field`, `record_unavailable`, `unsupported_continuation`, `internal_error` in `tests/recording/test_recording_data_large_fields.py`

### Implementation for User Story 3

- [x] T024 [US3] Complete `read_field_chunk` paging, range capping, EOF behavior, Unicode slicing, and all error-code branches in `src/business/agents/tools/recording_data_tools.py`
- [x] T025 [US3] Add structured logs for failed chunk reads with `error.code`, table, field, locator context (SC-006) in `src/business/agents/tools/recording_data_tools.py`
- [x] T026 [US3] Add failing runtime-config tests: changed threshold affects later placeholder triggering, changed preview_chars/chunk_chars affects later delivery, existing locator stays valid after config change in `tests/recording/test_recording_data_large_fields.py`
- [x] T027 [US3] Run and fix User Story 3 tests until green; verify blocked/unsupported/error paths produce structured logs containing `error.code` and `read_blocked_reason` as searchable keys (SC-006) in `tests/recording/test_recording_data_large_fields.py`

**Checkpoint**: Agent 可逐段读完整个大字段，EOF 和错误路径行为正确

---

## Phase 6: User Story 4 — 与现有数据发现和查询工具透明集成 (Priority: P2)

**Goal**: `describe_data` 增补机器可读大字段提示；prompt 和活文档更新为 5 工具工作流；wiring smoke + guard test 到位

**Independent Test**: `describe_data` 返回 `large_field` / `read_via` / `locator_fields`；`create_recording_tools()` 返回 5 个工具；prompt/文档不含旧 4 tools 描述

### Tests for User Story 4

- [x] T028 [US4] Add failing `describe_data` hint tests: schema-derived text fields in StableLocatorRule-covered tables get `large_field=true`, `read_via="read_field_chunk"`, `locator_fields=[...]`; uncovered table text fields do not advertise continuation in `tests/recording/test_recording_data_large_fields.py`
- [x] T029 [P] [US4] Add wiring smoke test: `create_recording_tools()` returns `read_field_chunk` as the fifth tool in `tests/recording/test_architecture_wiring.py`

### Implementation for User Story 4

- [x] T030 [US4] Add schema-derived `large_field`, `read_via`, `locator_fields` metadata to `_describe_data()` output for text columns in StableLocatorRule-covered tables in `src/business/agents/tools/recording_data_tools.py`
- [x] T031 [P] [US4] Update PM agent prompt: 4→5 tools workflow with read_field_chunk continuation guidance in `src/business/agents/prompts/pm_prompt.py`
- [x] T032 [P] [US4] Update programmer agent prompt: 4→5 tools workflow with read_field_chunk continuation guidance in `src/business/agents/prompts/programmer_prompt.py`
- [x] T033 [P] [US4] Update recording-data-tools section (4→5 tools, placeholder + chunk-read workflow) in `docs/ARCHITECTURE.md`
- [x] T034 [P] [US4] Update PM agent design doc (4→5 tools) in `docs/design/pm_agent_design.md`
- [x] T035 [P] [US4] Update programmer agent design doc (4→5 tools) in `docs/design/programmer_agent_design.md`
- [x] T036 [P] [US4] Mark read_field_chunk as implemented with file path in `docs/design/recording_tools_redesign_todo.md`
- [x] T037 [US4] Run and fix User Story 4 tests until green in `tests/recording/test_recording_data_large_fields.py` and `tests/recording/test_architecture_wiring.py`

**Checkpoint**: describe_data → query_data → read_field_chunk 全链路集成完成，文档与实现一致

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: 性能验证、回归覆盖、陈旧措辞清理

- [x] T038 [P] Add in-process SC-003 benchmark helper: measure placeholder construction overhead on a single 1.2MB field row (target ≤ 200ms) in `tests/recording/test_recording_data_large_fields.py`
- [x] T039 [P] Add CC-002 regression test: verify query_data large-field placeholders do not interfere with existing reference_handler citation substitution in `tests/recording/test_recording_data_large_fields.py`
- [x] T040 Update `docs/PROJECT_CONSTRAINTS.md` only if this feature introduced new constraints or modified existing constraint wording (compare pre-feature baseline; FR-016 / SC-005 lists affected docs)
- [x] T041 Run full quickstart validation from `specs/001-recording-field-layering/quickstart.md` (all 7 steps)
- [x] T042 Run full targeted regression: `tests/recording/test_recording_data_large_fields.py`, `tests/recording/test_query_data_sanitization.py`, `tests/recording/test_recording_data_tools_noise_filtering.py`, `tests/recording/filtering/test_query_projection_analyzer.py`, `tests/recording/filtering/test_recording_tools_no_sqlglot.py`, `tests/recording/test_architecture_wiring.py`
- [x] T043 [P] Search and remove stale `4 tools` / `4 个工具` / `_MAX_QUERY_CELL_CHARS` / `12KB` wording across `src/business/agents/tools/recording_data_tools.py`, `src/business/agents/prompts/pm_prompt.py`, `src/business/agents/prompts/programmer_prompt.py`, `config.example.comments.md`, `docs/ARCHITECTURE.md`, `docs/design/pm_agent_design.md`, `docs/design/programmer_agent_design.md`, `docs/design/recording_tools_redesign_todo.md`, `CONTRIBUTING.md`, `AGENTS.md`
- [x] T044 [P] Verify `specs/001-recording-field-layering/contracts/recording-large-field-tool-contract.md` examples match implemented request/response shapes

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies — start immediately
- **Phase 2 (Foundational)**: Depends on Phase 1 — BLOCKS all user stories
- **Phase 3 (US1, P1)**: Depends on Phase 2
- **Phase 4 (US2, P1)**: Depends on Phase 2; integrates with US1 placeholder format in recording_data_tools.py
- **Phase 5 (US3, P2)**: Depends on Phase 4 (extends read_field_chunk)
- **Phase 6 (US4, P2)**: Depends on Phase 3 + Phase 4 (all tools exist before doc/prompt updates)
- **Phase 7 (Polish)**: Depends on Phase 6

### User Story Dependencies

- **US1 (P1)**: After Foundational — no dependency on other stories
- **US2 (P1)**: After Foundational — shares recording_data_tools.py with US1 but tool logic is independent
- **US3 (P2)**: After US2 — extends read_field_chunk paging/error behavior
- **US4 (P2)**: After US1 + US2 — integration layer requires both tools to exist

### Parallel Opportunities

- Phase 1: T004, T005 parallel with T002, T003
- Phase 2: T008 parallel with T006–T007 (different files)
- Phase 3: T012 parallel with T010–T011 (different test file)
- Phase 4: T018 parallel with T017 (different test file)
- Phase 6: T031–T036 all parallel (independent doc/prompt files)
- Phase 7: T038, T039, T043, T044 all parallel

---

## Parallel Example: Phase 6 (US4)

```text
# Launch all doc/prompt updates in parallel:
T031: src/business/agents/prompts/pm_prompt.py
T032: src/business/agents/prompts/programmer_prompt.py
T033: docs/ARCHITECTURE.md
T034: docs/design/pm_agent_design.md
T035: docs/design/programmer_agent_design.md
T036: docs/design/recording_tools_redesign_todo.md
```

## Parallel Example: Phase 7

```text
# Launch all independent polish tasks in parallel:
T038: SC-003 benchmark test
T039: CC-002 regression test
T043: Stale wording cleanup (grep + edit)
T044: Contract examples verification
```

---

## Implementation Strategy

### MVP First (US1 + US2)

1. Complete Phase 1 + Phase 2
2. Complete US1: query_data 占位替换
3. Complete US2: read_field_chunk 首段读取 + 工具注册
4. **STOP and VALIDATE**: describe_data → query_data → read_field_chunk 最小闭环可用

**MVP scope = US1 + US2**：只有占位没有续读会阻断 Agent 查看内容，两个 P1 story 合起来才是最小可用交付。

### Incremental Delivery

1. Setup + Foundational → 配置和分析器就绪
2. + US1 → query_data 大字段占位替换 (MVP 前半)
3. + US2 → read_field_chunk 单次读取 (MVP 后半)
4. + US3 → 多次续读闭环 + 完整错误码覆盖
5. + US4 → describe_data 提示 + prompt/文档 5 工具同步
6. + Polish → 性能验证 + 回归 + 陈旧措辞清理

---

## Notes

- [P] tasks = 不同文件、无依赖，可并行
- [Story] label 对应 spec.md user story，用于追溯
- 每个 user story 可独立完成和验证
- 本特性不修改原始录制数据，不新增 DuckDB schema/migration
- `recording_data_tools.py` 不得直接 import `sqlglot`（T008 guard test 覆盖）
- `network_requests` 占位与续读必须复用 filter/sanitize 边界（T018 覆盖）
- 所有配置走 `get_unified_config()`，密钥无涉及
- 活文档更新清单（FR-016 / SC-005）：`docs/ARCHITECTURE.md`、`docs/design/pm_agent_design.md`、`docs/design/programmer_agent_design.md`、`docs/design/recording_tools_redesign_todo.md`、`config.example.comments.md`、`src/business/agents/prompts/pm_prompt.py`、`src/business/agents/prompts/programmer_prompt.py`
