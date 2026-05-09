# Agent Loop 核心设计

本文档为架构 v2 的 Agent Loop 细化设计，定义循环核心、LLM 客户端扩展、Agent 配置、用户交互机制及返回值结构。

依赖：[数据层设计](data_layer_design.md)、[记忆机制设计](memory_mechanism_design.md)

---

## 一、整体定位

Agent Loop 是三个 Agent（PM、程序员、试用）共用的运行时引擎。它是一个纯粹的同步循环，只负责驱动 LLM 调用、工具执行，不感知 UI 和事件系统。

```
UI 层（PyQt）
    ↓ 用户操作 / 用户回复
AgentUIBridge（优先级 4）
    ↓ 线程管理、PyQt 信号桥接
AgentOrchestrator（优先级 4）
    ↓ session 创建、Agent 选择、事件发送
    ↓ AgentLoop.run(session_id, user_input, tools)
    ↑ 返回 AgentResult
AgentLoop（本模块）
    ↓ assemble_context() / save_*()    ↓ chat_with_tools()
ContextManager（记忆层）            LangChainLLMClient（LLM 客户端）
    ↓                                  ↓
MessageRepository / SessionRepository    Anthropic / OpenAI API
    ↓
SQLite
```

**AgentLoop 上方的两层（优先级 4 设计）**：

| 层 | 职责 | 关注点 |
|----|------|--------|
| **AgentUIBridge** | 后台线程运行 Loop、AgentResult 转 PyQt 信号、接收用户回复 | UI 框架相关 |
| **AgentOrchestrator** | 创建 session、选择 AgentConfig、根据 AgentResult 发事件、Agent 间调度 | 业务流程 |

拆成两层的原因：改编排逻辑不影响 UI 桥接，换 UI 框架不影响编排逻辑。

**关键原则**：

- Agent Loop 自身不知道事件系统和 UI 的存在——它只负责运行循环、返回结果
- AgentOrchestrator 根据 AgentResult 决定是否发事件、启动下一个 Agent
- AgentUIBridge 负责线程管理和 PyQt 信号转换
- 三个 Agent 共用同一个 `AgentLoop` 类，通过 `AgentConfig` 区分行为

---

## 二、LLM 客户端扩展

### 2.1 新增数据结构

在 `src/business/ai/llm_client.py` 中新增：

```python
@dataclass
class ToolCallInfo:
    """单个工具调用信息"""
    id: str               # 工具调用 ID（如 "call_abc123"）
    name: str             # 工具名称（如 "query_recording_data"）
    args: Dict[str, Any]  # 工具参数


@dataclass
class LLMResponse:
    """LLM 响应的统一封装"""
    content: Optional[str]           # 文本内容（可能为 None）
    tool_calls: List[ToolCallInfo]   # 工具调用列表（单工具模式下最多一个元素）

    @property
    def has_tool_calls(self) -> bool:
        return len(self.tool_calls) > 0
```

**设计说明**：
- `LLMResponse` 是 Agent Loop 与 LLM 之间的唯一契约，Loop 代码不接触任何 LangChain 内部类型
- `ToolCallInfo.id` 由 LLM 生成，后续保存为 `tool_call_id`，用于 tool result 消息与 tool_call 的配对
- `content` 可能为 `None`（当 LLM 只返回 tool_calls 时），Agent Loop 保存时统一处理为空字符串
- 保留 `tool_calls` 为列表类型（而非单个对象）以兼容 LangChain 返回格式，但在单工具调用模式下始终只有 0 或 1 个元素

### 2.2 chat_with_tools 方法

在 `LangChainLLMClient` 上新增方法：

```python
def chat_with_tools(
    self,
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    **kwargs
) -> LLMResponse:
    """
    发送带工具定义的对话请求

    Args:
        messages: 消息列表，格式为 ContextManager.assemble_context() 的输出
                  支持 role: system/user/assistant/tool
        tools: 工具定义列表，每个元素为 Function Calling schema
        **kwargs: 额外参数

    Returns:
        LLMResponse，包含文本内容和/或工具调用（最多一个 tool_call）

    内部流程：
    1. 将 dict 消息转换为 LangChain 消息对象
    2. 用 self.llm.bind_tools(tools, parallel_tool_calls=False) 绑定工具定义
       强制单工具调用模式，每次响应最多返回一个 tool_call
    3. 调用 invoke 获取响应
    4. 从响应中提取 content 和 tool_calls，封装为 LLMResponse
    """
```

### 2.3 消息格式转换

`chat_with_tools` 内部需要将 dict 消息（来自 `ContextManager.assemble_context()`）转换为 LangChain 消息对象。相比现有的 `chat_with_messages` 方法，新增了对 `tool` 角色和 `assistant` 消息中 `tool_calls` 字段的处理：

