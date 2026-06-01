# Feature Specification: Skill Methodology Layer

**Feature Branch**: `012-skill-methodology-layer`
**Created**: 2026-05-26
**Status**: Completed
**Input**: User description: "基于 `docs/local/todo/todo-skill-methodology-layer.md`（可行性脑暴）和 `docs/local/todo/design-skill-methodology-layer.md`（实现设计稿）为 skill 方法论层创建 feature specification"

**Bugfix**: 2026-05-28 — ANALYZE-001 Resolve `/speckit.analyze` findings around historical clarification conflicts, marketplace scope, and verification coverage.

**Bugfix**: 2026-05-28 — ANALYZE-002 Resolve `/speckit.analyze` follow-up findings around assistant equipment scope and audit reason coverage.

## Clarifications

### Session 2026-05-26

- Q: 版本链回看视图应展示完整正文、diff 还是两者都有？ → A: 完整正文 + 与上一版的 diff 高亮对比同时提供
- Q: 内置创建方法论指引（"如何创建方法论"）的初始正文从哪里来？ → A: 代码库中的独立 seed 文件（与代码一起 review，迁移脚本只引用、不内嵌长文本）
- Q: 是否需要 `skills.changed` → `tools.changed` 的 deprecation 双发窗口？ → A: 不需要。本产品当前是单用户、未发布、无外部脚本消费者；直接改名即可，删除所有双发/窗口约束以避免范围扩张
- Q: 方法论的"触发条件"如何判定是否命中本轮用户输入？ → A: 由助理大脑（assistant 调度 LLM）结合当前上下文对自然语言形式的 `trigger_conditions` 自行判断，不做关键词字符串匹配；`trigger_conditions` 在数据层以"自然语言提示词条目"的形式存放，由大脑读取后参与派活决策。**(本条已被本会话后续澄清覆盖：trigger_conditions 不再进入 assistant 派活决策上下文，改为由装备者自己在执行时阅读判断——详见后一条 Q "assistant 派活时是否参考方法论装备关系或触发条件？")**
- Q: 工匠产出的方法论是否需要用户事前审核才能生效？ → A: 不需要。彻底取消审核闭环——工匠产出的方法论**直接 active 入库**，立刻可被装备、可被派活上下文看见；没有 draft / rejected 中间态、没有"待审区"概念。用户的纠错权力下放到事后：用户可随时在 SkillScreen 上编辑 active 方法论（每次编辑等价于一次用户驱动的 supersede，生成新版本接力）或对方法论软删除；marketplace 外部导入同样直接 active 入库（更严格的外部导入风控延后到未来 feature）。supersede 链上的所有版本都是 active 历程的一部分，没有"被拒绝"的终态
- Q: 提炼方法论时可以引用哪些大脑分区的 segment 作素材？ → A: 允许 archive zone（正例/成功 segment）与 failure zone（反例/失败 segment）两类；每条素材必须标注它来自哪个 zone，便于审计溯源区分"正例驱动 / 反例驱动"。其它分区（hot / persistent / subconscious / prediction）的 segment 不可作素材
- ~~Q: 派活时如何把方法论触发条件呈现给助理大脑（避免 token / latency 随方法论数量线性膨胀）？ → A: 渐进式披露（progressive disclosure）——派活上下文初始**只**放一份轻量索引（每条方法论的 id、名称、一句话短描述、当前被哪些 specialist 装备的列表），不直接喂 trigger_conditions 全文与正文 Markdown；大脑判断"哪些可能相关"后通过专用的方法论查询工具（按 id 拉详情）按需展开 trigger 全文与正文。无关方法论永远不进入主提示，token 成本与"大脑实际感兴趣的方法论数量"挂钩，与"方法论总数"解耦~~ **Superseded**: assistant 派活不读取方法论索引/触发条件/正文；装备清单只在装备者被派活后进入该装备者 system prompt。
- ~~Q: "创建方法论"这件事以什么形态提供？是否需要一个专门的"skill 工匠"固定专员？ → A: **不**引入"skill 工匠"这种固定专员。创建能力拆为两件资产：(1) 一个工具 `create_skill_methodology`（负责物理写入 brain_skills 表）；(2) 一份内置 active 方法论 "如何创建方法论"（描述何时调、怎么填、素材 zone 限制等最佳实践）。默认装备：仅 assistant 调度层本体拥有这两件资产——工具直接挂在 assistant 调度上下文中，方法论正文直接拼接进 assistant 自身决策上下文，不走任何 specialist 的工具白名单或有效系统提示。其它 specialist 默认无创建权限（既无 tool 也无 skill）；用户可在 SpecialistScreen 主动给个别 specialist 授权这两件资产。100% 调度约束保留：用户不能在 SpecialistScreen 上对某个 specialist 直接下"创建方法论"指令，必须经 assistant 对话路径~~ **Superseded**: "如何创建方法论"默认装备到 assistant 本体，正文不直接拼接进 assistant 决策上下文；正文只能由装备者通过 `load_skill_methodology` 按需加载。
- Q: 用户在 UI 上如何管理 assistant 本体装备的方法论清单？ → A: 在 SpecialistScreen 顶部固定显示一张"Assistant（主助理本体）"装备卡片，用户点进后使用与 specialist 一致的装备面板（多选 active 方法论、设置装备顺序、所需工具警告、保存）管理；assistant 本体的装备数据约束（FR-014/016/017/018）与 specialist 一致，唯一区别是该卡片不可删除/重命名（assistant 本体始终存在）
- Q: assistant 派活时是否参考方法论装备关系或触发条件？ → A: **不参考**。派活完全按 specialist 职责定位（沿用 010 已有的派活逻辑），与"谁装备了什么方法论""触发条件是否命中"完全无关。方法论只在装备者**被派活后**作为它执行时的手册生效；trigger_conditions 字段降级为"装备者自己工作时判断当前这一步要不要按这条手册走"的提示，**不**作为 assistant 派活决策信号。删除原 FR-035/035a/036/037 与 User Story 4 与原"派活索引 / 渐进式披露"机制。
- Q: 装备关系的默认值与新增传播规则是什么？ → A: **默认全装备 + 用户可卸**。新建 specialist 时自动装备当时所有 active 方法论；新方法论入库为 active 时（无论 assistant 调工具产出、用户编辑接力还是外部导入）自动追加装备到所有现有 specialist 与 assistant 本体；用户可在 SpecialistScreen 各装备面板卸下不需要的装备关系。装备顺序的默认值为按方法论创建时间升序追加到现有顺序末尾，用户可随时调整。**(原文中作为传播 trigger 之一的"提升为专员"路径已在本会话后续澄清中整体删除——见后文 Q "是否保留'提升为专员'路径"——故此处 trigger 列表已同步剔除。FR-014a 的核心语义不变。)**
- Q: 用户能否在 SkillScreen 直接编辑"如何创建方法论"这条内置方法论？ → A: 允许编辑，但**保存前**触发高危确认弹窗（沿用项目现有 `request_id + threading.Event + emit(request_id, message)` 同步确认协议），提示"修改此内置方法论将影响所有后续方法论创建行为，确定？"；用户确认后走与普通方法论一致的用户编辑 supersede 接力路径。FR-027a 的"不可软删除"保护与本条"编辑高危确认"保护合并为同一组对 `origin = system_bootstrap` 方法论的特殊保护。
- Q: 方法论的"相关度评分"字段是否本期保留？ → A: **删除**。用户真正想要的是"哪些 skill 用得频繁 / 哪些零使用"的整理视图，而非一个黑盒聚合分。改为：(1) 删除 FR-006 / Key Entities 中的"相关度评分"字段；(2) FR-041 累计的三项原始统计计数（被读取次数、被装备者数量、被引用执行次数）作为可观察事实直接暴露给 UI；(3) SkillScreen active 列表新增 FR-029a 定义的排序与筛选能力（最近变更 / 被引用次数 / 装备者数量；筛选"从未被引用执行过""最近 30 天没被引用过"），每张方法论卡片直接展示三项计数，让用户一眼判断价值。
- Q: 方法论被 supersede 出新版本时，统计计数如何处理？ → A: **继承累积**。supersede 链上的所有版本视为同一条方法论资产的不同版本，统计计数（被读取次数、被引用执行次数、最近一次被引用执行时间）从旧版本完整继承到新版本，之后新版本继续累计。装备者数量本身是"当前值"不存在继承问题（supersede 时由 FR-011 把装备关系全部切到新版本，新版本的装备者数量即旧版本的装备者数量）。如此，SkillScreen 的"最近 30 天没被引用过"筛选不会因为用户小修方法论而误判 v2 为冷门。
- Q: "被引用执行次数"的上报路径是什么？ → A: **复用现有 `memory_entries_referenced` 元数据惯例**。装备者（specialist 或 assistant 本体）在每轮 reply 的结构化元数据里新增一个 `skills_referenced: [skill_id, ...]` 字段，业务层在该轮 reply 落库时同步对列出的 skill 各 +1 并刷新最近一次被引用执行时间；字段缺失或格式错误时静默跳过本轮（不报错、不重试），未列出的 skill 本轮**不** +1。同一轮 reply 中同一个 skill_id 重复列出按 1 次计。**不**引入独立的上报工具、**不**走后台 worker 异步聚合、**不**做"装备即引用"的兜底——这是 C' 项目化方案，与 `memory_entries_referenced` 现有契约形状、失败静默策略、守卫测试模式完全对齐。
- Q: 装备 UI 上的 token 预算风险提示长什么样？ → A: **实时计量条**。SpecialistScreen 各装备面板（含 FR-015a 的 assistant 本体卡片）MUST 在顶部固定显示一条 token 计量条，包含：(1) 当前装备总条目数；(2) system prompt 中装备清单注入区段的 token 估算值；(3) 按阈值分段的颜色（健康 / 警示 / 危险，例如绿/黄/红）。该计量条 MUST 随用户勾选/卸下、调整顺序、新增/移除装备实时更新（前端本地估算，不需要每次后端调用）。阈值具体数值与 token 估算公式由 plan 阶段决定（与 Assumption "token 预算硬上限由 plan 阶段决定" 一致）。不引入"保存时弹窗确认"或"超过阈值时阻断保存"——计量条仅作可观察事实展示，最终判断权在用户。
- Q: "同名 / 同触发条件冲突"如何判定与提示？ → A: **业务层不做字符串/相似度判重，把判重责任放在 assistant 的提示工程**。理由：当前架构下 assistant 本体已经通过装备清单条目（FR-017）"看到"所有 active 方法论的轻量信息（id + 名称 + 描述 + 触发条件 list）——FR-014a 默认全装备保证 assistant 本体能看到全部 active 方法论；assistant 在调 `create_skill_methodology` 之前应自行扫描清单判重，发现重合就在对话里反问用户"要不要合并/择一"。"如何创建方法论"内置方法论的正文 MUST 写明这一判重义务（创建前先扫一眼装备清单，发现名称或触发场景重合时先与用户对齐）。业务层 `create_skill_methodology` 工具**不**做名称字符串相等检查、**不**做触发条件 list 元素相等检查、**不**做 LLM 相似度调用——直接 active 入库（FR-023）。UI 侧 SkillScreen 列表对名称完全相等的多条 active 方法论展示一个"同名"标签作纯视觉线索（精确字符串匹配只作标签展示，不算判重检测、不阻断、不弹窗），便于用户事后整理。整体哲学一致——"决策放在 LLM，机械工具不做关键词/字符串匹配"（参见 trigger 判定与 assistant 派活决策的同类约定）。
- Q: "触发条件"字段的存储与渲染结构？ → A: **存储为 list of strings（多条自然语言条目），渲染为 YAML list**。每条都是一句话短句（例："用户在请求做周报、月报、季报或复盘类总结时" / "用户说'按上周素材整理一份'这种语义同型的请求"），用户在 SkillScreen 编辑器里通过 add/remove bullet 列表编辑器维护（不是单个 textarea）；SQLite 持久化用 JSON array 或 TEXT[] 等价表示；装备清单条目（FR-017）注入 system prompt 时，触发条件以 YAML list 原生形态渲染（不再做"拼成单串"的损耗）；未来与 Anthropic Agent Skills 规范的 SKILL.md 导出对接（FR-042/043）时，由导出层把 list 拼接成单串赋给 frontmatter 的 `when_to_use` 字段（内部 list、外部单串、转换发生在导出层）。FR-031 的"编辑器五字段"中"触发条件"对应的 UI 控件为 list editor，而非单 textarea。
- Q: 方法论的"被读取次数"该统计什么？(2 轮澄清) → A: **改名为"被加载次数"，统计 agent 主动加载详情的频次，人翻看不计入**。语义重定向有两层：(1) 方法论正文**不再拼进 effective system prompt**——派活时 system prompt 只注入装备清单条目（id + 名称 + 描述 + 触发条件，**不含正文**），正文走新增的 `load_skill_methodology(skill_id)` 工具按需拉取，工具 result 进 messages 序列（与 010 已有的 hot/persistent 区被动注入模式一致，与 system prompt 的"角色定义"语义解耦）；(2) "+1" 触发点 = agent 调 `load_skill_methodology` 成功返回时 +1，SkillScreen 详情对话框 / 装备 UI 预览 / 审计视图等**人触发**路径**不** +1，无去重窗口（每次工具调用各算 1 次）。装备关系仍然是"用户给装备者预筛过的候选集"——装备 = 出现在该装备者的清单里，agent 可以看到候选；load = agent 真主动想用它。装备者协议同步对齐 Anthropic Agent Skills 开放规范（SKILL.md = YAML frontmatter + Markdown body；本 spec 的"名称/描述/触发条件/所需工具/正文" ≈ Anthropic frontmatter 的 `name`/`description`/`when_to_use`/`allowed-tools` + body），`load_skill_methodology` 工具 result 按此形态渲染。三项计数（被加载次数 / 当前装备者数量 / 被引用执行次数 + 最近一次时间）形成「暴露 vs 候选覆盖 vs 真用」的三维诊断视图，独立信号互补。

**Bugfix**: 2026-05-28 — ANALYZE-001 Conflict resolution: earlier Session 2026-05-26 notes that described ~~assistant dispatch progressive disclosure over methodology indexes~~ or ~~directly concatenating methodology body into assistant decision context~~ are historical only and are superseded by the later clarifications "assistant 派活时是否参考方法论装备关系或触发条件？" and "方法论的被读取次数该统计什么？". Implementation authority is: assistant dispatch does not read methodology data; equipped agents receive only lightweight entries in system prompt; body Markdown is loaded only through `load_skill_methodology`.

### Session 2026-05-27

