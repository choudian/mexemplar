# Main Implementation Plan Memory

**Purpose**: Consolidated technical state from all merged features. Reflects the *implemented* state of the system.
**Last Updated**: 2026-04-27
**Revision**: 2026-04-27 — Merged `specs/004-auth-toast`

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
│       ├── config.py                       # ToolDefinition (含 is_interrupting/pre_hook/post_hook) 与 AgentConfig global hooks
│       ├── agent_loop.py                   # 多工具批次处理、hook 执行、失败级联、中断校验、契约校验
│       ├── hook_models.py                  # ToolCallContext / PreHookResult / PostHookResult / args freezing
│       ├── tools/
│       │   ├── recording_data_tools.py     # 5 工具: describe_data, query_data, execute_code, read_recording, read_field_chunk
│       │   ├── pm_output_tools.py          # PM 中断型工具 (talk_to_user 等)
│       │   ├── programmer_tools.py         # 程序员工具
│       │   ├── trial_tools.py              # 试用工具；run_command per-run pre_hook 限流
│       │   └── builtin_general_tools.py    # read/write/edit/list/exec pre_hooks + 确认状态/自动放行/脱敏日志
│       └── prompts/
│           ├── pm_prompt.py                # 5 工具工作流
│           └── programmer_prompt.py        # 5 工具工作流
│   ├── ai/
│   │   └── llm_client.py                  # LLMResponse.tool_calls 完整暴露
│   └── memory/
│       └── context_manager.py             # get_pending_tool_calls (多工具恢复)
├── ui/
│   ├── main_window.py                       # auth toast 状态/队列/resize 重定位
│   ├── mixins/
│   │   ├── agent_bridge_mixin.py            # register_confirm_mechanism wiring
│   │   └── agent_handler_mixin.py           # 非阻塞确认队列 + toast 决策处理
│   ├── resources/
│   │   └── styles.qss                       # auth toast + 顶栏 Toggle 样式
│   └── widgets/
│       ├── chat_widget.py                   # 顶栏 "免确认" Toggle + new_chat_started
│       └── auth_toast.py                    # AuthToastSurface 非模态确认浮层
├── recording/
│   └── filtering/
│       ├── query_projection_analyzer.py    # SQL 列血缘分析 (sqlglot), StableLocatorRule, ProjectionBinding
│       ├── sql_rewriter.py                 # network_requests SQL rewrite + filter
│       └── filtered_conn.py               # FilteredDuckDBConnection
└── data/
    ├── config_models.py                    # LargeFieldConfig dataclass (threshold/preview/chunk)
    └── unified_config.py                   # get_recording_large_field_config()

tests/
├── test_hook_protocol.py                    # hook 协议、迁移 gate、global hook、动态工具、性能烟测
├── test_auth_toast_confirmation.py          # 确认状态/日志/自动放行业务测试
├── integration/
│   └── test_agent_loop_multi_tool_calls.py  # 多工具批次、中断型、恢复、契约校验 14 场景
├── recording/
│   ├── test_recording_data_large_fields.py         # 占位+续读+错误码+EOF+性能+配置变更测试
│   ├── test_query_data_sanitization.py             # 大字段替换后的 query_data 验证
│   ├── test_recording_data_tools_noise_filtering.py # filter 边界 + chunk read filter 测试
│   ├── test_architecture_wiring.py                 # 5 工具注册 wiring smoke
│   └── filtering/
│       ├── test_query_projection_analyzer.py       # 投影分析器 unit tests
│       └── test_recording_tools_no_sqlglot.py      # guard test: recording_data_tools 不 import sqlglot
└── ui/
    ├── test_auth_toast_surface.py           # AuthToastSurface 按钮/超时/关闭限制
    ├── test_chat_widget_auth_toggle.py      # Toggle 状态同步/新对话复位
    └── test_agent_handler_mixin.py          # 队列 FIFO/QMessageBox guard/会话切换
