# Contract: Manual Real Grand Tour Acceptance

## Purpose

Real Grand Tour 是发布前人工发起的真实链路验收，不替换默认 mock/controlled E2E。它允许真实 LLM 费用和真实桌面/浏览器录制，但发布证据只来自预先准备的非敏感目标与固定操作脚本，并仅在明确确认风险的本地开发执行中运行。

## Invocation Gate

实现后应提供独立命令，例如：

```powershell
cd frontend
npm run test:e2e:grand-tour -- --headed
```

Contract requirements:

- 真实套件只通过独立 `test:e2e:grand-tour` 命令运行；该入口内置启用 real-tour runtime 和 live capture，不依赖 shell opt-in 环境变量。
- 默认 `npm run test:e2e` 仍必须保持 mock-backed、cost-free、无 live capture；任何将真实套件并入默认 E2E 的改动均为回归。
- 在首个付费调用前输出/展示费用提示。
- 在开始当前桌面或浏览器捕获前输出/展示隐私提示并要求本次确认。
- 每次运行初始预算为最多 `20` 分钟和 `30` 次付费模型请求；达到任一上限即终止后续付费步骤、执行 cleanup 并报告 `budget_exceeded`。

## Scripted Safe Live Journey

真实 Teaching 场景仍采集真实屏幕或浏览器画面，但维护者必须在录制前准备一个不含真实用户、凭据或私密业务信息的目标，并严格执行同一条现场脚本：

1. 打开为验收准备的本地测试窗口或测试网页，其中只有固定的非敏感示例数据。
2. 开始录制后执行合同指定的固定动作序列，例如聚焦一个字段、输入固定示例文本、触发一次明确的提交/确认动作并回到应用。
3. 停止录制，等待公开 `recording.progress` 和 Teaching 阶段事件推进；模型输出只校验非空、阶段/角色与可观察完成状态。
4. 三次发布前验收运行必须使用同一脚本和等价无敏感目标；任意浏览日常桌面内容不能计作 SC-006 的通过证据。

实现时应将具体字段、示例文本和终态选择写入 page object/helper 中，并在人工运行说明中呈现，不要求模型返回固定措辞。
当前固定脚本由 `frontend/tests/e2e/pages/real-grand-tour-safe-journey.ts` 和 `docs/local/real-grand-tour-safe-journey.md` 定义：

- `liveJourneyId`: `safe-local-form-v1`
- Target fixture identity: `mexemplar-real-tour-local-fixture-form-v1`
- Fixed input text: `Sample approval request for local validation only`
- Action order: focus request field → enter fixed text → submit form → observe terminal state
- Terminal assertion: `Submitted`

在任何运行被计入发布证据前，page object/helper 和人工说明必须固定以上 `liveJourneyId`、目标 fixture identity、固定输入文本、动作顺序和终态断言；操作者偏离该脚本的运行不得计入 SC-006 的三次连续通过证据。

## Runtime Isolation

| Resource | Rule |
|----------|------|
| Sidecar port | 每次运行随机空闲 localhost 端口 |
| Session token | 每次运行随机 token；不写日志中的明文正文、不持久化 |
| Business data | 每个运行或场景使用临时 `EXEMPLAR_DATA_DIR`；结束清理 |
| Non-secret config | 从开发者统一配置按允许列表读取 provider/model/base_url/timeout 等，写入临时配置；不得复制未知键或 plaintext secret |
| Keyring | 只经注入式 side-effect-free resolver 读取当前开发者既有模型 credential；该 provider 必须覆盖 real-tour 场景可触达的 main、vision、background、settings connection validation、skill/composition LLM、compression LLM、embedding credential lookup 和 diagnostic redactor，不得触发 plaintext config fallback、config-to-keyring migration、`set_password` 或 `delete_password`，并禁止 Settings API secret POST/DELETE |
| Keyring audit | 测试进程必须安装可跨 sidecar 观测的 audit guard / adapter / service-name proxy，记录任何 set/delete/migration attempt；运行结束 mutation count 必须为 `0` |
| Recording output | 只写临时目录，并在 success/failure/timeout/cancel 后停止 recorder 和清理资源 |
| Budgets | 记录 elapsed time 与 paid-call count；初始上限为 20 分钟 / 30 次，超限进入失败与 cleanup |
| Run report | 每轮写入非敏感 summary report，关联 `commitSha`、`runId` 与 `liveJourneyId`；报告不包含 prompt、截图、录制正文或 credential |

