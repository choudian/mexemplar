# Implementation Plan: 主助理对话透明与可控

**Branch**: `014-assistant-chat-transparency` | **Date**: 2026-06-03 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `specs/014-assistant-chat-transparency/spec.md`

## Summary

把"黑盒"的主助理对话变成**看得见、停得下、接得上**：运行时输入门控、可中断的"停止"（深度取消，穿透其同步派出的子任务）、单条原地编辑的排队、实时可折叠的过程时间线、子任务可观测卡片与详情、对暂停子任务的"继续任务"。

技术核心是一个**业务层的"Agent 运行上下文" ContextVar**（持 `{root_session_id, cancel_event}`，在 worker 线程入口设置），`AgentLoop` 在迭代边界与工具批次前读取它实现**协作式深度取消**与**逐步活动事件**；面向前端的过程/子任务/取消信号一律走 `blinker → ui_event_projector → UI Event Registry` 的 typed envelope；"继续任务"复用既有 `continue_subagent` 并经主助理调度（守 100% 调度）；排队为前端驱动的单条状态机。无新增 SQLite 表/迁移，历史过程由既有消息重建。

## Technical Context

**Language/Version**: TypeScript（前端，React 18 + Vite）、Python 3.12（后端 sidecar/业务层）
**Primary Dependencies**: React 18、Zustand 5、lucide-react（前端）；FastAPI、blinker、LangChain、自研 AgentLoop（后端）
**Storage**: SQLite（**只读复用** `MessageRepository` / `WorkflowTransitionRepository` / `SessionRepository` 重建过程与子任务列表；**无新表、无迁移**）；不触 DuckDB
**Testing**: Vitest + React Testing Library + Playwright（前端 `frontend/tests/unit`、`frontend/tests/e2e`）；pytest（`tests/business`、`tests/desktop_api`、`tests/integration`、`tests/guardrails`）
**Target Platform**: Tauri 2 桌面应用（Windows 主）
**Project Type**: desktop-app（前端 + Python FastAPI sidecar + 业务层）
**Performance Goals**: 活动事件随执行实时到达 UI；"停止"点击即时反馈、在当前步骤返回后的下一个安全节点生效；过程事件载荷有界（文本截断）
**Constraints**: 取消必须协作式（不得硬杀线程）；非助理 Agent（PM/Programmer/Trial）零行为变化；面向前端事件必经 UI Event Registry；UI 文案不暴露内部术语；排队/草稿不持久化到后端
**Scale/Scope**: 单用户本地桌面；同一时刻一个活跃会话；助理委派深度有界（子代理/专员不再向下委派）

## Constitution Check

*GATE: 已在 Phase 0 前评估，并在 Phase 1 设计后复检——全部 PASS，无例外。*

| Principle | Gate question | Evidence |
|-----------|---------------|----------|
| I. 分层边界与事件协调 | 是否保持 `UI -> business -> execution -> data` 方向、跨模块通知走 `src/utils/events.py`？ | 触及层：UI（`frontend/`）、desktop_api、business（agents/orchestration）、utils。取消原语在 **business** 层（`src/business/agents/run_context.py`），`AgentLoop` 读取；面向前端的过程/子任务/取消信号经 **blinker** 新事件（`assistant_agent_step`、`assistant_subagent_*`）→ `ui_event_projector` → UI Event Registry typed envelope（`assistant.activity`、`assistant.subagent`、`assistant.progress` 增 `cancelled`）。前端只消费注册过的 typed event。停止/子任务/transcript 端点在 desktop_api，调用 business facade。**无下层反调上层**。 |
| II. 数据边界与持久化纪律 | SQLite/DuckDB 职责是否清晰、Repository 边界是否保留？ | **无新表、无迁移**。子任务列表与过程由既有 `MessageRepository`（中间 assistant + tool 消息）、`WorkflowTransitionRepository`（委派流转）、`SessionRepository` 经 Repository 边界**只读**重建。不写裸 SQL，不触 DuckDB/`network_requests`。 |
| III. 统一配置与密钥安全 | 新配置是否走 `UnifiedConfigManager`、密钥是否在 keyring？ | 取消检查节点等如需可调阈值，走 `get_unified_config()` 占位（默认值内置，Settings UI 暂不暴露，沿用 `brain.*` 既有做法）。**无新增密钥/敏感字段**。多数为 N/A。 |
| IV. 可验证交付 | 是否覆盖确定性逻辑 + 接线冒烟/门卫测试？ | 后端：loop 取消（迭代边界/工具批次前）、深度取消父子链、runtime `cancel_session`、stop/subagents/transcript 端点、`CANCELLED` 非错误、projector 映射、**非助理 Agent 零 emit/零行为变化门卫**、`assistant_agent_step` 路由（root + subagentId）。前端：composer 三态机（idle/editing/queued）、排队自动派发与边界、停止退回草稿、活动时间线折叠/限高、子任务卡片+双击详情、scope 过滤。AgentLoop 属高风险共享核心 → 必补行为契约测试。 |
| V. 活文档与规格驱动交付 | 活文档是否识别、临时材料是否在 `docs/local/`？ | 更新 `docs/ARCHITECTURE.md`（新事件/端点/取消原语）、`frontend/AGENTS.md`+镜像（助理屏新交互）、`src/AGENTS.md`+镜像（取消原语/活动事件/CANCELLED）；设计记录在 `docs/design/assistant_chat_transparency_design.md`（非"当前真相"）；过程草稿入 `docs/local/`。spec/plan/tasks 在 `specs/014-…`。 |

