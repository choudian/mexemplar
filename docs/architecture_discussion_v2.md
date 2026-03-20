# Exemplar 架构设计 v2

本文档为架构讨论的最终结论，所有设计决策以本文档为准。讨论过程记录见 v1。

---

## 一、整体流程

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

### 关键设计决策

1. **各阶段不是连续的** — 代码生成后工具进入列表，用户随时试用，中间可能隔很久
2. **所有 Agent 的会话都能保存和恢复** — 试用反馈可能在生成之后很久才发生
3. **PM 是对外角色** — 用户跟 PM 对话确认需求，试用失败时由 PM 分诊
4. **试用通过对话进行** — 试用 Agent 引导用户、提取参数、执行工具、展示结果
5. **试用成功 3 次后发布** — 工具修改后成功次数清零
6. **需求确认分类分批提问** — 不一次全问也不一个一个问
7. **停止条件双向** — Agent 觉得够了或用户说够了，任一方都可以结束需求确认

---

## 二、三个 Agent 分工

### 角色定义

| Agent | 职责 | 阶段 |
|-------|------|------|
| **产品经理 Agent** | 需求分析、跟用户确认、试用失败时分诊 | 需求确认、分诊 |
| **程序员 Agent** | 分析录制数据、决定技术方案、写代码 | 代码开发 |
| **试用 Agent** | 引导用户、提取参数、执行工具、展示结果 | 工具试用 |

三个 Agent 用**同一套 Loop 代码**，只是配置不同（prompt、工具集）。

### 为什么拆分

- 一个 Agent 又要像产品经理思考又要像程序员写代码，prompt 很难调，两种思维模式互相干扰
- 各自职责清晰，prompt 聚焦
- 试用阶段的职责（引导、参数提取、执行）跟需求分析和代码开发都不相关

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
| 5 | 跟用户对话 | 把分析结果转化为用户能懂的问题去确认 | Agent 提问，不替用户做决定 |

- **所有 Agent 共用同一套 4 个录制数据工具**，角色差异由 prompt 引导（PM 关注操作流程和用户意图，程序员关注技术线索）
- 列表操作通过元素上下文启发式识别，不确定就直接问用户
- 详见 [recording_tools_redesign_todo.md](design/recording_tools_redesign_todo.md)

---

## 四、程序员 Agent 工具集

程序员拿到需求 + 参数列表后，自己去录制数据里挖技术细节，决定技术方案，编写代码。

| # | 工具 | 用途 |
|---|------|------|
| 1~4 | 录制数据工具 | 与 PM 共用同一套 4 个工具（describe_data、query_data、execute_code、analyze_image） |
| 5 | 语法校验 | 验证语法错误和导入问题（不是真正执行） |

### 关键设计

- **录制数据工具所有 Agent 共用** — agent 写 SQL 自主决定查什么，不限定 query_type
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

当前采用 FC（Function Calling）方式，tool definitions 每次 LLM 调用都随请求发送。每个 Agent 只有 2-3 个工具，definition 占用的 token 量很小，不是成本大头（真正吃 token 的是消息历史，由引用机制控制）。

如果后期工具数量增多导致 token 浪费明显，可改为 Skill 渐进式披露模式（按需加载 tool definition 到 prompt 中）。当前阶段不需要。

### 用户交互

靠消息历史串联，不在 Loop 内部暂停。每一轮用户交互就是一次独立的 Loop 调用，用户回复后作为新消息进来，Agent 看到历史上下文自然接上。

### Agent 调度

不加额外的协调层。各 Agent 在各自阶段独立运行。以后加新 Agent 角色，通过通用的 Agent 注册/派发机制扩展。

### Agent 之间的衔接：事件驱动

Agent 之间通过 blinker 事件通信，流程编排集中在一个独立文件中。

**事件定义：**

| 事件 | 触发时机 | 携带数据 |
|------|---------|---------|
| requirement_confirmed | PM 确认完需求，用户确认后 | 需求 JSON、recording_id |
| code_completed | 程序员写完代码 | 代码、需求 JSON |
| review_passed | LLM Review 通过 | 代码 |
| review_failed | LLM Review 不通过 | 代码、修改意见、当前次数 |
| tool_saved | 工具入库 | 工具 ID |
| trial_failed | 试用失败 | 用户反馈、工具 ID |
| triage_completed | PM 分诊完成 | 分诊结果（代码问题/需求问题）、反馈详情 |

**职责分离：**
- **Agent Loop** — 纯执行引擎，只负责跑循环和返回 AgentResult，不感知事件系统
- **AgentOrchestrator** — 根据 loop.run() 的返回值发出业务事件、通过 `_dispatch_next` 显式调度下一个 Agent

