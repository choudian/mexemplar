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

## AgentLoop 多工具调用结果配对修复 — 2026-04-26

**Branch:** `003-fix-agentloop-tool-calls`
**Spec:** `specs/003-fix-agentloop-tool-calls`

**What was added:**
- US-005 (P1): 多工具调用完整配对 — 同轮多个普通工具按顺序执行并逐一保存结果
- US-006 (P1): 中断型工具行为可预期 — 混合批次拒绝、solo 中断保留既有语义、handler 契约校验
- US-007 (P2): 会话恢复按原始顺序补齐缺失结果，不重复已完成调用

**New Components:**
- `ToolDefinition.is_interrupting` — 声明式中断型分类字段
- `classify_tool_calls()` — 批次分类 helper
- `make_error_result()` / `ERROR_CODES` — 标准化错误结构生成
- `tests/integration/test_agent_loop_multi_tool_calls.py` — 14 场景集成测试

**Modified Components:**
- `src/business/agents/agent_loop.py` — 多工具批次处理、失败级联、中断校验、契约校验、恢复
- `src/business/agents/config.py` — ToolDefinition 新增 `is_interrupting` 字段
- `src/business/agents/tools/*.py` — 中断型工具注册添加 `is_interrupting=True`
- `src/business/memory/context_manager.py` — `get_pending_tool_calls()` 多工具恢复

**Tasks Completed:** 34/34 tasks

## 工具执行 Pre/Post Hook 系统 — 2026-04-27

**Branch:** `002-tool-hook-system`
**Spec:** `specs/002-tool-hook-system`

**What was added:**
- US-008 (P1): `ToolDefinition` 支持工具级 pre/post hook，未声明 hook 的工具保持透明行为
- US-009 (P2): `builtin_general_tools`、`recording_data_tools`、`trial_tools` 的门卫式 gate 迁移到 pre_hook
- US-010 (P3): `AgentConfig` 支持实例级 global pre/post hooks，按固定顺序作用于 `ToolDefinition` 工具

**New Components:**
- `src/business/agents/hook_models.py` — hook 协议 dataclass/type alias 与递归 args freezing helper
- `tests/test_hook_protocol.py` — hook 协议、迁移 gate、global hook、动态工具和性能烟测覆盖

**Modified Components:**
- `src/business/agents/agent_loop.py` — hook-aware per-call execution、hook 异常处理、post_hook rewrite、可靠失败状态
- `src/business/agents/config.py` — `ToolDefinition.pre_hook/post_hook` 与 `AgentConfig.global_pre_hooks/global_post_hooks`
- `src/business/agents/tools/builtin_general_tools.py` — read/write/edit/list/exec pre_hooks；确认请求失败 fail-closed
- `src/business/agents/tools/recording_data_tools.py` — query_data/analyze_image gate pre_hooks
- `src/business/agents/tools/trial_tools.py` — run_command per-run pre_hook 限流
- `docs/ARCHITECTURE.md` / `docs/PROJECT_CONSTRAINTS.md` — hook 运行结构与边界文档

**Tasks Completed:** 34/37 tasks
