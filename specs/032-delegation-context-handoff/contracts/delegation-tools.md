# Contract: 委派工具参数与错误语义

**Feature**: 032-delegation-context-handoff | **Date**: 2026-07-14

本 feature 无新外部 API/UI 事件;契约面是主助理可见的三个工具 schema 与其错误语义。

## delegate_to_subagent(修改)

新增可选参数:

```json
"context_message_indexes": {
  "type": "array",
  "items": {"type": "integer"},
  "description": "要携带给子代理的历史消息下标(1-based,按你本轮收到的消息顺序计数);不得引用 system 消息(可能含当前 Agent 专属能力目录)。子代理在全新会话启动,看不到任何对话历史;凡任务引用了对话中已产生的内容(方案、清单、代码、结论),必须用本参数把内容所在消息带上,禁止只写『之前讨论的方案』这类指代。系统会把被引用消息的原文逐字附给子代理。"
}
```

`task_description` / `execution_context` 的 description 追加同向约束(子代理无对话历史可见性;引用已产生内容必须经 context_message_indexes 携带)。

## delegate_to_specialist(修改)

新增可选参数:`execution_context`(string,语义与 delegate_to_subagent 对齐)、`context_message_indexes`(同上)。

`required` 保持 `["specialist_name", "task"]` 不变。

## build_task_graph(仅文案)

node `description` 字段 description 加强为:执行体看不到对话历史,本字段必须自包含——所有执行所需的内容(含对话中已产生的方案/清单/代码原文)必须写入,禁止指代。

## 错误语义(fail-closed,整体失败)

handler 返回标准 error JSON(经既有 `error_json` / tool result 通道),`success=false`,message 必须包含具体原因与重填指引:

| 场景 | message 要点 |
|---|---|
| 指向 system 消息 | 说明 system 可能含当前 Agent 专属能力目录,要求只引用 user / assistant / tool 消息 |
| 下标非法(非正整数 / 越界 / 重复 / 解析出空集) | 指出非法值与合法范围(1..快照长度),要求重填 |
| 快照不可用(恢复路径 / initial_tool_calls 路径) | 说明本轮无可用消息快照,要求直接把所需内容写入 execution_context 或重新委派 |
| 展开总量超上限 | 给出上限值与实际值,要求缩小引用范围或改写要点进 execution_context |

约束:不部分展开、不静默丢弃、不截断;错误不改变会话/任务状态(无 task 落库、无子会话创建)。

## 成功语义

- 展开块追加于 `execution_context` 尾部,格式见 data-model.md;原文逐字保真。
- 未提供 `context_message_indexes`(或省略)时,不触发消息下标解析或自动展开;这部分行为
  与 031 及之前一致。
- 兼容性例外:032 同时修复异步 specialist 静默丢弃非兜底 `task.description` 的既有
  缺口,并把恢复 checkpoint 作为 `execution_context` 中的补充上下文传递。即使省略
  `context_message_indexes`,这两类 specialist 执行体输入也会按修复后的语义变化;
  description 为空/等于 title 且无 checkpoint 时仍保持原输入形态。
- 返回值结构不变(同步:结果 dict;复杂:durable accepted + taskId)。

## 隔离不变量

- system 消息不得展开给执行体,避免把父 Agent 的能力目录名称/描述泄漏给权限更窄的 Agent。
- 执行体工具集不新增任何父会话读取能力;既有 `load_reference` 的 message ID 路径对执行体校验当前会话归属并拒绝父会话消息,主助理保留既有跨会话记忆下钻;子会话与父会话隔离边界不变。
- 展开发生于委派工具执行瞬间;异步任务落库后的 `description` 为全文,任何执行/重试/恢复路径不得回头解析下标。
- 自动展开块以不可见内部 provenance 区别于用户普通文本中的同名展示 header;provenance 可随 Task description 持久化,adapter/checkpoint 中间层必须保留,且仅由最终执行体格式化边界移除。
- AgentLoop 为 function-call 配对/审计保留原始 tool-call 参数是既有消息历史语义,不等于把下标持久化进 Task;崩溃恢复时原快照不可重建,必须按“快照不可用”整体拒绝。
