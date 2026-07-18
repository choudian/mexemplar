# Feature Specification: 委派上下文交接

**Feature Branch**: `032-delegation-context-handoff`
**Created**: 2026-07-14
**Status**: Completed
**Input**: User description: "委派上下文交接:修复子代理/专员无法继承对话上下文的问题。主助理委派任务给临时子代理/固定专员时,执行体在全新空会话启动,对话历史中已产生的内容(如上一轮生成的方案)无法传递——主助理若用'之前讨论的方案'这类指代,子代理只能凭空编造。"
**Bugfix**: 2026-07-17 — BUG-001（来源 VERIFY-F1）补记综合审查中已落地的 MCP 生命周期竞争修复及 Desktop API shutdown facade 接线,使规格影响面与分支实现一致。
**Bugfix**: 2026-07-18 — BUG-002（来源 VERIFY-F1/VERIFY-G1）修复 MCP SDK stack 清理失败被伪装成成功，并补齐 plan 的实际文件影响面。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 委派时携带对话中已产生的内容 (Priority: P1)

用户与主助理在对话中讨论产出了一个方案(或清单、结论、代码片段)。下一轮用户说"把这个方案写到某路径"。主助理委派执行体时,通过消息引用把方案所在的历史消息一并交接;执行体启动时的初始输入里已经包含方案原文,能够忠实执行,而不是基于"之前讨论的方案"这类指代凭空编造。

**Why this priority**: 这是本 feature 要修复的核心缺陷——当前执行体在全新空会话启动,唯一输入是主助理手写的任务描述,对话中已产生的内容整段丢失,直接导致交付内容错误或编造。

**Independent Test**: 构造"上一轮助理消息含方案全文、本轮委派写文件"的会话,主助理调用委派工具并引用方案所在消息;断言执行体收到的初始输入包含方案原文(逐字一致),且执行体没有任何可读取父会话的工具。

**Acceptance Scenarios**:

1. **Given** 会话历史中存在一条含方案全文的助理消息, **When** 主助理委派子代理并通过消息引用携带该消息, **Then** 子代理的初始输入包含该消息原文,内容与父会话中的原文逐字一致。
2. **Given** 主助理委派时未提供任何消息引用, **When** 委派执行, **Then** 行为与现状完全一致(仅任务描述 + 可选补充上下文),不报错、不注入额外内容。
3. **Given** 子代理已启动, **When** 检查其能力集合, **Then** 不存在任何按下标或 ID 读取父会话消息的工具(执行体是纯接收方)。

---

### User Story 2 - 固定专员获得同等交接能力 (Priority: P2)

用户让主助理把任务派给固定专员。专员委派入口此前连"补充上下文"字段都没有,交接面比子代理更窄。本 feature 后,专员委派与子代理委派具备同等的上下文交接能力:既能带补充说明,也能引用历史消息。

**Why this priority**: 专员是长期使用的执行角色,交接面缺口比子代理更大;但主路径(临时子代理)先行验证后,专员对齐属于同构扩展。

**Independent Test**: 用固定专员委派入口发起带消息引用的任务,断言专员初始输入包含引用消息原文与补充上下文。

**Acceptance Scenarios**:

1. **Given** 会话中已有讨论产出的内容, **When** 主助理委派专员并携带补充上下文与消息引用, **Then** 专员初始输入同时包含任务描述、补充上下文和被引用消息的原文。
2. **Given** 主助理只给了任务描述, **When** 委派专员, **Then** 行为与现状一致,向后兼容。

---

### User Story 3 - 异步任务稍后执行仍拿到全文 (Priority: P1)

复杂任务走建图落库、由调度器稍后驱动执行。委派时引用的消息在落库前就地展开为原文并持久化;即使进程重启、快照消失,worker 执行任务时拿到的仍是展开后的全文。

**Why this priority**: 消息引用只在主助理填参那一瞬间有意义(基于本轮可见消息数组的快照);若推迟解析,异步执行时快照已不存在,交接会静默失效。这是正确性边界,必须与 P1 主场景同期落地。

**Independent Test**: 委派复杂任务(建图落库)时携带消息引用,读取落库后的任务描述,断言其中已包含展开后的原文而非下标;模拟延迟执行,断言执行体输入仍含全文。