- Q: FR-027a 的"内置方法论保护"如何沿 supersede 版本链传播？ → A: **沿 supersede 链传播保护**。判定标准是版本链**根节点**的 origin：只要某条方法论的 supersede 链可追溯到 origin = `system_bootstrap` 的根节点，链上所有后续版本（无论它们各自的 origin 是 `user_edit` / `assistant_tool_call` / `specialist_tool_call` / `external_import` 中的哪一种）都受 FR-027a 完整保护——不可软删除、用户在 SkillScreen 编辑器保存前必须触发高危确认弹窗。原始 origin 字段如实记录每次产出来源用于审计，但 FR-027a 的保护标志独立按"链根 origin"判定。本约定与 FR-041a"统计计数沿链继承"的资产视角一致：方法论作为一类资产由其 supersede 链一致定义；FR-027a 的目标是"任何时刻必须有 `如何创建方法论` 的某个版本处于 active 以保证 assistant 具备创建指引"，该目标必须对全链生效，而非仅对 v1 生效。
- Q: 删除被装备方法论时的"强制移除"二次确认走哪种协议？ → A: **走项目高危同步确认协议**。沿用 `request_id + threading.Event + emit(request_id, message)` 同步协议（与 FR-027a 编辑保护、004 高危确认浮层同协议、CLAUDE.md 第 9 条硬规则），UI 用非模态浮层展示（含受影响装备者名单 + 当前装备者数量摘要）；后端 Service 在删除路径上阻塞等待用户决策；用户拒绝即取消整个删除请求；用户确认后在**单事务内**执行装备关系裁剪 + 方法论落 `soft_deleted`，崩溃整体回滚（避免出现"已落 soft_deleted 但装备者装备未裁剪"的不一致中间态）。FR-027a 受保护方法论本身也不允许走此删除路径（FR-027a 已禁止软删除）。事件经现有 UI Event Registry 注册，payload 不得包含方法论正文全文（前端按 skill_id + 受影响装备者 id 列表渲染）。
- Q: reply 元数据 `skills_referenced` 引用了"已被 supersede 的旧 skill_id"时如何处理？ → A: **fail-soft，按链根 asset id 归一化后 +1**。业务层在每轮 reply 落库时把元数据里的每个 skill_id 沿 supersede 链回溯到根 asset id，找到该 asset 当前 active 版本并对其"被引用执行次数 +1"、刷新最近一次被引用执行时间；过时 / 已 `superseded` 的 skill_id 全部归一化到当前 active 版本，不丢失"真按它走了"的信号；只有当链根 asset 当前已落 `soft_deleted` 终态时，本条引用视为"asset 已不存在"按 FR-041 现有静默跳过规则同等处理（不 +1、不报错重试）。该约定与 FR-041a"统计计数沿 supersede 链继承"的资产视角对称——reply 元数据写出的 skill_id 在语义上指向"asset"而非"version snapshot"，并发 supersede 边界场景下不再产生"统计无主"的 ambiguity。归一化逻辑由业务层在落库 +1 路径上集中实现；同一轮 reply 中多条引用归一化后指向同一 asset 仍按 FR-041 "同一轮重复列出按 1 次计"规则去重。
- Q: 内置"如何创建方法论"是否例外于 FR-014a"默认全装备到所有 specialist"？ → A: **例外，仅默认装备到 assistant 本体**。FR-014a / FR-025 的冲突按"链根 origin = `system_bootstrap` 的方法论"为单一例外消解：这类方法论变为 active（首次迁移入库或后续 supersede 接力出新版本）时**只**自动装备到 assistant 本体，**不**追加装备到任何 specialist；新建 specialist 的"默认全装备"快照同样**剔除**所有链根 origin = `system_bootstrap` 的方法论。例外的判定与 FR-027a 完全对称——按"版本链根 origin"判定，链上后续版本（如 user_edit 接力的 v2）即使自身 origin 不是 `system_bootstrap`，只要链根是 `system_bootstrap`，也继承本例外规则。普通（非例外）方法论仍走 FR-014a 默认全装备。用户在 SpecialistScreen 仍可对个别 specialist **主动**装备某个 `system_bootstrap` 方法论（与主动授权 `create_skill_methodology` 工具配套使用），主动装备的关系在该方法论后续 supersede 时按 FR-011 同样自动跟新到新版本，不被本例外规则撤销。
- Q: 同名 active 方法论可不可以共存？业务层是否做名称字符串相等检查？ → A: **拒绝同名共存**——`create_skill_methodology` 工具新建模式（非 supersede）在写入前检查全库是否已存在 `name` 精确字符串相等的 active 方法论，存在则拒绝并返回错误（含已占用 id 与 name，提示"请改名或先与用户确认合并/择一"）；用户在 SkillScreen 编辑器修改 `name` 撞名时同样阻断。该检查只看 `name` 字段精确字符串相等，**不**比较触发条件 list 元素、**不**比较所需工具、**不**比较正文 Markdown、**不**调用 LLM 做相似度判定（其它语义判重责任继续放在 assistant 的"如何创建方法论"提示工程层）。Supersede 模式不走本检查——supersede 是对已知 asset 的版本接力，新版本与旧版本同名是正常情况。理由：装备清单条目（FR-017）中 `name` 是 LLM 区分多条方法论的主要人类可读线索之一，允许同名 active 共存会让装备者大脑难以判断该 load 哪条；硬约束只锁住最便宜的一层（精确字符串），把"近名 / 同 trigger / 近义内容"等更柔软的语义判重交回 assistant 提示工程，与项目"决策放在 LLM，机械工具不做关键词/字符串匹配"哲学一致。本约定覆盖前一轮"业务层不做名称字符串检查"的旧推论——SC-019 同步修订为"业务层不做触发条件 list 元素相等检查、不调 LLM 相似度，但 `name` 精确字符串相等检查作为 FR-024a 唯一硬约束受守卫测试覆盖"。
- Q: SkillScreen active 列表的排序模式是否包含"被加载次数"？ → A: **包含，扩为 4 种排序模式**——FR-029a 当前定义 3 种排序键（最近变更 / 被引用次数 / 装备者数量），但卡片显示 3 项统计计数（被加载次数 / 装备者数量 / 被引用执行次数），排序键和卡片显示不对称。改为 4 种排序模式："最近变更时间倒序（默认）/ 被加载次数倒序 / 被引用执行次数倒序 / 装备者数量倒序"，与卡片显示的三项计数 + 时间维度对齐。理由：用户的真实诊断需求包括定位"被加载高但被引用低"的 description-rich-body-thin 异常方法论（LLM 经常想看但看完不真按它走，提示正文不够实用），这种"独立维度排序后肉眼对比相邻列"的工作流比复合筛选更直觉；FR-041 已经明确"三个独立信号互补"，每一维都值得能独立排序。筛选模式（"从未被引用执行过""最近 30 天没被引用过"）保持不变——筛选是按"被引用执行次数"判定，与排序键集独立。SC-015 同步修订到 4 种排序模式。
- Q: 用户在 SkillScreen 编辑**普通**（非 FR-027a 受保护）方法论保存时是否需要确认弹窗？ → A: **不弹窗，保存即生效**——保存按钮按下后立即走用户驱动的 supersede 接力：旧版本切 superseded、新版本入库 active、所有装备者的装备关系**在同一事务内**跟新到新版本（与 assistant 调工具产出的 supersede 同走 FR-011 事务约束）；崩溃整体回滚。前端通过非模态浮层告知"已生成 v_N"，无装备者名单、无二次确认按钮。理由：(1) 与 FR-023 "直接 active 入库" 哲学对称——assistant / 受授权 specialist 调 `create_skill_methodology` 的 supersede 模式都不走 UI 二次确认（不属于 UI 高危路径），用户编辑作为同一接力路径的另一入口也不应该走；(2) 与 FR-014a "默认全装备 + 用户可卸"的"事后可调整"理念一致——纠错成本低（每次编辑都是新 supersede 节点，旧版本永远留在审计链上，FR-039 提供 diff 视图回看），保护性弹窗反而拖慢正常修订；(3) FR-027a 已经把"会影响整个创建路径"的内置方法论单独兜底，剩下的普通方法论应让用户操作顺手；(4) 受影响装备者数量信息在 SkillScreen 卡片上已经直接显示（FR-029a 三项计数），用户在保存前心里已经有数，不需要在弹窗里再列一遍。**软删除路径维持 FR-020 高危同步确认协议不变**——删除是不可逆的状态切换（虽然物理记录保留），与可前向修订的编辑性质不同。
- Q: 是否保留"提升为专员"路径（从方法论编辑视图一键创建空白专员并装备该方法论）？ → A: **删除该路径**。理由：(1) FR-014a"新建 specialist 默认全装备"已经覆盖该路径主要价值——用户在 SpecialistScreen 正常新建专员时，当时所有 active 方法论自动装备到位（含目标方法论），无需独立快捷入口；(2) 该路径独占价值仅剩"把方法论的所需工具复制为专员工具白名单默认值"一项，单点价值低，用户可在 SpecialistScreen 手动配置；(3) 入口位置（SkillScreen 编辑器内）会让用户混淆"方法论 ≠ 专员"的资产分离方向，与本 feature 把两者作为独立资产的核心叙事冲突；(4) 它原属 P4 用户故事中的一个子场景，独立可交付价值最低，删除不影响 P1-P3 体感。同步修订点：删除 FR-019、User Story 4 Acceptance Scenario 4、Event Impact 中"用户提升为专员"事件 trigger、Assumptions 中"提升为专员动作产生的新空白专员"条目；上一条 Q "装备关系的默认值与新增传播规则" 中提到的"提升为专员"作为传播 trigger 已不存在，但 FR-014a 的核心语义（默认全装备 + 用户可卸）不变。
- Q: 触发条件 list 是否允许 0 条？ → A: **拒绝 0 条，工具层与 UI 层都强制 ≥1 条**。`create_skill_methodology` 工具在 args 校验阶段拒绝 `trigger_conditions` 为空 list 的调用并返回错误（与 FR-024 素材 ≥1 条同模式）；SkillScreen 编辑器保存按钮在 trigger_conditions list 为空时灰显或拒绝保存，错误提示明示"至少需要 1 条触发条件"。理由：触发条件是装备者大脑判断"该不该 load 这条方法论"的核心信号，与 description 字段（"是什么"）功能分工不同（"何时用"）；允许 0 条会把判断责任全部压到 description 上，破坏 FR-017 装备清单条目的二段结构语义；与 Anthropic SKILL.md 规范 `when_to_use` 字段的实践对齐；强制 ≥1 条还能阻断"无脑塞入装备清单"的退化用法。同步修订点：FR-006 字段约束新增"trigger_conditions list MUST 至少含 1 条 string 条目"；新增 FR-024b 显式表达工具层校验；FR-031 用户编辑器同步约束；新增 SC-022 守卫测试覆盖。本约定不影响"所需工具"list，"所需工具"允许 0 条（部分方法论确实不依赖工具，例如纯文档/思考类）。
- Q: bootstrap migration 读取 seed 文件失败时如何处理？ → A: **Fail-open with fallback**——seed 文件缺失 / 内容为空 / IO 异常时，migration 用代码里硬编码的最小 fallback 文本（一段简短 placeholder Markdown，说明"该方法论 seed 文件未能正确加载，请联系开发者修复并通过 SkillScreen 编辑此条方法论以恢复完整指引"）以 origin = `system_bootstrap` 写入大脑作为 active；应用启动成功不阻塞；首次启动后在 UI 上通过 non-blocking toast 提醒用户 seed 文件读取异常并附建议操作（"请检查 seed 文件或在 SkillScreen 上手动编辑'如何创建方法论'方法论"）。理由：(1) 保留"系统中必有该方法论某个 active 版本"这个核心不变量（FR-014a / FR-027 / FR-027a 多处依赖），fallback 文本本身也是合法 active 节点；(2) 不阻塞应用启动，单用户产品 fail-closed 等价于"用户被迫去定位 seed 文件路径"，体验差；(3) fallback 文本明确写出"请联系开发者"——开发者错误被暴露给用户感知，但不强制阻断用户进度；(4) 用户后续可通过 SkillScreen 编辑该方法论（链根 origin = `system_bootstrap`，受 FR-027a 保护，编辑要走高危确认弹窗），编辑接力出 v2 替代 fallback 内容。同步修订点：FR-027 增加 fail-open with fallback 段；新增 FR-027b 显式定义 fallback 文本与 toast 行为；新增 SC-023 守卫测试覆盖三类 seed 失败场景。
- Q: 装备者数量的统计与显示口径是否包含 assistant 本体？ → A: **包含**——FR-040 / FR-041 / FR-029a 排序键中的"装备者数量" = 当前装备该方法论的 specialist 数量 + (assistant 本体是否装备 ? 1 : 0)，卡片显示、排序键、守卫测试断言统一按此口径。理由与 FR-014a / FR-015a / SC-013 已确立的"assistant 本体作为一种装备者"叙事一致；尤其链根 origin = `system_bootstrap` 的内置方法论默认仅装备到 assistant 本体（FR-014a 例外规则），若 FR-040 只统计 specialist 会导致这类方法论装备者数量永远显示 0，与"它实际默认装备到 assistant 本体"的事实冲突。同步修订点：FR-040 措辞由"已被多少 specialist 装备"改为"已被多少装备者（specialist + assistant 本体）装备"，与 FR-041 / SC-013 / FR-015a / Key Entities "装备者-Skill 装备关系" 的装备者定义对齐。
- Q: `load_skill_methodology` 工具在单轮派活内的调用次数是否设硬上限？ → A: **不设硬上限**。工具层不基于"本轮已 load 次数"拒绝调用——本 feature 不引入运行时调用计数门限，单轮内装备者可以反复 load 同一或不同 skill_id；上下文增长由 010 既有的压缩机制兜底，单轮 token 预算的可观察前置预防由 FR-016a 装备阶段的 token 计量条提供。引导"先看清单 trigger_conditions 再决定 load 哪条"的责任放在 LLM 提示工程层：(1) "如何创建方法论"内置方法论正文 / FR-027 seed MUST 同时强调"装备者不应在单轮内无差别 load 装备清单中的所有方法论，应按 trigger_conditions 判断后再选择性 load"；(2) assistant / specialist 自身角色定义层面亦可叠加引导。理由：(a) 与项目"决策放在 LLM、机械工具不做关键词/字符串匹配（含频次类）"哲学一致——硬上限是不可见的机械红线，会让 agent 摸不着边界（"为什么这次成功上次失败"难调试）；(b) 装备数量上限的可观察提示已在 FR-016a token 计量条层完成（装备阶段预防胜于运行时硬阻断）；(c) `load_skill_methodology` 是只读工具，没有写入副作用，过度调用最坏后果是单轮上下文膨胀，由 010 压缩机制吸收；(d) 三项统计计数（FR-041）会把"被加载次数 vs 被引用执行次数"的不对称暴露给用户作为该方法论是否"description-rich-body-thin"的诊断信号，从用户侧倒推 agent 是否在过度 load。同步修订点：新增 FR-017b 显式声明"工具层不基于调用计数拒绝"；新增 SC-024 守卫测试覆盖"单轮内连续多次 load 不被工具层拒绝"；FR-027 seed 文件必填段中追加"装备者应按 trigger_conditions 选择性 load"的引导义务。
- Q: SkillScreen active 列表"最近变更时间倒序"默认排序键中的"最近变更"指什么？ → A: **指该 asset 当前 active 版本的 `created_at`** ——即 supersede 链上最新一次内容产出（新建直接入库 / supersede 接力 / 用户编辑接力 / 外部导入）的入库时刻；**不**含装备关系变更（被装备 / 被卸下）、**不**含被加载或被引用执行的统计计数刷新时刻。语义 = "该方法论内容资产层最近一次被实质修改"。理由：(1) 与 FR-029a 已确立的四维度独立排序键分工对齐——"装备组合的近度"由"装备者数量倒序"负责，"被使用的近度"由"被加载次数倒序 / 被引用执行次数倒序"以及"最近 30 天未被引用过"筛选负责；本键专注于"内容生命周期最近一次动作"；(2) 与 FR-041a "统计计数沿 supersede 链继承"的资产视角对称——本键也用 asset 视角，但只看"内容产出"事件而不看"使用"事件；(3) 排序键语义易懂——用户在卡片上能直接对应到 supersede 链审计视图最新一条节点的时间戳。同步修订点：新增 FR-029b 显式定义"最近变更时间"= 当前 active 版本的 `created_at`；FR-029a 默认排序键描述中追加引用 FR-029b；SC-015 守卫测试断言中追加"默认排序键 = 当前 active 版本 created_at 倒序，与装备关系变更、统计计数刷新解耦"。
- Q: `origin` 字段的取值是否为封闭枚举？ → A: **封闭枚举，仅这 5 个值**——`system_bootstrap` / `user_edit` / `assistant_tool_call` / `specialist_tool_call` / `external_import`。持久化层用 CHECK 约束（或等价的枚举落地形式）禁止非枚举值落库；Repository 类型契约用 Literal Union（或等价的封闭类型）；任何尝试写入非枚举 origin 值的请求被业务层 / Repository 在写入前拒绝并返回错误（不静默吞掉、不降级为默认值）。理由：(1) FR-027a "按链根 origin 判定保护"与 FR-014a "system_bootstrap 例外按链根 origin 判定"是关键的状态机分支，依赖 origin 字段取值集合稳定——开放扩展会让"新出现的 origin 值要不要触发例外规则"变得不确定；(2) FR-042/043 marketplace 占位接口当前只声明、未实现，未来如需细分外部来源（如 `marketplace_v1` / `community_export`）应由独立 feature 显式扩展本枚举集并补对应守卫测试，而不是悄悄塞自由 string 在缝隙里跑；(3) 本期单用户产品收窄边界，未来开放也来得及；(4) 封闭枚举让 SkillScreen 审计视图"操作来源"展示能用穷尽 switch 渲染，不会出现"未知 origin"的兜底 UI 状态。同步修订点：新增 FR-006a 显式声明 origin 字段为封闭枚举集（含上述 5 个值），并明确各值的语义边界；新增 SC-025 守卫测试覆盖三类拒绝路径（业务层写入路径 / Repository 类型边界 / 持久化层 CHECK 约束）；Key Entities 的 Skill 资产 origin 描述同步加上"封闭枚举"修饰。
- Q: 装备关系的历史快照（"曾经装备过"的回看）是否保留？ → A: **装备关系永不物理删除**——N:M 装备关系表 MUST 带 `status` 字段（取值 `active` / `unequipped`，封闭枚举）+ `equipped_at` / `unequipped_at` 时间戳 + 操作来源字段（哪个事件 / 用户 触发的本次卸下，与 FR-006a origin 枚举语义无重合，独立标签集）。卸下 = 标 `unequipped` 而非删行；强制软删除自动裁剪同样标 `unequipped` 留行；审计视图能按 specialist / 方法论双向回看历史装备组合轨迹（"该 specialist 在某时间窗口装备过哪些方法论""该方法论曾被哪些 specialist 装备又卸下"）。再次装备同一对 (specialist, skill) 时**新建一行** `status = active`（保留旧 `unequipped` 行作为历史），不复用历史行。FR-011 supersede 路径"装备关系全部切到新版本"语义化为：旧版本上所有 `status = active` 的关系行标记为 `unequipped`（unequipped_at = supersede 时间 / 操作来源 = `supersede_transfer`），同事务内为新版本插入对应的 `status = active` 行；崩溃整体回滚。理由：(1) 与 CC-001 / FR-007 "大脑数据永不物理删除"的核心约束对齐——装备关系作为大脑层资产的次级关系应受同等审计 retention，否则"为什么这个 specialist 当年表现好 / 差"类回溯问题无法解答；(2) schema 复杂度可控（多 2 列 + 1 个 unique partial index 限制每对仅 1 行 `status = active`）；(3) Option B 在 FR-011 supersede 单事务内"切到新版本"语义下难以表达"曾经的快照状态"——回滚或并发场景信号会丢失；(4) 当前没有 retention 压力，未来若需冷存归档由独立 feature 加路径。同步修订点：新增 FR-014b 显式定义装备关系 status 状态机与"再装备不复用历史行"约束；CC-001 措辞扩展为"含装备关系"；FR-034 审计视图明确"双向历史装备轨迹"能力；Key Entities "装备者-Skill 装备关系"描述同步加上"永不物理删除、卸下即标 unequipped 留行"修饰；新增 SC-026 守卫测试覆盖卸下不删行 / 再装备不复用 / supersede 路径 status 切换 / 物理删除尝试被阻断。