无门禁失败，**Complexity Tracking 留空**。

## Project Structure

### Documentation (this feature)

```text
specs/014-assistant-chat-transparency/
├── plan.md              # 本文件
├── research.md          # Phase 0：关键技术决策
├── data-model.md        # Phase 1：运行时/UI 实体与状态机
├── quickstart.md        # Phase 1：验证路径
├── contracts/           # Phase 1：UI 事件与端点契约
│   ├── ui-events.md
│   └── http-endpoints.md
└── tasks.md             # Phase 2（/speckit.tasks 生成，非本命令）
```

### Source Code (repository root)

```text
frontend/src/
├── screens/assistant/
│   ├── MessageComposer.tsx        # 改：running→停止、单条原地排队三态机（idle/editing/queued）
│   ├── ActivityTimeline.tsx       # 新：默认折叠、限高内滚的过程时间线
│   ├── SubagentCard.tsx           # 新：子任务卡片（动效/状态/双击/继续任务）
│   ├── SubagentDetailDrawer.tsx   # 新：子任务完整过程（含工具）抽屉
│   └── AssistantScreen.tsx        # 改：渲染时间线/卡片，接停止/排队/继续
├── state/
│   └── assistantStore.ts          # 改：progress 驱动门控、queuedMessage 状态机、activity/subagents、stop/continue
├── api/
│   └── assistant.ts               # 改：stopAssistantRun / listSubagents / getSubagentTranscript
└── styles/theme.css               # 改：时间线、卡片、排队三态样式

src/
├── business/
│   ├── agents/
│   │   ├── run_context.py         # 新：ContextVar 运行上下文（root_session_id + cancel_event）+ session→Event 表
│   │   ├── agent_loop.py          # 改：迭代边界/工具批次前取消检查 → CANCELLED；逐步 emit 活动事件
│   │   ├── config.py              # 改：ResultType.CANCELLED
│   │   └── observability.py       # 新：只读读模型，由既有 Repository 重建 transcript / 子任务权威列表（含压缩标记，不新增持久化）
│   └── orchestration/agent/orchestrator.py  # 改：CANCELLED 当正常终止；委派点 emit 子任务生命周期；续跑处理
├── desktop_api/
│   ├── assistant_runtime.py       # 改：begin/end 运行上下文、cancel_session、CANCELLED flush + cancelled 进度
│   ├── routers/assistant.py       # 改：stop / subagents / transcript 端点
│   ├── ui_events.py               # 改：注册 assistant.activity / assistant.subagent，progress 增 cancelled
│   └── ui_event_projector.py      # 改：assistant_agent_step / assistant_subagent_* → typed UI 事件
└── utils/events.py                # 改：声明新 blinker 事件

tests/
├── business/                      # loop 取消、深度取消父子链、CANCELLED 非错误、活动事件路由
├── desktop_api/                   # runtime cancel、stop/subagents/transcript 端点、projector 映射
└── guardrails/                    # 非助理 Agent 零行为变化、前端只消费注册事件

frontend/tests/
├── unit/                          # composer 三态机、排队边界、时间线折叠/限高、卡片/详情
└── e2e/                           # 助理屏：发→停止→继续、排队自动派发冒烟
```

**Structure Decision**: 桌面应用既有结构上的**扩展**，不新增顶层目录或项目。前端在 `frontend/src/screens/assistant/` + `state/` + `api/` + `styles/`；后端取消原语落 `src/business/agents/`，事件经 `src/utils/events.py` + `src/desktop_api/ui_event_projector.py` + `ui_events.py`，入口在 `src/desktop_api/routers/assistant.py`。测试分布于 `frontend/tests/` 与 `tests/{business,desktop_api,guardrails,integration}`。

## Complexity Tracking

> 无 Constitution 违例，留空。

## Critique 修订（2026-06-03，来自 critiques/critique-20260603.md）

工程加固项，纳入实现与测试约束：

- **E1 同线程不变量门卫**：深度取消依赖"子代理/专员与父在**同一线程同步**执行"（ContextVar 才能传播）。MUST 补门卫测试断言委派同线程执行，并在 `run_context.py`/委派处注释该承重不变量；一旦委派改走线程/异步即需重审取消机制。
- **E2 取消 Event 生命周期**：`session_id → Event` 表项 MUST 在 `end()` 清除；每次运行配一个**代际 token**，使陈旧 `set` 无法误取消复用同一 session 的新一轮运行。补回归测试。
- **E4 活动事件门控与上限**：`AgentLoop` MUST 仅在 ContextVar 存在（即可观测的助理/子代理运行）时 emit 活动事件，避免对 PM/Programmer/Trial 发无效事件；单回合活动事件设上限/合并，防极端长回合刷爆前端 store。
- **E5 载荷脱敏**：`assistant.activity` / `assistant.subagent` 载荷 MUST 显式走 009 既有 payload safety allowlist 脱敏（不仅截断），防工具入参/结果夹带敏感数据外泄到事件流/UI。
- **X2 续跑校验+兜底**：见 spec FR-030a——续跑后校验目标子任务确从 suspended→active；主助理未续跑时给用户兜底提示。
- **E3 历史保真（已定）**：历史回合被压缩则以规整概要展示，**不补充持久化**（无新表/迁移）；与 Storage/Constitution II 一致。
- **P2 实时全量（已确认）**：本期维持实时全量活动时间线（用户决定）；作为风险最高的共享 `AgentLoop` 改动，以行为契约测试包住。
