# 记忆机制设计

本文档为架构 v2 的记忆机制细化设计，定义显式 REF 加载、会话压缩、上下文组装的运行时行为及接口。

依赖：[数据层设计](data_layer_design.md)

---

## 一、整体定位

记忆机制是数据层之上的**运行时层**，位于 `src/business/memory/`。数据层始终存储原始完整消息，记忆层在加载上下文时进行压缩处理并转换为 LLM 消息格式。

```
Agent Loop
    ↓ assemble_context()
ContextManager（记忆层）
    ↓ get_context() / save()
MessageRepository / SessionRepository（数据层）
    ↓
SQLite（messages / sessions 表）
```

三个 Agent 共用同一套记忆机制，行为通过配置参数调节。

---

## 二、引用替换（短期记忆）

> 当前状态：会话内 tool result 的运行时引用替换已停用。`ReferenceHandler` 现在只负责将持久化 `Message` 转成 LLM API 消息格式，工具结果原文直接进入上下文。`load_reference` 仍保留给跨会话摘要等显式 REF 下钻场景。

### 2.1 机制概述

旧设计中，Agent 的回复文字天然是摘要，工具返回的大块原始数据在 N 步之后替换为指针，不需要额外 LLM 调用。该会话内替换机制已停用，避免 search/fetch 等工具结果在恢复后再次被归档并形成 `load_reference` 循环。

### 2.2 旧替换条件（已停用）

旧机制同时满足两个条件时替换：

1. **步数条件**：该 tool result 之后已有 ≥ N 条 `role=assistant` 消息（默认 N=3）
2. **大小条件**：该 tool result 的 `content` 长度 ≥ 阈值（默认 10000 字符）

步数按 assistant 消息计数，因为每条 assistant 回复代表一个"思考步骤"。user 消息和 tool result 不计入步数。

小的 tool result（错误信息、状态确认等）始终保留原文，不值得做引用替换。

### 2.3 旧替换时机（已停用）

旧机制在 `assemble_context()` 加载消息后、发给 LLM 之前运行时替换。当前 `assemble_context()` 只做压缩、孤立 tool result 清理和格式转换。**数据库中的原始消息始终不被修改**。

### 2.4 旧指针格式（已停用）

```
[REF::{message_id}] 此工具结果已归档（原始大小: {size}字符）。如需查看原始数据，请调用 load_reference("{message_id}")
```

- 用 `message_id`（UUID）作为引用键，与 `MessageRepository.get_by_id()` 对齐
- 包含原始大小，让 Agent 判断是否需要回看
- 包含加载指令，Agent 始终知道如何恢复

### 2.5 load_reference 工具

所有 Agent 共有的工具，通过 Function Calling 注册：

```json
{
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
```

**行为**：
- 调用 `MessageRepository.get_by_id(message_id)` 读取原始 `content`
- 返回原始内容作为**新的 tool result 消息**（标准 tool call/result 流程）
- 不修改历史中的指针消息
- 加载回来的数据当前不会被会话内引用替换再次归档

这是最简单的设计：不需要"粘滞"引用的状态追踪，一切都是标准的工具调用流程。

---

## 三、压缩机制（会话级记忆）

### 3.1 触发条件

默认使用 **token 估算**策略：非 archived 消息的估算 token 总数超过阈值时触发。

Token 估算公式：`len(content) / 3 * 1.2`（中文/混合内容约 1 token/3 字符，乘 1.2 安全余量防止低估）。

触发检查在 `assemble_context()` 中、引用替换之前执行。

#### 可组合触发策略

触发条件设计为可插拔策略，默认 token 估算，支持扩展：

| 策略 | 说明 | 配置键 |
|------|------|--------|
| `token` | 估算 token 总数超过阈值 | `memory.compression_token_threshold` (默认 80000) |
| `count` | 消息条数超过阈值 | `memory.compression_count_threshold` |
| `combined` | 任一条件满足即触发 | 同时配置多个阈值 |

