# Tasks: 外部 Coding 内置技能组合与专员授权

**Input**: [spec.md](./spec.md), [plan.md](./plan.md)
**Tests**: 必须覆盖授权矩阵、持久化和 UI 单项配置。

## Phase 1 - 内置组合域

- [X] T001 定义稳定 ID、11 个同源成员和内置只读元数据。
- [X] T002 将内置组合接入 list/get/execution snapshot/assistant summary，并拒绝修改、发布、试用和同名创建。
- [X] T003 扩展 Desktop API 与前端组合 DTO，呈现 builtin/read-only/trial/assistant-enabled 状态。
- [X] T004 补组合服务、API、DynamicToolManager 激活测试。

## Phase 2 - 专员配置与持久化

- [X] T005 增加 SQLite v29 `composition_ids` migration、ORM 字段与 downgrade。
- [X] T006 在 SpecialistRepository 同步写入当前记录和版本记录。
- [X] T007 在 SpecialistService 校验 published、非待复核、assistant-enabled 组合。
- [X] T008 扩展专员 typed API、前端 store 与管理屏，只保存组合 ID。
- [X] T009 补 migration、Repository、Service、API 和 React 配置测试。

## Phase 3 - 正式 Task 运行时授权

- [X] T010 从持久专员配置推导允许组合，并对普通组合成员重校验父会话授权。
- [X] T011 仅为固定 executor specialist + 非空 Task + 显式授权构造 external coding ToolDefinition。
- [X] T012 维持 range 延迟激活：初始无 11 个成员，组合调用后成员才出现。
- [X] T013 对 main/ephemeral/planner/sync/unassigned/no-identity/guessed-ID 路径添加 fail-closed 门卫测试。

## Phase 4 - 文档、审查与验证

- [X] T014 更新架构、项目约束和 AI 入口镜像。
- [X] T015 清理 `docs/local/todo` 并归档完成摘要。
- [X] T016 执行后端相关套件、前端完整测试、lint/build 和静态检查。
- [X] T017 按 Standards 与 Spec 双轴审查并修复固定身份门卫和 assistant-enabled 展示缺口。
- [X] T018 提交实现并记录验证结果。

## Verification Results

- 后端相关闭环：`280 passed`（external coding、技能组合、专员、迁移、API、编排与门卫）。
- 前端全量：`48 files / 393 tests passed`；既有 `ErrorToastHost` 测试仍输出 React `act()` warning。
- 静态检查：ESLint、changed-file Black check、changed-file flake8、`git diff --check` 通过。
- 生产构建：TypeScript + Vite build 通过；保留既有大于 500 kB chunk 提示。
- 完整 `tests/` 后端套件曾两次分别在 120 秒和 600 秒执行上限内未结束、未返回失败摘要；本次以覆盖所有改动边界的 280 项闭环套件作为交付门卫。
