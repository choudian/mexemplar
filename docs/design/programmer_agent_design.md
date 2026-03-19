# 程序员 Agent 设计

本文档为架构 v2 优先级6的细化设计，定义程序员 Agent 的 system prompt、工具集实现、代码输出格式及技术分析策略。

依赖：[Agent Loop 设计](agent_loop_design.md)、[事件系统设计](event_system_design.md)、[PM Agent 设计](pm_agent_design.md)

---

## 一、整体定位

程序员 Agent 是技术实现角色。核心能力：**读需求、查数据、定方案、写代码**。

```
PM 提交需求 JSON（goal + parameters + recording_id）
  → 程序员拿到需求 JSON 作为第一条 user message
  → 思考：需要什么技术信息？ → 查录制数据 → 观察结果 → 调整方案
  → 反复循环，直到有足够信息
  → 写代码 → 语法校验 → 提交代码
```

程序员不跟用户对话。程序员关心的是：
- 用户的目标到底是什么（透过操作看意图）
- 有哪些技术路径可以达成目标（多路径评估）
- 每条路径是否可行、代价多大（基于录制数据中的线索判断）
- 哪些值是参数化的（从需求 JSON 获取）
- 代码能不能跑通（语法校验）

---

## 二、System Prompt

```
你是 Exemplar 的程序员。你的任务是根据产品经理确认的需求，分析录制数据中的技术细节，编写代码来达成用户的目标。

## 你的身份

你是一个经验丰富的程序员。你不需要跟用户沟通——需求已经由产品经理确认好了。

你拿到的有两样东西：
- **需求 JSON**：产品经理已经确认了用户想做什么（目标和参数）
- **录制数据**：记录了用户实际做了什么（操作步骤、网络请求、页面结构等）

需求 JSON 定义你的目标，录制数据为你提供技术线索。但录制数据不是让你原样复现用户的操作——用户在浏览器里手动翻页抄数据，不意味着你也要写一个模拟翻页的程序，也许一个 API 调用就能拿到全部数据。

## 输入

你收到的第一条消息是需求 JSON，包含：
- goal：任务目标
- recording_id：录制 ID（用于查询录制数据）
- parameters：参数列表（哪些值是变量、哪些是固定的）
- notes：补充说明（可选）

## 你的思考方式

你每一步都要先想清楚再行动。遵循"思考 → 行动 → 观察"的循环：

1. **思考**：我的目标是什么？达成这个目标有哪些可能的技术路径？我还需要什么信息来判断哪条路径可行？
2. **行动**：查看录制数据（操作流程、网络请求、DOM 结构、截图等），获取判断依据
3. **观察**：拿到结果后，重新审视：这条路径走得通吗？有没有更简单的方式？需要换方向吗？

不断循环，直到你确定了可行的技术方案并有足够的信息来实现它。

### 技术决策方法论

达成同一个目标通常有多条技术路径。你的任务是从录制数据中找到线索，评估每条路径的可行性和代价，选择**能完成任务的、代价最小的**那条。

**核心原则：**

- **目标导向**：首先确保能完成任务，然后才考虑哪种方式更优
- **多路径评估**：不要只想一种方案，想想还有没有更简单的方式
- **基于证据判断**：录制数据中的线索（网络请求格式、DOM 结构、操作类型等）帮你判断每条路径是否可行
- **代价排序**：可行路径中，选最简单、最稳定、最不容易出错的

**录制数据是线索，不是模板。** 你需要透过用户的操作看到背后的目标，然后用程序员的方式达成它。

### 典型的思考过程

```
[思考] 目标：百度搜索关键词，获取前 N 条结果。
       可能的路径：1) 直接调 API 拿数据  2) 浏览器抓取页面  3) 其他方式？
       先看看录制数据里有什么线索。

[行动] 查看操作流程概览。
[观察] 用户做了 8 步：打开百度 → 输入关键词 → 点搜索 → 点击结果...
       这是搜索+采集。先看看有没有可以直接用的 API。

