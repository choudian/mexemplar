# 试用 Agent 设计

本文档为架构 v2 优先级7的细化设计，定义试用 Agent 的 system prompt、工具集实现、工具执行引擎及与 Orchestrator 的集成方式。

依赖：[Agent Loop 设计](agent_loop_design.md)、[事件系统设计](event_system_design.md)、[程序员 Agent 设计](programmer_agent_design.md)

---

## 一、整体定位

试用 Agent 是连接"工具入库"和"工具发布"的最后一关。核心能力：**引导用户填参数、执行工具、展示结果、收集反馈**。

```
工具入库（pending）
  → 用户触发试用
  → 试用 Agent 启动（拿到工具描述和参数定义）
  → 引导用户提供参数（talk_to_user）
  → 用户给出参数（对话中提取）
  → 执行工具（execute_tool）
  → 展示结果（talk_to_user）
  → 用户确认成功/失败
  → 提交结果（submit_trial_result → ToolSignal）
  → Orchestrator 处理：成功计数/分诊
```

试用 Agent 是**对话引导角色**，不是程序员。它不分析代码，不修复 bug。它只关心：
- 用户填了什么参数
- 工具跑出了什么结果
- 用户觉得结果对不对

---

## 二、System Prompt

System prompt 是**模板**，由 Orchestrator 在启动试用时注入工具信息。

### 2.1 模板字符串

```
你是 Exemplar 的试用助手。你正在帮助用户试用一个刚自动生成的工具。

⚠️ 重要说明：这个工具是由 AI 自动生成的，还未经过人工验证。试用的目的就是发现问题——
执行报错、结果不对、行为和预期不符，都是正常的，帮助收集反馈就是在帮助改进工具。

## 本次试用的工具

**工具名称**：{tool_name}
**功能描述**：{description}

**参数列表**：
{parameters_text}

## 你的任务

1. 告知用户这是自动生成的工具，可能需要调整，让用户放松预期
2. 用友好的方式引导用户提供参数值
3. 从用户回复中提取参数，执行工具
4. 把执行结果用用户能看懂的方式展示
5. 询问用户结果是否符合预期，提交试用结论

## 你的思考方式

每一步先想清楚再行动：

1. **思考**：用户提供了哪些参数？还缺什么？执行结果说明了什么？
2. **行动**：引导用户填参数 / 执行工具 / 展示结果 / 询问反馈
3. **观察**：结果符合预期吗？用户满意吗？

## 引导策略

- 开场先告知用户这是自动生成的工具，可能存在问题，试用就是验证阶段
- 用非技术语言说话——不要暴露参数名（如 keyword），而是用"搜索关键词"
- 必填参数要引导用户填写；有默认值的参数告诉用户默认值并询问是否修改
- 一次引导所有必填参数，不要一个一个问
- 用户如果直接给了所有信息（如"帮我搜 Python 教程"），直接提取参数执行，不要再问

## 结果展示

执行完成后，根据结果类型展示：

- **列表类结果**（多条数据）：展示前 3-5 条的关键字段 + 总数量，如"共获取到 47 条，以下是前 3 条示例"
- **操作类结果**（提交表单、点击按钮等）：说清楚做了什么、结果是否成功
- **无数据结果**：明确告知"执行完成但没有返回数据"
- **执行报错**：说明出了技术问题（不是用户的问题），描述错误现象

用户若想查看更多数据，可以在对话中提出，再次执行或调整展示范围。

## 试用结论

展示结果后，询问用户是否符合预期。根据用户回复：
- 符合预期 → 调用提交成功工具
- 不符合预期 → 收集用户反馈（具体哪里不对），调用提交失败工具

## 反馈收集

用户表示结果不符合预期时，不要接受模糊反馈，要追问到能定位问题的程度：

- 用户说"不对" / "不好用" → 追问：哪里不对？数量不够、内容不准确、执行报错、还是其他？
- 用户说"报错了" → 追问：有没有看到错误信息？能描述一下发生了什么吗？
- 用户说"太慢了" → 记录：执行速度问题，大概等了多久？

反馈越具体，后续修复越精准。收集到具体描述后再调用提交失败工具。

## 注意事项

- 如果工具执行报错，这不是用户的问题——如实告诉用户出了技术问题
- 不要替用户判断结果好不好，让用户自己说
- 不需要看工具的代码，参数列表已经是工具的完整使用说明
```

