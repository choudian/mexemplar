# Quickstart: 聊天界面体验完善（Chat UI Polish）

## Prerequisites

- 在仓库根目录运行。
- Windows/PyQt6 环境可用；若 `uv run` 因本机缓存权限失败，可使用 `.venv\Scripts\python.exe` 替代。

## Validation flow

1. 运行 Markdown UI 测试。

   ```powershell
   uv run python -m pytest tests/ui/test_chat_widget_markdown.py -q
   ```

2. 运行历史分页 UI/业务测试。

   ```powershell
   uv run python -m pytest tests/ui/test_chat_widget_history.py tests/data/test_message_repository.py -q
   ```

3. 运行 Toggle 回归测试，确认隐藏逻辑不破坏 004-auth-toast 同步语义。

   ```powershell
   uv run python -m pytest tests/ui/test_chat_widget_auth_toggle.py tests/ui/test_agent_handler_mixin.py -q
   ```

4. 运行 assistant 会话接线烟测。

   ```powershell
   uv run python -m pytest tests/integration/test_assistant_new_session.py -q
   ```

5. 运行语法和 diff 检查。

   ```powershell
   uv run python -m py_compile src/ui/widgets/chat_widget.py src/business/services/chat_service.py src/data/repos/message_repository.py
   git diff --check
   ```

## Manual acceptance

1. 启动 GUI，停留欢迎页，确认顶栏没有“免确认” Toggle。
2. 点击新对话但不发送消息，确认 Toggle 仍隐藏。
3. 发送第一条消息，确认 Toggle 出现，并且开启/关闭仍能同步到高危确认浮层。
4. 让助手回复包含标题、列表、代码块、加粗、链接、远程图片和 pipe table，确认助手消息富文本展示，用户消息仍纯文本。
5. 准备一个包含 archived 旧用户/助手消息、tool 消息和 compressed summary 的会话，打开后确认首屏只展示最新 10 条用户/助手消息。
6. 向上滚动，确认更早用户/助手消息逐页出现，且没有“归档”“压缩”标签、分隔条、tool 消息或 summary 消息。

## Fallback commands

若 `uv run` 失败：

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ui/test_chat_widget_markdown.py -q
.\.venv\Scripts\python.exe -m pytest tests/ui/test_chat_widget_history.py tests/data/test_message_repository.py -q
.\.venv\Scripts\python.exe -m py_compile src/ui/widgets/chat_widget.py src/business/services/chat_service.py src/data/repos/message_repository.py
```