[行动] 查看网络请求概览。
[观察] 搜索结果页是 HTML（GET /s?wd=xxx → 200, 15KB），不是结构化数据。
       搜索建议有 JSON API，但那不是结果数据。
       → 路径 1（直接 API）不可行，没有现成的数据接口。

[思考] 那就需要从页面获取数据。两种方式：
       a) 用 requests 拿 HTML 再解析 — 更轻量，但百度可能有反爬
       b) 用 Playwright 打开浏览器 — 更重，但能绕过大部分反爬
       先看看请求有没有复杂的鉴权或加密参数。

[行动] 查看搜索请求的详情（network_detail）。
[观察] GET /s?wd=Python&rsv_spt=1&rsv_iqid=xxx&... 有大量签名参数，
       而且 cookie 里有加密 token。
       → 路径 2a（requests 直接请求）代价太高，需要逆向签名逻辑。

[思考] 确定用 Playwright 浏览器方案。现在需要结果列表的选择器。

[行动] 查看第 5 步的操作详情。
[观察] css_selector = "div.result h3 a"，用 class 定位，稳定性中等但可用。

[思考] 方案确定了：Playwright 打开百度 → 填关键词 → 搜索 → 提取结果列表。
       可以开始写代码了。

[行动] 编写代码 → 语法校验 → 提交。
```

### 代码编写要点

- 从需求 JSON 的 parameters 中获取所有变量参数
- 可以补充技术参数（如超时时间、翻页数量），在提交时一并声明
- 写完后用语法校验工具检查，确认无误后用提交工具提交

## 代码规范

### 函数签名

```python
async def execute(**kwargs) -> Dict[str, Any]:
```

所有参数通过 kwargs 传入。参数名与需求 JSON 中定义的 parameter.name 一致。

### 返回格式

```python
{
    "success": True/False,
    "message": "执行结果说明",
    "data": ...  # 采集到的数据或操作结果
}
```

### 代码结构

```python
import asyncio
import json
import sys
from playwright.async_api import async_playwright
from typing import Dict, Any

async def execute(**kwargs) -> Dict[str, Any]:
    """工具描述"""
    # 1. 从 kwargs 获取参数
    keyword = kwargs.get("keyword", "")

    # 2. 执行自动化
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            # ... 实现逻辑 ...
            return {"success": True, "message": "完成", "data": results}
        except Exception as e:
            return {"success": False, "message": f"执行错误: {str(e)}", "data": None}
        finally:
            await browser.close()

if __name__ == "__main__":
    params = {}
    for arg in sys.argv[1:]:
        if "=" in arg:
            key, value = arg.split("=", 1)
            params[key] = value
    result = asyncio.run(execute(**params))
    print(json.dumps(result, ensure_ascii=False, indent=2))
```

### 必须遵守的规则

- 代码必须独立运行，不依赖 Exemplar 项目内部模块
- 使用浏览器时用 playwright.async_api（异步），不使用 sync_api
- 纯 API 方案可以只用 requests/urllib，不需要引入 Playwright
- 所有用户可变参数从 kwargs 获取，不硬编码
- 必须有异常处理，出错时返回 success=False
- 使用浏览器时必须在 finally 中关闭浏览器
- 支持 `if __name__ == "__main__"` 命令行调用
- 允许导入的模块：json, re, datetime, time, typing, asyncio, sys, playwright, requests, urllib, csv, html, math, random, string, collections, itertools, pydantic, dataclasses, enum

### 禁止的操作

- 禁止导入 os, subprocess, shutil, importlib, ctypes, socket 等系统操作模块
- 禁止使用 eval, exec, compile
- 禁止文件读写操作（open, unlink, mkdir）
- 禁止硬编码敏感信息

## 技术参数补充

你可以在 PM 定义的参数之外补充技术参数。常见的技术参数：
- timeout：页面加载超时时间（秒）
- max_retries：失败重试次数
- headless：是否无头模式
- page_count：翻页数量
- wait_time：等待间隔（秒）

补充的参数在 submit_code 时一并声明。

## Review 失败

如果收到类似"Review 失败（第N次），修改意见：xxx"的消息，说明你之前提交的代码没通过审查。请根据修改意见修正代码，重新语法校验后提交。你能看到之前的完整上下文。

## 注意事项

- 代码质量比速度重要——Review 通不过会被打回
- 采集大量数据时注意翻页和去重
- 需求 JSON 是你的任务定义，始终以它为准
```

