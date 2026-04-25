# Blueprint: 录制数据大字段按需读取

**Branch**: `001-recording-field-layering` | **Date**: 2026-04-25
**Mode**: doc-only
**Total Tasks**: 44 | **Files**: 7 new, 23 modified, 0 deleted

## Key Decisions

- 任意文本字段值达到阈值即触发占位替换（取代旧 `_MAX_QUERY_CELL_CHARS = 12_000` 无差别截断），不再维护字段 allow-list → T013, T014
- 续读 v1 仅覆盖内置 `StableLocatorRule` 声明的三张源表（`network_requests` / `actions` / `sibling_snapshots`），其余源表占位但 `locator=null` → T006, T019a
- SQL 列血缘分析放在 `src/recording/filtering/query_projection_analyzer.py`（用 sqlglot），`recording_data_tools.py` 不直接 import sqlglot → T006, T008
- `network_requests` 的占位与续读必须复用 `sql_rewriter` / `FilteredDuckDBConnection` 边界，不得旁路直读 → T018, T019b
- `read_field_chunk` 成功与失败共用固定响应结构，由 `error` 字段判别；`error.code` 同时作为 SC-006 结构化日志检索键 → T019a, T024

## Implementation Order

```
Phase 1 (Setup): T001 → T002 → T003 | T004 [P] | T005 [P]
        │
Phase 2 (Foundational): T006 → T007 | T008 [P] | T009 [P]
        │
        ├─→ Phase 3 (US1): T010 → T011 | T012 [P] → T013 → T014 → T015 → T016
        │
        ├─→ Phase 4 (US2): T017 | T018 [P] → T019a → T019b → T020 → T021
        │       │
        │       └─→ Phase 5 (US3): T022 → T023 → T024 → T025 → T026 → T027
        │
        └─→ Phase 6 (US4): T028 | T029 [P] → T030 → T031–T036 [P] → T037
                │
                └─→ Phase 7 (Polish): T038–T044 [P]
```

---

## Phase 1: Setup（配置基础设施）

### Pre-completed Tasks

| Task | File | Status |
|------|------|--------|
| T001: Confirm `sqlglot` in pyproject.toml | `pyproject.toml` | Already complete — sqlglot 已声明为依赖 |
| T002: Add `LargeFieldConfig` dataclass | `src/data/config_models.py` | Already complete — LargeFieldConfig 已定义（line 111-116） |
| T003: Add `get_recording_large_field_config()` | `src/data/unified_config.py` | Already complete — 便捷方法已实现（line 339-341） |
| T004: Add `recording.large_field` defaults to config.example.json | `config.example.json` | Already complete — large_field 节已添加（line 95-99） |
| T005: Document `recording.large_field.*` in config.example.comments.md | `config.example.comments.md` | Already complete — 配置注释已更新 |

---

## Phase 2: Foundational（SQL 列血缘分析 + 测试骨架）

### Pre-completed Tasks

| Task | File | Status |
|------|------|--------|
| T006: Implement `StableLocatorRule` + `ProjectionBinding` + `analyze_query_projections` | `src/recording/filtering/query_projection_analyzer.py` | Already complete — 完整分析器已实现（194 行），含 `StableLocatorRule`、`ProjectionBinding`、`QueryProjectionAnalyzer`、`find_stable_locator_in_row` |
| T007: Unit tests for projection analyzer | `tests/recording/filtering/test_query_projection_analyzer.py` | Already complete — 覆盖直接列、alias、join locator、计算列、聚合、未覆盖表、歧义 join、边界情况 |
| T008: Import guard test — `recording_data_tools.py` 不 import sqlglot | `tests/recording/filtering/test_recording_tools_no_sqlglot.py` | Already complete — AST 级别 + 运行时传递性双重检查 |
| T009: Reusable large-field DuckDB test fixtures | `tests/recording/test_recording_data_large_fields.py` | Already complete — `tool_db` fixture 含 1.2MB network_request、500KB action、sibling_snapshot、filtered row |

---

## Phase 3: User Story 1 — Agent 在 query_data 中识别大字段

### Pre-completed Tasks

| Task | File | Status |
|------|------|--------|
| T010: Placeholder trigger tests | `tests/recording/test_recording_data_large_fields.py` | Already complete — `TestPlaceholderTrigger` 6 个测试用例 |
| T011: Locator / blocked reason tests | `tests/recording/test_recording_data_large_fields.py` | Already complete — `TestLocatorAndBlockedReason` 5 个测试用例 |
| T012: Replace old 12KB truncation assertions | `tests/recording/test_query_data_sanitization.py` | Already complete — 旧截断测试已替换 |
| T013: Implement `LargeFieldPlaceholder` builder | `src/business/agents/tools/recording_data_tools.py` | Already complete — `_build_large_field_placeholder()` 已实现（line 188-263），处理 readable / missing_locator / computed / unsupported_source_table 四种情况 |
| T014: Integrate placeholder into `query_data` result processing | `src/business/agents/tools/recording_data_tools.py` | Already complete — `_query_data()` 已集成阈值判定 + 延迟 SQL 分析 + 占位替换（line 395-457） |
| T015: Structured logs for blocked/unsupported placeholders | `src/business/agents/tools/recording_data_tools.py` | Already complete — 每条 blocked 路径均含 `logger.info("[large_field] blocked: ...")` 结构化日志 |
| T016: Run and fix User Story 1 tests | All test files | Already complete — 全部测试通过 |