## Credential And Model Construction Inventory

Real-tour runner 必须在启动前建立并验证 credential/model construction inventory。该 inventory 至少覆盖以下类别；任何未覆盖但会在 real-tour 场景中触达的 callsite 都必须使套件以 `unmet_prerequisite` 失败，而不是回退到 ordinary getter。Inventory 记录必须包含 callsite、category、trace handling、real-tour provider handling、redaction handling、owner、out-of-scope/skip rationale 和 verification status。

| Category | Current examples to audit | Required real-tour behavior |
|----------|---------------------------|-----------------------------|
| Main assistant LLM | `src/desktop_api/orchestrator_runtime.py`, AgentLoop factories | 使用注入式 read-only provider |
| Vision/multimodal LLM | `src/business/agents/tool_helpers.py` | 使用同一 read-only provider；不得读取 plaintext vision key fallback |
| Background brain LLM | `src/business/brain/background_worker.py` | 使用同一 read-only provider 或显式跳过相关 scenario |
| Skill/composition LLM | `src/business/services/skill_composition/service.py` and any trial/helper callsites discovered by inventory scan | 若 scenario 触发 LLM，则使用同一 read-only provider；否则 scenario 限定为不触发 LLM 的隔离数据 visibility |
| Compression LLM | `src/business/memory/compression_handler.py` | 若触发压缩，则使用同一 read-only provider；否则测试 seed 需避免触发压缩 |
| Embedding credential lookup | `src/business/memory/assistant_memory.py` | Embedding 不要求 trace record，但 credential lookup 必须通过 read-only/no-migration path 或在 real-tour 中禁用该路径 |
| Settings connection validation | `src/business/services/settings_actions_service.py` | 连接验证只能读取只读 credential snapshot，不得调用 migration-capable getter |
| Diagnostic redactor | `src/business/debug/` planned redactor | 只接收已注册 secret snapshot，不得为了脱敏调用 ordinary getter |

Inventory guard 应由静态扫描和运行时 prereq 双重实现：新增或既有 `get_ai_*api_key`, `get_embedding_*`, `LangChainLLMClient`, `OpenAIEmbeddings`, `.invoke(`, `embed_query(` 等 callsite 必须登记为 real-tour-covered、ordinary-runtime-only 或 explicitly-out-of-scope。

## Minimum Scenario Set

`grand-tour.real.spec.ts` 必须把以下场景作为独立 report unit 运行或显式 skip；每个 unit 都有自己的 `scenarioId`, `status`, `lastObservableState`, `paidCallCount`, `elapsedMs`, `cleanupStatus` 和失败原因。一个场景失败不得覆盖或伪造另一个场景的结果。

| Scenario ID | Scope | Independent pass/fail boundary |
|-------------|-------|--------------------------------|
| `readiness` | 启动真实 sidecar、鉴权、健康检查和应用壳加载 | sidecar ready、runtime token 有效、普通导航可用；失败只报告 readiness |
| `assistant-real-reply` | Assistant 发起一次真实模型响应 | 观察到 public progress 和非空 assistant 结果；不校验固定措辞 |
| `teaching-live-recording` | 手动确认隐私提示后执行固定安全现场录制 | 只在独立 real-tour 命令内录制，观察 recording start/stop/cleanup；失败报告最后 recording 状态 |
| `teaching-workflow-progress` | Teaching 真实流程进入后续阶段 | 依据 public Teaching stage/progress 推进，断言阶段/角色/非空结果或明确失败状态 |
| `skills-compositions-visibility` | Skills/compositions 可见性或隔离数据 create/read | 默认不触发 LLM generation/trial；若触发，必须计入 paid-call budget 并通过 provider inventory |
| `settings-non-secret-interaction` | 非密钥设置交互和连接验证边界 | 只写隔离非密钥配置，credential fingerprint/presence 和 mutation count 不变 |
| `cross-screen-stability` | 主屏间导航稳定性 | 页面切换不丢关键 public state，不读取 raw DB/debug material |

