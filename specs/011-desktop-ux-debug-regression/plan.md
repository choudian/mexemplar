# Implementation Plan: Desktop UX, Debug Inspector, and Grand Tour Acceptance

**Branch**: `011-desktop-ux-debug-regression` | **Date**: 2026-05-24 | **Spec**: [spec.md](./spec.md)  
**Input**: Feature specification from `specs/011-desktop-ux-debug-regression/spec.md`

## Summary

本功能交付三项互相可独立验收的开发体验增强：Assistant 与 Teaching 共用长粘贴折叠交互；开发者在隐藏诊断入口阅读警示并显式武装当前 sidecar 会话的 runtime-only trace 后查看真实 LLM trace 与 Agent Flow，应用壳在捕获期间持续提供停止操作；提供单独手动触发、使用真实后端与真实模型、但隔离业务数据且严格只读凭据的 Grand Tour 验收套件。三个 slice 设置独立通过门槛，使低风险的输入体验改进不依赖高风险诊断/真实录制能力才能验收。

技术路径为：前端以共享 hook/预览组件保留完整 draft 并只折叠展示；后端新增 `DebugInspectorService` 与业务拥有的 control facade，以 `UnifiedConfigManager.set(..., persist="runtime")` 驱动启停、epoch purge 和 authenticated control status，持有记录数与字节双重有界的 trace/correlation/ephemeral flow-detail 缓冲区；统一 model invocation 观察边界 failure-isolated 地捕获文本、工具与视觉调用（视觉仅记录媒体元数据，不保留 base64/字节；embedding/vectorization 不生成 trace record），并由 orchestration 上下文补齐来源；Agent Flow 读取现有 `workflow_transitions` 权威状态事实，在 trace 武装期间从委派边界临时补充当前进程可用的 Assistant task/result detail；真实 Grand Tour 以独立 opt-in Playwright 配置运行，执行脚本化无敏感内容现场旅程，消费既有安全 UI event contract 作为等待信号，经注入到 real-tour 可触达的 main/vision/background/settings validation/skill-composition/compression/embedding/redactor 路径的无副作用凭据 provider 调用真实模型或读取凭据，并输出非敏感运行摘要。

## Technical Context