---

## 三、录制数据查询工具

> **本节已被统一工具设计替代。** 详见 [recording_tools_redesign_todo.md](recording_tools_redesign_todo.md)。

### 设计变更说明

原设计为程序员单独设计了 7 种 query_type 的 `query_recording_data` 工具，后经重新设计，改为 **4 个通用工具，所有 Agent 共用**：

| 工具 | 定位 | 替代原设计的 |
|------|------|-------------|
| `describe_data` | 数据发现入口（渐进式） | 无（新增） |
| `query_data` | agent 写 SQL 直接查询 DuckDB | 所有 query_type（action_summary, action_detail, element_context, network_overview, network_detail, dom_tree） |
| `execute_code` | 临时 Python 代码执行 | 无（新增，SQL 不够用时的补充） |
| `analyze_image` | 多模态模型分析截图 | screenshot query_type + multimodal_analysis |

**核心变化**：
- 程序员不再受限于 7 种预定义 query_type，可以直接写 SQL 做任意查询（JOIN、聚合、条件过滤等）。
- 角色差异由 prompt 处理。程序员的 prompt 引导它关注网络请求、DOM 结构等技术线索。
- recording_id 通过闭包注入，agent 在 SQL 中自行加 `WHERE recording_id = 'xxx'`。

**对程序员工作流的影响**：
- 原来需要分步调用 `network_overview` → `network_detail`，现在可以直接写 SQL 一步查到需要的数据
- 原来受 query_type 限制不能做的跨表查询（如"关联操作和网络请求"），现在可以直接 JOIN
- 复杂数据处理（如遍历 JSON 字段统计频次）可以用 `execute_code` 替代

实现代码：`src/business/agents/tools/recording_data_tools.py`

### 原第 3.3~3.5 节保留说明

原设计中 network_overview、network_detail、dom_tree 的查询逻辑和输出格式仍有参考价值——它们描述了程序员在分析录制数据时需要的信息结构。虽然工具层不再预定义这些查询，但程序员的 prompt 可以引导 agent 写出类似的 SQL 查询。原设计的要点：

- **网络请求**：过滤静态资源（image/stylesheet/font/script），只看 xhr/fetch/main_frame；response_body 按需查询避免撑满上下文
- **DOM 树**：数据量大，慎用；大多数情况 action_detail 的 dom_element 已足够
- **截图**：现在通过 `analyze_image(action_index, question)` 一步完成，不再需要先获取 base64 再传给分析工具

---

## 四、syntax_check 工具

### 4.1 定位

程序员写完代码后，提交前进行语法校验。不执行代码，只做静态检查。

### 4.2 Function Calling Schema

```json
{
  "type": "function",
  "function": {
    "name": "syntax_check",
    "description": "检查 Python 代码的语法正确性和导入合法性。不执行代码，只做静态分析。建议在提交代码前调用。",
    "parameters": {
      "type": "object",
      "properties": {
        "code": {
          "type": "string",
          "description": "要检查的 Python 代码"
        }
      },
      "required": ["code"]
    }
  }
}
```

### 4.3 Handler 实现

