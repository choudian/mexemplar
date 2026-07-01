# Feature Specification: 自我改进提案 — 半自动执行复盘改造闭环（B 阶段）

**Feature Branch**: `026-self-improvement-proposals`
**Created**: 2026-06-28
**Status**: Completed
**Input**: User description: "把执行复盘（A，已落地）发现的改进点变成可审批的提案；用户审批+补料后，由任务协作系统自动改源码、跑测试、回报；git 作安全网，合并保持手动。"

## 背景（已亲自读代码核实，非转述）

本特性是「Agent 自我提升」蓝图 ABC 三阶段里的 **B（半自动：人审批、机器实施）**。A 阶段已完成，B 在其上加「审批 + 自动实施」一层。

- **A 阶段（执行复盘·报告制）已真接线并有测试**（commit `f50ce7a`），本特性把它当**只读上游、不改动**：任务完成 → 确定性闸门 → 队列 → 后台 worker 调独立审查员 LLM → 落 `execution_reviews`（v20）→ 只读 API + BrainScreen 复盘视图。审查员产出结构化 findings `{type, what, evidence, severity, suggestion, worth_changing}`，整体 `advisory=true`，且审查员只持有只读工具。
- **B 依赖的任务协作执行内核可被后台程序化驱动（命门已核实通过）**：`GraphScheduler` 是进程级单例（`get_graph_scheduler()`），有幂等踢图入口 `start_graph(graph_id)`；`TaskDispatcher` 带真执行回调、在自有线程池跑（不绑对话回合）；`requires_confirmation` 节点自动暂停等放行；调度器随 orchestrator 创建即装配，后台 worker 随 sidecar 启动。设计上后台触发调度是被支持的用法。

## User Scenarios & Testing *(mandatory)*

### User Story 1 - 看见可执行的改进提案并人工把关 (Priority: P1)

执行复盘跑完后，用户在 BrainScreen 复盘视图里看到由「值得改造」的发现自动生成的**改进提案列表**。用户能逐条阅读（问题、证据、建议、严重度），并对每条做出决定：**批准并补充信息**（"大概改哪里、注意什么"），或**拒绝**。这一步把"看完报告之后无人接手"的空白补上：让用户随时掌握"系统觉得哪里能改"，并由人决定要不要动、怎么动。

**Why this priority**: 这是整条闭环的入口与人把关闸门，也是单独就有价值的最小切片——即使不接自动实施，它已经把复盘结论变成"可分诊、可决策"的待办，让用户看得见、管得住。

**Independent Test**: 在有 `worth_changing` 复盘发现的前提下，确认提案出现在复盘视图、状态正确；批准（带补料文本）与拒绝分别把提案推进到对应状态并持久化；刷新/重连后状态不丢。

**Acceptance Scenarios**:

1. **Given** 一条复盘记录含 `worth_changing=true` 的发现，**When** 复盘落库完成，**Then** 对应生成一条 `pending_review` 提案，展示问题/证据/建议/严重度。
2. **Given** 一条 `pending_review` 提案，**When** 用户填写补料文本并点批准，**Then** 提案转为 `approved` 且补料文本被持久化保留。
3. **Given** 一条 `pending_review` 提案，**When** 用户点拒绝，**Then** 提案转为 `rejected`，不触发任何实施动作。
4. **Given** 同一条复盘发现已生成过提案，**When** 复盘 worker 再次处理，**Then** 不重复生成第二条提案（幂等）。

---

### User Story 2 - 批准后机器自动改源码并回报 (Priority: P2)

用户批准一条提案后，系统**无需用户再操作**就自动把它交给任务协作系统：在一个**独立隔离的工作区**里，由规划专员拆解、执行体真去改源码、再跑测试；完成后把"在哪个分支改的、测试通没通、安全摘要"**回报到该提案**，用户在复盘视图即可看到结果。这把"看完报告之后亲手指挥 AI 改"的体力活自动化了。

**Why this priority**: 这是 B 的核心价值（机器实施），但依赖 P1 的审批动作作为触发，因此排在其后。

**Independent Test**: 批准一条提案 → 确认系统自动产出一个含改动且已跑过测试的隔离分支，且结果（分支名 + 测试通过与否 + 摘要）被回写到提案行，全程除"批准"外无需人工介入。

