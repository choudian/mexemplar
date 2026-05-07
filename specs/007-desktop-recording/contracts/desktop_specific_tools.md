# Contract: 3 桌面专属工具

> `list_desktop_actions` / `analyze_desktop_action` / `read_action_clip` 三工具的输入/输出契约。

## 工厂入口

```python
# src/business/agents/tools/desktop_tools.py

def create_desktop_specific_tools(recording_id: str) -> list[ToolDefinition]:
    """构造 3 桌面专属工具。仅在 recording_mode='desktop' 且 vision_model 配置齐全时被 Orchestrator 拼接到 PM/Programmer/Trial 工具集。"""
    return [
        _build_list_desktop_actions(recording_id),
        _build_analyze_desktop_action(recording_id),    # 仅 vision_model 配置时注入；未配置自然降级（CC-005）
        _build_read_action_clip(recording_id),
    ]
```

**注入条件**（FR-014 + FR-015 + FR-026a）：
- `recording_mode='desktop'` → 注入 3 工具到 PM / Programmer / Trial（取代 `analyze_image`）；
- `recording_mode='browser'` → **不**注入 3 工具，保留 `analyze_image`（反向门卫）；
- `recording.desktop.vision_model` 未配置 → 仅 `analyze_desktop_action` 不注入（其余两工具仍可用，自然降级）。

---

## 1. `list_desktop_actions`

### 输入

```python
list_desktop_actions(
    recording_id: str,
    time_range: tuple[str, str] | None = None,    # ISO 8601 格式 [start, end]，None = 不限
    action_types: list[str] | None = None,        # 元素从 7 枚举集取，None = 不过滤
    offset: int = 0,
    limit: int = 100,                              # 上限 500
) -> str  # JSON 序列化字符串
```

### 输出

成功：

```json
{
  "actions": [
    {
      "action_id": "...",
      "type": "mouse_left",
      "coord_x": 320,
      "coord_y": 480,
      "monitor_index": 0,
      "window_title": "记事本",
      "uia_summary": {"control_type": "Edit", "name": "文档"},
      "clipboard_text": null,
      "clipboard_image_path": null,
      "text_content": null,
      "timestamp": "2026-05-02T14:23:01.234Z",
      "duration_ms": null,
      "frame_count": 45,
      "has_clip": true
    }
  ],
  "total": 27,
  "offset": 0,
  "limit": 100,
  "has_more": false
}
```

错误：

```json
{"error": "invalid_action_type", "value": "<x>"}
```

### 错误码

- `invalid_action_type`：`action_types` 元素不在 7 枚举集内（大小写敏感）；MUST NOT 静默忽略；
- `recording_not_found`：`recording_id` 不存在；
- `limit_exceeded`：`limit > 500`。

### 约束

- `limit` 上限 500；
- `action_types` 枚举集 `{"mouse_left", "mouse_right", "mouse_middle", "wheel", "drag", "typing", "hotkey"}`，大小写敏感、与 `desktop_actions.type` 列值完全一致（FR-013）；
- 大字段经 ContextManager 自动占位替换（与 `read_recording` 同处理）。

---

## 2. `analyze_desktop_action`

### 输入

```python
analyze_desktop_action(
    action_ids: list[str],    # Phase 1 上限 2 个
    question: str,
) -> str  # 始终是纯字符串
```

### 输出

成功（多 action）：

```text
Action <id1>：用户在记事本输入框输入了 "hello"，输入框获得焦点后字符逐个出现，最后光标停留在 "hello" 之后

Action <id2>：用户点击了文件菜单，弹出包含"新建/打开/保存/另存为"的下拉列表
```

部分失败：

```text
Action <id1>：[error: vision_timeout]

Action <id2>：用户按了 Ctrl+S，弹出"另存为"对话框
```

全部失败：

```text
Action <id1>：[error: vision_unauthorized]

Action <id2>：[error: vision_unauthorized]
```

### 错误码（reason_code）

