# Tasks: 调度任务常驻会话复用

## Phase 1：数据与原子启动

- [x] T001 为 v32 migration 写 RED 测试：列、索引、回填、幂等、downgrade、版本递增。
- [x] T002 实现 v32 migration 与 ORM 字段。
- [x] T003 为 task session CAS、active-per-session、run 消息窗口查询写 RED 测试。
- [x] T004 实现 ScheduledTask/ScheduledTaskRun/Message/AssistantTask Repository 接口。
- [x] T005 为首次原子绑定与第二次复用写 Launcher RED 测试。
- [x] T006 实现 Launcher 首绑/复用事务与 session 关系验证。

## Phase 2：运行时所有权与回流

- [x] T007 为 runtime reservation、普通 worker 冲突和 run-id 终态写 RED 测试。
- [x] T008 实现 reservation → reserved dispatch → release 协议。
- [x] T009 为 graph-scoped drain/re-enqueue/pending 写 RED 测试。
- [x] T010 实现 ParentReentrySink graph 维度队列与 runtime graph worker。
- [x] T011 调整 GraphScheduler 完成通知顺序并补行为保持测试。

## Phase 3：完成判定

- [x] T012 为旧 tool evidence、旧 graph、旧 summary、NULL graph 写 RED 测试。
- [x] T013 将 RunCompletionMonitor mutation interface 改为 run_id，并窗口化三类查询。
- [x] T014 补 graph event → message sequence → run window 映射测试。

## Phase 4：Reset、权限与 UI

- [x] T015 为 reset 成功/active/busy/不存在写 SchedulerService 与 REST RED 测试。
- [x] T016 实现 reset facade、router、auth guard。
- [x] T017 为旧 session unattended 权限失效写门卫测试并实现 current-session 校验。
- [x] T018 为 typed client/store/screen 按钮写前端 RED 测试并实现交互。
- [x] T019 保留 takeover recoveryDraft 的 legacy/损坏数据恢复覆盖。

## Phase 5：规格、文档与验证

- [x] T020 同步 architecture、constraints 和相关 AI 入口三镜像。
- [x] T021 运行 Python 专项、集成、desktop API、guardrail 测试。
- [x] T022 运行 Black、Flake8、前端 lint/build/unit/e2e。
- [x] T023 运行 Python 全量测试。
- [x] T024 按 review 技能审查 Standards/Spec，修复发现。
- [x] T025 提交当前分支。

## 验证记录

- 本功能扩大专项：340 passed；Black / Flake8 通过。
- 前端：lint、build、447 个 unit tests、6 个 scheduled-center E2E 均通过。
- 排除独立 MCP filesystem 文件后的全量：3273 passed；唯一一次真实 LLM 连通失败单独重跑通过。
- 完整全量另有 8 个可独立复现的既有 MCP filesystem stop 失败：未改动的
  `mcp_process_manager.py` 在 AnyIO cancel scope 外层使用 `asyncio.wait_for`，跨 task 关闭时报错；
  本特性未修改 MCP 源码或测试，故不扩大范围修复。