```python
import ast
import json

def _syntax_check(code: str) -> str:
    """
    语法检查 handler

    检查项：
    1. AST 解析（语法错误）
    2. 导入合法性（白名单校验，只允许安全模块）
    3. execute 函数签名
    4. 禁止的函数调用（eval, exec, open 等）

    Returns:
        str — JSON 格式的检查结果
    """
    errors = []
    warnings = []

    # 1. AST 解析
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return json.dumps({
            "passed": False,
            "errors": [f"语法错误（第{e.lineno}行）: {e.msg}"],
            "warnings": []
        }, ensure_ascii=False)

    # 2. 导入检查（白名单模式，与 system prompt 允许列表对齐）
    ALLOWED_MODULES = {
        "json", "re", "datetime", "time", "typing", "asyncio", "sys",
        "playwright", "requests", "urllib", "csv", "html", "math",
        "random", "string", "collections", "itertools",
        "pydantic", "dataclasses", "enum",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top_module = alias.name.split(".")[0]
                if top_module not in ALLOWED_MODULES:
                    errors.append(f"禁止导入模块: {alias.name}（不在允许列表中）")
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                top_module = node.module.split(".")[0]
                if top_module not in ALLOWED_MODULES:
                    errors.append(f"禁止导入模块: {node.module}（不在允许列表中）")

    # 3. execute 函数检查
    has_execute = False
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == "execute":
                has_execute = True
                if not isinstance(node, ast.AsyncFunctionDef):
                    warnings.append("execute 函数建议使用 async def")
    if not has_execute:
        errors.append("缺少 execute 函数定义")

    # 4. 禁止的调用
    FORBIDDEN_CALLS = {"eval", "exec", "compile", "__import__", "open"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_CALLS:
                errors.append(f"禁止调用: {node.func.id}()")

    passed = len(errors) == 0
    return json.dumps({
        "passed": passed,
        "errors": errors,
        "warnings": warnings,
    }, ensure_ascii=False)
```

### 4.4 ToolDefinition

```python
syntax_check = ToolDefinition(
    name="syntax_check",
    schema=SYNTAX_CHECK_SCHEMA,
    handler=_syntax_check,
)
```

---

## 五、submit_code 工具

### 5.1 定位

程序员完成代码编写后调用此工具提交。handler 返回 `ToolSignal`，Loop 中断，Orchestrator 从 `signal_tool.args` 获取结构化数据。

与 PM 的 `submit_requirements` 机制完全一致。

### 5.2 Function Calling Schema

```json
{
  "type": "function",
  "function": {
    "name": "submit_code",
    "description": "提交编写完成的代码。代码必须通过语法校验后再提交。",
    "parameters": {
      "type": "object",
      "properties": {
        "tool_name": {
          "type": "string",
          "description": "工具名称（英文，snake_case，如 baidu_search_scraper）"
        },
        "description": {
          "type": "string",
          "description": "工具功能描述（中文，一句话）"
        },
        "code": {
          "type": "string",
          "description": "完整的 Python 代码"
        },
        "execution_strategy": {
          "type": "string",
          "enum": ["browser", "api", "hybrid"],
          "description": "执行策略：browser=浏览器自动化, api=直接调用API, hybrid=混合"
        },
        "parameters": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "name": {"type": "string", "description": "参数名"},
              "description": {"type": "string", "description": "参数说明"},
              "type": {"type": "string", "description": "参数类型（string/integer/boolean）"},
              "required": {"type": "boolean", "description": "是否必填"},
              "default": {"description": "默认值（可选，类型与参数类型一致）"}
            },
            "required": ["name", "description", "type", "required"]
          },
          "description": "完整参数列表（包含 PM 定义的参数和你补充的技术参数）"
        }
      },
      "required": ["tool_name", "description", "code", "execution_strategy", "parameters"]
    }
  }
}
```

### 5.3 Handler 实现

```python
def _submit_code(
    tool_name: str,
    description: str,
    code: str,
    execution_strategy: str,
    parameters: list,
) -> ToolSignal:
    """提交代码，中断循环"""
    return ToolSignal(
        result_type=ResultType.COMPLETED,
        display_text="[代码已提交]",
    )
```

### 5.4 Orchestrator 端处理

```python
# _on_programmer_completed 中
if result.signal_tool and result.signal_tool.name == "submit_code":
    code_data = result.signal_tool.args
    code = code_data["code"]

    emit("code_completed", sender=self,
         workflow_id=workflow_id,
         session_id=session_id,
         code=code)
    self._transition_repo.create(...)

    self._run_review(code, session_id, workflow_id)
```

`_save_tool` 同时使用 `code_data` 中的 `tool_name`、`description`、`execution_strategy`、`parameters`，不再需要 `_extract_tool_name(code)` 等临时解析方法。

---

## 六、程序员交互流程

### 6.1 正常代码生成流程

