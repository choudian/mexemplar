# Contract: Long-Paste Composer Interaction

## Covered Surfaces

- Assistant 消息输入框：`frontend/src/screens/assistant/MessageComposer.tsx`
- Skill Teaching 聊天输入框：`frontend/src/screens/teaching/shared.tsx` 的 `ChatComposer`

两处必须使用同一 qualifying/preview/send 语义；视觉样式可以按宿主容器适配。

## Qualifying Paste

仅对 clipboard 提供的文本 paste 处理。设粘贴前草稿为 `draft`，选区为 `[start, end)`，文本为 `pasteText`：

```text
nextDraft = draft.slice(0, start) + pasteText + draft.slice(end)
qualifies = lineCount(nextDraft) > 6 OR nextDraft.length > 1200
```

- 若 `qualifies`，组件阻止默认插入、提交精确 `nextDraft` 并进入 collapsed state。
- 若不 qualifying，普通 textarea 行为保留。
- 图片、文件或无文本 clipboard 不由该功能转换为文字卡片。
- `\r\n`、`\n`、空行、首尾空格和已有草稿字符必须原样保存在发送内容中。

## UI States

| State | Required UI | Required actions |
|-------|-------------|------------------|
| `normal` | 普通 textarea | 输入、paste、发送 |
| `collapsed` | 可识别的内容预览、行数/字符数、已省略指示 | `展开全部`、`清除内容`、`发送` |
| `expanded` | 完整 textarea（可内部滚动）与长内容标识 | `收起预览`、`清除内容`、`发送` |

手动逐行输入或 `.fill()` 更新文本不得自行触发 `collapsed`，本 feature 不提供从普通手动输入草稿主动折叠为 preview 的入口。用户可在已由 paste qualified 的 expanded 状态再次收起。

## Send And Reset

- 发送请求的 `content` 必须等于当前完整 `draft`，从不使用 preview。
- 既有发送 accepted 后，draft 与折叠临时状态一起复位。
- 发送失败且现有业务流程保留 draft 时，完整文本和当前可恢复交互状态不得丢失。
- 切换到另一会话/新的 Teaching 对话时，不携带上一草稿的 collapsed 状态。

## Accessibility

- Preview 需有可理解名称，例如“长文本预览，完整内容已保留”。
- 展开/收起按钮通过可见文本或 `aria-label` 暴露当前动作。
- 折叠态仍提供可键盘聚焦的发送和清空操作。
- 内容状态改变可用 `aria-expanded` / `aria-controls` 表达；不得要求鼠标悬停才能恢复全文。

## Acceptance Tests

| ID | Scenario |
|----|----------|
| `CP-001` | Assistant 空草稿粘贴 7 行后折叠，发送内容逐字一致 |
| `CP-002` | Teaching 同样的折叠/展开/清空/发送行为 |
| `CP-003` | 中间选区 paste 后 before/after 文本完整保留 |
| `CP-004` | 超过 1200 字符的单行 paste 折叠；混合换行不被规范化 |
| `CP-005` | 手动输入超过阈值仍保持普通 textarea |
| `CP-006` | 键盘操作可展开、收起、清空并发送 |