### 2.2 参数文本格式化

`{parameters_text}` 由 `format_parameters_text()` 生成，格式规则：
- `required=True` → "必填"
- `required=False` 且有 `default` → "选填，默认 {default}"
- 展示参数的中文 `description`，括号内附参数名

示例输出：

```
- **搜索关键词**（keyword，必填）
- **获取结果数量**（result_count，选填，默认 10）
- **超时时间**（timeout，选填，默认 30）
```

---

## 三、工具集

试用 Agent 有 2 个专用工具（+ 内置的 talk_to_user、load_reference）：

| # | 工具 | 类型 | 说明 |
|---|------|------|------|
| 1 | `execute_tool` | 普通工具 | 执行工具代码，返回执行结果 |
| 2 | `submit_trial_result` | 信号工具 | 提交试用结论，Loop 中断 |

录制数据工具**不给试用 Agent 用**。试用 Agent 不需要分析录制数据，只需执行代码和对话。

---

## 四、execute_tool 工具

### 4.1 定位

执行工具代码，传入用户提供的参数，返回执行结果。工具代码通过工具执行引擎运行（见第六节）。

### 4.2 Function Calling Schema

```json
{
  "type": "function",
  "function": {
    "name": "execute_tool",
    "description": "执行工具，传入用户提供的参数。UI 层会显示加载状态，无需在执行前单独告知用户。",
    "parameters": {
      "type": "object",
      "properties": {
        "parameters": {
          "type": "object",
          "description": "工具参数，key 为参数名（英文），value 为参数值。只传用户明确提供或有默认值的参数。"
        }
      },
      "required": ["parameters"]
    }
  }
}
```

**设计说明**：参数用 `object` 类型而非固定属性，因为每个工具的参数列表是动态的，无法在 FC schema 中静态定义。Agent 根据上下文中的参数定义自行组装 `parameters` 字典。

### 4.3 Handler 实现

```python
def create_trial_tools(workflow_id: str) -> list[ToolDefinition]:
    """创建试用工具列表，workflow_id 通过闭包绑定。"""

    def _execute_tool_handler(parameters: dict) -> str:
        from src.data.repositories import ToolRepository
        tool_repo = ToolRepository()
        tool = tool_repo.get_by_workflow_id(workflow_id)
        if not tool:
            return json.dumps(
                {"success": False, "message": f"未找到工作流 {workflow_id} 对应的工具", "data": None},
                ensure_ascii=False,
            )
        if not tool.execution_code:
            return json.dumps(
                {"success": False, "message": "工具代码为空", "data": None},
                ensure_ascii=False,
            )

        result = run_tool_code(tool.execution_code, parameters)
        return json.dumps(result, ensure_ascii=False, default=str)

    def _submit_trial_result_handler(success: bool, feedback: str = "") -> ToolSignal:
        # success / feedback 不需要在这里处理。
        # AgentLoop 在检测到 ToolSignal 时，会将 LLM 函数调用的原始 args dict
        # （{"success": ..., "feedback": ...}）存入 AgentResult.signal_tool.args，
        # Orchestrator 直接从那里读取，无需 handler 转传。
        return ToolSignal(
            result_type=ResultType.COMPLETED,
            display_text="[试用结果已提交]",
        )

    return [
        ToolDefinition(
            name="execute_tool",
            schema=EXECUTE_TOOL_SCHEMA,
            handler=_execute_tool_handler,
        ),
        ToolDefinition(
            name="submit_trial_result",
            schema=SUBMIT_TRIAL_RESULT_SCHEMA,
            handler=_submit_trial_result_handler,
        ),
    ]
```

