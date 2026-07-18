# Implementation Plan: 委派上下文交接

**Branch**: `032-delegation-context-handoff` | **Date**: 2026-07-14 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/032-delegation-context-handoff/spec.md`
**Bugfix**: 2026-07-17 — BUG-001（来源 VERIFY-F1）补齐 T019 已落地的 MCP 生命周期与 Desktop API shutdown 接线影响面。
**Bugfix**: 2026-07-18 — BUG-002（来源 VERIFY-F1/VERIFY-G1）让 MCP SDK stack 清理失败在缓存收口后显式传播，并补齐实际文件影响面。

## Summary

主助理委派任务时,执行体(临时子代理/固定专员)在全新空会话启动,对话中已产生的内容无法传递。本 feature 给 `delegate_to_subagent` / `delegate_to_specialist` 增加 `context_message_indexes` 参数:主助理按其本轮可见消息数组的下标引用非 system 历史消息;AgentLoop 在 LLM 响应后的工具执行阶段通过 contextvar 暴露本轮 assembled messages 快照(复用 `use_tool_runtime` 同款模式),委派 handler 在委派时刻按下标取原文、合并进 `execution_context` 作为"主对话相关原文"段;同步路径直接进入执行体初始输入,异步路径随 `task.description` 落库持久化。system/非法下标与超量整体 fail-closed。填参硬约束写在工具 schema description,不改主助理 system prompt。既有 `load_reference` 的 message ID 路径在 `ContextManager` seam 按 Agent 角色授权:主助理保留跨会话记忆下钻,执行体不能绕过交接读取父会话消息。

综合审查的 T019 同时修复了既有 MCP server 生命周期竞争:为每个 server 建立唯一 startup attempt fence,在资源构造前绑定,仅允许 current + 未取消 attempt 原子发布 session;bridge timeout、stop 与 shutdown 隔离迟到成功,关停覆盖 running/starting server、startup cleanup 与残留 Task,并由 owner thread 关闭 loop。Desktop API lifespan 改为只调用 `McpServerService.shutdown()`。这是保留在本分支的相邻可靠性修复,不新增 MCP 产品能力、公开 API、UI event、secret 或 schema;权威协议继续由 027 lifecycle contract 承载。

## Technical Context

**Language/Version**: Python 3.11+(运行时 3.12)
**Primary Dependencies**: 自研 AgentLoop、blinker、SQLAlchemy、asyncio、既有 MCP SDK/FastAPI lifespan(均既有,无新依赖)
**Storage**: SQLite——复用 `assistant_tasks.description`(v15 既有列),0 新表 / 0 migration
**Testing**: pytest(`uv run python -m pytest`);委派单元/行为/集成 + MCP 生命周期并发/清理（含 SDK stack close 超时/异常传播）+ Desktop API lifespan + guardrails
**Target Platform**: Windows 桌面(Tauri shell + Python sidecar)
**Project Type**: desktop-app(~~本 feature 仅动 Python business + 统一配置 data seam~~ 委派主线涉及 business/data;T019 相邻修复另涉及 business/mcp 与 desktop_api lifespan)
**Performance Goals**: 展开为纯内存拷贝,无额外 LLM 调用、无消息正文 DB 查询(快照已在内存);仅跨会话 message reference 授权时查询当前 session 角色
**Constraints**: system 消息禁止展开;展开总量可配置上限(默认 30000 字符),超限整体报错;委派工具保持 `is_concurrency_safe=False`(contextvar 依赖 caller thread);MCP startup attempt 必须 current + 未取消才可发布,shutdown 必须有界收口且失败可观察;`stack.aclose()` 超时/异常时仍须清空内部缓存并向 stop/shutdown 调用方传播失败
**Scale/Scope**: ~~单用户桌面应用;改动集中在 AgentLoop、委派工具/编排、ContextManager 会话引用门卫、统一配置与测试~~ 单用户桌面应用;委派主线保持上述范围,T019 相邻修复额外覆盖 `src/business/mcp/`、`src/desktop_api/app.py`、027 lifecycle contract 及对应测试

## Constitution Check

| Principle | Gate question | Evidence |
|-----------|---------------|----------|
| I. Layered Boundaries & Event Coordination | 保持 `UI -> business -> execution -> data/driver`? | ~~仅动 `src/business/`;0 UI/desktop_api 改动~~ 委派主线位于 business/data seam;T019 在 `business/mcp` 内实现生命周期语义,`desktop_api` 只经 `McpServerService.shutdown()` facade 调业务层,无 router/DTO/UI event 扩展。PASS |
| II. Data Boundary & Persistence Discipline | Repository 边界、无裸 SQL? | 不新增任何 SQL;展开文本经既有 `_dispatch_task_via_unified_model → dispatcher.create_child_task` 落入 `assistant_tasks.description`(既有 Repository 路径)。PASS |
| III. Unified Config & Secret Handling | 配置/密钥统一入口? | 新配置键 `agent_tools.delegation.context_expansion_max_chars`,经 `get_unified_config()` 读取并给默认值;非 secret;同步更新 config 模板默认值。PASS |
| IV. Verifiable Delivery | 确定性逻辑有自动化测试? | 委派覆盖 resolver、schema/handler、同步/异步链路、恢复、隔离和兼容;MCP 相邻修复覆盖唯一 attempt、资源构造前 stop、bridge timeout/迟到成功、starting/running shutdown、两轮有界取消/收割、owner-thread loop close、SDK stack close 超时/异常经公开 stop/shutdown 传播、失败观察及 Desktop API facade 接线。PASS |
| V. Living Docs & Spec-Driven Delivery | 活文档更新点明确? | 更新根/`src/` AI 入口镜像、`docs/ARCHITECTURE.md`、032 spec/plan/tasks,并同步 `specs/027-mcp-management/contracts/mcp-server-lifecycle.md`;constitution 不变。PASS |

~~无违例,Complexity Tracking 留空。~~ BUG-001（来源 VERIFY-F1）补记 T019 相邻修复后,受影响层、测试与活文档均已显式列出;复杂度见文末记录。

## Project Structure

### Documentation (this feature)

```text
specs/032-delegation-context-handoff/
├── spec.md              # feature 需求与验收标准
├── plan.md              # 本文件
├── research.md          # Phase 0:决策记录
├── data-model.md        # Phase 1:实体与数据流
├── quickstart.md        # Phase 1:验证路径
├── checklists/
│   └── requirements.md  # 需求质量检查
├── bugs/
│   ├── BUG-001.md       # T019 MCP/Desktop API 影响面追踪
│   └── BUG-002.md       # SDK stack cleanup 与文件清单修复追踪
├── contracts/
│   └── delegation-tools.md  # 委派工具参数契约与错误码
└── tasks.md             # Phase 2(/speckit-tasks 生成)

