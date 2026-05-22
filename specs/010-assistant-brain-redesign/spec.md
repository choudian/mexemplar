# Feature Specification: Assistant Brain Redesign

**Feature Branch**: `010-assistant-brain-redesign`
**Created**: 2026-05-20
**Status**: Completed
**Input**: User description: "基于 docs/design/assistant_agent_redesign_draft.md 和 docs/design/assistant_brain_implementation_design.md 这两份设计稿，为主助理 Agent（大脑架构）重新设计创建 feature specification"
**Critique Fix**: 2026-05-20 — Applied E11/E10/E12/E13/P7/X3 to align persistent-zone phase ownership, phase-specific distillation, prediction generation, dispatch measurement, and existing skills/compositions UI boundaries.

## User Scenarios & Testing *(mandatory)*

主助理（assistant）当前是"单 Agent + 单段记忆摘要"的被动记事本。本功能把它重构为一个"有大脑的人"：它有 6 个认知分区（热区 / 持久区 / 归档区 / 潜意识区 / 失败区 / 猜测区），会在后台自动沉淀、衰减、复审记忆；同时它的工作方式从"自己完成所有事"转变为"100% 调度"——永远把具体执行派给临时执行体或固定专员。下面 5 个用户故事按交付优先级排列，每个都是一个可独立交付、可独立验证的增量切片。

### User Story 1 - 跨对话延续的工作记忆 (Priority: P1)

作为日常用主助理办公的用户，我希望主助理记得我最近在做什么、最近聊出的领悟，这样我下次打开对话时不必从头解释背景。

**Why this priority**: 这是"大脑"的地基。没有跨对话延续的记忆，主助理就只是一个无状态的记事本；其余所有分区、调度和专员能力都建立在"主助理能感知自己最近的脉络"之上。单独交付它本身就是可用的 MVP——主助理从"每次重新认识你"变成"记得你"。

**Independent Test**: 用户就某个话题聊一段，关闭对话窗口，等待一段时间后重新打开对话；主助理在新对话里能引用上一段的脉络（在做什么 / 聊出的领悟），用户无需复述背景。

**Acceptance Scenarios**:

1. **Given** 用户首次使用、大脑各分区为空，**When** 用户打开对话，**Then** 主助理走破冰路径：自我介绍并自然地问 1-2 个最核心问题，不是表单、不展开成问卷。
2. **Given** 用户就某话题聊了一段并关闭窗口，**When** 经过静默防抖期，**Then** 这一段对话被封存并触发一次沉淀分析，把"发生的事"写入热区；若该段包含永久事实、稳定领悟或破冰答案，则同步写入持久区。
3. **Given** 上一段对话已沉淀，**When** 用户重新打开对话，**Then** 主助理能在不被复述的情况下引用最近脉络。
4. **Given** 用户关闭窗口后在防抖期内又回到同一对话继续聊，**When** 用户发出新消息，**Then** 该段不被提前封存，继续作为同一连续片段。
5. **Given** 某段对话已沉淀，**When** 用户几周后复活同一会话继续聊，**Then** 已沉淀的旧记忆不被撤销，新增量作为独立片段再次沉淀。

---

### User Story 2 - 永久身份与可回溯的历史档案 (Priority: P2)

作为长期使用主助理的用户，我希望主助理稳定地知道关于我的永久事实（家人、核心身份、长期经验），并且当我提起几周甚至几个月前的事情时，它能回查到。

**Why this priority**: 工作记忆（热区）会随生活脉络衰减；用户还需要一层不衰减的永久身份，以及一个能下钻到任意历史时点的档案。这层让主助理从"记得最近"升级到"了解你是谁、记得你的过去"。它独立可交付：吸收现有用户画像 + 历史回查本身就是完整价值。

**Independent Test**: 现有用户画像（称呼 / 风格 / 备注，已由 P1 v11 migration 回填为持久区事实）可在持久区被查看或被上下文注入引用；用户在对话里提到一件旧事，主助理通过检索归档区给出对应的历史摘要。

**Acceptance Scenarios**:

1. **Given** 用户此前已有 assistant 画像数据且 P1 v11 migration 已执行，**When** 大脑系统启用，**Then** 画像内容（称呼 / 风格 / 备注）作为持久区事实条目出现。
2. **Given** 主助理积累了稳定的长期经验，**When** 主助理处理新任务，**Then** 它能参考持久区的经验类条目。
3. **Given** 用户提到"上个月那次讨论"，**When** 主助理需要历史上下文，**Then** 它能从归档区按时间轴或主题轴检索到对应摘要。
4. **Given** 归档区已积累多段对话，**When** 周期性归档工作运行，**Then** 单元摘要被递进聚合为日 / 周 / 月 / 年和主题层级。

---

### User Story 3 - 100% 调度与可复用专员 (Priority: P3)

作为给主助理安排工作的用户，我希望主助理像项目经理一样，永远把具体执行派出去（哪怕是简单任务），并且我能让它把反复出现的同类工作固化成一个有名字的专员。

**Why this priority**: 这是主助理工作方式的根本转变——从"自己干所有事"变成"100% 调度"。它依赖前两层提供的记忆上下文来做派发决策，所以排在 P3。独立可交付：调度行为 + 用户主动招专员本身就是一个完整、可演示的能力切片。

**Independent Test**: 用户安排一个任务，主助理派给临时执行体而不是自己内联执行；用户说"帮我建一个 XX 专员"，主助理创建专员，之后再派同类任务时复用该专员。

**Acceptance Scenarios**:

1. **Given** 用户安排一个任务（含简单任务），**When** 主助理处理它，**Then** 主助理把任务派给临时执行体或固定专员，自身不直接执行。
2. **Given** 用户在对话里要求创建一个专员，**When** 主助理处理该请求，**Then** 一个带名字、描述、角色定义、工具白名单和 reason 的专员被直接创建。
3. **Given** 已存在一个固定专员，**When** 用户安排该专员擅长的任务，**Then** 主助理把任务派给该专员。
4. **Given** 主助理派出一个任务，**When** 执行体返回结果，**Then** 主助理汇总结果再回复用户。
5. **Given** 用户安排任务，**When** 主助理选择执行体，**Then** 它不调度 PM / Programmer / Trial 这三个录制流水线 Agent。

---

### User Story 4 - 避坑、人格感知与自我校准 (Priority: P4)

