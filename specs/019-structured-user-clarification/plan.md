# Implementation Plan: 结构化多选澄清 (Structured Multi-Choice Clarification)

**Branch**: `019-structured-user-clarification` | **Date**: 2026-06-15 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/019-structured-user-clarification/spec.md`

## Summary

新增主助理专属、需独占调用的 `ask_user_question` 工具：模型在关键岔路口一次抛出 1–4 道结构化问题（每题 2–4 选项、单/多选、始终可用的"其他"自由输入），前端在聊天输入框上方以非模态卡片整组展示并提交。请求生命周期完全内存化（`request_id + threading.Event + lock`，first-decision-wins），默认 5 分钟超时；超时/取消/停止/关闭一律 fail-closed，模型绝不获得猜测答案。技术上复刻既有高危确认（`builtin_general_tools` 同步确认协议）与试用预览（`expires_at` + first-decision-wins + UI Event Registry）两套成熟模式，但与高危确认链路**完全分离**。不新增任何 SQLite/DuckDB 表、迁移或配置项。

## Technical Context

**Language/Version**: Python 3.11+（运行时 3.12）；TypeScript / React 18 / Vite
**Primary Dependencies**: 自研 AgentLoop、FastAPI sidecar、blinker、Zustand、Vitest、Playwright、pytest
**Storage**: 无新增持久化——请求与草稿仅驻留 sidecar 进程内存（dict + threading 原语）；前端草稿仅 Zustand 内存
**Testing**: pytest（`tests/business`、`tests/desktop_api`、`tests/integration`、`tests/guardrails`）；Vitest（`frontend/tests/unit`）；Playwright（`frontend/tests/e2e`）
**Target Platform**: Tauri 2 桌面壳 + 本地 FastAPI sidecar（Windows 优先）
**Project Type**: 桌面应用（前后端分离 + 本地 bridge）
**Performance Goals**: 工具发起到卡片可见 < 1s（事件流延迟级）；决策提交到 worker 唤醒 < 100ms（内存 Event）
**Constraints**: 内存态、单会话单 pending、5 分钟超时、secret 不入事件/DTO/前端状态、与高危确认零耦合
**Scale/Scope**: 单用户本地、未发布、无外部消费者；约 6 个后端文件 + 4 个前端文件 + 对应测试

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate question | Evidence |
|-----------|---------------|----------|
| I. 分层边界与事件协调 | 是否保持 `UI -> business -> execution -> data` 方向，跨模块通知是否走既有事件契约？ | ✅ 工具/manager 在 business 层；面向前端事件经 `src/desktop_api/ui_events.py` UI Event Registry 注册（`assistant.clarification_requested` / `assistant.clarification_resolved`）；停止/关闭唤醒沿用线程同步原语（与既有确认 fail-closed 同处）。无下层反调上层。 |
| II. 数据边界与持久化纪律 | SQLite/DuckDB 职责是否明确，Repository 边界是否保留？ | ✅ **不触碰任何数据存储**——零新表、零迁移、零 Repository 改动。状态纯内存（CC-001）。 |
| III. 统一配置与密钥安全 | 配置/secret 是否都走 `UnifiedConfigManager`，输出是否脱敏？ | ✅ **无新增配置项**。5 分钟超时为模块内常量（同 `CONFIRM_TIMEOUT_MS` 风格，非用户可调）。secret 防护：prompt 禁令 + 事件 payload 经 `ui_event_safety_service` 递归扫描禁用值 + `clarification_resolved` 不含答案。 |
| IV. 可验证交付 | 是否覆盖确定性逻辑 + 链路冒烟/门卫测试？ | ✅ manager 单测（校验/单多选/其他/并发/超时/停止/关闭/事件失败）、AgentLoop 独占混批门卫测试、API/event 契约测试、集成链路冒烟、前端单测 + e2e；并修复既有 `test_auth_toast_confirmation.py` 纳入门禁。 |
| V. 活文档与规格驱动交付 | 是否标明要更新的活文档？临时材料是否限定 `docs/local/`？ | ✅ 更新 `docs/ARCHITECTURE.md`、`docs/PROJECT_CONSTRAINTS.md`、根/模块 AI 入口镜像、`docs/local/todo/agent-tool-patterns.md`（标记第 ② 项已实现）；本特性 spec/plan/tasks 在 `specs/019-*/`。 |

**结论：全部通过，无需 Complexity Tracking 例外。**

## Project Structure

### Documentation (this feature)

```text
specs/019-structured-user-clarification/
├── plan.md              # 本文件
├── spec.md              # 已完成
├── research.md          # Phase 0（本次生成）
├── data-model.md        # Phase 1（本次生成）
├── quickstart.md        # Phase 1（本次生成）
├── contracts/           # Phase 1（本次生成）
│   ├── tool_ask_user_question.md
│   ├── api_clarifications.md
│   └── events_clarification.md
└── checklists/
    └── requirements.md  # 已完成
