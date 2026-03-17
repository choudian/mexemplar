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

## 三、query_recording_data 工具

### 3.1 设计理念

架构 v2 要求"一个工具覆盖所有查询"。PM 通过 `query_type` 参数指定想查什么，工具内部路由到不同的查询逻辑。

PM 版本**不提供网络请求查询**（架构 v2 明确指出"需求分析阶段不看网络请求，噪声太大"）。

### 3.2 Function Calling Schema

```json
{
  "type": "function",
  "function": {
    "name": "query_recording_data",
    "description": "查询录制数据。支持查询操作流程、操作详情、元素上下文、截图等。不支持查询网络请求（那是程序员的职责）。",
    "parameters": {
      "type": "object",
      "properties": {
        "recording_id": {
          "type": "string",
          "description": "录制会话 ID"
        },
        "query_type": {
          "type": "string",
          "enum": ["action_summary", "action_detail", "element_context", "screenshot"],
          "description": "查询类型：action_summary=操作流程概览, action_detail=单个操作详情, element_context=元素上下文（兄弟元素、列表信息）, screenshot=操作截图"
        },
        "action_index": {
          "type": "integer",
          "description": "操作序号（从1开始）。action_detail、element_context、screenshot 时必填"
        }
      },
      "required": ["recording_id", "query_type"]
    }
  }
}
```

### 3.3 各查询类型说明

#### action_summary — 操作流程概览

PM 的第一步操作。返回整个录制的操作流程列表，每个操作精简为一行摘要。

**输入**：`recording_id`
**输出**：

```json
{
  "recording_id": "xxx",
  "total_actions": 8,
  "actions": [
    {
      "index": 1,
      "action_type": "navigate",
      "url": "https://www.baidu.com",
      "description": "打开 https://www.baidu.com",
      "has_input": false,
      "has_siblings": false
    },
    {
      "index": 2,
      "action_type": "click",
      "url": "https://www.baidu.com",
      "description": "点击搜索框",
      "has_input": false,
      "has_siblings": false
    },
    {
      "index": 3,
      "action_type": "keyboard_input",
      "url": "https://www.baidu.com",
      "description": "输入 'Python 教程'",
      "has_input": true,
      "has_siblings": false
    },
    {
      "index": 4,
      "action_type": "click",
      "url": "https://www.baidu.com",
      "description": "点击 '百度一下'",
      "has_input": false,
      "has_siblings": false
    },
    {
      "index": 5,
      "action_type": "click",
      "url": "https://www.baidu.com/s?wd=Python+教程",
      "description": "点击 'Python 官方教程 - 菜鸟教程'",
      "has_input": false,
      "has_siblings": true
    }
  ]
}
```

**生成逻辑**：
- 遍历 `actions` 表，按 `sequence_number` 排序
- 每个操作生成一行可读描述（根据 action_type + parameters + dom_element 组合）
- `has_input`：该操作是否包含用户输入（keyboard_input 类型或 input/textarea 元素的 change 事件）
- `has_siblings`：该操作的 action_id 在 `sibling_snapshots` 表中是否有记录

`has_input` 和 `has_siblings` 是给 PM 的线索提示——有输入的操作可能包含参数，有兄弟元素的操作可能是列表操作。PM 可以据此决定是否深入查看。

#### action_detail — 单个操作详情

PM 想深入了解某个操作的细节。

**输入**：`recording_id`, `action_index`
**输出**：

```json
{
  "index": 3,
  "action_type": "keyboard_input",
  "url": "https://www.baidu.com",
  "timestamp": "2026-03-10T14:30:00",
  "parameters": {
    "text": "Python 教程",
    "key": null
  },
  "dom_element": {
    "xpath": "//*[@id='kw']",
    "css_selector": "input#kw",
    "tag_name": "INPUT",
    "id": "kw",
    "className": "s_ipt",
    "text_content": "",
    "attributes": {
      "name": "wd",
      "type": "text",
      "placeholder": "请输入搜索关键词",
      "maxlength": "255",
      "autocomplete": "off"
    },
    "bounding_box": {"x": 350, "y": 170, "width": 550, "height": 44}
  }
}
```