```
Orchestrator 调用 run_agent("programmer", json.dumps(requirements), workflow_id)
  → AgentLoop 启动程序员

程序员自动执行（无需用户交互）：
  1. 解析需求 JSON，提取 goal、parameters、recording_id
  2. 调用 describe_data() 了解数据概况
  3. 用 query_data 写 SQL 查询操作流程和网络请求，分析技术线索
  4. 如需要，进一步查询操作详情、DOM 结构、API 响应等
  5. 如需要，调用 analyze_image 分析截图
  6. 确定技术方案
  7. 编写代码
  8. 调用 syntax_check(code=...)
  9. 修复语法问题（如有）
  10. 调用 submit_code(tool_name=..., code=..., ...)

submit_code handler 返回 ToolSignal(COMPLETED)
  → Loop 中断
  → AgentResult(signal_tool=ToolCallInfo(name="submit_code", args={...}))
  → Orchestrator → emit code_completed → 启动 Review
```

### 6.2 Review 失败重试流程

```
Orchestrator 调用 run_agent("programmer", "Review 失败（第1次），修改意见：xxx", workflow_id)
  → AgentLoop 恢复程序员 session（复用，有完整上下文）

程序员看到 Review 反馈：
  1. 分析修改意见
  2. 如需要，重新查询录制数据
  3. 修改代码
  4. syntax_check → submit_code

最多打回 3 次。超过 3 次 Orchestrator 强制入库。
```

### 6.3 分诊回来流程

```
Orchestrator 调用 run_agent("programmer", "用户反馈: xxx", workflow_id)
  → AgentLoop 恢复程序员 session

程序员看到用户反馈（来自 PM 分诊的 report_code_issue）：
  1. 分析用户反馈
  2. 查询录制数据定位问题
  3. 修改代码
  4. syntax_check → submit_code
```

### 6.4 程序员初始输入

由 Orchestrator 构造，直接传入需求 JSON：

```python
# 正常场景（recording_id 包含在 requirements_json 中，不单独传递）
self.run_agent("programmer", json.dumps(requirements_json), workflow_id)
```

`requirements_json` 结构（来自 PM 的 submit_requirements）：

```json
{
  "goal": "百度搜索关键词，获取前N条结果的详情页内容",
  "recording_id": "xxx",
  "parameters": [
    {
      "name": "keyword",
      "description": "搜索关键词",
      "recorded_value": "Python 教程",
      "type": "variable"
    },
    {
      "name": "result_count",
      "description": "获取结果数量",
      "recorded_value": "10",
      "type": "variable"
    }
  ],
  "notes": "用户希望获取结果页面的标题和摘要"
}
```

### 6.5 参数格式转换

PM 的 `submit_requirements` 参数格式与程序员的 `submit_code` 参数格式不同，程序员需要在编码过程中完成转换：

| PM 格式（输入） | submit_code 格式（输出） | 说明 |
|----------------|------------------------|------|
| `name` | `name` | 直接沿用 |
| `description` | `description` | 直接沿用 |
| `recorded_value` | `default` | recorded_value 作为默认值参考（程序员可根据语义调整） |
| `type: "variable"` | `required: true` | variable 参数通常是必填的 |
| `type: "fixed"` | `required: false`, 写入 `default` | fixed 参数通常有固定默认值 |
| — | `type: "string"/"integer"/"boolean"` | 程序员根据 recorded_value 的语义推断数据类型 |

程序员还会补充技术参数（如 `timeout`、`headless`），这些参数只出现在 submit_code 中，PM 不感知。

---

## 七、自然结束处理

程序员应始终通过 `submit_code` 提交代码。如果 LLM 不调用任何工具就结束循环（自然结束），`signal_tool` 为 None，Orchestrator 应视为异常。

Orchestrator 处理：

```python
def _on_programmer_completed(self, result, session_id, workflow_id):
    if result.signal_tool and result.signal_tool.name == "submit_code":
        # 正常路径
        ...
    else:
        # 异常：程序员未通过 submit_code 提交
        # 尝试从 final_output 中提取代码（兜底）
        code = self._extract_code(result.final_output)
        if code and code != result.final_output:
            # 提取到了代码块，继续流程
            ...
        else:
            # 完全无法提取代码
            emit("agent_error", ...)
```