```python
class CompressionTrigger(ABC):
    """压缩触发策略基类"""
    @abstractmethod
    def should_compress(self, messages: List[Message]) -> bool: ...

class TokenTrigger(CompressionTrigger):
    """基于 token 估算的触发策略"""

class CountTrigger(CompressionTrigger):
    """基于消息条数的触发策略"""

class CombinedTrigger(CompressionTrigger):
    """组合策略：任一子策略触发即触发"""
```

通过 `memory.compression_trigger_strategy` 配置选择策略（默认 `"token"`）。

### 3.2 压缩流程

```
1. 确定保留区：最近 keep_recent 条消息（默认 20）
2. 压缩区：system prompt 之后、保留区之前的所有消息
3. 将压缩区消息格式化为可读文本，喂给压缩 LLM 生成摘要
4. 后处理：将摘要中的 tool_call_id 替换为 tool_call 数据 + tool_result 引用（见 3.3）
5. 创建 compressed 消息，归档原始消息
```

**System prompt（sequence=1）始终跳过，不参与压缩。**

**Tool result 不喂完整数据。** 格式化时将 tool result 替换为精简格式：

```
[Tool 调用]: {tool_name}({参数}) → {tool_call_id}
[Tool 结果]: (数据量: {size}字符，详情可通过引用获取)
```

理由：
- Agent 调完工具后的 assistant 回复天然是对结果的摘要，关键信息已在上下文中
- Tool result 可能几十到几百 KB，喂完整数据容易超压缩模型的上下文限制
- 压缩的目的是保留决策和结论，不是保留原始数据

### 3.3 Tool 交互内嵌

#### 后处理流程

压缩 prompt 要求在摘要中保留 tool_call_id。拿到摘要后，程序进行**后处理**：

1. 扫描摘要文本中出现的 tool_call_id
2. 从压缩区原始消息中查找对应的 tool_call 数据（函数名 + 参数）
3. 将 tool_call_id 替换为 tool_call 的完整信息
4. 在对应位置追加 tool_result 的引用指针 `[REF::{message_id}]`

**示例**：

```
压缩 LLM 返回的原始摘要：
  "Agent 调用 call_abc123 查询了录制数据，发现页面使用了分页 API。
   随后调用 call_def456 和 call_ghi789 分别查询了网络请求和 DOM 结构。"

后处理替换后：
  "Agent 调用 查录制数据(recording_id="xxx", fields=["actions", "network"])
   → [REF::{msg_4_id}](50000字符)，发现页面使用了分页 API。
   随后调用 查录制数据(type="network") → [REF::{msg_8_id}](30000字符)
   和 查录制数据(type="dom") → [REF::{msg_9_id}](100000字符)
   分别查询了网络请求和 DOM 结构。"
```

最终结果仍是**一条 compressed 消息**，不需要追加额外消息。Agent 需要回看原始数据时调用 `load_reference`。

**优势**：
- 压缩结果只有一条消息，结构简洁，不存在边界问题
- tool_call 详情和 tool_result 引用内嵌在摘要中，上下文连贯
- 原始数据仍可通过 `load_reference` 访问
- 不需要额外 LLM 调用

### 3.4 压缩 Prompt

采用**结构化摘要**格式，强制输出固定章节，保证摘要质量稳定且信息完整。