```

### Source Code (repository root)

```text
src/business/agents/
├── config.py                              # [改] ToolDefinition 增加 requires_exclusive_call 字段
├── agent_loop.py                          # [改] _execute_tool_batch 增加独占混批拒绝；solo 独占走普通阻塞路径
├── tools/
│   ├── clarification_manager.py           # [新] 线程安全 pending 管理 + first-decision-wins（独立于 confirm 机制）
│   └── assistant_tools.py                 # [改] ASK_USER_QUESTION_SCHEMA + create_ask_user_question_handler + 输入校验
└── prompts/
    └── assistant_prompt.py                # [改] 何时用、一次问齐、secret 禁令、取消/超时后行为

src/business/orchestration/agent/
└── orchestrator.py                        # [改] _build_assistant_tools 注册 ask_user_question（仅主助理）

src/desktop_api/
├── clarifications.py                      # [新] desktop adapter：signal/event payload/decision/pending 快照/stop+shutdown 结算
├── ui_events.py                           # [改] 注册两个公开事件 + payload allowlist + enum
├── assistant_runtime.py                   # [改] install_clarification_signal；cancel_session 并排结算 stopped
├── app.py                                 # [改] lifespan shutdown 结算 shutdown
├── schemas.py                             # [改] 决策请求/响应 + pending 快照 DTO
└── routers/
    └── assistant.py                       # [改] GET pending + POST decision 两个会话级端点

frontend/src/
├── api/
│   └── assistant.ts                       # [改] 类型 + getPendingClarifications/submitClarificationDecision
├── state/
│   └── assistantStore.ts                  # [改] 按 session 存 pending/草稿/提交态；事件消费；resync 刷新；切换会话保留草稿
└── screens/assistant/
    ├── ClarificationCard.tsx              # [新] 输入框上方非模态卡片（fieldset/radio/checkbox + 其他 + 倒计时）
    └── AssistantScreen.tsx                # [改] 渲染 ClarificationCard（独立于 ConfirmationToast）
```

### Tests

```text
tests/business/test_clarification_manager.py          # [新] manager 单元：校验/单多选/其他/并发/超时/停止/关闭/事件失败
tests/business/test_agent_loop_exclusive_tool.py      # [新] 独占工具 solo 续跑 + 混批零执行完整配对
tests/desktop_api/test_clarification_api.py           # [新] 归属/重复/过期/pending 快照/payload allowlist/resolved 不含答案
tests/integration/test_clarification_flow.py          # [新] 模型发起→event→API 回答→tool result 入上下文→主助理续跑
tests/test_auth_toast_confirmation.py                 # [改] 修复 build_write/edit/exec_summary 迁移后的过时引用
frontend/tests/unit/clarificationCard.test.tsx        # [新] 键盘/选择规则/倒计时/提交防重/会话切换/取消停止
frontend/tests/e2e/assistant.spec.ts                  # [改/扩] 澄清卡 e2e（mock API）
```

**Structure Decision**: 沿用既有四层结构（`frontend` / `desktop_api` adapter / `business` / 无 data 改动）。澄清能力作为 business 层工具 + 内存 manager 落地，desktop_api 仅做 DTO/事件/路由 adapter，前端走 typed client + Zustand，严格遵守分层与 UI Event Registry。

## Complexity Tracking

> 无 Constitution 违例，无需填写。
