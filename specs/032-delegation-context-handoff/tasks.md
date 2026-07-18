# Tasks: 委派上下文交接

**Input**: Design documents from `specs/032-delegation-context-handoff/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/delegation-tools.md, quickstart.md
**Tests**: 用户要求 TDD——每个实现任务前置对应测试任务(先 RED 后 GREEN)。

**Organization**: 按 user story 分组;US1(P1 子代理携带原文)→ US3(P1 异步落库全文)→ US2(P2 专员对齐)。
**Bugfix**: 2026-07-17 — BUG-001（来源 VERIFY-F1）补齐 T019 相邻 MCP/Desktop API 修复在 032 spec/plan 中的影响面声明。
**Bugfix**: 2026-07-18 — BUG-002（来源 VERIFY-F1/VERIFY-G1）修复 MCP SDK stack cleanup 静默成功并补齐 plan 文件清单。

## Phase 1: Setup

无新依赖、无脚手架;跳过(既有 uv/pytest 环境直接可用)。

## Phase 2: Foundational(阻塞所有 user story)

快照 contextvar 与下标解析器是三个 story 的共同底座;AgentLoop 快照生命周期决定 fail-closed 边界。

- [X] T001 [P] 编写 resolver 单元测试(RED):tests/business/agents/test_delegation_context.py——合法下标逐字展开(含 role 标记格式)、按完整数组 1-based 计数但 system 引用整体拒绝、越界/非正整数/非法类型/重复下标整体拒绝、提供空数组拒绝、无快照时拒绝、展开总量超上限拒绝(不截断)、上限从 get_unified_config 读取且缺省 30000
- [X] T002 实现 src/business/agents/delegation_context.py:`use_llm_messages_snapshot(messages)` context manager(contextvar,参照 agent_loop.py:389-398 的 use_tool_runtime 先例)、`resolve_context_message_indexes(indexes) -> str`(成功返回【主对话相关原文】文本块,失败抛携带用户可读 message 的专用异常);上限键 `agent_tools.delegation.context_expansion_max_chars` 经 get_unified_config() 读取
- [X] T003 [P] 编写 AgentLoop 快照生命周期测试(RED):tests/business/agents/test_agent_loop_snapshot.py——LLM 响应路径工具批次内快照可见、批次结束后不可见、pending tool calls 恢复路径(agent_loop.py:1288-1297)保留既有 tool-call 参数但无原快照而 fail-closed、initial_tool_calls 路径(1298-1319)无快照
- [X] T004 实现 AgentLoop 改动:src/business/agents/agent_loop.py 仅在 LLM 路径(1322 assemble 后、1359 批次调用处)用 use_llm_messages_snapshot(messages) 包住 _execute_tool_batch;恢复/initial 两条路径不设快照
- [X] T005 配置默认值:data/config/config.json 模板(或项目配置模板所在处)补 `agent_tools.delegation.context_expansion_max_chars: 30000`;若 UnifiedConfigManager 需要显式 getter 惯例则按 021 `agent_tools.discovery.*` 同款方式接入

**Checkpoint**: resolver 与快照底座测试全绿,任何委派工具尚未变化(全量既有测试仍绿)。

## Phase 3: User Story 1 — 委派时携带对话中已产生的内容 (P1) [US1]

**Goal**: delegate_to_subagent 支持 context_message_indexes;子代理初始输入含逐字原文;非法引用 fail-closed。

**Independent Test**: 构造父会话含方案消息 → 带下标委派 → 断言子会话首条 user 消息含方案原文;非法下标 → error JSON 且无子会话创建。

- [X] T006 [P] [US1] 编写 handler 行为测试(RED):tests/business/agents/test_assistant_tools_delegation_context.py——带合法 indexes 时 dispatch_callback 收到的 execution_context 尾部含展开块且原文逐字一致;不带 indexes 行为与现状一致(向后兼容);system/越界/无快照/超限时返回 error JSON(success=false、含原因与重填指引)且 dispatch_callback 未被调用;schema 断言:context_message_indexes 存在、required 不变、description 含"禁止指代/必须携带/system 不得引用"关键语义
- [X] T007 [US1] 实现 src/business/agents/tools/assistant_tools.py:DELEGATE_TO_SUBAGENT_SCHEMA 增加 context_message_indexes(契约文案见 contracts/delegation-tools.md),task_description/execution_context description 追加约束;create_delegate_to_subagent_handler 增参并在 dispatch 前调 resolve_context_message_indexes,成功合并进 execution_context,失败 error_json 整体拒绝
- [X] T008 [US1] 同步链路集成测试(GREEN 验证):tests/integration/test_delegation_context_handoff.py——父会话 → simple 委派带 indexes → run_sync_ephemeral_subagent → 子会话首条 user 消息(_format_delegated_task_input 输出)包含"补充上下文"段与【主对话相关原文】块,原文逐字一致;`load_reference` 保持主助理跨会话下钻,执行体按父消息 ID 读取时被角色授权门卫拒绝

**Checkpoint**: US1 独立可验收——同步子代理路径完整可用。

## Phase 4: User Story 3 — 异步任务稍后执行仍拿到全文 (P1) [US3]

**Goal**: complex 路由落库的 task.description 已是展开全文;快照消亡后执行体仍获全文。

**Independent Test**: complex 委派带 indexes → 读落库 task.description 含原文无下标残留 → 脱离委派轮直接经 TaskExecutorAdapter 执行 → 执行体输入含全文。

- [X] T009 [P] [US3] 编写异步落库测试(RED):tests/integration/test_delegation_context_handoff.py——complex 委派带 indexes 后,dispatcher 落库的 task.description 包含展开块原文、不含 "context_message_indexes" 字样或未解析下标;简单断言展开发生在落库前(handler 层)
- [X] T010 [US3] 编写快照消亡执行测试(RED→GREEN):tests/integration/test_delegation_context_handoff.py——落库后以全新 orchestrator/adapter(无快照 contextvar)执行该 task,TaskExecutorAdapter._run_ephemeral 回填的 execution_context 含全文;该用例同时覆盖"进程重启等价"语义(不依赖内存快照)。注:US3 的生产实现已由 T007 合并点覆盖,本阶段任务以测试证明链路,若测试暴露缺口再补实现

**Checkpoint**: US1+US3 一起构成 MVP——子代理同步/异步两条路都拿到原文。

## Phase 5: User Story 2 — 固定专员获得同等交接能力 (P2) [US2]

**Goal**: delegate_to_specialist 支持 execution_context + context_message_indexes;同步/异步专员路径都能收到补充上下文;修复异步专员 description 静默丢弃。

**Independent Test**: 专员委派带 execution_context+indexes → 专员初始输入含补充上下文与原文;异步专员任务 description 不再丢失。

- [X] T011 [P] [US2] 编写专员链路测试(RED):tests/business/agents/test_assistant_tools_delegation_context.py、tests/business/agents/test_specialist_context_chain.py——delegate_to_specialist handler 新参数(schema 断言 + 合并/fail-closed 与 T006 同款);DelegationOrchestrator.delegate_to_specialist 把 execution_context 传入 _dispatch_task_via_unified_model(context=execution_context or task)与 run_specialist_via_delegated_executor;run_specialist_via_delegated_executor 调 _format_delegated_task_input(task, execution_context);TaskExecutorAdapter._run_specialist 把非兜底 task.description 作为 execution_context 传递(修复回归:非空上下文不再丢失,为空或等于 title 的统一派发兜底时保持既有输入形态);formatter/helper 保留展开原文尾随空白
- [X] T012 [US2] 实现 assistant_tools.py:DELEGATE_TO_SPECIALIST_SCHEMA 增加 execution_context + context_message_indexes(required 不变),handler 增参、解析合并、fail-closed(与 T007 同构,可提取共享私有 helper)
- [X] T013 [US2] 实现 src/business/orchestration/agent/delegation_orchestrator.py:delegate_to_specialist 与 run_specialist_via_delegated_executor 增加 execution_context 参数并透传至 _format_delegated_task_input(task, execution_context)(delegation_orchestrator.py:200,351)
- [X] T014 [US2] 实现 src/business/orchestration/agent/task_executor_adapter.py:_run_specialist 增加 execution_context=task.description 传递(经 run_specialist_via_delegated_executor 新参数;保持 checkpoint 语义不变)

**Checkpoint**: 三个 story 全部独立可验收。

## Phase 6: Polish & Cross-Cutting

- [X] T015 [P] build_task_graph node description 文案加强:src/business/agents/tools/assistant_tools.py(1456 附近)——"自包含;执行体看不到对话历史,所有需要的内容必须写入本字段,禁止指代";补 schema 文案断言测试(轻量关键词断言,不做整段快照)
- [X] T016 [P] AI 入口文档更新:根与 src/ 的 AGENTS.md/CLAUDE.md/GEMINI.md 三镜像同步——Recent Changes 加 032 条目;src/ 模块「Agent 与工具约束」补"委派上下文交接:快照仅 LLM 路径、下标引用是模型软约束、展开逐字/fail-closed 是系统硬保证、委派工具不得并发安全"
- [X] T017 全量回归与静态检查:审查前 032 定向 82 passed(含 adapter→formatter 异步双层链路只在最终边界消费 provenance 的回归测试),最终 agents+memory+032 integration 479 passed,最终全量 `tests/` 2921 passed、3 skipped;agents+memory+task_collaboration+integration+guardrails 1125 passed(批内 filesystem MCP 初始化超时 1 次,单跑通过);审查前全量 `tests/` 2908 passed、3 skipped,中期审查修复后全量 2913 passed、3 skipped 且仅既有 `test_concurrent_supersede_serializes_without_version_fork` SQLite 并发抖动 1 次失败、隔离重跑通过;black/flake8 涉改文件通过;根与 src AI 入口三镜像各自一致。mypy 以运行时 3.12 + explicit-package-bases 检查 6 个涉改源文件时报告 39 个既有类型债务(原有 Optional/Any 返回、隐式 Optional 与事件 Literal,本 feature 新 resolver/授权/保真分支无新增错误),按 CONTRIBUTING 的可选类型检查记录为既有例外。既有委派测试 test_assistant_dispatch_tools 专员回调断言按新契约加 execution_context=""。过程中修复:config contract 注册新键、快照测试 LLMResponse 契约、system 能力目录隔离、执行体/主助理分级 load_reference 授权、专员 title 兜底兼容、provenance 隔离的展开块尾随空白保真(含异步中间层延迟消费)、非法错误范围提示、重复下标与展开上限契约漂移
- [X] T018 审查修补:spec/contract 明示异步 specialist description/checkpoint 兼容性例外;resolver 与完整 handler→formatter 链新增 assistant/tool 尾随空白逐字符断言;新增双线程 contextvar 会话隔离与两委派工具 `is_concurrency_safe=False` 门卫;真实 UnifiedConfigManager 覆盖默认 30000、嵌套文件值、runtime override 与 1000..1000000 边界。修补后 032 定向 84 passed,相关测试 129 passed,black/flake8 涉改 Python 文件通过;全量 `tests/` 为 2924 passed、3 skipped、1 failed,唯一失败仍是与本次 diff 无关的既有 `test_concurrent_supersede_serializes_without_version_fork` SQLite 并发抖动,隔离重跑在本机仍失败并记录为既有例外。
- [X] T019 `$speckit-review-run all` 修补:LLM messages 快照改为 `tuple` + frozen `SnapshotMessage` 的不可变 role/content 拷贝;pending/initial 路径改用真实委派 handler、真实 session 与原始 `context_message_indexes` 证明无快照 fail-closed;specialist 集成覆盖真实 handler→orchestrator→TaskDispatcher→Repository→attempt→TaskExecutorAdapter;补齐 `load_reference` 不存在/越权同文案说明。MCP 生命周期增加 startup attempt 唯一围栏、资源构造前 bind、current+未取消原子发布、bridge/stop 迟到成功隔离、starting/running 全覆盖关停、两轮有界取消/收割、owner-thread loop close、失败观察与 `McpServerService.shutdown()` facade 接线;同步 027 contract、032 data-model、ARCHITECTURE 与 src AI 入口镜像。修补后定向 `142 passed`;Black、Flake8、`git diff --check` 通过;规格与 Standards 二次复核均 PASS、无剩余 actionable finding。全量 `tests/` 为 `2951 passed, 3 skipped, 1 failed`;唯一失败是既有 `test_create_dedup_allows_same_key_terminal_after_cooldown` 批内时间抖动,隔离复跑通过且该 repository 文件 `25 passed`。
- [X] T020 [BUG-001] 修复验证范围漂移:更新 specs/032-delegation-context-handoff/spec.md、plan.md、tasks.md,显式声明 T019 的 `src/business/mcp/` 与 `src/desktop_api/app.py` 影响面、startup attempt/shutdown 约束、027 contract 权威边界和对应测试;`speckit-bugfix-verify` 跨工件检查通过(报告 Patched、FR-011/FR-012 可追踪、T001-T020 连续、DAG 有效),Markdown H1/围栏与 `git diff --check` 通过,改动相关定向测试 `230 passed`;同一 Python 代码状态的全量 `tests/` 为 `2952 passed, 3 skipped`
- [X] T021 [BUG-002] 先补 RED 测试:tests/business/mcp/test_mcp_process_manager.py 覆盖公开 `stop_server()` 对 SDK stack close 异常/超时的传播、失败后缓存清空,以及 `shutdown()` 在完成 loop/thread 收口后向同步调用方报告 stack cleanup 失败;实现前两个 stop 测试均按预期失败,实现后三例转绿
- [X] T022 [BUG-002] 修复 src/business/mcp/mcp_process_manager.py:`_stop_server_coro` 汇总 startup task 与 `stack.aclose()` 超时/异常,始终清空 session/stack/stderr/name 缓存后抛出;`stop_all()`/`shutdown()` 继续传播;同步 032 spec/plan、027 lifecycle contract 与 docs/ARCHITECTURE.md,移除未实现 `_terminate_tree` fallback 的错误契约
- [X] T023 [BUG-002] 补齐 plan.md 对 `.specify/feature.json`、config.example.json、builtin_tools.py、tool_registry.py、配置/dispatch 回归测试、BUG 报告及活文档的实际文件清单;完整 branch diff 的文件 basename 均可在 Project Structure 追踪;`speckit-bugfix-verify` 检查 BUG-001/BUG-002 均为 Patched、FR-012/SC-007→plan→T021-T023 可追踪、T001-T023 连续唯一且 DAG 有效;MCP/sidecar/guardrail 定向 `116 passed`;Black、Flake8 与 `git diff --check` 通过

## Dependencies

```text
Phase 2 (T001→T002, T003→T004, T005)
  └─→ Phase 3 US1 (T006→T007→T008)
        └─→ Phase 4 US3 (T009, T010)   # 依赖 T007 的合并点
        └─→ Phase 5 US2 (T011→T012→T013→T014)  # T012 复用 T007 的 helper
              └─→ Phase 6 (T015, T016 可提前并行;T017→T018→T019→T020→T021→T022→T023 收尾)
```

- US3 与 US2 相互独立,可并行(不同文件为主;T012 与 T009/T010 无共享文件冲突,但 assistant_tools.py 同文件任务 T007/T012/T015 需串行)。

## Parallel Example

- Phase 2: T001 与 T003 并行(不同测试文件);T005 与 T002 并行。
- Phase 4/5: T009/T010(US3)与 T011(US2 测试)可并行编写。
- Phase 6: T015 与 T016 并行。

## Implementation Strategy

- **MVP** = Phase 2 + US1 + US3(P1 全覆盖:同步/异步子代理都拿到原文)。
- US2 为同构扩展 + 既有缺口修复,紧随其后。
- T019 MCP 生命周期修复是综合审查产生的相邻可靠性修复,不扩展委派产品能力;T020 负责把其实际影响面补回 032 规格与计划。
- BUG-002 以 T021 RED 测试锁定静默失败,T022 修实现/契约,T023 完成文件清单与验证门禁。
- 每个 Checkpoint 处跑一次相关回归,保证增量可交付。
