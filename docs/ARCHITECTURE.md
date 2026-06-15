# Exemplar 架构设计 v2

本文档为架构讨论的最终结论，所有设计决策以本文档为准。讨论过程记录见 v1。

---

## 零、桌面运行时

当前维护的桌面 UI 是 **Tauri 2 + React + TypeScript**，Python 代码以 FastAPI sidecar 的形式提供本地业务 API。

```text
React UI (frontend/)
  → typed API client / event stream
  → Tauri shell (src-tauri/)
  → localhost FastAPI sidecar (src/desktop_api/)
  → business services / AgentOrchestrator
  → execution / recording / data repositories
```

- Tauri 负责窗口、custom chrome、sidecar 生命周期、端口/token handoff 和打包。
- React 负责普通主界面：AI Assistant、Skill Teaching、Skill List、Skill Composition、Skill Methodology、Settings、Brain Management、Specialist Management；`/debug` 是隐藏的 Debug Inspector 直达路由，不进入普通导航。
- `src/desktop_api/` 是 UI adapter，router 不直接访问 Repository；默认只调用 business services，并把 `src/utils/events.py` 的 blinker 事件投影成受注册表约束的前端 UI event stream。`orchestrator_runtime.py` 里为复用既有 `AgentSessionStore` 组装的 Repository 触点是当前收敛例外，不得扩散到 router 或新 API。
- UI event stream 由后端 `UI Event Registry` 拥有公开契约；前端只消费注册 UI event type，不使用内部 blinker 事件名或 `sourceEvent` 推断展示行为。事件 envelope 包含 `eventId`、当前桌面事件会话内单调递增的 `sequence`、`sessionId`、`causationId`、`type`、`scope`、安全校验后的 `payload` 和 `createdAt`。
- sidecar event stream 为每个订阅者维护独立队列，并保留当前进程内的有界 replay buffer。前端重连时携带同一事件会话的 last-seen sequence；buffer 能覆盖缺口时按序回放，不能覆盖或事件会话不匹配时发送 `backend.resync_required`，由前端刷新权威快照恢复状态。
- sidecar 只绑定本机回环地址，并要求每次启动生成的 session token；token 不写入配置、OpenAPI 或日志。
- Debug Inspector 只通过 authenticated `/api/debug` 暴露，trace arm 是运行时状态，不持久化。Trace buffer 以进程内 epoch 隔离，受 record/bytes 限制；disable、clear、restart 都会销毁 raw detail。Raw debug endpoints 使用 `Cache-Control: no-store`，前端 raw trace/flow/reference state 只保存在组件内存，离开 `/debug` 或 clear/stop 时清理。模型 text/tool/vision 调用统一走 fail-isolated observation boundary；vision 只保留媒体元数据，embedding 不进入 LLM trace record，但必须在 provider/redaction inventory 中登记。
- Agent Flow 以持久 `workflow_transitions` 为权威，Debug Inspector 只在 armed epoch 中叠加临时 trace link 和 Assistant delegation task/result debug detail；UI 必须标出 linked/unlinked 与 provenance，不能把临时 detail 写回业务事实。
- Manual Real Grand Tour 是独立 Playwright 套件，默认 E2E 仍为 mock/controlled/cost-free。真实套件只通过 `npm run test:e2e:grand-tour` 运行，并内置启用 real-tour runtime 和 live capture；运行时使用随机 localhost port/token、临时数据目录、`UnifiedConfigManager` 只读凭据 getter、paid-call/time budget、public event watcher 和 sanitized summary report；trace/video/screenshot 默认关闭，现场录制只能按固定安全旅程执行。
- `src/main.py`、`mexemplar_gui.py`、`start.bat` 和 `mexemplar_gui.bat` 是显式失败的 legacy 兼容入口；`src/ui/` 的 PyQt 主 UI 代码已退休。

---

## 一、整体流程

系统有两个独立入口：**教技能**（录制流程）和**用技能**（办公助理）。

### 教技能：录制 → 分析 → 生成 → 试用 → 发布

```
用户触发录制 → 录制完成

→ PM Agent Loop（独立运行）
    → 分析录制数据 → 跟用户确认需求（多轮对话）
    → 需求确认完毕 → 展示摘要 → 用户确认
    → 输出结构化 JSON（目标 + 参数列表）
    → PM Loop 结束

→ 程序员 Agent Loop（独立运行）
    → 接收需求 JSON → 分析录制数据 → 写代码
    → LLM Review（最多打回3次）
    → 工具入库（pending 状态）
    → 程序员 Loop 结束

→ 试用 Agent Loop（可能隔很久才触发）
    → 引导用户提供参数（根据工具的参数定义）
    → 从对话中提取参数 → 执行工具 → 展示结果
    → 成功 ×3 → 工具发布
    → 失败 → PM Agent Loop（新的独立运行）
        → 分诊：代码问题 or 需求问题
        → 代码问题 → 恢复程序员 Agent Loop（带上反馈）
        → 需求问题 → 恢复 PM Agent Loop → 重新确认 → 再派程序员
```

### 录制层：三模式并存

录制模式一：Playwright 驱动（原有）
- App 启动 Chromium + 扩展
- 扩展经 WebSocket 向 App 发送 `browser_action`
- App 写入 `data/queues/*.jsonl`

录制模式二：扩展触发（新增）
- 用户自己的 Chrome + 扩展弹窗
- 扩展经 WebSocket 向 App 发送 `recording_control`
- App 启动 `ProxyRecorder` + `AccessibilityRecorder`
- mitmproxy 网络事件和 Windows UIA 交互事件共同写入同一 JSONL 队列

新增录制驱动模块：`ProxyRecorder`、`AccessibilityRecorder`、`SystemProxyManager`、`CertManager`

录制模式三：桌面录制
- React 教学页选择“桌面操作”后，经 `src/desktop_api/routers/teaching.py` 和 `DesktopRecordingService` 进入业务层；窗口最小化完成后才启动 `DesktopRecorder`，避免“开始教学”的点击进入录制数据。
- `DesktopRecorder` 聚合 pynput hook、UIA 查询、剪贴板 watcher、帧 ring buffer、PNG/clip sink 和全局热键注册；动作写入 DuckDB 的 `desktop_recordings` / `desktop_actions`，每条 action 带 `monitor_index`。
- 停止后前端进入 sanity review 状态；通过 `DesktopRecordingService.get_health_stats()` 读取 `desktop_recordings.health_stats`，三种决策为继续分析、放弃录制、重新录制。
- 桌面录制跨模块通知走 `src/utils/events.py` 的 blinker 事件，再由 sidecar event stream 推给前端；动作计数在 React 录制状态中展示。
- 进程启动时在桌面 recorder/hook 启动前应用 Per-Monitor V2 DPI awareness；非 Windows 或 API 不可用时降级记录日志，不阻塞启动。

### 用技能：办公助理日常入口

```
用户在 React AssistantScreen 中发消息
  → 办公助理理解任务
  → 判断需要哪个工具、缺什么参数
  → 参数不够 → 问用户
  → 参数齐了 → 调用工具（run_tool_code）
  → 执行成功 → 展示结果
  → 执行失败 → 自主判断原因
      → 参数问题 → 重新问用户
      → 临时错误 → 告知用户稍后重试
      → 代码 bug → 自动触发修复流程（PM 分诊）
```

工具不只从录制产生，共有三条路径：**录制浏览器操作**（路径 1）、**用户主动要求助理"做成工具"**（路径 2）、**助理检测到重复模式主动建议**（路径 3）。三条路径共享后半段管线（PM → 程序员 → 试用 → 发布）。