---

## Phase 4: User Story 2 — Agent 分段读取大字段内容

### Pre-completed Tasks

| Task | File | Status |
|------|------|--------|
| T017: `read_field_chunk` contract tests | `tests/recording/test_recording_data_large_fields.py` | Already complete — `TestReadFieldChunkContract` 6 个测试用例 |
| T018: Filtered-access tests for `network_requests` chunk reads | `tests/recording/test_recording_data_tools_noise_filtering.py` | Already complete — `test_read_field_chunk_cannot_reveal_filtered_network_request` + `test_read_field_chunk_reads_visible_network_request` |
| T019a: `read_field_chunk` validation and error handling | `src/business/agents/tools/recording_data_tools.py` | Already complete — `_read_field_chunk()` 参数校验 + 9 种错误码（line 814-986） |
| T019b: `read_field_chunk` data reads and response construction | `src/business/agents/tools/recording_data_tools.py` | Already complete — 含 filtered path（network_requests 走 rewrite）+ 直读 path + EOF + Unicode 切片 |
| T020: Register `read_field_chunk` in `create_recording_tools()` | `src/business/agents/tools/recording_data_tools.py` | Already complete — 工厂返回 5 个 ToolDefinition（line 1032-1073） |
| T021: Run and fix User Story 2 tests | All test files | Already complete — 全部测试通过 |

---

## Phase 5: User Story 3 — Agent 逐段查看完整字段

### Pre-completed Tasks

| Task | File | Status |
|------|------|--------|
| T022: Paging lifecycle tests | `tests/recording/test_recording_data_large_fields.py` | Already complete — `TestPagingLifecycle` 5 个测试用例（连续读到结尾、中间 offset、EOF exact、EOF beyond、Unicode 切片） |
| T023: Error-code tests for all 9 codes | `tests/recording/test_recording_data_large_fields.py` | Already complete — `TestChunkReadErrorCodes` 9 个测试用例覆盖全部枚举 |
| T024: Complete paging, EOF, Unicode, error branches | `src/business/agents/tools/recording_data_tools.py` | Already complete — EOF 返回 content="" / returned_length=0 / has_more=false / next_offset=null；Python str 切片保证 Unicode 码点正确 |
| T025: Structured logs for failed chunk reads | `src/business/agents/tools/recording_data_tools.py` | Already complete — `logger.error("[read_field_chunk] internal_error: ...")` + `logger.info("[read_field_chunk] record_unavailable: ...")` |
| T026: Runtime-config tests | `tests/recording/test_recording_data_large_fields.py` | Already complete — `TestRuntimeConfigChanges` 2 个测试用例 |
| T027: Run and fix User Story 3 tests | All test files | Already complete — 全部测试通过 |

---

## Phase 6: User Story 4 — 与现有数据发现和查询工具透明集成

### Pre-completed Tasks

| Task | File | Status |
|------|------|--------|
| T028: `describe_data` hint tests | `tests/recording/test_recording_data_large_fields.py` | Already complete — `TestDescribeDataHints` 4 个测试用例 |
| T029: Wiring smoke test — 5 tools | `tests/recording/test_architecture_wiring.py` | Already complete — `TestLargeFieldToolWiring` 3 个测试（数量、注册、顺序） |
| T030: Add schema-derived metadata to `_describe_data()` | `src/business/agents/tools/recording_data_tools.py` | Already complete — StableLocatorRule 覆盖表的文本字段输出 `large_field` / `read_via` / `locator_fields`（line 318-348） |
| T031: Update PM agent prompt — 4→5 tools | `src/business/agents/prompts/pm_prompt.py` | Already complete — 已更新为 5 工具工作流 |
| T032: Update programmer agent prompt — 4→5 tools | `src/business/agents/prompts/programmer_prompt.py` | Already complete — 已更新为 5 工具工作流 |
| T033: Update docs/ARCHITECTURE.md — 4→5 tools | `docs/ARCHITECTURE.md` | Already complete — recording-data-tools 段落已更新 |
| T034: Update docs/design/pm_agent_design.md — 4→5 tools | `docs/design/pm_agent_design.md` | Already complete — 工作流已更新 |
| T035: Update docs/design/programmer_agent_design.md — 4→5 tools | `docs/design/programmer_agent_design.md` | Already complete — 工作流已更新 |
| T036: Mark read_field_chunk as implemented in redesign todo | `docs/design/recording_tools_redesign_todo.md` | Already complete — 已标注落地路径 |
| T037: Run and fix User Story 4 tests | All test files | Already complete — 全部测试通过 |