**Acceptance Scenarios**:

1. **Given** 主助理委派复杂任务并引用历史消息, **When** 任务落库, **Then** 持久化的任务描述中已包含被引用消息的展开原文,不含未解析的下标。
2. **Given** 任务已落库且原始委派轮的内存快照已不存在, **When** 调度器驱动执行体运行该任务, **Then** 执行体初始输入包含展开原文,内容完整。

---

### Adjacent Review Repair - MCP 生命周期竞争加固 (Verification Gate)

综合审查在 032 分支内发现既有 MCP server 启停路径存在竞争窗口:同步桥超时、显式 stop 或 sidecar shutdown 后,旧启动协程仍可能迟到发布 session;关停也可能遗漏 starting server、未收割后台 Task 或在非 owner thread 关闭事件循环。该修复不扩展 032 的委派产品能力,但既然实现与测试已保留在本分支,就必须作为相邻审查修复被规格和计划显式声明。

**Independent Test**: 对同一 server 并发/连续启动、在资源构造前 stop、桥超时后迟到成功及 sidecar shutdown 场景做确定性测试;断言同时只有一个权威 startup attempt,已取消 attempt 不得发布 running session,所有 starting/running server 与残留 Task 被有界收割,且 Desktop API lifespan 只调用 `McpServerService.shutdown()`。

**Acceptance Scenarios**:

1. **Given** MCP server 正在启动, **When** 同步桥超时、用户 stop 或 shutdown 使当前 attempt 失效, **Then** 第三方 SDK 即使吞掉取消并迟到成功也不得发布 session/stack/cache,未发布资源必须进入可观察的清理路径。
2. **Given** sidecar 开始关闭且存在 running/starting server 或残留后台 Task, **When** lifespan 执行 shutdown, **Then** 它通过 business facade 完成有界停止、取消、收割和 owner-thread loop close;无法收口时显式失败而非静默伪装成功。

---

### Edge Cases

- 消息引用指向 system 消息(可能含当前 Agent 专属能力目录),或下标越界、重复、非法(负数、非整数)时:整次委派 fail-closed 报错,错误信息回给主助理让其重填;不部分展开、不静默忽略非法项。
- 被引用内容已被上下文压缩归档(主助理可见数组里只剩摘要):主助理本身数不到原文所在位置,此场景不在 V1 范围;主助理应先用既有的原文取回机制恢复内容再委派。
- 展开原文总量过大(如引用了多条超长消息):超过配置上限时整次委派报错并提示缩小引用范围,避免执行体上下文被无节制撑爆。
- 被引用消息是工具结果(如文件读取输出):允许引用——执行结果同样可能是需要交接的内容;按原文展开,不做二次加工。
- 同一轮对话内并发/连续多次委派:每次委派独立解析各自的引用,互不影响。
- MCP 启动 Task 在 bridge/stop/shutdown 的取消期限内拒绝退出时:旧 attempt 仍必须先失去发布资格;stop/shutdown 显式报告未收口风险,不得把迟到 session 写回 running 状态。
- MCP running server 的 SDK `AsyncExitStack.aclose()` 超时或抛错时:内部 session/stack/cache 仍必须清除,但 `stop_server()` / `shutdown()` 必须向同步调用方传播失败,不得只记 warning 后伪装成功。

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: 临时子代理委派入口 MUST 支持可选的消息引用参数:主助理按其当前可见的对话消息顺序指定要携带的历史消息;不提供时行为与现状一致。
- **FR-002**: 固定专员委派入口 MUST 补齐"补充上下文"字段,并支持与 FR-001 同等的消息引用参数。
- **FR-003**: 引用解析与原文展开 MUST 由委派链路在委派时刻完成,基于本轮喂给主助理的消息数组快照;展开结果作为独立的"主对话相关原文"段落注入执行体初始输入。
- **FR-004**: 展开 MUST 逐字保真:原文由系统拷贝,不经任何模型改写、摘要或截断(超上限时整体报错而非截断)。
- **FR-005**: 异步/建图路径 MUST 在任务持久化之前完成展开,持久化内容为全文;任务执行 MUST NOT 依赖委派轮的内存快照。
- **FR-006**: 非法引用(system 消息、越界、重复、非法值) MUST fail-closed:整次委派失败并把可理解的错误返回主助理供其重填;MUST NOT 部分展开或静默丢弃。system 消息 MUST NOT 下放,避免泄漏只对父 Agent 授权的能力目录。
- **FR-007**: 展开原文总量 MUST 有可配置上限,超限整体报错;上限走统一配置入口。
- **FR-008**: 执行体 MUST 保持纯接收方:不新增任何读取父会话消息的工具或接口,子会话与父会话的隔离边界不变。
- **FR-009**: 填参硬约束 MUST 写在委派工具的 schema description 中(凡任务引用了对话中已产生的内容,必须用消息引用携带,禁止只写指代);MUST NOT 通过修改主助理 system prompt 实现。任务图建图入口的节点描述字段 MUST 同步加强"自包含"表述。
- **FR-010**: 本 feature MUST NOT 新增公开 UI 事件、secret、数据库表或 migration;
  省略 `context_message_indexes` 时不得触发消息下标解析或自动展开。兼容性例外是
  FR-002/FR-005 所需的异步 specialist 交接修复:非兜底 `task.description` 不再被
  静默丢弃,恢复 checkpoint 改由 `execution_context` 的补充上下文段传递;
  description 为空/等于 title 且无 checkpoint 时保持原输入形态。