**Language/Version**: Python 3.12 runtime target（项目兼容 `>=3.11`）、TypeScript 5.7、React 18、Rust/Tauri 2 unchanged  
**Primary Dependencies**: FastAPI、Pydantic、SQLAlchemy、blinker、LangChain（ChatAnthropic / ChatOpenAI）、Zustand、Vite/Vitest、Playwright  
**Storage**: SQLite 中既有 `workflow_transitions` / session/message / `app_settings`；DuckDB 仅由真实录制既有路径使用；新增 trace、ephemeral delegation detail 与 correlation 不持久化  
**Testing**: pytest（business/desktop_api/integration/guardrails）、Vitest + React Testing Library、Playwright（受控 E2E 与手动 real Grand Tour 分离）  
**Target Platform**: Windows 桌面应用（Tauri 2 + localhost FastAPI sidecar + React UI）  
**Project Type**: Desktop app with local authenticated API bridge  
**Performance Goals**: 长粘贴交互即时响应且不复制持久数据；调试列表默认在最近 200 条、单条 1 MiB、合计 16 MiB 的初始保留预算内快速打开；trace 关闭时采集开销仅剩配置判断；Grand Tour 以事件/状态推进而非固定睡眠等待，单次人工运行最多 20 分钟与 30 次付费模型请求  
**Constraints**: trace 在每次 sidecar 启动时默认关闭且只能经鉴权、警示确认后的 runtime-only control arm 启用；raw textual prompt/response、debug-only handoff detail 与 correlation 只在本进程当前启用 epoch 的有界内存中存在，disable/clear/restart 必须销毁，且不得进入 HTTP/WebView cache、URL 或前端持久化状态；观察/脱敏/缓冲故障不得改变被观察模型调用结果；视觉输入不保存可还原媒体 bytes/data URL；embedding/vectorization 不纳入 trace record；应用控制的主模型/视觉/embedding secret 与 runtime token 在保存/返回前脱敏且 ordinary logs 禁止 diagnostic raw 内容；真实验收不得触发 keyring mutation 或日常业务数据写入  
**Scale/Scope**: 单本地进程、单开发者诊断入口；两个 composer；现有 Teaching 与 Assistant delegation flow；独立手动 Grand Tour 场景集

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| 原则 | 门卫问题 | 证据 |
|------|----------|------|
| **I. 分层边界与事件协调** | 是否保持 `UI -> business -> execution -> data/driver`，且通知不绕开事件边界？ | **通过**。长粘贴是前端局部状态；debug 调用链为 `DebugScreen -> typed debug API -> DebugInspectorService -> repository/unified model observation boundary`；router 不读 Repository。Agent Flow 使用已有权威 transition，额外 task/result detail 仅由业务委派边界捕获到临时诊断存储，raw 详情不加入公共 SSE。Grand Tour 只消费 `ui_events.py` 注册的安全事件。 |
| **II. 数据边界与持久化纪律** | SQLite/DuckDB 与 Repository 边界是否明确？ | **通过**。Trace/correlation/ephemeral delegation-detail buffer 为带 epoch 和字节预算的进程内对象，不新增 schema。Flow 对已有 SQLite `workflow_transitions` 的查询继续经 `WorkflowTransitionRepository` 进入业务 service，且不得把新增 raw detail 回写数据库。真实录制仍走 `DesktopRecordingService` 与既有 DuckDB/过滤边界。 |
| **III. 统一配置与密钥安全** | 新配置是否走统一配置，密钥是否安全？ | **通过**。`debug.trace.enabled` 仅由鉴权 debug control facade 通过 `get_unified_config().set(..., persist="runtime")` 驱动，sidecar 重启回到关闭；容量键与 reference response limit 仍经 unified accessor 读取且不在普通 Settings UI 暴露。Trace/redaction inventory 覆盖已创建客户端实际使用的主模型、vision、embedding credential 与 runtime token；ordinary logs 去除 diagnostic raw LLM/委派数据。Grand Tour 将 side-effect-free credential provider 注入 real-tour 可触达的 main/vision/background/settings validation/skill-composition/compression/embedding/redactor paths，禁止配置迁移、plaintext fallback 或 keyring write/delete。 |
| **IV. 可验证交付** | 确定性逻辑和静默失败路径是否有覆盖？ | **通过**。规划覆盖 composer paste/selection/keyboard 单测、trace arm 警示与 banner/stop 链路、text/tool/vision model invocation coverage 与 direct-invoke guard、trace disable-reenable/byte-budget/redaction/log-capture 单测、观察故障隔离注入、debug API auth/control/clear/reference/no-store 测试、ephemeral delegation detail/transition correlation 集成测试、禁止 diagnostic-only raw public-event/log/cache/frontend-persistence 的门卫测试，以及 real-tour runner 的无费用失败注入、credential-provider inventory/audit 与独立 opt-in 人工 Grand Tour。 |
| **V. 活文档与规格驱动交付** | 活文档与模块指引是否识别？ | **通过**。实现阶段需更新 `docs/ARCHITECTURE.md`、`docs/PROJECT_CONSTRAINTS.md`、`frontend/AGENTS.md` 与 `src/AGENTS.md` 及各自镜像，说明隐藏 debug 入口、短期原始数据边界和真实验收例外；输入待办仍留在 `docs/local/`。 |

**Post-design re-check**: 通过。第三轮 Critique 修订后，Phase 1 设计将 raw capture 限定为警示确认后的 authenticated runtime-only arm，补齐 trace-active stop/purge、failure-isolated observation、product-message versus diagnostic-only SSE 边界、HTTP/WebView cache 与前端持久化边界；Grand Tour 合同将无副作用 credential provider 注入所有 real-tour 可触达 credential/model/redactor 路径，并要求可审计、非敏感的人工运行报告；embedding/vectorization 明确不属于 trace record 覆盖，但仍进入 credential/redaction/provider inventory；未引入 constitution 例外。

## Project Structure

### Documentation (this feature)

```text
specs/011-desktop-ux-debug-regression/
├── plan.md
├── research.md
├── data-model.md
├── quickstart.md
├── contracts/
│   ├── composer-ui.md
│   ├── debug-api.md
│   └── grand-tour.md
└── tasks.md                 # Phase 2: /speckit.tasks 输出，不由本命令创建
```

### Source Code (repository root)

