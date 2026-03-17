# 代码待办清单

---

## 🔴 高优先级：录制数据链路 BUG

### ~~BUG-1：sibling_snapshots 数据采集了但未入库~~ ✅ 已修复

**现象**：`sibling_snapshots` 表始终为空

**原因**：浏览器扩展 `content_script_isolated.js` 的 `captureSiblings(target)` 已经采集了兄弟元素数据，`browser_recorder.py` 的 `_convert_event_to_action_dict()` 也将其放入了 `action_dict["siblings_snapshot"]`，但 `_save_to_duckdb()` 中**从未调用 `save_sibling_snapshot()`**。

**涉及文件**：
- `src/recording/browser_recorder.py` — `_save_to_duckdb()` 方法，需在保存 actions 之后遍历每个 action，如果有 `siblings_snapshot` 则调用 `recording_repository.save_sibling_snapshot(action_id, siblings_snapshot, recording_id)`
- `src/data/recording_repository.py` — `save_sibling_snapshot()` 方法已实现，无需改动

**影响**：PM Agent 无法识别列表操作（v2 架构依赖此数据做启发式列表识别）

---

### 清理：废弃 list_contexts 相关代码

`list_contexts` 表是 v1 预处理架构的遗留产物（由 `ListOperationAnalyzer` 预计算"列表 DOM ↔ API 请求"的关联关系）。v2 架构中这类分析由 Agent 运行时自己完成，不需要预计算存储。

**需要删除的代码**：
- `src/data/duckdb_manager.py` — `list_contexts` 表的 CREATE TABLE 和索引
- `src/data/models_duckdb.py` — `ListContext` ORM 模型
- `src/data/recording_repository.py` — `save_list_context()` 和 `get_list_context()` 方法
- `src/data/duckdb_orm_manager.py` — 如果有 list_contexts 相关代码
- `src/business/ai/preprocessing/analyzers/list_analyzer.py` — `ListOperationAnalyzer` 整个文件（v1 遗留，v2 不使用）

---

### 补充说明：actions 表字段完整性

| 字段 | 浏览器录制 | 桌面录制 |
|---|---|---|
| dom_element | ✅ 有数据 | - |
| dom_tree_snapshot | ✅ 有数据 | - |
| visual_features | ✅ 有数据 | - |
| screenshot_before | ❌ 始终为空 | ✅ 有数据 |
| screenshot_after | ❌ 始终为空 | ✅ 有数据 |
| parameters | ✅ 有数据 | ✅ 有数据 |

浏览器录制模式下没有截图，PM 的多模态分析工具在浏览器录制场景无法使用。后续可考虑在浏览器扩展中增加截图采集（通过 `chrome.tabs.captureVisibleTab` 或 canvas 截图）。

---

## 🟡 中优先级：ToolSignal 重构

基于 agent_loop_design.md 和 pm_agent_design.md 的设计更新，现有代码需要以下改动。

---

## 一、设计变更摘要

**核心思想**：工具 handler 的返回值决定是否中断循环。返回 `str` → 正常继续；返回 `ToolSignal` → 循环中断。

- Loop 不再硬编码任何工具名（如 `talk_to_user`）
- `talk_to_user`、`submit_requirements`、`report_code_issue` 都是普通注册工具，只是 handler 返回 `ToolSignal`
- Orchestrator 通过 `AgentResult.signal_tool.name` 判断后续路由

---

## 二、逐文件改动清单

### 2.1 `src/business/agents/config.py`

**改动 1：新增 `ToolSignal` 和 `ToolDefinition` 数据类**

在 `RetryConfig` 之后添加：

```python
@dataclass
class ToolSignal:
    """
    工具信号 — 工具 handler 返回此类型时，AgentLoop 中断循环。

    普通工具返回 str，信号工具返回 ToolSignal。
    Loop 只做 isinstance 检查，不关心具体是哪个工具。
    """
    result_type: ResultType
    display_text: str = "[已提交]"


@dataclass
class ToolDefinition:
    """工具定义：FC schema + 实现函数的映射"""
    name: str
    schema: Dict[str, Any]
    handler: Callable[..., Union[str, ToolSignal]]
```

**改动 2：`AgentResult` 增加 `signal_tool` 字段**

```python
@dataclass
class AgentResult:
    """Agent 运行结果"""
    result_type: ResultType
    final_output: Optional[str] = None
    question: Optional[str] = None
    error: Optional[str] = None
    signal_tool: Optional[Any] = None  # ToolCallInfo，信号工具触发时携带工具调用信息
```

**改动 3：`__all__` 增加 `ToolSignal`**

---

### 2.2 `src/business/agents/tool_registry.py`

**改动：可废弃或简化**

全局注册表不再是工具管理的主要机制。工具通过 `ToolDefinition` 由 Orchestrator 组装后传入 `loop.run(tools=...)`。`tool_registry.py` 可保留做辅助用途（如工具发现），或直接废弃。

---

### 2.3 `src/business/agents/builtin_tools.py`

**改动：保留 schema 常量 + 增加 handler 函数**

`talk_to_user` 和 `load_reference` 仍然是内置工具，由 AgentLoop 自动追加。保留 schema 常量定义，增加 handler：

```python
from .config import ToolSignal, ResultType

# schema 保留不变
TALK_TO_USER_SCHEMA = { ... }  # 同现有代码
LOAD_REFERENCE_SCHEMA = { ... }  # 同现有代码

# 新增 handler
def talk_to_user(message: str) -> ToolSignal:
    return ToolSignal(
        result_type=ResultType.NEEDS_USER_INPUT,
        display_text="[等待用户回复]"
    )
```

---

### 2.4 `src/business/agents/agent_loop.py`

**改动 1：`run()` 方法增加 `tools` 参数**