---

## 八、配置

### 8.1 工具定义

程序员的工具分为两类：**录制数据访问工具**（通用，所有 Agent 共用）和**专用工具**（程序员独有）。

```python
# src/business/agents/tools/recording_data_tools.py — 通用工具，闭包绑定 recording_id
from src.business.agents.tools import create_recording_tools
recording_tools = create_recording_tools(recording_id)
# 返回 [describe_data, query_data, execute_code, analyze_image]

# src/business/agents/tools/programmer_tools.py — 程序员专用工具
syntax_check = ToolDefinition(
    name="syntax_check",
    schema=SYNTAX_CHECK_SCHEMA,
    handler=_syntax_check,
)

submit_code = ToolDefinition(
    name="submit_code",
    schema=SUBMIT_CODE_SCHEMA,
    handler=_submit_code,
)
```

### 8.2 Orchestrator 组装

```python
from src.business.agents.tools import create_recording_tools
from src.business.agents.tools.programmer_tools import syntax_check, submit_code

recording_tools = create_recording_tools(recording_id)
PROGRAMMER_TOOLS = recording_tools + [syntax_check, submit_code]
# talk_to_user 和 load_reference 由 AgentLoop 自动追加

loop.run(session_id, user_input, tools=PROGRAMMER_TOOLS)
```

### 8.3 文件结构

```
src/business/agents/
    tools/
        __init__.py                      # 导出 create_recording_tools
        recording_data_tools.py          # 4 个通用录制数据工具（所有 Agent 共用）
        pm_recording_tools.py            # [已废弃] 旧 PM 版 query_recording_data
        pm_output_tools.py               # PM 输出工具（已有）
        programmer_tools.py              # syntax_check + submit_code（新增）
    prompts/
        pm_prompt.py                     # PM system prompt（已有）
        programmer_prompt.py             # 程序员 system prompt（新增）
```

### 8.4 AgentConfig 更新

`src/business/agents/config.py` 中需要新增 `PROGRAMMER_CONFIG`（或更新已有占位配置），将本设计第二节的 system prompt 写入 `system_prompt` 字段：

```python
PROGRAMMER_CONFIG = AgentConfig(
    agent_type=AgentType.PROGRAMMER,
    system_prompt=PROGRAMMER_SYSTEM_PROMPT,  # 从 prompts/programmer_prompt.py 导入
    max_iterations=30,  # 程序员需要更多迭代（查数据 + 写代码 + 校验）
)
```

---

## 九、边界情况

### 9.1 录制数据中没有网络请求

`network_overview` 返回 `total_requests: 0`。程序员应直接走浏览器自动化方案。

### 9.2 网络请求的 response_body 为 null

进行中的请求或被扩展拦截的请求可能没有 response_body。`network_detail` 中 `response_body = null`，`has_response_body = false`。

### 9.3 dom_tree_snapshot 为 null

浏览器录制模式下此字段可能为空（Phase 2 增强功能）。`dom_tree` 查询返回 `has_dom_tree: false`。程序员应依赖 `action_detail` 中的 `dom_element`。

### 9.4 语法校验通过但 Review 失败

语法校验只检查 AST 合法性和导入安全性。逻辑错误（如选择器写错、参数漏用）由 LLM Review 捕获。程序员根据 Review 反馈修正。

### 9.5 超大 network_overview

如果录制期间有大量 API 请求（> 50 条过滤后），截断为前 50 条并标注 `"truncated": true, "total_shown": 50`。程序员通常只需要前几个关键 API。

### 9.6 自然结束（未调用 submit_code）

见第七节处理方式。Orchestrator 尝试从 `final_output` 提取代码作为兜底。

### 9.7 程序员想跟用户对话

程序员有 `talk_to_user`（内置工具），但正常流程中不应使用。如果程序员确实调用了 `talk_to_user`，Loop 正常中断，Orchestrator 将问题通过 UI 展示给用户。用户回复后恢复程序员 session。

这是兜底机制——需求不清晰时程序员可以问用户，但理想情况下 PM 已经确认清楚了。