```
你是一个对话压缩助手。请将以下对话历史压缩为结构化摘要。

## 输出格式要求

必须包含以下章节（无内容则写"无"）：

### 关键决策
- 已做出的决策及其理由

### 技术发现
- 发现的 API 端点、数据结构、页面模式等技术细节

### 当前进展
- 任务进行到哪一步，下一步是什么

### 待确认事项
- 尚未确认或需要用户进一步输入的问题

### 标识符清单
- 必须原样保留的标识符：recording_id、session_id、tool_id、tool_call_id（如 call_xxx）、API 端点 URL、CSS 选择器、参数名、文件路径等
- 格式：每个标识符单独一行，标注用途
- **特别注意**：tool_call_id 必须原样保留，后续处理依赖它来还原工具调用详情

## 压缩规则

保留：
- 所有关键决策和结论
- 用户明确表达的需求和偏好
- 重要的技术发现和具体数据
- 所有不可重构的标识符（ID、URL、选择器、路径等）必须原样保留

不需要保留：
- 礼貌用语和过渡语
- 重复的信息
- 已被后续结论推翻的早期猜测
- 工具调用的原始数据（只保留分析结论）

--- 对话历史 ---
{messages_text}
```

**设计说明**：
- **结构化章节**参考 OpenClaw 的 compaction-safeguard 模式，固定章节比自由文本的摘要质量更稳定
- **标识符清单**确保 recording_id、API 端点、CSS 选择器等不可重构的信息不会在压缩中丢失，Agent 后续能继续引用

### 3.5 压缩模型

复用现有 `AIConfig` 中的 compression_model_* 配置：

- `config.get_compression_model_provider()`
- `config.get_compression_model_name()`
- `config.get_compression_model_api_key()`
- `config.get_compression_model_temperature()`
- `config.get_compression_model_max_tokens()`

通过 `create_llm_client()` 创建压缩专用的 LLM 客户端。

### 3.6 压缩持久化

1. 创建 compressed 消息：`role='summary'`，`message_type='compressed'`，`compressed_range='X-Y'`，`sequence=X`（压缩区第一条消息的序号），内容为后处理后的摘要文本
2. 将压缩区原始消息标记 `is_archived=1`
3. 以上操作在同一个数据库事务中完成

**sequence 取值说明**：compressed 消息的 sequence 取压缩区起始序号（X），而非 `get_next_sequence()`。因为原始消息已 `is_archived=1`，查询 `WHERE is_archived=0 ORDER BY sequence` 时，compressed 消息自然排在 system prompt 之后、保留区之前，顺序正确。

### 3.7 再压缩

长时间运行的会话可能多次触发压缩。再压缩时：
- 之前的 compressed 消息和更多旧消息一起喂给压缩 LLM
- 生成新的 compressed 消息，覆盖更大的 `compressed_range='X-Y'`，`sequence=X`
- 旧的 compressed 消息标记 `is_archived=1`

### 3.8 失败兜底

压缩 LLM 调用失败时：
- 记录错误日志
- 不阻塞 Agent Loop，跳过本次压缩
- 下次 `assemble_context()` 时重新检查是否需要压缩

---

## 四、上下文组装

### 4.1 核心方法

`ContextManager.assemble_context()` 是 Agent Loop 每次调用 LLM 前的唯一入口：

```python
def assemble_context(self) -> List[Dict]:
    """
    加载会话消息，按需压缩，返回 LLM API 格式的消息列表。

    流程：
    1. 从 DB 加载非 archived 消息（按 sequence 排序）
    2. 检查是否需要压缩 → 如需要，执行压缩，重新加载
    3. 清理孤立 tool result
    4. 转换为 LLM API 格式
    """
```

### 4.2 消息格式转换

```python
def _to_llm_format(self, msg: Message) -> Dict:
    # summary 角色映射为 system 发给 LLM
    llm_role = "system" if msg.role == "summary" else msg.role
    result = {"role": llm_role, "content": msg.content}

    if msg.role == "tool":
        result["tool_call_id"] = msg.tool_call_id
        if msg.tool_name:
            result["name"] = msg.tool_name

    if msg.role == "assistant" and msg.tool_calls:
        result["tool_calls"] = json.loads(msg.tool_calls)
        if result["content"] is None:
            result["content"] = ""

    return result
```

### 4.3 System Prompt 处理

System prompt 存入 messages 表作为 `sequence=1, role='system'` 的消息。