**生成逻辑**：
- 从 `actions` 表查指定序号的操作
- `dom_element` 原样返回（来自浏览器扩展 `getElementLocator()`，不做字段过滤）
- **不返回** `dom_tree_snapshot`（太大，PM 不需要）和 `visual_features`（技术细节）

#### element_context — 元素上下文

PM 想看某个操作的兄弟元素，判断是否是列表操作。

**输入**：`recording_id`, `action_index`
**输出**：

```json
{
  "index": 5,
  "has_siblings": true,
  "siblings": {
    "container_selector": "div.search-results",
    "item_selector": "div.result-item",
    "list_type": "list",
    "total_count": 10,
    "clicked_index": 1,
    "items": [
      {"index": 1, "text_summary": "Python 官方教程 - 菜鸟教程", "has_link": true, "clicked": true},
      {"index": 2, "text_summary": "Python 入门教程 - 廖雪峰的官方网站", "has_link": true, "clicked": false},
      {"index": 3, "text_summary": "Python 基础教程 | 菜鸟教程", "has_link": true, "clicked": false}
    ]
  }
}
```

**生成逻辑**：
- 查 `sibling_snapshots` 表（按 action_id）
- 如有，返回兄弟元素摘要（只取每个兄弟的 `text_summary`，不返回完整 DOM 结构）
- 如果没有，返回 `has_siblings: false`

`items` 中每个兄弟只保留 `index`、`text_summary`（已由 JS 端截断到 50 字符）和 `has_link`（从 siblings JSON 中提取），控制数据量。如果兄弟元素超过 10 个，只返回前 5 个 + 后 5 个（含 clicked 项）并注明 `"truncated": true`。

#### screenshot — 操作截图

PM 想看某个操作的截图（操作前后各一张）。返回截图的 base64 数据，供后续 multimodal_analysis 使用。

**输入**：`recording_id`, `action_index`
**输出**：

```json
{
  "index": 5,
  "has_screenshot_before": true,
  "has_screenshot_after": true,
  "screenshot_before": "data:image/png;base64,iVBOR...",
  "screenshot_after": "data:image/png;base64,iVBOR..."
}
```

**生成逻辑**：
- 从 `actions` 表查指定序号的操作
- 返回 `screenshot_before` 和 `screenshot_after`
- 如果截图为空，对应字段为 `null`，`has_screenshot_*` 为 `false`

**注意**：截图数据很大，PM 拿到后应该传给 multimodal_analysis 去分析，而不是自己直接看 base64。这条截图数据会被引用替换机制在 N 步后替换为指针。

**当前限制**：浏览器录制模式下 `screenshot_before` 和 `screenshot_after` **始终为空**（截图功能仅桌面录制实现）。这意味着浏览器录制场景中 `screenshot` 查询和 `multimodal_analysis` 工具实质上不可用。PM 需完全依赖文本数据（dom_element、parameters、sibling_snapshots）分析需求。

后续可通过浏览器扩展增加截图采集（`chrome.tabs.captureVisibleTab` API）来解决此限制。

### 3.4 description 生成逻辑

`action_summary` 中每个操作的 `description` 按以下规则生成：

这个方法不做字段转换，只是把原始数据组合成一句可读描述（给 `action_summary` 的 `description` 字段用）：

