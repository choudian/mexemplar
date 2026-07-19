# Contract: 创建确认卡 + per-task 无人值守免确认

本特性两个独立的安全协议，**复用既有视觉/模式，但不复用既有后端协议**（019 `clarification_manager` 主助理独占 + 阻塞 worker + 全内存；`_auto_approve_enabled` 进程级单一布尔）。

---

## A. 创建确认卡协议（`SchedulingConfirmationManager`）

**位置**：`src/business/scheduling/scheduling_confirmation_manager.py`。**仿** `clarification_manager.py`（独立 pending dict + 独立 Lock + first-decision-wins + 后端权威 `expires_at`）+ `TrialPreviewRequestManager` 的 typed UI event 模式。

**与 019 的关键差异**（不复用 019 后端的理由）：
1. **持久化**：019 全内存；定时任务创建须跨 sidecar 重启存活 → 待决策（pending 确认卡短期，超时即 fail-closed 拒绝；**第一批 pending 卡可走内存 + 短超时**，因 fail-closed 拒绝=不创建，天然安全无需清理）。**决策：第一批内存态**（与 019 一致），超时拒绝=不创建，重启丢失 pending 卡=用户重说一句，安全可接受。
2. **触发者**：019 仅主助理 `ask_user_question`；本卡由主助理 `create_scheduled_task` 工具触发，经独立 manager + 独立事件 `scheduling.confirmation_*`（不挤占 `assistant.clarification_*`）。
3. **承载内容**：019 是问答；本卡是「核对解析结果 + 勾选免确认 + 取消」，payload 含 `draft` + `unattendedAutoApprove`（这是 019 没有的「附加布尔开关」，确认卡 payload 增量）。
4. **挂载点**：019 `ClarificationCard` 仅挂 `AssistantScreen.tsx:474`（session 内）；本卡须**全局可见**（创建可能发生在用户正对话时，也可能跨屏）→ 在 `AppShell` 挂全局 `StructuredConfirmationCard` 容器（抽取自 `ClarificationCard`）。

**协议**：
- `request_id` 前缀 `scf_<hex12>`。
- `create(draft, session_id) -> request_id`：组装 `expiresAt = now + 确认超时`，入 pending dict，emit `scheduling.confirmation_requested`（interactive）；事件发布异常时立即把该隐形 pending 结算为 stopped 并向调用方报错。
- `submit_decision(request_id, decision, edited_draft?, unattended_auto_approve?) -> bool`：first-decision-wins，已结算返回 `accepted=False`。
  - 每次提交先在同一把锁内重校验 `expires_at`；过期即先赢得裁定并返回未接受，任何 REST 迟到 confirm 都不能落库。
  - `decision="confirm"`：只把公开 edited draft 的 `title` / `instruction` 合并进后端权威原 draft（不得替换 `schedule_payload` / source / kind），落库 `ScheduledTaskRepository.create(...)`，`unattended_auto_approve` 取勾选值，emit `scheduling.confirmation_resolved(status=confirmed)` + `scheduled_task.changed(changeType=created)`。
  - `decision="cancel"`：不落库，emit `resolved(status=cancelled)`。
  - `SchedulerWorker` 每轮清理过期卡；`AssistantRuntime.cancel_session` 按 session 结算 stopped；sidecar 关闭全量结算 shutdown。
- **fail-closed**：超时、关闭、停止、requested 事件发布失败一律 = 不创建（FR-006）。SSE 暂时断连不等于用户拒绝，pending 可由权威快照恢复。
- **SSE 重连恢复**：`GET /api/scheduled-tasks/confirmations/pending`（仿 019 `clarifications/pending`）在无 `sessionId` 时返回全局卡列表，快照含确认卡已经公开的可渲染 `draft` 五字段 + `unattendedAutoApprove`，但不含内部 `schedule_payload` / `next_fire_at`；缺口走 `backend.resync_required`。

**视觉**：复用/抽取 `ClarificationCard.tsx`（`frontend/src/screens/assistant/ClarificationCard.tsx:53`）→ `StructuredConfirmationCard`，props 对齐 `requestId/draft/expiresAt/onSubmit/onCancel` + 新增 `unattendedAutoApprove` 勾选框（附风险说明）。

---