用户还可以将多个已发布技能组合成**技能组合**——一个更大的可调用能力。技能组合支持两种模式：**范围型**（LLM 在选定技能范围内自主选择调用）和**顺序型**（按固定顺序执行，LLM 负责衔接参数）。技能组合作为虚拟 Tool 暴露给办公助理，与原子技能统一调度。详见第九节。

### 关键设计决策

1. **各阶段不是连续的** — 代码生成后工具进入列表，用户随时试用，中间可能隔很久
2. **所有 Agent 的会话都能保存和恢复** — 试用反馈可能在生成之后很久才发生
3. **PM 是对外角色** — 用户跟 PM 对话确认需求，试用失败时由 PM 分诊
4. **试用通过对话进行** — 试用 Agent 引导用户、提取参数、执行工具、展示结果
5. **试用成功 3 次后发布** — 工具修改后成功次数清零
6. **需求确认分类分批提问** — 不一次全问也不一个一个问
7. **停止条件双向** — Agent 觉得够了或用户说够了，任一方都可以结束需求确认
8. **办公助理是独立入口** — 不属于录制工作流，长期存在，随时可对话

---

## 二、四个 Agent 分工

### 角色定义

| Agent | 职责 | 阶段 | 触发方式 |
|-------|------|------|---------|
| **产品经理 Agent** | 需求分析、跟用户确认、试用失败时分诊 | 需求确认、分诊 | 录制完成自动触发 |
| **程序员 Agent** | 分析录制数据、决定技术方案、写代码 | 代码开发 | PM 确认需求后自动触发 |
| **试用 Agent** | 引导用户、提取参数、执行工具、展示结果 | 工具试用 | 用户主动试用 |
| **办公助理 Agent** | 调用已发布工具和技能组合执行日常任务、闲聊、触发修复/工具沉淀 | 日常使用 | 用户主动发起对话 |

四个 Agent 用**同一套 Loop 代码**，只是配置不同（prompt、工具集）。

### Agent 分类对比

| | PM / 程序员 | 试用 | 办公助理 |
|---|---|---|---|
| 定位 | 教技能（内部流程） | 教技能（验证阶段） | 用技能（面向用户的日常入口） |
| 生命周期 | 任务完成即结束 | 任务完成即结束 | 长期存在，随时可对话 |
| 工具集 | 录制数据工具 + 信号工具（固定） | execute_tool + submit_trial_result + run_command（固定） | 已发布的用户工具（动态）+ 技能组合（虚拟 Tool）+ 内置通用工具 |
| 会话绑定 | 绑定 workflow_id | 绑定 workflow_id | 不绑定 workflow_id，独立存在 |

试用 Agent 的 `create_trial_tools()` 固定返回三个工具：`execute_tool`、`submit_trial_result`、`run_command`。其中 `run_command` 用于在工具执行环境中运行命令，支持试用阶段的自修复。

### 为什么拆分

- 一个 Agent 又要像产品经理思考又要像程序员写代码，prompt 很难调，两种思维模式互相干扰
- 各自职责清晰，prompt 聚焦
- 试用阶段的职责（引导、参数提取、执行）跟需求分析和代码开发都不相关
- 办公助理面向日常使用，工具集动态变化，与教技能流程解耦

办公助理的详细设计（工具集、会话管理、首次引导、执行失败处理、工具沉淀路径）见 [assistant_agent_design.md](design/assistant_agent_design.md)。

### PM → 程序员的交接

交接数据为结构化 JSON：

```json
{
  "goal": "百度搜索关键词，获取前100条结果的详情页内容",
  "recording_id": "xxx",
  "parameters": [
    {
      "name": "keyword",
      "description": "搜索关键词",
      "recorded_value": "Python 教程",
      "type": "variable"
    }
  ]
}
```

参数化职责分配：
- **主要参数由 PM 确定** — PM 跟用户聊，用户知道哪些值每次都变
- **技术参数由程序员补充** — 如翻页数量、超时时间等
- 允许程序员在开发过程中追加

---

## 三、PM Agent 工具集

PM 的人设是**懂需求分析的产品经理**，不是程序员。核心能力：**看、猜、问、再看**。

| # | 工具 | 用途 | 说明 |
|---|------|------|------|
| 1 | describe_data | 数据发现（渐进式：无参返回表概览，传表名返回字段详情） | 任务开始先调一次了解数据概况 |
| 2 | query_data | agent 写 SQL 直接查询 DuckDB | 主力数据获取，~90% 的查询 |
| 3 | execute_code | 临时 Python 代码执行 | SQL 不够用时的补充（~10%） |
| 4 | analyze_image | 多模态模型分析截图 | **非常规手段**，兜底用。图片不进 agent 主上下文，只返回文字分析结果 |
| 5 | read_field_chunk | 分段读取大字段原始内容 | 当 query_data 返回 `__large_field__` 占位对象时，按 locator+offset+length 分段续读 |
| 6 | 跟用户对话 | 把分析结果转化为用户能懂的问题去确认 | Agent 提问，不替用户做决定 |

- **PM 和程序员共用同一套 5 个录制数据工具**，角色差异由 prompt 引导（PM 关注操作流程和用户意图，程序员关注技术线索）。试用 Agent 和办公助理不使用录制数据工具
- 5 个通用录制数据工具为 `describe_data`、`query_data`、`execute_code`、`read_recording`、`read_field_chunk`。它们在创建时根据 `recording_id` 查询 `recording_mode` 并切换表集合；跨 mode 访问返回 `table_not_in_mode`，而不是泄露另一种录制模式的表。
- 浏览器录制路径保留 `analyze_image`；桌面录制路径不注入 `analyze_image`，改由 `create_desktop_specific_tools()` 注入 `list_desktop_actions`、`read_action_clip`，并在 `recording.desktop.vision_model` 已配置时注入 `analyze_desktop_action`。
- PM / 程序员 prompt 通过 `build_pm_prompt(mode)` / `build_programmer_prompt(mode)` 双轨构建：浏览器 mode 返回 legacy prompt，桌面 mode 增加按 `window_title` 聚焦、跳过冗余动作、关键节点多模态分析和 `async def execute() -> dict` 等契约提示。
- `query_data` 与 `execute_code` 查询 `network_requests` 时默认只暴露 `filtered=false` 的可见行，并隐藏 `filtered / filter_reason / filtered_at / is_recommendation / importance_level` 以及 `filter_decisions` 表；这一约束由 `src/recording/filtering/` 中的 SQL 改写器和 DuckDB 代理统一实现，`recording_data_tools.py` 只负责装配
- `describe_data` 中的 `network_requests.row_count` 也只统计 Agent 可见行，避免通过概览计数反推出被隐藏的噪声请求数量
- 列表操作通过元素上下文启发式识别，不确定就直接问用户
- 详见 [recording_tools_redesign_todo.md](design/recording_tools_redesign_todo.md)

---

## 四、程序员 Agent 工具集

程序员拿到需求 + 参数列表后，自己去录制数据里挖技术细节，决定技术方案，编写代码。

| # | 工具 | 用途 |
|---|------|------|
| 1~5 | 录制数据工具 | 与 PM 共用同一套 5 个工具（describe_data、query_data、read_field_chunk、execute_code、analyze_image） |
| 5 | 语法校验 | 验证语法错误和导入问题（不是真正执行） |

### 关键设计

- **录制数据工具 PM 和程序员共用** — agent 写 SQL 自主决定查什么，不限定 query_type
- **需求常驻上下文** — 需求和参数列表始终在上下文里，不做成工具，防止 Agent 钻进技术细节后跑偏
- **工具集详细设计待定** — 依赖数据存储层稳定后再细化