- **FR-011**: 相邻 MCP 审查修复 MUST 为每个 `server_id` 保持至多一个权威 startup attempt;attempt MUST 在 SDK import、配置解析、临时资源和进程构造前绑定,且只有仍为 current、未取消的 attempt 才能在同一锁内原子发布 session/stack/cache。bridge 超时、stop 或 shutdown 后的迟到成功 MUST NOT 发布 running 状态。
- **FR-012**: Sidecar shutdown MUST 只经 `McpServerService.shutdown()` business facade 进入进程管理器;关停 MUST 覆盖 running/starting server、已跟踪 startup cleanup 与残留后台 Task,按有界取消/收割协议由 owner thread 关闭事件循环。无法在边界内收口时 MUST 显式记录并向同步调用方报告失败;尤其是 running server 的 SDK stack close 超时/异常不得被吞掉,内部缓存清理完成后仍 MUST 传播失败。

### Key Entities

- **消息引用**: 主助理填参时对其可见消息数组中非 system 消息的指称;仅在委派工具执行瞬间具有解析语义。既有 AgentLoop 会为 function-call 配对、审计和崩溃恢复保存原始 tool-call 参数,但下标不会进入持久 Task 描述,恢复时因原快照不存在而 fail-closed,不得延迟解析。
- **展开原文段**: 按引用取出的消息原文组成的文本段,注入执行体初始输入;异步路径下随任务描述一并持久化。

### Constraints & Compatibility

- **CC-001**: "主助理会正确携带所需上下文"是模型软约束(靠工具 description 指导),MUST NOT 描述为硬保证;系统硬保证的是"给了合法引用就逐字展开、给了非法引用就整体报错"。
- **CC-002**: 子会话与父会话的隔离是既有安全边界,本 feature 不得为交接便利开任何执行体侧读取父会话的口子。
- **CC-003**: 展开内容随任务描述落库属于既有存储面(会话内容本就持久化于消息表),不新增 secret 暴露面;引用解析过程不进普通日志。
- **CC-004**: 配置(展开总量上限)统一走 `get_unified_config()`,不硬编码。
- **CC-005**: MCP 生命周期相邻修复只加固 027 的既有 stdio server 启停契约;MUST NOT 新增公开 API、UI 事件、secret、表、migration 或传输类型。权威生命周期细节继续以 `specs/027-mcp-management/contracts/mcp-server-lifecycle.md` 为准。
- **CC-006**: startup attempt fence、迟到成功隔离和 shutdown drain 是确定性并发边界,必须由行为测试硬保证,不得依赖第三方 SDK 总会及时响应取消。

## Architecture Impact *(Mexemplar-specific)*

### Layer Impact