改流程只改 Orchestrator，改 Agent 不影响流程。

---

## 六、记忆机制

### 短期记忆：引用机制

Agent 的回复文字保留（天然就是摘要），工具返回的大块原始数据在 N 步之后替换成指针。

```
替换前：
  Agent: 我来查一下这个页面的网络请求
  Tool result: {完整的 200KB 响应数据...}
  Agent: 发现这个 API 返回了 JSON，data 字段包含列表数据

替换后：
  Agent: 我来查一下这个页面的网络请求
  Tool result: [REF::{message_id}] 此工具结果已归档（原始大小: 200000字符）。如需查看原始数据，请调用 load_reference("{message_id}")
  Agent: 发现这个 API 返回了 JSON，data 字段包含列表数据
```

- **触发时机**：固定步数（默认 3 步），可配置
- Agent 需要回看细节时，调用 `load_reference` 工具加载原始数据
- 不需要额外 LLM 调用生成摘要

### 会话级记忆：消息类型系统

对话历史存库，每条消息带**类型标签**。类型可扩展，初步识别：

- **普通消息（normal）** — Agent 回复、用户输入、系统提示、工具调用结果
- **压缩消息（compressed）** — 对第 X-Y 条消息的摘要，原始消息可归档

引用替换不体现为消息类型，而是运行时行为（见记忆机制设计）。

### 全局记忆

暂不实现，等项目跑通有真实用户数据后再加。

### 记忆使用范围

| Agent | 短期记忆 | 会话级长期记忆 | 全局级长期记忆 |
|-------|---------|--------------|--------------|
| 产品经理 | ✅ | ✅ 需求历史、修改记录 | 📋 暂不实现 |
| 程序员 | ✅ | ✅ 历次修改和试用反馈 | ❌ 不需要 |
| 试用 | ✅ | ✅ 试用历史 | ❌ 不需要 |

---

## 七、录制数据与采集通道

### 采集通道：扩展路线，不需要 CDP

- Chrome 扩展（content_script + background service worker）
- 覆盖所有 Chromium 系浏览器（Chrome、Edge、Brave、Arc、Opera）
- 早期曾用 CDP + Native Host，后切换到纯扩展，没有能力退化

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
- 短期记忆的引用机制 — 大块数据用指针，按需加载
- PM 分类分批提问
- 程序员不需要全局记忆
- PM 给程序员的交接信息只给需要的，不给分析过程

---

## 九、实现优先级

数据先行，基础设施先于业务角色。

| 优先级 | 模块 | 说明 |
|--------|------|------|
| 1 | **数据层设计** | 消息存储结构、消息类型系统、会话管理表结构 |
| 2 | **记忆机制** | 基于数据层实现引用替换、会话保存恢复、上下文加载 |
| 3 | **Agent Loop 核心** | 基于记忆机制管理消息历史 |
| 4 | **事件系统 + 流程编排** | Agent 之间的衔接 |
| 5 | **PM Agent** | prompt + 工具集 |
| 6 | **程序员 Agent** | prompt + 工具集（依赖数据存储层稳定） |
| 7 | **试用 Agent** | prompt + 工具集 |
| 8 | **LLM Review** | 代码质量检查 |

每个模块单独细化为独立的设计文档，细化到可直接开发的程度。

### 已完成的细化设计

| 优先级 | 模块 | 设计文档 | 与本文档的差异决策 |
|--------|------|----------|-------------------|
| 1 | 数据层设计 | [data_layer_design.md](design/data_layer_design.md) | 见下方说明 |
| 2 | 记忆机制 | [memory_mechanism_design.md](design/memory_mechanism_design.md) | 见下方说明 |
| 3 | Agent Loop 核心 | [agent_loop_design.md](design/agent_loop_design.md) | 见下方说明 |
| 4 | 事件系统 + 流程编排 | [event_system_design.md](design/event_system_design.md) | 见下方说明 |
| 5 | PM Agent | [pm_agent_design.md](design/pm_agent_design.md) | 见下方说明 |
| 6 | 程序员 Agent | [programmer_agent_design.md](design/programmer_agent_design.md) | 见下方说明 |
| 7 | 试用 Agent | [trial_agent_design.md](design/trial_agent_design.md) | 见下方说明 |
| 8 | LLM Review | [llm_review_design.md](design/llm_review_design.md) | 见下方说明 |

