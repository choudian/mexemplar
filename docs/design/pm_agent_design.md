# PM Agent 设计

本文档为架构 v2 优先级5的细化设计，定义 PM Agent 的 system prompt、工具集实现、交互策略及输出格式。

依赖：[Agent Loop 设计](agent_loop_design.md)、[事件系统设计](event_system_design.md)

---

## 一、整体定位

PM Agent 是面向用户的需求分析角色。核心能力：**看、猜、问、再看**。

```
录制完成
  → PM 拿到 recording_id
  → 查看操作流程（第一轮粗看）
  → 推测用户目标
  → 向用户提问确认（分类分批）
  → 如有疑问，回看录制数据细节
  → 用户确认完毕 → 输出需求 JSON
```

PM 不是程序员。PM 不关心技术实现细节（API 怎么调、代码怎么写），只关心：
- 用户想做什么（目标）
- 哪些值每次都变（参数）
- 哪些是固定步骤（常量）

---

## 二、System Prompt

```
你是 Exemplar 的产品经理。你的任务是分析用户的浏览器操作录制，理解用户想要自动化的工作流程，并与用户确认需求。

## 你的身份

你是一个懂需求分析的产品经理，不是程序员。你关注的是"用户想做什么"和"哪些东西每次都不一样"，不关心技术实现（不关心代码怎么写、API 怎么调）。

## 你的思考方式

你每一步都要先想清楚再行动。遵循"思考 → 行动 → 观察"的循环：

1. **思考**：基于当前已知信息，我还缺什么？下一步应该做什么？
2. **行动**：查看录制数据、深入查看某个操作的细节、或者向用户提问
3. **观察**：拿到结果后，重新审视：我的理解对不对？还有什么不确定的？

不断循环，直到你对用户的需求有充分的理解。

### 典型的思考过程

```
[思考] 我还没看过录制数据，先整体看一遍操作流程。
[行动] 查看操作流程概览。
[观察] 用户做了 8 步操作：打开百度 → 输入关键词 → 点击搜索 → 点击结果...
       第 3 步有文字输入，可能是参数。第 5 步点击了列表项，有兄弟元素。

[思考] 整体目标大概是"百度搜索并获取结果"。但第 5 步的列表操作不确定——
       用户是只要第一条结果，还是要所有结果？先看看那个操作的上下文。
[行动] 查看第 5 步的元素上下文。
[观察] 列表有 10 个兄弟元素，用户点的是第 1 个，类型是 list。
       很可能是列表操作。

[思考] 现在我大致理解了：搜索关键词 → 获取结果列表。
       需要跟用户确认：1) 目标是不是这样 2) 关键词是不是每次都变 3) 要几条结果
[行动] 向用户提问。
```

## 需求分析指南

### 目标识别

从操作流程中提炼用户的核心意图。关注：
- 用户最终到达了什么页面？得到了什么？
- 中间步骤中哪些是达成目标的必经之路，哪些是偶然的？

### 参数识别

参数是"每次执行时可能不同的值"。识别线索：
- 用户输入的文本（搜索词、表单填写）→ 很可能是参数
- 用户点击的特定列表项 → 项目名称或位置可能是参数
- URL 中的变量部分（商品 ID、用户名）→ 可能是参数

每个参数需要记录：name（英文简短名）、description（中文说明）、recorded_value（录制时的值）、type（"variable" 或 "fixed"）。

### 列表操作识别

如果某个操作涉及"从列表中选择一项"（可以从元素上下文中发现），需要弄清楚：
- 用户是要处理这一项，还是要处理多项/全部？
- 如果处理多项，怎么选择？（全部、前 N 项、按条件筛选）

### 提问策略

把问题按类别分组，一组一组地问，每组 2-4 个问题：
- **目标确认**：你是不是想做 XXX？（最重要，第一轮问）
- **参数确认**：这些值哪些是每次都变的？
- **边界情况**：如果遇到 XXX 怎么办？（可选，按需问）

不要一次全问（用户烦），也不要一个一个问（太慢）。

### 停止条件

以下任一条件满足即可结束需求确认：
- 你认为信息已经足够描述这个任务
- 用户表示"差不多了"、"可以了"、"就这些"等

如果操作流程清晰、目标明确、参数很少，确认一轮就够了，不要过度追问。

## 分诊模式

当你收到类似"工具 xxx 试用失败，用户反馈：xxx"的消息时，说明你正在分诊模式。

1. 分析用户反馈，判断问题类型：
   - **需求问题**（如"我不是要搜索百度，而是要搜索谷歌"）→ 与用户重新确认需求，确认完毕后用提交需求的工具提交
   - **代码问题**（如"点击按钮没反应"、"页面超时了"）→ 用报告代码问题的工具将反馈转交给程序员

2. 如果不确定是哪种问题，问用户。

## 注意事项

- 说话像产品经理，不用技术术语
- 不要替用户做决定，不确定就问
- 截图分析消耗大量资源，只在文字信息不够时才用
- 你的回复是给用户看的，要简洁友好
- 需求确认完毕后，用工具提交结果，不要直接输出 JSON
```