```python
def run(self, session_id: str, user_input: Optional[str] = None, tools: Optional[List[ToolDefinition]] = None) -> AgentResult:
```

**改动 2：工具列表由传入的 tools + 内置工具组成**

```python
# 现在
all_tool_schemas = get_tool_schemas() + [TALK_TO_USER_SCHEMA, LOAD_REFERENCE_SCHEMA]

# 改为
tools = tools or []
all_tool_schemas = [td.schema for td in tools] + [TALK_TO_USER_SCHEMA, LOAD_REFERENCE_SCHEMA]
tool_handlers = {td.name: td.handler for td in tools}
tool_handlers["talk_to_user"] = talk_to_user
```

**改动 3：移除硬编码 `talk_to_user` 检查（第 242-253 行）**

现在的代码：
```python
# 检查 talk_to_user
if tool_call.name == "talk_to_user":
    ctx.save_tool_result(
        tool_call_id=tool_call.id, tool_name="talk_to_user", content="[等待用户回复]"
    )
    ctx.update_session_status("suspended")
    question = tool_call.args.get("message", "")
    logger.info(f"[Agent Loop] 需要用户输入: {question[:50]}...")
    return AgentResult(
        result_type=ResultType.NEEDS_USER_INPUT,
        question=question,
    )
```

改为统一的 ToolSignal 检查：
```python
# 执行工具（统一路径，不区分内置/注册）
try:
    if tool_call.name == "load_reference":
        result = ctx.load_reference(tool_call.args["message_id"])
    else:
        handler = tool_handlers.get(tool_call.name)
        if handler is None:
            result = f"错误：未知工具 '{tool_call.name}'"
        else:
            result = handler(**tool_call.args)

    # 检查是否为 ToolSignal
    if isinstance(result, ToolSignal):
        ctx.save_tool_result(
            tool_call_id=tool_call.id,
            tool_name=tool_call.name,
            content=result.display_text,
        )
        if result.result_type == ResultType.NEEDS_USER_INPUT:
            ctx.update_session_status("suspended")
            return AgentResult(
                result_type=ResultType.NEEDS_USER_INPUT,
                question=tool_call.args.get("message", ""),
                signal_tool=tool_call,
            )
        else:
            ctx.update_session_status("completed")
            return AgentResult(
                result_type=result.result_type,
                signal_tool=tool_call,
            )

    # 普通工具结果
    ctx.save_tool_result(
        tool_call_id=tool_call.id,
        tool_name=tool_call.name,
        content=result,
    )

except Exception as e:
    # ... 错误处理不变 ...
```

**改动 4：导入 `ToolSignal`**

```python
from .config import AgentConfig, AgentResult, ResultType, RetryConfig, ToolSignal
```

---

### 2.5 PM Agent 工具（新增文件）

**`src/business/agents/tools/pm_output.py`**（导出 `ToolDefinition` 实例，handler 返回 ToolSignal）

schema 定义详见 pm_agent_design.md 第六、七节。此处只列 handler：

```python
def _submit_requirements(**kwargs) -> ToolSignal:
    return ToolSignal(result_type=ResultType.COMPLETED, display_text="[需求已提交]")

def _report_code_issue(feedback: str) -> ToolSignal:
    return ToolSignal(result_type=ResultType.COMPLETED, display_text="[代码问题已报告]")

submit_requirements = ToolDefinition(name="submit_requirements", schema=SUBMIT_REQUIREMENTS_SCHEMA, handler=_submit_requirements)
report_code_issue = ToolDefinition(name="report_code_issue", schema=REPORT_CODE_ISSUE_SCHEMA, handler=_report_code_issue)
```

---

### 2.6 `src/business/orchestrator/agent_orchestrator.py`

**改动 1：组装工具列表并传入 `run()`**

```python
from src.business.agents.tools.pm_output import submit_requirements, report_code_issue
# ... 其他工具 import

PM_TOOLS = [pm_query_recording_data, multimodal_analysis, submit_requirements, report_code_issue]
loop.run(session_id, user_input, tools=PM_TOOLS)
```

**改动 2：路由逻辑**

```python
if result.signal_tool and result.signal_tool.name == "submit_requirements":
    requirements = result.signal_tool.args
elif result.signal_tool and result.signal_tool.name == "report_code_issue":
    feedback = result.signal_tool.args["feedback"]
```

---

## 三、`load_reference` 的处理

`load_reference` 需要 `ctx`（ContextManager），不适合做成外部传入的 ToolDefinition。

**方案：保持现状**。`load_reference` 仍在 agent_loop.py 中特殊处理（`if tool_call.name == "load_reference"`），schema 由 Loop 自动追加。这只是内部实现细节，不影响 ToolSignal 机制。

---

## 四、改动顺序

1. `config.py` — 新增 ToolSignal 和 ToolDefinition，修改 AgentResult，AgentConfig 删除 tools 字段
2. `builtin_tools.py` — 保留 schema 常量，增加 talk_to_user handler（返回 ToolSignal）
3. `agent_loop.py` — run() 增加 tools 参数，移除硬编码 talk_to_user，统一 isinstance 检查
4. PM 工具文件 — pm_output.py 导出 ToolDefinition 实例
5. Orchestrator — 组装 PM_TOOLS 传入 run()，使用 signal_tool 路由
6. `tool_registry.py` — 可选：简化或废弃（不再是工具管理的核心机制）

---

## 五、涉及的测试

- `tests/test_agent_loop.py` — 需更新 talk_to_user 相关测试用例
- 新增 ToolSignal 单元测试
- 新增 PM 工具的测试（submit_requirements 返回 ToolSignal）
- Orchestrator 路由测试

---

*基于 agent_loop_design.md 第 3.2.1 节和 pm_agent_design.md 更新，记录时间：2026-03-17*