```python
def _convert_to_langchain_messages(self, messages: List[Dict[str, Any]]) -> List:
    """
    将 dict 消息转换为 LangChain 消息对象

    处理的角色：
    - system → SystemMessage
    - user → HumanMessage
    - assistant → AIMessage（可能包含 tool_calls）
    - tool → ToolMessage（必须包含 tool_call_id）
    """
    from langchain_core.messages import (
        HumanMessage, AIMessage, SystemMessage, ToolMessage
    )

    lc_messages = []
    for msg in messages:
        role = msg["role"]
        content = msg.get("content", "")

        if role == "system":
            lc_messages.append(SystemMessage(content=content))
        elif role == "user":
            lc_messages.append(HumanMessage(content=content))
        elif role == "assistant":
            if "tool_calls" in msg and msg["tool_calls"]:
                lc_messages.append(AIMessage(
                    content=content or "",
                    tool_calls=msg["tool_calls"]
                ))
            else:
                lc_messages.append(AIMessage(content=content))
        elif role == "tool":
            lc_messages.append(ToolMessage(
                content=content,
                tool_call_id=msg["tool_call_id"],
                name=msg.get("name", "")
            ))

    return lc_messages
```

### 2.4 响应提取

从 LangChain 的 `AIMessage` 响应中提取 `LLMResponse`：

```python
def _extract_response(self, ai_message) -> LLMResponse:
    """
    从 LangChain AIMessage 提取统一响应

    LangChain 的 AIMessage.tool_calls 格式（已标准化）：
    [{"id": "call_xxx", "name": "tool_name", "args": {...}}, ...]

    Anthropic 和 OpenAI 提供商经过 LangChain 适配后格式一致，
    不需要 Agent Loop 关心提供商差异。
    """
    tool_calls = []
    if hasattr(ai_message, 'tool_calls') and ai_message.tool_calls:
        for tc in ai_message.tool_calls:
            tool_calls.append(ToolCallInfo(
                id=tc["id"],
                name=tc["name"],
                args=tc["args"]
            ))

    return LLMResponse(
        content=ai_message.content if ai_message.content else None,
        tool_calls=tool_calls
    )
```

### 2.5 工具定义格式

工具定义传入 `chat_with_tools` 时使用标准 Function Calling schema。`bind_tools()` 会自动转换：

```python
# 示例工具定义
{
    "type": "function",
    "function": {
        "name": "query_recording_data",
        "description": "查询录制数据...",
        "parameters": {
            "type": "object",
            "properties": {
                "recording_id": {"type": "string", "description": "录制 ID"},
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "要查询的字段列表"
                }
            },
            "required": ["recording_id"]
        }
    }
}
```

### 2.6 提供商兼容性

LangChain 的 `ChatAnthropic` 和 `ChatOpenAI` 都支持 `bind_tools()` 方法，并且返回的 `AIMessage.tool_calls` 已经被 LangChain 标准化为统一格式。因此 `chat_with_tools` 不需要针对不同提供商做特殊处理。这是选择在 LangChain 之上扩展而非直接调用 API 的主要原因。

---

## 三、AgentConfig 配置

### 3.1 数据结构

```python
# src/business/agents/config.py

from dataclasses import dataclass, field
from typing import List, Dict, Any, Callable, Optional, Union
from enum import Enum


class AgentType(str, Enum):
    PM = "pm"
    PROGRAMMER = "programmer"
    TRIAL = "trial"


@dataclass
class RetryConfig:
    """LLM 调用重试配置

    任何异常都会触发重试（基于线性退避）。不再按错误关键词区分可重试/不可重试——
    早期的字符串白名单几乎匹配不到 LangChain/SDK 包装后的真实异常文本，等价于关闭。
    """
    max_retries: int = 3      # 最大重试次数
    retry_delay: float = 1.0  # 退避基数；实际延迟 = retry_delay * (retry_count + 1)


@dataclass
class ToolDefinition:
    """工具定义：FC schema + 实现函数的映射"""
    name: str                      # 工具名称，必须与 schema 中的 name 一致
    schema: Dict[str, Any]         # Function Calling schema（传给 LLM）
    handler: Callable[..., Union[str, 'ToolSignal']]  # 实现函数（执行时调用）


@dataclass
class AgentConfig:
    """Agent 配置"""
    agent_type: AgentType
    system_prompt: str             # system prompt 模板
    max_iterations: int = 50       # 最大迭代次数
    retry: RetryConfig = field(default_factory=RetryConfig)  # LLM 调用重试配置
```

注意：`AgentConfig` 不再包含 `tools` 字段。工具列表通过 `AgentLoop.run()` 的 `tools` 参数从外部传入（见 4.1 节）。

### 3.2 ToolDefinition 设计说明

`ToolDefinition` 将 Function Calling schema 和 Python 实现函数绑在一起：

- `schema` — 发送给 LLM 的工具描述（名称、描述、参数 JSON Schema）
- `handler` — Agent Loop 执行工具时调用的 Python 函数，签名为 `(**kwargs) -> Union[str, ToolSignal]`
- `name` — 用于 dispatch 匹配，必须与 `schema["function"]["name"]` 一致

