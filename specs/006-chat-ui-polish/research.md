# Research: 聊天界面体验完善（Chat UI Polish）

## Decision: 使用 Qt/PyQt 内建 Markdown 渲染能力

**Rationale**: 当前项目主 UI 栈已是 PyQt6，`pyproject.toml` 未包含 Markdown 解析库。本地 `.venv` 验证 Qt/PyQt 为 6.11.0，`QTextDocument.setMarkdown()` 存在且默认参数为 `QTextDocument.MarkdownDialectGitHub`，能覆盖标题、列表、代码块、引用和 pipe table 等基础语法。优先复用 Qt 能力可避免新增依赖和额外 HTML sanitizer 组合。

**Alternatives considered**:

- 新增 Python Markdown / markdown-it-py / mistune：可控性更高，但需要新增依赖和额外 HTML 清洗链路，超出本 feature 的最小边界。
- 手写 Markdown 解析：表格、代码块、流式半截语法和安全降级容易出错，不适合当前范围。
- 继续 QLabel PlainText：无法满足 spec 的 Markdown 富文本验收。

## Decision: Markdown 渲染前进行安全降级，链接/图片不触发导航

**Rationale**: Qt Markdown 能把 Markdown 转成文档结构，但 raw HTML、链接和图片仍需要按 spec 收紧。渲染前对 `<...>` raw HTML / script 片段做转义或纯文本降级；渲染 widget 保持只读和可选择文本，关闭 `openExternalLinks`，`anchorClicked` 不执行导航。图片资源只允许 `http(s)`，本地文件、脚本协议和裸 HTML 图片标签降级为 alt 文本或纯文本。

**Alternatives considered**:

- 允许 QTextBrowser 默认链接行为：会打开浏览器或外部目标，违反 FR-006/SC-001。
- 完全禁用图片：安全但不满足“允许远程图片渲染”的 clarified 方向。
- 直接渲染 raw HTML：风险高，违反安全约束。

## Decision: 历史回看使用展示专用分页接口，不复用 LLM 上下文接口

**Rationale**: `ContextManager.assemble_context()` 和 `MessageRepository.get_context()` 是 LLM 上下文路径，会过滤 `is_archived=True`，并保留压缩摘要给模型使用。用户界面需要的是展示时间线：用户消息和助手对话回复按 `sequence` 合并，排除 tool、tool result、summary/compressed。新增 `ChatService` 展示接口可保持 UI 不碰 Repository，同时不改变压缩和 Agent 上下文契约。

**Alternatives considered**:

- 让 UI 直接调用 `MessageRepository.get_all()`：违反 UI 不直接触碰数据层。
- 修改 `get_context()` 返回 archived：会污染 LLM 上下文并破坏压缩契约。
- 把旧消息做独立归档区：违背 clarified spec 的透明时间线要求。

## Decision: 历史分页以 `before_sequence` 向上加载，初始窗口为最新 10 条展示消息

**Rationale**: SQLite `messages(session_id, sequence)` 已有索引，按 `sequence < before_sequence` 倒序取 `limit` 条再升序返回，可以稳定支持 1000+ 旧消息。UI 初始渲染最新 10 条并滚动到底部；用户滚动到顶部时 prepend 更早一页并保持滚动视口位置，避免全量创建 widget 阻塞输入。

**Alternatives considered**:

- 打开会话时一次性加载全部消息：简单但不满足 SC-007。
- 使用 offset 分页：归档/插入摘要消息会让 offset 更脆弱；基于 sequence 的 keyset pagination 更稳定。
- 新增缓存表：当前数据量和查询形态不需要 schema 扩展。

## Decision: “免确认” Toggle 只新增可见性状态，不改变确认协议

**Rationale**: 004-auth-toast 已定义 Toggle 与浮层“全部允许”的同步、复位和 pending 收敛语义。本 feature 只解决欢迎页/新对话起始态误导展示，因此应在 `ChatWidget` 维护“当前视图是否已启动 Agent 会话”的可见性条件，并继续把开关状态同步交给现有 `set_auto_approve_enabled()` / `auto_approve_toggled` 信号。

**Alternatives considered**:

- 把 Toggle 做成全局设置：违反 004-auth-toast 和 docs/PROJECT_CONSTRAINTS 中“会话级内存状态”的边界。
- 新增配置项控制显示：spec 已明确默认启用且不新增配置。
- 修改 `AgentHandlerMixin` 确认协议：风险大且不属于 UI 可见性问题。