### 代码 Review

程序员写完代码后，加一层 LLM Review：

- **不是独立 Agent**，就是一次 LLM 调用
- 只关注硬伤（逻辑错误、参数漏用、明显 bug），不管代码风格
- **最多打回 3 次**，超过直接入库（pending），后面还有用户试用兜底

---

## 五、Agent Loop 设计

### 核心 Loop

废掉 LangGraph，自己实现简单的 while 循环（参考 nanobot）：

```
while not done and iteration < max_iterations:
    response = llm.chat(messages, tools)
    if response.has_tool_calls:
        执行工具 → 结果加回 messages → 继续
    else:
        输出结果 → 结束
```

复杂度在 Agent 的能力上（工具、prompt、记忆），不在 Loop 本身。

### 工具注册方式：Function Calling

PM/程序员/试用 Agent 采用全量 FC 注入——工具少（3-4 个），token 开销可忽略。

办公助理 Agent 采用 **FC + 懒加载**——内置工具全量 FC 注入，用户动态工具和技能组合按需注入。技能组合作为虚拟 ToolDefinition 注册，固定 schema（`task` + `context`），内部按模式分发到成员技能。详见 [assistant_agent_design.md](design/assistant_agent_design.md) 4.1-4.4 节和第九节。

用户能力目录采用**渐进式延迟加载**。主助理、临时子代理和固定专员先按各自会话/专员白名单过滤已发布技能与可用组合；授权目录同时满足 `agent_tools.discovery.full_catalog_max_items`（默认 20）和 `full_catalog_max_chars`（默认 6000）时，system prompt 注入完整摘要，否则只注入技能/组合数量与发现说明，不写入隐藏能力名称。Agent 通过增强后的 `search_tools(query?, kind?, offset?, limit?)` 浏览或搜索授权目录，结果返回稳定分页、总数、`nextOffset` 和可直接传给 `get_tool_detail` 的无歧义 selector；`get_tool_detail` 继续负责激活 FC schema。搜索和详情每次调用都重校验发布状态、组合可用性、成员授权和白名单，Prompt 快照不能成为越权依据。

### 工具执行 Hook

`AgentLoop` 对调用方传入或动态构建的 `ToolDefinition` 支持同步 pre/post hook。执行顺序为：

```text
tool pre_hook
→ AgentConfig.global_pre_hooks
→ handler
→ tool post_hook
→ AgentConfig.global_post_hooks
```

pre_hook 只做放行、拒绝和观测，不能改写 handler 入参；`ToolCallContext.args` 是递归只读隔离视图。post_hook 只接收 handler 的原始字符串结果或普通 handler 异常转换出的标准化错误字符串；多个 post_hook 不形成结果流水线，最后一个返回非空 `PostHookResult.result` 的 hook 决定最终展示文本。

多工具批处理语义先于 hook 生效：同轮混合中断型工具时直接写入 `invalid_model_output`，不执行 hook 或 handler。普通批次按原调用顺序分区，连续且显式声明 `ToolDefinition.is_concurrency_safe=True` 的无副作用工具使用最多 4 个 worker 并发执行 handler、hook 和 output governance；未知工具及未声明安全的工具各自形成串行屏障。治理后的结果仍由 AgentLoop 调用线程按模型原顺序写入 messages 并发出活动事件，保证 assistant tool_calls 与 tool results 的配对和序列稳定。

并发分区内单个读取失败只保存该调用的错误，不取消同分区其他调用，也不阻断后续串行分区。串行路径继续按 `ToolDefinition.has_side_effects` 级联：副作用工具（write_file、exec）失败时后续调用写 `not_executed`；未标记并发安全的无副作用工具仍串行执行且失败后可继续。合法单中断工具可以执行 pre_hook，但返回 `ToolSignal` 后跳过 post_hook 并保持原有暂停或完成语义。当前并发白名单只包含确认线程安全的 web/file/search/raw-output 读取工具、`search_tools` 和 `load_reference`；会修改激活缓存的 `get_tool_detail`、增加加载计数的 `load_skill_methodology`、用户工具、组合工具、process 系列及所有写入/执行/委派工具保持串行。

`load_reference` 和 `talk_to_user` 是 AgentLoop 内建注入工具，继续用于上下文引用和用户交互，但不进入 tool/global hook 管线。

### 内置通用工具运行结构

办公助理的通用内置工具仍由 `src/business/agents/tools/builtin_general_tools.py` 作为公开 facade 注册，但文件、搜索、Web 搜索、命令、后台进程和大输出治理分别下沉到 focused 模块：

| 模块 | 职责 |
|------|------|
| `builtin_contracts.py` | 统一 result envelope、稳定 outcome/error code、运行期 tool context |
| `builtin_permissions.py` | workspace 解析、外部/隐藏/系统/symlink 分类、确认决策和脱敏摘要 |
| `file_tools.py` | 有界读取、raw-byte baseline、baseline-safe 写入/编辑、结构化 patch |
| `search_tools.py` | 结构化文件/内容搜索、默认 ignore、分页和脱敏 |
| `web_search_providers.py` | `web_search` provider registry、`web.search_backend` 路由、Brave / DuckDuckGo HTML / ddgs 后端 |
| `command_tools.py` | 同步 `exec` 和 process lifecycle handler |
| `output_governance.py` | 可见结果压缩、raw output reference、`load_tool_output` 和健康计数 |
| `src/execution/command_runner.py` | 同步子进程执行边界、cwd/timeout/stdout/stderr 归一化 |
| `src/execution/process_manager.py` | 当前 sidecar 会话内后台进程 registry、日志窗口、等待/停止/关闭 |
| `src/data/repos/tool_output_repository.py` | 私有 blob + SQLite metadata 的 raw output reference Repository |

AgentLoop 在执行已升级内置工具时注入 `ToolRuntimeContext`（session、tool_call、tool_name、workspace root），handler 返回统一 JSON envelope。保存任何文本 tool result 前统一经过 output governance：小型 legacy/custom 结果保持原格式；大结果、截断结果或已有 raw reference 的结果先复用/创建 `ToolOutputRepository` 私有 artifact，再生成有界 compact envelope。compact payload 的 `facts` 与 `preview` 来自确定性提取，独立低成本模型只追加 advisory `semanticSummary`，不能覆盖 exit code、错误码、状态等可验证事实。

语义摘要配置位于 `agent_tools.output.semantic_summary.*`，运行时使用独立的 `agent_tools.output.semantic_summary.api_key`，不得回退主模型密钥。该密钥由 `UnifiedConfigManager` 管理：`config.json` 提供本地默认值，`app_settings` 可覆盖，Settings 保存/删除操作写入统一配置。输入按工具类型优先提取 stdout/stderr、文件内容、搜索结果、网页正文或 reference 内容；超过输入预算时按 head/error context/uniform/tail 选择，再以最多 6 个 map、并发 3 和一次 reduce 在默认 12 秒总预算内同步生成。摘要调用失败、超时或 JSON 畸形时只移除 `semanticSummary`，原有 facts、preview 和 raw reference 保留，仍只持久化一条 tool result。Debug trace source 为 `tool_output_summary`；Real Grand Tour 使用相同的只读配置 getter，并继续受付费调用预算约束。

能力目录参数位于 `agent_tools.discovery.*`：完整目录条目/字符双阈值、搜索默认/最大页大小和单项描述上限。它们由 `UnifiedConfigManager` 在每次 Prompt 构建或搜索调用时读取，运行时覆盖无需重启即可影响后续调用；属于工程调优参数，不在 Settings UI 暴露。