## B. per-task 无人值守免确认协议（`UnattendedConfirmationManager`）

**位置**：`src/business/scheduling/unattended_confirmation_manager.py`。**完全独立**于进程级 `_auto_approve_enabled`（`builtin_general_tools.py:159`，调查硬证据：进程级单一布尔，开启波及所有会话）。

**数据**：`dict[scheduled_task_id] -> bool`，从 SQLite `scheduled_tasks.unattended_auto_approve` 加载（`unattended_auto_approve=1` 的任务 id 集合）。进程启动时全量加载 + 增量更新（任务创建/开关变更时刷新）。

**决策点注入**：在 `builtin_general_tools._confirm_or_reject` 内先解析当前 root session，再决定是否允许进入既有进程级确认路径（新增 `_unattended_auto_approve_for(session_id) -> Literal["authorized", "reject_immediately", "passthrough"]`）：
1. 空 `session_id` 表示没有可判定的会话上下文，可 `passthrough`；非空 id 必须先查权威
   session。查不到行或查询异常 → `reject_immediately`，不得退回进程级
   `_auto_approve_enabled` / 交互确认。只有明确查到且 `source!='scheduled'` 才
   `passthrough`，用户会话行为不变。
2. scheduled session 关联的 `scheduled_task_id` 在授权集 → `authorized` 并放行，审计来源记 `CONFIRM_SOURCE_UNATTENDED_TASK`。
3. scheduled session 未授权、关系字段异常或授权查询失败 → `reject_immediately`，在确认入口直接拒绝（不等 `_CONFIRM_TIMEOUT`，也不允许进程级「全部允许」越过 per-task 边界）；任务继续其余部分并在汇报列出被跳过动作。

**四重限定（FR-024，硬保证）**：
1. 仅 `source='scheduled'` 会话生效（用户会话 `source='user'` 永远走原逻辑）。
2. 仅该 `scheduled_task_id`（per-task 授权集）。
3. 默认关闭（`unattended_auto_approve=0`）。
4. 只能由用户显式 UI 操作开启（确认卡勾选 / 详情页 PATCH；**无工具入口**）。

**隔离门卫（guard test `test_unattended_scope.py`）**：
- 开启某 task 免确认后，`_auto_approve_enabled` 的值**不变**（assert 不被读写）。
- 用户会话（`source='user'`）的高危确认**仍走原流程**（不被自动放行）。
- 另一未授权的 scheduled task 的高危确认**仍立即拒绝**。
- 即使进程级 `_auto_approve_enabled=True`，未授权 scheduled task 也**仍立即拒绝**。
- 即使进程级 `_auto_approve_enabled=True`，非空 root session 查不到或查询异常也
  **仍立即拒绝**，且不进入交互确认。
- 决策审计日志记 `CONFIRM_SOURCE_UNATTENDED_TASK` + `scheduled_task_id`。

---

## C. CC-005 受控破例声明（须修订活文档）

`unattended_auto_approve` 持久化到 SQLite 违反现行硬规则「全部允许/免确认只允许是当前进程会话级内存状态，不得写入配置、SQLite 或 DuckDB」（CLAUDE.md + `docs/PROJECT_CONSTRAINTS.md:21`）。

**这是用户显式拍板的受控例外**，四重限定（仅 scheduled 会话 / 仅该任务 / 默认关闭 / 只能 UI 显式开启）+ 工具参数门卫（三重不暴露）+ 独立 manager（不碰进程全局）+ 列表层可见可回收（FR-019）共同把爆炸半径焊死在「仅该 scheduled 会话的高危动作」。

**implement 阶段 MUST 同步修订**（plan Complexity Tracking CT-1）：
- `.specify/memory/constitution.md`：在 Engineering Guardrails 或 Core Principles 增「受控例外：调度中心 per-task 无人值守免确认」条款，注明四重限定 + 边界；version PATCH 或 MINOR bump。
- `docs/PROJECT_CONSTRAINTS.md:21`：把「不持久化」补「调度中心 per-task `unattended_auto_approve` 是显式受控例外（见 033）」。
- 根 + 模块 `AGENTS.md`/`CLAUDE.md`/`GEMINI.md`：同步例外说明（四镜像）。

不得静默违反——任何评审 MUST 检查此例外条款与代码实现一致。