specs/027-mcp-management/contracts/
└── mcp-server-lifecycle.md  # [改] T019 startup attempt/shutdown 权威契约

docs/
└── ARCHITECTURE.md      # [改] 委派边界与 MCP shutdown/stack cleanup 语义
```

### Source Code (repository root)

```text
.specify/
└── feature.json                          # [改] 当前 feature 元数据

config.example.json                       # [改] delegation 配置默认值

src/business/
├── agents/
│   ├── agent_loop.py                    # [改] LLM 路径工具批次外包快照 contextvar
│   ├── builtin_tools.py                 # [改] load_reference 按执行角色授权
│   ├── delegation_context.py            # [新] 快照 contextvar + 下标解析/展开/上限校验
│   └── tools/assistant_tools.py         # [改] 两个委派工具 schema+handler、build_task_graph node description 表述
├── memory/
│   └── context_manager.py                # [改] load_reference message ID 按 Agent 角色授权
├── orchestration/agent/
│   ├── delegation_orchestrator.py       # [改] specialist 链路补 execution_context 透传
│   ├── orchestrator.py                  # [改] specialist wrapper 透传 execution_context;formatter 保留原文空白
│   ├── task_executor_adapter.py         # [改] _run_specialist 补 description→execution_context(修既有丢失缺口)
│   └── tool_registry.py                 # [改] delegation facade specialist execution_context 协议
└── mcp/
    ├── mcp_process_manager.py            # [改] startup attempt fence、迟到成功隔离、有界 shutdown/drain、stack cleanup 失败传播
    └── mcp_server_service.py             # [改] business shutdown facade