```text
frontend/
├── src/
│   ├── api/
│   │   └── debug.ts                         # 新增：typed debug control/data REST client
│   ├── app/
│   │   ├── AppShell.tsx                     # 支持隐藏诊断页与 armed 时持续 trace-active stop banner
│   │   └── routes.tsx                       # 分离普通 nav routes 与隐藏 debug route
│   ├── components/
│   │   └── LongPastePreview.tsx             # 新增：两类 composer 共享的预览/操作区
│   ├── hooks/
│   │   └── useLongPasteCollapse.ts          # 新增：精确保留选区插入及临时折叠状态
│   └── screens/
│       ├── assistant/MessageComposer.tsx    # 接入共享长粘贴交互
│       ├── teaching/shared.tsx              # ChatComposer 接入共享交互
│       └── debug/                           # 新增：Trace / Agent Flow 隐藏诊断视图
└── tests/
    ├── unit/
    │   ├── long-paste-composer.test.tsx
    │   └── debug-screen.test.tsx
    └── e2e/
        ├── grand-tour.real.spec.ts          # 新增：显式 opt-in 真实验收
        ├── helpers/event-watcher.ts
        ├── helpers/real-grand-tour-runtime.ts
        └── pages/                           # 真实旅程 page objects

src/
├── business/
│   ├── ai/llm_client.py                     # 在统一 provider 调用边界采集 trace
│   ├── agents/agent_loop.py                 # 设置 session/agent/iteration trace context
│   ├── agents/tool_helpers.py                # vision 调用迁入统一观察边界并支持凭据 provider 注入
│   ├── agents/tools/assistant_tools.py       # 委派 ordinary log 改为安全摘要
│   ├── brain/                               # 后台 LLM 来源上下文标注及 real-tour provider 透传
│   ├── memory/context_manager.py            # 复用现有 reference 加载能力
│   ├── memory/assistant_memory.py           # embedding credential lookup 纳入 provider/redaction inventory；不生成 trace record
│   ├── memory/compression_handler.py        # compression LLM 纳入 real-tour provider inventory
│   ├── services/settings_actions_service.py # real-tour settings validation 使用只读 credential snapshot
│   ├── services/skill_composition/          # composition/trial LLM factory 纳入 provider inventory 或 scenario 显式跳过
│   ├── orchestration/agent/orchestrator.py  # flow correlation 的权威执行切入点
│   └── debug/                               # 新增：control facade、DebugInspectorService、context、buffer、redaction
├── data/
│   ├── unified_config.py                    # 新增 runtime-only debug arm / retention accessor；无迁移
│   └── credential_resolver.py               # 新增：real-tour keyring-only、无副作用 credential provider
└── desktop_api/
    ├── app.py                               # 注册受 session middleware 保护的 debug router
    ├── orchestrator_runtime.py              # real-tour 时把只读 credential provider 注入模型工厂
    ├── schemas.py                           # Debug DTO
    └── routers/debug.py                     # 仅调用 business debug control/data facade

tests/
├── business/debug/                          # control、buffer、redaction、failure isolation、reference tests
├── desktop_api/test_debug_api.py            # 鉴权/control arm/DTO/clear tests
├── integration/test_debug_flow_trace.py     # transition 与 trace correlation
└── guardrails/test_debug_boundaries.py      # 无 durable raw trace / 无 diagnostic-only raw public-event 泄漏

docs/
├── ARCHITECTURE.md
└── PROJECT_CONSTRAINTS.md
```

**Structure Decision**: `src/business/debug/` 拥有诊断控制、secret inventory、epoch/byte-bounded lifecycle、failure isolation 与临时 delegation detail，避免 `src/utils/` 变成含敏感业务内容的全局容器，也避免 API router 越层读取数据库。Hidden debug route `/debug` 在禁用状态仅调用受鉴权 control API 展示警示并以 runtime-only unified-config arm 启用；armed 状态由 `AppShell` 显示停止提示。已有 `WorkflowTransitionRepository` 保持权威状态来源；对当前持久 payload 已包含的 Teaching detail 直接脱敏投影，对现有 Assistant transition 未保存的 task/result 仅在 tracing epoch 内由 orchestrator 的委派执行边界捕获并附加。统一 model invocation observation 必须覆盖现有 text/tool/vision LLM direct invoke，并吞住自身诊断故障而保持 provider outcome；embedding/vectorization calls 不生成 trace records，但必须登记到 credential inventory/allowlist。ordinary logging 只输出安全摘要。Grand Tour 使用 `src/data/credential_resolver.py` 的只读 provider，并由 real-tour 可触达 factories/actions 显式透传，不能退回普通 migration-capable getter。

## Delivery Slices

### Slice P1: Long-Paste Composer Experience