- [x] **Business** (`src/business/`) — 委派工具 schema、委派编排链路、ContextManager 引用授权、任务落库前的展开注入;相邻修复涉及 `business/mcp` 的 startup attempt fence、资源清理和 shutdown facade
- [x] **Data** (`src/data/`) — 仅统一配置模型/getter,0 新表、0 migration
- [x] **Desktop API Bridge** (`src/desktop_api/`) — 仅 lifespan shutdown 从直接进程管理器调用收口到 `McpServerService.shutdown()`;无 route、DTO、auth 或 UI event 契约变化
- [ ] **UI** / **Execution** / **Recording** / **Utils** — 不涉及

### Agent Impact

- Which Agent(s) are affected: Assistant(主助理委派工具)及其派生执行体(临时子代理 / 固定专员 / planner 产图路径的节点描述约束)
- New tools or modified tool handlers: 修改 `delegate_to_subagent`、`delegate_to_specialist`(新增参数与 description 约束)、`build_task_graph`(仅 node description 表述加强);无新工具
- System prompt changes needed: 无(约束明确要求写在工具 description,不改 system prompt)
- Orchestrator dispatch changes: 委派链路透传本轮消息数组快照,委派时刻解析引用并展开注入执行体初始输入;异步路径落库前展开

### MCP Lifecycle Impact

- 每个 server 同时只允许一个权威 startup attempt;资源构造前 bind,current + 未取消是唯一发布条件。
- bridge timeout、stop 与 shutdown 先使 attempt 失效,再做有界取消/等待;迟到成功不能覆盖权威状态。
- shutdown 覆盖 running/starting server、startup cleanup 与残留 Task,事件循环只由 owner thread 关闭。
- Desktop API lifespan 只调用 `McpServerService.shutdown()`;027 lifecycle contract 与 `docs/ARCHITECTURE.md` 已同步。

### Data Store Impact

- **SQLite**: 无新表、无 migration;复用既有任务描述字段持久化展开后的全文
- **Config**: 新增展开总量上限配置键,走统一配置入口
- **Secrets**: 无新增敏感字段

### Event Impact

- 无新公开 UI 事件;无内部事件变更

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 典型场景(上一轮产出方案、本轮委派写文件)下,执行体初始输入包含方案原文且与父会话原文逐字一致,自动化测试可验证。
- **SC-002**: 100% 的非法引用委派整体报错并可被主助理重试,不存在部分展开或静默丢弃的用例。
- **SC-003**: 异步任务在委派轮内存快照消失(含进程重启)后执行,执行体输入仍包含展开全文。
- **SC-004**: 不使用 `context_message_indexes` 的既有委派回归测试保持通过;异步
  specialist 的 description/checkpoint 兼容性例外由专门回归测试覆盖。
- **SC-005**: 专员委派入口与子代理委派入口的上下文交接能力对齐(补充上下文 + 消息引用均可用)。
- **SC-006**: MCP 并发启动、资源构造前 stop、bridge 超时/取消、迟到成功与失败清理测试全部通过;不存在已失效 startup attempt 发布 running session 的用例。
- **SC-007**: MCP shutdown 测试证明 running/starting server 与后台 Task 均进入有界收口,Desktop API lifespan 只经 service facade 关停;startup Task 拒绝取消、SDK stack close 超时/异常及 drain/join 失败都可观察并向同步调用方传播,不会静默成功。

## Assumptions

- 主助理对"短距离"非 system 消息(最近几轮)的下标计数可靠性足够高;数错下标导致携带错误内容的兜底校验(如内容摘要比对)不在 V1 范围,作为后续可选加固。
- 被压缩归档区间的内容引用不在 V1 范围:主助理可见数组里数不到原文;既有的原文取回机制(`load_reference`)覆盖该场景。
- 引用粒度为单条可见消息,允许引用工具结果消息(执行结果也可能是要交接的内容)。
- 项目当前为单用户未发布阶段,无外部消费者,委派工具参数变更无需双发兼容或 deprecation 周期。
- 消息序号渲染(`[#seq]` 前缀)与按序号区间取原文的存储接口均不在本 feature 范围(下标按内存快照解析,不查库)。
- MCP 生命周期加固是综合审查发现后保留在本分支的相邻可靠性修复,不是新的委派用户能力;其产品范围与 027 保持一致。
