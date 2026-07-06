# Research: 提案审批"讨论"功能

**Date**: 2026-07-06 | **Plan**: [plan.md](plan.md)

## D1 — 开场上下文用什么消息角色呈现

**Decision**: 会话创建时直接落一条 `role="assistant"` 的 markdown 消息（提案讨论上下文全文），零模型调用。

**Rationale**:
- FR-428 要求上下文在会话内可读：display 路径只展示 user/assistant 角色（`program`/`agent` 被 `format_messages_for_display` 与 display-message 过滤跳过），`program` 角色不可见，排除。
- 伪造 user 消息违反"用户输入是数据"原则（frontend AI 文档），排除。
- assistant 角色天然走 SafeMarkdown 渲染（006 契约），提案上下文格式化为 markdown 后可读性最好；同时自然进入 LLM 上下文，助理后续回答"知道自己说过什么"。
- FR-426 零模型调用：直接 `save_message` 落库即可，不跑 AgentLoop。

**Alternatives considered**: `program` 角色注入（不可见，违 FR-428）；首条用户消息携带（伪造用户发言）；新增专用消息角色/卡片（违"实现最薄"与 0 新事件约束）。

## D2 — 幂等绑定与并发竞态

**Decision**: `ImprovementProposalRepository.bind_discussion_session(proposal_id, session_id)` 用条件 UPDATE（`WHERE id=? AND discussion_session_id IS NULL`）+ rowcount 判定；service 侧先建会话再 claim，claim 失败（rowcount=0）则删除刚创建的孤儿会话并返回已绑定的会话 id。

**Rationale**: 项目 CAS 惯例是原子条件 UPDATE + rowcount（不是 BEGIN IMMEDIATE）；单用户桌面下真实并发概率极低，但 FR-427 要求幂等，该顺序保证最坏情况下也只留一个绑定、无孤儿。UI 侧按钮点击后立即 disable 作为第一道防线。

**Alternatives considered**: 先 claim 占位再建会话（需要占位值语义，脏状态窗口更差）；应用级锁（超出单机需求）；忽略竞态（留孤儿会话污染会话列表）。

## D3 — finding 序列化单一来源

**Decision**: 新建 `src/business/self_improvement/proposal_context.py`，提供 `format_proposal_finding_text(proposal, include_outcome: bool) -> str`：问题/证据/建议/严重度/类型 + 用户补充说明；`include_outcome=True` 时追加实施分支/结果摘要/测试结论/失败原因（如有）。`proposal_bridge._build_implementation_graph` 的节点 description 改为调用同一 helper 拼 finding 块（guard_block 等 bridge 专属段保留在 bridge 内）；讨论开场消息调用 `include_outcome=True` 版本。

**Rationale**: FR-421 明确"不另写一份副本"；bridge 现有 f-string 是唯一权威格式，提取后两处消费同一实现，防止字段增减时漂移。守卫测试断言两条路径都 import 该 helper。

**Alternatives considered**: 讨论侧复制一份文本模板（必然漂移）；把序列化塞进 proposal_service（bridge 反向 import service 不顺，独立小模块最干净）。

## D4 — 前端入口与跳转

**Decision**: BrainScreen 提案详情区（论证链下方、审批操作上方）加"讨论"按钮（已绑定会话时文案"继续讨论"，DTO 带 `discussionSessionId`）；点击走 brainStore 新 action `openProposalDiscussion(proposalId)` → `POST /api/improvement-proposals/{id}/discussion` → 拿 sessionId → 切路由到 assistant 屏 + `assistantStore.selectSession(sessionId)`。请求期间按钮 disable，失败走既有区域错误提示。

**Rationale**: assistantStore 已有 `selectSession`（会拉历史消息与快照），路由切换用既有 `routes.tsx` 机制，无需新导航设施；按钮状态遵循"动作立刻有反应"易用性原则。

**Alternatives considered**: BrainScreen 内嵌迷你聊天窗（重复实现聊天 UI，违 FR-424"不引入独立聊天界面"）；先跳转再懒创建（跳过去后没有会话可选，时序更绕）。

## D5 — 绑定失效判定与自愈

**Decision**: service 判定"绑定会话可用"= `SessionRepository.get_by_id` 存在且 status 属于会话列表可见集合（`active/suspended/completed/failed`）；不可用（行缺失或已归档删除）时创建新会话、重建开场消息，并用无条件 UPDATE 换绑（此时旧绑定已确认死亡，直接覆盖）。

**Rationale**: FR-423 自愈；删除路径经既有 assistant delete/archive API，提案侧不做级联监听（spec 假设），点击时惰性检测成本最低。

**Alternatives considered**: 订阅会话删除事件实时清绑定（新增监听与事件耦合，超出必要）；绑定死亡时报错让用户手动处理（违 FR-423）。

## D6 — 会话标题

**Decision**: 讨论会话标题为「讨论：{proposal.what 截断 24 字}」，经 `ChatService.create_session(title=...)` 传入（`_normalize_title` 既有截断逻辑兜底）。

**Rationale**: FR-424 要求会话出现在普通列表里，可辨识标题让用户从会话列表也能找回讨论；复用既有 title 参数，无 ChatService 改动。

**Alternatives considered**: 默认无标题（列表里全是"新会话"无法辨识）；标题带提案 id（内部 ID 不进 UI 文案，违前端易用性原则）。