## User Scenarios & Testing *(mandatory)*

主助理（assistant）当前已经具备"大脑 + 100% 调度 + 可复用专员"能力（010），但每个专员的工作方式还硬编码在它自己的角色定义里。本功能为助理引入一层独立的**方法论资产**——一个 specialist（以及 assistant 本体）可以装备多个方法论 skill（"做某件事时遵循的步骤"），同一方法论也可被多个装备者复用；方法论的创建能力以"一个工具 + 一份内置方法论"的组合形态默认挂在 assistant 调度层本体，用户在对话里说"把刚才这套做成方法论"时由 assistant 直接调工具写入并**直接 active 入库**，立刻可被装备使用；用户的纠错权力下放到事后——可随时在 SkillScreen 上编辑（等价于一次用户驱动的 supersede）或软删除。同时把现有用户能看到的"工具技能"术语整体改名为 "Tool"，把 "Skill" 术语让给方法论层，避免用户混淆。下面 5 个用户故事按交付优先级排列，每个都是一个可独立交付、可独立验证的增量切片。

### User Story 1 - "工具技能"术语腾位为 "Tool" (Priority: P1)

作为日常使用主助理的用户，我希望界面上的"Skill"始终指方法论（怎么做），而录制出来的工具能力改称 "Tool"（能做什么），这样在后续引入方法论层时不会被名字混淆。

**Why this priority**: 这是后面所有 story 的前置条件。如果不先把"Skill"这个词腾出来，后续 SkillScreen 与方法论资产的命名都会和现有"Skill Teaching / Skill List / Skill Composition"撞名，用户会同时听到两种"Skill"导致心智混乱。本身单独发布也是有价值的清理。

**Independent Test**: 升级到本版本后，打开主桌面 UI，原"Skill Teaching / Skill List / Skill Composition"三个主屏的导航文案、屏内标题、按钮文本、空态文案全部呈现 "Tool"；原有 teaching / list / composition 三块业务功能行为不回归。

**Acceptance Scenarios**:

1. **Given** 用户已升级到本版本，**When** 用户打开应用，**Then** 侧边导航不再有"Skill"字样指向工具技能，而是 "Tool Teaching"、"Tool List"、"Tool Composition"。
2. **Given** 用户已在旧版本中收藏了 `/skills` 路径，**When** 用户访问该旧路径，**Then** 系统重定向到新的 Tool List 路径，不返回 404。
3. **Given** 升级后首次打开应用，**When** 用户进入任一原 Skill 主屏，**Then** UI 一次性呈现"已将'Skill'重命名为'Tool'"的一次性提示，可关闭后不再出现。

---

### User Story 2 - 通过 assistant 创建方法论并事后纠错 (Priority: P2)

作为日常使用主助理的用户，我希望可以对助理说"把刚才那套做周报的流程做成方法论"，助理就用它自带的 `create_skill_methodology` 工具直接把流程提炼成 active 方法论入库；如果产出不够好，我可以随时在 SkillScreen 上编辑（每次编辑就是一次新版本）或软删除——纠错权在事后，不在事前。

**Why this priority**: 这是方法论层的最小可用切片。没有创建路径，方法论层就只是一个空架子。这一层独立可交付：用户能完整体验"对话请求 → assistant 自身调工具提炼 → 方法论 active 入库 → 自动装备到所有装备者"完整链路；后续的装备调整、修订都建立在"方法论已存在"的基础上。

**Independent Test**: 用户在与助理的对话里说"把刚才那件事做成方法论"，前端在 SkillScreen 列表区出现一张新的 active 方法论卡片（无需任何审核动作）；用户打开编辑器修改任一字段保存，旧版本进入 superseded 链节点、新版本成为当前 active；用户也可对一份 active 方法论执行软删除，使其落入 soft_deleted 终态。

**Acceptance Scenarios**:

1. **Given** 用户最近完成了一件可被提炼的工作（如周报），**When** 用户在对话里说"把刚才那套做成方法论"，**Then** assistant 调度层本体按其装备的"如何创建方法论"内置方法论指引，从该工作的素材中提炼内容并调用 `create_skill_methodology` 工具直接以 active 入库，通过非模态通知告诉用户"已新增方法论 X"。
2. **Given** SkillScreen 列表区已有一份新增的 active 方法论卡片，**When** 用户打开卡片，**Then** 用户能看到名称、描述、触发条件、所需工具、正文 Markdown，以及该方法论引用的素材来源（segment 摘要 + 链接）。
3. **Given** 用户对一份 active 方法论不满意，**When** 用户在 SkillScreen 编辑器中修改任一字段并保存，**Then** 系统把当前 active 版本切为 superseded、保存的内容成为新的 active 版本，装备它的所有 specialist（含 assistant 本体若装备）自动跟新到新版本；前端通过事件被动刷新。
4. **Given** 用户决定不再保留某份方法论，**When** 用户在 SkillScreen 对该方法论选"软删除"，**Then** 方法论落入 `soft_deleted` 终态、不再可见可装备，但物理记录保留可在审计视图查到（且若有装备者装备它，遵循 FR-012 的强制裁剪流程）。
5. **Given** assistant 或被授权的 specialist 尝试调用 `create_skill_methodology` 工具但没有提供任何素材来源 segment，**When** 调用发起，**Then** 工具拒绝执行并返回错误"至少需要 1 条来自 archive 或 failure 分区的素材"，调用方按指引重试。
6. **Given** 用户尚未打开 SkillScreen，**When** 一份新 active 方法论入库，**Then** 应用侧边导航的 Skill 入口显示"新增内容"未读提示。

---

### User Story 3 - 装备方法论给专员 (Priority: P3)

作为已经在用助理"专员"系统的用户，我希望可以把一份 active 的方法论装备给一个或多个固定专员，让这些专员在工作时按方法论行事；当我修改装备关系时，系统能告诉我哪些方法论缺哪些工具、哪些方法论已被哪些专员引用。

**Why this priority**: 这一层让方法论层"派得上用场"。没有装备机制，方法论就只是文档；有了它，专员的工作方式就可以由用户用方法论拼搭。它依赖 P2 的方法论已存在，所以排在 P3。独立可交付：装备 + 引用关系展示本身就是完整的工具感。

**Independent Test**: 用户在 SpecialistScreen 打开一个 specialist，进入"装备方法论"面板，可以多选 active skill 装备给它；保存后专员的 system prompt 已经按装备顺序列出装备清单条目（id + 名称 + 描述 + 触发条件），且专员在工作中调 `load_skill_methodology(skill_id)` 能拉到对应方法论正文；尝试软删除一个被引用的方法论时，系统先阻断并列出受影响专员。

**Acceptance Scenarios**:

1. **Given** 用户已经创建过若干 active 方法论，**When** 用户在 SpecialistScreen 打开任一专员的"装备方法论"面板，**Then** 用户能多选方法论装备给该专员，并设置装备顺序。
2. **Given** 用户为某 specialist 装备的方法论声明了"所需工具"，**When** 用户保存装备，**Then** 系统检查该 specialist 的工具白名单是否覆盖这些所需工具；若不覆盖则在装备 UI 上对该方法论标黄警告，但**仍允许**保存。
3. **Given** 一份方法论已被一个或多个装备者（specialist 或 assistant 本体）装备，**When** 用户试图在 SkillScreen 软删除它，**Then** 系统先阻断该删除操作，通过项目高危同步确认协议（`request_id + threading.Event + emit(request_id, message)`）触发非模态确认浮层，浮层列出"以下装备者装备了它：…"与受影响装备者数量摘要，要求用户二次确认是否强制移除（FR-020）。
4. **Given** 用户在确认浮层上选"强制移除"，**When** 后端处理删除请求，**Then** 系统在单事务内自动卸下所有受影响装备者上的该装备关系，并对每个受影响装备者发出"已更新"通知，方法论本身落入 `soft_deleted` 终态；用户若拒绝则整个删除请求取消、装备关系与方法论状态均不变。
5. **Given** 用户在某 specialist 上装备了方法论 A、B、C，**When** 主助理派活给该 specialist，**Then** 该 specialist 的 system prompt 已经按用户配置的顺序列出 A、B、C 三条装备清单条目（id + 名称 + 描述 + 触发条件，不含正文）；specialist 在工作中可按需调 `load_skill_methodology(skill_id)` 拉取任意一条的完整正文，工具 result 进入 messages 序列。

---

### User Story 4 - 方法论的修订与溯源 (Priority: P4)

作为长期使用方法论的用户，我希望可以让 assistant 把某条方法论改一版（supersede），新版本立即接管所有装备它的专员；过去的旧版本与素材来源仍可被回看，即使素材本身已被我删除，方法论本身不受影响。

**Why this priority**: 这一层让方法论可演化。它依赖 P2/P3 已稳定，所以排在 P4。独立可交付：修订 + 装备自动跟新 + 溯源降权显示本身就是完整的"方法论资产生命周期"体验。