文件修改采用先读后写模型：`read_file` 返回基于原始字节的 baseline；已存在文件的 `write_file`、`edit_file` 和 `apply_patch` update/delete 必须带当前 baseline，过期或缺失在落盘前拒绝。`list_dir` 和搜索返回有界、相对路径的结构化结果，搜索默认使用原生遍历而非 shell 解析。命令解析为 argv 后以 `shell=False` 启动，只允许 workspace 内 cwd 和路径参数；shell 控制语法、shell host 与内联解释器代码在执行前拒绝。后台进程受会话级数量、日志和等待上限约束，只在当前 sidecar 进程会话内可管理，重启后旧 `proc_*` id 返回 unavailable。

### 内置工具依赖预装

`web_search` 通过 `web.search_backend` 选择 provider：`auto` 会按 `brave-free → ddg-html → ddgs` 尝试；显式配置 `brave-free`、`ddg-html` 或 `ddgs` 时只使用指定 provider。Brave API Key 经 Settings secret API 写入统一配置；`ddg-html` 使用标准库请求 DuckDuckGo HTML 页面；`ddgs` 保留 `duckduckgo-search` 作为最后降级，并继续通过 `tool_executor.run_tool_code()` 在 `data/tool_venv/` 子进程执行。

仍需要第三方包的内置工具不在主进程直接 import，而是通过 `tool_executor.run_tool_code()` 在工具 venv 子进程执行。`tool_executor` 暴露 `BUILTIN_TOOL_DEPS` 列表和 `ensure_builtin_deps()` 函数，FastAPI lifespan 启动时调用预装。后续新增内置工具依赖只需往该列表追加包名。

### 用户交互

靠消息历史串联，不在 Loop 内部暂停。每一轮用户交互就是一次独立的 Loop 调用，用户回复后作为新消息进来，Agent 看到历史上下文自然接上。

### Agent 调度

不加额外的协调层。各 Agent 在各自阶段独立运行。以后加新 Agent 角色，通过通用的 Agent 注册/派发机制扩展。

办公助理不需要 `_dispatch_next`（没有下游 Agent），Loop 完成后不调度。助理触发的修复流程（`report_tool_bug`）和工具沉淀（`codify_as_tool`）通过异步任务队列投递，由后台 worker 消费后调用现有 PM 分诊流程。入队后通过 `threading.Event` 立即唤醒 worker；这条链路是对 blinker 的受控例外，因为 blinker `send()` 是同步的，不适合在助理 worker 线程中嵌套启动 PM。

### Agent 之间的衔接：两层通信机制

流程编排对外仍由 `AgentOrchestrator` 统一负责；公开 import 入口为 `src.business.orchestration.agent`，内部由多个子模块协作。通信分两层：

| 通信方向 | 机制 | 说明 |
|---------|------|------|
| Loop → Orchestrator | return AgentResult | 函数调用返回值，同步 |
| Orchestrator → 外部 | blinker 事件 | 跨模块解耦通知，UI/日志/持久化各自监听 |

**事件不用于 Agent 间调度**。Orchestrator 收到 AgentResult 后通过 `_dispatch_next` 显式调用下一个 Agent，blinker 事件只发给 UI / 日志 / WorkflowTransition，不通过事件监听器触发下一步。

**临时子代理可唤回**：办公助理派出的临时子代理（`resumable_on_failure=True`）撞迭代上限或遇可恢复的 LLM 失败（账户配额/限流/网络）时，AgentLoop 返回 `ResultType.PAUSED` 并将会话置 `suspended`，Orchestrator 据此回传带 `subagent_id` 的可唤回句柄并记一条内部 `assistant_delegation_paused` workflow transition（非公开 UI 事件）。主助理可用 `inspect_subagent`（只读概览、零模型调用）与 `continue_subagent`（凭 `subagent_id` 从持久化会话历史恢复续跑，经归属校验）调度，工作历史零丢失且不引入主助理直接执行路径。不可恢复的 LLM 失败仍返回 `ERROR`。

**完整事件列表**（定义在 `src/utils/events.py`）。其中 workflow/agent 事件由 AgentOrchestrator 发出；录制生命周期事件（`recording_started`、`recording_stopped`、`recording_completed`）由 Recorder 层发出：

| 类别 | 事件名 | 触发时机 |
|------|--------|---------|
| 录制 | `recording_started` / `recording_stopped` | 录制开始/停止 |
| 录制 | `recording_completed` | 录制数据准备就绪 |
| 交互 | `agent_needs_user_input` | Agent 需要用户回复 |
| 交互 | `agent_error` | Agent 执行失败 |
| 协作 | `requirement_confirmed` | PM 完成需求确认 |
| 协作 | `code_completed` | 程序员提交代码 |
| 协作 | `review_passed` / `review_failed` | LLM Review 结果 |
| 协作 | `tool_saved` | 工具入库（pending 状态） |
| 协作 | `trial_success` | 单次试用成功（含当前累计次数） |
| 协作 | `trial_failed` | 试用失败，触发 PM 分诊 |
| 协作 | `triage_completed` | PM 分诊判定为代码问题 |
| 协作 | `tool_published` | 工具发布（试用成功满 3 次） |
| 失败追踪 | `teaching_failure_updated` | 教学失败记录新增或更新 |
| 失败追踪 | `teaching_failure_resolved` | 失败记录已解决 |
| 失败追踪 | `teaching_failure_retrying` | 开始重试失败流程 |
| 桌面录制 | `desktop_action_count_changed` | 桌面 action 数变化，UI 浮窗刷新 |
| 桌面录制 | `desktop_recorder_start_failed` | hook 注册等启动失败 |
| 桌面录制 | `desktop_recording_degraded` | UIA、剪贴板、热键等子系统降级 |
| 桌面生成 | `desktop_syntax_gate_retry_failed` | 桌面 Programmer 代码连续语法失败 |
| 桌面试用 | `desktop_trial_preview_ready` / `desktop_trial_finished` | 桌面 Trial 预览和执行结果 |

各协作事件的数据格式详见 [event_system_design.md](design/event_system_design.md) 第三节。

PM/程序员/试用 Agent 通过 `workflow_id` 路由到对应教学/试用状态，办公助理通过 `session_id` 路由到对应前端会话状态。

### 聊天展示路径

```
AssistantScreen → desktop API → ChatService.get_display_messages() → MessageRepository.get_display_page()
```

前端通过 `/api/assistant/sessions/{session_id}/messages` 加载历史消息；API 调用 `ChatService.get_display_messages(session_id, limit=10, before_sequence=None)`，由 `MessageRepository.get_display_page()` 在 SQLite `messages` 表上执行 keyset 分页。展示过滤规则：保留 `role` 为 `user`、`assistant`、`summary` 的消息；`message_type=compressed` 且 `role=summary` 的消息保留展示；其余 compressed 消息过滤掉；排除空内容、已归档和仅工具调用的消息。`summary` 角色在前端以可折叠 `<details>` 元素渲染（"之前的对话内容"）。返回 `ChatHistoryPage`（包含 `DisplayChatMessage` DTO 列表和 `has_more_before` 分页标志）。UI 向上滚动时传入 `before_sequence` 加载更早展示消息。

### Assistant 失败消息恢复

Assistant 终止性失败通过 SQLite v14 的 `assistant_run_failures` 持久化，并由 `AssistantRunFailureRepository` 和 `AssistantFailureService` 管理。记录关联会话和触发失败的用户消息序号，状态机为 `failed → retrying → resolved|failed`；sidecar 启动时把上次进程中断遗留的 `retrying` 恢复为 `failed`。每个会话只允许一个当前未解决失败，并发重试通过条件更新保证最多一个请求进入 `retrying`。