工具 handler 的返回值决定 Loop 行为：
- 返回 `str` → 普通工具结果，Loop 继续迭代
- 返回 `ToolSignal` → Loop 中断，按 `ToolSignal.result_type` 返回 AgentResult

**工具由调用方组装，通过 `run()` 参数传入 Loop**。Loop 不关心工具从哪来，只负责发给 LLM + 按名字执行 handler。这样 PM 和程序员可以各自传入不同的 `query_recording_data`（不同 schema 和 handler），互不干扰，不需要全局注册表或命名冲突处理。

### 3.2.1 ToolSignal

```python
@dataclass
class ToolSignal:
    """工具返回此类型时，Loop 中断并返回对应的 AgentResult。"""
    result_type: ResultType            # 中断后返回什么类型
    display_text: str = "[已提交]"     # 存入消息历史的占位文本
```

这是工具与 Loop 之间的唯一协议。Loop 不关心工具叫什么名字，只看返回值类型。

### 3.3 内置工具

两个内置工具所有 Agent 共享，由 AgentLoop 自动追加到传入的工具列表中：

```python
# --- talk_to_user ---

TALK_TO_USER_SCHEMA = {
    "type": "function",
    "function": {
        "name": "talk_to_user",
        "description": "向用户提问或展示信息。当你需要用户确认、提供额外信息、或展示分析结果时调用此工具。",
        "parameters": {
            "type": "object",
            "properties": {
                "message": {
                    "type": "string",
                    "description": "要展示给用户的消息或问题"
                }
            },
            "required": ["message"]
        }
    }
}

def talk_to_user(message: str) -> ToolSignal:
    """talk_to_user 的 handler：返回 ToolSignal 中断循环"""
    return ToolSignal(
        result_type=ResultType.NEEDS_USER_INPUT,
        display_text="[等待用户回复]"
    )


# --- load_reference ---

LOAD_REFERENCE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "load_reference",
        "description": "加载之前被归档的工具返回结果的原始数据。当你需要回看之前工具调用的详细数据时使用。",
        "parameters": {
            "type": "object",
            "properties": {
                "message_id": {
                    "type": "string",
                    "description": "引用ID，从 [REF::xxx] 标记中获取"
                }
            },
            "required": ["message_id"]
        }
    }
}
```

`talk_to_user` 的 handler 返回 `ToolSignal`，与业务工具（如 `submit_requirements`）使用同一套机制。Loop 中没有对 `talk_to_user` 的硬编码判断。

`load_reference` 仍然是普通工具（返回 `str`），由 `_execute_tool` 委托给 ContextManager。

### 3.4 三个 Agent 的配置

```python
# src/business/agents/config.py

PM_CONFIG = AgentConfig(
    agent_type=AgentType.PM,
    system_prompt="...",  # 优先级 5 定义，此处为占位
    max_iterations=50,
)

PROGRAMMER_CONFIG = AgentConfig(
    agent_type=AgentType.PROGRAMMER,
    system_prompt="...",  # 优先级 6 定义
    max_iterations=30,
)

TRIAL_CONFIG = AgentConfig(
    agent_type=AgentType.TRIAL,
    system_prompt="...",  # 优先级 7 定义
    max_iterations=20,
)
```

AgentConfig 只包含 prompt 和循环控制参数。工具列表由 Orchestrator 在启动 Agent 时组装并传入 `run()`：

```python
# src/business/orchestrator/agent_orchestrator.py

from src.business.agents.tools.pm_recording_query import pm_query_recording_data
from src.business.agents.tools.multimodal_analysis import multimodal_analysis
from src.business.agents.tools.pm_output import submit_requirements, report_code_issue

PM_TOOLS = [
    pm_query_recording_data,
    multimodal_analysis,
    submit_requirements,
    report_code_issue,
    # talk_to_user 和 load_reference 由 AgentLoop 自动追加
]

# 启动 PM
loop.run(session_id, user_input, tools=PM_TOOLS)
```

**为什么工具在外部组装**：PM 和程序员各自有独立版本的 `query_recording_data`（不同 schema、不同 handler），如果放在 config 或全局注册表中会有命名冲突。由 Orchestrator 组装后传入，各 Agent 的工具列表完全独立。

**System prompt 说明**：当前阶段 system prompt 为占位符。实际 prompt 内容在优先级 5-7 的各 Agent 设计中定义。Agent Loop 只负责将 `config.system_prompt` 作为第一条消息存入会话。

---

## 四、AgentLoop 核心

### 4.1 类定义

```python
# src/business/agents/agent_loop.py

import time
import json
import logging

logger = logging.getLogger(__name__)


class AgentLoop:
    """
    Agent 运行循环

    三个 Agent 共用此类，通过 AgentConfig 区分行为。
    每次调用 run() 执行一轮循环（直到需要用户输入、完成或出错）。
    """

    def __init__(self, config: AgentConfig, llm_client: LangChainLLMClient, unified_config: UnifiedConfigManager):
        self._config = config
        self._llm = llm_client
        self._unified_config = unified_config

    def run(
        self,
        session_id: str,
        user_input: Optional[str] = None,
        tools: Optional[List[ToolDefinition]] = None,
    ) -> AgentResult:
        """
        执行 Agent 循环

        Args:
            session_id: 会话 ID
            user_input: 用户输入（首次启动时为初始输入，恢复时为用户回复）
                        为 None 时表示无需新增用户消息（如系统触发的重新运行）
            tools: 工具列表（由调用方组装传入）。为 None 时只有内置工具可用。

        Returns:
            AgentResult，包含循环结束原因和相关数据
        """
```