**Acceptance Scenarios**:

1. **Given** 一条 `approved` 提案，**When** 桥接触发，**Then** 创建一个独立工作区与特性分支，提案转 `in_progress` 并记录分支/工作区引用。
2. **Given** 实施任务图被建好，**When** 桥接踢起调度，**Then** 规划专员与执行体在该隔离工作区内推进改造并在其中跑测试，正在运行的应用文件不受影响。
3. **Given** 实施任务图完成，**When** 结果回流，**Then** 提案转 `done`，并记录分支名、测试通过与否、安全摘要供用户查看。
4. **Given** 实施任务图整体失败或测试不通过，**When** 结果回流，**Then** 提案转 `failed` 并展示安全失败摘要；不自动合并、不污染主工作区。
5. **Given** 触发桥接时调度器单例尚未装配，**When** 桥接尝试踢图，**Then** 优雅处理（确保装配后再踢或推迟），不静默丢任务、不报错崩溃。

---

### User Story 3 - 隔离与可回滚的安全保证 (Priority: P3)

每一次自动改造都被关在独立工作区里、只允许改源码、合并由用户手动完成、随时可凭 git 干净回滚。用户即使放手让机器改自己的系统，也始终握着"撤销那根杆子"。

**Why this priority**: 这是让用户敢用 B 的前提；它是贯穿性安全保证，可独立验证，但本身不产生新用户操作面，故置于 P3。

**Independent Test**: 用门卫测试验证执行体无法改非源码（DB/外部副作用 fail-closed）；拒绝或失败后主工作区无残留；任意一次改造可凭 git 删分支/弃工作区干净撤销；正在运行的应用在改造期间不被扰动。

**Acceptance Scenarios**:

1. **Given** 一次进行中的自动改造，**When** 执行体尝试修改非源码（数据库、外部服务、git 工作区之外的文件），**Then** 该动作被 fail-closed 阻断。
2. **Given** 一条改造产生的分支，**When** 用户决定不要，**Then** 删分支 / 弃工作区即可干净撤销，无需数据库或外部清理。
3. **Given** 一次自动改造正在独立工作区进行，**When** 用户继续正常使用应用，**Then** 正在运行的应用不被改动文件干扰（生效需显式合并 + 重启）。

### Edge Cases

- 复盘发现 `worth_changing=true` 但 `suggestion` 为空/含糊 → 仍生成提案，把"建议不足"如实展示给用户由其补料。
- A 阶段被关闭或某次任务无复盘 → 不产生提案，界面优雅空态，不报错。
- 同一会话短时间产生多条提案并被分别批准 → 各自独立工作区/分支；实施按 FR-018 串行（一次一条 in_progress），其余排队，互不碰撞、不争用执行容量。
- 桥接建工作区时目标路径已存在（上次残留）→ 拒绝复用脏工作区，按失败处理并提示，不静默覆盖。
- 实施任务图卡住/执行体崩溃 → 复用任务协作既有恢复语义（lease 围栏/恢复扫描）；最终仍无法推进则提案标 `failed`。
- 提案已 `approved` 但桥接建图失败 → 提案转 `failed`，记录安全原因，不留半截在 `in_progress`。
- 用户对同一提案重复点批准 → 幂等，不重复建工作区/任务图。
- 多条提案先后批准 → 串行实施（FR-018）；某条合并后，后续提案分支基线变旧 → 合并前提示用户 rebase/重建，避免回带已修问题或冲突。
- 用户主工作树有未提交改动 → 自我改造基线是 HEAD commit、不含这些未提交改动（见 Assumptions），界面/文档需说明以免困惑。

## Requirements *(mandatory)*

### Functional Requirements

**提案产生与生命周期**

