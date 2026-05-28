# Quickstart: Desktop UX, Debug Inspector, and Grand Tour Acceptance

## Planning Outputs

本 feature 以以下文档为实现依据：

```text
specs/011-desktop-ux-debug-regression/
├── spec.md
├── plan.md
├── research.md
├── data-model.md
├── critiques/
│   ├── critique-20260524-093539.md
│   ├── critique-20260524-102350.md
│   └── critique-20260524-110445.md
└── contracts/
    ├── composer-ui.md
    ├── debug-api.md
    └── grand-tour.md
```

## Suggested Implementation Order

1. 实现 `contracts/composer-ui.md`：共享长粘贴 hook/预览组件及两处 composer 单测。该 MVP 只依赖长粘贴 fixture setup，可先于 debug/real-tour scaffolding 独立验收。
2. 实现进程内 debug service、authenticated trace control facade、runtime-only unified-config arm、epoch/record/byte retention、application-controlled secret inventory 和 ordinary-log guard；把 text/tool/vision 调用统一纳入 fail-isolated model observation boundary。
3. 实现 debug REST DTO/client 与隐藏 `/debug` DebugScreen；禁用状态只显示 warning/control，armed 状态在 AppShell 显示 stop banner；raw endpoints 设置 `Cache-Control: no-store`，前端 raw state 仅保存在内存并在 clear/disable/离开 route 时清理；再接入已有 transitions 的 Agent Flow，对 Assistant delegated task/result 仅捕获 trace-enabled ephemeral detail，并在 UI 标记 provenance。
4. 拆出 real Grand Tour 专用 Playwright runtime、注入 main/vision/background/settings validation/skill-composition/compression/embedding/redactor 的 side-effect-free credential provider，或在场景前显式跳过未覆盖路径、event watcher、预算/隔离/非敏感 summary report、artifact sanitization 和不产生费用的失败注入覆盖；最后同步活文档与模块 AI 镜像。

各步骤有独立 gate：composer 覆盖通过即可单独验收；debug/flow 需先通过敏感数据与生命周期门卫；manual real tour 不并入默认 E2E。

## Automated Validation

从仓库根目录运行后端相关覆盖：

```powershell
uv run python -m pytest tests/data/test_unified_config_debug.py tests/data/test_read_only_credential_resolver.py tests/data/test_real_tour_audit.py tests/business/debug tests/desktop_api/test_debug_api.py tests/desktop_api/test_real_tour_credentials.py tests/desktop_api/test_app_contract.py::test_desktop_api_registers_core_routes tests/integration/test_debug_flow_trace.py tests/guardrails/test_debug_boundaries.py tests/guardrails/test_debug_provider_inventory.py tests/guardrails/test_real_grand_tour_artifacts.py tests/guardrails/test_real_tour_credential_mutation.py tests/test_agent_loop_retry.py tests/test_hook_protocol.py -q
uv run python -m py_compile src/data/credential_resolver.py src/desktop_api/app.py src/desktop_api/routers/debug.py src/business/debug/service.py
```

从 `frontend/` 运行交互与受控 E2E 覆盖：

```powershell
cd frontend
npm run lint
npm run test -- --run tests/unit/long-paste-hook.test.ts tests/unit/assistant-long-paste.test.tsx tests/unit/teaching-long-paste.test.tsx tests/unit/debug-screen.test.tsx tests/unit/app-shell-debug.test.tsx tests/unit/real-grand-tour-runtime.test.ts tests/unit/real-grand-tour-event-watcher.test.ts tests/unit/real-grand-tour-failures.test.ts
npm run test:e2e -- tests/e2e/long-paste-composer.spec.ts tests/e2e/debug-inspector.spec.ts tests/e2e/grand-tour-default.spec.ts
npm run build
```

验证重点：

- qualifying paste 的发送文本与原草稿逐字一致，手工输入不自动折叠。
- `debug.trace.enabled=false` 时既不采集 trace，也不能读取 raw debug detail；control API 只返回安全状态和 warning。Arm 必须要求 warning acknowledgement；armed 时 AppShell 显示 stop banner；`capture -> disable -> re-enable` 后旧 epoch 仍为空，mid-flight completion 不回填；sidecar restart 默认 unarmed。
- text/tool/vision 模型路径均被 observation 覆盖；vision detail 只有媒体元数据、没有 base64/data URL；embedding/vectorization 不要求 trace record，但 credential/callsite 必须在 provider/redaction allowlist 中；超限记录明确标识 omission 且不突破字节预算。
- capture/redaction/correlation/buffer 故障注入不改变正常 provider success 或 provider failure 语义；只产生安全 diagnostic-unavailable/omission。
- response/body/UI/ordinary captured logs、HTTP/WebView cache、URL、localStorage/sessionStorage、persisted store 中均找不到主模型、vision、embedding credential sentinel、runtime token、diagnostic-only raw model 文本或 raw delegation detail；既有 `assistant.message.content` 继续作为用户可见产品输出存在。
- Agent Flow 中无 trace 的现有 transition 仍显示为 `unlinked`；持久事实与临时 Assistant task/result detail 具有不同 provenance。
- `/api/events` 的普通 payload 不新增 diagnostic-only raw prompt、raw handoff、raw media 或 debug-only correlation。
- reference expansion 超大内容返回明确 truncation/chunking/too-large diagnostic，不无界返回。
- real-tour runner 的 timeout/cancel/cleanup/budget/credential mutation guard、完整 credential/model construction inventory、artifact sanitization、main/vision/background/settings validation/skill-composition/compression/embedding/redactor provider 注入或场景跳过，以及 report sanitization 在无真实模型与无 live capture 的测试中可验证。
- guardrail 静态扫描覆盖 `.invoke(`、`embed_query(`、`LangChainLLMClient(`、`OpenAIEmbeddings(`、`get_ai_*api_key` 等 callsites；新增 callsite 未登记时测试失败。