**数据层设计与第六节（记忆机制）的差异：**
- **删掉引用数据表** — 引用替换改为运行时行为（记忆层负责），数据层始终存储原始完整消息，不单独存引用
- **消息类型只保留 normal/compressed** — 去掉 reference 类型，因为引用不在数据层体现
- **会话表不存业务关联字段** — 不存 recording_id、tool_id 等，跨 Agent 传递的数据直接作为消息写入
- **新增 workflow_id 替代 parent_session_id** — 同一次录制触发的所有会话共享 workflow_id，避免多 Agent 反复协作时 parent 语义模糊
- **Fork 采用消息复制** — 分叉时创建新 session + 复制消息，所有 ID 换新，无递归依赖
- **新增 workflow_transitions 表** — 记录 Agent 之间的交接事件（谁交给谁、什么事件、携带什么数据），供未来调度模型分析协作模式

**记忆机制设计与第六节的细化/新增决策：**
- **引用步数按 assistant 消息计数** — "N步"细化为 tool result 之后的 assistant 回复数
- **引用大小阈值 2000 字符** — 小于此值的 tool result 不值得做引用替换
- **指针格式 `[REF::{message_id}]`** — 用 message_id 作为引用键，包含大小和加载指令
- **压缩触发为可组合策略** — 默认 token 估算，支持消息条数、组合策略，用户可配
- **Tool 交互内嵌** — 摘要保留 tool_call_id，后处理替换为 tool_call 数据 + tool_result 引用指针，内嵌在摘要文本中，不追加额外消息，不存在边界问题
- **结构化摘要格式** — 压缩输出强制固定章节（关键决策/技术发现/当前进展/待确认/标识符清单），保证摘要质量稳定
- **标识符保留** — 压缩时原样保留 recording_id、API 端点、CSS 选择器等不可重构的标识符
- **Token 估算安全余量** — 估算值乘 1.2，防止低估导致该压缩时未触发
- **System prompt 存入 messages 表** — 会话自包含可追溯，压缩时跳过不参与
- **压缩消息专用 `role='summary'`** — 与 system prompt 的 `role='system'` 区分，发 LLM 时映射为 system 角色

**Agent Loop 设计与第五节（Agent Loop 设计）的细化/新增决策：**
- **AgentLoop 上层两层架构** — "不加额外的协调层"细化为 AgentUIBridge（线程 + PyQt 信号）+ AgentOrchestrator（session 管理 + 事件发送），改编排不影响 UI，换 UI 不影响编排
- **LLM 客户端扩展** — 在 LangChainLLMClient 上新增 chat_with_tools() 方法，返回统一的 LLMResponse（content + tool_calls），Agent Loop 不接触 LangChain 内部类型
- **单工具调用模式** — 强制 `parallel_tool_calls=False`，每次 LLM 响应最多一个 tool_call，消除多工具调用的所有边界问题
- **talk_to_user 哨兵机制** — "靠消息历史串联"细化为哨兵工具，调用时 Loop 中断返回 AgentResult，tool result 为"[等待用户回复]"
- **AgentResult 返回值** — 4 种 ResultType（NEEDS_USER_INPUT / COMPLETED / ERROR / MAX_ITERATIONS_REACHED），AgentOrchestrator 据此决定后续行为
- **工具执行错误不终止循环** — 错误作为 tool result 返回给 LLM，由 Agent 自行决定重试或换策略
- **内置工具自动追加** — talk_to_user 和 load_reference 由 AgentLoop 自动追加到工具列表，不在 AgentConfig 中声明
- **文件结构** — src/business/agents/（复数）新目录，与旧 agent/ 共存直至迁移完成
- **max_iterations 默认值** — PM 50、程序员 30、试用 20

**事件系统设计与第五节的细化/新增决策：**
- **事件发送者** — Loop 不发任何事件，所有业务事件由 Orchestrator 在 loop.run() 返回后发出（避免 blinker 同步回调的嵌套执行问题）
- **事件类型** — 去掉 agent_completed 等通用事件，只保留有业务含义的事件（requirement_confirmed、code_completed 等）和交互事件（agent_needs_user_input、agent_error）
- **调度机制** — Orchestrator 根据 loop.run() 返回值通过 `_dispatch_next` 显式调度，不通过事件监听器调度
- **内部事件粒度** — 去掉 agent_iteration_started/completed、agent_tool_executed/failed 等内部事件
- **Orchestrator 职责** — 统一负责 session 管理、显式调度、业务事件发送，不需要独立的流程编排文件

