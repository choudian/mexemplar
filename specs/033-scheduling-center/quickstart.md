# Quickstart: Scheduling Center（调度中心）

第一批（最小闭环 + 待办接入）的快速体验与验证路径。面向 implement 完成后的冒烟自测。

## 前置

1. 在 worktree `033-scheduling-center` 分支，后端经 Tauri shell 启动 sidecar（正常开发路径，不走 legacy PyQt）。
2. migration 自动推进到 **v31**（v30 建 `scheduled_tasks` / `scheduled_task_runs` + `sessions` 加 3 列；v31 增加 run 终态事件确认时间与单调代次）。验证：`schema_version` 表 `version=31`。
3. 桌面通知插件已装（`src-tauri/Cargo.toml` + `lib.rs` + `capabilities/default.json` + `frontend/package.json`）。验证：前端 `import { sendNotification }` 可用。
4. 前端路由 `/scheduled` 出现在 NavRail（主屏 9→10）。

---

## 场景 1 — 立即任务（P1 最小闭环）

1. 在 AI Assistant 对话说：「现在帮我查一下今天的天气并写一段摘要」。
2. 主助理调 `create_scheduled_task(source_type=direct, schedule_kind=one_shot, run_at=now)`。
3. **弹创建确认卡**（全局 `StructuredConfirmationCard`）：核对标题 / 「立即执行」/ 指令原文；`unattendedAutoApprove` 默认不勾；点确认。
4. 任务落库 + **立即触发**：新建 `source=scheduled` 会话，主助理在后台执行（无人值守提示已注入）。
5. 完成后：**应用内 Toast（success）+ 桌面通知**；调度中心历史出现一条 `succeeded` run。

**验证点**：会话 `source='scheduled'`（DB）；聊天屏列表**看不到**该会话；调度中心历史看得到且能点进去接着聊；`sessions.is_scheduled=1`。

## 场景 2 — 一次性定时（P1）

1. 对话说：「2 分钟后提醒我整理会议纪要」（用短延迟便于验证）。
2. 确认卡展示人话「一次性 7月18日 22:35」+ 指令；确认。
3. 等 2 分钟到点 → 自动触发执行 → 通知 + 历史。

**验证点**：`next_fire_at` 与确认卡展示一致；到点秒级触发（SchedulerWorker 动态 wait）；触发后 `status=completed`、`next_fire_at=NULL`。

## 场景 3 — 周期（P2）

1. 对话说：「每隔 1 分钟查一次某个网页标题」。
2. 确认卡 → 确认。
3. 观察连续 2 次滚动触发（每次结束 `next_fire_at` 滚到下个未来时点）。
4. **misfire 验证**：触发后立即关 sidecar，等过 2 个周期再启动 → 只补跑最近一次。
5. **reentry 验证**：把周期改到「每隔 10 秒」、任务设成耗时 30 秒，观察到点时上次未静默 → 本次 `skipped`（不堆积）。

**验证点**：`compute_next_fire` 滚动正确；misfire 补一次不补全部；reentry 记 `skipped` 不并发堆积。

## 场景 4 — 从待办接入（P2）

1. 在 `/todos` 建一条待办「整理本周 PR 列表」（带 description）。
2. 待办条目行内「让 AI 做」按钮 → 弹创建确认卡：指令框**预填 title + description**，可编辑；用户核定后的指令独立持久化，schedule_kind 锁 one_shot；设短延迟。
3. 确认 → 执行完成。
4. 回 `/todos`：该待办**未被自动标记完成**，仅卡片显示「上次执行：时间 + 成功」。

**验证点**：`source_type='todo'`、`schedule_kind='one_shot'`（门卫拒绝 recurring）；执行内容等于确认卡核定并持久化的 `instruction`；`user_todos` 表**无任何写入**（调度路径只读 todo_id）；待办状态未变。另将待办删除或标记完成后分别尝试到点触发与「现在跑一次」，两条路径都应把调度任务置 `expired`、不建 run；模拟 Repository 读取异常时任务保持可重试，不得误判为删除。

## 场景 5 — 无人值守安全与接管（P2）

1. 创建一个会触发高危动作（如 `exec`）的 scheduled 任务，**不勾**免确认。立即触发。
2. **验证 fail-closed**：高危动作**立即被拒绝**（不等 120s），主助理汇报列出被跳过的动作，run 最终 `failed` 或部分完成。通知带原因。
3. 创建同类任务，这次在确认卡**勾选** `unattendedAutoApprove`（附风险说明已读）。立即触发。
4. **验证 per-task 范围**：该任务的高危动作**自动放行**（审计日志 `CONFIRM_SOURCE_UNATTENDED_TASK`）；同时另一未勾选的 scheduled 任务仍立即拒绝；即使先在普通聊天开启进程级「全部允许」，未授权 scheduled 任务也不得被放行；**用户正在聊的会话不受任何影响**（per-task 开关不改 `_auto_approve_enabled` 值）。
5. **接管验证**：让一个 scheduled run 反问（落 `waiting_for_user`）→ 收到「需要你接管」通知 → 从调度中心历史点进会话接着聊 → run 回 `running` 直至完成。

**验证点**：未授权立即拒绝（不等超时）；per-task 隔离（不波及用户会话/其他 task）；`waiting_user` 不标失败、可接管续跑。

---

## 调度中心管理屏验证

- 列表：所有任务（周期/一次性/待办来源）的标题、状态、调度描述、下次触发、上次结果；未跑过标「还没跑过」。
- **免确认任务醒目标记**（⚠）在列表层一眼可见；详情页可关掉收回授权。
- 空态：无任务时显示创建指引（引导去对话 + 例句）。
- 行内操作：暂停 / 启用 / 现在跑一次 / 删除。
- 历史：每条 run 的状态/时间/汇报；`waiting_user` 醒目标注 + 进入会话入口。

## 退出清理

- sidecar 关闭时 `SchedulerWorker.stop()` 在 lifespan finally 内有界 join（仿 brain/task_collab worker）。
- 验证：关 sidecar 不留僵尸线程、不污染 `_auto_approve_enabled`。