### 4.2 核心循环逻辑

采用**单工具调用模式**（`parallel_tool_calls=False`），每次 LLM 响应最多包含一个 tool_call。这消除了多工具调用的所有边界问题（如 talk_to_user 与其他工具同时出现时的处理、跳过未执行工具导致 tool_call/tool_result 配对错误等）。

```python
def run(self, session_id: str, user_input: Optional[str] = None, tools: Optional[List[ToolDefinition]] = None) -> AgentResult:
    ctx = ContextManager(session_id)

    # 如果是新会话（还没有 system prompt），初始化
    if not self._has_system_prompt(session_id):
        ctx.save_message(role="system", content=self._config.system_prompt)

    # 恢复会话时（suspended 或 completed 复用），将状态更新为 active
    if ctx.get_session_status() in ("suspended", "completed"):
        ctx.update_session_status("active")

    # 保存用户输入（如果有）
    if user_input is not None:
        ctx.save_user_message(user_input)

    # 构建工具列表（传入的 tools + 内置 tools）
    all_tool_schemas = self._build_tool_schemas(tools or [])
    tool_handlers = self._build_tool_handlers(tools or [])

    iteration = 0
    while iteration < self._config.max_iterations:
        iteration += 1

        # 1. 组装上下文
        messages = ctx.assemble_context()

        # 2. 调用 LLM（带重试）
        response = self._call_llm_with_retry(messages, all_tool_schemas, ctx)
        if response is None:
            # LLM 调用失败（已记录日志和更新 status），直接返回错误
            return AgentResult(
                result_type=ResultType.ERROR,
                error="LLM 调用失败（重试次数耗尽或不可重试错误）"
            )

        # 3. 保存 assistant 消息
        ctx.save_assistant_message(
            content=response.content or "",
            tool_calls=json.dumps([
                {"id": tc.id, "name": tc.name, "args": tc.args}
                for tc in response.tool_calls
            ]) if response.has_tool_calls else None
        )

        # 4. 如果没有工具调用，循环结束
        if not response.has_tool_calls:
            ctx.update_session_status("completed")
            return AgentResult(
                result_type=ResultType.COMPLETED,
                final_output=response.content
            )

        # 5. 执行单个工具调用（parallel_tool_calls=False 保证最多一个）
        tool_call = response.tool_calls[0]

        # 执行工具（普通工具或 load_reference）
        result = self._execute_tool(tool_call, ctx, tool_handlers)

        # 6. 检查返回值类型
        if isinstance(result, ToolSignal):
            # 工具要求中断循环
            ctx.save_tool_result(
                tool_call_id=tool_call.id,
                tool_name=tool_call.name,
                content=result.display_text
            )
            status = "suspended" if result.result_type == ResultType.NEEDS_USER_INPUT else "completed"
            ctx.update_session_status(status)
            return AgentResult(
                result_type=result.result_type,
                question=tool_call.args.get("message") if result.result_type == ResultType.NEEDS_USER_INPUT else None,
                final_output=None,
                signal_tool=tool_call
            )

        # 普通工具结果，保存并继续迭代
        ctx.save_tool_result(
            tool_call_id=tool_call.id,
            tool_name=tool_call.name,
            content=result
        )

        # 继续下一轮迭代

    # 超过最大迭代次数
    ctx.update_session_status("failed")
    return AgentResult(
        result_type=ResultType.MAX_ITERATIONS_REACHED,
        error=f"超过最大迭代次数 ({self._config.max_iterations})"
    )
```

### 4.3 工具执行

```python
def _execute_tool(
    self,
    tool_call: ToolCallInfo,
    ctx: ContextManager,
    tool_handlers: Dict[str, Callable]
) -> Union[str, ToolSignal]:
    """
    执行单个工具调用

    Returns:
        str — 普通工具结果，Loop 继续迭代
        ToolSignal — 工具要求中断循环

    处理顺序：
    1. load_reference → 委托给 ContextManager（返回 str）
    2. 已注册的工具 → 调用 handler（可能返回 str 或 ToolSignal）
    3. 未知工具 → 返回错误信息（返回 str）
    """
    try:
        if tool_call.name == "load_reference":
            return ctx.load_reference(tool_call.args["message_id"])

        handler = tool_handlers.get(tool_call.name)
        if handler is None:
            return f"错误：未知工具 '{tool_call.name}'"

        return handler(**tool_call.args)

    except Exception as e:
        logger.error(f"[AgentLoop] 工具执行失败: {tool_call.name}, 错误: {e}")
        return f"工具执行出错: {tool_call.name} - {str(e)}"
```