---

## 三、录制数据查询工具

> **本节已被统一工具设计替代。** 详见 [recording_tools_redesign_todo.md](recording_tools_redesign_todo.md)。

### 设计变更说明

原设计为 PM 和程序员分别设计了独立的 `query_recording_data` 工具（PM 4 种 query_type、程序员 7 种），后经重新设计，改为 **4 个通用工具，所有 Agent 共用**：

| 工具 | 定位 | 替代原设计的 |
|------|------|-------------|
| `describe_data` | 数据发现入口（渐进式：无参返回表概览，传表名返回字段详情） | 无（新增） |
| `query_data` | agent 写 SQL 直接查询 DuckDB | `query_recording_data` 的所有 query_type |
| `execute_code` | 临时 Python 代码执行（SQL 不够用时的补充） | 无（新增） |
| `analyze_image` | 多模态模型分析截图 | `multimodal_analysis` |

**核心变化**：
- **角色差异由 prompt 处理**，工具层不做区分。PM 也用 SQL 查数据，prompt 引导它关注操作流程和用户意图。
- **agent 自主决定看什么**。不再通过 query_type 枚举限定查询方式。
- **recording_id 通过闭包注入**，agent 不需要传 recording_id 参数。agent 写 SQL 时自行加 `WHERE recording_id = 'xxx'`（recording_id 在 agent 启动时写入 prompt）。

实现代码：`src/business/agents/tools/recording_data_tools.py`

### PM 使用截图的典型流程

原设计需要先 query_recording_data(screenshot) 获取 base64 再传给 multimodal_analysis，现在合并为一步：

```
1. PM 查看 describe_data() 了解数据概况
2. PM 用 query_data 查操作流程 → 发现第5步"点击 a 元素"不够清楚
3. PM 调用 analyze_image(action_index=5, question="用户点击的是页面上的什么？")
   → handler 内部从 DuckDB 读取截图，传给多模态模型，只返回文字分析结果
4. PM 结合文本和截图分析结果，继续需求确认
```

---

## 四、PM 交互流程

### 5.1 正常需求确认流程

```
Orchestrator 调用 run_agent("pm", "请分析这段录制", recording_id)
  → AgentLoop 启动 PM

PM 第一轮（自动，不需用户交互）：
  1. 调用 query_recording_data(recording_id, query_type="action_summary")
  2. 分析操作流程，推测目标
  3. 如有疑问，调用 action_detail / element_context 深入查看
  4. 组织第一批问题

PM 调用 talk_to_user：
  → Loop 中断，返回 NEEDS_USER_INPUT
  → 问题通过 UI 展示给用户

用户回复 → Orchestrator 调用 run_agent("pm", user_reply, recording_id)
  → AgentLoop 恢复

PM 可能继续提问（根据用户回答）：
  → 可能还有 1-2 轮 talk_to_user

PM 调用 submit_requirements(goal=..., parameters=[...])：
  → handler 返回 ToolSignal(COMPLETED)
  → Loop 中断，返回 AgentResult(signal_tool=ToolCallInfo(name="submit_requirements", args={...}))
  → Orchestrator 从 signal_tool.args 获取结构化需求 → emit requirement_confirmed
```

### 5.2 分诊流程

```
Orchestrator 调用 run_agent("pm", "工具 xxx 试用失败，用户反馈：xxx", recording_id)
  → PM 复用已有 session（能看到之前的需求确认上下文）

PM 分析用户反馈：

路径1 — 需求问题：
  → PM 调用 talk_to_user，跟用户重新确认需求
  → 确认完毕后调用 submit_requirements(...)
  → Orchestrator → emit requirement_confirmed

路径2 — 代码问题：
  → PM 调用 report_code_issue(feedback="...")
  → handler 返回 ToolSignal(COMPLETED)
  → Orchestrator 从 signal_tool.name == "report_code_issue" → emit triage_completed(code_issue)
```

### 5.3 PM 初始输入

PM 启动时收到的第一条 user message（由 Orchestrator 构造）：

**正常场景**：
```
请分析录制 {recording_id} 的操作流程，理解用户想要自动化的任务，并与用户确认需求。
```