**Independent Test**: 用户对助理说"把'周报生成'方法论改一版，让它多看 failure zone 里的失败案例"，assistant 通过 `create_skill_methodology` 工具的 supersede 模式产出新版 active 后，原装备该方法论的装备者自动跟新到新版本；查看旧版本时可看到素材链接，若该素材后续被软删除，旧版本仍可读但素材链接降权显示。

**Acceptance Scenarios**:

1. **Given** 一份 active 方法论 A 已被多个 specialist 装备，**When** assistant（或被授权 specialist）调用 `create_skill_methodology` 工具的 supersede 模式产出 A 的新版本，**Then** 旧版 A 状态切为 `superseded`、新版本成为 active，所有装备者的装备关系自动指向新版本，整个切换在单事务内完成。
2. **Given** 一份方法论引用了若干 segment 作为素材来源，**When** 其中某些 segment 被软删除，**Then** 方法论本身状态不变，溯源面板对应素材项显示"来源已删除"的降权样式，但仍可看到素材 ID 与摘要快照。
3. **Given** 一份方法论已经过多次 supersede 形成版本链，**When** 用户在审计视图按版本链回看，**Then** 用户能依次看到每一版的名称、描述、完整正文、以及与上一版的正文 diff 高亮对比，并附带当时的创建者（assistant 调工具产出 / 受权 specialist 调工具产出 / 用户编辑）、创建时间、变更原因。

---

### Edge Cases

- **"如何创建方法论" 自举死循环**：assistant 自身按"如何创建方法论"内置方法论指引来产新方法论；若该方法论持续 supersede 产出更糟的新版本，用户可在 SkillScreen 上对它直接编辑（等价于一次用户驱动的 supersede 接管自举链）；该内置方法论受 FR-027a 保护**沿 supersede 链整链传播**——只要版本链根节点 origin = `system_bootstrap`，无论后续被多少次接力（assistant 调工具 / 用户编辑 / 受授权 specialist 调工具），链上当前 active 版本始终受保护、不允许软删除（保证 assistant 任何时候都有可参照的创建指引）。
- **token 预算爆炸**：一个装备者（specialist 或 assistant 本体）装备过多方法论后，其 system prompt 中的装备清单条目数量随之增加；每条清单条目只是 id + 名称 + 描述 + 触发条件（远小于完整正文），但装备数量较大时仍可能逼近 token 预算上限。SpecialistScreen 各装备面板与 assistant 本体装备卡片顶部固定显示 token 计量条（FR-016a：当前装备条目数 + token 估算值 + 阈值染色，随勾选实时更新）让用户在调整装备过程中即时看到风险；不引入保存时弹窗或阻断。运行时如果装备者按需 load 大量方法论正文，messages 序列也会膨胀，但这属于运行时上下文管理而非装备配置问题，不在本 feature 处理。
- **同名/同触发条件冲突**：分两层处理。(1) **同名（`name` 精确字符串相等）由业务层硬拒绝**——`create_skill_methodology` 工具新建模式（非 supersede）在写入前检查全库是否已存在同名 active；存在则拒绝并在工具 result 返回错误（含已占用 id 与 name 提示）；用户在 SkillScreen 编辑器改 `name` 撞名时同样阻断（详见 FR-024a / FR-031）。Supersede 模式不走本检查（新版本与旧版本同名为常见形态）。(2) **同/近触发条件、近义内容、近似正文等"语义判重"由 assistant 提示工程兜底**——"如何创建方法论"内置方法论的正文 MUST 写明"创建前先扫装备清单，发现名称或触发场景重合时先与用户对齐"；业务层不做触发条件 list 元素相等检查、不做 LLM 相似度判定。整体哲学：硬约束只覆盖最便宜的一层（`name` 精确字符串），其它语义判重责任放在 LLM 提示工程层，与项目"决策放在 LLM、机械工具不做关键词/字符串匹配（trigger 判定 / 派活决策）"一致——`name` 精确字符串例外的理由是装备清单条目（FR-017）中 `name` 是 LLM 区分多条方法论的主要人类可读线索，允许同名 active 共存会让装备者大脑难以判断该 load 哪条。SkillScreen 列表 UI 不再有"同名视觉标签"——业务层已经把这种状态阻断在写入路径上，列表中不会出现同名 active 方法论。
- **素材 segment 处于 distilling/pending 中间态**：assistant 在素材尚未完成沉淀时引用它；本期允许引用但**不**记录额外的"素材当时处于过渡态"字段——FR-010 仅持久化 segment_id 与 zone 标注，过渡态状态由 segment 自身的状态机暴露给审计视图查询，避免在 brain_skill_source_segments 表上引入冗余快照字段（与项目"单用户未发布无外部脚本消费者，避免范围扩张"原则一致）。如未来用户在审计视图回看时反馈"难以辨别当时素材是否已沉淀完成"，由独立 feature 在 source segment 元数据层加快照字段。
- **用户绕过 assistant 试图让 specialist 创建方法论**：用户在 SpecialistScreen 试图直接对某个 specialist 下"创建方法论"指令；系统应在 UI 层就明确"创建方法论指令只能通过 assistant 对话路径下达，不能直派给 specialist"。
- **未授权 specialist 试图调工具**：某个未被授权 `create_skill_methodology` 工具的 specialist 在其工作流中尝试调用该工具，**Then** 工具调用被工具层鉴权拒绝（与现有 tool 白名单机制一致），并在 specialist 上下文中返回"无权限"错误。
- **并发 supersede 接力**：同一 active 方法论 X 在很短时间内被两条 supersede 流程相继产出新版本 v_a、v_b；先入事务者胜出（X → superseded、v_a → active、装备切到 v_a），后到者自动以"当前 active"为新基线接力（v_a → superseded、v_b → active、装备再切到 v_b），最终形成单向、无分叉的 supersede 链 X → v_a → v_b，每一次切换都在单事务内完成、崩溃整体回滚。
- **强制移除时受影响装备者中的 specialist 正在被派活**：用户对方法论选强制移除，但其中一个受影响装备者（specialist）此刻正在执行任务；裁剪装备关系不应影响当前执行轮，下一轮派活才生效。

## Requirements *(mandatory)*

### Functional Requirements

> **编号跳号说明**：以下小节中 **FR-019 / FR-028 / FR-035 / FR-035a / FR-036 / FR-037** 均为已删除编号——FR-019（"提升为专员"路径）见 Session 2026-05-27 删除澄清；FR-035–037（派活索引 / 渐进式披露）见 Session 2026-05-26 "assistant 派活时是否参考方法论装备关系或触发条件？" 删除澄清；FR-028 在迭代过程中合并入 FR-029。编号空缺保留以维护历史澄清链与原 FR id 引用稳定，不代表内容遗失。

#### 命名与术语（FR-001 ~ FR-005）

- **FR-001**: 系统 MUST 在主桌面 UI 上把现有的"Skill Teaching / Skill List / Skill Composition"三个主屏的导航与屏内文案统一改为对应的 "Tool" 版本。
- **FR-002**: 系统 MUST 保留对原 `/skills` 类前端路由的访问，并重定向到新的 Tool List 路径。
- **FR-003**: 系统 MUST 把原 `skills.*` 类对外通知名整体改为 `tools.*`（如 `skills.changed` → `tools.changed`），直接切换、不需要 deprecation 窗口或双发兼容（本产品为单用户、未发布、无外部脚本消费者）。
- **FR-004**: 系统 MUST 在术语切换后的首次进入"工具类"主屏时呈现一次性提示告知用户"已将 Skill 重命名为 Tool"，提示可关闭并不再出现。
- **FR-005**: 系统 MUST 在 SkillScreen / 方法论相关 UI 中只把 "Skill" 一词用于指代方法论资产，避免与 Tool 共用此词。

#### 方法论数据资产（FR-006 ~ FR-013）

- **FR-006**: 系统 MUST 把方法论作为大脑里与 specialist 平级的一等资产存储，具备名称、描述、触发条件、所需工具、正文、状态、版本、超越链、引用计数、统计计数（被加载次数 / 装备者数量 / 被引用执行次数，详见 FR-041）、素材来源、origin（创建来源，封闭枚举详见 FR-006a）、是否可见可装备等元数据。核心 5 字段（名称 / 描述 / 触发条件 / 所需工具 / 正文 Markdown）按 Anthropic Agent Skills 开放规范的 SKILL.md 形态对齐（≈ `name` / `description` / `when_to_use` / `allowed-tools` + body），便于通过 `load_skill_methodology` 工具按规范渲染与未来导入导出（FR-042/043）对接；扩展字段（状态 / 版本 / 超越链 / 素材来源 / 统计计数等）作为大脑层附加元数据，不进入 SKILL.md frontmatter，仅在 SQLite 内部持久化。**字段存储类型约束**：名称、描述、正文 Markdown 为单串文本；触发条件、所需工具为 list of strings（SQLite 用 JSON array 等价表示）；状态、版本号等为各自的标量类型。**字段必填约束**：名称、描述、正文 Markdown 与触发条件 list 均不允许为空——触发条件 list MUST 至少含 1 条非空 string 条目（执行点详见 FR-024b 工具层与 FR-031 用户编辑器层）；所需工具 list 允许为 0 条（纯文档/思考类方法论确实可能不依赖任何工具）。
- **FR-006a**: 系统 MUST 把方法论 `origin` 字段约束为**封闭枚举**，仅允许以下 5 个取值，且各值语义边界如下：
  - `system_bootstrap` — 由系统迁移脚本读取 seed 文件（或 FR-027b fallback 文本）以 active 入库的内置方法论的初始版本节点 origin；FR-027a / FR-014a 例外规则的"链根 origin"判定锚点。
  - `user_edit` — 用户在 SkillScreen 编辑器保存某条方法论触发的 supersede 接力新版本的 origin。
  - `assistant_tool_call` — assistant 调度层本体调用 `create_skill_methodology` 工具产出的新版本 origin（无论是新建模式还是 supersede 模式，本字段如实记录"是 assistant 调度层本体调的"这个事实）。
  - `specialist_tool_call` — 被授权 specialist 调用 `create_skill_methodology` 工具产出的新版本 origin（同上记录"是某个 specialist 调的"这个事实）。
  - `external_import` — 通过 FR-042/043 占位接口（本期未实现）从外部来源导入的方法论 origin；本期不允许写入。
  
  持久化层 MUST 用 CHECK 约束（或等价枚举落地形式）禁止非枚举值落库；Repository 类型契约 MUST 用 Literal Union / Enum 等封闭类型；任何尝试写入非枚举 origin 值的请求 MUST 在写入前被业务层 / Repository 拒绝并返回错误（不静默吞掉、不降级为默认值）。未来扩展枚举集（如细分 marketplace 来源）必须由独立 feature 显式修订本条 + 补对应守卫测试 + 补 FR-027a / FR-014a 例外规则的影响评估；本期不留任何"开放扩展槽位"。守卫测试覆盖详见 SC-025。
- **FR-007**: 系统 MUST 保证方法论数据**永不物理删除**：拒绝、软删除、被超越都通过状态字段表达，物理记录保留。
- **FR-008**: 系统 MUST 支持方法论的状态机：方法论创建即 `active`；`active → (superseded | soft_deleted)`；`superseded` 与 `soft_deleted` 为非终态可观测的历史/失效形态（不再恢复为 active，但保留物理记录与版本链可被审计回看）。系统**不**引入 `draft` 或 `rejected` 中间态。
- **FR-009**: 系统 MUST 保证**全库内同名（`name` 字段精确字符串相等）至多一条 active 方法论**；同名的历史非 active 版本（superseded / soft_deleted）允许多条共存。检查只看 `name` 字段精确相等，**不**比较触发条件、所需工具、正文等其它字段；硬约束的具体执行点在 FR-024a。
- **FR-010**: 系统 MUST 为每个方法论保留素材来源（一个或多个 segment ID，且每条素材附带其来源 zone 标注，取值仅限 `archive` 或 `failure`）和当时的会话 ID，用于审计与溯源。
- **FR-011**: 系统 MUST 在方法论被 superseded 时把所有装备关系**在 supersede 操作的同一事务里**自动从旧版本切到新版本，崩溃则整体回滚（无论 supersede 来源是 assistant / 被授权 specialist 调用 `create_skill_methodology` 工具，还是用户在 SkillScreen 编辑器的直接编辑）。
- **FR-011a**: 系统 MUST 按 first-writer-wins 接力规则处理并发 supersede——当两条 supersede 流程几乎同时作用于同一 active 目标 X：先入事务者胜出（X → superseded、v_a → active、装备切到 v_a）；后到者自动把"当前 active"重定向为 v_a 作为新基线，再以新基线接力执行（v_a → superseded、v_b → active、装备再切到 v_b）。最终形成单向、无分叉的 supersede 链（X → v_a → v_b → …），每一次接力切换都必须在单事务内完成，崩溃整体回滚。
- **FR-012**: 系统 MUST 在方法论被强制软删除时，**自动**裁剪~~所有 specialist 上~~所有装备者（specialist + assistant 本体）上对该方法论的装备关系。
- **FR-013**: 系统 MUST 把方法论的元数据与正文持久化在大脑的 SQLite 持久化层中，不写入 DuckDB 录制库或配置文件。

#### 装备关系与专员（FR-014 ~ FR-020）

