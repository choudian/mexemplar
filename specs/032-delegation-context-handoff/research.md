# Research: 委派上下文交接

**Date**: 2026-07-14 | **Feature**: 032-delegation-context-handoff

Technical Context 无 NEEDS CLARIFICATION;以下记录设计决策、依据与被否备选。代码事实均已在计划前实读源码核实(文件:行号以当前分支为准)。

## D1. 上下文交接机制:下标引用 + 系统就地展开

- **Decision**: 主助理在委派工具里用 `context_message_indexes`(1-based 下标数组)引用其本轮可见消息;后端在委派工具执行瞬间按本轮 assembled messages 快照解析并逐字展开,注入执行体初始输入。
- **Rationale**:
  - 对比"主助理抄全文进 execution_context"(纯 prompt 约束):输出 token 最贵,LLM 抄长文会缩写/漏段/改措辞;系统拷贝逐字精确且零输出开销。
  - 对比"自动携带近 N 轮历史":无脑携带无关轮次,token 不可控;下标引用只带被点名内容。
  - 对比"lazy 引用(子代理拿引用自己加载)":内容被引用即几乎必用,lazy 多付一整个 LLM 往返,且需给执行体开父会话读取口子(违反隔离边界)。用户在设计讨论中明确否决 lazy。
- **Alternatives considered**: 消息序号渲染(`[#seq]` 前缀)+ 按序号查库——需改上下文渲染管线、加 Repository 区间接口,且压缩边界序号语义不唯一(摘要复用 start_seq);短距离场景(本 feature 主场景)下标计数已够,列为后续可选加固,V1 不做。

## D2. 快照通道:contextvar,仅 LLM 响应路径设置

- **Decision**: 新模块 `src/business/agents/delegation_context.py` 提供 `use_llm_messages_snapshot(messages)`(context manager)与解析入口;`AgentLoop.run()` 只在 LLM 路径(`agent_loop.py:1322` `messages = ctx.assemble_context()` 之后、`agent_loop.py:1359` `_execute_tool_batch` 周围)设置快照。
- **Rationale**:
  - 项目已有同款先例:`use_tool_runtime`(`agent_loop.py:389-398`)以 contextvar 给内置工具注入 runtime,无需改 handler 签名或 dispatch_callback 链。
  - 下标是**位置语义**,必须对着模型产生 tool call 时看到的那份数组解析;重新调 `ctx.assemble_context()` 可能触发压缩导致位置漂移→静默错位,绝对禁止。
  - 恢复路径(`agent_loop.py:1288-1297` pending tool calls,可能跨进程重启)与 `initial_tool_calls` 路径(`agent_loop.py:1298-1319`)原快照不可复现——不设快照,带下标委派 fail-closed,模型下一轮基于新上下文重填。
- **线程安全前提**: 委派工具 `is_concurrency_safe=False`(src/CLAUDE.md 既有硬规则"写入/执行/委派工具不得标记并发安全"),handler 在 caller thread 执行,contextvar 可见。并发 worker 线程只跑只读工具,不触 resolver。
- **Alternatives considered**: AgentLoop 实例属性(`self._last_messages`)——同一 orchestrator 可能被复用/嵌套,实例态跨会话污染风险;显式参数穿 dispatch_callback——签名改动波及 orchestrator/adapter 全链,收益为零。

## D3. 下标语义:1-based、按完整可见数组计数、禁止选择 system

- **Decision**: 下标按模型本轮收到的完整数组计数,system 消息仍占位置但不得被选择。例如第 1 条为 system 时,第一条可引用 user 消息通常是下标 2。后端先按同一数组定位,再对所选 role 做 fail-closed 授权校验。
- **Rationale**: 任何"先过滤再计数"都要求模型和后端各自实现同一过滤,两边漂移即错位;保留完整位置语义可避免错位。system prompt 可能含仅对父 Agent 授权的能力目录,若复制给权限更窄的执行体会泄漏隐藏能力名称/描述,因此定位后必须拒绝 system。
- **Alternatives considered**: 负下标(从末尾倒数)——两套计数并存反而增加模型出错面;仅正序 1-based,description 写清。

## D4. 展开合并点:委派 handler 内追加进 execution_context

- **Decision**: handler 解析成功后,将展开块(格式:`【主对话相关原文】\n--- 消息 #<idx>(<role>)---\n<原文>`)追加到 `execution_context` 尾部,再走既有链路。handler 在展示 header 后附不可见内部 provenance 标记;Task 持久化、adapter 与 checkpoint 拼接等中间层保留标记,仅最终执行体格式化边界识别“header + provenance”、移除标记并逐字保留该块,从而避免异步链路二次 `.strip()`;边界前普通上下文继续沿用旧 `.strip()`。用户普通文本里的同名 header 不触发保真分支。
- **Rationale**: 同步路径 `_format_delegated_task_input(task, execution_context)`(`orchestrator.py:1524-1539`)已把 execution_context 渲染为"补充上下文"段;异步路径 `_dispatch_task_via_unified_model(context=execution_context or task)`(`delegation_orchestrator.py:49-56`)→ dispatcher 落库 `task.description` → `TaskExecutorAdapter._run_ephemeral`(`task_executor_adapter.py:111-121`)把 `task.description` 回填为 execution_context。**合并进 execution_context 后,ephemeral 同步/异步两条链零改动**,落库即全文,下标不进入 Task 语义。
- **Alternatives considered**: 独立参数穿全链——改 orchestrator/dispatcher/adapter 五处签名 + task 表无对应列(要么新列要么拼接,最终还是拼接);在 `_format_delegated_task_input` 加第三参数——异步路径落库前就得展开,展开点仍在 handler,第三参数只是把拼接推迟,反而让同步/异步产生两种拼接实现。

