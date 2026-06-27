# Feature Specification: 用户待办任务列表

**Feature Branch**: `025-user-todo-list`  
**Created**: 2026-06-27  
**Status**: implementation  
**Input**: `docs/local/todo/user-todo-spec.md`

## User Stories

### P1 - 创建待办

用户可以在待办页面创建一条个人待办，标题必填，描述和优先级可选。新待办默认 `pending`，创建后出现在列表顶部。

**Acceptance**

- 标题为空时不创建，并返回可理解的校验错误。
- 标题、描述、优先级正确持久化。
- 超长标题和描述由业务层按限制截断，避免 UI 或 API 写入异常长文本。

### P1 - 查看和筛选待办

用户可以查看全部个人待办，并按 `all`、`open`、`done` 筛选；默认按创建时间倒序，也可以按优先级排序。

**Acceptance**

- `open` 包含 `pending` 与 `in_progress`。
- 优先级排序固定为 `urgent > high > medium > low`。
- 空列表显示空状态，不展示假数据。

### P1 - 完成和撤销完成

用户可以把 `pending` 或 `in_progress` 待办标记为 `done`，系统记录 `completed_at`；也可以撤销完成，状态回到 `pending` 并清空完成时间。

**Acceptance**

- 完成操作幂等。
- 撤销完成不会修改标题、描述、优先级。

### P2 - 编辑和删除待办

用户可以编辑标题、描述、状态、优先级；也可以在确认后删除不再需要的待办。

**Acceptance**

- 编辑不存在或已删除的待办返回 404。
- 删除是物理删除，删除后列表不再返回该记录。

### P2 - 通过 AI 助手管理待办

用户可以通过自然语言让助手创建、查询、完成、调整个人待办。

**Acceptance**

- 主助理不直接操作待办数据。
- 主助理把待办管理请求调度给临时执行体，执行体通过用户待办工具调用业务服务。
- 执行体无法明确匹配目标待办时，返回候选或说明需要用户确认。

## Functional Requirements

- **FR-001**: 系统 MUST 支持创建、查看、编辑、完成/撤销完成、删除个人待办。
- **FR-002**: 系统 MUST 将个人待办存储在本地 SQLite `user_todos` 表。
- **FR-003**: Desktop API MUST 只调用业务 service，不直接访问 Repository。
- **FR-004**: 前端 MUST 通过 typed API client 访问待办能力。
- **FR-005**: AI 管理待办 MUST 通过被调度执行体的工具完成，不把待办写工具加入主助理工具集。
- **FR-006**: 用户待办 MUST 与 task collaboration 的 `assistant_todo_items` 私人 checklist 完全隔离。
- **FR-007**: V1 MUST 不新增公开 UI event；UI 操作后通过 API 刷新权威列表。

## Data Model

`user_todos`

- `todo_id` primary key
- `title` required text
- `description` optional text
- `status`: `pending | in_progress | done`
- `priority`: `low | medium | high | urgent`
- `sort_order` integer
- `created_at`, `updated_at`, `completed_at`

## Out Of Scope

- 截止日期、提醒、重复任务、子任务。
- 云同步或多用户协作。
- 将个人待办挂到 task graph 节点。