- **FR-014**: 系统 MUST 支持一个装备者（specialist 或 assistant 调度层本体）装备 0..N 个 active 方法论，一个方法论可被 0..N 个装备者装备（N:M）。装备的语义是"该方法论会出现在装备者的轻量清单里供其选择是否加载"（详见 FR-017），不是"方法论正文被直接拼进装备者的 system prompt"。assistant 本体作为一种特殊装备者，按相同协议处理其装备清单注入，不出现在任何 specialist 的清单或上下文中。
- **FR-014b**: 系统 MUST 保证装备关系（specialist 或 assistant 本体与 skill 之间的 N:M 关系行）**永不物理删除**：装备关系表 MUST 带 `status` 字段（封闭枚举 `active` / `unequipped`）+ `equipped_at` / `unequipped_at` 时间戳 + `unequipped_reason`（操作来源标签，取值含 `user_unequip` / `force_remove_on_soft_delete`（来自 FR-020 强制移除）/ `supersede_transfer`（来自 FR-011 supersede 切版本）等，与 FR-006a 的 skill `origin` 枚举语义独立、不复用同名 token）。**写入约束**：(a) 卸下 = 把 `status` 从 `active` 改为 `unequipped` 并写 `unequipped_at` + `unequipped_reason`，不删行；(b) 强制软删除路径（FR-020）裁剪装备关系同样标 `unequipped`，留行可审计；(c) FR-011 supersede 切版本路径在同事务内把旧版本上所有 `status = active` 行标记为 `unequipped`（`unequipped_reason = supersede_transfer`），并为新版本插入对应的 `status = active` 新行——崩溃整体回滚；(d) 再次装备同一对 (装备者, skill) 时**新建一行** `status = active`（保留所有历史 `unequipped` 行），不复用 / 不更新历史行；(e) 数据库层 MUST 用 unique partial index（或等价约束）限制"每对 (装备者, skill) 至多 1 行 `status = active`"，避免重复装备状态；(f) 任何对装备关系行的物理 DELETE 尝试（API / Repository / 直连 SQL 三层）MUST 被守卫测试覆盖拒绝（与 SC-008 同模式）。**审计视图**：FR-034 审计视图基于该状态机能按 specialist / skill 双向回看历史装备组合轨迹（"该 specialist 在某时间窗口装备过哪些方法论""该方法论曾被哪些装备者装备又卸下"）。守卫测试覆盖详见 SC-026。
- **FR-014a**: 系统 MUST 在以下两类事件中**默认全装备**，但**排除链根 origin = `system_bootstrap` 的方法论**（详见下文例外规则）：(1) 新建一个 specialist 时，系统自动把当时所有 active 方法论按其创建时间升序装备到该 specialist，装备顺序追加在末尾；(2) 一个方法论变为 active 时（新建直接 active、supersede 接力后的新版本、用户编辑接力后的新版本、外部导入直接 active），系统自动追加装备到所有现有 specialist 与 assistant 本体，对 supersede / 编辑接力场景与 FR-011 的"装备关系自动从旧版本切到新版本"合并在同一事务内处理（已装备旧版本者切到新版本而非追加，未装备者新增装备到末尾）。**链根 origin = `system_bootstrap` 的方法论例外规则**：这类方法论变为 active 时**只**自动装备到 assistant 本体，**不**追加装备到任何 specialist；新建 specialist 的默认全装备快照同样**剔除**所有链根 origin = `system_bootstrap` 的方法论。例外按"版本链根 origin"判定（与 FR-027a 对称），链上后续版本（如 `user_edit` 接力的 v2）即使自身 origin 字段不是 `system_bootstrap`，只要链根是 `system_bootstrap` 仍继承本例外。用户可在 SpecialistScreen / "Assistant 调度层（本体）" 装备面板上随时卸下任意条不需要的装备关系；也可对个别 specialist **主动**装备某个 `system_bootstrap` 方法论（与主动授权 `create_skill_methodology` 工具配套使用），主动装备的关系在该方法论后续 supersede 时按 FR-011 同样自动跟新到新版本、不被本例外规则撤销。卸下的关系在该方法论下一次 supersede / 编辑接力时**不**自动复装。
- **FR-015**: 系统 MUST 让用户可在 SpecialistScreen 上对每个 specialist 的装备方法论排序，排序决定其 system prompt 中**装备清单条目**（id + 名称 + 描述 + 触发条件，不含正文）的列出顺序。
- **FR-015a**: 系统 MUST 在 SpecialistScreen 顶部固定显示一张"Assistant（主助理本体）"装备卡片，让用户使用与 specialist 一致的装备面板（多选 active 方法论、设置装备顺序、所需工具警告、保存）管理 assistant 本体装备的方法论清单；该卡片的数据约束与 specialist 完全一致（FR-014/016/017/018），唯一区别是不可被删除或重命名（assistant 本体始终存在）。
- **FR-016**: 系统 MUST 在装备 UI 上对"该方法论所需的工具"是否在该 specialist 的工具白名单内做检查；不在时显示警告，但不阻断装备保存。
- **FR-016a**: 系统 MUST 在 SpecialistScreen 各装备面板顶部（含 FR-015a 的 assistant 本体卡片）固定显示 token 计量条，包含三项可观察事实：(1) 当前装备总条目数；(2) system prompt 中装备清单注入区段的 token 估算值；(3) 按阈值分段的颜色染色（健康 / 警示 / 危险）。计量条 MUST 随用户勾选/卸下、调整装备顺序、新增/移除装备实时更新（前端本地估算即可，不要求每次后端 round-trip）。阈值数值与 token 估算公式由 plan 阶段确定。计量条仅作可观察事实展示——**不**引入保存时弹窗确认、**不**引入超阈值阻断保存；最终判断权始终在用户。
- **FR-017**: 系统 MUST 在装备者（specialist 或 assistant 本体）被派活时，按用户配置的装备顺序，把它当前装备的所有 active 方法论的**轻量清单条目**注入到该装备者的 system prompt；每条清单条目包含 id、名称、描述、触发条件，**不含**正文 Markdown。方法论正文不进入 system prompt，由装备者在工作过程中调用 `load_skill_methodology(skill_id)` 工具按需拉取（FR-017a），工具 result 落入该装备者的 messages 序列。清单条目与工具 result 的形态对齐 Anthropic Agent Skills 规范的 SKILL.md frontmatter + body 二段式（"名称/描述/触发条件/所需工具" ≈ `name`/`description`/`when_to_use`/`allowed-tools`，正文 = body）。
- **FR-017a**: 系统 MUST 提供 `load_skill_methodology(skill_id)` 工具用于装备者在工作过程中按需拉取方法论正文：默认装备给所有装备者（specialist + assistant 本体），无白名单约束（只读、无写入风险）；工具 result 为该方法论的 SKILL.md 形态文本（YAML frontmatter + Markdown body，对齐 Anthropic Agent Skills 规范）；传入的 skill_id 必须在调用方当前装备清单内，否则工具拒绝并返回错误（防止越界访问未装备的方法论）；传入的 skill 已 `soft_deleted` 或 `superseded` 时同样拒绝；调用只读、不影响方法论状态机；每次成功返回使该方法论的"被加载次数" +1（详见 FR-041）。
- **FR-017b**: 系统 MUST **不**对 `load_skill_methodology` 工具设置单轮调用次数硬上限——工具层不基于"本轮已 load 次数"拒绝调用，装备者在单轮内可反复 load 同一或不同 skill_id（每次成功返回均按 FR-041 计数 +1）。单轮 token 增长由 010 既有上下文压缩机制兜底；装备阶段的 token 风险前置预防由 FR-016a 装备 UI 的 token 计量条提供；"装备者应按 trigger_conditions 判断后再选择性 load、不应单轮无差别 load 整个装备清单"的引导责任放在 LLM 提示工程层（"如何创建方法论"内置方法论 seed 文件正文 MUST 写明此引导义务，详见 FR-027）。理由与项目"决策放在 LLM、机械工具不做关键词/字符串匹配（含频次类）"哲学一致——硬上限是不可见红线、会让 agent 摸不着边界。守卫测试覆盖详见 SC-024。
- **FR-018**: 系统 MUST 拒绝把非 active（superseded / soft_deleted）方法论装备给任何 specialist；现有装备指向的方法论被 supersede 时由 FR-011 自动跟新。
- **FR-020**: 系统 MUST 对装备关系做引用计数：用户在 SkillScreen 软删除被一个或多个装备者（specialist 或 assistant 本体）装备的方法论时，**MUST 走项目高危同步确认协议**（沿用 `request_id + threading.Event + emit(request_id, message)` 与 FR-027a 编辑保护、004 高危确认浮层同协议；CLAUDE.md 第 9 条硬规则）——后端 Service 在删除路径阻塞等待用户决策，UI 用非模态浮层展示受影响装备者名单与当前装备者数量摘要；用户拒绝即取消整个删除请求；用户确认后在**单事务内**执行装备关系裁剪 + 方法论落 `soft_deleted`，崩溃整体回滚（避免出现"已落 soft_deleted 但装备未裁剪"的不一致中间态）。FR-027a 受保护方法论本身不允许走此路径（FR-027a 已禁止软删除，UI 上不出现软删除入口、Service 拒绝软删除请求）。Supersede 路径不走本确认协议——由 FR-011 的事务自动跟新装备关系，无需用户二次确认。

#### 创建能力下放（FR-021 ~ FR-027a）

- **FR-021**: 系统 MUST 把"创建方法论"能力实现为一个工具 `create_skill_methodology`（支持新建与 supersede 两种模式），由工具层鉴权；调用方需在自己的工具白名单内拥有此工具才可调用。
- **FR-022**: 系统 MUST 让用户**不能**绕过主助理直接对某个 specialist 下"创建方法论"指令；所有"创建 / 修订方法论"的对话路径都必须经 assistant 处理（由 assistant 自己调工具，或 assistant 派给被授权的 specialist）。SpecialistScreen UI 上不得提供"对某 specialist 直接下创建方法论指令"的入口。
- **FR-023**: 系统 MUST 让 `create_skill_methodology` 工具产出的方法论**直接以 active 入库**，无需用户事前审核；唯一例外是 FR-024a 的全库同名 active 拒绝（仅 `name` 精确字符串相等触发，其它语义判重不做）。其余情况下用户的纠错权力下放到事后（FR-031 的编辑等价于一次用户驱动的 supersede；FR-012 的软删除）。
- **FR-024**: 系统 MUST 要求 `create_skill_methodology` 工具调用至少绑定 1 条素材来源 segment，且每条素材必须来自 `archive` 或 `failure` 分区（其它分区的 segment 不可作为素材来源）；缺少素材或引用了不允许分区的 segment 均拒绝调用并返回错误。
- **FR-024a**: 系统 MUST 在 `create_skill_methodology` 工具**新建模式**（非 supersede 模式）写入前检查全库是否已存在 `name` 字段精确字符串相等的 active 方法论；存在则拒绝调用并在工具 result 中返回错误（含已占用 id 与 name，提示"请改名或先与用户确认合并/择一"），不写入任何数据。检查只比较 `name` 字段精确相等，**不**比较触发条件 list 元素、**不**比较所需工具 list、**不**比较正文 Markdown、**不**调用 LLM 做相似度判定——其它语义判重责任放在 assistant 的"如何创建方法论"提示工程层（FR-027 / Edge Case "同名/同触发条件冲突"）。Supersede 模式不走本检查（新版本与旧版本同名是 supersede 的常见形态）。用户在 SkillScreen 编辑器修改 `name` 字段保存时同样适用本检查；撞名则保存被拒、UI 给出错误提示并附已占用同名的 active 方法论 id 链接（详见 FR-031）。本条是 SC-019 的唯一硬约束例外。
- **FR-024b**: 系统 MUST 在 `create_skill_methodology` 工具调用的 args 校验阶段拒绝 `trigger_conditions` 为空 list（含 0 条或 list 内全为空 string）的请求，返回错误"至少需要 1 条非空触发条件"，不写入任何数据。此校验对新建与 supersede 两种模式均生效（保证 supersede 后的新版本同样满足必填约束）。所需工具 list 允许为空（FR-006）；本校验只针对触发条件。守卫测试覆盖详见 SC-022。
- **FR-025**: 系统 MUST 默认把 `create_skill_methodology` 工具与 "如何创建方法论" 内置方法论装备在 assistant 调度层本体；所有 specialist 默认**不**装备这两件资产，因此默认无写方法论能力。"如何创建方法论"作为链根 origin = `system_bootstrap` 的方法论本身就是 FR-014a 默认全装备规则的例外（详见 FR-014a 例外规则），与本条 FR-025 一致。用户可在 SpecialistScreen 主动为某个 specialist 授权这两件资产（工具白名单 + 方法论装备）；被授权后该 specialist 才能调工具创建方法论。其它未授权 specialist 仅能通过查询工具读取方法论。SkillScreen 上对 active 方法论的"编辑 / 软删除"是用户主导操作、走专门的用户 Service 入口，不算 specialist 写权限、不需要工具授权。
- **FR-026**: 系统 MUST 在新 active 方法论入库或被 supersede 出新版本时通过事件通知前端，前端在 SkillScreen 列表区被动刷新（确定性硬约束）。同时 assistant 调度层在对话回复路径上 SHOULD 通过角色 prompt 引导其在工具产出新 active / 新版本后向用户回复"已新增 / 更新方法论 X"作为可见反馈——此 SHOULD 项属 LLM 行为引导而非守卫测试硬约束，落点在 `assistant_prompt.py` 与 "如何创建方法论" seed 文件正文，不要求自动化测试断言具体 LLM 输出。
- **FR-027**: 系统 MUST 提供一份名为 "如何创建方法论" 的内置 active 方法论，其初始正文必须以独立的 seed 文件形式存放在代码库中（迁移脚本只读取该 seed 文件并写入大脑，不内嵌长文本），由系统迁移以 active 入库并默认装备到 assistant 调度层本体；它的后续修订同样走 supersede 路径直接生效（与其它方法论一致，无单独审核步）。**seed 文件正文 MUST 明确写明判重义务**：assistant（或被授权 specialist）在调 `create_skill_methodology` 之前，先扫描自己 system prompt 里的装备清单条目（FR-014a 默认全装备保证清单包含所有当时 active 的方法论），如果发现名称或触发场景与现有方法论高度重合，必须先在对话里与用户对齐"要不要合并/择一"再决定是否产出新方法论——业务层不做这类判重，全部责任在 assistant 的提示工程里。**seed 文件正文还 MUST 写明 load 节制义务**（与 FR-017b 工具层无硬上限配套）：装备者在调 `load_skill_methodology` 之前先读装备清单条目里的 trigger_conditions list，按本轮上下文判断哪些方法论的触发场景真命中再选择性 load 对应正文；不应单轮无差别 load 整个装备清单的所有方法论，避免 messages 序列被冗余正文撑爆。
- **FR-027b**: 系统 MUST 在 seed 文件读取失败（文件缺失 / 内容为空 / IO 异常 / 编码错误）时采用 **fail-open with fallback** 策略：迁移用代码内硬编码的最小 fallback 文本作为该方法论的正文以 origin = `system_bootstrap` 写入大脑作为 active，迁移成功完成不阻塞应用启动。Fallback 文本 MUST 明确写明"该方法论的 seed 文件未能正确加载，当前为系统应急 fallback 版本，请联系开发者修复 seed 文件，或在 SkillScreen 上手动编辑此方法论以恢复完整指引"，并保留最小限度的判重义务说明（"创建前先扫描装备清单条目，发现重合先与用户对齐"）以保证 assistant 在 fallback 状态下仍有可用的创建指引底线。应用启动后 MUST 通过 non-blocking toast 提醒用户"如何创建方法论 seed 文件读取异常，已用 fallback 版本，请检查 seed 文件或在 SkillScreen 编辑修复"。Fallback 写入版本与正常 seed 写入版本在数据层同等对待——同样受 FR-027a 保护（链根 origin = `system_bootstrap`），同样可被后续 supersede 接力替换（用户编辑或开发者修复 seed 后再次迁移时如检测到当前 active 仍为 fallback 版本，可触发一次自动 supersede 用真实 seed 内容覆盖；若 active 已被用户编辑接力出 v2 及以上，则尊重用户的修订不再自动覆盖）。守卫测试覆盖详见 SC-023。
- **FR-027a**: 系统 MUST 保护**整条 supersede 链可追溯到 origin = `system_bootstrap` 根节点**的内置方法论不可被软删除——SkillScreen 上对该方法论隐藏"软删除"操作，对应 Service 入口拒绝软删除请求；但允许通过 supersede 接力修订其内容，且任何时刻必须有该方法论的某个版本处于 active，以保证 assistant 永远具备创建方法论的指引。**保护按"版本链根 origin"判定，不按"当前 active 版本的 origin"判定**：用户编辑等接力路径产出的新版本即使其自身 origin 字段为 `user_edit`，只要其 supersede 链可回溯到 `system_bootstrap` 根节点，仍受 FR-027a 完整保护；原始 origin 字段如实记录每次产出来源用于审计，不被链根判定覆盖。**用户在 SkillScreen 编辑器中保存对受保护方法论的修改时，系统 MUST 在保存前触发高危确认弹窗（沿用项目现有 `request_id + threading.Event + emit(request_id, message)` 同步确认协议），提示"修改此内置方法论将影响所有后续方法论创建行为，确定？"；用户拒绝即取消保存，用户确认后走与普通方法论一致的用户编辑 supersede 接力路径。assistant 与受授权 specialist 通过 `create_skill_methodology` 工具对该方法论做 supersede 时不走此 UI 确认（不属于 UI 高危路径），仍然受常规 supersede 事务约束。**