作为依赖主助理做判断的用户，我希望它能在决策类任务前回想过去的失败教训，能逐渐理解我难以直说的偏好与反感，并对"我接下来可能做什么"形成可验证的预测来自我校准。

**Why this priority**: 这一层让大脑从"记录与调度"升级为"有判断力、有人格、会自省"。失败区、潜意识区、猜测区都是在前面三层稳定后才有意义的高阶认知。独立可交付：决策避坑 + 人格沉淀 + 猜测验证三者构成一个清晰的"更聪明的主助理"切片。

**Independent Test**: 给主助理一个决策类任务，它先检索失败区；让系统运行一个猜测周期，能看到生成的可验证猜测条目，并在周期过后自动得到验证状态。

**Acceptance Scenarios**:

1. **Given** 失败区已有带场景范围的教训，**When** 主助理面对一个决策类任务，**Then** 它主动检索失败区以避免重蹈覆辙。
2. **Given** 用户的多段对话累积出隐性特质，**When** 周期性潜意识沉淀运行，**Then** 潜意识区出现偏好 / 价值观 / 风格 / 反感类条目，并标注为"参考性"。
3. **Given** 用户的人格随时间变化，**When** 出现与旧潜意识条目冲突的新观察，**Then** 旧条目可被新条目覆盖且保留历史。
4. **Given** 一个猜测周期开始，**When** 猜测生成工作运行，**Then** 系统产出关于"用户接下来可能做什么"的可验证预测条目。
5. **Given** 一个猜测条目到达验证时点，**When** 猜测验证工作运行，**Then** 该条目得到 hit / miss / partial / expired 等明确状态。
6. **Given** 猜测区存在预测条目，**When** 主助理构建工作上下文，**Then** 猜测内容不进入主助理可见范围，仅用于系统自我校准和用户在管理界面查看。

---

### User Story 5 - 自动招人与大脑管理模块 (Priority: P5)

作为想主动管理主助理的用户，我希望系统能在发现我反复派同类活时自动帮我固化出专员，并且我有一个专门的"大脑管理模块"可以查看、编辑、删除大脑里的任何内容。

**Why this priority**: 这一层把"自动化产物对用户透明可控"这一交互原则完整落地，并补齐 HR 自动招人闭环。它建立在前面所有分区和专员能力之上，是收尾层。独立可交付：自动招人 + 大脑管理界面构成"用户对大脑的完全可见与可控"。

**Independent Test**: 让系统观察一段时间的派发模式后自动生成一个带 reason 的专员；打开大脑管理模块，能查看 / 编辑 / 删除 6 个分区的条目以及专员和技能池。

**Acceptance Scenarios**:

1. **Given** 用户在一段时间内反复派同一类任务，**When** HR 招人扫描运行，**Then** 系统直接生成一个对应专员（不走"提案 + 确认"），并附带可追溯的 reason。
2. **Given** 大脑各分区有数据，**When** 用户打开大脑管理模块，**Then** 用户能看到 6 个分区的条目，每个自动产物都附带 reason 一起展示（默认不折叠）。
3. **Given** 用户在管理模块查看某个自动产物，**When** 用户修改或删除它，**Then** 修改 / 删除被当作反馈信号消费，且不弹出任何"是否要…"确认。
4. **Given** 用户在管理模块，**When** 用户调整某专员的技能白名单，**Then** 该调整直接生效，无需经过主助理。
5. **Given** 大脑管理模块存在，**When** 用户日常使用主助理，**Then** 大脑管理模块与对话界面并列，用户不必为日常工作进入管理模块。

### Edge Cases

- 大脑各分区全空（冷启动）：主助理走破冰路径，只问 1-2 个最核心问题，绝不展开成问卷，也不弹任何 onboarding 引导。
- Segment 强制切：当对话消息量 / token 触达上限，该段被立即封存（不走防抖期），沉淀照常触发。
- 沉淀分析失败：当沉淀的结构化输出不合法（schema 不符），系统重试；超过重试上限后 Segment 状态置为 `failed`（不产生任何 Memory Entry），在管理界面以"沉淀失败，可手动重试"显示，不静默丢弃；用户触发重试后状态回到 `pending`。
- 应用崩溃后的 Segment 恢复：应用启动时，若发现任何 Segment 处于 `distilling` 状态（即上次运行时沉淀进行中发生了崩溃），系统 MUST 将其重置回 `pending` 状态，重试计数器不变；崩溃属于基础设施失败，不计入内容质量重试配额；重置后由 background worker 按正常流程重新触发沉淀。
- 进行中（`open` 态）Segment 的崩溃恢复：`open` 态 Segment 不持久化为数据库行，而是由对话消息中尚未被任何已封存 Segment 覆盖的部分隐式推导。应用被非优雅终止（进程被杀、断电，既未触发 window close 也未触发 idle）时，进行中的会话增量不会丢失——它没有易失的内存状态；下一次会话边界（`new_session` 等）会把这段未覆盖的消息正常封存为 `pending` Segment 并触发沉淀。`brain_segments` 行只在 Segment 封存时创建。
- 复活推翻型：用户复活旧会话并推翻了之前的结论，旧记忆不被物理撤销，而是产生失效信号、被标记为已被覆盖。
- 检索无 active 结果：当检索某分区没有有效条目，系统仍返回已失效条目并标注失效系数，而不是返回空。
- 记忆冲突：当明确事实与推测性条目冲突，以事实优先；当两条记忆适用场景（scope）不同，二者共存。
- 临时执行体的对话：临时 subagent 的会话内容不进入归档与沉淀分析。
- 历史会话迁移：大脑系统启用前的既有会话不被自动批量沉淀（避免瞬间堆积大量分析），仅以最底层档案形式可检索，用户可按需手动触发补沉淀。
- 用户沉默：用户对某个自动产物既不修改也不删除，这种沉默不计入正向或反向任何信号，系统也不主动追问。
- 专员工具越权：专员的工具白名单不能超出主助理当前技能池的范围。
- 潜意识误判：用户在管理界面删除一条潜意识条目，该删除被作为"判断偏了"的纠偏信号消费，后续沉淀把它当反例输入。

## Clarifications

### Session 2026-05-20