- **创建会话时**：将 Agent 的 system prompt 作为第一条消息存入
- **加载上下文时**：正常加载，无特殊处理（它就是第一条消息）
- **压缩时**：跳过 `role='system'` 的消息，不参与压缩
- **与 summary 的区别**：`role='system'` 是原始 system prompt（sequence=1），`role='summary'` 是压缩生成的摘要。两者发给 LLM 时都映射为 system 角色，但在数据库层面明确区分
- **优势**：会话完全自包含，可追溯当时用的什么 prompt

---

## 五、消息持久化

### 5.1 持久化时机

消息在产生时立即持久化：

| 时机 | 保存内容 |
|------|---------|
| 会话创建 | system prompt（sequence=1） |
| 用户输入到达 | user 消息 |
| LLM 响应返回 | assistant 消息（含 tool_calls） |
| 工具执行完成 | tool result 消息 |

每条消息通过 `MessageRepository.get_next_sequence()` 自动分配序号。

### 5.2 会话恢复

恢复会话 = 调用 `assemble_context()`。没有特殊的"恢复"流程——加载消息、应用压缩并转换格式、返回上下文，跟正常的上下文组装完全相同。

### 5.3 Fork

遵循数据层设计的 Fork 操作：

1. 创建新 session（同一 workflow_id）
2. `MessageRepository.bulk_copy()` 复制消息到新 session
3. 所有 message_id 换新

显式 REF 中的 ID 指向原始会话的消息或摘要。由于 `load_reference` 通过 ID 全局查找，不限于当前 session，原始消息未被删除，引用仍然有效。

---

## 六、类设计

### 6.1 文件结构

```
src/business/memory/
    __init__.py
    context_manager.py      # ContextManager — Agent Loop 的唯一接口
    reference_handler.py    # ReferenceHandler — LLM 消息格式转换
    compression_handler.py  # CompressionHandler — 压缩逻辑 + 触发策略
```

### 6.2 ContextManager — 公开 API

```python
class ContextManager:
    """Agent Loop 与记忆系统的唯一接口。"""

    def __init__(self, session_id: str, config: UnifiedConfigManager):
        self.session_id = session_id
        self._msg_repo = MessageRepository()
        self._session_repo = SessionRepository()
        self._reference_handler = ReferenceHandler(config)
        self._compression_handler = CompressionHandler(config)

    # --- 上下文组装 ---

    def assemble_context(self) -> List[Dict]:
        """加载消息 → 压缩检查 → 孤立 tool 清理 → 返回 LLM 格式"""

    # --- 消息持久化 ---

    def save_message(self, role: str, content: str,
                     tool_call_id: str = None,
                     tool_name: str = None,
                     tool_calls: str = None) -> Message:
        """保存消息，自动分配 sequence"""

    def save_user_message(self, content: str) -> Message:
        """便捷方法：保存用户消息"""

    def save_assistant_message(self, content: str,
                                tool_calls: str = None) -> Message:
        """便捷方法：保存 assistant 消息"""

    def save_tool_result(self, tool_call_id: str,
                          tool_name: str, content: str) -> Message:
        """便捷方法：保存工具结果"""

    # --- 引用加载 ---

    def load_reference(self, reference_id: str) -> str:
        """加载显式 REF 指向的原始内容。供 load_reference 工具调用。"""

    # --- 会话管理 ---

    def fork_session(self, fork_at_sequence: int) -> str:
        """从指定位置分叉会话，返回新 session_id"""

    def get_session_status(self) -> str:
        """获取会话状态"""

    def update_session_status(self, status: str):
        """更新会话状态"""
```

### 6.3 ReferenceHandler — 内部

```python
class ReferenceHandler:
    """引用处理逻辑：当前保留完整 tool result，不做运行时指针替换。"""

    def __init__(self, config: UnifiedConfigManager):
        self.steps_threshold = config.get_memory_reference_steps_threshold()
        self.size_threshold = config.get_memory_reference_size_threshold()

    def apply_replacements(self, messages: List[Message]) -> List[Dict]:
        """
        输入有序消息列表，输出 LLM 格式的消息列表。
        旧 size/steps 引用替换逻辑已停用。
        """
```