src/data/
├── config_models.py                     # [改] delegation 配置模型
└── unified_config.py                    # [改] 上限 getter

src/desktop_api/
└── app.py                                # [改] lifespan 只经 McpServerService.shutdown() 关停

tests/
├── business/
│   ├── agents/
│   │   ├── test_delegation_context.py                  # [新] resolver 单元测试
│   │   ├── test_agent_loop_snapshot.py                 # [新] 快照生命周期测试
│   │   ├── test_assistant_dispatch_tools.py            # [改] specialist callback 新契约回归
│   │   ├── test_assistant_tools_delegation_context.py  # [新] handler/schema 行为测试
│   │   └── test_specialist_context_chain.py            # [新] 专员透传/兼容测试
│   └── mcp/
│       ├── test_mcp_process_manager.py                 # [改] attempt fence/shutdown 竞争、清理与失败传播
│       ├── test_mcp_server_service.py                  # [改] shutdown facade
│       └── test_sync_bridge_threading.py               # [改] bridge 线程边界
├── data/
│   └── test_unified_config.py                          # [改] delegation 配置默认/覆盖/边界
├── desktop_api/
│   └── test_app_startup.py                             # [改] lifespan shutdown facade
└── integration/
    ├── test_assistant_dispatch.py                      # [改] specialist execution_context 回归
    └── test_delegation_context_handoff.py              # [新] 同步/异步/隔离链路
