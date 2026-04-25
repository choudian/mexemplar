# Implementation Plan: 录制数据大字段按需读取

**Branch**: `001-recording-field-layering` | **Date**: 2026-04-23 | **Spec**: `./spec.md`
**Input**: Feature specification from `/specs/001-recording-field-layering/spec.md`

## Summary

把 `query_data` 当前对所有字符串列无差别截断到 12KB 的旧行为，替换为"任意文本字段值 ≥ `threshold_chars`（默认 1000）→ 返回结构化占位对象 + 1KB 预览 + `read_field_chunk` 续读提示"的新交付协议；新增工具 `read_field_chunk` 按 `locator + field + offset[+ length]` 从源表（沿用 `network_requests` 的 filter/sanitize 边界）按字符切片读取原文，单段 `content` 硬上限 `max_chunk_chars`（默认 1000）。`describe_data` 增补 `large_field` / `read_via` / `locator_fields` 三项机器可读元数据，基于当前 schema + stable locator 规则把"哪些文本字段达到阈值后会进入该工作流、续读靠哪个稳定 ID 字段"提前告知 Agent。SQL 列血缘分析放在 `src/recording/filtering/query_projection_analyzer.py`（基于 `sqlglot`），在 `recording_data_tools.py` 之外完成"该输出列是否直接源字段、是否同行携带稳定定位字段"的判定，保持工具层不直接 import `sqlglot` 的现有边界。

## Technical Context

**Language/Version**: Python 3.11+
**Primary Dependencies**: DuckDB（`FilteredDuckDBConnection` / `sql_rewriter`）、`sqlglot`（仅在 `src/recording/filtering/`）、`blinker`（事件，本特性不新增事件）、AgentLoop / Agent SDK ToolDefinition、PyQt6（不直接触达）
**Storage**: DuckDB（录制分析层；本特性只读，不改 schema）；SQLite（业务配置层，仅扩展 `recording.large_field.*` 数值配置项）
**Testing**: pytest（已有 `tests/recording/`、`tests/recording/filtering/` 命名空间）
**Target Platform**: 与现有 Mexemplar 桌面运行时一致（Windows + Linux）
**Project Type**: Single-project（已有 `src/` + `tests/` 布局）
**Performance Goals**: 占位替换额外延迟 ≤ 200ms（`SC-003`；in-process、单条 1.2MB 行、仅计占位构造增量耗时）；`read_field_chunk` 不设硬性延迟目标（spec 已澄清）
**Constraints**:
- 单段 `content` ≤ `max_chunk_chars`（默认 1000 字符）
- 占位 `preview` ≤ `preview_chars`（默认 1000 字符），元数据为固定小结构；默认配置下整体 JSON 预期约为 2KB 量级，但不作为独立硬验收线
- `network_requests` 的占位与续读必须复用现有 filter / sanitize 边界（`CC-003a`），不得旁路直读
- 占位/续读全程 deterministic（不调 LLM）
**Scale/Scope**: 单个 1.2MB+ 网络响应体可被分段读取至完结；同一查询结果中多个大字段独立占位（无聚合上限）

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate question | Evidence required |
|-----------|---------------|-------------------|
| I. 分层边界与事件协调 | 设计是否保持 `UI -> business -> data/driver` 方向？跨模块通知是否走 `blinker`？ | 触及层：`business/agents/tools`（新工具）、`recording/filtering`（新分析器）、`data`（配置项）。**无新事件**——`read_field_chunk` 同步返回；不引入 worker / 跨线程通知。`recording_data_tools.py` 不直接 import `sqlglot`，沿用既有 gatekeeper 测试 |
| II. 数据边界与持久化纪律 | SQLite/DuckDB 责任划分清楚？Repository 边界保留？`network_requests` 读取是否仍经过 filter/sanitize？ | DuckDB：仅读，无 schema/migration。`network_requests` 的占位与续读全部经 `FilteredDuckDBConnection` / `sql_rewriter`（**新增 gatekeeper 测试**：`read_field_chunk` 调用 `network_requests` 时不得直连 raw DuckDB）。其他源表（`actions`、`sibling_snapshots`、未来扩展）允许参数化直读，但同样限制为单条按 `id_field` 读取 |
| III. 统一配置与密钥安全 | 新设置走 `UnifiedConfigManager`？密钥是否离开代码？ | 新增 `recording.large_field.{threshold_chars, preview_chars, max_chunk_chars}`，通过 `config_models.py` 定义、`UnifiedConfigManager` 读写、`config.example.json` + `config.example.comments.md` 暴露；`describe_data` hints 基于当前 schema + stable locator 规则派生，不额外维护字段名单配置。**无密钥** |
| IV. 可验证交付 | 计划是否包含确定性逻辑的自动化覆盖、新接线的 wiring smoke 与 guard 测试？ | Unit：projection analyzer、placeholder builder、chunk reader、错误码枚举。Integration：`describe_data` → `query_data` → `read_field_chunk` 全链路 quickstart 验证。Wiring smoke：`read_field_chunk` 已注册进 PM/程序员 agent 的 ToolDefinition 列表。Guard：`recording_data_tools.py` 不导入 `sqlglot`；`read_field_chunk` 对 `network_requests` 不调用裸 `duckdb.connect` |
| V. 活文档与规格驱动交付 | 受影响活文档已识别？临时材料留 `docs/local/`？ | 按 `FR-016` / `SC-005` 必须更新：`docs/ARCHITECTURE.md`、`docs/design/pm_agent_design.md`、`docs/design/programmer_agent_design.md`、`docs/design/recording_tools_redesign_todo.md`、`config.example.comments.md`、`src/business/agents/prompts/pm_prompt.py`、`src/business/agents/prompts/programmer_prompt.py`；约束面变化时同步 `docs/PROJECT_CONSTRAINTS.md`。本计划与下游 research/data-model/contracts/quickstart 留在 `specs/001-recording-field-layering/`，不进 `docs/local/` |