**分诊场景**：
```
工具 {tool_id} 试用失败，用户反馈：{user_feedback}。
请分析问题原因：如果是需求问题，请与用户重新确认需求；如果是代码问题，请直接输出用户反馈供程序员排查。
```

---

## 五、submit_requirements 工具

### 6.1 定位

PM 需求确认完毕后调用此工具提交结构化需求。handler 返回 `ToolSignal`，Loop 中断，Orchestrator 从 `signal_tool.args` 获取结构化数据。

### 6.2 Function Calling Schema

```json
{
  "type": "function",
  "function": {
    "name": "submit_requirements",
    "description": "提交确认后的需求。当你与用户确认完毕、对任务目标和参数有充分理解后调用此工具。",
    "parameters": {
      "type": "object",
      "properties": {
        "goal": {
          "type": "string",
          "description": "任务目标的一句话描述"
        },
        "recording_id": {
          "type": "string",
          "description": "录制会话 ID"
        },
        "parameters": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "name": {"type": "string", "description": "参数名（英文，简短）"},
              "description": {"type": "string", "description": "参数说明（中文）"},
              "recorded_value": {"type": "string", "description": "录制时的实际值"},
              "type": {"type": "string", "enum": ["variable", "fixed"], "description": "variable=每次变的，fixed=固定的"}
            },
            "required": ["name", "description", "recorded_value", "type"]
          },
          "description": "参数列表"
        },
        "notes": {
          "type": "string",
          "description": "补充说明（用户提到的特殊要求等）"
        }
      },
      "required": ["goal", "recording_id", "parameters"]
    }
  }
}
```

### 6.3 Handler 实现

```python
def submit_requirements(goal: str, recording_id: str, parameters: list, notes: str = "") -> ToolSignal:
    """提交需求，中断循环"""
    return ToolSignal(
        result_type=ResultType.COMPLETED,
        display_text="[需求已提交]"
    )
```

handler 不做任何业务逻辑——结构化数据通过 `signal_tool.args` 传递给 Orchestrator。handler 只负责返回 `ToolSignal` 中断循环。

### 6.4 Orchestrator 端处理

```python
# _on_pm_completed 中
if result.signal_tool and result.signal_tool.name == "submit_requirements":
    requirements = result.signal_tool.args  # {goal, recording_id, parameters, notes}
    emit("requirement_confirmed", sender=self,
         workflow_id=workflow_id,
         requirements_json=requirements)
    self.run_agent("programmer", json.dumps(requirements), workflow_id)
```

不需要 JSON 解析容错——数据来自工具参数，结构由 Function Calling schema 保证。

---

## 六、report_code_issue 工具

### 7.1 定位

分诊场景中，PM 判定为代码问题时调用此工具，将用户反馈转交程序员。

### 7.2 Function Calling Schema

```json
{
  "type": "function",
  "function": {
    "name": "report_code_issue",
    "description": "报告代码问题。当你判断试用失败是代码层面的问题（不是需求问题）时调用此工具，将问题反馈转交给程序员。",
    "parameters": {
      "type": "object",
      "properties": {
        "feedback": {
          "type": "string",
          "description": "问题描述，包含用户反馈和你的判断"
        }
      },
      "required": ["feedback"]
    }
  }
}
```

### 7.3 Handler 实现

```python
def report_code_issue(feedback: str) -> ToolSignal:
    """报告代码问题，中断循环"""
    return ToolSignal(
        result_type=ResultType.COMPLETED,
        display_text="[代码问题已报告]"
    )
```

### 7.4 Orchestrator 端处理

```python
# _on_pm_completed 中
if result.signal_tool and result.signal_tool.name == "report_code_issue":
    feedback = result.signal_tool.args["feedback"]
    emit("triage_completed", sender=self,
         workflow_id=workflow_id,
         triage_result="code_issue",
         feedback=feedback)
    self.run_agent("programmer", feedback, workflow_id)
```

---

## 七、配置更新

### 8.1 工具定义

PM 的工具分为两类：**录制数据访问工具**（通用，所有 Agent 共用）和**信号工具**（PM 专用）。

```python
# src/business/agents/tools/recording_data_tools.py — 通用工具，闭包绑定 recording_id
from src.business.agents.tools import create_recording_tools
recording_tools = create_recording_tools(recording_id)
# 返回 [describe_data, query_data, execute_code, analyze_image]

# src/business/agents/tools/pm_output.py — PM 专用信号工具
submit_requirements = ToolDefinition(
    name="submit_requirements",
    schema=SUBMIT_REQUIREMENTS_SCHEMA,
    handler=_submit_requirements,  # 返回 ToolSignal
)

report_code_issue = ToolDefinition(
    name="report_code_issue",
    schema=REPORT_CODE_ISSUE_SCHEMA,
    handler=_report_code_issue,  # 返回 ToolSignal
)
```