- **FR-001**: 系统 MUST 在某条执行复盘落库后，为其中每个 `worth_changing=true` 的发现生成一条改进提案；同一发现 MUST 幂等，不重复生成。
- **FR-001a**: 系统 MUST 抑制**跨复盘的同类提案堆积**——系统性低效（如"重复抓取"）会在多次任务的复盘里被反复报出，若每次都新建提案会淹没界面、造成审批疲劳。同类发现 MUST 走去重/合并或冷却窗口，不每条复盘各生一条近重复提案。
- **FR-002**: 每条提案 MUST 关联其来源复盘记录，并保留可展示的问题描述、证据、建议、严重度。
- **FR-003**: 提案 MUST 有明确生命周期：`pending_review → approved → in_progress → done | failed`，以及从 `pending_review` 直接到 `rejected`；状态流转 MUST 持久化。
- **FR-004**: 提案生成 MUST NOT 改变 A 阶段执行复盘的存储、产出或只读语义（A 只读、不动）。

**审批与补料**

- **FR-005**: 用户 MUST 能在 BrainScreen 复盘视图内查看提案列表并逐条阅读详情，不新增独立主屏。
- **FR-006**: 用户 MUST 能批准一条提案，并可附带**补料文本**（改造方向/注意事项）；补料文本 MUST 被持久化并传递给后续实施。
- **FR-007**: 用户 MUST 能拒绝一条提案；拒绝 MUST NOT 触发任何实施动作或副作用。
- **FR-008**: 在用户批准之前，系统 MUST NOT 对任何提案发起实施或产生不可逆副作用（advisory-only 直到人点头）。

**桥接与自动实施**

- **FR-009**: 批准一条提案后，系统 MUST 无需用户进一步操作即把它交给任务协作系统实施。
- **FR-010**: 实施 MUST 在一个**独立隔离的 git 工作区 + 特性分支**内进行（一提案一工作区）；提案 MUST 记录该工作区路径与分支名。
- **FR-011**: 系统 MUST 程序化构建实施任务图（规划专员只规划、执行体改源码并跑测试）并经进程级调度器单例踢起推进；当调度器尚未装配时 MUST 优雅处理（确保装配后再踢或推迟），不静默丢任务。
- **FR-012**: 实施任务图完成后，系统 MUST 把结果（分支名、测试通过与否、安全摘要）回写到对应提案并使其在复盘视图可见。
- **FR-013**: 实施整体失败或测试不通过时，提案 MUST 转 `failed` 并展示安全失败摘要；MUST NOT 自动合并、MUST NOT 污染主工作区。

**安全与回滚**

- **FR-014**: 执行体的自动改造 MUST 被焊死在以下爆炸半径内（三条各由门卫测试守住）：
  - **(a) 文件改动**：MUST 只发生在该提案的隔离工作区内的 git 源码文件；对工作区之外文件、数据库文件、外部服务的修改 MUST fail-closed 阻断。
  - **(b) exec 能力**：跑测试所需的 `exec` MUST 限定在工作区内的测试型用途；网络型 / 破坏型 exec MUST 被阻断（"只改源码"不等于"可任意 exec"）。
  - **(c) 禁改自我改进核心**：执行体 MUST NOT 修改自我改进子系统自身（提案生成/桥接/审查员/调度内核）与应用启动核心路径——防止一次坏改造砖掉"改自己的能力"或启动，形成递归砖化/坏提案反馈环。
- **FR-015**: 合并到主分支 MUST 保持用户手动完成；系统第一版 MUST NOT 自动合并或自动重启使改动生效。
- **FR-016**: 任意一次自动改造 MUST 可凭 git（删分支 / 弃工作区）干净回滚，不依赖数据库或外部清理；拒绝/失败后主工作区 MUST 无残留污染。
- **FR-017**: 自动改造进行期间 MUST NOT 扰动正在运行的应用所用文件（生效显式经合并 + 重启）。

**运行与运维**

- **FR-018**: 系统 MUST 串行化自我改造实施（同一时刻至多一条提案在实施），避免多条改造争用执行容量并降低跨提案合并冲突；后批准的提案排队等前一条进终态。
- **FR-019**: 系统 MUST 对保留的实施工作区设回收策略（保留上限或显式清理入口），避免失败/完成的 worktree 长期堆积占盘。
- **FR-020**: 当存在 `pending_review` 提案时，系统 MUST 给用户一个可发现的待审提示（如非模态 toast / 计数徽标），不让提案静悄悄躺在管理屏无人知。

### Key Entities *(include if feature involves data)*