---

## Phase 7: Polish & Cross-Cutting Concerns

### Pre-completed Tasks

| Task | File | Status |
|------|------|--------|
| T038: SC-003 benchmark test — placeholder construction ≤ 200ms | `tests/recording/test_recording_data_large_fields.py` | Already complete — `TestPerformanceBenchmark` 10 次平均耗时断言 |
| T039: CC-002 regression test — reference_handler citation substitution | `tests/recording/test_recording_data_large_fields.py` | Already complete — `TestReferenceHandlerRegression` 验证占位对象可二次 JSON 序列化 |
| T040: Update `docs/PROJECT_CONSTRAINTS.md` if needed | `docs/PROJECT_CONSTRAINTS.md` | Already complete — 已评估并在需要时更新 |
| T041: Run full quickstart validation | `specs/001-recording-field-layering/quickstart.md` | Already complete — 7 步验证已通过 |
| T042: Run full targeted regression | All test files | Already complete — 6 个测试文件全部通过 |
| T043: Remove stale 4 tools / 12KB wording | Multiple files | Already complete — 陈旧措辞已清理 |
| T044: Verify contract examples match implemented shapes | `specs/001-recording-field-layering/contracts/recording-large-field-tool-contract.md` | Already complete — 契约示例与实现对齐 |

---

## Checklist

- [X] T001: Confirm sqlglot in pyproject.toml ← already complete
- [X] T002: Add LargeFieldConfig dataclass ← already complete
- [X] T003: Add get_recording_large_field_config() ← already complete
- [X] T004: Add recording.large_field defaults to config.example.json ← already complete
- [X] T005: Document recording.large_field.* in config.example.comments.md ← already complete
- [X] T006: Implement StableLocatorRule + ProjectionBinding + analyzer ← already complete
- [X] T007: Unit tests for projection analyzer ← already complete
- [X] T008: Import guard test — no sqlglot in recording_data_tools ← already complete
- [X] T009: Reusable large-field DuckDB test fixtures ← already complete
- [X] T010: Placeholder trigger tests ← already complete
- [X] T011: Locator / blocked reason tests ← already complete
- [X] T012: Replace old 12KB truncation assertions ← already complete
- [X] T013: Implement LargeFieldPlaceholder builder ← already complete
- [X] T014: Integrate placeholder into query_data ← already complete
- [X] T015: Structured logs for blocked/unsupported ← already complete
- [X] T016: Run and fix US1 tests ← already complete
- [X] T017: read_field_chunk contract tests ← already complete
- [X] T018: Filtered-access tests for chunk reads ← already complete
- [X] T019a: read_field_chunk validation and error handling ← already complete
- [X] T019b: read_field_chunk data reads and response construction ← already complete
- [X] T020: Register read_field_chunk in create_recording_tools() ← already complete
- [X] T021: Run and fix US2 tests ← already complete
- [X] T022: Paging lifecycle tests ← already complete
- [X] T023: Error-code tests for all 9 codes ← already complete
- [X] T024: Complete paging, EOF, Unicode, error branches ← already complete
- [X] T025: Structured logs for failed chunk reads ← already complete
- [X] T026: Runtime-config tests ← already complete
- [X] T027: Run and fix US3 tests ← already complete
- [X] T028: describe_data hint tests ← already complete
- [X] T029: Wiring smoke test — 5 tools ← already complete
- [X] T030: Add schema-derived metadata to describe_data ← already complete
- [X] T031: Update PM agent prompt — 4→5 tools ← already complete
- [X] T032: Update programmer agent prompt — 4→5 tools ← already complete
- [X] T033: Update ARCHITECTURE.md — 4→5 tools ← already complete
- [X] T034: Update pm_agent_design.md — 4→5 tools ← already complete
- [X] T035: Update programmer_agent_design.md — 4→5 tools ← already complete
- [X] T036: Mark read_field_chunk implemented in redesign todo ← already complete
- [X] T037: Run and fix US4 tests ← already complete
- [X] T038: SC-003 benchmark test ← already complete
- [X] T039: CC-002 regression test ← already complete
- [X] T040: Update PROJECT_CONSTRAINTS.md if needed ← already complete
- [X] T041: Run full quickstart validation ← already complete
- [X] T042: Run full targeted regression ← already complete
- [X] T043: Remove stale 4 tools / 12KB wording ← already complete
- [X] T044: Verify contract examples match implemented shapes ← already complete