每个 scenario report unit 必须独立写入 `scenarioId`、`status`、`lastObservableState`、`paidCallCount`、`elapsedMs`、`cleanupStatus`，可选 `reason` 只能使用安全枚举/短摘要，不能包含 raw prompt、raw response、credential、runtime token、截图、录制正文或完整本地路径。

## Event Watcher

测试侧通过与前端相同认证 header 连接现有 `/api/events` 公共合同，处理 sequence/replay/resync。等待依据必须是安全公开状态而非 debug raw material。

| Scenario | Wait for | Minimum assertion |
|----------|----------|-------------------|
| Readiness | `/api/health` ready | 应用壳与普通导航可用 |
| Assistant real reply | `assistant.progress.payload.status` plus displayed assistant message | 观察到 `running` 后进入 terminal/waiting/error outcome，且有真实非空 assistant 结果，不匹配固定措辞 |
| Teaching recording | `recording.progress.payload.status` | 明示同意后观察到 `recording`，结束必须观察到 `stopped` 或 `completed`；`failed`/`degraded` 记录为诊断结果 |
| Teaching workflow | `teaching.stage_changed.payload.stage` and `teaching.progress.payload.status` | 阶段由 `intent_confirmation` 进入 `learning` / `trial_validation` / `published`，或明确 `failed` / `abandoned`；失败保留最后状态 |
| Trial/publication where reached | `trial.progress.payload.status/published` and `teaching.stage_changed.payload.stage` | `succeeded` 与 `published` 状态一致，或以失败状态报告 |
| Skills/compositions | product API/UI state change | 默认只执行隔离业务数据的 visibility/create/read，不触发 LLM generation/trial；若实现选择触发 LLM，则必须计入 paid-call budget 并覆盖 skill/composition credential provider |
| Settings | `settings.changed` for non-secret key only | 仅临时配置受影响，credential fingerprint/presence 不变 |
| Cross-screen stability | public UI state | 页面切换不丢关键状态、不依赖 raw DB read |

## Artifact Policy

Real-tour Playwright 配置必须默认避免保存可能包含当前桌面、prompt、credential 或 raw model output 的 artifacts：

- `trace`, `video` and `screenshot` default to `off` for real-tour runs.
- Failure artifacts may include only sanitized summary JSON and safe public event/status logs.
- 若需要截图用于人工定位，只允许针对预先准备的无敏感目标窗口/页面，并必须经 sentinel sanitization 检查；该截图不得作为默认发布证据提交。
- Playwright output、ordinary logs、summary report 和任何 attachment 都必须经过 sentinel 检查，确认不含 raw prompt/response、credential、runtime token、raw media bytes/data URL 或完整敏感本地路径。

## Scenario Independence

- 每个场景记录自己的 `scenarioId`, `status`, `lastObservableState`, `cleanupStatus`。
- 场景不得依赖前一个场景产生的日常数据；需要共享 fixture 时只来自该运行的临时 seed。
- 某场景失败不应伪装成后续场景的业务失败；报告分别列出结果。
- LLM 输出只断言角色、阶段、非空和业务可观测完成，不断言特定措辞。
- 每个场景记录 `paidCallCount` 与 `elapsedMs`；预算耗尽是独立、明确的失败原因，不得当作业务通过。

## Summary Report

每次手动 real-tour 运行必须在本地 Playwright output 下生成 summary JSON，例如：