`AssistantRuntime` 在终止失败时先保存失败记录，再补发本回合持久化消息及带安全 `failure` 投影的用户消息，最后发布 `assistant.progress(status=failed)`。普通聊天 DTO 和 `assistant.message` 只包含 `category / message / suggestion / attemptCount / failedAt`；内部状态码和异常类型只保存在数据层，原始响应体、endpoint、密钥、异常正文和 stack trace 不进入普通日志、DTO 或 UI event。普通终止失败不再发布 `assistant.error`，避免和内联恢复卡产生重复 Toast。

`POST /api/assistant/sessions/{session_id}/retry` 接受 `{ messageSequence, content? }`。缺省 `content` 时从后端读取原消息并复用原回合；提供 `content` 时创建新的用户回合，不修改原消息。成功后源失败转 `resolved` 并通过权威 `assistant.message` 更新移除旧卡；再次失败时，原样重试更新原失败，编辑后重试把新失败关联到新用户消息。用户直接发送新的普通消息也会先解决旧失败。手动重试不限次数，不改变既有 provider 自动重试策略，也不切换备用模型。

前端恢复卡紧贴对应用户气泡，提供“重试”“编辑后重试”和“查看调试信息”。提交期间所有操作禁用；API 自身失败才走现有错误 Toast，运行终止失败只更新卡片。Debug 操作进入 `/debug?sessionId=...`，按会话过滤并选择最新失败 trace；trace 未提前启用时明确说明历史原始详情不能补录。事件流缺口仍通过 `backend.resync_required` 重新加载消息权威快照，前端不根据本地 progress 推测失败归属。

### Markdown 渲染边界

assistant 消息在前端通过 `SafeMarkdown` 渲染。渲染前剥离 raw HTML/script 和不安全链接目标；用户消息按纯文本显示。后端 DTO 用 `rendering` 字段标识 `safe_markdown` 或 `plain_text`，但不向 UI 暴露 archive/compression 内部术语。

### 免确认 Toggle 可见性

前端 assistant store 控制输入栏免确认 Toggle 的显隐：欢迎页/新对话空态时隐藏，当前会话启动过 assistant 运行后显示。高危确认仍由 `builtin_general_tools` 的 `request_id + threading.Event` 等待模型管理，sidecar 用 emit-compatible shim 发布 `assistant.confirmation` 事件，前端通过非模态确认浮层回写决策。用户可通过两个入口开启会话级免确认：(1) MessageComposer 输入栏的"全部允许" Toggle；(2) ConfirmationToast 中的"全部允许"按钮。开启后通过 `POST /api/assistant/confirmations/auto-approve` 同步后端状态并放行所有挂起确认。状态仅存于进程会话内存，新建会话时自动复位。

### 结构化多选澄清（ask_user_question，019）

主助理专属的 `ask_user_question` 是**需独占调用的非中断阻塞工具**：模型在关键决策无法可靠推断时，单次抛出 1–4 道结构化问题（每题 2–4 选项、单/多选、始终可填"其他"）。生命周期由 `src/business/agents/tools/clarification_manager.py` 用 `request_id + threading.Event + lock + first-decision-wins` 管理，结构对标高危确认但**完全独立**（独立 pending 表、独立信号、独立终态集，不复用确认链路）。默认 5 分钟超时，全程**内存态**——无 SQLite/DuckDB 表、无迁移、无配置项，sidecar 重启即失效。`ToolDefinition.requires_exclusive_call` 让 AgentLoop 对"独占工具与其他工具混批"零执行 + 全批 `invalid_model_output`；solo 调用阻塞等用户决策后在同一回合续跑。desktop adapter（`src/desktop_api/clarifications.py`）发布两个公开 UI 事件 `assistant.clarification_requested` / `assistant.clarification_resolved`（后者不含答案），前端 `ClarificationCard` 在输入框上方以非模态卡片整组提交，与高危确认浮层互不复用生命周期。停止当前回合结算为 `stopped`、应用关闭结算为 `shutdown`，普通 SSE 断线不取消、重连经 `GET …/clarifications/pending` 或事件回放恢复。超时/取消/停止/关闭一律 fail-closed，模型绝不获得猜测答案。

**职责分离：**
- **Agent Loop** — 纯执行引擎，只负责跑循环和返回 AgentResult，不感知事件系统
- **AgentOrchestrator** — 根据 loop.run() 的返回值发出业务事件、通过 `_dispatch_next` 显式调度下一个 Agent

改流程只改 Orchestrator，改 Agent 不影响流程。

### Trial Agent Config：动态构建

PM/程序员/助理三个 Agent 有预定义的固定 Config（`PM_CONFIG`、`PROGRAMMER_CONFIG`、`ASSISTANT_CONFIG`）。试用 Agent 例外：其 system prompt 需要注入当前工具的参数定义，因此 Config 在每次启动试用时由 `_build_trial_config(workflow_id)` 动态构建，不缓存复用。

### 教学失败追踪

每次 agent_error 事件自动触发 Orchestrator 记录教学失败（TeachingFailureRepository）。UI 展示失败列表，用户可手动重试。重试采用三级策略：

1. **复用旧 session** — 旧 session 存在，直接恢复（user_input=None，复用消息历史）
2. **从 transition 记录恢复** — 旧 session 不存在，但上阶段留有 transition payload，新建 session 用上阶段结果当输入
3. **降级到上一阶段** — 都没有时，从上游阶段（pm / programmer）重新触发

失败记录状态：active → retrying → resolved / dismissed。

---

## 六、记忆机制

### 短期记忆：引用机制

会话内 tool result 的运行时引用替换当前已停用。工具返回的大块原始数据直接保留在上下文中，避免旧机制把 search/fetch 结果替换成纯指针后诱发 `load_reference` 反复恢复同一数据。

```
旧机制示例（已停用）：
  Agent: 我来查一下这个页面的网络请求
  Tool result: {完整的 200KB 响应数据...}
  Agent: 发现这个 API 返回了 JSON，data 字段包含列表数据
```

- `memory.reference_size_threshold` 的默认值保留为 10000 字符，用于后续重新设计时的兼容配置。
- `load_reference` 仍保留给跨会话摘要等显式 REF 下钻场景，但会话内 tool result 不再由 `ReferenceHandler` 自动生成 `REF::` 指针。
- 大输出治理优先走已升级内置工具的可见摘要 + `load_tool_output` 授权读取机制。

### 会话级记忆：消息类型系统

对话历史存库，每条消息带**类型标签**。类型可扩展，初步识别：

- **普通消息（normal）** — Agent 回复、用户输入、系统提示、工具调用结果
- **压缩消息（compressed）** — 对第 X-Y 条消息的摘要，原始消息可归档

压缩流程由 `CompressionHandler` 驱动，分为以下步骤：

1. `_split_messages` 将消息划分为 system / 压缩区 / 保留区
2. `_adjust_boundary_for_tool_pairs` 检测跨越压缩/保留边界的 tool 组（assistant(tool_calls) + 对应 tool result），将跨界 tool 组整体移入保留区，避免配对断裂
3. 调用压缩 LLM 对压缩区生成结构化摘要
4. 若边界调整后压缩区为空，跳过 LLM 调用和持久化，直接返回 `system + keep_msgs`

`assemble_context` 在压缩后、格式转换前执行 `_cleanup_orphan_tool_results`，检测并剔除孤立 tool result（tool_call_id 不在任意 assistant(tool_calls) 中出现的 tool 消息），作为边界调整的兜底校验。