### 6.4 CompressionHandler — 内部

```python
class CompressionHandler:
    """会话压缩：使用 LLM 对旧消息生成摘要。"""

    def __init__(self, config: UnifiedConfigManager):
        self._trigger = self._create_trigger(config)
        self.keep_recent = config.get_memory_compression_keep_recent()
        self._llm_client = None  # 懒初始化

    def should_compress(self, messages: List[Message]) -> bool:
        """委托给触发策略判断"""
        return self._trigger.should_compress(messages)

    def compress(self, session_id: str, messages: List[Message],
                 msg_repo: MessageRepository) -> List[Message]:
        """
        执行压缩：
        1. 分离 system prompt、压缩区、保留区
        2. 调用压缩 LLM 对压缩区生成摘要
        3. 后处理：将摘要中的 tool_call_id 替换为原始 tool_call 数据 + tool_result 引用
        4. 创建 compressed 消息，归档原始消息
        5. 返回更新后的消息列表
        """

    def _split_messages(self, messages: List[Message]) -> Tuple[
        Message,           # system prompt
        List[Message],     # 压缩区
        List[Message],     # 保留区
    ]:
        """分离消息区域：system prompt / 压缩区 / 保留区"""

    def _post_process_summary(self, summary: str,
                                compress_messages: List[Message]) -> str:
        """
        后处理摘要文本：
        1. 扫描摘要中出现的 tool_call_id
        2. 从压缩区原始消息中查找对应 tool_call 数据（函数名 + 参数）
        3. 替换 tool_call_id 为完整 tool_call 信息
        4. 追加对应 tool_result 的引用指针 [REF::{message_id}]

        注意：LLM 可能不会在摘要中保留所有 tool_call_id。
        如果匹配到的 tool_call_id 数量显著少于压缩区中实际的
        tool_call 数量，记录 warning 日志（不阻塞流程）。
        未匹配的 tool_call 信息丢失可接受——Agent 的 assistant
        回复已包含关键结论，压缩的目的是保留决策而非原始数据。
        """

    def _format_for_compression(self, messages: List[Message]) -> str:
        """
        将消息格式化为可读文本，用于压缩 prompt。
        tool result 不喂完整数据，只喂工具名、参数和数据量，
        agent 的后续分析已包含关键结论。
        """

    def _create_trigger(self, config) -> CompressionTrigger:
        """根据配置创建触发策略"""

    def _get_llm_client(self) -> LangChainLLMClient:
        """懒初始化压缩 LLM 客户端"""
```

---

## 七、与 Agent Loop 的集成

Agent Loop（优先级 3）使用 ContextManager 的伪代码：

```python
# 获取配置
config = get_unified_config()

# 创建会话
session = session_repo.create(workflow_id=wf_id, agent_type="pm")
ctx = ContextManager(session.session_id, config)

# 保存 system prompt
ctx.save_message(role="system", content=agent.system_prompt)

# 保存用户输入（首次 / 多轮对话的后续输入）
ctx.save_user_message(user_input)

while not done and iteration < max_iterations:
    # 1. 组装上下文
    messages = ctx.assemble_context()

    # 2. 调用 LLM
    response = llm.invoke(messages, tools=agent.tools)

    # 3. 保存 assistant 消息
    ctx.save_assistant_message(
        content=response.content,
        tool_calls=json.dumps(response.tool_calls) if response.tool_calls else None
    )

    # 4. 处理工具调用
    if response.tool_calls:
        for tool_call in response.tool_calls:
            if tool_call.name == "load_reference":
                result = ctx.load_reference(tool_call.args["message_id"])
            else:
                result = execute_tool(tool_call)
            ctx.save_tool_result(
                tool_call_id=tool_call.id,
                tool_name=tool_call.name,
                content=result
            )
    else:
        done = True

# 用户回复后继续
ctx.save_user_message(new_user_input)
# 继续 loop...
```