**关键设计**：
- 工具执行失败时**不终止循环**，而是将错误信息作为 tool result 返回给 LLM。LLM 看到错误后可以选择重试、调整参数或直接告诉用户。这与架构 v2"复杂度在 Agent 能力上"的原则一致。
- Loop 不关心工具叫什么名字，只看返回值是 `str` 还是 `ToolSignal`。哪些工具是"中断型"的，由工具 handler 自己决定。

### 4.4 工具列表构建

```python
def _build_tool_schemas(self, tools: List[ToolDefinition]) -> List[Dict[str, Any]]:
    """构建发给 LLM 的完整工具定义列表（传入的 + 内置的）"""
    schemas = [td.schema for td in tools]
    schemas.append(TALK_TO_USER_SCHEMA)
    schemas.append(LOAD_REFERENCE_SCHEMA)
    return schemas

def _build_tool_handlers(self, tools: List[ToolDefinition]) -> Dict[str, Callable]:
    """构建工具名称到 handler 的映射"""
    handlers = {}
    for td in tools:
        handlers[td.name] = td.handler
    # talk_to_user 也通过 handler 注册（返回 ToolSignal）
    handlers["talk_to_user"] = talk_to_user
    # load_reference 不在 handlers 中，由 _execute_tool 特殊处理（需要 ctx）
    return handlers

def _call_llm_with_retry(
    self,
    messages: List[Dict],
    tool_schemas: List[Dict],
    ctx: ContextManager
) -> Optional[LLMResponse]:
    """
    调用 LLM，带重试机制

    所有异常都会触发重试（最多 max_retries 次），采用线性退避：
    delay = retry_delay * (retry_count + 1)。

    Returns:
        LLMResponse，失败时返回 None（调用者需检查）
    """
    for retry_count in range(self._config.retry.max_retries + 1):
        try:
            return self._llm.chat_with_tools(messages, tool_schemas)
        except Exception as e:
            if retry_count >= self._config.retry.max_retries:
                logger.error(f"[AgentLoop] LLM 调用最终失败: {e}")
                ctx.update_session_status("failed")
                return None
            delay = self._config.retry.retry_delay * (retry_count + 1)
            logger.warning(f"[AgentLoop] LLM 调用失败，{delay}秒后重试（{retry_count + 1}/{self._config.retry.max_retries}）: {e}")
            time.sleep(delay)

def _has_system_prompt(self, session_id: str) -> bool:
    """检查会话是否已有 system prompt（轻量查询，不触发压缩和引用替换）"""
    msg_repo = MessageRepository()
    first_msg = msg_repo.get_first(session_id)
    return first_msg is not None and first_msg.role == "system"
```

---

## 五、用户交互机制

### 5.1 talk_to_user 的工作原理

`talk_to_user` 是一个 handler 返回 `ToolSignal` 的工具。当 LLM 调用它时，handler 返回 `ToolSignal(result_type=NEEDS_USER_INPUT)`，Loop 检测到后中断循环。

这与业务工具（如 PM 的 `submit_requirements`）使用完全相同的机制——Loop 不知道 `talk_to_user` 是"特殊"的，它只看到返回值是 `ToolSignal`。

### 5.2 循环生命周期

```
AgentOrchestrator               AgentLoop                    ContextManager
  │                               │                              │
  │ ── run(session_id, input) ──→ │                              │
  │                               │ ── save_user_message() ────→ │
  │                               │                              │
  │                               │ ←── while loop ──→           │
  │                               │   assemble_context()         │
  │                               │   chat_with_tools()          │
  │                               │   execute tools              │
  │                               │   save results               │
  │                               │   ...                        │
  │                               │   LLM calls talk_to_user     │
  │                               │                              │
  │ ←── AgentResult(NEEDS_...) ── │                              │
  │                               │                              │
  │    [用户在 UI 中回复]           │                              │
  │                               │                              │
  │ ── run(session_id, reply) ──→ │                              │
  │                               │ ── save_user_message() ────→ │
  │                               │                              │
  │                               │ ←── while loop ──→           │
  │                               │   ...（继续）                 │
```

### 5.3 AgentOrchestrator 的使用模式

```python
# AgentOrchestrator 内部逻辑（优先级 4 设计）

# 启动新会话
session = session_repo.create(workflow_id=wf_id, agent_type="pm")
loop = AgentLoop(config=PM_CONFIG, llm_client=llm, unified_config=unified_config)

# 首次运行
result = loop.run(session.session_id, user_input="用户的初始输入")

if result.result_type == ResultType.NEEDS_USER_INPUT:
    # 通过 AgentUIBridge 将 result.question 展示给用户
    # 用户回复后 AgentUIBridge 回调 Orchestrator
    result = loop.run(session.session_id, user_input=user_reply)

elif result.result_type == ResultType.COMPLETED:
    # 根据 Agent 类型发事件，触发下一个 Agent
    emit("requirement_confirmed", ...)
```

---