## D5. 专员链路补齐(修复既有静默丢失缺口)

- **Decision**: `delegate_to_specialist` 工具加 `execution_context` + `context_message_indexes`;`DelegationOrchestrator.delegate_to_specialist`(`delegation_orchestrator.py:162-224`)与 `run_specialist_via_delegated_executor`(同文件 249-364)增加 `execution_context` 参数并传入 `_format_delegated_task_input(task, execution_context)`(当前 `delegation_orchestrator.py:351` 只传 task);`TaskExecutorAdapter._run_specialist`(`task_executor_adapter.py:123-150`)把 `task.description` 作为 execution_context 传下(当前只传 `task.title`,description 静默丢弃——实读确认的既有缺口)。
- **Rationale**: 专员交接面当前比子代理更窄(无 execution_context 字段);异步专员任务的 description 丢失意味着即使落库了全文也送不到执行体——不修则本 feature 对异步专员路径无效。统一派发在 context 为空时用 title 兜底 description,adapter 必须识别该兜底并保持旧输入只出现一次。
- **Alternatives considered**: 仅加工具字段不修 adapter——异步专员路径静默失效,违反 spec FR-005/SC-003。

## D6. fail-closed 与上限

- **Decision**: 四类失败整体报错(标准 error JSON,含原因与重填指引):(a) 指向 system 消息;(b) 下标非法——非正整数、越界、重复;(c) 快照不可用(恢复/initial 路径);(d) 展开总量超 `agent_tools.delegation.context_expansion_max_chars`(默认 30000 字符)。错误经既有 tool result 通道回主助理,下一轮重填。
- **Rationale**: 部分展开或静默丢弃会让执行体拿到"看似完整实则缺页"的上下文,比不带更危险(spec FR-006);30000 字符 ≈ 常见方案/清单体量的数倍,同时防住"引用整段超长工具输出"把执行体上下文撑爆。
- **Alternatives considered**: 超限自动截断——违反 FR-004 逐字保真;截断点落在内容中间产生误导性残句。

## D7. 配置键

- **Decision**: `agent_tools.delegation.context_expansion_max_chars`,经 `get_unified_config()` 读取,代码内给默认值 30000,`config.json` 模板同步补默认值;非 secret,无脱敏需求。
- **Rationale**: 归入既有 `agent_tools.*` 命名空间(021 先例 `agent_tools.discovery.*`);constitution III 要求新配置项同步默认值与模板。

## D8. 约束写工具 description,不改 system prompt

- **Decision**: 硬性填参要求写进 `delegate_to_subagent` / `delegate_to_specialist` 的 schema description(工具级 + 字段级);`build_task_graph` node `description` 字段(`assistant_tools.py:1456` 附近)加强为"自包含指令;执行体看不到对话历史,所有需要的内容必须写入本字段"。主助理 system prompt(`assistant_prompt.py`)不动。
- **Rationale**: 用户明确要求(已记入长期记忆):约束跟工具走——填参时刻可见、自动覆盖所有持有者(planner 也用 build_task_graph)、与工具同文件不漂移。
- **注意**: 该约束是**模型软约束**(是否携带靠 description 指导);系统硬保证仅限"合法引用逐字展开、非法引用整体报错"(spec CC-001,与项目"软约束/硬保证"文档惯例一致)。

## D9. 下标参数的持久化边界

- **Decision**: 不新增专门引用实体,也不把下标写入 `assistant_tasks.description`;Task 只保存展开全文。AgentLoop 继续按既有消息协议把原始 tool-call 参数保存在 `messages.tool_calls`,用于 function-call 配对、审计及 pending tool-call 恢复。
- **Rationale**: 崩溃可能发生在保存 assistant tool call 后、handler 执行前。保留原始参数后,恢复路径会看到下标但因没有原 LLM 快照而 fail-closed;若静默删掉该参数,恢复反而会把委派当成“未请求上下文”执行。数字下标可进入既有活动投影,普通日志仍只记数量且不记录所指内容。

## 实读核实的关键代码事实(实现时的锚点)

| 事实 | 位置 |
|---|---|
| 快照来源:`messages = ctx.assemble_context()` 后进 `_execute_tool_batch`,快照不传入工具 | `agent_loop.py:1322,1359` |
| contextvar 先例 `use_tool_runtime` | `agent_loop.py:389-398` |
| 恢复/initial 两条无快照路径 | `agent_loop.py:1288-1319` |
| system prompt 以 `role="system"` 消息行存储,在可见数组内 | `agent_loop.py:1116` |
| handler 仅收 `**tool_call.args`,无 context 注入 | `agent_loop.py:415` |
| `delegate_to_subagent` schema/handler | `assistant_tools.py:1755-1833` |
| ephemeral 委派入口(simple/complex 分流) | `delegation_orchestrator.py:30-69` |
| 同步执行核心 + `_format_delegated_task_input` 调用点 | `delegation_orchestrator.py:95-160(140)` |
| specialist 入口(无 execution_context) | `delegation_orchestrator.py:162-224` |
| specialist 执行核心(`_format_delegated_task_input(task)` 单参) | `delegation_orchestrator.py:249-364(351)` |
| 输入拼装 `_format_delegated_task_input` | `orchestrator.py:1523-1539` |
| 异步 ephemeral 回填 description→execution_context | `task_executor_adapter.py:101-121` |
| 异步 specialist 只传 title(description 丢失) | `task_executor_adapter.py:123-150` |
| 委派工具不并发(caller thread 契约) | src/CLAUDE.md「Agent 与工具约束」 |