---

## 十、与架构 v2 的关系

### 一致的决策

- 程序员自己去录制数据里挖技术细节，决定技术方案
- 录制数据查询工具所有 Agent 共用（4 个通用工具，详见 [recording_tools_redesign_todo.md](recording_tools_redesign_todo.md)）
- 需求常驻上下文（作为第一条 user message）
- 允许程序员补充技术参数
- 工具集详细设计依赖数据存储层

### 本设计新增/细化的决策

| 决策 | 架构 v2 原文 | 本设计 |
|------|-------------|--------|
| 工具数量 | "2 个工具（查录制数据 + 语法校验）" | 6 个工具：4 个通用录制数据工具（describe_data、query_data、execute_code、analyze_image） + syntax_check + submit_code |
| 代码提交方式 | "程序员写完代码" | 通过 `submit_code` 工具（ToolSignal）提交结构化数据，不靠从自由文本提取代码 |
| 代码输出格式 | 未明确 | `async def execute(**kwargs) -> Dict[str, Any]`，标准返回格式，支持命令行调用 |
| 技术方案决策 | "决定技术方案" | ReACT 循环中根据录制数据动态决策，API 优先策略作为指南而非固定步骤 |
| 语法校验 | "验证语法错误和导入问题（不是真正执行）" | AST 解析 + 导入白名单 + execute 函数签名检查 + 禁止调用检查 |
| 参数补充 | "允许程序员在开发过程中追加" | 在 `submit_code` 的 parameters 字段中声明完整参数列表（PM 的 + 技术追加的） |
| Review 反馈 | "LLM Review 打回" | Orchestrator 将反馈作为 user_input 发给程序员，session 复用，有完整上下文 |
| 录制数据工具 | "PM 和程序员是同一个工具的不同配置" | 改为 4 个通用工具所有 Agent 共用，agent 写 SQL 自主查询，角色差异由 prompt 引导。详见 [recording_tools_redesign_todo.md](recording_tools_redesign_todo.md) |
| Orchestrator 适配 | "_extract_code(final_output)" | 改为从 `signal_tool.args["code"]` 获取，`_save_tool` 使用结构化 metadata |

### 对 event_system_design.md 的影响

`_on_programmer_completed` 需要更新：

```python
# 现有设计（event_system_design.md 8.3.3）
def _on_programmer_completed(self, result, session_id, workflow_id):
    code = self._extract_code(result.final_output)  # 从自由文本提取

# 更新为
def _on_programmer_completed(self, result, session_id, workflow_id):
    if result.signal_tool and result.signal_tool.name == "submit_code":
        code_data = result.signal_tool.args
        code = code_data["code"]
        # code_data 还包含 tool_name, description, execution_strategy, parameters
    else:
        code = self._extract_code(result.final_output)  # 兜底
```

`_save_tool` 签名更新：

```python
# 现有
def _save_tool(self, code, workflow_id, session_id, status="pending"):

# 更新为
def _save_tool(self, code_data: dict, workflow_id, session_id, status="pending"):
    # code_data 包含: code, tool_name, description, execution_strategy, parameters
    # 直接使用结构化 metadata，替代 _extract_tool_name(code) 等临时解析方法
```

### 对现有 CodeExecutor 的影响

本设计定义的代码格式（`async def execute(**kwargs)` + `playwright.async_api`）与现有 `src/execution/code_executor.py` 存在差异：

| 维度 | 现有 CodeExecutor | 本设计 |
|------|------------------|--------|
| 入口函数名 | `execute_tool` | `execute` |
| 调用方式 | 同步 | 异步（`async def`） |
| Playwright API | `playwright.sync_api` | `playwright.async_api` |
| 允许模块 | 不含 `asyncio` | 含 `asyncio` |

**处理方式**：现有 CodeExecutor 是 v1 遗留组件，v2 的工具执行将由试用 Agent（优先级 7）设计新的执行机制。CodeExecutor 的适配不在本设计范围内，但此差异需要在优先级 7 设计时统一解决。

---

*基于架构 v2 细化，记录时间：2026-03-18*
