# Contract: REST API（`/api/scheduled-tasks`）

**仿照** `routers/user_todos.py`（`APIRouter(prefix="/api/scheduled-tasks", tags=["scheduled-tasks"])`），schema 集中在 `desktop_api/schemas.py`，**字段一律 camelCase**。注册进 `app.py:186-201` include 序列；**鉴权自动**（应用级 `X-Mexemplar-Session` 中间件，零 Depends）。错误映射手写 `LookupError→404 / ValueError→422`，500 走全局兜底。

> **创建入口**：定时任务创建经主助理工具 + 创建确认卡（见 `confirmation-and-unattended.md`），**REST 不暴露创建表单**（FR-005）。REST 只承载管理、行内操作、历史、接管、确认卡决策提交。

## DTO（`schemas.py` 追加）

```ts
ScheduledTaskStatus = "active" | "paused" | "completed" | "expired"
ScheduleKind = "one_shot" | "recurring"
ScheduledTaskSource = "direct" | "todo"
RunStatus = "running" | "succeeded" | "failed" | "waiting_user" | "skipped"

ScheduledTaskItem {
  scheduledTaskId: string           // sch_ 前缀
  sourceType: ScheduledTaskSource
  sourceRef: string                 // direct=指令文本；todo=todo_id
  title: string
  scheduleKind: ScheduleKind
  scheduleDescription: string       // 人话：「每天 09:00」「每周一 08:00」「一次性 7月19日 17:00」
  status: ScheduledTaskStatus
  unattendedAutoApprove: boolean    // 列表层必须可见（FR-019）
  nextFireAt: string | null         // UTC ISO
  lastFireAt: string | null
  lastRunOutcome: RunStatus | null  // 上次执行结果（未跑过 null）
  lastRunAt: string | null
  createdAt: string
  updatedAt: string
}

ScheduledTaskListResponse { items: ScheduledTaskItem[]; total: number; limit: number; offset: number }

ScheduledTaskPatchRequest {
  // 仅允许以下字段（修改调度核心 = 删除重建，FR 第一批无修改能力）
  status?: "paused" | "active"          // 暂停 / 启用
  unattendedAutoApprove?: boolean       // 详情页开关（FR-019）；唯一写入该字段的 REST 路径之一
}
// 注意：PATCH 严禁接受 scheduleKind / schedulePayload / sourceType / sourceRef / title —— 防止绕过确认卡改调度

ScheduledTaskRunItem {
  runId: string                        // schr_ 前缀
  scheduledTaskId: string
  sessionId: string | null             // 非 skipped 为 ast_ 会话；skipped 未启动会话，固定 null
  startedAt: string
  finishedAt: string | null
  status: RunStatus
  summary: string | null               // advisory，确定性截取
  failureReason: string | null         // 安全投影，无敏感诊断
}

ScheduledTaskStartedRunItem extends ScheduledTaskRunItem {
  sessionId: string                    // fire-now 成功时已存在真实 scheduled 会话
  status: "running"                    // 202 响应的类型级不变量
}

ScheduledTaskRunListResponse { items: ScheduledTaskRunItem[]; total: number; limit: number; offset: number }

TakeoverResponse {
  sessionId: string
  recoveryDraft: string | null         // 旧 phantom/空会话惰性自愈时返回原任务指令；前端只预填、不自动发送
}

ScheduledConfirmationDraft {
  title: string
  scheduleDescription: string
  instruction: string
  scheduleKind: ScheduleKind
  sourceType: ScheduledTaskSource
}

ScheduledConfirmationPendingItem {
  requestId: string
  sessionId: string
  draft: ScheduledConfirmationDraft       // 仅公开可渲染字段，不含 schedulePayload
  unattendedAutoApprove: boolean
  expiresAt: string
  status: "pending"
}
```

## Endpoints

| Method | Path | 说明 | 响应 |
|---|---|---|---|
| GET | `/api/scheduled-tasks` | 列表（管理屏）；query `status?`, `limit?`, `offset?` | `ScheduledTaskListResponse` |
| GET | `/api/scheduled-tasks/{id}` | 任务详情（含详情页开关） | `ScheduledTaskItem` |
| PATCH | `/api/scheduled-tasks/{id}` | 暂停/启用、`unattendedAutoApprove` 开关（**仅这俩**） | `ScheduledTaskItem` |
| POST | `/api/scheduled-tasks/{id}/fire-now` | 行内「现在跑一次」（FR-018，立即触发动作） | `202 ScheduledTaskStartedRunItem`（类型固定 `status=running`、`sessionId: string`） |
| DELETE | `/api/scheduled-tasks/{id}` | 软删（`is_deleted=1`，历史保留） | `204` |
| GET | `/api/scheduled-tasks/{id}/runs` | 历史（query `limit?`, `offset?`） | `ScheduledTaskRunListResponse` |
| POST | `/api/scheduled-tasks/{id}/runs/{runId}/takeover` | 接管 `waiting_user`/`failed` run → 进入会话接着聊 | `TakeoverResponse` |
| POST | `/api/scheduled-tasks/confirmations/{requestId}/decision` | 创建确认卡决策（confirm / cancel / 编辑后 confirm） | `204`（cancel）/ `ScheduledTaskItem`（confirm 落库） |
| GET | `/api/scheduled-tasks/confirmations/pending` | 重连恢复；query `sessionId?`，省略时返回全局 pending 卡 | `{items: ScheduledConfirmationPendingItem[]}` |

## 错误映射

- `LookupError`（任务/run 不存在）→ `404 ErrorResponse(error.code="scheduled_task_not_found")`，不泄漏存在性差异。
- `ValueError`（PATCH 非法字段 / 状态非法转移 / schedule kind 与 payload 形态不匹配）→ `422`。
- `POST /{id}/fire-now` 可对 active / paused / completed / expired 管理态手动触发；paused
  仅阻止自动到点扫描，手动触发不得隐式 resume 或改变原 `next_fire_at`。
- `POST /{id}/fire-now` 在 sidecar runtime launcher 尚未装配时 → `503 scheduler_runtime_unavailable`；
  不得创建无 dispatch callback 的伪运行。
- `POST /{id}/fire-now` 若同 task 已有 active run → `409 scheduled_task_run_already_active`；
  若 session+run 原子落库或 dispatch 已失败 → `503 scheduled_task_start_failed`。原子落库
  失败不创建 run；dispatch 失败保留指向真实 session 的 failed run。只有实际进入
  `running` 才返回 `202 ScheduledTaskStartedRunItem`，前端不得把 failed / skipped 投影成成功 Toast。
- `POST /{id}/runs/{runId}/takeover` 对 v30/v31 期间遗留的 phantom/空 session 惰性自愈：
  先重建同 id、同 task 的 scheduled session，再返回 `recoveryDraft` 供用户核对后手动发送；
  修复失败 → `503 scheduled_takeover_unavailable`，不得返回不可用的 session id。
- 确认卡 `requestId` 已结算 / 归属错配 / 已超时 → `404`（统一不泄漏存在性，且已 fail-closed 拒绝）。
- 其余异常 → 全局 `500 desktop_api_error`。
- **token 不进任何响应正文**（守卫测试 `test_scheduled_tasks_api_auth.py` 断言无 token → 401）。

## 配置（走 `UnifiedConfigManager`）

新增 `scheduler.scan_interval_seconds`（bounded `[5,600]`，默认 30）与
`scheduler.confirmation_timeout_seconds`，统一经 `UnifiedConfigManager` getter 读取。
misfire 最近一次补跑与 reentry 跳过是 FR-010/FR-011 硬不变量，不提供可关闭它们的配置键。