```json
{
  "runId": "real_gt_20260524_001",
  "commitSha": "abc1234",
  "liveJourneyId": "safe-local-form-v1",
  "startedAt": "2026-05-24T10:30:00Z",
  "finishedAt": "2026-05-24T10:42:00Z",
  "budgetUsage": { "elapsedMs": 720000, "paidCallCount": 12 },
  "credentialMutationCount": 0,
  "scenarios": [
    {
      "scenarioId": "assistant-real-reply",
      "status": "passed",
      "lastObservableState": "assistant.progress:succeeded",
      "cleanupStatus": "not_applicable"
    }
  ]
}
```

报告规则：

- 可记录状态、计数、scenario id、event type/status、cleanup outcome 和不可逆 fingerprint comparison result。
- 不得包含 raw prompt/response、trace detail、handoff text、截图、录制内容、runtime token、credential、临时数据库正文或完整本地敏感路径。
- 三次发布前验收通过证据必须使用同一 `commitSha` 与 `liveJourneyId`；若代码或旅程脚本变化，计数重新开始。
- PR/release 证据只能引用安全字段：run id、commit SHA、journey id、scenario pass/fail counts、budget usage、cleanup status 和 credential mutation count；不得粘贴 raw prompt、截图、录制正文、完整敏感路径或未消毒附件内容。
- 报告默认不提交仓库；PR/发布说明只引用安全摘要结果。

## Credential Invariant

运行前后必须验证：

```text
keyring credential presence/fingerprint before == after
no request was made to /api/settings/secrets/*
no keyring set_password/delete_password/migration side effect occurred during the run
credential provider covered main/vision/background/settings validation/skill-composition/compression/embedding/redactor paths or explicitly skipped those scenarios before model construction
no plaintext credential appears in report, trace, screenshots or temporary config
```

Fingerprint 用不可逆摘要或存在性对比完成，不在测试输出中打印原始 credential。启动前必须验证隔离配置中无待迁移 plaintext secret；若只读 resolver 不可用，或任何 real-tour-reachable factory/action 需要回退到有写副作用的普通 getter，则真实套件以 unmet prerequisite 失败。

## Recording Cleanup Invariant

Teaching real-capture 场景在以下每种结束方式都必须执行 stop/cleanup 并在报告记录结论：

- success
- model/workflow failure
- timeout
- user cancellation/test interruption
- paid-call/time budget exhaustion

测试失败报告必须包含最后公开可见的 recording/workflow 状态和 cleanup outcome，但不得带录制 raw content 或 secret。

## Controlled Failure Verification

不产生模型费用、不捕获当前桌面内容的自动化 runner 覆盖必须注入并验证：

| Injection | Required assertion |
|-----------|--------------------|
| Default E2E separation | 默认 `npm run test:e2e` 不启动 real sidecar/model/recorder，真实链路只在独立命令中运行 |
| Model failure or event timeout | 报告最后安全公开状态并执行 cleanup |
| Cancellation/test interruption | 录制 stop/cleanup 在 finally 路径执行 |
| Stop failure | 场景失败且 cleanup outcome 明确标红，不伪装成功 |
| Credential mutation attempt | Resolver/guard 拒绝动作并令场景失败；mutation count 仍为零 |
| Missing provider injection for any real-tour-reachable model/credential/redactor path | 套件以 unmet prerequisite 失败，不回退到 ordinary getter |
| Time/paid-call budget exhaustion | 后续付费步骤停止，录制停止并报告 `budget_exceeded` |
| Report/artifact sanitization sentinel | summary report、Playwright output、attachments 和 ordinary logs 中不出现 sentinel prompt/credential/token/raw media 字面值 |

## Default Regression Separation

- `npm run test:e2e` 继续运行 controlled/mock suites，不要求真实 credential，不发生付费模型调用，不捕获当前桌面/浏览器。
- Real Grand Tour 使用独立 spec/config/tag/command；任何将其无意并入默认测试的改动均为回归。