新增共享 `useLongPasteCollapse` 与预览呈现，Assistant/Teaching 都在 `paste` 时依据“插入后的完整草稿”判断折叠，保留选区插入、混合换行和超长单行内容。折叠阈值固定为插入后草稿达到 `7` 个逻辑行（按 `\r\n`、`\n` 或 `\r` 分隔计数但不改写正文）或超过 `1200` 个 JavaScript `string.length` code units；恰好 `1200` 且少于 `7` 行不折叠，`7` 行或 `1201` code units 折叠。覆盖展开、收起、清空、发送重置、键盘可访问、边界值以及纯手输不自动折叠。

### Slice P2: Local Trace Inspector

新增业务拥有的 authenticated trace control facade、统一配置 runtime-only arm accessor、epoch/byte-bounded 进程内 trace buffer、application-controlled secret inventory/redaction 与 trace context。隐藏诊断页在禁用状态仅显示警示和 arm 控件；arm 通过 `UnifiedConfigManager.set(..., persist="runtime")` 创建新 epoch，armed 期间 `AppShell` 显示停止提示，停止/重启立即 purge/reset。抽取统一 model invocation observation boundary 覆盖 `LangChainLLMClient.chat()`、`chat_with_tools()` 与现有视觉调用 helper，审计并禁止其它受支持 text/tool/vision LLM 路径直接绕开采集；embedding/vectorization path 不生成 trace record，但进入 credential/redaction/provider allowlist。捕获、脱敏或 buffer 故障必须 fail-isolated，不改变 provider 成功/失败结果。文本调用保存经脱敏且在预算内的原始文本；多模态调用仅保存文本块与媒体类型/数量/字节大小等元数据，绝不保存 base64/data URL。移除或安全化当前输出 raw request/response/tool args 的 DEBUG 日志。新增受鉴权、受 arm 限制且设置 `Cache-Control: no-store` 的 debug data API，支持筛选、详情、清空和有响应预算/分块语义的引用展开；DebugScreen raw state 只保存在内存，clear/disable/离开 `/debug` 时清除。

### Slice P3: Agent Flow Correlation

通过 debug service 查询已有 Teaching 与 Assistant delegation `workflow_transitions`，展示真实顺序、session/agent、状态及实际已经持久保存的 payload。由于现有 Assistant delegation transition 不包含 task/result 原文，在 tracing epoch 开启期间由 orchestrator 委派切入点另行捕获 redacted ephemeral detail，并与 transition/workflow/trace 关联；disable/clear/restart 后删除这部分详情。不扩展公共 SSE、不新增 durable correlation，并覆盖无 trace 或无 ephemeral detail 的 transition 仍显示为 unlinked/unavailable。

### Slice P4: Real Grand Tour Acceptance And Living Docs

将真实验收与默认 mock E2E 分离：随机 sidecar token/端口、临时业务数据和非密钥配置、注入到 main/vision/background/settings validation/skill-composition/compression/embedding/redactor 的 keyring-only side-effect-free credential provider、显式付费/录制隐私确认、文档化无敏感内容现场旅程、20 分钟/30 次付费调用预算，以及基于安全公共状态/事件的等待与清理报告。Skills/compositions 场景默认限定为隔离业务数据的 visibility/create/read，不触发 LLM；若实现选择触发 generation/trial，必须纳入 paid-call budget 与 provider inventory。每轮生成关联 commit/journey 的非敏感 summary report；另提供不调用模型、不录制真实桌面的 runner failure tests，注入 timeout/cancel/stop failure/secret-mutation attempt，并以可观测 keyring audit guard 捕获短暂 mutation attempt。Real-tour Playwright artifacts 默认关闭 trace/video/screenshot，失败输出仅保留经 sentinel 检查的安全 summary/status。同步活文档与模块 AI 镜像，记录此手动例外和 debug 敏感数据边界。

## Delivery Gates

| Slice | Independent completion gate | Does not wait for |
|-------|-----------------------------|-------------------|
| P1 Composer | 两处 composer 的文字精确发送、临时状态重置和键盘覆盖通过 | Debug 或 real-tour 实现 |
| P2 Trace Inspector | invocation coverage、disable epoch、byte budget、secret/log guard 与 authenticated API/UI 覆盖通过 | Real Grand Tour 手动执行 |
| P3 Agent Flow | persisted fact 与 ephemeral detail 区分、委派 detail/correlation、unlinked fallback 覆盖通过 | Real Grand Tour 手动执行 |
| P4 Real Grand Tour | controlled runner failure tests 通过且人工脚本旅程记录结果 | 不并入默认 E2E |