```python
def _generate_action_description(action: dict) -> str:
    action_type = action["action_type"]
    params = action.get("parameters", {})
    element = action.get("dom_element") or {}
    url = action.get("url", "")

    if action_type == "navigate":
        return f"打开 {url}"

    if action_type in ("keyboard_input", "fill"):
        text = params.get("text") or params.get("value", "")
        if text:
            return f"输入 '{text[:30]}'"
        key = params.get("key", "")
        return f"按键 {key}"

    if action_type == "click":
        text = element.get("text_content", "")
        if text and len(text) <= 30:
            return f"点击 '{text}'"
        tag = element.get("tag_name", "").lower()
        return f"点击 {tag} 元素"

    if action_type == "change":
        value = params.get("value", "")
        tag = element.get("tag_name", "").lower()
        return f"选择/修改 {tag}（值: {value}）"

    if action_type == "submit":
        return "提交表单"

    if action_type == "dblclick":
        text = element.get("text_content", "")
        return f"双击 '{text}'" if text else "双击元素"

    if action_type == "keydown":
        key = params.get("key", "")
        modifiers = []
        if params.get("ctrlKey"): modifiers.append("Ctrl")
        if params.get("altKey"): modifiers.append("Alt")
        if params.get("shiftKey"): modifiers.append("Shift")
        prefix = "+".join(modifiers) + "+" if modifiers else ""
        return f"按键 {prefix}{key}"

    return f"{action_type} 操作"
```

### 3.5 PM 与程序员的工具差异

同一个工具名 `query_recording_data`，但 PM 和程序员使用不同的 schema 和 handler：

| 维度 | PM 版本 | 程序员版本（优先级6设计） |
|------|--------|----------------------|
| query_type | action_summary, action_detail, element_context, screenshot | 以上 + network_requests, dom_tree, full_action |
| 返回详细度 | dom_element 原样返回，不含 dom_tree_snapshot / visual_features | 完整（包含所有技术细节） |
| 网络请求 | 不支持 | 支持 |
| DOM 树 | 不返回 | 支持查询 |

两个版本是独立的 `ToolDefinition` 实例，由 Orchestrator 组装后通过 `loop.run(tools=...)` 传入。

---

## 四、multimodal_analysis 工具

### 4.1 定位

非常规手段，兜底用。当 PM 从文本数据（操作描述、元素属性）无法判断用户意图时，用截图辅助理解。

**典型使用场景**：
- 页面布局复杂，元素文本不够描述清楚
- 需要确认"用户点的是页面上的哪个区域"
- 列表操作中，文本相似度高，需要视觉区分

### 4.2 Function Calling Schema

```json
{
  "type": "function",
  "function": {
    "name": "multimodal_analysis",
    "description": "分析操作截图，理解页面视觉布局。这是一个消耗大量 token 的操作，只在文本信息不够时才使用。截图数据需要先通过 query_recording_data（query_type=screenshot）获取。",
    "parameters": {
      "type": "object",
      "properties": {
        "screenshot_data": {
          "type": "string",
          "description": "截图的 base64 数据（从 query_recording_data 的 screenshot 查询结果中获取）"
        },
        "question": {
          "type": "string",
          "description": "分析问题，如'这个页面上有什么表单元素？'、'用户点击的是页面的哪个区域？'"
        }
      },
      "required": ["screenshot_data", "question"]
    }
  }
}
```

### 4.3 实现方案

```python
def multimodal_analysis(screenshot_data: str, question: str) -> str:
    """
    调用多模态 LLM 分析截图

    使用 compression_model（Haiku 级别）进行分析，控制成本。
    如果未配置多模态模型，返回错误提示。
    """
    config = get_unified_config()

    # 复用 compression_model 配置（Haiku 级别，足够做截图分析）
    llm = create_llm_client(
        provider=config.get_compression_model_provider(),
        model=config.get_compression_model_name(),
        api_key=config.get_compression_model_api_key(),
    )

    # 构建多模态消息
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": screenshot_data.replace("data:image/png;base64,", "")
                    }
                },
                {
                    "type": "text",
                    "text": question
                }
            ]
        }
    ]

    response = llm.chat_with_messages(messages)
    return response
```

**模型选择说明**：
- 复用 `compression_model` 配置（默认 Haiku），控制成本
- 截图分析不需要最强模型，Haiku 级别足够理解页面布局
- 如果后续需要更精准的分析，可以在配置中切换到 Sonnet