会话内引用替换当前不体现为消息类型，也不作为运行时自动行为（见记忆机制设计）。

### 跨会话记忆（办公助理专用）

办公助理需要跨会话记忆来理解用户的使用模式和历史任务。采用**层级摘要 + ID 引用**机制（全局摘要 → 分组摘要 → 会话摘要 → 原始消息），通过 `load_reference` 逐层下钻。详见 [assistant_agent_design.md](design/assistant_agent_design.md) 第七节。

### 全局记忆（PM/程序员/试用）

暂不实现，等项目跑通有真实用户数据后再加。

### 记忆使用范围

| Agent | 短期记忆 | 会话级长期记忆 | 跨会话记忆 |
|-------|---------|--------------|------------|
| 产品经理 | ✅ | ✅ 需求历史、修改记录 | 📋 暂不实现 |
| 程序员 | ✅ | ✅ 历次修改和试用反馈 | ❌ 不需要 |
| 试用 | ✅ | ✅ 试用历史 | ❌ 不需要 |
| 办公助理 | ✅ | ✅ 当前会话上下文 | ✅ 层级摘要 + 语义搜索 |

---

## 七、录制数据与采集通道

### 采集通道：Playwright + Extension + CDP 混合设计

- Playwright + Chrome 扩展（content_script + background service worker）+ CDP
- 覆盖所有 Chromium 系浏览器（Chrome、Edge、Brave、Arc、Opera）
- CDP 用于在页面加载前注入 `MEXEMPLAR_CONFIG` 配置（`browser_recorder.py` `_inject_config_via_cdp`）
- Extension 负责事件采集并通过 WebSocket 上报

### 扩展能力边界

**能拿到的：**
- DOM 事件/元素/属性、DOM 树快照、兄弟元素上下文、页面截图
- 网络请求（URL/method/type/请求头/请求体/响应头/状态码）
- 响应体 — 通过 monkey-patch fetch/XMLHttpRequest 实现

**拿不到的：**
- WebSocket 消息帧 — 可通过 monkey-patch WebSocket 构造函数解决，按需添加
- 非 fetch/XHR 的响应体 — 一般不需要

### 数据缺口

| 缺口 | 解决方案 |
|------|---------|
| 下拉选项未采集 | 用户交互触发下拉展开时，专门采集所有选项的 text + value |
| DOM 树深度不够（maxDepth=5） | 加大 maxDepth，数据量增大可接受 |

---

## 八、顶层设计原则

> **上下文精准控制是整个 Agent 架构最关键的设计原则。**

在有限的上下文窗口里，放对的信息。放多了 LLM 被噪声干扰，放少了信息不足。

体现在：
- 查录制数据按需查字段，不 `SELECT *`
- 短期记忆的上下文治理 — 大块工具结果先保留原文，后续由压缩和内置工具输出治理兜底
- PM 分类分批提问
- 程序员不需要全局记忆
- PM 给程序员的交接信息只给需要的，不给分析过程
- 办公助理的懒加载机制 — 只在 LLM 决定使用某个用户工具时才注入 FC schema，不一次性灌入所有工具定义
- 办公助理的跨会话记忆层级 — 全局摘要 ≤500 token 常驻 system prompt，需要细节时按 REF ID 逐层下钻

---

## 九、技能组合

技能组合是由多个已发布技能组成的、更大的可调用能力。对用户来说像普通技能一样可以命名、描述、保存、被 Assistant 调用。

### 双模执行

| 模式 | 执行语义 | 适用场景 |
|------|---------|---------|
| **范围型（range）** | LLM 在选定技能范围内自主选择调用哪些、是否调用 | 围绕同一任务域的能力包，每次执行未必用全 |
| **顺序型（ordered）** | 按固定顺序执行，LLM 负责衔接每步结果到下一步参数 | 查数据→生成内容→执行动作等有明显先后依赖 |

默认创建为范围型，创建时可直接切换为顺序型。顺序型支持 LLM 生成推荐顺序，用户可手动调整。

### 数据模型

两张表独立于原子技能：

- **skill_compositions** — 组合元数据（名称、描述、适用场景、模式、状态、assistant_enabled、recommend_order、needs_review）
- **skill_composition_members** — 成员关系（多对多），含 selected_order（用户选择顺序）和 execution_order（顺序型执行顺序）

成员关系走独立关系表而非 JSON 字段，便于反向查询和约束维护。V1 同一技能在同一组合中只能出现一次。

状态流转：draft → published → offline（可重新发布）。

### Assistant 集成

技能组合作为虚拟 ToolDefinition 暴露给办公助理：

- 固定 function calling schema：`task`（必填，任务描述）+ `context`（选填，补充上下文）
- 内部 function name 使用 `comp_<short_id>` 前缀，与原子技能规避冲突
- Assistant 调用时把"任务描述"传给组合，由内部执行器分发到成员技能
- 搜索/激活与原子技能统一走 DynamicToolManager 的懒加载机制

### 试用机制

采用对话式试用，基于 AgentLoop 独立运行：

- 试用 system prompt 区分范围型和顺序型的引导策略
- **执行快照**：试用启动时冻结组合定义和成员技能信息，中途组合变更不影响已运行的试用会话
- 成员技能在组合启动后才暴露给 Agent（先只暴露组合工具，启动后再暴露成员）
- 默认真执行，不额外触发发布和状态迁移

### needs_review 标记

成员技能状态回退（如试用失败导致 pending）时，Orchestrator 自动标记引用该技能的组合为 `needs_review`。标记后：

- 该组合对 Assistant 隐藏（不参与搜索和激活）
- 用户打开组合并保存一次后自动清除
- API/UI 会把该标记映射为 `displayStatus = needs_review`，而持久化 `status` 仍只保留 `draft / published / offline` 生命周期。

### 关键设计决策

1. **技能组合独立于原子技能** — 不复用 Tool 模型，有独立的表、仓库、服务
2. **不嵌套** — V1 不支持组合嵌套组合
3. **发布后可直接编辑** — 不做草稿覆盖发布版
4. **无副作用试用** — 组合层不提供额外的副作用屏蔽，成员技能本身决定是否支持 sandbox
5. **会话边界** — 只允许调用用户选中的技能/技能组合，内置工具低优先级兜底

---

## 十、Brain Service 架构

办公助理的跨对话记忆和专员调度由 `src/business/brain/` 独立业务层提供。该层在已有的 Agent Loop 和编排层之上，为 assistant 注入持久化上下文、Segment 沉淀、zone 衰减、archive 检索、专员管理和自校准能力。

### 业务层模块

| 模块 | 职责 |
|------|------|
| `src/business/brain/models.py` | 共享常量、dataclass（Segment 状态、zone 类型、memory entry 类型等） |
| `src/business/brain/segment_service.py` | Segment 生命周期管理：创建、封存（`window_close` / `idle` / `new_session` / `token_limit`）、崩溃恢复 |
| `src/business/brain/distillation_service.py` | Phase-aware Segment 沉淀：将消息历史蒸馏为结构化 memory entry 并写入对应 zone |
| `src/business/brain/context_builder.py` | 会话启动上下文组装：persistent-zone 按配置上限注入 + hot/subconscious top-N 选择 + zone summary |
| `src/business/brain/decay_router.py` | Hot-zone 衰减路由：`event` vs `insight` 差异化衰减 |
| `src/business/brain/archive_service.py` | Archive unit 和 time-layer 聚合任务 |
| `src/business/brain/retrieval_service.py` | 显式 archive 检索、invalidation fallback、相关性排序 |
| `src/business/brain/specialist_service.py` | 专员 CRUD、技能白名单子集校验、自动招募扫描 |
| `src/business/brain/prediction_service.py` | Prediction 生成与验证服务逻辑 |
| `src/business/brain/management_service.py` | Brain 管理界面 facade：zone、entry、Segment 重试和演化链 |
| `src/business/brain/skill_service.py` | 方法论资产创建、接力、用户编辑、软删除、列表和审计 |
| `src/business/brain/skill_equipment_service.py` | assistant/specialist 方法论装备关系、默认装备传播和 token budget 估算 |
| `src/business/brain/skill_bootstrap_service.py` | 内置"如何创建方法论" seed 读取、fallback bootstrap 和系统链根保护 |
| `src/business/brain/skill_reference_counter.py` | assistant/specialist 回复元数据中的方法论引用计数 |
| `src/business/brain/background_worker.py` | 后台 Worker：pending Segment 处理、蒸馏崩溃重置、衰减清扫、archive 分层、prediction 周期、事件唤醒 |