## 六、会话生命周期

### 6.1 创建新会话

**AgentOrchestrator** 负责创建会话，`AgentLoop.run()` 接收 `session_id`：

```python
# 由 AgentOrchestrator 完成
session = session_repo.create(
    session_id=str(uuid.uuid4()),
    workflow_id=workflow_id,
    agent_type=config.agent_type.value,
    status="active"
)
result = loop.run(session.session_id, user_input="...")
```

AgentLoop 检测到会话中没有 system prompt 时自动初始化。

### 6.2 恢复已暂停的会话

用户回复后，AgentOrchestrator 用相同的 `session_id` 再次调用 `run()`：

```python
# talk_to_user 导致 loop 返回后，session status 为 "suspended"
# 用户回复后：
result = loop.run(session_id, user_input=user_reply)
# run() 内部：
# 1. 检测到已有 system prompt，不重复初始化
# 2. 检测到 status="suspended"，更新为 "active"
# 3. 保存新的 user message → 进入 while 循环
```

**状态转换**：
```
active → (run 中) → suspended（遇到 talk_to_user）
suspended → (run 恢复，自动改为 active) → completed / suspended / failed
completed → (复用 session，自动改为 active) → completed / suspended / failed
```

**Session 复用原则**：一个 workflow + 一个 agent type = 一个 session。completed 的 session 会被 Orchestrator 复用（如 review 打回、分诊回来），AgentLoop 检测到 completed 状态时更新为 active 后继续运行。

### 6.3 会话完成

当 LLM 不调用任何工具时，Loop 自然结束，session status 设为 `"completed"`。AgentOrchestrator 根据 `AgentResult` 决定后续操作（如发事件触发下一个 Agent）。

### 6.4 会话失败

两种失败场景：
- **LLM 调用异常** — 网络错误、API 限流等。session status 设为 `"failed"`，返回 `ResultType.ERROR`
- **超过最大迭代次数** — session status 设为 `"failed"`，返回 `ResultType.MAX_ITERATIONS_REACHED`

AgentOrchestrator 的处理：
- 发 `agent_error` 事件，记录错误日志，通知用户
- failed 的 session 不复用（可能有未配对的 tool_call 等脏数据），下次 `_get_or_create_session` 会创建新 session

---

## 七、AgentResult 返回值

### 7.1 数据结构

```python
# src/business/agents/agent_loop.py

class ResultType(str, Enum):
    """Agent 循环结束原因"""
    NEEDS_USER_INPUT = "needs_user_input"     # 需要用户输入
    COMPLETED = "completed"                    # 任务完成
    ERROR = "error"                            # 发生错误
    MAX_ITERATIONS_REACHED = "max_iterations"  # 超过最大迭代次数


@dataclass
class AgentResult:
    """Agent 循环的返回值"""
    result_type: ResultType

    # NEEDS_USER_INPUT 时有值
    question: Optional[str] = None

    # COMPLETED 时有值（自然结束时为 LLM 最后文本，tool_signal 触发时为 None）
    final_output: Optional[str] = None

    # tool_signal 工具触发时有值（携带工具名和结构化参数）
    signal_tool: Optional[ToolCallInfo] = None

    # ERROR / MAX_ITERATIONS_REACHED 时有值
    error: Optional[str] = None
```

### 7.2 各层的处理

| ResultType | AgentOrchestrator（编排） | AgentUIBridge（UI 桥接） |
|------------|--------------------------|-------------------------|
| `NEEDS_USER_INPUT` | 记录会话状态，等待用户回复后再次调用 `run()` | 将 `question` 通过 PyQt 信号发给 UI 展示 |
| `COMPLETED` | 检查 `signal_tool` 决定后续操作（见 7.3） | 通知 UI 任务完成 |
| `ERROR` | 记录错误，决定是否重试 | 通知 UI 展示错误信息 |
| `MAX_ITERATIONS_REACHED` | 记录异常 | 通知 UI 任务可能过于复杂 |

### 7.3 COMPLETED 的两种来源

Loop 返回 `COMPLETED` 有两种情况：

**自然结束**：LLM 不调用任何工具。`final_output` 有值，`signal_tool` 为 None。这是兜底路径——正常流程中 Agent 应通过 tool_signal 工具结束。

**tool_signal 工具触发**：工具 handler 返回 `ToolSignal`。`signal_tool` 有值（携带工具名和结构化参数），`final_output` 为 None。Orchestrator 通过 `signal_tool.name` 和 `signal_tool.args` 获取结构化数据并路由。

```python
# Orchestrator 中的处理示例
if result.result_type == ResultType.COMPLETED:
    if result.signal_tool:
        # tool_signal 触发：从工具参数获取结构化数据
        if result.signal_tool.name == "submit_requirements":
            requirements = result.signal_tool.args
            emit("requirement_confirmed", ...)
        elif result.signal_tool.name == "report_code_issue":
            emit("triage_completed", feedback=result.signal_tool.args["feedback"], ...)
    else:
        # 自然结束（兜底）：final_output 是自由文本
        ...
```

