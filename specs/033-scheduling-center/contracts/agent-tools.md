# Contract: Agent Tools（主助理定时任务工具）

**注册**：`build_assistant_tools(session_id)` 的 import 白名单（`tool_registry.py:428-469`）+ `static_tools` 列表（`:638-663`）。schema/handler 放 `assistant_tools.py`（plain dict via `make_tool_schema`，仿 `user_todo` 五件套 + 032 约束写法）。**绝不进** `build_delegated_executor_tools`（`tool_registry.py:188-209`，executor 路径）—— guard test `test_scheduled_tool_boundaries.py` 守。

> **三重不暴露（CC-005 / FR-025）**：所有工具的 `properties` **不含** `unattended_auto_approve` 字段；handler 函数签名**不接**该字段；facade（service）调用时**不传**（强制 default False）。该字段唯一写入路径 = 创建确认卡勾选 / 详情页 PATCH 开关（`confirmation-and-unattended.md`）。三层静态断言 guard test `test_scheduled_task_unattended_field_isolated.py`（比 031 更严）。

## 工具清单（5 个）

### 1. `create_scheduled_task`

```jsonc
{
  "name": "create_scheduled_task",
  "description": "创建一个定时/周期/立即唤醒主助理执行的任务。创建后须经用户确认卡核对（标题/人话时间/指令）并勾选是否开启无人值守免确认后才落库；调用本工具不会直接落库。待办来源(source_type='todo')的任务恒为一次性(one_shot)，不支持周期。立即执行 = 创建 one_shot 且 run_at=当前时刻。时间字段以用户本地时区语义理解(如「每天9点」=本地9点)。",
  "properties": {
    "source_type": { "type": "string", "enum": ["direct", "todo"], "description": "direct=直接指令文本；todo=引用某条待办" },
    "instruction": { "type": "string", "description": "任务指令原文(direct 必填；todo 时预填待办 title+description，可被用户在确认卡编辑)。给 AI 当指令需足够具体" },
    "todo_id": { "type": "string", "description": "source_type='todo' 时填待办 id；direct 时省略" },
    "title": { "type": "string", "description": "展示标题" },
    "schedule_kind": { "type": "string", "enum": ["one_shot", "recurring"], "description": "todo 来源强制 one_shot" },
    "schedule_payload": { "type": "object", "description": "one_shot: {run_at:'now'|'<ISO 时刻>', tz?}; recurring: {kind:'interval'|'daily'|'weekly'|'weekdays', interval_seconds?, time_of_day?, weekdays?, tz?}. 无 offset 的 ISO / 日历时刻按显式 IANA tz 或桌面系统本地时区解释；带 offset 的 ISO 按其 offset；最终 next_fire_at 转 UTC 存储" }
  },
  "required": ["source_type", "schedule_kind", "schedule_payload"]
}
```
**handler**：组装 `draft`（含 `scheduleDescription` 人话、`next_fire_at` 试算）→ 提交 `SchedulingConfirmationManager` 创建 pending 确认卡 → emit `scheduling.confirmation_requested` → **不落 scheduled_tasks**。返回给主助理「已弹确认卡等待用户核对」。确认/取消经 REST decision endpoint。

### 2. `list_scheduled_tasks`

```jsonc
{ "name": "list_scheduled_tasks",
  "description": "列出当前用户的定时任务(供主助理回答用户查询)。返回标题/状态/调度描述/下次触发/上次结果；含是否开启无人值守免确认的标记。",
  "properties": {
    "status_filter": { "type": "string", "enum": ["active","paused","completed","expired"], "description": "可选" },
    "limit": { "type": "integer", "default": 20 },
    "offset": { "type": "integer", "default": 0 }
  } }
```
**handler**：调 `ScheduledTaskService.list`，返回 JSON。

### 3. `update_scheduled_task`（受限）

```jsonc
{ "name": "update_scheduled_task",
  "description": "更新定时任务的非核心字段。调度核心(schedule_kind/schedule_payload/source_type/source_ref)不可经此工具修改——改时间/改周期/改指令须删除后重新创建(经确认卡)。unattended_auto_approve 不可经此工具修改(只能由用户在 UI 确认卡勾选或详情页开关)。本工具仅允许改 title 等展示字段。",
  "properties": {
    "scheduled_task_id": { "type": "string" },
    "title": { "type": "string", "description": "仅展示字段可改" }
  },
  "required": ["scheduled_task_id"] }
```
**handler**：字段白名单过滤（拒收 `schedule_*` / `source_*` / `unattended_auto_approve` / `status`），调 service.update。`status` 暂停/启用走 `pause_scheduled_task`。

### 4. `pause_scheduled_task`

```jsonc
{ "name": "pause_scheduled_task",
  "description": "暂停或恢复一个定时任务。暂停期间过点的触发不补跑(one_shot 置 expired，recurring 滚动到下个未来时点)。",
  "properties": {
    "scheduled_task_id": { "type": "string" },
    "resume": { "type": "boolean", "default": false, "description": "false=暂停, true=恢复启用" }
  },
  "required": ["scheduled_task_id"] }
```
**handler**：CAS `status` 转移 `active⇄paused`。

### 5. `delete_scheduled_task`

```jsonc
{ "name": "delete_scheduled_task",
  "description": "软删定时任务(保留历史 runs 可追溯)。删除后不再触发。",
  "properties": { "scheduled_task_id": { "type": "string" } },
  "required": ["scheduled_task_id"] }
```
**handler**：CAS `is_deleted=1`。

## 不经工具的能力

- **`fire_now`（立即跑一次）**：是 UI 行内动作（REST `POST /{id}/fire-now`），第一批**不**作为主助理工具（避免主助理绕过确认卡直接点燃）；用户在对话要「现在跑」时，主助理引导用户在调度中心点「现在跑一次」，或创建 `one_shot(run_at=now)` 经确认卡。
- **`unattended_auto_approve` 开关**：仅 UI（确认卡勾选 / 详情页 PATCH），**无工具入口**。
- **接管 / 接着聊**：UI 入口（`POST /{id}/runs/{runId}/takeover`），非工具。

## 授权边界（guard test）

- `test_scheduled_tool_boundaries.py`：5 工具名 ∈ `build_assistant_tools(sid)()`、∉ `build_delegated_executor_tools(...)`。
- `test_scheduled_task_unattended_field_isolated.py`：`unattended_auto_approve` 不在 5 个 schema 的 `properties`、不在 5 个 handler 源码、不在 router `create/update` 源码（三层静态断言，`inspect.getsource`）。