#### 用户管理与编辑（FR-029 ~ FR-034）

- **FR-029**: 系统 MUST 提供 SkillScreen 双视图：active 方法论列表、审计视图（含 superseded / soft_deleted 历史与版本链）。
- **FR-029a**: 系统 MUST 在 SkillScreen active 列表提供以下排序与筛选能力，所有数据来源于 FR-041 累计的统计计数：
  - 排序模式（用户可切换，**4 种**）：(1) 最近变更时间倒序（默认，"最近变更"定义详见 FR-029b）；(2) 被加载次数倒序（找 agent 经常拉详情的）；(3) 被引用执行次数倒序（找真按它走的高频）；(4) 装备者数量倒序（找最广用）。排序键集与卡片显示的三项计数 + 时间维度对齐，让用户在任一独立维度都能直接排序定位（包括"被加载高但被引用低"这类 description-rich-body-thin 异常方法论）。
  - 筛选模式（用户可叠加）：(1) "从未被引用执行过"（被引用执行次数 = 0）；(2) "最近 30 天没被引用过"（最近一次被引用执行时间早于当前时间 30 天前）
  - 每张方法论卡片 MUST 直接显示三项计数（被加载次数、装备者数量、被引用执行次数）让用户一眼判断价值
- **FR-029b**: 系统 MUST 把 FR-029a 排序键中的"最近变更时间"定义为 **该 asset 当前 active 版本的 `created_at`** ——即 supersede 链上最新一次内容产出（新建直接入库 / `create_skill_methodology` 工具 supersede / 用户编辑接力 / 外部导入）的入库时刻。该时间**不**因下列事件刷新：(a) 装备关系变更（装备者新增 / 卸下）；(b) `load_skill_methodology` 工具被调用（被加载次数 +1 不刷新本时间）；(c) reply 元数据 `skills_referenced` 字段触发被引用执行次数 +1（不刷新本时间，但同时刷新 FR-041 / FR-029a 筛选用的"最近一次被引用执行时间"——这是独立时间戳）；(d) 卡片显示统计计数刷新。换言之，"最近变更时间"专属于内容生命周期（supersede 链节点产生）；"最近一次被引用执行时间"专属于使用生命周期（reply 元数据触发）；两者是独立的两个时间戳，分别支撑 FR-029a 的默认排序与 FR-029a 的"最近 30 天未被引用"筛选，互不串扰。语义对应到 SkillScreen 审计视图：用户按"最近变更时间倒序"看到的第一条方法论，在审计视图打开后链上最新节点的时间戳与卡片显示一致。
- **FR-030**: 系统 MUST 在 SkillScreen 的 active 列表与编辑器中，为每份方法论提供"编辑"和"软删除"两个用户操作。**编辑保存路径分两种**：(1) 普通方法论（链根 origin ≠ `system_bootstrap`）保存按钮按下即立即走用户驱动的 supersede 接力，旧版本切 superseded、新版本入库 active、所有装备者的装备关系在同一事务内跟新到新版本（与 FR-011 事务约束一致），**无任何 UI 二次确认弹窗**；前端通过非模态浮层告知"已生成 v_N"。(2) FR-027a 受保护方法论（链根 origin = `system_bootstrap`）保存前 MUST 触发高危确认弹窗（详见 FR-027a），用户确认后才走同一 supersede 接力。**软删除路径**统一走 FR-012 / FR-020 的引用阻断 + 高危同步确认 + 强制裁剪流程（无论是否受保护——FR-027a 已禁止受保护方法论走软删除）。崩溃场景下编辑事务整体回滚。
- **FR-031**: 系统 MUST 让用户在编辑器中可修改名称、描述、触发条件、所需工具、正文 Markdown 五个字段；状态机字段、引用计数等系统字段只读。**"触发条件"字段的 UI 控件 MUST 为 list editor（支持 add/remove/reorder bullet 条目），不得用单 textarea**——因为存储形态为 list of strings（详见 FR-006 / Assumption）；"所需工具"同样为 list editor（每条对应一个工具名）。其它三字段为单行/多行文本输入。**字段必填约束执行点**：编辑器保存按钮在 "名称 / 描述 / 正文 Markdown" 任一为空、或 "触发条件 list" 为空（0 条或全为空 string）时 MUST 灰显或拒绝保存，对应错误提示明示具体缺失字段（与 FR-024b 工具层校验对称，保证用户编辑入口与工具入口的字段约束一致）；所需工具 list 允许为空，不阻断保存。修改名称字段时如撞到 FR-024a 定义的全库同名 active（`name` 精确字符串相等），保存被拒、UI 显示错误提示并附已占用同名的 active 方法论 id 链接，用户改名后才能继续保存；其它字段（触发条件 / 所需工具 / 描述 / 正文）的修改不受同名约束（与 FR-024a 哲学一致：业务层只锁名称精确字符串这一层）。
- **FR-032**: 系统 MUST 在前端通过事件被动刷新 SkillScreen 与 SpecialistScreen，避免用户手动重载。
- **FR-033**: 系统 MUST 让有未被用户查看过的新增 / 修订 active 方法论时，应用侧边导航的 Skill 入口显示未读提示；用户进入 SkillScreen 后自动清零。
- **FR-034**: 系统 MUST 提供方法论审计视图：按时间倒序展示状态变更历史、每次变更的操作来源（assistant 调工具产出 / 受权 specialist 调工具产出 / 用户编辑 / 用户软删除 / 装备关系跟新 / 等）、操作时间、变更原因。**装备关系历史维度**：审计视图 MUST 基于 FR-014b 装备关系状态机的留行约束，提供"该方法论曾被哪些装备者装备又卸下、各次装备 / 卸下时间与来源"的双向历史回看；同样支持 SpecialistScreen 上"该装备者历史装备组合轨迹"反向视图（"某 specialist 在某时间窗口装备过哪些方法论"），便于用户回溯"为什么当年这个装备者表现好 / 差"。装备关系卸下来源标签（`user_unequip` / `force_remove_on_soft_delete` / `supersede_transfer` 等，详见 FR-014b）作为审计视图过滤条件之一可见。

#### 溯源与可观测（FR-038 ~ FR-041）

- **FR-038**: 系统 MUST 在方法论查看视图中展示所有素材来源；素材 segment 处于 soft_deleted 状态时降权显示但仍可读到 segment ID 与摘要快照。
- **FR-039**: 系统 MUST 在方法论查看视图中展示版本链（按 supersede 关系），每节点可回看当时的名称 / 描述 / 完整正文；同时对相邻两版提供正文 diff 高亮对比视图，用户可在"完整正文"与"diff"两种展示之间切换。
- **FR-040**: 系统 MUST 在装备 UI 与 SkillScreen 卡片上显示该方法论已被多少**装备者**（specialist + assistant 本体；与 FR-014 / FR-014a / FR-015a / FR-041 的装备者定义一致）装备——口径为 "当前装备该方法论的 specialist 数量 + (assistant 本体是否装备 ? 1 : 0)"；本计数与 FR-041 的"当前装备者数量"、FR-029a 排序键 "装备者数量倒序"、SC-015 卡片显示项使用同一口径，被引用计数对用户透明（仅作 SkillScreen 卡片可观察事实展示，不暴露内部存储行数）。
- **FR-041**: 系统 MUST 让方法论累计三项统计计数：(1) **被加载次数**（装备者调用 `load_skill_methodology(skill_id)` 工具成功返回时 +1；人在 SkillScreen 详情、装备 UI 预览、审计视图等界面翻看**不** +1；工具调用失败（skill_id 不在装备清单、skill 已 `soft_deleted` 或 `superseded`）**不** +1；每次成功调用各算 1 次，无去重窗口；语义 = "agent 真主动想拉它的正文用"）；(2) 当前装备者数量（specialist + assistant 本体；随装备/卸下实时更新，不是累计而是当前值；语义 = "候选覆盖面"）；(3) 被引用执行次数（**复用 `memory_entries_referenced` 元数据惯例**：装备者在每轮 reply 结构化元数据里以 `skills_referenced: [skill_id, ...]` 字段显式列出本轮实际按了哪些方法论走，业务层在该轮 reply 落库时同步对列出的 skill 各 +1 并记录最近一次被引用执行时间用于 FR-029a 的"最近 30 天"筛选；字段缺失或格式错误本轮静默跳过、不报错重试；同一轮重复列出同一个 skill_id 按 1 次计；未列出的 skill 本轮**不** +1，**不**做"装备即引用"的兜底；语义 = "LLM 自报本轮真按它走了"）。**reply 元数据中的过时 / 已 `superseded` 的 skill_id MUST 按 supersede 链根 asset id 归一化后 +1 到该 asset 当前 active 版本**（fail-soft 归一化，与 FR-041a 资产视角对称——并发 supersede 边界场景下不丢失"真按它走了"的信号）；只有当链根 asset 已落 `soft_deleted` 终态时，本条引用按上文"字段格式错误本轮静默跳过"规则同等处理；同一轮 reply 中多条引用经归一化后指向同一 asset 仍按"同一轮重复列出按 1 次计"规则去重。三项计数形成「暴露 vs 候选覆盖 vs 真用」三维诊断视图，独立信号互补：被加载高 + 被引用低 = "agent 经常查阅但很少真按它走"，提示该方法论可能描述不清；被引用高 + 装备者数量低 = "少数装备者高频依赖"，提示可推广装备。这些计数直接暴露在 SkillScreen 列表与方法论卡片，支持 FR-029a 的排序与筛选；未来"高价值方法论提示"等衍生能力由独立 feature 在此基础上叠加。
- **FR-041a**: 方法论被 supersede 出新版本时（无论 supersede 来源是 assistant / 受授权 specialist 调工具产出，还是用户在 SkillScreen 编辑），新版本 MUST **完整继承**旧版本的被加载次数、被引用执行次数与最近一次被引用执行时间作为初始值，并在此基础上继续累计；装备者数量随 FR-011 的装备关系切换自然继承（旧版本的装备关系全部切到新版本）。SkillScreen 卡片显示的三项计数永远反映"该方法论从诞生至今的资产维度累积"，不是"当前版本独立累积"。

#### 市场对接占位（FR-042 ~ FR-043）

- **FR-042**: 系统 MUST 为"从外部来源导入方法论"保留**未来扩展锚点**，本期仅声明不实现。**锚点的具体落地形态 = (a) FR-006a `origin` 封闭枚举包含 `external_import` 取值 + (b) SC-025(e) 守卫测试覆盖"业务层拒绝来自 desktop_api 入口的 `external_import` 写入"路径**。本期不创建独立的导入契约 markdown 文件 / API endpoint / DTO，不允许任何 desktop_api 入口写入 `external_import`，避免范围扩张（与项目"单用户未发布无外部脚本消费者"原则一致）。未来 marketplace 等独立 feature 实现外部导入时再补对应契约文件 + endpoint + 入库前风控；本 feature 仅保留锚点不实施。
- **FR-043**: 系统 MUST 将"外部导入方法论未来默认直接 active 入库、如需 marketplace 风控则由独立 feature 加严"记录为未来 feature 的契约锚点；~~本期在接口契约中规定外部导入方法论可直接 active 入库~~。本期不创建可调用的导入接口、不创建额外导入 DTO、不引入 `draft` 中间态；SC-025(e) 是本期唯一验证点，用于证明合法枚举值 `external_import` 仍被当前业务入口拒绝。

### Key Entities *(include if feature involves data)*

- **Skill (方法论)**：大脑中的一类资产，描述"做某件事时遵循的步骤"。属性包括名称（单串）、描述（单串）、触发条件（list of strings）、所需工具（list of strings）、正文 Markdown（单串）、状态（active / superseded / soft_deleted）、版本号、超越链指向、素材来源、统计计数（被加载次数 / 装备者数量 / 被引用执行次数）、`origin`（创建来源，**封闭枚举**：`system_bootstrap` / `user_edit` / `assistant_tool_call` / `specialist_tool_call` / `external_import`，详见 FR-006a）、最近变更人、最近变更时间。核心 5 字段（名称 / 描述 / 触发条件 / 所需工具 / 正文 Markdown）的形态对齐 Anthropic Agent Skills 开放规范（SKILL.md = YAML frontmatter + body；本 spec 字段 ≈ frontmatter 的 `name` / `description` / `when_to_use` / `allowed-tools` + body；触发条件与所需工具内部为 list，导出 SKILL.md 时由导出层做"list → 规范期望形态"的转换）；其余扩展字段仅在大脑层 SQLite 持久化，不进入 SKILL.md frontmatter。一个 Skill 可被 0..N 个装备者装备。
- **装备者-Skill 装备关系**：连接装备者（specialist 或 assistant 调度层本体）与 Skill 的 N:M 关系，附带装备顺序、装备人、装备时间。**关系行永不物理删除**（受 CC-001 / FR-014b 约束）——卸下、强制移除自动裁剪、supersede 切版本均通过 `status` 字段（封闭枚举 `active` / `unequipped`）+ `unequipped_at` + `unequipped_reason`（封闭标签集 `user_unequip` / `force_remove_on_soft_delete` / `supersede_transfer` 等）表达；再次装备同一对 (装备者, skill) 时新建一行而非复用历史行；FR-034 审计视图基于该留行约束提供 specialist / skill 双向历史装备组合轨迹回看。
- **`create_skill_methodology` 工具**：方法论层的物理写入工具，支持新建与 supersede 两种模式；默认装备在 assistant 调度层本体的工具白名单，用户可在 SpecialistScreen 主动为个别 specialist 授权；调用方必须提供 ≥1 条来自 archive 或 failure 分区的素材来源。
- **如何创建方法论 (内置 active 方法论)**：随迁移以 active 入库的、版本初始为 1 的方法论；描述何时调 `create_skill_methodology`、怎么填字段、怎么选素材 zone 等最佳实践；初始正文来源于代码库中的独立 seed 文件；默认装备到 assistant 调度层本体；其 supersede 链根节点 origin = `system_bootstrap`，受 FR-027a 保护不可软删除，可通过 supersede 修订；**保护沿链传播**——后续接力产出的新版本（origin 为 `user_edit` 等）只要其 supersede 链可回溯到该 `system_bootstrap` 根节点，同样受保护。
- **素材来源 (Source Segment 引用)**：方法论持有的一组 segment 引用，每条引用附带"来源 zone"标注（`archive` 表示正例 / 成功 segment，`failure` 表示反例 / 失败 segment；二者皆可，其它分区不可），用于审计当时方法论是从哪些对话片段提炼而来以及是正例驱动还是反例驱动；segment 自身的存续不由本资产保证。