---

## 五、submit_trial_result 工具

### 5.1 定位

试用结束后，Agent 调用此工具提交结论。Handler 返回 ToolSignal，Loop 中断。Orchestrator 从 `signal_tool.args` 获取 `success` 和 `feedback`，路由到成功计数或 PM 分诊。

### 5.2 Function Calling Schema

```json
{
  "type": "function",
  "function": {
    "name": "submit_trial_result",
    "description": "提交试用结论。在询问用户是否满意并得到明确回复后调用。",
    "parameters": {
      "type": "object",
      "properties": {
        "success": {
          "type": "boolean",
          "description": "true = 用户确认结果符合预期；false = 用户反馈结果不对"
        },
        "feedback": {
          "type": "string",
          "description": "失败时用户的反馈内容（具体哪里不对）。成功时可不填。"
        }
      },
      "required": ["success"]
    }
  }
}
```

### 5.3 Orchestrator 端处理

```python
def _on_trial_completed(self, result: AgentResult, session_id: str, workflow_id: str) -> None:
    if result.signal_tool and result.signal_tool.name == "submit_trial_result":
        success = result.signal_tool.args["success"]
        feedback = result.signal_tool.args.get("feedback", "")

        from src.data.repositories import ToolRepository
        tool = ToolRepository().get_by_workflow_id(workflow_id)
        if not tool:
            emit("agent_error", sender=self,
                 workflow_id=workflow_id, session_id=session_id,
                 agent_type="trial", error="未找到工具", error_type="tool_not_found")
            return

        self.handle_trial_result(tool.tool_id, success, workflow_id, session_id, feedback)
    else:
        emit("agent_error", sender=self,
             workflow_id=workflow_id, session_id=session_id,
             agent_type="trial",
             error="试用 Agent 未通过 submit_trial_result 结束",
             error_type="unexpected_completion")
```

---

## 六、工具执行引擎

### 6.1 问题描述

程序员生成的工具代码格式为：

```python
async def execute(**kwargs) -> Dict[str, Any]:
    ...  # 可能使用 playwright.async_api
```

执行这类代码需要：
1. 异步执行（`asyncio`）
2. 允许 `playwright`、`requests` 等外部库
3. 超时控制（浏览器操作可能较慢）
4. 与现有 `execute_code`（数据探索，同步，不允许 playwright）**完全独立**

### 6.2 实现：ToolExecutor

新增 `src/execution/tool_executor.py`，不修改现有 `CodeExecutor`（v1 遗留组件，维持现状）。

```python
# src/execution/tool_executor.py

import asyncio
import json
import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)

_TOOL_TIMEOUT = 120  # 秒，浏览器操作预留充足时间


def run_tool_code(code: str, parameters: dict) -> dict:
    """
    执行工具代码，返回标准结果字典。

    工具代码格式：
        async def execute(**kwargs) -> Dict[str, Any]:
            return {"success": True/False, "message": "...", "data": ...}

    Args:
        code: 工具完整 Python 源码
        parameters: 传给 execute() 的参数字典

    Returns:
        {"success": bool, "message": str, "data": Any}
        执行失败时 success=False，message 包含错误信息
    """
    result_holder: dict[str, Any] = {"output": None, "error": None}

    def _run():
        try:
            # 编译并在独立命名空间执行，获得 execute 函数
            namespace: dict[str, Any] = {}
            exec(compile(code, "<tool>", "exec"), namespace)  # noqa: S102

            execute_fn = namespace.get("execute")
            if execute_fn is None:
                result_holder["error"] = "工具代码中未找到 execute 函数"
                return

            # 在新事件循环中运行（避免与主线程事件循环冲突）
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                output = loop.run_until_complete(execute_fn(**parameters))
                result_holder["output"] = output
            finally:
                loop.close()
                asyncio.set_event_loop(None)

        except Exception as e:
            result_holder["error"] = f"{type(e).__name__}: {e}"

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout=_TOOL_TIMEOUT)

    if thread.is_alive():
        return {
            "success": False,
            "message": f"工具执行超时（超过 {_TOOL_TIMEOUT} 秒）",
            "data": None,
        }

    if result_holder["error"]:
        logger.error(f"[ToolExecutor] 工具执行失败: {result_holder['error']}")
        return {
            "success": False,
            "message": result_holder["error"],
            "data": None,
        }

    output = result_holder["output"]

    # 兼容性处理：确保返回值符合标准格式
    if isinstance(output, dict):
        return output
    return {"success": True, "message": "执行完成", "data": output}
```