---

## 八、配置

通过 `UnifiedConfigManager` 管理，新增以下配置项：

| 配置键 | 默认值 | 说明 |
|--------|--------|------|
| `memory.reference_steps_threshold` | 3 | tool result 被替换前需要的 assistant 消息数 |
| `memory.reference_size_threshold` | 10000 | 触发替换的最小字符数（当前保留配置，运行时替换停用） |
| `memory.compression_token_threshold` | 80000 | token 估算触发压缩的阈值 |
| `memory.compression_count_threshold` | — | 消息条数触发压缩的阈值（可选） |
| `memory.compression_keep_recent` | 20 | 压缩时保留的最近消息数 |
| `memory.compression_trigger_strategy` | `"token"` | 触发策略：`"token"` / `"count"` / `"combined"` |

对应在 `UnifiedConfigManager` 中添加访问方法：

```python
def get_memory_reference_steps_threshold(self) -> int
def get_memory_reference_size_threshold(self) -> int
def get_memory_compression_token_threshold(self) -> int
def get_memory_compression_count_threshold(self) -> Optional[int]
def get_memory_compression_keep_recent(self) -> int
def get_memory_compression_trigger_strategy(self) -> str
```

---

## 九、边界情况

### 9.1 空/None Content

assistant 消息可能 `content=None`（仅包含 tool_calls）。格式转换时设为空字符串。

### 9.2 单条 assistant 消息包含多个 tool_calls

每个 tool result 是独立消息，有各自的 `tool_call_id`。当前格式转换保留每条 tool result 的原始 content、`tool_call_id` 和 `name`。

### 9.3 并发会话

ContextManager 实例绑定单个 session，不共享可变状态。数据库层面的并发由 SQLAlchemy 处理。

### 9.4 超大 tool result

单条 tool result 超过 LLM 上下文窗口的情况：
- 应在工具设计层面避免（分页、过滤、内置工具输出治理）
- `ReferenceHandler` 不再用会话内指针隐藏超大结果
- 如确实发生，LLM 会报错，Agent 可自行调整查询

### 9.5 压缩区为空

如果 system prompt 之后、保留区之前没有消息（会话刚开始），`should_compress` 返回 False，不触发压缩。

### 9.6 再压缩

多次压缩时，之前的 compressed 消息作为普通文本参与新一轮压缩。新 compressed 消息的 `compressed_range` 覆盖从最早到新截止点的完整范围。

---

## 十、与数据层设计的差异说明

本设计基于架构 v2 第六节，与数据层设计保持一致的决策：

- **会话内引用替换已停用** — 数据层始终存原始消息，无引用表
- **消息类型只有 normal/compressed** — 无 reference 类型
- **load_reference 通过 ID 查找消息或摘要** — 无额外存储

本设计**新增/细化**的决策：

| 决策 | 架构 v2 原文 | 本设计细化 |
|------|-------------|-----------|
| 步数计算 | "固定步数（默认 3 步）" | 旧机制规则，当前停用 |
| 大小阈值 | 未明确 | 默认 10000 字符，当前仅保留配置 |
| 指针格式 | 未明确 | 旧机制为 `[REF::{message_id}]` + 大小 + 指令，当前会话内不生成 |
| 压缩触发 | "消息类型可扩展" | token 估算为默认，可组合策略 |
| 压缩 tool 处理 | 未明确 | 摘要中内嵌 tool_call 数据 + tool_result 引用（后处理替换） |
| System prompt | 架构 v2 未明确 | 存入 messages 表，不参与压缩 |
| 压缩消息角色 | 未明确 | 专用 `role='summary'`，发 LLM 时映射为 user |

---

*基于架构 v2 细化，记录时间：2026-03-12*