**结论**：所有 gate 通过，无需 Complexity Tracking。

## Project Structure

### Documentation (this feature)

```text
specs/001-recording-field-layering/
├── plan.md              # 本文件
├── spec.md              # 已经过两轮 + 本次 5 题澄清
├── research.md          # Phase 0：6 个 decision（均已与最新澄清对齐）
├── data-model.md        # Phase 1：7 个实体 + 1 个错误码枚举
├── quickstart.md        # Phase 1：6 步验收路径
├── contracts/
│   └── recording-large-field-tool-contract.md   # describe_data / query_data / read_field_chunk 三方契约
└── checklists/
    ├── gate.md                                  # 历史重型 gate 清单，仅作参考
    └── large-fields.md                          # 当前正式需求质量 checklist
```

### Source Code (repository root)

```text
src/
├── business/
│   └── agents/
│       ├── tools/
│       │   ├── recording_data_tools.py        # 修改：query_data 注入 placeholder builder；新工具 read_field_chunk
│       │   └── builtin_general_tools.py       # （仅引用，确认未受影响）
│       └── prompts/
│           ├── pm_prompt.py                    # 修改：4 tools → 5 tools 工作流
│           └── programmer_prompt.py            # 修改：同上
├── recording/
│   └── filtering/
│       ├── query_projection_analyzer.py        # 新增：sqlglot 列血缘分析（直接列 vs 计算列、同行 ID 列）
│       ├── sql_rewriter.py                     # （沿用，read_field_chunk 走它访问 network_requests）
│       └── filtered_conn.py                    # （沿用）
└── data/
    ├── config_models.py                        # 修改：新增 LargeFieldConfig dataclass
    └── unified_config.py                       # 修改：注册新 namespace（若需要）

config.example.json                             # 修改：新增 recording.large_field.* 默认值
config.example.comments.md                      # 修改：解释新配置项 + 5 工具工作流

tests/
├── recording/
│   ├── test_recording_data_large_fields.py     # 新增：占位 + 续读 + 错误码 + EOF 行为
│   ├── test_query_data_sanitization.py         # 修改：旧 12KB 行为断言移除/替换
│   ├── test_recording_data_tools_noise_filtering.py  # （回归）
│   ├── test_architecture_wiring.py            # 新增：wiring smoke（read_field_chunk 注册为第 5 工具）
│   └── filtering/
│       ├── test_query_projection_analyzer.py   # 新增：unit
│       └── test_recording_tools_no_sqlglot.py  # 新增：guard test（recording_data_tools.py 不 import sqlglot）

docs/
├── ARCHITECTURE.md                             # 修改：record-data tools 段落 4→5 工具
├── PROJECT_CONSTRAINTS.md                      # 修改（仅当约束面变化时）
└── design/
    ├── pm_agent_design.md                      # 修改：工作流 4→5 工具
    ├── programmer_agent_design.md              # 修改：同上
    └── recording_tools_redesign_todo.md        # 修改：标注 read_field_chunk 已落地路径
```

