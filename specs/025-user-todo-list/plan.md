# Implementation Plan: 用户待办任务列表

## Summary

新增独立的个人待办模块，覆盖本地 SQLite 持久化、业务 service、Desktop API、执行体工具、前端主屏和测试。该能力不复用 `assistant_todo_items`，避免把用户个人待办与任务执行器内部 checklist 混在一起。

## Architecture

- Data: 新增 `UserTodo` ORM、v18 migration、`UserTodoRepository`。
- Business: 新增 `src/business/user_todos/`，集中校验、截断、状态/优先级归一化、投影。
- Desktop API: 新增 `/api/user-todos` router 和 DTO。
- Agent Tools: 新增 `create_user_todo`、`list_user_todos`、`update_user_todo`、`complete_user_todo`、`delete_user_todo`，只注册到 delegated executor 工具集。
- Frontend: 新增 `userTodos` typed API、Zustand store、`UserTodoScreen`、导航路由 `/todos`。
- Docs: 更新架构/约束/AI 入口镜像，完成后把本地 todo 草稿归档。

## Validation

- Repository/service 行为测试：创建、筛选、排序、完成幂等、删除。
- Desktop API 测试：CRUD contract、错误映射、路由注册。
- Agent 工具/门卫测试：用户待办工具存在于 delegated executor，不存在于主助理；工具通过 service 投影返回。
- Frontend 单测：页面加载、创建、完成、筛选。
- 静态验证：Python 相关 pytest、前端相关 vitest/lint。
