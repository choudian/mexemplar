# Contract: Chat UI Polish

本合同定义本 feature 内部 UI/业务边界。它不是外部网络 API。

## ChatService: 展示历史分页

### `get_display_messages(session_id: str, limit: int = 10, before_sequence: int | None = None) -> ChatHistoryPage`

Purpose:

- 给 `ChatWidget` 读取用户可见聊天历史。
- 包含压缩前 archived 的用户消息和助手对话回复。
- 排除 tool、tool result、summary/compressed 和空内容消息。

Preconditions:

- `session_id` 是现有 assistant 会话 ID。
- `limit` 必须为正数；默认和首屏验收值为 10。
- `before_sequence=None` 表示读取最新一页；否则读取 `sequence < before_sequence` 的更早展示消息。

Postconditions:

- `messages` 按 `sequence` 升序返回。
- `messages` 中只包含 `role == "user"` 或 `role == "assistant"` 且 `content` 非空的展示消息。
- 返回对象不暴露 `is_archived`、`compressed_range` 或 `message_type` 给 UI。
- 不创建、不更新、不删除任何 SQLite 行。

Failure behavior:

- 查询失败时由 `ChatWidget` 记录日志并回退到欢迎/空状态，不展示内部异常给用户。
- 不改变 `ContextManager`、压缩摘要或 Agent 当前上下文。

## ChatWidget: 历史加载

### Initial open

Given 用户打开一个已有会话：

- UI 调用 `ChatService.get_display_messages(session_id, limit=10, before_sequence=None)`。
- 若返回消息非空，按升序渲染并滚动到底部。
- 若返回为空，展示欢迎状态并隐藏 Toggle。

### Scroll up

Given 当前聊天框顶部附近触发向上加载：

- UI 使用当前最早展示消息的 `sequence` 作为 `before_sequence`。
- UI 将新页 prepend 到现有消息上方。
- UI 保持用户视口位置，不能跳到底部。
- UI 不显示“归档”“压缩”或分隔条。

## ChatWidget: Markdown 渲染

### Assistant message

Given `role == "assistant"` 且 `content` 非空：

- 渲染层使用安全降级后的 Markdown 文本构建只读富文本。
- 支持标题、列表、加粗/斜体、行内代码、代码块、引用、分隔线、链接样式文本、远程图片和 GitHub 风格 pipe table。
- 链接点击、图片点击、外部导航、本地文件访问和脚本执行必须为 no-op。

### User message

Given `role == "user"`：

- 内容必须以纯文本展示。
- Markdown 记号不得被解析。

## ChatWidget: “免确认” Toggle 可见性

Visibility rules:

- 欢迎页：hidden。
- 会话列表页：hidden。
- 新对话起始态：hidden。
- 用户发送第一条消息并启动 assistant session 后：visible。
- 切换到已有有消息会话：visible。
- 新对话或清空当前会话：hidden，并继续执行既有 new-chat reset。

Behavior rules:

- 可见性变化不得发出额外 `auto_approve_toggled` 用户切换信号。
- 现有 `set_auto_approve_enabled()` 仍只同步 checked/text/property。
- 不修改 `AgentHandlerMixin` 中 pending confirmation 的 settlement、timeout 和 source 语义。
