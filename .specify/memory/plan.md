# Main Implementation Plan Memory

**Purpose**: Consolidated technical state from all merged features. Reflects the *implemented* state of the system.
**Last Updated**: 2026-04-25
**Revision**: 2026-04-25 — Bootstrapped from `specs/001-recording-field-layering`

---

## Technical Context

**Language/Version**: Python 3.11+ (runtime 3.12)
**Primary Dependencies**: PyQt6, SQLite (SQLAlchemy/Alembic), DuckDB, Playwright, blinker, sqlglot, LangChain, mitmproxy, AgentLoop (自研)
**Storage**: SQLite (业务数据, via Repository); DuckDB (录制分析数据, via FilteredDuckDBConnection/sql_rewriter)
**Testing**: pytest (`tests/`)
**Target Platform**: Windows + Linux desktop
**Project Type**: Desktop application (single repo)

---

## Current Project Structure

```
src/
├── business/
│   └── agents/
│       ├── tools/
│       │   ├── recording_data_tools.py     # 5 工具: describe_data, query_data, execute_code, read_recording, read_field_chunk
│       │   └── builtin_general_tools.py
│       └── prompts/
│           ├── pm_prompt.py                # 5 工具工作流
│           └── programmer_prompt.py        # 5 工具工作流
├── recording/
│   └── filtering/
│       ├── query_projection_analyzer.py    # SQL 列血缘分析 (sqlglot), StableLocatorRule, ProjectionBinding
│       ├── sql_rewriter.py                 # network_requests SQL rewrite + filter
│       └── filtered_conn.py               # FilteredDuckDBConnection
└── data/
    ├── config_models.py                    # LargeFieldConfig dataclass (threshold/preview/chunk)
    └── unified_config.py                   # get_recording_large_field_config()

tests/
├── recording/
│   ├── test_recording_data_large_fields.py         # 占位+续读+错误码+EOF+性能+配置变更测试
│   ├── test_query_data_sanitization.py             # 大字段替换后的 query_data 验证
│   ├── test_recording_data_tools_noise_filtering.py # filter 边界 + chunk read filter 测试
│   ├── test_architecture_wiring.py                 # 5 工具注册 wiring smoke
│   └── filtering/
│       ├── test_query_projection_analyzer.py       # 投影分析器 unit tests
│       └── test_recording_tools_no_sqlglot.py      # guard test: recording_data_tools 不 import sqlglot
```

[Source: specs/001-recording-field-layering]

---

## Configuration

### recording.large_field.* (via UnifiedConfigManager)

| Key | Type | Default | Effect |
|-----|------|---------|--------|
| `recording.large_field.threshold_chars` | int | 1000 | 文本字段值 ≥ 此值触发占位替换 |
| `recording.large_field.preview_chars` | int | 1000 | 占位对象 preview 前缀最大字符数 |
| `recording.large_field.max_chunk_chars` | int | 1000 | read_field_chunk 单次 content 最大字符数 |

配置变更仅影响后续阈值/预览/chunk 大小，不使既有 locator 失效。

[Source: specs/001-recording-field-layering]

---

## Tool Architecture

### Recording Data Tools (5 tools, registered via `create_recording_tools()`)

1. **describe_data** — 表结构 + 大字段提示 (`large_field` / `read_via` / `locator_fields`)
2. **query_data** — SQL 查询 + 大字段自动占位替换
3. **execute_code** — 代码执行
4. **read_recording** — 录制元数据
5. **read_field_chunk** — 大字段分段读取 (新增)

### SQL 列血缘分析

`query_projection_analyzer.py` 使用 sqlglot 分析 SQL AST，为每个结果列生成 `ProjectionBinding`（直接列 vs 计算列），结合 `StableLocatorRule` 判定是否支持续读。

### Filter Boundary

- `network_requests`: 占位 + 续读必须走 `sql_rewriter` / `FilteredDuckDBConnection`
- 其他 StableLocatorRule 覆盖表：参数化单行直读
- `recording_data_tools.py` 不直接 import `sqlglot`（guard test 约束）

[Source: specs/001-recording-field-layering]

---

## StableLocatorRule Coverage (v1)

| Table | Stable ID Field | describe_locator_fields |
|-------|----------------|------------------------|
| `network_requests` | `request_id` | `["request_id"]` |
| `actions` | `action_id` | `["action_id"]` |
| `sibling_snapshots` | `snapshot_id` | `["snapshot_id"]` |

[Source: specs/001-recording-field-layering]

---

## Testing Strategy

- **Unit**: 投影分析器、占位 builder、chunk reader、错误码枚举
- **Integration**: describe_data → query_data → read_field_chunk 全链路
- **Wiring smoke**: `create_recording_tools()` 返回 5 个 ToolDefinition
- **Guard**: `recording_data_tools.py` 不导入 `sqlglot`
- **Performance**: SC-003 占位构造 ≤ 200ms (in-process benchmark)
- **Regression**: CC-002 reference_handler 正交性、SC-004 小字段零回归

[Source: specs/001-recording-field-layering]