- **改进提案（Improvement Proposal）**: 一条可执行的改造请求。关键属性：来源复盘引用、问题/证据/建议/严重度快照、状态（pending_review/approved/in_progress/done/failed/rejected）、用户补料文本、关联实施任务图引用、关联工作区路径与分支名、结果回报（测试通过与否 + 安全摘要）、时间戳。与「执行复盘记录」一对多（一条复盘的多个发现各成一条提案）。
- **执行复盘记录（Execution Review）**: A 阶段既有实体，本特性只读引用，不改其结构。

### Constraints & Compatibility *(include when relevant)*

- **CC-001**: 严格分层——UI → typed API → business service → repository；UI MUST NOT 直连数据层；提案数据 MUST 走新增 Repository，不在业务代码裸写 SQL。
- **CC-002**: 面向前端的事件 MUST 先在 UI Event Registry（`src/desktop_api/ui_events.py`）注册再消费；缺口/会话不匹配走 `backend.resync_required` 拉权威快照；MUST NOT 用内部事件名做前端展示决策。
- **CC-003**: 配置 MUST 走 `get_unified_config()`；MUST NOT 硬编码；secret MUST NOT 进入普通日志、明文 DTO 或前端持久化状态；实施失败的 provider 原始错误 MUST NOT 进入安全失败摘要（只暴露安全投影）。
- **CC-004**: A 阶段 `execution_reviews` 表、审查员逻辑/模型、advisory 语义 MUST 保持不变（回归边界）。
- **CC-005**: 任务协作系统（调度器单例、dispatcher、任务图、`requires_confirmation`、worktree 惯例）MUST 整体复用，MUST NOT 另起一套平行执行流水线。
- **CC-006**: 系统提示词与工具 MUST 走"直接改源码 + git"路径，本特性 MUST NOT 把提示词/工具数据化进数据库。
- **CC-007**: 本特性 MUST 停在 B（人批准、人合并）；MUST NOT 引入机器自动判定改得好不好并自批自改（C 阶段）。
- **CC-008**: 改静默失败 / 编排 / 事件 / Repository / 恢复路径 MUST 补行为契约测试；FR-014 的三条爆炸半径硬边界（文件 / exec / 禁改自我改进核心）MUST 各由架构门卫测试守住。
- **CC-009**: 提案对 finding 的 `what/evidence` 快照展示 MUST NOT 比 A 阶段已暴露的执行 trace 投影泄漏更多敏感内容；持久化与 UI 展示沿用 A 的脱敏边界。

## Architecture Impact *(Mexemplar-specific)*

### Layer Impact

- [x] **UI** (`frontend/src/`) — BrainScreen 复盘视图扩展（提案列表 + 批准/补料/拒绝交互）、brainStore、executionReview API client 扩展。
- [x] **Desktop API Bridge** (`src/desktop_api/`) — 提案的 typed API（列表 / 批准+补料 / 拒绝）、UI Event Registry 注册新公开事件、提案状态变更事件。
- [x] **Business** (`src/business/`) — 提案生成（挂在复盘 worker 写回后旁路）、提案→任务桥接 service（建工作区 + 建任务图 + 踢调度器 + 回报）、执行体"只改源码"约束。
- [x] **Data** (`src/data/`) — 新增 `improvement_proposals` 表 + 新 migration 版本 + ProposalRepository；可能新增配置占位（如自动改造开关）。
- [x] **Execution / Recording / Utils** — Recording 无语义改动；Utils 新增 self-improvement proposal 状态变更 blinker 事件；执行体侧 workspace 边界校验收口在 business/内建工具权限交界（见 FR-014）。

### Agent Impact

- 受影响 Agent：proposal 任务图中的规划节点（只读/搜索能力）+ 执行与测试节点（delegated executor / programmer，改源码并跑测试）；主助理与 A 的审查员不变。
- 新增/修改工具：执行体侧需要"只改源码 + 限定工作区"的能力边界（workspace policy / 门卫），不新增对外业务工具。
- 系统提示词：实施任务的输入需带提案上下文 + 用户补料；不改主助理或审查员系统提示词骨架。
- Orchestrator dispatch：复用既有 `get_graph_scheduler().start_graph()`；新增的是"后台桥接 → 建图 → 踢图"的调用方，不改调度器内核。

### Data Store Impact