**Merge/Release Policy**: P1 可在其独立测试和文档满足后单独合入，不等待 P2-P4。P3 依赖 P2 提供的 trace/control 基础，可与 P2 同一交付批次或在 P2 后合入。P4 是发布前真实链路验收能力，不阻塞 P1/P2/P3 的开发合入，但在宣称 real-tour 覆盖可用或以其作为发布证据前必须通过自身 gate。

## Raw Diagnostic Lifecycle

| Data | Source | Lifetime | Clear / Disable / Restart | Ordinary log / SSE |
|------|--------|----------|---------------------------|--------------------|
| Trace arm state | authenticated debug control facade -> runtime unified config | current sidecar process only | N/A / false + purge / false | safe active status only / no raw data |
| Text trace input/output/tool args | unified model observation boundary | current tracing epoch; count + byte bounded | purged / purged / lost | forbidden / forbidden |
| Vision input | unified model observation boundary | text blocks + media metadata only; no restorable bytes | purged / purged / lost | forbidden / forbidden |
| Existing workflow transition fact | `WorkflowTransitionRepository` | existing business lifecycle | not deleted by debug clear/disable | existing safe public projection only |
| Extra Assistant delegation task/result detail | orchestrator delegation boundary while enabled | current tracing epoch; byte bounded | purged / purged / lost | forbidden / forbidden |
| Reference expansion response | on-demand authenticated response | response only; not added to trace cache by read; bounded/chunked | no stored debug copy | forbidden / forbidden |
| Frontend debug raw state | DebugScreen memory state | current route/session only | purged / purged / lost | forbidden / forbidden |
| HTTP/WebView cache | Raw debug API response path | no retention allowed | `Cache-Control: no-store` | forbidden / forbidden |

Observation-side failures (control bookkeeping aside from a requested disable, capture, redaction, correlation or buffer mutation) are diagnostic-only: they may leave a safe `diagnostic_unavailable`/omission indication when possible, but never replace, retry or fail an otherwise successful provider operation and never mask an original provider failure.

Context propagation failures must be visible rather than silent: model work crossing thread, executor or background-worker boundaries must enter through a helper that sets/restores `TraceCaptureContext`; if no source can be recovered, the trace is retained with `source=unknown` and covered by tests.

## Configuration And Data Impact

| Item | Decision |
|------|----------|
| `debug.trace.enabled` | `bool`, default `false`, 仅由 authenticated debug control facade 以 `persist="runtime"` 设置；每次 sidecar 启动重新为 `false`，不加入普通 Settings UI |
| `debug.trace.max_records` | `int`, initial default `200`, 正整数校验后控制进程内 deque |
| `debug.trace.max_record_bytes` | `int`, initial default `1048576` (1 MiB)，单条 retained detail 上限；超限返回显式 omission |
| `debug.trace.max_total_bytes` | `int`, initial default `16777216` (16 MiB)，trace 与 ephemeral flow detail 合计上限；先淘汰最旧记录 |
| `debug.reference.max_response_bytes` | `int`, initial default `1048576` (1 MiB)，单次 reference expansion 响应上限；超限走 truncation/chunking/too-large diagnostic |
| Runtime token | 由 sidecar 生命周期向 debug redactor 提供进程内值，不落配置/日志/DTO |
| Controlled secrets | 普通诊断 redactor 接收实际构造模型客户端时注册的 secret/token，不因脱敏另行触发 migration getter；Grand Tour main/vision/background/settings validation/skill-composition/compression/embedding/redactor paths 统一注入 keyring-only provider 或显式跳过对应场景，禁止 plaintext fallback、迁移或 mutation |
| SQLite | 仅读取已有 workflow/session/message 与隔离 Grand Tour 数据；无 trace migration |
| DuckDB | 真实录制场景按既有 service/filtering 边界写临时数据；无 debug 直读新增 |

Debug hidden defaults must be provided through unified configuration defaults/schema/accessors, with invalid-value fallback tests. They must not be hard-coded only inside `DebugInspectorService`.

## Credential And Provider Inventory

Before tasks are generated, implementation work must include a guardrail inventory built from static search for credential/model/provider callsites. Initial required entries:

| Path / pattern | Classification | Required handling |
|----------------|----------------|-------------------|
| `src/desktop_api/orchestrator_runtime.py` `get_ai_api_key()` | main LLM | real-tour read-only provider |
| `src/business/agents/tool_helpers.py` `get_ai_vision_api_key()` / `.invoke(` | vision LLM | observation boundary + real-tour read-only provider |
| `src/business/brain/background_worker.py` `get_ai_api_key()` | background LLM | context propagation + real-tour read-only provider |
| `src/business/services/skill_composition/service.py` `LangChainLLMClient` | composition/trial LLM | provider injection or real-tour scenario skip |
| `src/business/memory/compression_handler.py` compression LLM | compression LLM | provider injection or seed avoids compression |
| `src/business/memory/assistant_memory.py` `OpenAIEmbeddings` / `embed_query` | embedding/vectorization | no trace record; redaction/provider inventory coverage |
| `src/business/services/settings_actions_service.py` connection validation | settings action | read-only credential snapshot |
| Any future `.invoke(`, `embed_query(`, `LangChainLLMClient(`, `OpenAIEmbeddings(`, `get_ai_*api_key` | unknown until registered | tests fail until classified |

## Validation Strategy

| Area | Planned validation |
|------|--------------------|
| Composer | Vitest/RTL：插入位置、固定阈值边界（6/7 行、1200/1201 code units、混合换行）、展开/收起/清空/发送、键盘/ARIA、Assistant 与 Teaching 一致性 |
| Trace invocation/service | pytest：text/tool/vision observation coverage、direct-provider-invoke guard、embedding out-of-trace allowlist、media metadata/no bytes、record/aggregate byte eviction、epoch disable-reenable/mid-flight completion、failure record、capture/redaction/buffer failure isolation、thread/executor context propagation、clear |
| Debug API/UI | pytest + Vitest：401/404 fail-closed、warning-gated runtime arm/status/stop、sidecar restart defaults off、typed filtering/detail/reference with response limit、raw endpoints `Cache-Control: no-store`、memory-only frontend raw state、clear/disable/route-leave purge、armed banner；隐藏 route `/debug` 不出现在 NavRail；触发后 30 秒内可定位并展开一条已完成 foreground/background trace |
| Agent Flow | pytest integration：既有 PM/Programmer/Trial persisted payload 投影、Assistant ephemeral task/result 捕获、detail provenance、link/unlinked、disable purge、无新 durable diagnostic；最小 transition matrix 覆盖 `PM -> Programmer`、`Programmer -> Review -> Programmer` retry、review acceptance/publication path、`Trial -> PM` failure triage and reroute/publication、Assistant-to-ephemeral-subagent、Assistant-to-fixed-specialist 及 executor return，且 linked trace 往返导航不超过两次交互 |
| Boundaries | guardrail + log/cache/storage capture：diagnostic-only raw trace/handoff/media/correlation 与 credential sentinel 未进入 `ui_events.py` 普通合同、ordinary logs、HTTP/WebView cache、URL 或 frontend persisted store；既有 `assistant.message.content` 保持合法；异常日志同样无 sentinel/raw；router 不直接 import Repository |
| Provider inventory | guardrail：所有 `.invoke(`、`embed_query(`、`LangChainLLMClient(`、`OpenAIEmbeddings(`、`get_ai_*api_key` callsites 必须登记为 observation boundary、real-tour provider covered、ordinary-runtime-only 或 explicitly-out-of-scope |
| Real-tour runner | controlled Playwright/unit tests：no opt-in skip、main/vision/background/settings validation/skill-composition/compression/embedding/redactor provider 注入或场景跳过、跨 sidecar keyring audit guard 拒绝 mutation、timeout/cancel/stop failure、预算耗尽、artifact sanitization、summary report/cleanup，无真实凭据/费用/现场录制 |
| Manual Grand Tour | opt-in headed Playwright：付费/隐私确认、脚本化安全 live journey、真实模型可用性、事件驱动推进、isolated writes、skills/compositions 明确场景边界、关联 commit/journey 的非敏感 report、recording stop/cleanup、keyring fingerprint 与 audited mutation count 不变 |

## Complexity Tracking

所有 Constitution Check 门卫均通过。Runtime-only trace arm 只为明确武装的当前 sidecar 会话开启敏感捕获，并通过 banner/stop、epoch purge 与 failure-isolation 防止静默扩散或业务回归。Real Grand Tour 的真实付费调用与现场录制是规格中已声明的人工验收例外，已由脚本化安全旅程、注入式只读凭据 provider、mutation audit、非敏感报告、预算和 cleanup 门卫收敛；它不扩展默认 E2E 或普通生产行为。
