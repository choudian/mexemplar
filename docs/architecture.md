# Exemplar 架构设计 v2

本文档为架构讨论的最终结论，所有设计决策以本文档为准。讨论过程记录见 v1。

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

### 用技能：办公助理日常入口

```
用户在 ChatWidget 中发消息
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
| **办公助理 Agent** | 调用已发布工具执行日常任务、闲聊、触发修复/工具沉淀 | 日常使用 | 用户主动发起对话 |

四个 Agent 用**同一套 Loop 代码**，只是配置不同（prompt、工具集）。

### Agent 分类对比

| | PM / 程序员 | 试用 | 办公助理 |
|---|---|---|---|
| 定位 | 教技能（内部流程） | 教技能（验证阶段） | 用技能（面向用户的日常入口） |
| 生命周期 | 任务完成即结束 | 任务完成即结束 | 长期存在，随时可对话 |
| 工具集 | 录制数据工具 + 信号工具（固定） | execute_tool + submit_trial_result（固定） | 已发布的用户工具（动态）+ 内置通用工具 |
| 会话绑定 | 绑定 workflow_id | 绑定 workflow_id | 不绑定 workflow_id，独立存在 |

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
| 5 | 跟用户对话 | 把分析结果转化为用户能懂的问题去确认 | Agent 提问，不替用户做决定 |

- **PM 和程序员共用同一套 4 个录制数据工具**，角色差异由 prompt 引导（PM 关注操作流程和用户意图，程序员关注技术线索）。试用 Agent 和办公助理不使用录制数据工具
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

办公助理 Agent 采用 **FC + 懒加载**——内置工具全量 FC 注入，用户动态工具按需注入。详见 [assistant_agent_design.md](design/assistant_agent_design.md) 4.1-4.4 节。

### 用户交互

靠消息历史串联，不在 Loop 内部暂停。每一轮用户交互就是一次独立的 Loop 调用，用户回复后作为新消息进来，Agent 看到历史上下文自然接上。

### Agent 调度

不加额外的协调层。各 Agent 在各自阶段独立运行。以后加新 Agent 角色，通过通用的 Agent 注册/派发机制扩展。

办公助理不需要 `_dispatch_next`（没有下游 Agent），Loop 完成后不调度。助理触发的修复流程（`report_tool_bug`）和工具沉淀（`codify_as_tool`）通过异步任务队列投递，由后台 worker 消费后调用现有 PM 分诊流程。

### Agent 之间的衔接：两层通信机制

流程编排由 AgentOrchestrator 统一负责（不单独拆文件）。通信分两层：

| 通信方向 | 机制 | 说明 |
|---------|------|------|
| Loop → Orchestrator | return AgentResult | 函数调用返回值，同步 |
| Orchestrator → 外部 | blinker 事件 | 跨模块解耦通知，UI/日志/持久化各自监听 |

**事件不用于 Agent 间调度**。Orchestrator 收到 AgentResult 后通过 `_dispatch_next` 显式调用下一个 Agent，blinker 事件只发给 UI / 日志 / WorkflowTransition，不通过事件监听器触发下一步。

**完整事件列表**（均由 Orchestrator 发出，定义在 `src/utils/events.py`）：

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

各协作事件的数据格式详见 [event_system_design.md](design/event_system_design.md) 第三节。

PM/程序员/试用 Agent 通过 `workflow_id` 路由到对应 UI，办公助理通过 `session_id` 路由到对应 ChatWidget 实例。

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

### 跨会话记忆（办公助理专用）

办公助理需要跨会话记忆来理解用户的使用模式和历史任务。采用**层级摘要 + ID 引用**机制（全局摘要 → 分组摘要 → 会话摘要 → 原始消息），与会话内的引用替换同构，通过 `load_reference` 逐层下钻。详见 [assistant_agent_design.md](design/assistant_agent_design.md) 第七节。

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
- 办公助理的懒加载机制 — 只在 LLM 决定使用某个用户工具时才注入 FC schema，不一次性灌入所有工具定义
- 办公助理的跨会话记忆层级 — 全局摘要 ≤500 token 常驻 system prompt，需要细节时按 REF ID 逐层下钻

---

## 九、实现优先级

数据先行，基础设施先于业务角色。

**教技能流程（优先级 1-8）：**

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

**用技能流程（优先级 9-20）：**

| 优先级 | 模块 | 说明 | 状态 |
|--------|------|------|------|
| 9 | **助理 AgentConfig + Prompt** | 助理 Agent 配置、system prompt 模板 | ✅ 完成 |
| 10 | **动态工具懒加载** | DynamicToolManager + search_tools / get_tool_detail | ✅ 完成 |
| 11 | **Orchestrator 适配** | assistant 类型的会话管理、工具构建、签名变更 | ✅ 完成 |
| 12 | **ChatWidget 接通** | 去掉模拟回复，接通 AgentUIBridge | ✅ 完成 |
| 13 | **report_tool_bug** | 工具 bug 报告 → PM 分诊流程 | ✅ 完成 |
| 14 | **首次引导流程** | profile 收集、存储、注入 | ✅ 完成 |
| 15 | **内置通用工具** | web_search、web_fetch、exec 等内置工具实现 | ✅ 完成 |
| 16 | **侧边栏会话列表** | 多会话管理 UI | 待开发 |
| 17 | **新建会话工具选择** | 手动选择工具子集 | ✅ 完成（allowed_tool_ids 机制） |
| 18 | **工具沉淀路径 2** | codify_as_tool + PM 适配执行记录输入 | ✅ 完成 |
| 19 | **工具沉淀路径 3** | 重复模式检测 + 自动建议 + 拒绝冷却 | ✅ 完成 |
| 20 | **跨会话记忆** | 层级摘要 + memory_search + load_reference 扩展 | ✅ 完成 |

**额外实现（原计划外）：**

| 模块 | 说明 |
|------|------|
| **教学失败追踪** | agent_error 自动记录、UI 展示失败列表、三级策略重试（见第五节） |

每个模块单独细化为独立的设计文档，细化到可直接开发的程度。

### 已完成的细化设计

| 优先级 | 模块 | 设计文档 |
|--------|------|----------|
| 1 | 数据层设计 | [data_layer_design.md](design/data_layer_design.md) |
| 2 | 记忆机制 | [memory_mechanism_design.md](design/memory_mechanism_design.md) |
| 3 | Agent Loop 核心 | [agent_loop_design.md](design/agent_loop_design.md) |
| 4 | 事件系统 + 流程编排 | [event_system_design.md](design/event_system_design.md) |
| 5 | PM Agent | [pm_agent_design.md](design/pm_agent_design.md) |
| 6 | 程序员 Agent | [programmer_agent_design.md](design/programmer_agent_design.md) |
| 7 | 试用 Agent | [trial_agent_design.md](design/trial_agent_design.md) |
| 8 | LLM Review | [llm_review_design.md](design/llm_review_design.md) |
| 新增 | 办公助理 Agent | [assistant_agent_design.md](design/assistant_agent_design.md) |

细化设计文档在架构 v2 基础上做了进一步决策，**以各设计文档为准**。

---


*基于 v1 讨论精炼，记录时间：2026-03-11*
*更新：2026-03-27 — 精简文档：删除与设计文档重复的差异决策、办公助理详细设计和工具沉淀章节（已收入 assistant_agent_design.md），工具沉淀三条路径概述移至第一节*
*更新：2026-04-07 — 同步代码现状：精确化 Agent 两层通信机制描述；补全事件列表（teaching_failure 系列、trial_success、recording_started/stopped）；补充 Trial Agent Config 动态构建说明；新增教学失败追踪系统说明；更新优先级表完成状态*