### 4.4 PM 使用截图的典型流程

```
1. PM 查看 action_summary → 发现第5步"点击 a 元素"不够清楚
2. PM 调用 query_recording_data(query_type="screenshot", action_index=5)
   → 获得 screenshot_before 的 base64
3. PM 调用 multimodal_analysis(screenshot_data=..., question="用户点击的是页面上的什么？")
   → 获得"用户点击的是搜索结果列表中的第一个链接"
4. PM 结合文本和截图分析结果，继续需求确认
```

---

## 五、PM 交互流程

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

## 六、submit_requirements 工具

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

## 七、report_code_issue 工具

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

## 八、配置更新

### 8.1 工具定义

PM 的每个工具是一个 `ToolDefinition`（name + schema + handler）：

```python
# src/business/agents/tools/pm_recording_query.py
pm_query_recording_data = ToolDefinition(
    name="query_recording_data",
    schema=PM_QUERY_RECORDING_DATA_SCHEMA,
    handler=_pm_query_recording_data,
)

# src/business/agents/tools/multimodal_analysis.py
multimodal_analysis = ToolDefinition(
    name="multimodal_analysis",
    schema=MULTIMODAL_ANALYSIS_SCHEMA,
    handler=_multimodal_analysis,
)

# src/business/agents/tools/pm_output.py
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
from src.business.agents.tools.pm_recording_query import pm_query_recording_data
from src.business.agents.tools.multimodal_analysis import multimodal_analysis
from src.business.agents.tools.pm_output import submit_requirements, report_code_issue

PM_TOOLS = [pm_query_recording_data, multimodal_analysis, submit_requirements, report_code_issue]
# talk_to_user 和 load_reference 由 AgentLoop 自动追加，不需要在此列出

loop.run(session_id, user_input, tools=PM_TOOLS)
```

**为什么不用全局注册表**：PM 和程序员各自有不同版本的 `query_recording_data`（不同 schema 和 handler）。全局注册表按 name 做 key，同名会覆盖。由调用方组装传入，各 Agent 工具列表完全独立，无命名冲突。

### 8.3 文件结构

```
src/business/agents/
    tools/
        pm_recording_query.py        # PM 版本的 query_recording_data
        multimodal_analysis.py       # multimodal_analysis 实现
        pm_output.py                 # submit_requirements + report_code_issue
    prompts/
        pm_prompt.py                 # PM system prompt（常量字符串）
```

PM 的 system prompt 从 `config.py` 中移出到 `prompts/pm_prompt.py`，保持配置文件简洁。

---

## 九、边界情况

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

## 十、与架构 v2 的关系

### 一致的决策

- PM 不看网络请求
- PM 和程序员的"查录制数据"是同一个工具的不同配置
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
| query_type 设计 | "Agent 想看什么就查什么，不拆分多个工具" | 一个工具 + query_type 参数路由到 4 种查询，兼顾灵活性和可控性 |
| action_summary 输出 | 未明确 | 精简为一行摘要 + has_input/has_siblings 提示 |
| element_context 输出 | 未明确 | 兄弟元素只取 text_summary + has_link，超过 10 个截断为前 5 + 后 5 |
| 截图数据流 | "截图数据从工具1获取，工具2负责分析" | query_recording_data(screenshot) → base64 → multimodal_analysis(screenshot_data) |
| 多模态模型 | "工具2负责调用多模态模型分析" | 复用 compression_model 配置（Haiku 级别） |
| description 生成 | 未明确 | 按 action_type 生成可读描述的规则 |
| PM 初始输入 | 未明确 | Orchestrator 构造的结构化文本（正常/分诊两种模板） |
| system prompt 风格 | "PM 的人设是懂需求分析的产品经理" | ReACT 风格（思考→行动→观察循环），不写死步骤清单 |

---

*基于架构 v2 细化，记录时间：2026-03-17*