- `vision_timeout`：vision LLM 调用超时；
- `vision_unauthorized`：401 / 403；
- `vision_failed`：其他失败（网络 / 5xx / parse 异常）；
- `[error: <reason_code>]` 段与成功段拼接为同一字符串返回（FR-013 + spec round 1 第 1 题 round 4）；
- **始终返回纯字符串**：MUST NOT 抛异常、MUST NOT 返回 dict 错误对象。

### 多模态消息组装顺序（FR-013 + spec round 8 第 1 题）

工具内部按以下结构组装上传给 vision LLM 的多模态消息：

```text
┌─ Action <id1> ─────────────────────────────────────┐
│ [若 type='typing']                                 │
│ Action <id1> 用户输入文本: hello                   │
│                                                    │
│ [若 clipboard_image_path 非空]                     │
│ Action <id1> 剪贴板图（动作 hook 触发瞬间最新一张）│
│ <剪贴板图>                                         │
│                                                    │
│ Action <id1> 帧 1/45 (T=-1000ms 相对动作开始)      │
│ <帧 1>                                             │
│ Action <id1> 帧 2/45 (T=-933ms 相对动作开始)       │
│ <帧 2>                                             │
│ ...                                                │
│ Action <id1> 帧 45/45 (T=2000ms 相对动作开始)      │
│ <帧 45>                                            │
└────────────────────────────────────────────────────┘
--- Action <id1> 帧序列结束 / Action <id2> 开始 ---
┌─ Action <id2> ─────────────────────────────────────┐
│ ... (同上结构) ...                                 │
└────────────────────────────────────────────────────┘

<question 文本>
```

### 缩放与上传

- 单帧 PNG 上传前等比缩小到长边 1280px（**仅缩小不放大**，原长边 ≤ 1280 时保持原尺寸；语义对齐 `PIL.Image.thumbnail`，spec round 8 第 2 题）；
- 落盘文件本身保持原生分辨率不变（FR-005）；
- 上限：`action_ids` ≤ 2 个；
- Phase 1 不设单次会话/单 recording 累计调用上限（FR-013 + spec round 2 第 3 题），仅 INFO 日志事后审计。

### Provider routing

- provider 沿用 `analyze_image` 当前 provider 配置（FR-026a + spec round 7 第 2 题）；
- model 用 `recording.desktop.vision_model`（独立于 `analyze_image` model）；
- API key 沿用 `analyze_image` 同套 keyring entry。

### INFO 日志格式

```text
[INFO] analyze_desktop_action recording_id=<id> action_ids=<list> frames_uploaded=<n> session_total_calls=<n> session_total_frames=<n>
```

---

## 3. `read_action_clip`

### 输入

```python
read_action_clip(action_id: str) -> str  # JSON 序列化字符串
```

### 输出

成功：

```json
{
  "clip_path": "data/recordings/<recording_id>/clips/<action_id>.mp4",
  "duration_ms": 3000,
  "fps": 15,
  "resolution": [1920, 1080]
}
```

失败：

```json
{"error": "clip_unavailable", "action_id": "<id>"}
```

### 约束

- 仅返回 mp4 路径与元数据，**不进 Agent 主上下文**（视频不上传 vision LLM，仅 Phase 2 UI 播放器使用）；
- `has_clip=FALSE` 时返回 `clip_unavailable` 错误（FR-013）；
- Agent 应将 `clip_path` 视为不透明引用（不直接读 mp4 文件内容）。

---

## 测试切面

- **`list_desktop_actions`**：枚举校验拒绝 `["MouseLeft"]`（大小写错），time_range / offset / limit 翻页正确；
- **`analyze_desktop_action`**：多模态组装顺序断言（mock vision LLM 拦截上传 payload，断言文本前缀 / 剪贴板图前置 / 帧顺序 / question 末尾）；缩放仅缩小语义（< 1280 不拉伸）；失败段拼接 `[error: <reason_code>]`；2 个 action_ids 上限断言；
- **`read_action_clip`**：`has_clip=FALSE` 时错误对象；正常时 mp4 路径与 duration_ms / fps；
- **`vision_model` 未配置 → `analyze_desktop_action` 不注入**：`create_desktop_specific_tools` 返回列表只含 2 个工具（`list_desktop_actions` + `read_action_clip`）。