**Structure Decision**: 沿用现有 `src/{business,recording,data}/...` + `tests/{recording,...}/` 单仓布局；本特性不引入新顶层目录、不分前后端、不拆 lib。SQL 列血缘分析严格留在 `src/recording/filtering/`，与既有边界一致（`recording_data_tools.py` 经过 gatekeeper 测试禁止直接 import `sqlglot`）。

## Phase 0 Status

`research.md` 已存在且与最新澄清对齐：

| Decision | 状态 | 备注 |
|----------|------|------|
| D1: SQL 列血缘分析放在 `src/recording/filtering/` | 保持 | 与 II / I 原则一致 |
| D2: 配置归入 `recording.large_field.*` | **修订** | 仅保留 `threshold_chars` / `preview_chars` / `max_chunk_chars` 三个数值项；`describe_data` hints 改为基于当前 schema + stable locator 规则派生，不再保留显式 hint list |
| D3: 用结构化占位替换截断文本 | 保持 | 与 `FR-002` / `FR-003` 一致 |
| D4: 续读 locator 仅由"同行直接 ID 列"构造 | **修订** | 不再使用字段 allow-list；placeholder 适用于任意达到阈值的文本结果列。续读 v1 限定在内置 `StableLocatorRule` 覆盖的源表（初始 `network_requests` / `actions` / `sibling_snapshots`），且必须是直接选择源字段 + 同行直接选择该表稳定 ID 列 |
| D5: 续读 `network_requests` 必须复用 filter 边界 | 保持 | `CC-003a` 硬约束 |
| D6: 默认 `threshold_chars=1000`、`preview_chars=1000`、`max_chunk_chars=1000` | 保持 | 按 Q3/Q4 决定：`max_chunk_chars=1000`；`preview_chars` 默认值收敛到 1000（与单段一致），不再保留 4000 的旧值 |

> 下文 Phase 1 的 data-model / contracts 已按修订后的 Decision 4 / Decision 6 同步更新。

## Phase 1 Status

| Artifact | 状态 |
|----------|------|
| `data-model.md` | 已更新：`LargeFieldConfig` 仅保留数值配置项；用 `StableLocatorRule` 表达 table-level locator metadata；`ChunkReadRequest.length` 标为可选；`ChunkReadResponse` 新增 `error: {code, message} \| null` |
| `contracts/recording-large-field-tool-contract.md` | 已更新：trigger rules 移除旧 `enabled_fields` gate；request 中 `length` 标可选；success/error 合并为单 schema（`error == null` 即成功）；error 段列出枚举 code |
| `quickstart.md` | 已更新：示例 `length` 取消硬写 4000；EOF 与错误返回示例对齐新结构；补充 `SC-003` 的 in-process 测量口径 |
| `AGENTS.md` / `CLAUDE.md` SPECKIT marker | 已更新：均指向本 `plan.md` |

## Follow-up Status

1. **旧的"字段未配置为可分段读取"措辞**：已在 `spec.md` 回写为"字段不存在 / 非文本 / 定位列非法或不稳定 / 数据不可用"等现行错误语义。
2. **`enabled_hint_fields` 是否保留**：已拍板为不保留；`describe_data` hints 改为基于当前 schema + stable locator 规则自动派生。
3. **`SC-003` 的 200ms 测量口径**：已拍板为 in-process 增量测量（单条 1.2MB 行；只计占位构造与结果结构化，不含 GUI/启动/人工操作/`read_field_chunk`）。

## Complexity Tracking

> Constitution Check 全部通过，无需填写。