**PM Agent 设计与第三节（PM Agent 工具集）的细化/新增决策：**
- **工具数量** — 从 3 个（查录制数据、多模态分析、跟用户对话）扩展为 6 个（4 个通用录制数据工具 + submit_requirements + report_code_issue），后两者通过 ToolSignal 机制提交结构化数据
- **需求输出方式** — 通过 submit_requirements 工具提交，结构由 FC schema 保证，不靠 prompt 约束 JSON 格式
- **分诊路由** — PM 调用 submit_requirements（需求问题）或 report_code_issue（代码问题），Orchestrator 根据 signal_tool.name 路由
- **录制数据工具** — 原"一个工具 + query_type"改为 4 个通用工具（describe_data、query_data、execute_code、analyze_image），所有 Agent 共用，角色差异由 prompt 引导。详见 [recording_tools_redesign_todo.md](design/recording_tools_redesign_todo.md)
- **System prompt 风格** — ReACT 风格（思考→行动→观察循环），不写死步骤清单

**程序员 Agent 设计与第四节（程序员 Agent 工具集）的细化/新增决策：**
- **工具数量** — 从 2 个（查录制数据、语法校验）扩展为 6 个（4 个通用录制数据工具 + syntax_check + submit_code），submit_code 通过 ToolSignal 机制提交结构化代码数据
- **代码输出格式** — `async def execute(**kwargs) -> Dict[str, Any]`，标准返回格式 `{success, message, data}`，支持命令行调用
- **技术方案决策** — API 优先策略：有可用 API 就不用浏览器模拟
- **录制数据工具** — 与 PM 共用同一套 4 个通用工具，agent 写 SQL 自主查询，不再受限于预定义 query_type
- **Orchestrator 适配** — `_on_programmer_completed` 从 `signal_tool.args["code"]` 获取代码，`_save_tool` 使用结构化 metadata

**LLM Review 设计与第四节（代码 Review）的细化/新增决策：**
- **Reviewer 输入** — 代码 + description + parameters，均来自 submit_code.args，无需额外查询；无原始 PM goal 字段，用程序员写的 description 替代
- **录制数据禁区** — Prompt 明确告知 Reviewer 不得质疑来自录制数据的技术决策（URL、API路径、响应字段结构、CSS选择器）
- **检查项细化** — "硬伤"具体为 5 类：语法错误、参数漏用、函数签名错误、返回格式错误、必崩逻辑
- **打回次数阈值** — retry_count < 4（程序员最多犯 3 次错，第 4 次失败强制入库），现有实现 retry_count < 3 需修正
- **输出格式** — 自然语言 feedback，不结构化（Orchestrator 路由不依赖类型，结构化只增加出错点）
- **打回消息** — 加轮次前缀"第 N 次，共最多 3 次"，让程序员感知进度
- **retry_count 存储** — 内存 Dict[workflow_id, int]，不持久化（Review 循环分钟级内完成，重启概率极低）
- **Review 异常** — 默认通过，不阻断流程
- **Prompt 注入** — str.replace() 替换占位符，避免代码中花括号触发 format 异常

**试用 Agent 设计与第一节（整体流程）的细化/新增决策：**
- **工具数量** — 2 个专用工具：execute_tool + submit_trial_result（+ 内置 talk_to_user），不给录制数据工具
- **参数提取** — Agent 在 execute_tool 的 parameters 字段中直接组装，不做单独的参数提取工具
- **执行机制** — 新增 `src/execution/tool_executor.py`（`run_tool_code`）：新线程 + asyncio.new_event_loop()，120 秒超时，不限制内建（代码已通过 syntax_check 审查），与 execute_code（数据探索）完全独立
- **System prompt 注入** — Orchestrator 在 `_build_trial_config` 中从 DB 读取工具信息注入模板，trial Loop 不缓存（每个 workflow system prompt 不同）
- **试用结论提交** — submit_trial_result(success, feedback)，Orchestrator 通过 workflow_id 查 DB 获取 tool_id
- **多次执行** — execute_tool 可在同一会话中多次调用，计数只在 submit_trial_result(success=True) 时更新
- **结果展示格式** — system prompt 定义默认规则（列表取前 3-5 条 + 总数、操作类说成败、无数据明确告知）
- **用户预期管理** — 开场主动告知用户这是自动生成的工具，遇到问题很正常
- **反馈质量** — 用户反馈模糊时追问具体原因，收集可定位问题的描述后再提交

---

## 十、待讨论事项

- [x] ~~Agent 之间的衔接机制~~（已确定，事件驱动 + 集中编排，见第五节）
- [ ] 测试策略
- [ ] 文档规范化
- [ ] UI 术语优化
- [ ] README 重写

---

*基于 v1 讨论精炼，记录时间：2026-03-11*