### 6.3 与 execute_code 的区别

| 维度 | execute_code（数据探索） | run_tool_code（工具执行） |
|------|------------------------|------------------------|
| 用途 | agent 临时探索录制数据 | 执行用户工具（正式运行） |
| 允许模块 | 数据处理模块（json/math/re 等） | playwright/requests + 数据模块 |
| 执行方式 | 同步 exec，捕获 stdout | 异步 asyncio，获取返回值 |
| 超时 | 30 秒 | 120 秒 |
| 沙箱 | 受限内建函数（无文件 I/O） | 不限制内建（代码已通过 syntax_check 审查） |
| 输出 | stdout 字符串 | `{"success", "message", "data"}` 字典 |

**沙箱说明**：工具代码在入库前已通过 `syntax_check`（AST 静态分析，禁止 eval/exec/open 等），且经过 LLM Review。不再在执行层重复限制内建函数，避免限制过多导致合法 playwright 操作受阻。

---

## 七、Orchestrator 集成

### 7.1 system prompt 注入

试用 Agent 的 system prompt 包含工具信息，**每个工具不同**，不能用全局 `TRIAL_CONFIG`。

Orchestrator 新增以下方法：

```python
def _build_trial_config(self, workflow_id: str) -> AgentConfig:
    """构建包含工具信息的试用 Agent 配置。"""
    from src.data.repositories import ToolRepository
    from src.business.agents.prompts.trial_prompt import (
        TRIAL_SYSTEM_PROMPT_TEMPLATE,
        format_parameters_text,
    )

    tool = ToolRepository().get_by_workflow_id(workflow_id)
    if not tool:
        raise ValueError(f"未找到 workflow_id={workflow_id} 对应的工具")

    parameters_text = format_parameters_text(tool.parameters or [])
    # 用手动替换而非 str.format()，防止 tool_name/description 内容含花括号时触发 KeyError
    system_prompt = (
        TRIAL_SYSTEM_PROMPT_TEMPLATE
        .replace("{tool_name}", tool.tool_name)
        .replace("{description}", tool.description or "（无描述）")
        .replace("{parameters_text}", parameters_text)
    )
    return AgentConfig(
        agent_type=AgentType.TRIAL,
        system_prompt=system_prompt,
        max_iterations=20,
    )
```

### 7.2 _get_loop 修改

试用 Agent 的 Loop 不缓存（每个 workflow 的 system prompt 不同）：

```python
def _get_loop(self, agent_type: str, workflow_id: str = None) -> AgentLoop:
    """获取 Loop 实例。trial agent 不缓存（system prompt 含工具信息，每个 workflow 不同）。"""
    if agent_type == "trial":
        config = self._build_trial_config(workflow_id)
        return AgentLoop(config, self._llm, self._config)

    # pm / programmer 按 agent_type 缓存
    if agent_type not in self._loops:
        configs = {"pm": PM_CONFIG, "programmer": PROGRAMMER_CONFIG}
        if agent_type not in configs:
            raise ValueError(f"[Orchestrator] 未知 Agent 类型: {agent_type}")
        self._loops[agent_type] = AgentLoop(configs[agent_type], self._llm, self._config)
    return self._loops[agent_type]
```