### Constraints & Compatibility *(include when relevant)*

- **CC-001**：大脑数据永不物理删除约束（来自 010）必须对方法论与其**装备关系**同等适用：方法论自身的拒绝、软删除、被超越都通过状态字段表达（FR-007 / FR-008）；装备关系行的卸下、强制移除自动裁剪、supersede 切版本同样通过 `status` 字段（FR-014b）表达，物理行始终保留可被审计访问。任何对方法论行或装备关系行的物理 DELETE 尝试（API / Repository / 直连 SQL 三层）都受守卫测试拒绝（SC-008 覆盖方法论行、SC-026 覆盖装备关系行）。
- **CC-002**：主助理 100% 调度约束（来自 010）必须保持：本 feature **不**引入"skill 工匠"这种固定专员；用户不能绕过 assistant 直接对某个 specialist 下"创建方法论"指令，所有创建/修订路径必须经 assistant 调度（由 assistant 自身调工具，或 assistant 派给被授权的 specialist）。
- **CC-003**：装备关系的修改对正在执行的派单轮**不生效**；最快从下一轮派单开始生效。系统不中断进行中的执行。
- **CC-004**：面向前端的事件必须经现有 UI Event Registry 公开契约注册后才能发出；本功能新增的事件不得绕过 Registry。Payload 不得包含方法论正文全文等大字段（前端走 API 详情接口取）。
- **CC-005**：现有"工具技能"（Skill Teaching/List/Composition）的录制层业务行为不得回归；本功能只改名、不改业务。
- **CC-006**：现有 "skills.*" 类对外通知直接整体改名为 "tools.*"，无需 deprecation 窗口或双发兼容。约束依据：本产品当前是单用户、未发布、无外部脚本消费者；保持简单优于为不存在的兼容场景预留路径。
- **CC-007**：本功能新增的数据资产必须通过大脑 Repository 边界访问；前端 / Tauri / desktop_api 层不得直接读写新增表。
- **CC-008**：本功能不得引入 subconscious 自动产出方法论的路径；subconscious 最多只能在未来作为"建议是否要做"的信号源，不在本 feature 范围内。

## Architecture Impact *(Mexemplar-specific)*

### Layer Impact

- [x] **UI** (`frontend/src/`, `src-tauri/`) — 新增 SkillScreen 双视图（active 列表 + 审计）与编辑器；Specialist 装备方法论面板；命名整顿（Tool 系列）与 /skills 路由 redirect；非模态"已新增 / 修订方法论"通知；侧边导航未读提示。
- [x] **Desktop API Bridge** (`src/desktop_api/`) — 新增方法论查询 / 用户编辑 / 用户软删除端点；`create_skill_methodology` 工具的物理写入由后端业务层 Service 处理，不暴露独立端点给前端直调；装备关系 CRUD 端点；UI Event Registry 新增方法论相关事件；把原 `skills.*` 类通知整体改名为 `tools.*`（直接切换，无双发兼容层）。
- [x] **Business** (`src/business/`) — 新增方法论 Service（含状态机、引用计数、强制删除阻断、supersede 接力 + 装备关系跟新；明确区分"`create_skill_methodology` 工具入口"与"用户 SkillScreen 写入入口"；含 `system_bootstrap` origin 的不可软删除保护；新建 specialist 时自动装备全部 active 方法论、新方法论入库时自动追加装备到所有现有 specialist 与 assistant 本体的"默认全装备 + 用户可卸"逻辑）；扩展 SpecialistService 在 system prompt 构建路径上**注入装备清单条目**（id + 名称 + 描述 + 触发条件，不含正文），并把方法论按需加载工具 `load_skill_methodology` 装备给所有装备者；扩展 assistant 调度层支持"作为装备者"装备方法论与拥有创建工具；新增"如何创建方法论"内置方法论的 bootstrap 路径（含 seed 文件读取 + FR-027b 定义的 fail-open with fallback 容错：seed 缺失/为空/IO 异常时用硬编码 fallback 文本入库为 active 并触发 UI toast，不阻塞应用启动）；新增"被加载次数 +1"路径在 load 工具调用成功返回时同步累计、"被引用执行次数 +1"路径复用 `memory_entries_referenced` 元数据惯例（`skills_referenced` 字段批量计数）。
- [x] **Data** (`src/data/`) — 新增大脑迁移版本：方法论表 + 装备关系表 + 索引；Repository 新增对应仓储；bootstrap 数据写入。
- [ ] **Execution** (`src/execution/`) — 不变。
- [ ] **Recording** (`src/recording/`) — 不变。
- [x] **Utils** (`src/utils/`) — 大概率新增方法论生命周期 blinker 事件用于跨模块通知；面向前端的事件仍走 UI Event Registry。

### Agent Impact

- 受影响 Agent: Assistant（默认装备 `create_skill_methodology` 工具与"如何创建方法论"内置方法论；其派活决策逻辑与 010 保持一致，不因方法论装备关系或触发条件而改变）。
- **不**新增固定 specialist（本 feature 不引入"skill 工匠"专员）。
- 不变：PM / Programmer / Trial 不在调度池内。
- 新增工具 / 工具组：(1) 方法论写入工具 `create_skill_methodology`（默认仅装备给 assistant 调度层本体，用户可主动授权给个别 specialist；负责新建与 supersede）；(2) 方法论按需加载工具 `load_skill_methodology(skill_id)`（默认装备给所有装备者，只读、无白名单约束；工具 result 为 SKILL.md 形态文本 = YAML frontmatter + Markdown body；调用方必须传入装备清单内、状态为 active 的 skill_id，否则拒绝；每次成功返回使被加载次数 +1）；(3) 方法论查询工具（用于 SkillScreen / 审计视图 / 装备 UI 的元数据读取，不进入装备者上下文，仅供后端 / desktop API 调用）。具体工具命名与 schema 在 plan 阶段定。
- 系统提示变化：specialist / assistant 本体的 system prompt 按用户配置的装备顺序注入装备清单条目（id + 名称 + 描述 + 触发条件，不含正文 Markdown）；方法论正文**不**进入 system prompt，由装备者调 `load_skill_methodology(skill_id)` 工具按需拉取，工具 result 进 messages 序列。清单条目与工具 result 的形态对齐 Anthropic Agent Skills 规范的 SKILL.md frontmatter + body 二段式。
- Reply 元数据扩展：specialist 与 assistant 本体的 reply 结构化元数据 schema 新增 `skills_referenced: [skill_id, ...]` 字段，复用既有 `memory_entries_referenced` 同构契约（业务层落库同步 +1、字段缺失静默跳过、未列出不 +1）。
- 调度变化：**派活决策本身不变**——assistant 派活仍按 specialist 职责定位选人，不读取方法论清单、不评估触发条件、不因装备关系调整偏好。方法论只在被派活的装备者**执行任务时**作为其装备清单条目（在 system prompt）与按需拉取的正文（在 messages）生效。

### Data Store Impact

- **SQLite** (`src/data/repos/`): 新增方法论表（含与大脑通用元数据对齐的字段）、N:M 装备关系表；新增对应仓储方法；写一次大脑 migration 版本。
- **DuckDB**: 不涉及。
- **Config**: 不引入需要持久化的配置；如有 token 预算阈值类参数，走大脑命名空间下的占位配置，本 feature 暂不暴露到 Settings UI。
- **Secrets**: 不涉及。

### Event Impact