```

[Sources: specs/001-recording-field-layering, specs/002-tool-hook-system, specs/003-fix-agentloop-tool-calls, specs/004-auth-toast]

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

---

## Agent System Architecture

### AgentLoop 多工具批次处理 [Source: specs/003-fix-agentloop-tool-calls]

AgentLoop 在收到 LLM 响应后，按以下流程处理 tool_calls：

1. **批次分类**：调用 `classify_tool_calls()` 按 `ToolDefinition.is_interrupting` 将每个 tool call 分为 `ordinary`/`interrupting`/`unknown`
2. **三种批次路径**：
   - **Ordinary batch**（全部 ordinary/unknown）：按顺序执行，失败时级联 `not_executed`
   - **Solo interrupting**（恰好 1 个 interrupting）：执行 handler，成功则触发暂停/完成语义，异常则继续 loop
   - **Invalid-output batch**（>1 且含 interrupting）：保存原响应，不执行任何 handler，为每个 call 写入 `invalid_model_output`
3. **契约校验**：运行时检查 `is_interrupting` 与 handler 返回类型一致，不一致写入 `handler_contract_violation`
4. **恢复**：`get_pending_tool_calls()` 返回最近 assistant 消息中所有未配对调用，按原始顺序补齐

### 标准化错误结构

AgentLoop 发出的配对错误统一为顶层 JSON：`{"error": "<code>", "message": "...", ...}`
错误码枚举：`unknown_tool`、`handler_exception`、`handler_contract_violation`、`not_executed`、`invalid_model_output`、`pre_hook_rejected`

### Agent 工具执行 Hook 管线 [Source: specs/002-tool-hook-system]

Hook 执行发生在 AgentLoop 批处理分类之后、实际 handler 执行之前/之后。参与对象仅限调用方传入或动态构建的 `ToolDefinition`；AgentLoop 注入的 `talk_to_user` / `load_reference` 不进入 hook 管线。

顺序：

1. 工具级 `pre_hook`
2. 当前 `AgentConfig.global_pre_hooks`（列表顺序）
3. handler
4. 工具级 `post_hook`
5. 当前 `AgentConfig.global_post_hooks`（列表顺序）

关键运行规则：

- `ToolCallContext.args` 使用递归只读隔离视图；pre_hook 不能改写 handler 入参。
- pre_hook 返回 `PreHookResult(error=...)` 时写入 `pre_hook_rejected` 并跳过 handler/post_hook。
- pre_hook 抛异常时记录 WARNING、停止剩余 pre_hook、执行 handler、跳过全部 post_hook。
- post_hook 不做结果流水线；所有 post_hook 接收 handler 原始字符串结果，最后一个非空 rewrite 生效。
- post_hook 抛异常时返回 handler 原始结果，丢弃前序 post_hook 的部分改写。
- handler 抛异常时转换为标准化 error 字符串；若未被 pre_hook 异常短路，post_hook 仍可观察/改写该错误文本，但批处理级联依据原始失败状态。
- 合法 `ToolSignal` 跳过 post_hook；声明式 `is_interrupting` 与 handler 返回类型不一致时写入 `handler_contract_violation`。

### Migrated Gate Ownership [Source: specs/002-tool-hook-system]

- `builtin_general_tools`: `read_file` / `write_file` / `edit_file` / `list_dir` / `exec` 的路径、系统目录、命令安全和确认 gate 在 pre_hook；确认请求异常必须 fail-closed。
- `recording_data_tools`: `query_data` 复用 `rewrite(sql)` / 过滤策略做 pre_hook 拒绝判断；`analyze_image` 的 6-action 拒绝在 pre_hook。
- `trial_tools`: `run_command` 5 次上限由 `create_trial_tools()` 内的 per-run 闭包 pre_hook 维护。
- 非迁移边界：`programmer_tools.syntax_check`、`recording_data_tools.execute_code` 沙箱、`tool_executor` venv 隔离/命令白名单、`dynamic_tool_manager` 工具发现/激活。

### 结构化日志

4 类日志事件（`logger.info`）：`batch.start`、`batch.call_result`、`batch.complete`、`recovery.start`/`recovery.call_result`

---

## Testing Strategy — Agent System

- **Integration**: 14 场景覆盖普通多工具、失败级联、纯文本非失败、未知工具级联、混合中断、多中断、solo 异常、契约违反双向、恢复部分/全部/缺 handler/损坏记录、单工具回归
- **Regression**: 现有 `test_v2_full_flow.py`、`test_assistant_new_session.py` 无可见回归
- **Guard**: 下一轮 LLM messages 无未配对 tool calls

[Source: specs/003-fix-agentloop-tool-calls]

### Hook Protocol and Migration Tests [Source: specs/002-tool-hook-system]

- `tests/test_hook_protocol.py`: no-hook 透明性、pre_hook 拒绝、递归只读 args、pre/post hook 异常、post_hook rewrite、handler 异常、ToolSignal 契约、动态 callable 刷新、global hook 顺序/作用域、SC-002/SC-005 性能/挂载成本烟测。
- Migrated gate coverage: builtin general 工具拒绝路径、`query_data` parser/filter 拒绝与 harmless 路径、`analyze_image` action 上限、`run_command` 第 6 次拒绝。
- Static guards: 旧 gate 判断不残留在 handler，非迁移边界保持原位。
- Final gates: hook 协议套件、recording guard/regression、AgentLoop multi-tool smoke、syntax validation、black/flake8/full pytest 或明确例外说明。

---

## 高危操作确认 Toast 化 [Source: specs/004-auth-toast]

### 确认浮层架构

Assistant 高危工具确认从 `QMessageBox.question` 模态弹窗改为非阻塞 `AuthToastSurface` 浮层。保留现有 `builtin_general_tools` 的 request_id + `threading.Event` 等待模型和 `pyqtSignal` 跨线程通道。UI 端新增独立于普通 Toast 的确认浮层队列管理。

核心运行机制：
1. Worker 线程触发 `_ask_user_confirm` → 创建 `PendingConfirmation` → `pyqtSignal` emit request_id + message
2. UI 线程 `AgentHandlerMixin._on_confirm_action_requested` 入队 → 显示一个 `AuthToastSurface`
3. 用户决策（三按钮或超时）→ `set_confirm_result` 回写 → Worker `event.set()` 唤醒
4. 自动放行开启时（"全部允许"或顶栏 Toggle）：pre_hook 直接返回 None，不 emit signal

### 会话级自动放行状态

`_auto_approve_enabled` + `_auto_approve_source` 为模块级变量，受 `_confirm_lock` 保护。开启时覆盖 Assistant 全部高危工具（write_file/edit_file/exec）。新对话时 `reset_auto_approve` 复位。不持久化。

### 脱敏结构化日志

每次终态决策写入 `logger.info`，字段：request_id、tool_name、decision、source、elapsed_ms、summary。summary 由 `_truncate_summary` + `_sanitize_fragment` 生成，自动截断长参数并替换敏感模式（sk-*、password=、token= 等）。

### 测试覆盖

- **Business tests**: `tests/test_auth_toast_confirmation.py` — 确认状态、脱敏摘要、自动放行开关、超时映射、settle 截止时间
- **UI surface tests**: `tests/ui/test_auth_toast_surface.py` — 三按钮信号、超时触发、重复决策忽略、手动关闭拒绝
- **UI integration tests**: `tests/ui/test_agent_handler_mixin.py` — 5-Worker FIFO、Toast 共存、响应性 ≤100ms、超时收敛 ≤1s、allow-all 排队放行、Toggle 双向同步、新对话收敛、QMessageBox guard
- **ChatWidget tests**: `tests/ui/test_chat_widget_auth_toggle.py` — Toggle 默认关闭、状态同步、新对话复位
