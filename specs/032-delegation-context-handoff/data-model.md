# Data Model: 委派上下文交接

**Date**: 2026-07-14 | **Feature**: 032-delegation-context-handoff

本 feature **0 新表 / 0 migration / 0 新列**。实体均为内存态或复用既有持久化字段。

## 实体

### LlmMessagesSnapshot(内存态,新)

主助理本轮实际送入 LLM 的消息数组按顺序复制出的不可变解析投影,经 contextvar 在工具执行期间可见。投影只保留 resolver 所需的 `role` / `content`,不共享源数组或元素的可变引用。

| 字段 | 类型 | 说明 |
|---|---|---|
| messages | `tuple[SnapshotMessage, ...]` | 与本轮 `assemble_context()` 完整数组等长、同顺序的不可变 tuple |
| `SnapshotMessage.role` | `str` | 捕获时复制的角色值 |
| `SnapshotMessage.content` | `str \| None` | 捕获时复制的消息正文;字符串本身不可变 |

- **生命周期**: 设置于 AgentLoop LLM 路径的工具批次执行前,批次结束即清除;恢复路径与 initial_tool_calls 路径不设置。
- **不变量**: `tuple` + frozen `SnapshotMessage` 保证快照结构不可变;源 messages 在工具执行期间即使被其他代码误改,解析仍使用捕获时的 role/content。投影的位置和值对应模型所见完整数组,禁止重新 assemble 替代。

### ContextMessageIndexes(工具参数,新)

| 字段 | 类型 | 校验 |
|---|---|---|
| context_message_indexes | `list[int]`(可选) | 每项为 1-based 正整数;≤ 快照长度;不得重复;不得指向 system 消息;提供时不得为空;非法即整体拒绝 |

- **生命周期**: 只在委派工具执行瞬间按快照解析,解析后不进入下游 Task 语义。AgentLoop 仍按既有 function-call 配对/审计机制把原始 tool-call 参数保存在 `messages.tool_calls`,并可能在活动投影里显示数字下标;这保证崩溃恢复时保留原调用且因快照缺失而 fail-closed。`assistant_tasks.description` 只保存展开全文,不保存下标;普通日志只记录引用数量,不记录下标对应内容。

### ExpandedContextBlock(派生文本,新)

按下标取出的消息原文组成的标记文本块,追加进 `execution_context`。

- **格式**(确定性拼装):

```text
【主对话相关原文】
--- 消息 #<idx>（<role>）---
<content 原文>
--- 消息 #<idx>（<role>）---
<content 原文>
```

- **约束**: system 角色禁止展开(能力目录授权隔离);其余 content 逐字保真(FR-004);总长度(含标记行)≤ `agent_tools.delegation.context_expansion_max_chars`(默认 30000),超限整体报错不截断;tool 角色消息 content 为 envelope 文本时原样携带。handler 会在展示 header 后附一个不可见内部 provenance 标记并随 Task 描述持久化;adapter/checkpoint 中间层不得消费该标记,仅最终执行体输入格式化边界移除。普通用户文本即使包含同名展示 header,没有 provenance 也只按旧 execution_context 规则处理。

## 复用的既有持久化字段

| 字段 | 表 | 用法 |
|---|---|---|
| `description` | `assistant_tasks`(v15 既有) | 异步路径:handler 展开合并后的 `execution_context` 经 `_dispatch_task_via_unified_model(context=...)` → `dispatcher.create_child_task(description=...)` 原样落库;执行时由 `TaskExecutorAdapter` 回填。落库内容为**展开后全文**,不含未解析下标 |

## 配置

| 键 | 默认 | 说明 |
|---|---|---|
| `agent_tools.delegation.context_expansion_max_chars` | 30000 | 展开块总字符上限;经 `get_unified_config()` 读取;非 secret |

## 状态转换

无新状态机。委派失败(fail-closed)走既有 tool result 错误通道,不进入 `assistant_run_failures` 或 task 状态机。

## 数据流

```text
主助理 LLM 响应(tool_call: delegate_*, context_message_indexes=[i, j])
  → AgentLoop: use_llm_messages_snapshot(本轮 messages) 内执行 handler
  → handler: resolve(indexes)
      ├─ 非法/无快照/超限 → error JSON(整体失败)→ tool result → 主助理重填
      └─ 合法 → ExpandedContextBlock 追加进 execution_context
            ├─ simple(同步)→ run_*_via_delegated_executor
            │     → _format_delegated_task_input(task, execution_context)
            │     → 子会话首条 user 消息含原文
            └─ complex(异步)→ _dispatch_task_via_unified_model(context=execution_context)
                  → task.description 落库(全文)
                  → scheduler → TaskExecutorAdapter(description → execution_context)
                  → 执行体首条 user 消息含原文(快照早已消亡,不依赖)
```
