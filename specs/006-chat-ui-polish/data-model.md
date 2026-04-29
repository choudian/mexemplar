# Data Model: 聊天界面体验完善（Chat UI Polish）

## Existing Entity: Message

来源：`src/data/models_sqlite.py` 的 `Message` ORM。

| Field | Type | Usage in this feature |
|-------|------|-----------------------|
| `message_id` | string | 只读标识；UI 不展示 |
| `session_id` | string | 查询当前会话展示历史 |
| `sequence` | integer | 展示时间线排序和 keyset pagination 边界 |
| `role` | string | 仅 `user` / `assistant` 可作为普通聊天消息展示 |
| `content` | text nullable | 展示文本；空内容不渲染为普通聊天气泡 |
| `message_type` | string | `compressed` / summary 类消息必须排除 |
| `tool_call_id` | string nullable | 工具结果标识；存在于 tool result 时不展示 |
| `tool_name` | string nullable | 工具结果辅助字段；不展示 |
| `tool_calls` | text nullable | assistant 工具调用元数据；工具调用消息不作为普通聊天记录展示 |
| `compressed_range` | string nullable | 压缩摘要范围；不展示 |
| `is_archived` | bool | 仅内部状态；展示接口可以读取 archived 原始用户/助手消息，但不得暴露给 UI |
| `created_at` | datetime | 可用于稳定测试或未来时间显示；本 feature 不新增可见时间标签 |

Validation rules:

- `role="summary"` 或 `message_type="compressed"` MUST NOT 出现在普通聊天时间线。
- `role="tool"` MUST NOT 出现在普通聊天时间线。
- `role="assistant"` 且 `content` 为空、仅包含 `tool_calls` 的消息 MUST NOT 渲染为普通聊天气泡。
- `role in ("user", "assistant")` 且 `content` 非空的消息 MAY 进入展示时间线，不受 `is_archived` 影响。
- 展示顺序 MUST 按 `sequence` 升序。

## New DTO: DisplayChatMessage

业务层返回给 UI 的展示用消息，不持久化。

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `sequence` | int | yes | 用于排序和下一次 `before_sequence` |
| `role` | literal `user` / `assistant` | yes | 决定气泡方向和 Markdown 是否启用 |
| `content` | str | yes | 已过滤为空内容；用户消息按纯文本，助手消息可 Markdown |
| `created_at` | datetime or None | no | 当前不展示，但可用于测试/后续排序断言 |

Relationships:

- 一条 `DisplayChatMessage` 映射自一条 SQLite `Message`。
- 不包含 `is_archived`、`message_type`、`tool_calls` 等内部状态，防止 UI 误展示压缩概念。

## New DTO: ChatHistoryPage

业务层返回给 UI 的分页结果，不持久化。

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `messages` | list[DisplayChatMessage] | yes | 始终按 `sequence` 升序返回 |
| `has_more_before` | bool | yes | 是否还能继续向上加载更早展示消息 |
| `next_before_sequence` | int or None | no | 下一页使用的边界；通常为当前页第一条 `sequence` |

Validation rules:

- 初始读取不传 `before_sequence`，默认 `limit=10`。
- 向上滚动时传入当前已展示最早消息的 `sequence`。
- Repository 查询可多取 `limit + 1` 条判断 `has_more_before`，返回给 UI 时裁剪为 `limit`。

## UI State: AutoApproveToggleVisibility

不持久化，属于 `ChatWidget` 内部视图状态。

| State | Toggle visible |
|-------|----------------|
| `session_list` / 欢迎列表 | false |
| `new_chat_empty` / 新对话起始态 | false |
| `conversation_started` / 当前对话已启动 Agent | true |
| `conversation_cleared` / 清空后会话 | false |

State transitions:

- `on_new_chat()` -> `new_chat_empty`，隐藏 Toggle，并继续触发既有 new chat reset。
- `_do_send()` 成功发出第一条用户消息并创建/使用 session -> `conversation_started`，显示 Toggle。
- `_switch_to_session(session_id)` 且展示消息非空 -> `conversation_started`，显示 Toggle。
- 回到会话列表或欢迎页 -> 隐藏 Toggle。

## UI View: MarkdownMessageView

不持久化，属于聊天气泡内部渲染 widget/helper。

Fields / properties:

- `role`: `assistant` 时启用 Markdown；`user` 时禁用。
- `raw_text`: 原始消息内容。
- `safe_markdown`: raw HTML/script 降级后的 Markdown 文本。
- `navigation_enabled`: 固定 false。
- `allowed_image_schemes`: `http`, `https`。

Validation rules:

- 用户消息必须走纯文本，不能 Markdown 解析。
- 助手消息中的链接可呈现链接样式，但点击不得打开浏览器或外部目标。
- 非远程图片、本地文件、脚本协议和裸 HTML 图片必须降级。
- 流式半截 Markdown 在最终收敛前不得造成异常或大段重排。