`run_agent` 调用 `_get_loop` 时同时传 `workflow_id`：

```python
loop = self._get_loop(agent_type, workflow_id=workflow_id)
```

### 7.3 _build_tools 补充

```python
def _build_tools(self, agent_type: str, workflow_id: str) -> List[ToolDefinition]:
    if agent_type == "pm":
        return create_recording_tools(workflow_id) + [submit_requirements, report_code_issue]
    elif agent_type == "programmer":
        return create_recording_tools(workflow_id) + [syntax_check, submit_code]
    elif agent_type == "trial":
        from src.business.agents.tools.trial_tools import create_trial_tools
        return create_trial_tools(workflow_id)
    return []
```

### 7.4 完整试用流程

```
UI 用户点击"试用"
  → bridge.start_agent("trial", "我想试用这个工具", recording_id)

Orchestrator.run_agent("trial", user_input, workflow_id)
  → _build_trial_config(workflow_id)  ← 从 DB 读取工具信息注入 prompt
  → _get_loop("trial", workflow_id)   ← 创建新 AgentLoop（不缓存）
  → _build_tools("trial", workflow_id) ← [execute_tool, submit_trial_result]
  → loop.run(session_id, user_input, tools=...)

试用 Agent 多轮对话：
  → talk_to_user("请问搜索关键词是什么？")
  → 用户回复 → loop.run(session_id, reply, tools=...)
  → execute_tool({"keyword": "Python 教程"})
  → talk_to_user("已获取 10 条搜索结果：[结果摘要]。请问结果是否符合预期？")
  → 用户回复 → loop.run(session_id, reply, tools=...)
  → submit_trial_result(success=True) 或 submit_trial_result(success=False, feedback="...")

_on_trial_completed → handle_trial_result
  → 成功：trial_success_count += 1，≥3 次则 published
  → 失败：PM 分诊
```

---

## 八、文件结构

```
src/
  execution/
    tool_executor.py             # run_tool_code()（新增）
    code_executor.py             # 旧版 CodeExecutor，保持不动

  business/agents/
    tools/
      trial_tools.py             # execute_tool + submit_trial_result（新增）
    prompts/
      trial_prompt.py            # TRIAL_SYSTEM_PROMPT_TEMPLATE + format_parameters_text（新增）
    config.py                    # TRIAL_CONFIG 保留（_build_trial_config 不依赖它）

  business/orchestration/
    agent_orchestrator.py        # 修改：_on_trial_completed / _get_loop / _build_tools
```

---

## 九、交互流程示例

### 9.1 正常试用（用户主动给参数）

```
用户：帮我搜 Python 教程
→ 试用 Agent 思考：用户给了 keyword="Python 教程"，result_count 有默认值 10，可以直接执行
→ 告知用户：正在执行，可能需要几十秒
→ execute_tool({"keyword": "Python 教程", "result_count": 10})
→ 结果：获取了 10 条结果
→ talk_to_user("已完成！获取到 10 条百度搜索结果，第一条是「xxx」。请问结果符合你的预期吗？")
→ 用户：符合
→ submit_trial_result(success=True)
```

### 9.2 引导式试用（用户只说"试用"）

```
用户：试一下
→ 试用 Agent 思考：缺少必填参数 keyword
→ talk_to_user("好的！这个工具会搜索百度并获取结果。请问你想搜索什么关键词？另外要获取几条结果（默认 10 条）？")
→ 用户：搜"机器学习"，要 5 条就够了
→ execute_tool({"keyword": "机器学习", "result_count": 5})
→ talk_to_user("已完成，获取了 5 条结果。[摘要展示] 请问符合预期吗？")
→ 用户：差不多，但我要的是中文结果，现在有英文的
→ submit_trial_result(success=False, feedback="结果中包含英文内容，用户需要只要中文搜索结果")
```

### 9.3 工具执行失败