- Q: 大脑数据（热区、潜意识区、持久区）是否需要静态加密？ → A: 不额外加密，依赖 OS 文件系统 & 现有 SQLite 安全边界，与现有消息历史保持一致；若将来出现合规要求则单独处理。
- Q: 大脑上下文应在何时重建并注入 assistant 提示词？ → A: 每次 assistant 运行准备 prompt 时在后台工作线程同步全量构建一次；zone/specialist 变更事件（blinker）通知前端刷新管理界面，并使下一次 assistant 运行自然读取最新数据；Segment 边界后的新沉淀条目通过同一构建路径进入热区上下文。
- Q: P1 数据 schema 交付范围：一次性建全 6 个分区还是按 phase 增量建表？ → A: P1 一次性建全所有分区 schema（含支撑表），后续 phase 只激活业务逻辑，不再新增 migration。
- Q: 从技能池移除工具时，已引用该工具的专员白名单如何处理？ → A: 两步策略：先阻断并展示受影响专员列表；若用户确认强制移除，则自动从所有专员白名单中裁剪该工具。
- Q: 大脑管理模块以何种形态集成到前端 UI？ → A: 新增顶层路由页面（如 /brain），与对话页面并列在导航栏切换，不引入新 Tauri 窗口。
- Q: Memory Entry 的 status 字段合法枚举值是什么？ → A: `active / fading / invalidated / soft-deleted / distillation-failed`，覆盖热区衰减、失效信号、管理界面软删和沉淀失败四个场景。
- Q: "prolonged idle" Segment 边界由谁检测？ → A: 前端检测（UI 不活跃计时器），到达阈值后向后端发送 `segment_idle_trigger` 事件；后端 background worker 只响应事件，不自行轮询。
- Q: 热区衰减由什么机制驱动？ → A: 沉淀触发 + 周期兜底：每次 Segment 沉淀写入后触发全热区重评分；background worker 按周期扫描长期未更新的条目作为兜底。
- Q: 沉淀分析失败的条目在管理界面放哪里？ → A: 失败时不产生 Memory Entry，Segment 本身保持"待沉淀"状态；`distillation-failed` 是 Segment 的状态，不是 Memory Entry 的状态。Memory Entry 状态枚举移除该值。
- Q: 助理在何种条件下可以主动失效记忆条目？ → A: 被动（用户明确要求）+ 主动（助理检测到明显事实冲突）均允许；主动失效时助理必须在当轮回复中向用户说明。
- Q: 是否在 Memory Entry 元数据中加入效果追踪字段？ → A: 是，加入 `loaded_count`（注入次数）和 `referenced_count`（LLM 实际引用次数），effectiveness = referenced/loaded 用于驱动检索降权。
- Q: 是否需要专门的多分区 token 压缩策略（如 LLM profile 编译）？ → A: 不需要。衰减机制自然控制分区条目规模，大脑分区的 token 占用不会暴涨；context 过长时走现有对话消息压缩，不额外处理大脑分区。
- Q: 是否需要在 Memory Entry 上加入 supersedes 演化链字段？ → A: 是，加入 `superseded_by: entry_id?`（可空外键），新条目写入时同步填充被替代条目的该字段，形成可在管理界面追溯的演化链。
- Q: 沉淀分析的 LLM 调用架构是单次还是多次顺序调用？ → A: 单次结构化 LLM 调用，输出涵盖当前 phase 已激活写入分区的结构化 JSON；整体失败则整体重试，不做分区级部分重试。`distillation_output` schema 按 phase 裁剪：P1 要求 `hot_zone` + `persistent_zone`，P2 追加归档区写入，P4 追加 `subconscious_zone` + `failure_zone`；未激活分区不请求、不持久化，避免为会被丢弃的结果付 LLM 成本。猜测区不由 Segment 沉淀工具生成，而由周期性 prediction generation worker 生成。
- Q: `referenced_count` 如何计量——额外 LLM 调用、启发式打分，还是助理显式引用？ → A: 助理回复附带结构化元数据字段 `memory_entries_referenced: [entry_id, …]`；后端读取该字段后批量更新对应条目的 `referenced_count`，无需额外 LLM 调用。
- Q: 助理主动检索归档区 / 失败区的触发机制是显式工具调用还是后端自动注入？ → A: 显式工具调用——提供 `retrieve_archive(query)` 和 `retrieve_failure_zone(context)` 等工具，助理在判断需要时主动调用；后端不做静默自动注入。
- Q: 大脑上下文注入的选取策略——统一排序注入、全量截断，还是分层策略？ → A: 分层策略：持久区全量注入所有 active 条目（条目少且是用户身份核心）；热区和潜意识区各自选 top-N 注入，排序采用复合评分而非单一效果比：热区主排序键为 `relevance_score`（新近度兜底），潜意识区主排序键为新近度，效果比（`referenced_count/loaded_count`）仅作为附加加权项叠加；`loaded_count` 较低的新条目获得探索配额，避免从未被注入的高价值条目被永久饿死。该复合排序自 P1 起即可观察、可验证——`referenced_count` 计量随 `reply_to_user` 工具在 P3 到位，在此之前效果比项对所有条目恒为零，复合评分自然退化为 relevance/新近度排序；具体 N 值为占位符，待实测调整（符合 CC-008）。
- Q: 自动招募专员后如何通知用户，以及专员管理的 UI 形态？ → A: 非模态 toast 通知（含专员名 + reason，点击可跳转）；专员管理作为独立的专员管理页面模块（独立路由，如 `/brain/specialists` 或与 `/brain` 并列），用户可在该页面直接查看、编辑、删除专员及调整技能白名单，不局限于大脑分区条目的内嵌面板。
- Q: 沉淀 LLM 输出"有效"的判断标准是什么？ → A: 仅验证结构合法性——JSON schema 匹配、所有必填分区字段存在且类型正确；允许任意分区的条目列表为空。内容语义不作为合法性判断依据，避免假重试循环。
- Q: 会话启动时大脑上下文以同步阻塞还是异步方式加载？ → A: 异步非阻塞——会话页面立即开放输入；上下文在后台构建；助理在生成首轮回复前等待上下文就绪（用户感知上不被阻塞，但首轮回复不会在上下文缺失情况下发出）。
- Q: 助理输出中 `memory_entries_referenced` 字段缺失或格式错误时如何处理？ → A: 静默跳过——本轮不更新任何条目的 `referenced_count`，对话正常继续，不报错不重试；`referenced_count` 是辅助降权信号，偶发缺失不影响核心功能。
- Q: 沉淀结果所有请求分区条目全为空时（例如纯闲聊段），Segment 状态如何处置？ → A: 触发一次额外重试（即使是轻量对话，也通常应能在当前 phase 已激活分区里提取到某种可用信号；零条目是提取不力的信号，值得重试一次）；重试仍全空则置 `completed` 接受结果，不进入死循环。
- Q: 猜测区预测条目的验证（hit/miss/partial/expired）由谁执行？ → A: 后台 worker 自动验证——到达验证时间点后，worker 发起 LLM 评估，对比预测文本与该时段内已沉淀的记忆条目，自动写入结论；不需要用户手动确认，不在助理会话中顺带处理。
- Q: Segment 重试耗尽后的终态是 `failed`（独立枚举）还是继续保持 `pending`？ → A: `failed` 是独立枚举状态，在管理界面显示为"沉淀失败，可手动重试"；用户触发重试后状态回到 `pending` 再进入 `distilling`；`pending` 专指"封存但尚未开始沉淀"，与失败态明确区分。
- Q: 助理记忆失效工具的作用域——当前上下文条目、仅被动可见区，还是任意 ID？ → A: 仅限当前上下文中出现过的条目（被动注入的热 / 持久 / 潜意识区条目，或通过 `retrieve_*` 工具本次取回的归档 / 失败区条目）；若要失效归档区某条旧记忆，助理须先显式检索到该条目，再调用失效工具。
- Q: 猜测验证结果只存状态还是同时存验证理由文本？ → A: 状态 + 验证理由文本——后台 worker LLM 评估时同时输出一句理由，写入条目专用字段，在管理界面与验证状态一起展示；不存置信分数。
- Q: 预测验证 worker 本身失败（LLM 调用超时 / API 错误）时如何处理？ → A: 有限次重试（次数为可配置占位符，符合 CC-008）；超出重试上限后条目状态置为 `expired`，验证理由字段注明"验证调用失败，无法核实"；与沉淀重试逻辑保持一致。
- Q: "100% 调度"规则的边界——纯对话性回复是否也需要派发？ → A: 任务 = 需要工具调用、外部操作或多步执行的请求，须派给执行体；问候、记忆查询（从注入上下文直接回答）、简短澄清等纯对话性交流由助理直接回复，不经过派发；SC-002 采用带人工标注任务样本的试验比例度量，不含纯对话性交流。
- Q: 用户在管理界面"编辑"记忆条目时，是原地更新还是生成新的替代条目？ → A: 生成新的替代条目——编辑产生一个新条目（含更新后内容），通过 `superseded_by` 链替代旧条目（类似批注 / 追踪修改：保留原文、记录改了什么、改成什么）；`superseded_by` 链同时覆盖系统产生的认知演化和用户主动批注两种场景，管理界面可展示完整演化链。旧条目状态置为 `soft-deleted`，内容永久保留。
- Q: 应用重启时发现 Segment 处于 `distilling` 状态（崩溃遗留），如何恢复？ → A: 启动时扫描并重置所有 `distilling` Segment 回 `pending`，重试计数器不变；崩溃属于基础设施失败，不计入内容质量重试配额，由 worker 正常调度重新沉淀。
- Q: 多个 Segment 边界事件几乎同时触发时，如何保证每个 Segment 只沉淀一次？ → A: DB 级原子转换——`pending → distilling` 在事务内以 compare-and-swap 或行锁完成；并发的第二个事件到达时 Segment 状态已不是 `pending`，转换被拒绝，事件静默丢弃；无需额外应用层去重。
- Q: 用户删除 / 编辑产生的反馈信号如何被"消费"？ → A: 主动注入——信号按分区和操作类型存入 `feedback_signals` 表；未来的沉淀 / 招募扫描 LLM 调用从中加载近期相关信号，作为"这类提取之前被用户否定 / 修正"的提示词上下文追加到提示词中；需要专门的 `feedback_signals` 表设计。
- Q: 热区条目的"事件类"与"洞察类"如何区分，衰减路由如何按类型分流？ → A: 显式 `entry_type` 字段（枚举：`event` / `insight`）；沉淀 LLM 在创建热区条目时赋值；衰减路由器读取该字段：`event` → 归档区，`insight` → 持久区或退役。

