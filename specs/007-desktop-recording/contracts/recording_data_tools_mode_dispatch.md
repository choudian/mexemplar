# Contract: 5 通用工具 mode dispatch

> 5 个通用录制数据工具（`describe_data` / `query_data` / `execute_code` / `read_recording` / `read_field_chunk`）按 `recording_mode` 内部切表的契约。

## 工厂入口

```python
# src/business/agents/tools/recording_data_tools.py

def create_recording_tools(recording_id: str) -> list[ToolDefinition]:
    """构造 5 个通用工具。工厂启动时一次查 recording_mode，闭包传给所有 handler。"""
    repo = RecordingRepository()
    recording_mode: str = repo.get_recording_mode(recording_id)  # 'browser' | 'desktop'

    return [
        _build_describe_data(recording_id, recording_mode),
        _build_query_data(recording_id, recording_mode),
        _build_execute_code(recording_id, recording_mode),
        _build_read_recording(recording_id, recording_mode),
        _build_read_field_chunk(recording_id, recording_mode),
    ]
```

**契约要点**：
- 工厂启动时**一次性**通过 `RecordingRepository.get_recording_mode(recording_id)` 查 `recording_mode`，不在 handler 内反复查；
- `get_recording_mode()` 是唯一 mode 查询入口：浏览器录制从 `recording_sessions.recording_mode` 读取，桌面录制从 `desktop_recordings.recording_mode` 读取；两表均未命中时返回标准化 `recording_not_found` 错误；
- handler 闭包捕获 `recording_mode`，与 `recording_id` 同等不可变；
- `query_data_pre_hook` 也通过闭包获得 `recording_mode`（FR-012）。

## handler 行为

### `describe_data()`

| 输入 | mode = 'browser' | mode = 'desktop' |
|---|---|---|
| 无参 | 描述浏览器 5 张表 schema（既有，字节级保留） | 描述 `desktop_recordings` / `desktop_actions` 两张表 schema |

**输出 schema 同形**：返回 `dict[str, dict]`，键为表名，值为 `{"columns": [...], "primary_key": [...], "row_count": int, ...}`。

### `query_data(sql: str)`

- 输入 SQL 字符串；
- 经 `query_data_pre_hook` 校验：
  - 调用 `src/recording/filtering/sql_rewriter.py:validate_table_against_mode_allowlist(sql, mode)`；
  - 浏览器 mode allowlist = `{recording_sessions, actions, network_requests, sibling_snapshots, recording_screenshots}`；
  - 桌面 mode allowlist = `{desktop_recordings, desktop_actions}`；
  - 跨 mode 表访问 → 返回 `{"error": "table_not_in_mode", "table": "<name>", "mode": "<current_mode>"}`（FR-012a）；
- 校验通过后执行 SQL（浏览器 mode 仍走既有 `FilteredDuckDBConnection` 过滤路径，CC-002 #2 不变）。

### `execute_code(code: str)`

- 输入 Python 代码字符串；
- 在工具内部沙箱执行（既有，与浏览器 mode 同实现，仅闭包注入的 DataFrame `df` 数据源按 mode 切：浏览器 mode = 5 张表的 join，桌面 mode = `desktop_recordings × desktop_actions` join 默认）；
- 输出 stdout 末行作为返回值。

### `read_recording(recording_id?)`

| mode | 返回 |
|---|---|
| browser | `recording_sessions` 行 + 关联表聚合摘要（既有，字节级保留） |
| desktop | `desktop_recordings` 行（含 `health_stats` JSON）+ 聚合摘要 |

**桌面聚合摘要 shape**（FR-011 + spec round 3 第 2 题）：

```json
{
  "session": {"recording_id": "...", "start_time": "...", "end_time": "...", "monitor_index": 0, "status": "stopped", "health_stats": {...}},
  "summary": {
    "action_count": 27,
    "type_counts": {"mouse_left": 14, "wheel": 2, "drag": 2, "typing": 5, "hotkey": 4, "mouse_right": 0, "mouse_middle": 0},
    "window_title_counts_top5": [["记事本", 18], ["桌面", 5], ["资源管理器", 4]],
    "time_range": {"first_ts": "...", "last_ts": "..."}
  },
  "boundary_actions": {
    "head": [{"action_id": "...", "type": "mouse_left", ...}, /* 前 5 行原始动作 */],
    "tail": [/* 后 5 行原始动作 */]
  }
}
```

**约束**：
- MUST NOT 返回中段原始动作行（Agent 用 `list_desktop_actions` 翻页取深，避免首调 token 压爆）；
- `boundary_actions.head` / `.tail` 各 ≤ 5 行（合计 ≤ 10 行）；
- 当 `action_count <= 10` 时 head 含全部行、tail 为空（避免重复）；
- 大字段（`text_content` / `clipboard_text` / `uia_summary` 序列化超阈值）经 ContextManager 自动占位替换。

### `read_field_chunk(stable_locator: str, offset: int = 0, length: int = 1000)`

| mode | stable_locator 形式 |
|---|---|
| browser | `actions.<column>.<action_id>` / `network_requests.<column>.<request_id>` 等（既有） |
| desktop | `desktop_actions.<column>.<action_id>`（仅 `text_content` / `clipboard_text` / `uia_summary` 列触发占位） |

输出与浏览器 mode 同形：`{"chunk": "<text>", "offset": int, "total_length": int, "more_available": bool}`。

## 门卫不变量（SC-005 + CC-002）

| # | 不变量 | 守卫测试 |
|---|---|---|
| 1 | 浏览器 mode 5 通用工具 canonical JSON baseline 字节级 byte-equal | `test_desktop_browser_path_byte_equal.py` |
| 2 | `network_requests.filtered = FALSE` 视图保留 | 既有过滤测试 |
| 3 | `recording_data_tools.py` 不直接 import sqlglot | 既有 guard test |
| 4 | 浏览器 mode allowlist 完全屏蔽桌面 2 张表 | `test_desktop_tools_mode_dispatch.py` 反向断言 |
| 5 | 桌面 mode allowlist 完全屏蔽浏览器 5 张表 | 同上 |
| 6 | mode 内两表 JOIN 允许（如 `desktop_recordings × desktop_actions`） | 同上 |
| 7 | 跨 mode 表访问统一返回 `table_not_in_mode` 错误 | 同上 |

## 测试切面

- **链路冒烟**：桌面 mode 创建工具 → 调 `read_recording(recording_id)` → 返回 `desktop_recordings` 行 + 聚合摘要；
- **门卫**：浏览器 mode 调 `query_data("SELECT * FROM desktop_actions")` → 返回 `table_not_in_mode` 错误；反向同；
- **长字段定位**：桌面 mode 调 `read_field_chunk("desktop_actions.<column>.<action_id>")` → 返回对应长字段 chunk；浏览器 mode 使用同 locator → 拒绝；
- **canonical baseline**：浏览器 mode 全 5 工具输出 vs 改造前 fixture 字节级 byte-equal。