- 新增大脑端 blinker 事件（具体命名在 plan 阶段定），用于：方法论创建（assistant 调工具产出 / 受权 specialist 调工具产出 / 外部导入）、被超越（含用户编辑接力）、被软删除、被装备关系跟新；以及面向 UI 的"删除被阻断"交互式事件用于阻断弹窗。
- 现有 `skills.*` 类 UI 事件整体改名为 `tools.*`，直接切换，无双发窗口。
- 现有 `brain_specialist_recruited` / `brain_specialist_changed` 类事件在装备关系自动跟新时复用。

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**：升级后用户在 30 秒内能在导航与主屏上识别"原 Skill 三屏已统一更名为 Tool"，无需打开文档。
- **SC-002**：用户从对话中说"把刚才做的事做成方法论"到 SkillScreen 列表区出现 active 方法论卡片的端到端时长 ≤ 30 秒（含 assistant 调度层调用 `create_skill_methodology` 工具时的 LLM 推理时间），失败时有明确错误提示而不是静默卡住。
- **SC-003**：用户在 SkillScreen 上编辑保存一份方法论后 ≤ 3 秒，skill 列表、版本链视图与所有装备它的 specialist 视图被动刷新到一致状态（新版本 active、旧版本 superseded、装备关系切到新版本）。
- **SC-004**：方法论入库后，在装备它的装备者（specialist 或 assistant 本体）之后的派活中，该方法论的轻量清单条目（id + 名称 + 描述 + 触发条件，**不含**正文）**已经**出现在该装备者的 system prompt 里；装备者在工作过程中调用 `load_skill_methodology(skill_id)` 时能拉到完整正文（YAML frontmatter + Markdown body 形态），可在调试视图查到 system prompt 注入内容与 messages 序列中的 tool result。
- **SC-005**：尝试软删除被引用的方法论时 100% 触发阻断弹窗（不出现"已删但装备者仍装备"的不一致状态）。
- **SC-006**：方法论被 supersede 后（无论来源是 assistant / 受权 specialist 调工具产出，还是用户 SkillScreen 编辑），所有原本装备旧版本的装备者（specialist + assistant 本体）在事务提交后 100% 指向新版本，无残留指向旧版本的装备关系；崩溃场景下事务回滚使新旧版本均未生效。
- **SC-007**：本 feature 上线后，现有"工具技能"录制 / list / composition 三块业务的端到端 e2e 用例**全部**通过（命名整顿不带来业务回归）。
- **SC-008**：本 feature 上线后，物理删除方法论行的尝试在守卫测试中被 100% 阻断（包括 API、Repository、直连 SQL 三条路径）。
- **SC-009**：本 feature 上线后，未在工具白名单内拥有 `create_skill_methodology` 工具的任何 specialist 调用该工具被 100% 阻断（默认情况下只有 assistant 调度层本体与用户主动授权过的 specialist 能调用）；用户 SkillScreen 上的编辑 / 软删除走专门用户 Service 入口，与工具鉴权解耦。
- **SC-010**：本 feature 上线后，`create_skill_methodology` 工具在没有素材来源或素材来自非 `archive`/`failure` 分区时调用 100% 被拒绝（不允许创建凭空方法论或引用不允许分区的素材）。
- **SC-011**：本 feature 上线后，旧 `/skills` 类路由的访问 100% 重定向到新路径，不返回 404。
- **SC-012**：本 feature 上线后，旧 `skills.*` 类通知名 100% 已从 Registry 与发布路径中下线，新名 `tools.*` 100% 成为唯一权威通知（无任何双发残留）。
- **SC-013**：本 feature 上线后，新建一个 specialist 时系统 100% 把当时所有 active 方法论按创建时间升序自动装备给该 specialist（**剔除链根 origin = `system_bootstrap` 的方法论**）；一个非 `system_bootstrap` 方法论变为 active（新建直接入库 / supersede 接力 / 用户编辑接力 / 外部导入）时系统 100% 把它追加装备到所有现有 specialist 与 assistant 本体；一个链根 origin = `system_bootstrap` 的方法论变为 active 时系统 100% 只装备到 assistant 本体、**不**追加装备到任何 specialist。三类自动装备行为以及"`system_bootstrap` 例外按链根 origin 判定"在守卫测试中被验证。
- **SC-014**：本 feature 上线后，assistant 派活决策路径 100% **不**注入方法论索引、trigger_conditions 全文或方法论正文；守卫测试覆盖 assistant 派活上下文构建路径，断言其不读取方法论相关数据。
- **SC-015**：本 feature 上线后，SkillScreen active 列表 100% 能在 **4 种**排序模式（最近变更 / 被加载次数 / 被引用次数 / 装备者数量）间切换，并能筛选出"从未被引用执行过""最近 30 天没被引用过"两类方法论；每张方法论卡片直接展示三项统计计数（被加载次数 / 装备者数量 / 被引用执行次数）。4 种排序、2 类筛选、卡片三项计数显示在守卫测试中被验证；守卫测试同时断言：(a) 排序键集与卡片显示的三项计数 + 时间维度对齐；(b) 默认排序键"最近变更时间倒序"的时间字段 = 当前 active 版本 `created_at`（FR-029b），不因装备关系变更、`load_skill_methodology` 调用、`skills_referenced` 字段触发的被引用执行 +1 而刷新；(c) "最近 30 天未被引用过"筛选用的时间字段是与 FR-029b "最近变更时间"独立的 "最近一次被引用执行时间"。
- **SC-016**：本 feature 上线后，"被引用执行次数 +1" 路径在守卫测试中被覆盖：(a) 装备者 reply 元数据 `skills_referenced` 列出的 skill_id 各 +1 且最近一次时间被刷新；(b) 未列出的 skill 本轮**不** +1；(c) 同一轮 reply 中同一个 skill_id 重复列出按 1 次计；(d) 字段缺失或格式错误时本轮静默跳过、不报错重试；(e) 不存在"装备即引用"的兜底加计；(f) reply 元数据中已被 `superseded` 的 skill_id 按 supersede 链根 asset id 归一化到当前 active 版本 +1（**不**丢失"真按它走了"的信号）；(g) 当链根 asset 已落 `soft_deleted` 时本条引用按"格式错误"规则静默跳过；(h) 同一轮 reply 中多条引用经归一化后指向同一 asset 仍按 (c) 去重。
- **SC-017**：本 feature 上线后，"被加载次数 +1" 路径在守卫测试中被覆盖：(a) 装备者调用 `load_skill_methodology(skill_id)` 成功返回时该 skill 的被加载次数 +1；(b) 工具调用失败（skill_id 不在装备清单 / skill 已 `soft_deleted` / `superseded`）**不** +1；(c) 人在 SkillScreen 详情、装备 UI 预览、审计视图等界面翻看**不** +1；(d) 不存在"装备即加载"的兜底加计；(e) 同一装备者短时间内重复调同一 skill_id 各算 1 次（无去重窗口）。
- **SC-018**：本 feature 上线后，方法论正文**不**出现在任何装备者的 effective system prompt 里——守卫测试覆盖 specialist 与 assistant 本体的 system prompt 构建路径，断言其中只包含装备清单条目（id + 名称 + 描述 + 触发条件）而**不**包含方法论的 body Markdown；body 100% 通过 `load_skill_methodology` 工具 result 进入 messages 序列。
- **SC-019**：本 feature 上线后，`create_skill_methodology` 工具在业务层**不**对触发条件 list 元素做相等/相似度检查、**不**对所需工具 list 做相等检查、**不**对正文 Markdown 做相似度检查、**不**调用 LLM 做语义判重——守卫测试通过构造"同 trigger 元素但不同名"的输入并断言工具直接成功入库（前提 FR-024 的素材约束已满足）。**唯一硬约束例外是 FR-024a 的 `name` 精确字符串相等同名拒绝**，守卫测试覆盖：(a) 工具新建模式遇全库同名 active 时被拒并返回错误（含已占用 id 与 name 提示），不写入任何数据；(b) Supersede 模式**不**走该检查（新版本与旧版本同名是正常情况），断言能成功 supersede 出与旧版本同名的新版本；(c) 用户在 SkillScreen 编辑器修改 `name` 撞到现有同名 active 时保存被拒，UI 显示错误提示与已占用同名的 active 方法论 id 链接；(d) SkillScreen 列表中**不会**出现两条同名 active 方法论（业务层已在写入路径阻断该状态），断言列表不再渲染"同名"视觉标签。
- **SC-020**：本 feature 上线后，SpecialistScreen 各装备面板（含 assistant 本体卡片）顶部 100% 显示 token 计量条，含装备条目数 + token 估算值 + 阈值染色三项；前端 e2e 测试断言计量条在勾选/卸下/调整顺序时实时更新，且超过阈值时变色但不阻断保存。
- **SC-021**：本 feature 上线后，SkillScreen 编辑器对**普通**方法论（链根 origin ≠ `system_bootstrap`）的"保存"按钮 100% **不**触发任何 UI 二次确认弹窗——按下即走 supersede 接力（旧版本切 superseded、新版本入库 active、装备关系单事务跟新），前端通过非模态浮层告知"已生成 v_N"；对 **FR-027a 受保护方法论**（链根 origin = `system_bootstrap`）的"保存"按钮 100% 触发高危确认弹窗，用户拒绝即取消保存。两类编辑路径的事务原子性（崩溃整体回滚）与装备关系跟新一致性（无装备者残留旧版本）在守卫测试中被验证。
- **SC-022**：本 feature 上线后，"触发条件 list 必填 ≥1 条"约束在守卫测试中被覆盖：(a) `create_skill_methodology` 工具新建模式传入 `trigger_conditions = []` 时被拒并返回错误，不写入任何数据；(b) 工具 supersede 模式传入 `trigger_conditions = []` 时同样被拒；(c) 工具传入 `trigger_conditions = ["", "  "]`（全为空 string 或纯空白 string 的 list）时按"等价于空 list"处理同样被拒；(d) SkillScreen 编辑器对触发条件 list 为空的方法论保存请求被拒，错误提示明示"至少需要 1 条触发条件"；(e) 所需工具 list 允许 0 条，工具调用与编辑器保存均不阻断该字段为空的情况。
- **SC-023**：本 feature 上线后，bootstrap migration 的 seed 文件 fail-open with fallback 路径在守卫测试中被覆盖：(a) seed 文件缺失场景下，migration 完成后大脑中存在一条 origin = `system_bootstrap`、状态 active 的"如何创建方法论"方法论，其正文为 fallback 文本，应用启动成功不阻塞；(b) seed 文件内容为空 / 全为空白时同样走 fallback 路径；(c) seed 文件 IO 异常 / 编码错误时同样走 fallback 路径；(d) fallback 版本受 FR-027a 完整保护（不可软删除、用户编辑需高危确认）；(e) 后续启动时若 seed 文件已修复且当前 active 仍为 fallback 版本（链上无 user_edit 接力节点），migration 自动 supersede 用真实 seed 内容覆盖；(f) 后续启动时若 active 已被用户编辑接力出 v2 及以上，migration **不**自动覆盖、尊重用户修订；(g) UI 启动后 100% 触发 non-blocking toast 提示用户 seed 读取异常状态（仅在 fallback 路径生效，正常 seed 写入路径不触发）。
- **SC-024**：本 feature 上线后，`load_skill_methodology` 工具的"无调用次数硬上限"约束在守卫测试中被覆盖：(a) 同一装备者在单轮内连续多次（≥3 次）调用 `load_skill_methodology` 不同 skill_id，每次成功 load 均被工具层接受并返回 SKILL.md 形态文本，工具层**不**基于"本轮已 load 次数"拒绝调用；(b) 同一装备者在单轮内重复 load 同一 skill_id 不被工具层拒绝（FR-041 被加载次数累计每次 +1，无去重窗口）；(c) 工具层拒绝路径仅限 FR-017a 列出的三类（skill_id 不在装备清单 / skill 已 `soft_deleted` / skill 已 `superseded`），不包含任何频次类拒绝；(d) "如何创建方法论" seed 文件正文断言中包含"按 trigger_conditions 选择性 load、不应单轮无差别 load 全清单"的引导文本（与 FR-027 同步约束）。
- **SC-025**：本 feature 上线后，方法论 `origin` 字段的"封闭枚举"约束（FR-006a）在守卫测试中被覆盖：(a) 业务层 Service 写入路径对非枚举 origin 值的请求 100% 拒绝并返回错误（含合法枚举集合提示），不静默降级；(b) Repository 类型契约层面（Literal Union / Enum）对非枚举值在编译期 / 运行期类型校验阶段拒绝；(c) 持久化层 CHECK 约束（或等价枚举落地形式）对绕过 Service 与 Repository 的直连 SQL 写入尝试同样拒绝；(d) 5 个合法枚举值（`system_bootstrap` / `user_edit` / `assistant_tool_call` / `specialist_tool_call` / `external_import`）每一个都能成功通过三层校验并落库；(e) 本期"`external_import` 不允许写入"约束受独立守卫测试覆盖——即使 origin 值合法属于枚举集，业务层仍拒绝任何来自 desktop_api 入口的 `external_import` 写入（直到 FR-042/043 由独立 feature 实现）；(f) FR-027a / FR-014a "按链根 origin 判定"的守卫测试断言 origin 字段的取值范围与本枚举集完全重合。
- **SC-026**：本 feature 上线后，装备关系的"永不物理删除"约束（FR-014b）在守卫测试中被覆盖：(a) 用户在 SpecialistScreen 卸下某装备关系时，关系行 `status` 由 `active` 变为 `unequipped`、`unequipped_at` 与 `unequipped_reason = user_unequip` 被填充，行本身**不**被物理删除；(b) FR-020 强制软删除路径自动裁剪受影响装备关系时同样标 `unequipped`（`unequipped_reason = force_remove_on_soft_delete`），不删行；(c) FR-011 supersede 切版本路径在同事务内把旧版本上所有 `active` 关系行标记 `unequipped`（`unequipped_reason = supersede_transfer`）并为新版本插入新 `active` 行，崩溃整体回滚不留中间态；(d) 再次装备同一对 (装备者, skill) 时新建一行 `status = active`，历史 `unequipped` 行保留不变；(e) 数据库 unique partial index（或等价约束）阻止每对 (装备者, skill) 同时存在多于 1 行 `status = active`；(f) 物理删除装备关系行的尝试（API / Repository / 直连 SQL 三条路径）被 100% 阻断，与 SC-008 同模式；(g) FR-034 审计视图能基于该状态机回放"该方法论被哪些装备者装备又卸下的完整历史轨迹"与反向的"specialist 历史装备组合"。

## Scope Amendment: 工具池并入工具列表（2026-06-01）

**动因**：010 实现的 `SkillPoolPanel` 放在 `/brain` 大脑管理页语义不符——工具池是"能力清单视图"，而大脑管理页关注的是"认知分区条目"。用户在工具列表屏（`/skills`）的"已掌握"分类里已经能看到自建工具，两处各维护一份清单造成认知割裂。

**变更内容**：

1. **提取公开常量**：`_BUILTIN_TOOL_CATALOG`（私有）→ `src/business/brain/builtin_tools.py` 中的 `BUILTIN_TOOL_CATALOG`（公开），`specialist_service.py` 改为 import 引用。
2. **内置工具并入工具列表**：`skills_service.py` 的 `get_category("published")` 与 `get_all_categories()` 在已掌握列表头部追加全部内置工具条目（`is_builtin: True`，`trialSuccessCount: 3`，`source: "内置"`）。`ToolSummary` Pydantic schema 新增 `is_builtin: bool = False` 字段（原因：FastAPI 序列化时会过滤掉 schema 外字段，不加此字段则前端永远收到 `undefined`）。前端 `SkillSummary` 类型同步加 `is_builtin?: boolean`。
3. **内置工具卡片只读**：`SkillCards.tsx` published 视图中，`is_builtin` 为 true 的卡片显示"内置" badge、隐藏删除按钮、隐藏试用按钮、不显示成功次数；用户自建的已掌握工具卡片保持原有操作。
4. **移除 BrainScreen 中的 SkillPoolPanel**：`BrainScreen.tsx` 删除 `SkillPoolPanel` import 与渲染、移除相关 state 绑定（`skillPool / loadingSkillPool / removeSkill / pendingSkillRemoval / clearPendingSkillRemoval`）与 `loadSkillPool` useEffect 调用。`brainStore` 中的 `skillPool / loadSkillPool` 状态保留，因为 `SpecialistScreen` 白名单编辑仍依赖。
5. **文档同步**：`docs/ARCHITECTURE.md` 路由表移除 `/brain` 的"skill-pool 管理"描述，补充说明 `brainStore` 的 skill-pool 状态供 `SpecialistScreen` 复用。

**不变**：`DELETE /api/brain/skill-pool/{tool_id}` 端点与 `remove_from_pool` 业务逻辑保留（UI 入口消失，后续如需从工具列表踢出授权池可复用）。

## Assumptions

- 用户已经在 010 之后的版本上运行；本 feature 直接构建在大脑 6 分区、segment 沉淀、specialist 系统、自动招募、UI Event Registry 已上线的基础上。
- 用户对"专员"概念已经熟悉；本 feature 不再解释 specialist 的基础语义。
- 现有"工具技能"录制层的技术实现保持不变，命名整顿只发生在 UI 文案、前端路由、对外通知名称三个层面。
- assistant 调度层调用 `create_skill_methodology` 工具时的 LLM 调用走 assistant 现有模型与额度池；被授权 specialist 调用该工具时走其 specialist 自身的模型与额度池；本 feature 不引入独立的模型选择。
- `create_skill_methodology` 工具与 "如何创建方法论" 内置方法论的初始装备关系（默认挂在 assistant 调度层本体）由系统迁移在第一次启动新版本时一次性写入；"如何创建方法论" 的初始正文来源于代码库中的独立 seed 文件（具体路径与文件名在 plan 阶段确定）；之后不再回滚为初始内容。Seed 文件读取失败时按 FR-027b 走 fail-open with fallback 路径（用硬编码 fallback 文本入库 active + UI toast），不阻塞启动；后续 seed 修复后若 active 仍为 fallback 版本 migration 自动 supersede 用真实 seed 覆盖，若已有用户编辑接力则尊重用户修订不自动覆盖。
- 方法论的"触发条件"是给**装备者自己**读的**自然语言提示词条目**（例如 "用户在请求做周报 / 复盘类总结时" 这种短句）；**存储为 list of strings**（多条独立条目，SQLite 用 JSON array 等价表示，FR-006），用户在 SkillScreen 编辑器中用 list editor 维护（FR-031）；作为装备清单条目的一部分注入到装备者的 system prompt（与名称、描述、id 一起）时按 **YAML list 原生形态**渲染，不再拼成单串。装备者读触发条件 list 后自行判断当前这一步要不要调 `load_skill_methodology` 拉这条方法论的正文用；**不**走任何字符串、子串、正则、词边界、关键词命中类机械匹配；本 feature 不再单独引入额外的"匹配引擎"。trigger_conditions 字段**不**进入 assistant 派活决策上下文。该字段在与 Anthropic Agent Skills 规范对接时对齐 SKILL.md frontmatter 的 `when_to_use` 字段——FR-042/043 的导出层负责把 list 拼接成单串赋给 `when_to_use`，导入层负责把单串切分回 list（内部 list、外部单串）。
- 本 feature 不引入方法论的跨项目导入导出能力（FR-042/043 仅为契约占位）。
- token 预算的硬上限阈值由 plan 阶段决定；spec 层只要求"装备 UI 能给用户提前提示风险"，不规定具体数值。
- 本 feature 的所有数据资产仅本地存储；不涉及任何外部账号或云同步。
- 方法论的形态对齐 [Anthropic Agent Skills 开放规范](https://agentskills.io)：SKILL.md = YAML frontmatter + Markdown body 二段式；本 spec 的核心 5 字段映射到规范 frontmatter 的 `name` / `description` / `when_to_use` / `allowed-tools` + body。`load_skill_methodology` 工具 result 按此形态渲染（agent 拉到的是 SKILL.md 文本本身）。本 spec 的扩展字段（status / origin / 超越链 / 素材来源 / 统计计数等）为大脑层附加元数据，仅在内部 SQLite 持久化，不进入 SKILL.md frontmatter，保持规范导出形态的纯净。未来 FR-042/043 的外部导入导出契约（marketplace / 跨工具兼容）以该规范为对齐目标，本期不实现。