- **SQLite** (`src/data/repos/`): 新增 `improvement_proposals` 表（状态 + 补料 + 来源复盘外键 + 任务图/工作区/分支引用 + 结果回报）+ 新 migration 版本（在 v20 之后）+ `ImprovementProposalRepository`（soft 状态流转，CAS 条件更新避免并发丢更新）。
- **Config** (`src/data/unified_config.py`): 可能新增 `self_improvement.proposals.*` 开关/参数占位（如自动改造启用、并发上限），走统一配置三处同步。
- **Secrets**: 无新增敏感字段；实施失败原始错误不入安全摘要。

### Event Impact

- 新增公开 UI 事件（先在 `ui_events.py` 注册）：提案生成 / 状态变更（approved / in_progress / done / failed / rejected）以便复盘视图实时刷新；payload 走安全 allowlist，缺口走 `backend.resync_required`。
- 后端内部跨模块通知优先 blinker；面向前端经 UI Event Registry typed envelope。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 当一次执行复盘产出 `worth_changing` 发现，用户能在复盘视图的一处看到对应提案，并完成"批准+补料"或"拒绝"，状态正确持久化、刷新/重连不丢。
- **SC-002**: 用户批准一条提案后，除"批准"外**无需任何人工操作**，系统即自动产出一个含改动且已在隔离工作区跑过测试的分支，并把"分支名 + 测试通过与否 + 安全摘要"回写到该提案。
- **SC-003**: 一次自动改造的全部文件改动 100% 限制在 git 跟踪源码内且位于独立工作区；执行体对非源码（DB/外部/工作区外）的修改、网络/破坏型 exec、以及对自我改进核心与启动路径的修改尝试，均被 100% fail-closed 阻断（FR-014 三条门卫测试可证）。
- **SC-004**: 任意一次自动改造可凭 git 删分支/弃工作区在不动数据库与外部资源的前提下干净回滚；拒绝/失败后主工作区零残留。
- **SC-005**: A 阶段执行复盘的触发、产出 findings 结构、只读 API 与 advisory 语义在本特性前后保持一致（回归通过）。
- **SC-006**: 全程不发生"提案能批但实施无人推进"的断链（命门回归）：批准后任务图被真实推进至终态并回报。

## Assumptions

- **目标用户**：单用户、未发布、无外部消费者；spec 不预留 deprecation/双发兼容。
- **提案产生粒度**：默认每条 `worth_changing=true` 发现都生成提案，由用户用"拒绝"过滤噪声；不按严重度预筛（噪声若过多再迭代加阈值）。
- **审批即单道闸门**：用户在提案阶段批准即为唯一人工闸门；实施任务图默认不再叠加 `requires_confirmation` 二次确认（git + 手动合并是后置安全网）。失败/测试不过的工作区默认**保留**供用户检视，仅"拒绝"路径清理。
- **合并与生效**：第一版合并由用户手动 git 操作完成，改动生效需重启应用；应用层（一键合并 + 自动重启）留待后续。
- **调度器可达性**：B 的触发发生在"任务完成之后"，此时 orchestrator 必已创建、调度器单例必已装配；桥接仍对未装配情形兜底（FR-011）。
- **隔离机制**：采用 git worktree 作为"一提案一隔离工作区"的实现；执行体 workspace 指向该工作区。**该 workspace 重定向是整套隔离/回滚安全模型的承重假设，实现期 MUST 先以 spike 验证可行性（见 plan 的 phasing）再建桥接其余部分。**
- **改造基线**：worktree 从当前 HEAD commit 创建，**不含**主工作树的未提交改动；自我改造看到的是最近提交的代码。
- **闭环测试策略**：命门回归（端到端）测试 MUST mock 执行体/LLM，确定性断言"建图→踢图→状态机→回报"接线，不依赖真实 LLM 跑改码（避免慢与 flaky）。
- **提案去重**：跨复盘同类发现走去重/冷却（FR-001a），不每条复盘各生近重复提案。
- **复用底座**：任务协作执行内核、9115e0a 休眠的 `self_improvement` 审计/度量底座作为现成地基复用，不推翻。
- **范围红线**：不做 C 阶段自动 eval/自批自改；不把提示词/工具数据化进 DB（用户已明确否决）。