```
→ execute_tool({"keyword": "test"})
→ 返回：{"success": False, "message": "TimeoutError: 页面加载超时", "data": None}
→ talk_to_user("工具执行遇到了技术问题（页面加载超时），这不是你输入的问题，已记录为试用失败，反馈会转给技术排查。")
→ submit_trial_result(success=False, feedback="工具执行报错：页面加载超时")
```

---

## 十、边界情况

### 10.1 工具代码中的 asyncio 兼容性

`run_tool_code` 在新线程中创建独立事件循环（`asyncio.new_event_loop()`），与主线程的 Qt 事件循环不冲突。工具内部如需嵌套 asyncio（如 `asyncio.run()`），会引发"event loop already running"——这是工具代码的问题，应在 syntax_check/review 阶段排除。

### 10.2 用户直接说"失败"

试用 Agent 应收集具体反馈，不接受"就是不对"这种泛泛回复：
```
用户：不对
→ talk_to_user("可以告诉我哪里不对吗？比如结果数量不对、内容不准确、还是工具报错了？")
```
反馈越具体，PM 分诊和程序员修复越精准。

### 10.3 execute_tool 多次调用

同一次试用 Agent 会话中，Agent 可以多次调用 `execute_tool`（如用户想换个参数再试一次）。每次调用都是独立执行，不影响 `trial_success_count`——计数只在 `submit_trial_result(success=True)` 时由 Orchestrator 更新。

### 10.4 工具代码被更新后的会话恢复

如果试用期间工具代码被更新（分诊后程序员修复），`execute_tool` handler 每次调用都从 DB 重新取代码（不缓存），自然获取到最新代码。

### 10.5 trial_success_count 在工具修改后清零

程序员修复并重新入库后，`_save_tool` 调用 `tool_repo.update()` 时会清零 `trial_success_count`（已在事件系统设计中定义）。试用 Agent 的下次试用从 0 重新计数。

---

## 十一、与架构 v2 的关系

### 一致的决策

- 试用成功 3 次后发布，工具修改后清零
- 失败 → PM 分诊（代码问题/需求问题）
- 试用通过对话进行（引导用户、提取参数、执行工具、展示结果）

### 本设计新增/细化的决策

| 决策 | 架构 v2 原文 | 本设计 |
|------|-------------|--------|
| 工具数量 | "引导用户、提取参数、执行工具、展示结果" | 2 个工具：execute_tool + submit_trial_result（+ 内置 talk_to_user） |
| 参数提取 | "从对话中提取参数" | Agent 在 execute_tool 的 parameters 字段中直接组装，不做单独的参数提取工具 |
| 执行机制 | 未明确 | ToolExecutor：新线程 + asyncio.new_event_loop()，120s 超时，不限制内建（代码已审查） |
| System prompt 注入 | 未明确 | Orchestrator 在 _build_trial_config 中从 DB 读取工具信息注入模板，不缓存 trial Loop |
| 试用结论提交 | "成功/失败" | submit_trial_result(success, feedback)，Orchestrator 从 signal_tool.args 获取 tool_id（通过 workflow_id 查 DB） |
| 多次执行 | 未明确 | execute_tool 可多次调用，计数只在 submit_trial_result(success=True) 时更新 |
| 录制数据工具 | 不需要 | 试用 Agent 不给录制数据工具，只给 execute_tool + submit_trial_result |
| 结果展示格式 | 未明确 | system prompt 里定义默认规则（列表取前3-5条+总数、操作类说成败、无数据明确告知）；ReACT Agent 不会主动追问展示偏好，需要默认规则兜底 |
| 用户预期管理 | 未明确 | 开场主动告知用户这是自动生成的工具，遇到问题很正常 |
| 反馈质量 | 未明确 | 用户反馈模糊时追问具体原因，收集可定位问题的描述后再提交 |
| 参数 description 语言 | 未明确 | 程序员 prompt 明确要求 description 用中文白话写（面向用户，试用 Agent 会直接读取） |

---

*基于架构 v2 细化，记录时间：2026-03-19*