### 数据层

| Repository | 职责 |
|------------|------|
| `src/data/repos/brain_repository.py`（`BrainRepository`） | Memory Entry 和 Segment CRUD、compare-and-swap 状态转换、事务原子写入、invalidation/soft-delete、feedback signal 持久化 |
| `src/data/repos/specialist_repository.py`（`SpecialistRepository`） | 专员持久化、软删除停用、版本历史 |
| `src/data/repos/skill_repository.py`（`SkillRepository`） | 方法论资产、来源 Segment、supersede 链、软删除和引用/加载计数 |
| `src/data/repos/skill_equipment_repository.py`（`SkillEquipmentRepository`） | assistant/specialist 方法论装备 N:M 状态、顺序、用户卸载与审计 |

### 数据库表（v11 Migration）

v11 迁移在 SQLite 中新增以下表：

| 表 | 说明 |
|----|------|
| `brain_segments` | Segment 记录（`open` 态不持久化，行仅在封存时创建） |
| `brain_memory_entries` | 六 zone 的 memory entry：hot / persistent / archive / subconscious / failure / prediction |
| `brain_specialists` | 专员定义（名称、描述、技能白名单、状态） |
| `brain_specialist_versions` | 专员版本历史 |
| `brain_recruitment_signals` | 自动招募信号 |
| `feedback_signals` | 用户反馈信号（prompt injection、silence no-op） |

### 方法论资产层（v12 Migration）

012 在 Brain Service 内新增“方法论资产”层。方法论与 specialist 平级，是 assistant 本体或 specialist 可装备的操作步骤与判断规则；UI 上原“工具技能”统一称为 Tool，Skill 词位只指方法论。

| 表 | 说明 |
|----|------|
| `brain_skills` | 方法论资产与版本链：`active → superseded / soft_deleted`，含 `origin`、`chain_root_id`、`loaded_count`、`referenced_count`、`change_reason` |
| `brain_skill_source_segments` | 方法论来源 Segment，只允许 archive / failure zone |
| `brain_skill_equipment` | assistant 本体 / specialist 与方法论的状态化装备关系，`active → unequipped` 留历史行 |

v12 表与普通大脑 entry 一样不允许物理删除：方法论删除走 `status = soft_deleted`，装备移除走 `status = unequipped` + `unequipped_reason`。`brain_skill_equipment` 使用 partial unique index 保证同一装备者与同一方法论最多一条 active 关系；SQLite trigger 阻断 `brain_skills` 与 `brain_skill_equipment` 的直连 DELETE。

业务入口：

- `SkillService` 管理 create / supersede / user edit / soft delete / history。supersede 使用 SQLite `BEGIN IMMEDIATE` 起始写锁，并始终按链根解析当前 active 作为新基线，避免版本链分叉。
- `SkillEquipmentService` 管理 equip / unequip / reorder / default propagation / supersede transfer；`system_bootstrap` 链根默认只装备 assistant 本体，用户主动装备过的 specialist 在后续 supersede 中继续跟随新版本。
- `SkillBootstrapService` 负责 seed 文件加载、fail-open fallback 和“如何创建方法论”内置方法论首装 assistant 本体。

Agent 与 prompt：

- assistant 与 specialist system prompt 只注入装备清单轻量段：id、name、description、trigger_conditions，不注入 `body_markdown`。
- 完整正文必须由 `load_skill_methodology(skill_id)` 按需加载，工具结果以 SKILL.md 形态进入 messages 序列，并触发 `loaded_count +1`。
- specialist 派活决策本身不读取方法论或 trigger_conditions；派活时冻结装备清单，本轮 `load_skill_methodology` 鉴权按冻结快照执行，装备变更最快下一轮生效。

事件：

- 后端 blinker：`brain_skill_changed`、`brain_skill_equipment_changed`、`brain_skill_supersede_completed`、`brain_skill_bootstrap_fallback_used`。
- 前端公开 UI event：`skill.changed`、`skill.equipment.changed`。旧 Tool 域事件为 `tools.changed`，不得恢复 `skills.changed`。

公开 UI event payload 以 `src/desktop_api/ui_events.py` Registry 为准：

| Event type | 必填 payload | 可选 payload | Scope |
|------------|--------------|--------------|-------|
| `skill.changed` | `reason`、`skillId`、`chainRootId` | `newSkillId`、`callerType`、`callerId`、`bootstrapFallbackUsed`、`bootstrapFallbackInfo` | `skillId` |
| `skill.equipment.changed` | `changeType`、`entityType`、`entityId`、`skillId` | `unequippedReason` | `entityId`、`skillId` |

### 前端路由

| 路由 | 页面 | 说明 |
|------|------|------|
| `/skills/methodology` | SkillMethodologyScreen | 方法论 active 列表、排序/筛选、编辑器、版本链与装备审计 |
| `/brain` | BrainScreen | 六 zone 浏览、过滤、entry 编辑/删除、evolution chain |
| `/brain/specialists` | SpecialistScreen | 专员 CRUD、软删除停用、白名单编辑、assistant 本体与 specialist 方法论装备 |

前端对应 Zustand store：`brainStore`（zone/entry/segment/skill-pool 状态，skill-pool 供 SpecialistScreen 白名单编辑复用）、`specialistStore`（专员列表/编辑草稿/白名单）、`skillMethodologyStore`（方法论列表、排序筛选、编辑草稿、装备关系、token budget thresholds）。

### 事件

| 事件名 | 触发时机 |
|--------|---------|
| `brain_zone_changed` | zone entry 新增、更新或删除 |
| `brain_specialist_changed` | 专员创建、更新、停用 |
| `segment_boundary_triggered` | Segment 封存触发（window_close / idle / new_session / token_limit） |
| `segment_idle_trigger` | 前端 idle timer 触发 Segment 边界 |
| `brain_specialist_recruited` | 自动招募专员成功 |
| `brain_context_ready` | 会话启动上下文组装完成 |
| `brain_skill_changed` | 方法论创建、接力、用户编辑、软删除 |
| `brain_skill_equipment_changed` | 方法论装备、卸下、调序、默认传播、接力转移 |
| `brain_skill_supersede_completed` | 方法论 supersede 链路提交完成 |
| `brain_skill_bootstrap_fallback_used` | 内置方法论 seed fail-open fallback 被使用 |

所有 brain 事件定义在 `src/utils/events.py`，由业务服务发出，经 `src/desktop_api/ui_events.py` 的公开 Registry 与 `src/desktop_api/ui_event_projector.py` 的投影层转为前端 UI event stream。

### 助理对话透明与可控（014-assistant-chat-transparency）