```

**Structure Decision**: 委派运行语义落在 `src/business/` 既有模块,配置声明落在 `src/data/` 统一配置 seam;新模块 `delegation_context.py` 放 `src/business/agents/`(与 AgentLoop 同层,被 tools 与 loop 共用,不反向依赖 orchestration)。父消息引用隔离收敛在既有 `ContextManager.load_reference` seam,调用方无需新增参数或复制授权逻辑。T019 相邻修复继续把 MCP 生命周期语义留在 `src/business/mcp/`;Desktop API 只调用 service facade,不承载进程或取消规则。

## 核心设计决策(摘要,详见 research.md)

1. **快照通道 = contextvar**:AgentLoop `run()` 的 LLM 路径(`messages = ctx.assemble_context()` 后)用 `use_llm_messages_snapshot(messages)` 包住 `_execute_tool_batch`;委派 handler 经 `get_llm_messages_snapshot()` 取。恢复路径(pending tool calls)与 `initial_tool_calls` 路径**不设快照**——此时原快照不可复现,带下标的委派 fail-closed 报"快照不可用,请重新委派"。
2. **下标语义**:1-based,按主助理本轮实际收到的完整消息数组顺序计数(system 仍占位置但不得选择);工具 description 明确写出计数与 system 禁止规则。
3. **展开合并点 = 委派 handler**:解析成功后把"【主对话相关原文】"文本块追加进 `execution_context`;同步路径经 `_format_delegated_task_input` 的既有"补充上下文"段渲染,异步路径经 `_dispatch_task_via_unified_model(context=...)` 落库进 `task.description` 再由 adapter 送达。handler 在展示 header 后附不可见内部 provenance;持久化、adapter 与 checkpoint 拼接中间层保留标记,最终 `_format_delegated_task_input` 才由共享 normalization helper 识别该组合、逐字保留展开块并移除 provenance,避免异步链路重复消费;普通上下文(含同名 header)保持 032 前 `.strip()` 语义。
4. **专员链路补齐**(既有缺口顺带修复):`delegate_to_specialist` 工具加 `execution_context` + `context_message_indexes`;`DelegationOrchestrator.delegate_to_specialist` / `run_specialist_via_delegated_executor` 增加 `execution_context` 透传到 `_format_delegated_task_input(task, execution_context)`;`TaskExecutorAdapter._run_specialist` 把 `task.description` 作为 execution_context 传下去(当前只传 `task.title`,description 被静默丢弃)。
5. **fail-closed 语义**:引用 system 消息、下标非法(越界/非正整数/重复)、快照不可用、展开总量超上限——整次委派返回标准 error JSON(含具体原因与重填指引),不部分展开;错误结果回到主助理下一轮由其重填。
6. **约束落点 = 工具 schema description**:`task_description`/`execution_context`/`context_message_indexes` 三处 description 写明"执行体看不到对话历史;引用对话已产生内容必须用 context_message_indexes 携带原文,禁止只写指代;不得引用 system";`build_task_graph` node `description` 字段同步加强"自包含+看不到对话历史"表述。不改 system prompt。
7. **父消息隔离 = ContextManager seam 角色授权**:`load_reference` 的 summary ID 路径保持既有显式跨会话摘要能力;message ID 路径允许主助理跨会话记忆下钻,其他 Agent 只允许 `message.session_id == ContextManager.session_id`;不存在与越权共用不泄露存在性的错误文案。执行体即使从展开的工具结果中看到父消息 ID,也不能回读父会话。
8. **下标持久化边界**:AgentLoop 既有 `messages.tool_calls` 仍保存原始参数用于配对/审计/崩溃恢复;数字下标不进入 `assistant_tasks.description`,恢复时因原快照缺失而 fail-closed,不能把参数删除后静默降级成无上下文委派。
9. **MCP 相邻审查修复 = startup attempt fence + 有界 shutdown**:每个 server 同时只有一个权威 attempt,Task 在任何 SDK/资源构造前 bind;只有 current + 未取消 attempt 可在锁内原子发布 session/stack/cache。bridge timeout、stop/shutdown 先使 attempt 失效,再做两轮有界取消/收割;stop 汇总 startup task 与 SDK stack cleanup 失败，始终清空本地 session/stack/stderr/name 缓存后再抛出；shutdown 继续向同步调用方传播该失败。owner thread 负责最终 loop close。Desktop API 只经 `McpServerService.shutdown()` facade,完整状态机与伪代码见 027 lifecycle contract。

## Regression Compatibility Note

全量配置契约回归另行暴露了既有模板漂移:`UIConfig` 已定义 `accent` / `radius`,但 `config.example.json` 缺字段。修复以独立提交 `9f7ca34` 保留,不属于 032 的运行时行为或需求扩展;032 自身新增的配置面仍只有 `agent_tools.delegation.context_expansion_max_chars`。

T019 的 MCP 生命周期修复同样不是新的委派产品能力,而是综合审查发现并已保留在本分支的相邻可靠性修复。它不新增依赖、公开 API、UI event、secret、表或 migration,但会改变 MCP server 启停失败与清理的内部语义;因此必须在本 plan 的受影响层、结构、测试和复杂度中显式声明,并以 027 lifecycle contract 为权威。

BUG-002 进一步校正停止语义：SDK `AsyncExitStack.aclose()` 超时或抛异常不再被 warning-only 吞掉。内部缓存仍确定性清空，但 `stop_server()`、`stop_all()` 与同步 `shutdown()` 必须报告失败；当前 SDK adapter 不暴露可依赖的 PID，因此契约不再声称存在未实现的 `_terminate_tree` 兜底。

## Complexity Tracking

| Deviation | Why Needed | Simpler Alternative Rejected |
|-----------|------------|-------------------------------|
| 032 分支同时包含 T019 的 MCP 生命周期相邻修复 | 综合审查发现 startup timeout/stop/shutdown 的迟到发布与清理竞争;代码、测试和 027 contract 已在本分支形成一致修复,计划必须如实声明实际影响面 | 仅在 tasks.md 事后备注会让 plan 错报“0 desktop_api/MCP 影响”,违反 Constitution 的计划完整性门禁;静默延期则保留已知生命周期风险 |
| SDK `AsyncExitStack.aclose()` 在 server 已发布后仍可能超时或失败 | 本地缓存必须收口以避免复用失效 session，同时调用方必须知道 SDK 子进程资源可能没有完成释放 | 仅记录 warning 并返回成功会制造“已安全停止”的假象，违反可验证交付与显式失败原则 |