## Baseline Fixtures

实现与验收使用固定输入，避免不同开发者用不同样例证明不同结论：

- Source todo baseline: 最终验收需回看 `docs/local/todo/todo-chat-input-collapse-long-paste.md`、`docs/local/todo/todo-debug-trace-page.md` 和 `docs/local/todo/todo-grand-tour-e2e-rewrite.md`，确认 refined spec 覆盖了原始待办意图；若本地缺少这些 ignored todo 文件，记录为 source-note unavailable 而不是用其他样例替代。
- Long paste fixture: 一份 7 行文本和一份 1201 字符单行文本，分别覆盖换行阈值和字符阈值；中间选区 paste 样例固定为 `before + paste + after`。
- Trace fixture: 一次 Assistant 普通回复、一次 Assistant delegation、一次 Teaching `PM -> Programmer` handoff 和一条 vision/multimodal 样本；embedding/vectorization 只验证 credential/redaction inventory，不要求 trace record。
- Legacy Grand Tour baseline: 记录旧 `grand-tour.spec.ts` 固定等待推进和 API Key 保存交互的风险样例，用于确认 real-tour runner 不再依赖固定 pause 或 secret mutation。

## Manual Debug Inspector Check

实现完成后，启动桌面应用并直接访问隐藏 debug route `/debug`：

1. 确认普通导航中不存在 Debug 菜单；未 armed 时页面只显示警示/control 状态，不显示 raw trace。
2. 阅读敏感内容警示并 arm 当前 sidecar trace；确认 AppShell 出现 trace-active stop banner。
3. 触发一轮 Assistant 消息、一次 Teaching/assistant delegation 工作流和一条可用的 vision 诊断路径。
4. 查看 trace 输入/输出、Agent Flow 顺序及可用 trace link；确认 persisted transition 与 ephemeral detail 标识清晰，vision 只显示媒体元数据。
5. 请求一条存在的 reference 并确认缺失 reference 给出明确诊断；用超大 reference 验证 truncation/chunking/too-large diagnostic。
6. 通过 stop banner 关闭再重新开启 trace；确认之前 raw trace/ephemeral detail 无法再次读取，随后清空本轮新数据；重启后确认 trace 默认 unarmed。
7. 检查页面、API 响应、HTTP headers、frontend storage 和 ordinary logs 不显示已知 credential、sidecar token、diagnostic-only raw request/response 或委派文本；raw debug responses 必须是 no-store。

## Manual Real Grand Tour

Real Grand Tour 仅在开发者明确接受费用与现场录制风险后执行。独立命令会默认启用真实链路和 live capture，不再要求在 shell 里注入 opt-in 环境变量：

```powershell
cd frontend
npm run test:e2e:grand-tour -- --headed
```

运行前确认：

- 日常设置中已有可通过 side-effect-free provider 读取的真实模型 credential；该 provider 覆盖 main、vision、background、settings validation、skill-composition、compression、embedding credential lookup 和 redactor，或相关 scenario 在启动前显式跳过；测试不会触发迁移、保存、替换、删除或 plaintext fallback。
- 已准备一个仅含固定示例数据、无敏感内容的目标窗口或测试网页，并将严格按照 `contracts/grand-tour.md` 的 scripted safe live journey 操作。
- Skills/compositions 场景默认只做隔离数据 visibility/create/read，不触发 LLM；若改为 generation/trial，必须计入 paid-call budget 并通过 provider inventory。
- 接受真实 provider 调用可能产生费用，并接受单轮最多 20 分钟 / 30 次付费调用的自动中止预算。

运行后检查本地 summary report 应包含 `commitSha`、`liveJourneyId`、每个场景的 outcome、最后安全可见状态、paid-call/time budget usage 以及 recording/resource cleanup 状态；credential presence/fingerprint 必须与运行前一致且 mutation count 为零。报告、Playwright output 和 attachments 不得包含 prompt/response、截图、录制正文、runtime token、credential、raw media 或完整敏感路径；real-tour trace/video/screenshot 默认关闭或严格限于已消毒的安全目标；连续三次发布证据必须使用同一 commit 和 journey id。PR/release 中只引用 run id、commit SHA、journey id、scenario pass/fail counts、budget usage、cleanup status 和 credential mutation count，不复制 raw report 内容、完整本地路径、截图、prompt 或录制正文；代码或 journey 脚本变化后，三次计数重新开始。

三次发布前证据引用格式：

```text
Real Grand Tour evidence: commit=<sha>, liveJourneyId=safe-local-form-v1,
runs=<runId1>,<runId2>,<runId3>, scenarios=<passed>/<failed>/<skipped>,
budget=<paidCallCount>/<elapsedMs>, cleanup=<status>, credentialMutationCount=0
```

## Documentation Gate

实现交付时需要同步：

- `docs/ARCHITECTURE.md`
- `docs/PROJECT_CONSTRAINTS.md`
- `frontend/AGENTS.md` / `frontend/CLAUDE.md` / `frontend/GEMINI.md`
- `src/AGENTS.md` / `src/CLAUDE.md` / `src/GEMINI.md`

这些更新需说明 debug raw data 的 runtime-only arm、epoch/byte/reference-response/鉴权/logging/cache/frontend-storage 边界、trace-active stop banner、隐藏 `/debug` 路由、failure-isolated observation、ephemeral delegation detail、embedding out-of-trace 但进 provider/redaction inventory、注入式只读 credential provider inventory、非敏感 real-tour report/artifact policy，以及真实 Grand Tour 对默认受控 E2E 的有限例外。
