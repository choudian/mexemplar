# Merged Features Log

## 录制数据大字段按需读取 — 2026-04-25

**Branch:** `001-recording-field-layering`
**Spec:** `specs/001-recording-field-layering`

**What was added:**
- US-001 (P1): query_data 对任意达到阈值的文本字段返回结构化占位对象，取代旧 12KB 截断
- US-002 (P1): 新增 `read_field_chunk` 工具，Agent 按 locator + field + offset 分段读取原文
- US-003 (P2): 多次续读闭环、EOF 空成功、Unicode 码点切片、9 种错误码全覆盖
- US-004 (P2): describe_data 增补机器可读大字段提示；prompt/文档更新为 5 工具工作流

**New Components:**
- `src/recording/filtering/query_projection_analyzer.py` — SQL 列血缘分析 (sqlglot)
- `tests/recording/test_recording_data_large_fields.py` — 占位+续读+错误+性能+配置测试
- `tests/recording/filtering/test_query_projection_analyzer.py` — 分析器单元测试
- `tests/recording/filtering/test_recording_tools_no_sqlglot.py` — import guard test

**Modified Components:**
- `src/business/agents/tools/recording_data_tools.py` — 占位 builder + read_field_chunk + 5 工具注册
- `src/data/config_models.py` — LargeFieldConfig dataclass
- `src/data/unified_config.py` — get_recording_large_field_config()
- `config.example.json` / `config.example.comments.md` — recording.large_field.* 配置
- `src/business/agents/prompts/pm_prompt.py` / `programmer_prompt.py` — 5 工具工作流
- `docs/ARCHITECTURE.md` / `docs/design/*.md` — 文档同步

**Tasks Completed:** 44/44 tasks