把"黑盒"主助理对话变成**看得见、停得下、接得上**，运行结构上新增：

- **取消原语（业务层）**：`src/business/agents/run_context.py` 持 `ContextVar[{root_session_id, cancel_event, generation}]` + 进程内 `session_id → threading.Event` 注册表 + 每次运行的代际 token + 待停止集合。`AssistantRuntime._run_assistant`（worker 线程入口）`begin()`/`finally: end()`；`AgentLoop.run` 在**迭代开头**与 **LLM 返回后/工具批次前**读 `cancel_event`，命中则置会话 `suspended` 并返回 `ResultType.CANCELLED`（新增取值，可恢复暂停，非错误）。助理 100% 调度，子代理/专员在**同一线程同步**跑子 loop，ContextVar 沿同步调用栈传播——停止一次父子皆停（深度取消，门卫测试守护同线程不变量）。
- **新增 blinker 事件**（`src/utils/events.py`）：`assistant_agent_step`（逐步过程，仅可观测运行时 emit、单回合上限）、`assistant_subagent_started/finished/paused`（子任务生命周期，session_id=父会话）。
- **公开 UI 事件**（Registry + projector，payload 走 009 allowlist 脱敏）：`assistant.activity`（过程时间线，按 `subagentId` 归类；`text` 字段保留原文 + `redacted` 标记——命中敏感规则的步骤 UI 默认隐藏、双击查看，原文本就明文存于 messages 表）、`assistant.subagent`（子任务卡片壳与状态，仍脱敏）；`assistant.progress.status` 新增 `cancelled` 取值，运行中 payload 带 `runId` 供停止请求绑定当前代际。非助理 agent_type 在 projector 处过滤，零 UI 噪声。
- **新增端点**（`src/desktop_api/routers/assistant.py`，经 `AssistantRuntime` facade）：`POST …/sessions/{id}/stop`（协作式停止，可选 body `{runId}` 防迟到旧停止误停新回合，pending 高危确认 fail-closed 唤醒，不破坏 CC-001）、`GET …/sessions/{id}/transcript?subagentId=`（过程时间线读模型）、`GET …/sessions/{id}/subagents`（子任务权威列表）。读模型在 `src/business/agents/observability.py`，由 `MessageRepository`/`WorkflowTransitionRepository`/`SessionRepository` **只读**重建，**无新表/迁移**；已压缩回合带 `compressed` 标志供前端按规整概要渲染。
- **结构化澄清端点**（019，`src/desktop_api/routers/assistant.py`）：`GET …/sessions/{id}/clarifications/pending`（当前会话待答澄清快照，无则 `clarification:null`，不含答案/草稿）、`POST …/sessions/{id}/clarifications/{requestId}/decision`（提交/取消，归属错配 404、答案校验失败 422 且不结算、已结算幂等 200）。状态仅在 `clarification_manager` 进程内存，**无新表/迁移/配置**。
- **"继续任务"**复用助理消息派发（不新增端点）：暂停子任务卡片发带 `subagent_id` 的续跑指令唤醒主助理，由主助理调既有 `continue_subagent` 续跑（守 100% 调度）。
- **前端**（`frontend/src/screens/assistant/`）：运行态输入门控 + 停止三态（`MessageComposer`）、单条原地排队三态机（`assistantStore`）、默认折叠限高内滚的活动时间线（`ActivityTimeline`）、子任务卡片 + 双击详情抽屉（`SubagentCard`/`SubagentDetailDrawer`），缺口走 `backend.resync_required` + 权威端点兜底。

### 后台 Worker

`BrainBackgroundWorker` 在 desktop API 启动时创建，随 sidecar 生命周期停止。它负责：

1. pending Segment 的蒸馏处理
2. 蒸馏中崩溃的 Segment 重置
3. hot-zone 衰减清扫
4. archive 分层聚合
5. prediction 生成与验证周期
6. subconscious distillation
7. invalidation review
8. 自动招募信号扫描与事件唤醒（`threading.Event`）

Worker 周期由 `brain.*` 配置控制，数值为占位符，待实测后调整。

### 上下文注入

assistant session 启动时，`BrainContextBuilder` 取代旧的 summary 注入逻辑：

1. 从 `BrainRepository` 读取 persistent-zone top-N entry（按配置上限）
2. 读取 hot-zone top-N entry（按 relevance + recency + effectiveness 排序）
3. 读取 subconscious-zone top-N entry（按新近度 + effectiveness + 探索权重排序）
4. 组装为 system prompt 中的 brain context section
5. 冷启动时触发 icebreaker 行为

---

## 十一、细化设计文档索引

各模块的详细设计文档，在架构 v2 基础上做了进一步决策，**以各设计文档为准**。

| 模块 | 设计文档 |
|------|----------|
| 数据层设计 | [data_layer_design.md](design/data_layer_design.md) |
| 记忆机制 | [memory_mechanism_design.md](design/memory_mechanism_design.md) |
| Agent Loop 核心 | [agent_loop_design.md](design/agent_loop_design.md) |
| 事件系统 + 流程编排 | [event_system_design.md](design/event_system_design.md) |
| PM Agent | [pm_agent_design.md](design/pm_agent_design.md) |
| 程序员 Agent | [programmer_agent_design.md](design/programmer_agent_design.md) |
| 试用 Agent | [trial_agent_design.md](design/trial_agent_design.md) |
| LLM Review | [llm_review_design.md](design/llm_review_design.md) |
| 办公助理 Agent | [assistant_agent_design.md](design/assistant_agent_design.md) |
| 技能组合 | [skill_composition_design.md](design/skill_composition_design.md) |
| Brain Service | `specs/010-assistant-brain-redesign/` 下的 `spec.md`、`plan.md`、`data-model.md`、`contracts/` |

---

*基于 v1 讨论精炼，记录时间：2026-03-11*
*更新：2026-03-27 — 精简文档：删除与设计文档重复的差异决策、办公助理详细设计和工具沉淀章节（已收入 assistant_agent_design.md），工具沉淀三条路径概述移至第一节*
*更新：2026-04-07 — 同步代码现状：精确化 Agent 两层通信机制描述；补全事件列表（teaching_failure 系列、trial_success、recording_started/stopped）；补充 Trial Agent Config 动态构建说明；新增教学失败追踪系统说明；更新优先级表完成状态*
*更新：2026-04-13 — 新增技能组合架构（第九节）：双模执行、数据模型、Assistant 集成、试用机制、needs_review 标记；删除已完成的优先级跟踪表，保留细化设计文档索引*
*更新：2026-04-21 — 同步当前实现形态：补充 assistant 后台任务队列为何不走 blinker；更正 AgentOrchestrator 为“对外单一入口 + 内部拆分子模块”的现状*
*更新：2026-05-16 — 同步前端事件层：新增后端 UI Event Registry、per-subscriber event stream、same-session replay/resync、typed frontend event consumption 和桌面 Trial preview 确认闭环*
*更新：2026-06-15 — 新增 Assistant 失败消息持久化、原样/编辑后重试、内联恢复卡和会话过滤 Debug Inspector 链路*
*更新：2026-05-05 — 同步桌面录制：新增桌面 recorder / Service / mode dispatch / 桌面专属工具 / sanity check / Trial runner / syntax gate / DPI 与 blinker 事件边界*
*更新：2026-05-24 — 新增隐藏 Debug Inspector、runtime-only trace lifecycle、Agent Flow provenance、fail-isolated model observation 和 opt-in Real Grand Tour 边界*
*更新：2026-06-12 — AgentLoop 对显式并发安全的连续读取工具并行执行 handler 与 output governance，结果保持主线程原序持久化*