---

## 八、文件结构

```
src/business/agents/              # 新目录（复数），区分于现有 agent/
    __init__.py
    agent_loop.py                 # AgentLoop、AgentResult、ResultType
    config.py                     # AgentConfig、AgentType、ToolDefinition、ToolSignal
                                  # PM_CONFIG、PROGRAMMER_CONFIG、TRIAL_CONFIG
    builtin_tools.py              # TALK_TO_USER_SCHEMA、LOAD_REFERENCE_SCHEMA
                                  # talk_to_user handler
    tools/                        # 工具实现（每个工具一个文件）
        __init__.py
        recording_query.py        # query_recording_data handler + schema
        multimodal_analysis.py    # multimodal_analysis handler + schema
        syntax_check.py           # syntax_check handler + schema
```

**命名说明**：新目录为 `agents`（复数），与旧 `agent`（LangGraph）共存。迁移完成后删除旧目录。

**不在此模块中的内容**：
- 流程编排（优先级 4，独立文件）
- System prompt 内容（优先级 5-7，config.py 中只有占位符）
- 工具的具体实现细节（优先级 5-7，工具文件中只有框架）

---

## 九、与事件系统的集成

Agent Loop 本身**不引入任何事件系统依赖**。它通过返回 `AgentResult` 告知调用者发生了什么。

事件的发送由 AgentOrchestrator（优先级 4）负责：

```python
# AgentOrchestrator 中的伪代码（优先级 4 设计）
result = pm_loop.run(session_id, user_input, tools=PM_TOOLS)

if result.result_type == ResultType.COMPLETED:
    # PM 完成需求确认 → 发事件 + 记录 transition
    if result.signal_tool:
        # ToolSignal 触发：从工具参数获取结构化数据
        if result.signal_tool.name == "submit_requirements":
            emit("requirement_confirmed",
                 sender=self,
                 workflow_id=workflow_id,
                 requirements_json=result.signal_tool.args)
            transition_repo.create(
                workflow_id=workflow_id,
                event_type="requirement_confirmed",
                to_session_id=session_id,
                payload={"requirements": result.signal_tool.args}
            )

elif result.result_type in (ResultType.ERROR, ResultType.MAX_ITERATIONS_REACHED):
    # Agent 执行失败 → 发事件 + 记录 transition（供追踪完整工作流）
    emit("agent_error",
         sender=self,
         workflow_id=workflow_id,
         session_id=session_id,
         agent_type=session.agent_type,
         error=result.error)
    transition_repo.create(
        workflow_id=workflow_id,
        event_type="agent_error",
        to_session_id=session_id,
        payload={"agent_type": session.agent_type, "error": result.error}
    )
```

需要在 `src/utils/events.py` 中新增的事件（优先级 4 实现）：

```python
# Agent 协作事件（见架构 v2 第五节）
requirement_confirmed = _signals.signal("requirement_confirmed")
code_completed = _signals.signal("code_completed")
review_passed = _signals.signal("review_passed")
review_failed = _signals.signal("review_failed")
tool_saved = _signals.signal("tool_saved")
trial_failed = _signals.signal("trial_failed")
triage_completed = _signals.signal("triage_completed")

# Agent 错误事件
agent_error = _signals.signal("agent_error")
```

---

## 十、与现有代码的关系

### 10.1 替换

| 现有文件 | 处置 |
|---------|------|
| `src/business/agent/graph.py` | **废弃** — LangGraph 状态图被 while 循环替代 |
| `src/business/agent/state.py` | **废弃** — AgentState 被 AgentConfig + 数据库消息替代 |
| `src/business/agent/ui_bridge.py` | **废弃** — 被新的 AgentUIBridge（优先级 4）替代 |
| `src/business/agent/checkpointer/` | **废弃** — LangGraph checkpoint 被 sessions + messages 表替代 |
| `src/business/agent/nodes/` | **废弃** — 各节点逻辑分散到工具实现和 prompt 中 |
| `src/business/agent/tools/tool_adapter.py` | **废弃** — LangGraph Tool 适配器不再需要 |

### 10.2 复用

| 现有文件 | 说明 |
|---------|------|
| `src/business/ai/llm_client.py` | **扩展** — 新增 LLMResponse、ToolCallInfo、chat_with_tools() |
| `src/utils/events.py` | **扩展** — 新增 Agent 协作事件（优先级 4 实现） |
| `src/data/unified_config.py` | **复用** — 读取 AI 配置（provider、model、api_key 等） |

### 10.3 依赖（尚未实现）

| 模块 | 来源 | 状态 |
|------|------|------|
| ContextManager | `src/business/memory/context_manager.py` | 优先级 2，设计完成，待实现 |
| SessionRepository | `src/data/repositories.py` | 优先级 1，设计完成，待实现 |
| MessageRepository | `src/data/repositories.py` | 优先级 1，设计完成，待实现 |
| sessions / messages 表 | `src/data/migrations.py` | 优先级 1，设计完成，待实现 |

---