### 8.2 Orchestrator 组装并传入

工具列表不在 AgentConfig 中，由 Orchestrator 组装后传入 `loop.run()`：

```python
# src/business/orchestrator/agent_orchestrator.py
from src.business.agents.tools import create_recording_tools
from src.business.agents.tools.pm_output import submit_requirements, report_code_issue

recording_tools = create_recording_tools(recording_id)
PM_TOOLS = recording_tools + [submit_requirements, report_code_issue]
# talk_to_user 和 load_reference 由 AgentLoop 自动追加，不需要在此列出

loop.run(session_id, user_input, tools=PM_TOOLS)
```

### 8.3 文件结构

```
src/business/agents/
    tools/
        __init__.py                  # 导出 create_recording_tools
        recording_data_tools.py      # 4 个通用录制数据工具（所有 Agent 共用）
        pm_recording_tools.py        # [已废弃] 旧 PM 版 query_recording_data
        pm_output.py                 # submit_requirements + report_code_issue
    prompts/
        pm_prompt.py                 # PM system prompt（常量字符串）
```

PM 的 system prompt 从 `config.py` 中移出到 `prompts/pm_prompt.py`，保持配置文件简洁。

---

## 八、边界情况

### 9.1 录制数据为空

`action_summary` 返回 `total_actions: 0`，PM 应该告诉用户"没有录制到操作"并结束。

### 9.2 截图不存在

`screenshot` 查询返回 `has_screenshot_before: false, has_screenshot_after: false`，PM 应该放弃截图分析，依赖文本信息。浏览器录制模式下此情况必然发生。

### 9.3 兄弟元素过多

`element_context` 中兄弟元素超过 10 个时，只返回前 5 个 + 后 5 个并标注 `truncated: true`。PM 可以通过文本告诉用户"列表有 N 项"。

### 9.4 用户想立刻结束

用户说"就这样"、"可以了"，PM 应该直接调用 `submit_requirements` 提交当前已确认的需求。

### 9.5 多模态分析不可用

如果 compression_model 未配置或调用失败，multimodal_analysis 返回错误信息。PM 应该继续依赖文本信息，不应中断流程。

### 9.6 自然结束（未调用 tool_signal 工具）

PM 可能在没有调用 `submit_requirements` 或 `report_code_issue` 的情况下自然结束循环（LLM 不返回 tool_calls）。此时 `signal_tool` 为 None，`final_output` 为自由文本。Orchestrator 应视为异常情况，emit `agent_error`。

---

## 九、与架构 v2 的关系

### 一致的决策

- PM 不看网络请求
- PM 和程序员共用同一套录制数据工具（4 个通用工具，详见 [recording_tools_redesign_todo.md](recording_tools_redesign_todo.md)）
- 分类分批提问
- 停止条件双向
- 列表操作通过元素上下文识别
- 截图分析是非常规手段，兜底用

### 本设计新增/细化的决策

| 决策 | 架构 v2 原文 | 本设计 |
|------|-------------|--------|
| PM 工具数量 | "3 个工具（查录制数据、多模态分析、跟用户对话）" | 5 个工具：查录制数据、多模态分析 + talk_to_user（内置）、submit_requirements、report_code_issue |
| 需求输出方式 | "输出结构化 JSON" | 通过 submit_requirements 工具提交，结构由 FC schema 保证，不靠 prompt 约束 JSON 格式 |
| 分诊路由 | "PM 分诊完成 → 分诊结果" | PM 调用 submit_requirements（需求问题）或 report_code_issue（代码问题），Orchestrator 根据 signal_tool.name 路由 |
| 录制数据工具 | "Agent 想看什么就查什么，不拆分多个工具" | 4 个通用工具（describe_data、query_data、execute_code、analyze_image），所有 Agent 共用，详见 [recording_tools_redesign_todo.md](recording_tools_redesign_todo.md) |
| 截图分析 | "截图数据从工具1获取，工具2负责分析" | analyze_image 一步完成（传操作序号 + 问题），handler 内部读取截图并调多模态模型 |
| 多模态模型 | "工具2负责调用多模态模型分析" | 通过 UnifiedConfigManager 获取用户配置的多模态模型 |
| PM 初始输入 | 未明确 | Orchestrator 构造的结构化文本（正常/分诊两种模板） |
| system prompt 风格 | "PM 的人设是懂需求分析的产品经理" | ReACT 风格（思考→行动→观察循环），不写死步骤清单 |

---

*基于架构 v2 细化，记录时间：2026-03-17*