## Requirements *(mandatory)*

### Functional Requirements

#### Dispatch & Executors

- **FR-001**: System MUST route every user task — including simple tasks — to a separate executor; the assistant MUST NOT execute tasks directly itself. A "task" is defined as any request that requires tool use, external action, or multi-step execution. Pure conversational exchanges — greetings, brief clarifications, memory queries the assistant can answer directly from its injected context — are NOT tasks and MUST be handled by the assistant directly without dispatch. The assistant uses this distinction to decide per message whether dispatch is required.
- **FR-002**: System MUST provide two kinds of executor: ephemeral subagents (single-use, not persisted, unnamed) and fixed specialists (persistent, named, reusable).
- **FR-003**: System MUST allow the assistant to infer the user's real intent before selecting an executor, rather than executing the request literally.
- **FR-004**: When delegating to an ephemeral subagent, System MUST allow the assistant to specify the task instruction, the execution context, and an optional tool whitelist.
- **FR-005**: System MUST have the assistant consolidate an executor's result before replying to the user.
- **FR-006**: System MUST exclude the PM, Programmer, and Trial recording-pipeline agents from the assistant's dispatch options.

#### Brain Zones

- **FR-007**: System MUST maintain six cognitive zones for the assistant: hot zone, persistent zone, archive zone, subconscious zone, failure zone, and prediction zone.
- **FR-008**: The hot zone MUST hold the user's current life context (events, insights, current activities, surrounding people, environment) and MUST decay based on continued relevance to current life rather than a fixed time window. Hot-zone relevance scoring MUST be triggered after every Segment distillation write (entries transition to `fading` when relevance drops below threshold); a background worker MUST additionally run periodic sweeps to catch entries that have not been re-evaluated due to extended inactivity.
- **FR-009**: When a hot zone entry fades out, System MUST NOT delete it — event-type entries MUST move to the archive zone and insight-type entries MUST move to the persistent zone or be retired. Entry type MUST be determined by an explicit `entry_type` field (enum: `event` | `insight`) assigned by the distillation LLM at creation time; the decay router reads this field to determine the target zone.
- **FR-010**: The persistent zone MUST hold two kinds of content: explicit permanent facts and stable long-term experience.
- **FR-011**: System MUST absorb the existing assistant profile (display name, style, notes) into the persistent zone as fact entries.
- **FR-012**: The archive zone MUST be a layered index over conversation history (unit summaries, then theme and time summaries, then high-level abstraction) navigable from either a theme axis or a time axis.
- **FR-013**: The subconscious zone MUST hold implicit user traits the user cannot easily state directly (preferences, values, style, aversions) and MUST be treated as reference, not as binding rules.
- **FR-014**: The subconscious zone MUST support evolution — newer entries can supersede older entries while history is retained.
- **FR-015**: The failure zone MUST hold hard-learned lessons, each carrying an applicable scope so a lesson from one situation is not blindly applied to another.
- **FR-016**: The prediction zone MUST hold verifiable predictions about the user's likely next actions, used for system self-calibration. Each prediction entry MUST carry a verification checkpoint (a future date or event condition). Verification MUST be performed automatically by the background worker at the checkpoint: the worker issues an LLM evaluation comparing the prediction text against Memory Entries distilled during the relevant period and writes a `hit`, `miss`, `partial`, or `expired` conclusion back to the entry along with a one-sentence verification rationale text (the LLM's explanation for the judgment, e.g. "No relevant action records found in the distilled entries for this period"); both the status and the rationale MUST be displayed together in the brain management module. No confidence score is stored. User confirmation is not required; the assistant does NOT evaluate predictions inline during conversation turns. If the verification LLM call itself fails (network error, API error, timeout), the worker MUST retry a configurable number of times (placeholder value, per CC-008); if retries are exhausted, the entry MUST be marked `expired` with the verification rationale set to a system-generated note such as "verification call failed — could not be assessed"; this is consistent with the distillation retry pattern.
- **FR-017**: System MUST keep the hot, persistent, and subconscious zones passively visible to the assistant; MUST make the failure and archive zones accessible only through the assistant's explicit retrieval; and MUST keep the prediction zone invisible to the assistant.
- **FR-018**: Every brain entry MUST carry common metadata including status, origin, applicable scope, and timestamps; every auto-generated entry MUST carry a non-empty, traceable reason. The Memory Entry `status` field MUST be one of: `active` (normal, retrievable), `fading` (hot-zone entry losing relevance, still visible to assistant), `invalidated` (weight-degraded by explicit invalidation signal, still returned by retrieval with invalidation factor), `soft-deleted` (user-deleted in management UI, retained in history but excluded from normal retrieval). Distillation failure is tracked on the Segment, not the Memory Entry — a Segment that exhausts retries transitions to `failed` status (a distinct enum value, displayed in the management UI as "distillation failed, manual retry available"); no Memory Entry is created. A user-triggered retry moves the Segment back to `pending` and then `distilling`. Every Memory Entry MUST also carry effect-tracking counters: `loaded_count` (number of times this entry was injected into the assistant's context) and `referenced_count` (number of times the LLM's reply demonstrably referenced the entry's content); the effectiveness ratio (referenced_count / loaded_count) MUST be used as a retrieval ranking signal — entries with low effectiveness after sufficient injection exposure are deprioritized but never excluded entirely, while newly created or rarely injected entries receive the exploration allowance defined by the composite ranking strategy. `referenced_count` MUST be measured via explicit structured output: the assistant's reply MUST include a `memory_entries_referenced` metadata field listing the IDs of entries it actually drew on; the backend MUST read this field and batch-update `referenced_count` for each listed entry. No secondary LLM evaluation call is used for this measurement. If the `memory_entries_referenced` field is absent or structurally malformed in a given reply, the system MUST silently skip the `referenced_count` update for that turn — the conversation continues normally with no error or retry; any unknown entry IDs in the field MUST be ignored rather than treated as errors. Every Memory Entry MUST carry a nullable `superseded_by` field (foreign key to another Memory Entry); when a new entry supersedes an older one, the older entry's `superseded_by` MUST be populated atomically in the same write operation, forming a traversable evolution chain visible in the brain management module. This chain covers two origins: system-generated supersession (the system produces a new insight replacing an older one) and user-initiated edits (the user modifies an entry in the management UI, producing a new entry that replaces the original, displayed as an annotated diff).

#### Distillation

- **FR-019**: System MUST use the Segment — one continuous "open conversation → talk for a while → close, idle, or forced-switch" stretch — as the unit of distillation analysis.
- **FR-020**: System MUST trigger a Segment boundary on any of: window close, prolonged idle, the user opening a new session, or a message/token limit being reached. Prolonged-idle detection MUST be performed by the frontend (UI inactivity timer); upon reaching the configured threshold the frontend MUST emit a `segment_idle_trigger` event to the backend. The backend MUST NOT poll message timestamps to detect idle state independently.
- **FR-021**: System MUST trigger exactly one distillation analysis when a Segment is sealed — exactly-once delivery MUST be guaranteed by an atomic DB-level state transition: moving a Segment from `pending` to `distilling` MUST be performed within a transaction using compare-and-swap or a row-level lock so that concurrent boundary events targeting the same Segment cause at most one successful transition; any event that arrives when the Segment is already in `distilling`, `completed`, or `failed` state MUST be silently discarded, and that analysis MUST write to the phase-activated zones from a single shared understanding so the zones stay mutually consistent. The distillation MUST be implemented as a single structured LLM call whose response is a phase-specific multi-zone JSON object; if the call fails or produces invalid output the entire Segment retries as a unit — no partial per-zone retry is permitted. Output validity is determined by structural schema conformance only: the JSON must match the expected phase-specific schema with all required active-zone fields present and correctly typed; any requested zone's entry list MAY be empty without triggering a retry. Unactivated zones MUST NOT be present in the schema for that phase and MUST NOT be silently requested then discarded. Semantic content quality is NOT a validity criterion. However, if a structurally valid response contains zero entries across all requested zones, the system MUST trigger exactly one additional retry — a well-prompted phase-specific distillation should usually extract at least one relevant signal when the Segment contains usable content; an all-empty result is treated as an extraction failure worth one retry attempt. If the retry also produces an all-empty result, the Segment MUST be marked `completed` with zero Memory Entries and no further retries are triggered. Exactly-once delivery MUST further cover writing, not only triggering: the Memory Entry inserts produced by a successful distillation and the Segment's `distilling` → `completed` state transition MUST be committed within a single database transaction. If the process crashes before that transaction commits, the inserts MUST roll back as a unit, leaving the Segment in `distilling` for crash recovery to reset to `pending`; a crash occurring between entry writes and the status transition MUST NOT result in duplicate Memory Entries when the Segment is re-distilled.
- **FR-022**: System MUST NOT trigger distillation analysis from a single delegation event, because a single delegation lacks surrounding context.
- **FR-023**: System MUST NOT retract already-distilled memories when a session is revived; the new increment MUST be distilled independently as a new Segment.
- **FR-024**: System MUST treat a user reviving an old session as a positive weighting signal for the memories associated with that session.
- **FR-025**: System MUST run periodic background work covering archive layering, invalidation review, hot-zone-to-persistent abstraction, subconscious deep distillation, prediction generation and verification, memory weight recomputation, and specialist-recruitment scanning. Prediction generation MUST be performed by a periodic background worker with cross-Segment context; it is not produced by the Segment `distillation_output` tool.

#### Cold Start

- **FR-026**: When all brain zones are empty for a first-time user, System MUST have the assistant run an icebreaker consisting of a self-introduction plus 1-2 of the most essential questions.
- **FR-027**: The icebreaker MUST be natural conversation; it MUST NOT be a form or onboarding popup and MUST NOT expand into a questionnaire.
- **FR-028**: System MUST write the user's icebreaker answers directly into initial persistent-zone entries, each with a reason. The mechanism is the normal P1 Segment distillation path: the Segment containing the icebreaker exchange MUST route durable user-answer facts to `zone='persistent'`, `origin='distillation'`, `status='active'` entries in the same atomic transaction that completes the Segment; no assistant-facing "write memory" tool is required. Because P1 injects the persistent zone in full, those entries become visible through the next context rebuild without passing through the fading hot zone.
- **FR-029**: After the brain has accumulated sufficient context, System MAY have the assistant make subtle, conversational inferences about the user's likely direction, and MUST NOT present such inferences as a form or questionnaire.

#### Specialists

- **FR-030**: System MUST support three specialist origins: automatic background recruitment, user-initiated creation during conversation, and user creation in the management UI.
- **FR-031**: Automatic specialist recruitment MUST be based on recognizing sustained delegation patterns, MUST generate the specialist directly without a "proposal + confirmation" step, and MUST attach a reason that traces back to the originating delegations. Upon creation, the system MUST display a non-modal toast notification in the UI (containing the specialist name and reason, with a link to the specialist management page); the toast MUST NOT block or interrupt the conversation flow.
- **FR-032**: Each specialist MUST carry a name, description, role definition, tool whitelist, origin, reason, and version history.
- **FR-033**: A specialist's tool whitelist MUST be a subset of the assistant's current skill pool. When a tool is removed from the skill pool and one or more specialists reference it, the system MUST block the removal and display the list of affected specialists; if the user confirms a forced removal, the system MUST auto-prune that tool from all affected specialist whitelists.
- **FR-034**: System MUST let the user view, edit, and delete specialists, and adjust a specialist's skills, directly from the management UI without going through the assistant.

#### Retrieval & Invalidation

- **FR-035**: System MUST let the assistant actively retrieve from the archive zone (when the user mentions past events) and from the failure zone (before decision-type tasks). Retrieval MUST be triggered by explicit assistant tool calls (e.g. `retrieve_archive(query)`, `retrieve_failure_zone(context)`); the backend MUST NOT silently pre-inject archive or failure zone entries into the context without an explicit tool invocation.
- **FR-036**: System MUST let the assistant mark a memory entry as invalid and MUST require a reason for the invalidation. The assistant MAY invalidate an entry reactively (when the user explicitly states a memory is wrong) or proactively (when the assistant detects a clear factual conflict with current conversation); proactive invalidation MUST be disclosed to the user in the same reply turn in which it occurs. The invalidation tool MUST only accept entry IDs that are present in the assistant's current context window — either passively injected (hot / persistent / subconscious zone entries) or returned by an explicit retrieval tool call (`retrieve_archive`, `retrieve_failure_zone`) earlier in the same turn or session. Attempting to invalidate an entry the assistant has not yet retrieved MUST be rejected; the assistant must first call the appropriate retrieval tool to bring the entry into context.
- **FR-037**: Invalidation MUST degrade an entry's weight rather than hard-filter it — when retrieval finds no active results, invalidated entries MUST still be returned, marked with an invalidation factor.
- **FR-038**: System MUST NOT physically delete distilled data; a user deletion in the management UI MUST be a soft delete that retains history. A user edit of a memory entry in the management UI MUST also preserve the original — the edit MUST produce a new Memory Entry containing the updated content, the new entry MUST be linked to the old entry via the `superseded_by` field (the old entry's `superseded_by` is set to the new entry's ID), and the old entry's status MUST be set to `soft-deleted`. The management UI MUST display this evolution chain as an annotated diff (original → revised), analogous to tracked changes. The `superseded_by` chain is used for both system-generated memory evolution (new insights replacing old ones) and user-initiated edits.

#### Interaction & Brain Management

- **FR-039**: System MUST provide a dedicated brain management module and a dedicated specialist management module, both presented as peers to the assistant conversation interface rather than nested within it. The specialist management module MUST be a distinct navigable page (e.g. a sub-route of `/brain` such as `/brain/specialists`, or a standalone top-level route) rather than an inline panel — users must be able to reach it directly from main navigation.
- **FR-040**: The brain management module MUST let the user view, edit, and delete all entries across the six zones.
- **FR-041**: The specialist management module MUST be a dedicated page where the user can view, create, edit, and delete specialists, and adjust each specialist's tool whitelist, entirely within the page without going through the assistant. The brain management module MUST separately provide an assistant skill-pool management panel for managing the full skill pool.
- **FR-042**: System MUST present every auto-generated product together with its reason, shown by default rather than collapsed.
- **FR-043**: System MUST NOT present any "do you want to…" confirmation popup for auto-generated products — auto-generated products take effect directly.
- **FR-044**: System MUST consume the user's edits and deletions of auto-generated products as feedback signals — an edit means right direction but wording adjustment, a deletion means the system judged wrong. Feedback signals MUST be stored in a dedicated `feedback_signals` table keyed by zone, operation type (edit / delete), and the affected entry or specialist ID. Future distillation LLM calls and specialist-recruitment scans MUST load recent relevant feedback signals from this table and append them to their prompts as contextual guidance (e.g., "entries of this type were previously rejected by the user — avoid repeating similar extractions"). This active injection is the primary consumption mechanism; signals are not merely logged for analytics.
- **FR-045**: System MUST NOT count user silence as either a positive or negative signal, and MUST NOT proactively press the user for a response.

### Key Entities *(include if feature involves data)*

- **Assistant (主助理)**: The user-facing orchestrator agent — a project manager that dispatches all execution and owns the brain.
- **Cognitive Zone (认知分区)**: One of six brain partitions — hot (current context), persistent (permanent facts + experience), archive (layered history index), subconscious (implicit personality), failure (scoped lessons), prediction (self-calibration forecasts).
- **Memory Entry (记忆条目)**: A single unit of cognition stored in a zone, carrying content, status (`active` / `fading` / `invalidated` / `soft-deleted`), `entry_type` (enum `event` | `insight`, set at creation by the distillation LLM, used by the hot-zone decay router to route faded entries to the correct zone), origin, reason, applicable scope, weighting signals, effect-tracking counters (`loaded_count`, `referenced_count`), supersession link (`superseded_by: entry_id?`), and lifecycle metadata. Prediction-zone entries additionally carry `verification_checkpoint` (future date or event condition), `verification_status` (`hit` / `miss` / `partial` / `expired`), and `verification_rationale` (one-sentence LLM explanation).
- **Segment (片段)**: One continuous open-to-close stretch of conversation; the unit of distillation analysis. One Session can contain multiple Segments. A Segment carries its own status: `pending` (sealed, awaiting distillation — distinct from `failed`), `distilling` (analysis in progress), `completed` (distillation succeeded; Memory Entries may be zero if the segment had no extractable content after the one all-empty retry), `failed` (exhausted retries without producing structurally valid output — shown in management UI as "distillation failed, manual retry available"; a user-triggered retry returns the Segment to `pending`).
- **Session (会话)**: The user's notion of "one conversation topic", which may span months and contain multiple Segments; the context to which memory entries are attributed.
- **Distillation (沉淀)**: The reflective process that, at each Segment boundary, reads the full Segment and writes memory entries into multiple zones from a single understanding.
- **Specialist (专员)**: A persistent, named executor with a defined role and a tool whitelist, reusable across delegations.
- **Ephemeral Subagent (临时 subagent)**: A single-use, unnamed executor created for one task and discarded afterward.
- **Skill Pool (技能池)**: The full set of capabilities the assistant can use; a specialist is granted a subset of it.
- **Reason (缘由)**: The mandatory, traceable explanation attached to every auto-generated product and shown to the user.
- **Recruitment Signal (招人信号)**: A background-detected indicator of a sustained delegation pattern that drives automatic specialist creation.
- **Brain Management Module (大脑管理模块)**: The dedicated UI surface, parallel to the conversation interface, for viewing/editing/deleting zone entries, specialists, and the skill pool.

### Constraints & Compatibility *(include when relevant)*

- **CC-001**: The redesign MUST reuse the existing agent execution kernel as the run-loop for the assistant, ephemeral subagents, and specialists, rather than replacing it.
- **CC-002**: The redesign MUST NOT change the PM / Programmer / Trial recording-pipeline agents or their orchestration chain.
- **CC-003**: The redesign MUST NOT introduce new middleware (message queues, caches, message buses, vector databases); it MUST reuse the existing database-queue + background-worker pattern.
- **CC-004**: System MUST preserve existing assistant profile data by migrating it into the persistent zone, keeping backward-compatible behavior during the transition.
- **CC-005**: System MUST keep architectural layering intact — UI reaches business capability through typed interfaces, the desktop API bridge remains a UI adapter and not a data-access layer, and lower layers do not call upward.
- **CC-006**: All new configurable thresholds MUST go through the unified configuration entry; any session-level "allow all / skip confirmation" state MUST remain in-process memory only and MUST NOT be persisted.
- **CC-007**: Distilled data MUST never be physically deleted by the system; invalidation is weighting, not removal.
- **CC-008**: Scoring formulas and numeric thresholds (decay curves, top-N caps, debounce/idle/retry/limit values, periodic-job timings) are intentionally NOT fixed by this specification; they are placeholders to be tuned with real data after the first delivery phase. The stable contracts are the zone set, the entry attributes, the trigger conditions, and the behavioral guarantees.
- **CC-009**: The feature MUST be delivered in incremental, independently shippable phases corresponding to the five prioritized user stories; each phase MUST be observable and verifiable on its own.
- **CC-010**: Existing high-risk confirmation semantics for tool execution MUST remain intact for tasks carried out by executors.
- **CC-011**: Brain zone data MUST NOT introduce additional encryption beyond the existing OS file system and SQLite security boundary; brain zone tables reside in the same SQLite file as existing conversation messages and share the same security posture. Encryption at the SQLite or application level is deferred to a separate compliance-driven effort.

## Architecture Impact *(Mexemplar-specific)*

### Layer Impact

Which layers are affected? Check all that apply:

- [x] **UI** (`frontend/src/`, `src-tauri/`) — React screens, state, API client, Tauri shell, or window commands. Two new navigable surfaces are introduced within the existing React app: (1) a brain management module (e.g. `/brain`) for viewing/editing/deleting zone entries and managing the skill pool; (2) a specialist management module (e.g. `/brain/specialists` or a peer top-level route) as a dedicated page for creating, editing, deleting specialists and adjusting their tool whitelists. Both are accessible from the main navigation bar alongside the conversation interface. A non-modal toast notification component is required to surface auto-recruited specialist events. No new Tauri window is introduced.
- [x] **Desktop API Bridge** (`src/desktop_api/`) — FastAPI routers, schemas, event stream adapters, or sidecar contracts
- [x] **Business** (`src/business/`) — agents, orchestration, services, memory
- [ ] **Execution** (`src/execution/`) — tool execution sandbox
- [x] **Data** (`src/data/`) — models, repositories, migrations, config
- [ ] **Recording** (`src/recording/`) — recorder, filtering, browser extension
- [x] **Utils** (`src/utils/`) — events, helpers

### Agent Impact *(if touching Agent system)*

- Which Agent(s) are affected: Assistant only. PM / Programmer / Trial are explicitly out of scope and must be unchanged.
- New tools or modified tool handlers? New assistant-facing capabilities are required for task delegation to ephemeral subagents, delegation to fixed specialists, specialist creation, archive retrieval, failure retrieval, and memory invalidation.
- System prompt changes needed? Yes — the assistant prompt is restructured into multi-zone injection (hot / persistent / subconscious zones passively visible, specialist list, capability list) plus a "100% dispatch" working-style section; the prompt is rebuilt in the assistant worker before each run, so zone or specialist changes are picked up by the next run without a separate prompt cache. Injection strategy is tiered: the persistent zone MUST be injected in full (all active entries); the hot zone and subconscious zone MUST each contribute a top-N selection ranked by a composite score. The composite score MUST NOT use the effectiveness ratio (referenced_count / loaded_count) as its sole key: the hot zone ranks primarily by `relevance_score` (recency as tiebreaker), the subconscious zone ranks primarily by recency, and the effectiveness ratio is blended in only as an additional weighting term; entries with a low `loaded_count` (newly created, not yet injected) MUST receive an exploration allowance so a never-injected high-value entry is not permanently starved out of the top-N. Because `referenced_count` measurement is not delivered until P3 (it rides on the `reply_to_user` tool), the effectiveness term is zero for all entries during P1 and P2 and the composite score degrades gracefully to the relevance/recency ordering — the ranking is therefore observable and verifiable from Phase P1 onward (per CC-009). Specific N values, the exploration-allowance size, and the blend weights are placeholders subject to real-data tuning (per CC-008).
- Orchestrator dispatch changes? The assistant builds the new multi-zone prompt before each assistant run inside the sidecar assistant worker; an execution path is added for creating ephemeral/specialist executor sessions. Blinker zone-change and specialist-change events are used for UI/event-stream invalidation, not for an in-process prompt cache. Per-token or per-iteration prompt rebuilds remain out of scope. Context loading is non-blocking to the conversation UI because it runs in the background assistant worker; the assistant MUST NOT generate its first reply until the context is ready, but the user is NOT shown a blocking loading screen.

### Data Store Impact *(if touching data layer)*

- **SQLite** (`src/data/repos/`): New persistent storage is required for the six brain zones plus supporting structures (segments, specialists with version history, a memory change log, recruitment signals, entry relations, and a `feedback_signals` table for tracking user edit/delete signals that are injected into future distillation and recruitment prompts); new schema migrations are required. The existing conversation message store is reused as the lowest archive layer. Existing assistant profile data is migrated into the persistent zone. **All six zone tables and supporting tables MUST be created in a single migration in Phase 1 (P1)**; subsequent phases activate business logic against those tables without adding further migrations.
- **DuckDB** (`src/recording/filtering/`): Not affected.
- **Config** (`src/data/unified_config.py`): New `brain.*` configuration keys (segment thresholds, background-worker retry/tick settings, prompt injection caps, hot-zone decay, archive toggles, retrieval backend) via the unified config; all values are placeholders pending real-data tuning.
- **Secrets** (keyring): No new secret fields.

### Event Impact *(if adding/changing events)*

- New events to define in `src/utils/events.py`: zone-change and specialist-change notifications used to rebuild the assistant prompt; a window-closing trigger event; a `segment_idle_trigger` event emitted by the frontend when the UI inactivity timer fires.
- Modified event payloads: none required beyond the new events.
- New event listeners: an event router consuming Segment-boundary triggers (window close, new session, idle, message/token limit) and user edit/delete signals from the brain management module.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user can close the assistant and return after a delay, and the assistant references the prior Segment's context without the user re-explaining, in at least 9 of 10 trials.
- **SC-002**: In a labeled acceptance suite of at least 10 user task requests (requests requiring tool use, external action, or multi-step execution), at least 9 of 10 requests result in delegation to an executor, and 0 accepted runs show the assistant performing the requested task directly. Pure conversational exchanges are excluded from this measurement.
- **SC-003**: After a Segment is sealed and distilled, the resulting brain entries are available to the assistant in the next conversation with no manual step required from the user.
- **SC-004**: 100% of auto-generated brain entries and specialists display a concrete, traceable reason.
- **SC-005**: First-time users reach normal use after answering at most 2 questions, with no form or onboarding wizard shown.
- **SC-006**: A user can locate and then edit or delete any entry in any of the six zones from the brain management module.
- **SC-007**: After a sustained pattern of similar delegations, a specialist is auto-created within one recruitment-scan cycle, carrying a reason that references the originating delegations.
- **SC-008**: Every prediction-zone entry is verifiable — it carries a concrete claim and receives a hit / miss / partial / expired status after its verification point.
- **SC-009**: The system never hard-deletes distilled data; retrieval that finds no active results still returns invalidated entries marked with an invalidation factor.
- **SC-010**: No "do you want to…" confirmation popup appears for any auto-generated product across the brain management module.
- **SC-011**: Existing assistant profile data appears in the persistent zone after the brain system is enabled, with no loss of display name, style, or notes.
- **SC-012**: The PM, Programmer, and Trial recording flows remain demonstrable with no user-visible regression after the redesign.

## Assumptions

- Single user, single brain — multi-user support is out of scope for this version.
- The existing agent run-loop, agent configuration, and background-worker / task-queue infrastructure are stable and reusable as the foundation for this feature.
- The existing conversation message history is the authoritative lowest layer of the archive zone.
- Scoring formulas, decay curves, periodic-job schedules, top-N caps, and debounce / idle / retry / limit thresholds are placeholders to be tuned with real data after the first delivery phase; this specification fixes behavior and structure, not numbers.
- Structured multi-zone distillation from a single analysis is reliable enough for production use; if it proves unstable, a documented fallback splits the analysis into a core path and lighter secondary paths.
- The five prioritized user stories are the intended delivery order; each is independently shippable and verifiable.
- The brain management module is a separate UI surface, parallel to (not nested in) the assistant conversation interface.
- No confirmation / approval UI is built for auto-generated products; this is a deliberate design stance, and user edits / deletions are the feedback channel instead.
- Existing Skills, Compositions, the assistant skill pool, and specialists coexist in the short term. The existing Skills screens continue to manage taught reusable capabilities, existing Compositions continue to manage user-authored combinations, the `/brain` skill-pool panel only manages the assistant capability whitelist used by specialist tool whitelists, and the specialist management page owns named executor roles. Their long-term consolidation path is deferred.
- Conversations from before the brain system existed are not auto-distilled in bulk on migration; they remain retrievable as raw archive and can be distilled on demand.