## 十一、边界情况

### 11.1 LLM 返回空内容且无 tool_calls

`content` 为 `None` 或空字符串，且 `tool_calls` 为空列表。按"无 tool_calls"分支处理，循环正常结束，`final_output` 为空字符串。调用者需处理空输出的情况。

### 11.2 工具执行抛出异常

由 `_execute_tool` 捕获，错误信息作为 tool result 返回给 LLM。循环不终止。LLM 可以选择重试或换策略。

### 11.3 LLM 调用未知工具

`_execute_tool` 中 handler 查找失败，返回错误字符串 `"错误：未知工具 'xxx'"`。LLM 看到后应调用正确的工具。如果持续调用未知工具，最终会因 `max_iterations` 退出。

### 11.4 已完成的会话尝试恢复

AgentLoop 允许对 `"completed"` 的 session 调用 `run()`——它会将 status 更新为 `"active"`，保存新的 user message 并进入循环。这是设计意图：分诊打回、review 失败等场景下，Orchestrator 复用已有 session，PM/程序员能看到之前的上下文继续工作。

### 11.5 load_reference 的 message_id 无效

`ContextManager.load_reference()` 找不到消息时，返回错误字符串（如 `"引用未找到: {message_id}"`）而非抛异常。LLM 看到后可自行处理。

### 11.6 并发调用同一 session

`AgentLoop.run()` 是同步阻塞方法。AgentUIBridge 在后台线程中运行 Loop 时，需确保同一 session 不会被并发调用。这是 AgentUIBridge 的职责。

---

## 十二、与架构 v2 的差异说明

本设计基于架构 v2 第五节，与架构 v2 保持一致的决策：

- **while 循环替代 LangGraph** — 核心 loop 逻辑与 v2 一致
- **Function Calling 注册** — tool definitions 随请求发送
- **用户交互不在 Loop 内暂停** — 靠消息历史串联
- **Agent 之间事件驱动** — Loop 本身不涉及事件

本设计**新增/细化**的决策：

| 决策 | 架构 v2 原文 | 本设计细化 |
|------|-------------|-----------|
| LLM 客户端接口 | 未明确 | 新增 LLMResponse / ToolCallInfo 数据类，chat_with_tools() 方法 |
| 消息格式转换 | 未明确 | _convert_to_langchain_messages 处理 tool / assistant 含 tool_calls 的消息 |
| 单工具调用模式 | 未明确 | 强制 `parallel_tool_calls=False`，每次响应最多一个 tool_call，消除多工具调用的边界问题 |
| talk_to_user 机制 | "靠消息历史串联" | talk_to_user 的 handler 返回 ToolSignal(NEEDS_USER_INPUT)，Loop 通过 isinstance 判断中断循环，不硬编码工具名 |
| ToolSignal 机制 | 未明确 | 工具 handler 返回 ToolSignal 时 Loop 中断。talk_to_user 和业务工具（如 submit_requirements）共用此机制 |
| 返回值 | 未明确 | AgentResult 数据类，4 种 ResultType，新增 signal_tool 字段携带触发的工具调用信息 |
| 工具执行错误 | 未明确 | 错误作为 tool result 返回给 LLM，不终止循环 |
| LLM 调用重试 | 未明确 | 新增 RetryConfig，默认重试 3 次，延迟 1 秒，用字符串子串匹配判断可重试错误（LangChain 会包装底层异常，类型匹配不可靠） |
| 工具传入方式 | 未明确 | 工具列表由调用方（Orchestrator）组装，通过 `run(tools=...)` 传入 Loop。AgentConfig 不含 tools 字段。PM/程序员可各自传入不同版本的同名工具，无命名冲突 |
| 内置工具 | 未明确 | talk_to_user 和 load_reference 由 Loop 自动追加。talk_to_user 通过 handler 返回 ToolSignal，load_reference 由 _execute_tool 特殊处理（需要 ctx） |
| AgentLoop 上层架构 | "不加额外的协调层" | 拆为两层：AgentUIBridge（线程 + PyQt 信号）+ AgentOrchestrator（session 管理 + 事件发送），改编排不影响 UI，换 UI 不影响编排 |
| 会话初始化 | 未明确 | AgentLoop 检测有无 system prompt 判断是否首次运行（轻量查询，不触发 assemble_context），避免重复初始化 |
| 会话恢复 | 未明确 | 恢复 suspended 会话时自动将 status 更新为 active |
| 错误事件记录 | 未明确 | Agent 执行失败时记录到 workflow_transitions，发送 agent_error 事件，方便追踪完整工作流 |
| 文件结构 | 未明确 | src/business/agents/（复数）新目录，与旧 agent/ 共存直至迁移完成 |
| max_iterations 默认值 | "iteration < max_iterations" | PM 50、程序员 30、试用 20 |

---

*基于架构 v2 细化，记录时间：2026-03-12；更新时间：2026-03-13（新增 LLM 重试机制、错误事件记录）；2026-03-17（ToolSignal 机制替代 talk_to_user 硬编码）*
