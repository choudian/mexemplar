# 办公助理 Agent 设计

本文档为架构 v2 的新增模块设计，定义办公助理 Agent 的整体定位、system prompt、工具集、会话管理、首次引导流程及跨会话记忆机制。

依赖：[Agent Loop 设计](agent_loop_design.md)、[事件系统设计](event_system_design.md)、[记忆机制设计](memory_mechanism_design.md)

---

## 一、整体定位

办公助理 Agent 是用户日常使用的**主入口**。之前的 PM/程序员/试用 Agent 负责"教技能"（录制 → 分析 → 生成代码 → 试用发布），办公助理负责**用技能**——用户下达任务，助理调用已发布的工具去执行。

助理也是用户的日常对话对象。用户可以闲聊、问问题、下达任务，助理都应该自然回应。有合适的工具就调工具，没有就用自身能力（LLM + 内置通用工具）回答。

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

### 与其他 Agent 的关系

| | PM / 程序员 / 试用 | 办公助理 |
|---|---|---|
| 定位 | 教技能（内部流程） | 用技能（面向用户的日常入口） |
| 触发 | 录制完成自动触发 | 用户主动发起对话 |
| 生命周期 | 任务完成即结束 | 长期存在，随时可对话 |
| 工具集 | 录制数据工具 + 信号工具（固定） | 已发布的工具（动态） |
| 与"教技能"流程 | 是流程的一部分 | 独立入口，可触发修复流程（report_tool_bug）；可通过三种路径产生新工具（见第八节） |

---

## 二、首次使用引导

用户第一次打开 ChatWidget 时，助理通过引导式设问了解用户偏好，作为人设定制的基础。

### 2.1 引导流程

```
首次打开 ChatWidget
  → 检测：assistant_profile 是否存在？
  → 不存在 → 进入引导模式
  → 助理依次询问：
      1. 称呼："你好！我是你的办公助理。你希望我怎么称呼你？"
      2. 风格："你偏好什么沟通风格？（简洁干脆 / 详细解释 / 轻松随意 / 其他）"
      3. 其他："有什么需要我特别注意的吗？（没有的话直接说没有就行）"
  → 用户回答完毕
  → 助理将回答整理为 profile，存入 assistant_profile 表
  → 后续所有会话的 system prompt 中注入该 profile
```

### 2.2 Profile 存储

```
assistant_profile:
  profile_id     TEXT PK DEFAULT 'default'  -- 单用户桌面应用，固定为 'default'
  display_name   TEXT       -- 用户希望的称呼
  style          TEXT       -- 沟通风格偏好
  notes          TEXT       -- 其他注意事项
  raw_answers    JSON       -- 原始对话内容（备查）
  created_at     DATETIME
  updated_at     DATETIME
```

引导对话采用**硬编码 UI 表单**（PyQt Dialog），不走 AgentLoop。参考 nanobot（传统 CLI 问答）和 openclaw（step-by-step Wizard 表单）的做法，两者都选择了确定性流程而非 LLM 驱动。理由：确定性强、不浪费 token、用户体验可控。

### 2.3 Profile 修改

用户可以在对话中说"改一下我的称呼"或"换个风格"，助理识别到这类请求后调用 `update_profile` 工具更新。不需要单独的设置页面。

**update_profile** FC Schema：

```json
{
  "name": "update_profile",
  "description": "更新用户偏好档案。用户要求修改称呼、风格、注意事项时调用。",
  "parameters": {
    "type": "object",
    "properties": {
      "display_name": { "type": "string", "description": "用户希望的称呼（不修改则不传）" },
      "style": { "type": "string", "description": "沟通风格偏好（不修改则不传）" },
      "notes": { "type": "string", "description": "特别注意事项（不修改则不传）" }
    }
  }
}
```

Handler 只更新传入的非空字段（`_session_id` 由闭包绑定，LLM 不需要传）。**注意**：现有 AgentLoop 的 system prompt 只在会话首次初始化时设置一次（写入 messages 表后不再更新），所以 profile 变更**不会在当前会话生效**。

实现方案：`update_profile` handler 更新 DB 后，**用正则匹配替换** messages 表中 system prompt 消息的 `## 关于用户` 段落（匹配 `## 关于用户` 到下一个 `## ` 之间的内容）。需注意：ContextManager 的压缩机制只压缩 user/assistant 消息，**不压缩 system prompt 消息**（`assemble_context` 中 system prompt 始终原样保留），所以正则匹配是安全的。实现时需加断言验证 system prompt 消息确实包含 `## 关于用户` 标记，如果不包含（理论上不会发生）则跳过替换、仅更新 DB，变更在下次新建会话时生效。

---

## 三、System Prompt

### 3.1 基础 prompt（固定部分）

```
你是用户的办公助理。你的职责是帮助用户完成日常工作任务。

{profile_section}

{memory_section}

## 你的能力

你可以调用以下工具来完成任务：

{tools_section}

## 你的工作方式

你通过"思考 → 行动 → 观察"的循环来完成任务。每一步：

1. **思考**：分析当前状况——用户想做什么？需要哪个工具？参数够不够？上一步结果说明了什么？
2. **行动**：基于思考做出一个动作——调用工具、向用户提问、或直接回答
3. **观察**：看到行动的结果后，回到第 1 步继续思考，直到任务完成

关键原则：
- 能找到合适的工具就直接调用，不要反复确认
- 缺参数时一次问齐，不要一个一个问
- 用户的表述可能不精确，尽量从上下文推断意图
- 如果不确定用户要用哪个工具，简短列出候选让用户选
- 工具执行失败时，先思考原因再决定下一步行动，不要机械重试

## 执行失败时的思考

工具执行返回失败时，根据错误信息思考原因：
- **参数问题**（参数缺失、格式错误、值无效）→ 向用户重新确认参数，再次执行
- **临时错误**（网络超时、目标网站不可用、登录态过期）→ 告知用户出了临时问题，建议稍后重试
- **代码 bug**（ImportError、AttributeError、逻辑错误等代码层面的异常）→ 调用 report_tool_bug 提交修复

判断原则：如果换一组参数或换个时间可能成功，就不是代码 bug。如果无论怎么调参数都会失败，那就是代码 bug。

## 结果展示

- **列表类结果**：展示前 3-5 条关键字段 + 总数量
- **操作类结果**：说清楚做了什么、是否成功
- **无数据结果**：明确告知"执行完成但没有返回数据"

## 注意事项

- 不要编造工具不存在的能力。没有合适工具时，用自身能力尽量回答
- 如果用户想让你"学会"某件事，先用通用能力完成任务，用户可要求将执行过程做成工具
- 如果工具执行结果中附带了"建议做成工具"的提示，自然地转达给用户，不要忽略也不要过度推销
- 保持对话简洁，不要重复用户说过的话
```

### 3.2 Profile 注入

`{profile_section}` 在有 profile 时替换为：

```
## 关于用户

- 称呼：{display_name}
- 沟通风格偏好：{style}
- 特别注意：{notes}
```

无 profile（首次使用前）时留空。

### 3.3 全局摘要注入

`{memory_section}` 在有全局摘要时替换为跨会话记忆的第三层摘要（详见第七节）：

```
## 历史记忆

用户使用模式：
- 每天早上查天气（已有工具）
- 每周一导出销售数据（已有工具）
高频工具：天气查询、Excel导出、百度搜索
[REF::summary_group_3] [REF::summary_group_4]
```

无全局摘要（首次使用阶段）时留空。控制长度不超过 500 token。

### 3.4 工具列表注入

`{tools_section}` 在每次会话启动时从 DB 查询 published 工具，格式化为自然语言描述：

```
- **百度搜索**：搜索百度并获取结果。参数：搜索关键词（必填）、结果数量（选填，默认10）
- **抓取网页**：获取指定网页的内容。参数：网址（必填）
```

这段文字只是给 LLM 理解用的概览，实际的 FC schema 通过工具注册机制传递。

---

## 四、工具集

### 4.1 工具调用机制：FC + 懒加载

**现有 Agent（PM/程序员/试用）保持不变**，工具少（3-4 个），全量 FC 注入没有 token 问题。

**助理 Agent** 采用 FC + 懒加载，解决用户工具多时的 token 成本：

```
两层工具：

固定内置工具（始终 FC 注入）：
  update_profile、report_tool_bug、codify_as_tool、web_search、web_fetch 等 16 个 + talk_to_user + load_reference
  → 数量固定，token 可控
  → LLM 直接 function call 调用，参数有 schema 约束

用户动态工具（懒加载 FC）：
  System prompt 放工具简表（名称 + 一句话描述）
  → LLM 决定用某个工具 → 调 get_tool_detail(name) 查看完整参数
  → 下一轮该工具的 FC schema 动态注入
  → LLM 通过 FC 调用，参数有 schema 约束
```

**参考依据**：nanobot 和 openclaw 都采用 Tools（FC）+ Skills（知识层）双层架构，FC 作为工具调用基础机制不可替代——LLM 对 FC 的参数准确率明显高于自由拼 JSON。

### 4.2 懒加载辅助工具

助理 Agent 额外注入两个辅助工具（FC），用于发现和了解用户动态工具：

**search_tools** — 搜索匹配的工具

```json
{
  "name": "search_tools",
  "description": "按关键词搜索可用的用户工具。当不确定该用哪个工具时使用。",
  "parameters": {
    "type": "object",
    "properties": {
      "query": { "type": "string", "description": "搜索关键词或意图描述" }
    },
    "required": ["query"]
  }
}
```

Handler：通过 Repository 的参数化查询做 SQL LIKE 模糊匹配工具名称和描述（用户工具数量通常在几十个以内，不需要全文检索）。**注意**：`search_published` 必须使用 SQLAlchemy 的 `column.like(f"%{query}%")` 或参数绑定，禁止拼接 SQL 字符串——query 来自 LLM 输出，虽非直接用户输入，仍应防注入。

```python
def search_tools(query: str) -> str:
    """按关键词搜索已发布的用户工具"""
    tools = ToolRepository().search_published(query)  # SQLAlchemy 参数化 LIKE 查询
    if not tools:
        return "没有找到匹配的工具。"
    lines = [f"- {t.name}：{t.description}" for t in tools[:10]]
    return "找到以下工具：\n" + "\n".join(lines)
```

**get_tool_detail** — 获取工具完整参数说明

```json
{
  "name": "get_tool_detail",
  "description": "获取指定用户工具的完整参数说明。调用不熟悉的工具前，先用这个查看参数格式。",
  "parameters": {
    "type": "object",
    "properties": {
      "tool_name": { "type": "string", "description": "工具名称" }
    },
    "required": ["tool_name"]
  }
}
```

### 4.3 调用路径

```
助理收到用户任务
  → 判断：是内置工具能做的？
    → 是 → 直接 FC 调用内置工具（一步到位）
    → 否 → 看 system prompt 工具简表，判断哪个用户工具合适
      → 不确定 → search_tools(query) 搜索
      → 找到了但不确定参数 → get_tool_detail(name) 查看
      → get_tool_detail 返回后，下一轮该工具的 FC schema 动态注入
      → LLM 通过 FC 调用用户工具（参数有 schema 约束）
```

### 4.4 动态 FC 注入机制

**⚠️ AgentLoop 前置改动**：现有 AgentLoop 在 `run()` 入口处构建一次工具列表（`agent_loop.py:226-232`），while 循环内每轮迭代复用同一个 `all_tool_schemas` 和 `tool_handlers`，不支持中途追加工具。要实现懒加载，需要将工具列表的构建从 `run()` 入口**移到 while 循环内部**，每轮迭代重新拼装。具体改动：

```python
# agent_loop.py run() 方法改动
# 改动前：tools 在 while 循环外构建一次
# 改动后：tools 在 while 循环内每轮重建

def run(self, session_id, user_input, tools=None, system_prompt_override=None):
    ...
    # 主循环
    iteration = 0
    while iteration < self._config.max_iterations:
        iteration += 1

        # 【改动】每轮重新构建工具列表（支持动态追加）
        current_tools = tools() if callable(tools) else (tools or [])
        all_tool_schemas = [td.schema for td in current_tools] + [
            TALK_TO_USER_SCHEMA, LOAD_REFERENCE_SCHEMA,
        ]
        tool_handlers = {td.name: td.handler for td in current_tools}
        tool_handlers["talk_to_user"] = talk_to_user

        messages = ctx.assemble_context()
        ...
```

改动方式：`tools` 参数支持传入 callable（工厂函数），每轮调用获取最新工具列表。传入 list 时行为不变（兼容现有 PM/程序员/试用 Agent）。

**对 Orchestrator 的影响**：`_build_tools` 的返回类型从 `List[ToolDefinition]` 变为 `Union[List[ToolDefinition], Callable[[], List[ToolDefinition]]]`。PM/程序员/试用分支仍返回 list，assistant 分支返回 lambda：

```python
def _build_assistant_tools(self, session_id: str) -> Callable[[], List[ToolDefinition]]:
    """返回工厂函数，每轮迭代调用时拿到最新的已激活工具"""
    dynamic_manager = self._get_dynamic_manager(session_id)
    builtin = self._get_assistant_builtin_tools(session_id)

    def tool_factory() -> List[ToolDefinition]:
        return builtin + dynamic_manager.get_activated_tools()
    return tool_factory
```

`loop.run(session_id, user_input, tools=tool_factory)` 不需要 Orchestrator 做额外适配——AgentLoop 内部判断 `callable(tools)` 决定行为。

`get_tool_detail` 的 handler 除了返回参数说明外，还会标记该工具需要在下一轮注入 FC schema：

```python
class DynamicToolManager:
    """管理用户工具的懒加载 FC 注入"""

    MAX_ACTIVATED = 10  # 最多同时激活的用户工具数，防止长会话 token 膨胀

    def __init__(self):
        self._activated_tools: dict[str, ToolDefinition] = {}  # 已激活的用户工具
        self._access_order: list[str] = []  # LRU 顺序，最近使用的在末尾

    def get_tool_detail(self, tool_name: str) -> str:
        """查看工具详情，同时激活该工具的 FC schema"""
        tool = ToolRepository().get_by_name(tool_name)
        if not tool or tool.status != "published":
            return f"工具 '{tool_name}' 不存在或未发布"

        # 构建 FC schema 并标记为已激活
        tool_def = self._build_tool_definition(tool)
        self._activated_tools[tool_name] = tool_def

        # 更新 LRU 顺序
        if tool_name in self._access_order:
            self._access_order.remove(tool_name)
        self._access_order.append(tool_name)

        # 超出上限时淘汰最久未使用的工具
        while len(self._activated_tools) > self.MAX_ACTIVATED:
            oldest = self._access_order.pop(0)
            self._activated_tools.pop(oldest, None)

        # 返回人类可读的参数说明
        return self._format_detail(tool)

    def get_activated_tools(self) -> list[ToolDefinition]:
        """获取已激活的用户工具列表，供 AgentLoop 在下一轮注入 FC schema"""
        return list(self._activated_tools.values())
```

**生命周期**：`DynamicToolManager` 实例按 session_id 缓存在 Orchestrator 中（`dict[session_id, DynamicToolManager]`），在同一会话的多次 `run_agent` 调用间保持激活状态。会话关闭时清理。虽然 AgentLoop 不缓存（每次创建新实例），但 `DynamicToolManager` 独立于 Loop 存在，由 `_build_assistant_tools` 传入。

AgentLoop 每轮构建 FC 工具列表时：
```python
tools = (
    builtin_tools              # 固定内置工具（始终注入）
    + [search_tools, get_tool_detail]  # 懒加载辅助工具
    + dynamic_manager.get_activated_tools()  # 已激活的用户工具（按需注入）
)
```

### 4.5 用户动态工具的 handler

每个用户工具的 handler 是一个闭包，内部调用 `run_tool_code`：

```python
def _create_tool_handler(tool_id: str) -> Callable:
    """为指定工具创建执行 handler（闭包绑定 tool_id）"""
    def handler(**kwargs) -> str:
        tool = ToolRepository().get_by_id(tool_id)
        if not tool or not tool.execution_code:
            return json.dumps({"success": False, "message": "工具不可用", "data": None})

        result = run_tool_code(tool.execution_code, kwargs, tool.dependencies or [])
        return json.dumps(result, ensure_ascii=False, default=str)
    return handler
```

FC schema 从工具的 `parameters` 字段动态生成：

```python
def _build_tool_schema(tool: Tool) -> dict:
    """从 Tool 模型构建 FC schema"""
    properties = {}
    required = []
    for param in (tool.parameters or []):
        properties[param["name"]] = {
            "type": param.get("type", "string"),
            "description": param.get("description", ""),
        }
        if param.get("required", False):
            required.append(param["name"])

    return {
        "type": "function",
        "function": {
            "name": f"utool_{tool.tool_id[:8]}",  # 规范化短名称，前缀 utool_ 避免与内置工具碰撞
            "description": tool.description or "",
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        },
    }
```

### 4.6 System prompt 中的工具简表

助理的 system prompt 注入用户工具简表（仅名称 + 描述，不含参数细节）：

```
## 用户工具

以下是你可以使用的用户自定义工具。使用前先调用 get_tool_detail 查看参数格式。

- 百度搜索：搜索百度并获取结果
- 抓取网页：获取指定网页的内容
- Excel导出：将数据导出为Excel文件
- ...

如果不确定该用哪个，可以用 search_tools 搜索。
```

### 4.7 report_tool_bug（助理专用）

当助理判断工具执行失败是代码 bug 时调用。

Handler 实现：**不返回 ToolSignal**（不中断 Loop），返回普通字符串。助理报告完 bug 后继续跟用户对话。写入待处理队列而非同步 emit，避免线程嵌套问题。

Handler 代码和线程安全说明见 6.3 节。

### 4.8 内置工具汇总

| # | 工具 | 类型 | 说明 |
|---|------|------|------|
| 1 | update_profile | 业务工具（FC） | 更新用户偏好档案（称呼/风格/注意事项） |
| 2 | report_tool_bug | 业务工具（FC） | 报告工具 bug → PM 分诊 |
| 3 | codify_as_tool | 业务工具（FC） | 将执行记录做成可复用工具 |
| 4 | web_search | 通用工具（FC） | 网页搜索 |
| 5 | web_fetch | 通用工具（FC） | 抓取网页内容 |
| 6 | cron | 通用工具（FC） | 定时提醒 |
| 7 | image_generate | 通用工具（FC） | AI 图片生成 |
| 8 | memory_search | 通用工具（FC） | 搜索历史记忆（混合检索） |
| 9 | browser | 通用工具（FC） | 浏览器自动化 |
| 10 | pdf | 通用工具（FC） | PDF 读取 |
| 11 | image | 通用工具（FC） | 图片查看/识别 |
| 12 | read_file | 通用工具（FC） | 读本地文件 |
| 13 | write_file | 通用工具（FC） | 写本地文件 |
| 14 | edit_file | 通用工具（FC） | 编辑本地文件 |
| 15 | list_dir | 通用工具（FC） | 列目录 |
| 16 | exec | 通用工具（FC） | 执行 shell 命令 |
| 17 | search_tools | 辅助工具（FC） | 搜索用户工具 |
| 18 | get_tool_detail | 辅助工具（FC） | 查看用户工具参数，触发懒加载 |
| 19 | dismiss_suggestion | 业务工具（FC） | 用户拒绝工具化建议时记录（冷却机制） |
| - | 用户已发布工具 | 动态工具（懒加载 FC） | get_tool_detail 后动态注入 |
| - | talk_to_user | 信号工具（FC） | AgentLoop 自动追加 |
| - | load_reference | 内置工具（FC） | AgentLoop 自动追加 |

### 4.9 工具名称规范化

用户工具的 `tool_name` 是中文（如"百度搜索"），但 FC 的 function name 需要是合法标识符。需要一个映射：

- FC schema 中使用规范化名称：`utool_<short_id>`，其中 `short_id` 为 tool_id 的前 8 位（如 `utool_550e8400`）。前缀 `utool_` 避免与内置工具碰撞，短 ID 避免超过 API 的 function name 长度限制（部分 API 限制 64 字符）。碰撞概率极低（16^8 = 42 亿），如碰撞则取前 12 位
- system prompt 的工具简表中展示中文名
- LLM 通过 description 匹配工具，不依赖 function name
- `_build_tool_schema` 和 `_create_tool_handler` 中需维护 `utool_<short_id>` ↔ `tool_id` 的双向映射

### 4.10 高危工具安全机制

`exec`（shell 命令）和 `write_file`（写本地文件）是高危操作，需要双重保护：

**1. 执行前用户确认**：不使用 ToolSignal（ToolSignal 暂停 Loop 后无法恢复执行原命令，LLM 重新推理可能不再调用）。改为 handler 内部同步确认：handler 通过 pyqtSignal 通知 UI 线程弹出确认框（使用 `QDialog.exec()` 确保 UI 事件循环不中断），worker 线程用 `threading.Event.wait()` 阻塞等待。用户点确认 → set Event → handler 继续执行并返回结果；用户拒绝 → 返回"用户取消了该操作"。Loop 不中断，LLM 收到执行结果后继续推理。

**2. 白名单限制**：
- `exec`：维护可执行命令白名单（如 `dir`/`ls`、`ping`、`ipconfig` 等安全命令），不在白名单中的命令必须经过用户确认。白名单可配置（存入 `assistant_profile` 或全局配置）。
- `write_file`：限制可写目录为用户指定的工作目录（默认为桌面/文档目录），超出范围的路径需用户确认。禁止写入系统目录。

**Token 成本评估**：20 个常驻 FC schema 约 2800-3800 token，加上 system prompt（~800）、profile（~200）、全局摘要（~500）、工具简表（视用户工具数量），每轮请求的 prompt 开销约 **4000-6000 token**。这是日常对话入口的固定成本，需关注。如有必要，可考虑将低频工具（如 pdf、image_generate）也改为懒加载。

---

## 五、会话管理

### 5.1 会话模型

办公助理会话不绑定 workflow_id（它不属于任何录制工作流）。

复用现有 Session 表。**注意**：现有 Session 表的 `workflow_id` 字段为 `NOT NULL`，需要改为 `nullable=True`，并做数据迁移（现有数据不受影响，只是放开约束）。

```
agent_type = "assistant"
workflow_id = NULL  -- 需先将 Session.workflow_id 改为 nullable
```

### 5.2 多会话支持

- 用户可以同时拥有多个助理会话
- 侧边栏显示助理会话列表，用户可新建、切换、回看历史
- 每个会话独立维护消息历史（引用替换、压缩照常走）

### 5.3 新建会话时的工具选择

```
点击新建会话（+ 按钮）
  → 默认：直接创建会话，使用全部已发布工具（tool_ids = NULL）
  → 高级选项（折叠面板或二级入口）：手动勾选工具子集
    → 展示 CheckBox 列表（工具名 + 一句话描述），默认全选
    → 用户取消勾选不需要的工具 → 确认
    → 创建会话，tool_ids 存储勾选的工具 ID 列表
```

**UI 形式**：新建按钮点击后默认直接创建会话（零摩擦）。工具选择作为可选的高级功能，通过按钮旁的下拉菜单"新建（选择工具）"进入。避免每次新建都弹窗打断用户。

工具集存储在 Session 的元数据中：

```python
# Session 表新增字段（或使用现有的 JSON 元数据字段）
tool_ids: JSON  # ["tool_id_1", "tool_id_2", ...]，NULL 表示全部
```

每次 `loop.run()` 时：
- `tool_ids` 为 NULL → 查询全部 published 工具（包括新发布的，自动可见）
- `tool_ids` 非空 → 只加载指定的工具，仍需过滤掉已 unpublish 的。**新发布的工具不自动加入**（用户主动选了子集，说明有意控制范围；自动加入会违背用户意图）。助理可在对话中提示"有新工具 XX 发布了，要加入当前会话吗？"

### 5.4 Orchestrator 适配

Orchestrator 处理 assistant 类型的特殊之处：

- **不需要 `_dispatch_next`**：助理没有下游 Agent，Loop 完成后不调度
- **用 session_id 作为主键传递**：会话独立存在，不绑定 workflow_id
- **工具集动态构建**：每次从 DB 查，不像 PM/程序员有固定工具集
- **Loop 不缓存**：system prompt 含动态工具列表，每个会话不同

**接口变更**：现有 `run_agent(agent_type, user_input, workflow_id)` 和 `reply_to_agent(agent_type, user_input, workflow_id)` 的第三个参数是 `workflow_id`，assistant 类型没有 workflow_id。需要将签名改为统一的上下文参数：

```python
# 方案：run_agent / reply_to_agent 签名变更
def run_agent(self, agent_type: str, user_input: str,
              workflow_id: str = None, session_id: str = None) -> None:
    """
    PM/程序员/试用：传 workflow_id（现有逻辑不变）
    assistant：传 session_id（不传 workflow_id）
    """
    ...

# _build_tools 新增 assistant 分支
def _build_tools(self, agent_type: str, workflow_id: str = None,
                 session_id: str = None) -> List[ToolDefinition]:
    if agent_type == "assistant":
        return self._build_assistant_tools(session_id)
    # ... 现有逻辑
```

AgentUIBridge 同步变更：
```python
def reply_to_agent(self, agent_type: str, user_input: str,
                   workflow_id: str = None, session_id: str = None) -> None:
    self.start_agent(agent_type, user_input,
                     workflow_id=workflow_id, session_id=session_id)
```

**事件变更**：`agent_needs_user_input` 事件 payload 需新增 `session_id` 字段。现有 `_on_needs_user_input` handler 的 pyqtSignal 也需携带 `session_id`，UI 端通过 `session_id`（而非 `workflow_id`）路由到正确的 ChatWidget 实例。PM/程序员/试用 Agent 不受影响（它们仍通过 `workflow_id` 路由）。

**会话获取变更**：助理 Agent 的会话由用户主动创建（点 + 按钮），不走现有 `_get_or_create_session`（该方法通过 `workflow_id + agent_type` 查找，不适用助理）。`run_agent` 中 assistant 类型直接使用传入的 `session_id`：

```python
def run_agent(self, agent_type: str, user_input: str,
              workflow_id: str = None, session_id: str = None) -> None:
    if agent_type == "assistant":
        # 助理会话由 UI 创建，直接使用传入的 session_id
        assert session_id, "assistant 类型必须传 session_id"
    else:
        # PM/程序员/试用：通过 workflow_id 查找或创建会话
        session_id = self._get_or_create_session(workflow_id, agent_type)

    # 【assistant 分支需跳过的代码路径】：
    # 1. WorkflowTransition 记录：assistant 不写入（无 workflow_id）
    #    → 在写入处加 `if workflow_id:` 守卫
    # 2. emit 事件的 workflow_id 字段：传 None，事件消费方按 session_id 路由
    # 3. _dispatch_next：assistant 不调度（result_type 始终为 NEEDS_USER_INPUT）
    # 4. format_system_prompt(recording_id=workflow_id)：assistant 不需要，传 None 无副作用
    ...
```

---

## 六、工具执行失败处理

### 6.1 助理自主判断

工具执行失败时，助理根据 `run_tool_code` 返回的 error message 自主判断原因，不需要问用户。

判断逻辑写在 system prompt 中（见第三节），不硬编码。LLM 看 error message 足以区分：
- `KeyError: 'keyword'` → 参数问题
- `TimeoutError` / `ConnectionError` → 临时错误
- `ImportError` / `AttributeError` / `NameError` → 代码 bug

### 6.2 处理路径

```
工具执行失败
  → 助理判断原因
  → 参数问题：
      "参数好像有问题，能再确认一下 XX 吗？"
      → 用户提供新参数 → 重新执行
  → 临时错误：
      "执行遇到了网络问题，建议稍后再试。"
      → 继续对话（用户可能有别的任务）
  → 代码 bug：
      → 调用 report_tool_bug 提交修复
      → "这个工具有个技术问题，已经提交修复了。修好后你可以再用。"
      → 继续对话
```

### 6.3 report_tool_bug 触发的修复流程

`report_tool_bug` handler **不使用 blinker 事件**（blinker emit 是同步的，会在助理 worker 线程中嵌套启动 PM Agent，导致线程阻塞或竞态）。直接写入 DB 队列，由独立的后台 worker 异步消费。

```python
def report_tool_bug(tool_name: str, error_message: str, user_task: str,
                    parameters_used: dict = None) -> str:
    """报告工具 bug——写入待处理队列，不同步触发 PM"""
    tool = ToolRepository().get_by_name(tool_name)
    if not tool or not tool.workflow_id:
        return "无法提交修复请求：未找到该工具的来源信息"

    # 写入队列而非同步 emit，避免在助理 worker 线程中嵌套执行 PM
    BugReportQueue.enqueue(
        workflow_id=tool.workflow_id,
        tool_id=tool.tool_id,
        error_message=error_message,
        user_task=user_task,
        parameters_used=parameters_used or {},
    )
    return f"已提交修复请求。工具 {tool_name} 的问题会被分析和修复，修好后你可以重新使用。"
```

### 6.4 异步任务队列

`report_tool_bug` 和 `codify_as_tool` 都采用队列方案避免线程嵌套。统一为一个 `pending_assistant_tasks` 表：

```
pending_assistant_tasks:
  task_id        TEXT PK
  task_type      TEXT       -- 'bug_report' | 'codify_tool'
  payload        JSON       -- 任务参数（workflow_id、tool_id、error_message 等）
  status         TEXT       -- 'pending' | 'processing' | 'completed' | 'failed'
  created_at     DATETIME
  updated_at     DATETIME
```

Orchestrator 启动时创建一个后台 worker 线程，轮询此表取出 pending 任务执行。**轮询策略**：默认间隔 5 秒，入队时通过 `threading.Event.set()` 立即唤醒 worker（避免用户等待最多 5 秒），轮询作为兜底。

消费逻辑：
- `bug_report` → `_start_triage(tool_id, feedback, workflow_id)`（workflow_id 来自工具记录）
- `codify_tool` → 先创建新的 workflow 记录（`workflow_id = uuid4()`，类型标记为 `codify`），再 `run_agent("pm", execution_trace_input, workflow_id=new_workflow_id)`。PM 的现有流程强依赖 workflow_id（`_get_or_create_session`、`_build_tools`、`WorkflowTransition` 等均为 NOT NULL），不能传 None。

`BugReportQueue.enqueue()` 和 `CodifyRequestQueue.enqueue()` 本质上都是往这张表插入一行。

队列消费复用了现有的 PM 分诊 → 程序员修复 → 重新入库的完整流程。修复完成后工具自动更新（`_save_tool` 更新 execution_code），助理下次调用时自然使用新代码。

---

## 七、跨会话记忆

### 7.1 设计原则

跨会话记忆采用**层级摘要 + ID 引用**机制，与会话内的引用替换同构。主路径是通过 ID 逐级查找（`load_reference`），辅以语义搜索（`memory_search`）解决"不确定在哪"的模糊查找场景。

### 7.2 层级结构

```
第三层：全局摘要（常驻 system prompt）
  内容很短，概括用户的核心偏好和使用模式
  包含 [REF::summary_group_X] 指向下层分组摘要

第二层：分组摘要（每 N 个会话一个）
  概括一批会话的主要活动
  包含 [REF::session_summary_X] 指向下层会话摘要

第一层：会话摘要（每个会话一个）
  概括单次会话的任务和结果
  包含 [REF::msg_X] 指向原始消息

第零层：原始消息
  完整的对话记录和工具调用结果
```

**`load_reference` 扩展**：现有 `load_reference` 只查 messages 表（`msg_` 前缀），需要扩展支持 `assistant_summaries` 表。根据 ID 前缀路由：
- `msg_*` → messages 表（现有逻辑不变）
- `session_summary_*` → assistant_summaries 表（level=1）
- `summary_group_*` → assistant_summaries 表（level=2）

这样全局摘要中的 `[REF::summary_group_3]` 才能正确下钻。

**改动位置**：`context_manager.py` 的 `load_reference` 方法（当前在 `context_manager.py:153-171`）。改动方式：在方法开头加前缀判断，`session_summary_*` 和 `summary_group_*` 前缀走 `AssistantSummaryRepository().get_by_id(ref_id)`，其余走现有 messages 表逻辑。`AssistantSummaryRepository` 需要作为依赖注入到 `ContextManager`，或者 `load_reference` 内部按需实例化（与现有 `MessageRepository` 的使用方式保持一致）。

**⚠️ FC schema 参数名适配**：现有 `load_reference` 的 FC schema 参数名为 `message_id`（`agent_loop.py:292`），但跨会话记忆的引用 ID 是 `session_summary_*` / `summary_group_*`，语义上不是 message。需要将 FC schema 的参数名改为更通用的 `reference_id`（同步更新 `LOAD_REFERENCE_SCHEMA` 和 `agent_loop.py` 中的硬编码参数名 `tool_call.args["message_id"]` → `tool_call.args["reference_id"]`）。LLM 看到 `[REF::summary_group_3]` 时，会自然地调用 `load_reference(reference_id="summary_group_3")`。

### 7.3 回忆过程

```
用户："帮我再查一下上次那个关键词"

助理看到 system prompt 中的全局摘要：
  "用户经常使用百度搜索工具 [REF::summary_group_3]"
  → 需要更多细节，调 load_reference("summary_group_3")

拿到分组摘要：
  "3月20日：搜了Python教程 [REF::session_summary_abc]
   3月22日：搜了招聘信息 [REF::session_summary_def]"
  → 大概率是最近一次，再 load 确认

拿到会话摘要：
  "搜招聘信息 → ✓ 成功，关键词='前端开发'，结果导出Excel [REF::msg_45~msg_52]"
  → 找到了，使用关键词"前端开发"重新执行
```

### 7.4 存储

```
assistant_summaries:
  summary_id    TEXT PK
  level         INT        -- 1=会话摘要, 2=分组摘要, 3=全局摘要
  content       TEXT       -- 摘要内容（含 [REF::xxx] 引用）
  source_ids    JSON       -- 来源 ID 列表（会话ID 或下级摘要ID）
  embedding     BLOB       -- 摘要的向量表示（用于语义搜索）
  created_at    DATETIME
  updated_at    DATETIME
```

### 7.5 memory_search：语义搜索记忆

与 `load_reference`（按 ID 精确查）互补，`memory_search` 解决"不确定在哪"的模糊搜索场景。

参考 openclaw 的混合检索架构：

```
memory_search(query, max_results?, min_score?)
  ├→ 向量检索：query → embedding → 与 assistant_summaries.embedding 做余弦相似度
  ├→ 关键词检索：SQLite FTS5 全文搜索
  └→ 合并排序：score = vector_weight × vector_score + text_weight × text_score
      └→ 时间衰减：越近的摘要权重越高
```

**搜索范围**：assistant_summaries 全部层级（会话摘要、分组摘要、全局摘要），搜到后可用 `load_reference` 进一步下钻。

**FC Schema**：

```json
{
  "type": "function",
  "function": {
    "name": "memory_search",
    "description": "搜索历史记忆。当用户提到之前的对话、任务、偏好，但你不确定具体在哪时使用。返回相关的记忆片段。",
    "parameters": {
      "type": "object",
      "properties": {
        "query": {
          "type": "string",
          "description": "搜索关键词或语义描述"
        },
        "max_results": {
          "type": "integer",
          "description": "最多返回条数，默认5"
        }
      },
      "required": ["query"]
    }
  }
}
```

**Handler 返回格式**：

```json
{
  "results": [
    {
      "summary_id": "session_summary_abc",
      "level": 1,
      "score": 0.82,
      "snippet": "搜招聘信息 → ✓ 成功，关键词='前端开发'，结果导出Excel [REF::msg_45~msg_52]",
      "created_at": "2026-03-22T14:30:00"
    }
  ]
}
```

助理拿到结果后，可以直接使用 snippet 中的信息回答，也可以用 `load_reference` 按 REF ID 下钻获取更多细节。

**Embedding 方案**：采用 auto 降级策略（参考 openclaw），用户零配置即可使用：

```
memory_search 检索策略（auto 模式）：

1. 检测用户是否配置了 embedding API Key（keyring 查）
   → 有 → 混合检索（向量 + FTS5），score = 0.7 × vector_score + 0.3 × text_score
   → 没有 → 降级为 FTS-only（纯关键词搜索），不报错

2. Provider 自动选择优先级：
   → 检测已配置的 API Key，按顺序尝试：OpenAI → 其他
   → 都没有 → FTS-only

3. 向量存储：sqlite-vec 扩展（与现有 SQLite 技术栈一致）

4. 时间衰减：越近的摘要权重越高
```

**用户体验**：不需要额外配置任何 embedding 相关的东西。没有 API Key 时纯关键词搜索也能工作；配了 Key 后自动升级为混合检索，质量更好。

### 7.6 触发时机

| 层级 | 触发条件 | 说明 |
|------|---------|------|
| 会话摘要（第一层） | **用户新建会话时** | 后台异步批量为之前所有未生成摘要的会话生成摘要（不阻塞新会话创建） |
| 会话摘要（第一层） | **12 小时无活动** | 后台定时检查，超时的会话自动生成摘要 |
| 分组摘要（第二层） | **每积累 10 个会话摘要** | 自动将最近 10 个会话摘要精炼为一个分组摘要 |
| 全局摘要（第三层） | **分组摘要更新时** | 自动从所有分组摘要重新精炼全局摘要 |

### 7.7 摘要内容格式

**会话摘要（第一层）**——核心是"用户安排了什么 + 做成了没有"：

```
会话时间：2026-03-25 14:00 ~ 16:30
任务记录：
- 查北京天气 → ✓ 成功（晴，28°C）[REF::msg_101~msg_105]
- 导出3月销售数据到Excel → ✓ 成功 [REF::msg_108,msg_112,msg_115]
- 帮忙写一封邮件给老板请假 → ✓ 成功，用户满意 [REF::msg_116~msg_120]
- 查上海到北京的机票 → ✗ 失败，工具报错已提交修复 [REF::msg_121~msg_125]
使用工具：web_search(2次)、Excel导出(1次)
```

一个任务通常跨多条消息（用户下达 → 确认参数 → 执行 → 结果 → 用户反馈）。REF 引用支持两种格式：
- `msg_101~msg_105`：连续消息范围
- `msg_108,msg_112,msg_115`：不连续的多条消息（中间穿插了其他对话）

结果判断靠 LLM：工具执行成功且用户没抱怨 = 成功；用户说"不对"/"重来" = 失败；工具报错 = 失败。结果详情通过 REF 引用下钻。

**分组摘要（第二层）**——概括一批会话的任务类型和趋势：

```
时间范围：2026-03-20 ~ 2026-03-28
活跃会话：10个
高频任务类型：天气查询(5次)、数据导出(3次)
关键事件：
- 用户开始频繁导出销售数据 [REF::session_summary_abc]
- 天气查询已做成工具 [REF::session_summary_def]
```

**全局摘要（第三层）**——常驻 system prompt，极简概括：

```
用户使用模式：
- 每天早上查天气（已有工具）
- 每周一导出销售数据（已有工具）
- 偶尔问公司政策类问题
高频工具：天气查询、Excel导出、百度搜索
[REF::summary_group_3] [REF::summary_group_4]
```

### 7.8 精炼策略

每层摘要由 LLM 生成，精炼 = 用 LLM 把下层内容压缩成上层格式。

**生成会话摘要的 prompt 要点**：
- 输入：会话的完整消息历史
- 提取：每个用户任务 + 执行结果（成功/失败）+ 用户满意度
- 保留 [REF::msg_X] 引用以便下钻
- 丢弃：具体参数值、工具返回的原始数据

**生成分组摘要的 prompt 要点**：
- 输入：10 个会话摘要
- 提取：高频任务类型、使用趋势、关键事件
- 保留 [REF::session_summary_X] 引用
- 丢弃：单次任务的细节

**生成全局摘要的 prompt 要点**：
- 输入：所有分组摘要
- 提取：用户核心使用模式、高频工具、偏好变化
- 保留 [REF::summary_group_X] 引用
- 控制长度：不超过 500 token（常驻 system prompt，需要省 token）

### 7.9 摘要生成的执行上下文

| 项目 | 方案 |
|------|------|
| LLM 模型 | 使用与助理相同的 LLM 实例（通过 `UnifiedConfig` 获取）。摘要任务简单，不需要单独配置模型。如后续发现成本过高，可降级为更便宜的模型（如 Haiku） |
| 执行线程 | 在 `pending_assistant_tasks` 队列 worker 的同一后台线程中执行（与 bug_report / codify_tool 共享 worker）。摘要生成不紧急，排队执行即可 |
| Token 预算 | 会话摘要 ≤ 300 token、分组摘要 ≤ 500 token、全局摘要 ≤ 500 token。通过 `max_tokens` 参数硬控 |
| 失败处理 | LLM 调用失败时标记 `pending_assistant_tasks` 状态为 `failed`，不重试。下次触发条件满足时会重新生成（幂等）。不阻塞用户正常使用 |
| 并发控制 | 同一时刻只处理一个摘要任务（队列串行消费）。避免多个 LLM 调用并发导致的 API 限流 |

---

## 八、工具沉淀——三条路径

### 8.1 总览

| 路径 | 触发方式 | 输入源 | 后续流程 |
|------|---------|--------|---------|
| 路径 1 | 用户录制浏览器操作 | 录制数据 | PM → 程序员 → 试用 → 发布（现有） |
| 路径 2 | 用户主动说"做成工具" | 助理执行记录 | PM → 程序员 → 试用 → 发布 |
| 路径 3 | 助理检测到重复模式，主动建议 | 助理执行记录（多次） | 同路径 2 |

三条路径共享后半段管线（PM 分析 → 程序员写代码 → 试用 → 发布），区别只在输入源和触发方式。

### 8.2 路径 2：用户主动要求

```
用户："把刚才查天气的操作做成工具"
  → 助理调用 codify_as_tool(task_description)
  → 请求入队，后台 worker 触发 PM（输入 = 执行记录，而非录制数据）
  → PM 分析执行记录 → 提取意图、参数
  → 程序员生成工具代码
  → 试用验证
  → 发布
  → tool_published 事件 → UI 直接推送系统提示到 ChatWidget
```

**工具发布通知**：现有 `tool_published` 事件由 AgentUIBridge 监听并 emit `tool_published_signal`。助理场景下，ChatWidget 收到此信号后直接在对话区插入一条系统提示（如"工具'天气查询'已上线，可以直接使用了"），不经过 AgentLoop。助理下次构建工具列表时自然包含新工具。

**codify_as_tool** FC Schema：

```json
{
  "name": "codify_as_tool",
  "description": "将最近完成的任务做成可复用工具。用户明确要求时调用。",
  "parameters": {
    "type": "object",
    "properties": {
      "task_description": {
        "type": "string",
        "description": "任务的自然语言描述，如'查询指定城市的天气'"
      }
    },
    "required": ["task_description"]
  }
}
```

Handler：从当前会话历史中自动提取执行记录（工具调用链、参数、结果），不依赖 LLM 手动组装，保证质量稳定。

```python
def codify_as_tool(task_description: str, *, _session_id: str) -> str:
    """_session_id 由 handler 闭包绑定，LLM 不需要传"""
    # 从会话消息历史中提取最近的工具调用链
    messages = MessageRepository().get_by_session(_session_id)
    execution_trace = _extract_tool_calls(messages)  # 结构化提取

    # 写入队列而非同步 emit，避免在助理 worker 线程中嵌套执行 PM
    # （与 report_tool_bug 同理，见 6.3 线程安全说明）
    CodifyRequestQueue.enqueue(
        task_description=task_description,
        execution_trace=execution_trace,
    )
    return "已提交工具创建请求，创建完成后会通知你。"
```

**`_extract_tool_calls` 提取策略**：从会话末尾向前扫描，收集最近一轮连续的工具调用（从最后一条用户消息到 codify_as_tool 调用之间的所有 tool_call 消息）。如果用户在同一轮对话中执行了多个不相关任务，LLM 传入的 `task_description` 可作为过滤依据（只保留与描述相关的工具调用）。

**已压缩消息的处理**：长会话中早期消息可能已被压缩归档（`CompressionHandler` 将压缩区消息标记为 archived）。`_extract_tool_calls` 使用 `MessageRepository().get_by_session(_session_id)` 获取**全部消息**（含 archived），但只扫描最近 N 条非 archived 消息（N 取保留区大小，默认约 20 条）。原因：codify_as_tool 场景下用户通常是"刚执行完一个任务就要求做成工具"，相关的工具调用一定在最近的保留区内；如果已经被压缩了，说明距离太远，提取出来的上下文也不准确——这种情况下返回"未找到最近的工具调用记录，请先执行一次该任务再要求做成工具"。

### 8.3 路径 3：自动检测重复模式

助理完成任务后，自动检查记忆中是否存在相似的历史任务。

**检测流程：**

```
助理完成一个任务
  → memory_search(当前任务描述)
  → 返回历史相似任务列表
  → LLM 判断：这些历史任务跟当前任务是同类型的吗？
    → 不是 → 结束
    → 是 → 相似次数 >= 阈值（默认 3 次）？
      → 不够 → 结束
      → 够了 → 检查：这类任务已有对应工具？
        → 有 → 结束
        → 没有 → 检查：之前建议过被拒绝？距上次建议 < N 次？
          → 是 → 结束（避免骚扰）
          → 否 → 建议用户做成工具
```

**建议话术：**

```
"我注意到这是你第三次让我查天气了。要不要把这个做成工具？
以后直接说城市名就行，不用每次都等我一步步查。"
```

**实现机制**：检测流程**不由 LLM 主动驱动**（让 LLM 每次任务后都调 memory_search 会浪费 token 且不可靠）。改为 handler 层自动执行：

1. 每次用户工具执行成功后，`run_tool_code` 返回成功结果时，由 handler 层（不是 LLM）自动触发后台检测
2. 后台检测逻辑（纯代码，不走 LLM）：
   - 查 `tool_suggestion_history` 表，找与当前工具名匹配的记录
   - 如果 `times_seen >= 阈值` 且无对应已发布工具 且不在冷却期 → 在工具执行结果后追加一句建议文本（拼接到 tool result 返回值中），LLM 会自然地转达给用户
3. 用户回复"好" → LLM 调用 `codify_as_tool`；回复"不用" → LLM 调用 `dismiss_suggestion` 记录拒绝

需要新增一个内置工具 `dismiss_suggestion`：

```json
{
  "name": "dismiss_suggestion",
  "description": "用户拒绝了工具化建议时调用，记录拒绝事实。",
  "parameters": {
    "type": "object",
    "properties": {
      "task_pattern": { "type": "string", "description": "被拒绝的任务类型描述" }
    },
    "required": ["task_pattern"]
  }
}
```

4.8 节内置工具汇总表需新增此工具。

**关键设计决策：**

- **检测由代码驱动，不靠 LLM 主动调 memory_search**：可靠且省 token
- **相似判断用工具名匹配**（用户工具执行场景）或任务描述关键词匹配（内置工具执行场景），不用 LLM 判断
- **用户拒绝后冷却**：记录拒绝事实，隔 N 次同类任务后再建议一次（N 可配置，默认 5）
- **阈值可配置**：默认 3 次，存入 assistant_profile 或全局配置

### 8.4 PM 适配

PM 需要能处理两种输入源：

| | 路径 1（录制数据） | 路径 2/3（执行记录） |
|---|---|---|
| 输入格式 | 浏览器操作步骤（click、input、navigate） | 自然语言任务描述 + 工具调用链 |
| PM 分析重点 | 从 DOM 操作推断用户意图 | 从任务描述和工具调用推断可参数化的部分 |
| 输出 | 相同：工具规格（名称、描述、参数、实现思路） | 相同 |

PM 的 system prompt 需要扩展，支持解读执行记录格式。

**注意**：路径 2/3 的执行记录中，工具调用可能是助理的**内置通用工具**（如 `web_search` → `web_fetch` → 手动解析）。PM 需要理解这些内置工具调用的组合，将其转化为一个独立的、不依赖助理内置工具的用户工具代码。例如：助理用 `web_search("北京天气")` + `web_fetch(url)` 完成了天气查询，PM 应输出一个直接调用天气 API 或爬虫的独立工具，而不是"调用 web_search"。PM prompt 中需明确这一点。

其余流程（程序员生成代码、试用验证、发布）完全不变。

### 8.5 拒绝记录存储

```
tool_suggestion_history:
  suggestion_id   TEXT PK
  task_pattern    TEXT       -- LLM 总结的任务类型描述（如"查天气"）
  suggested_at    DATETIME
  accepted        BOOLEAN    -- 用户是否接受
  times_seen      INT        -- 该类型任务已出现次数
```

助理建议前先查此表，判断是否在冷却期。

---

## 九、ChatWidget 接通

### 9.1 当前状态

ChatWidget 是纯 UI 壳子，`on_send_message` 调用 `_simulate_ai_response`（硬编码模拟回复）。

### 9.2 接通方案

```
ChatWidget
  ↓ 用户发消息
  ↓ emit pyqtSignal: user_message_sent(session_id, message)
MainWindow
  ↓ 收到信号
  ↓ 调用 AgentUIBridge.reply_to_agent("assistant", message, session_id=session_id)
AgentUIBridge
  ↓ 后台线程
  ↓ Orchestrator.run_agent("assistant", message, session_id=session_id)
AgentLoop
  ↓ LLM 回复 / 工具调用
  ↓ 返回 AgentResult
Orchestrator
  ↓ NEEDS_USER_INPUT → emit "agent_needs_user_input"（需携带 session_id）
  ↓ COMPLETED → 不调度下游（助理没有下游）
AgentUIBridge
  ↓ blinker → pyqtSignal: question_received（需携带 session_id，用于路由到正确的 ChatWidget）
MainWindow
  ↓ 收到信号
  ↓ 调用 ChatWidget.add_assistant_message(text)
ChatWidget
  ↓ 显示助理回复
```

### 9.3 ChatWidget 需要的改动

- `on_send_message`：不再调 `_simulate_ai_response`，改为 emit 信号给 MainWindow
- 新增 `add_assistant_message(text)`：外部调用，添加助理消息到对话区
- 新增 `set_loading(bool)`：助理思考/工具执行中时显示加载状态
- 新增 `set_session_id(session_id)`：切换会话时更新上下文
- 新增 `load_history(messages)`：切换到历史会话时加载历史消息

**消息排队**：用户在助理执行中（loading 状态）发送的消息进入队列，当前执行完成后自动处理队列中的下一条消息。UI 上输入框保持可用，用户可以继续输入；发送后消息立即显示在对话区（用户气泡），但助理回复需等当前任务完成。AgentUIBridge 维护一个 per-session 消息队列，worker 线程空闲时自动 dequeue。

**与高危工具确认框的交互**：exec/write_file 弹出确认框时，worker 线程阻塞等待确认（见 4.10）。确认框是模态 Dialog（`QDialog.exec()`），**弹出期间 UI 交互被阻塞**，用户必须先处理确认框（确认或拒绝）。确认框关闭后，输入框恢复可用，用户可继续发消息。这是可接受的交互——高危操作需要用户明确决策后才能继续。

### 9.4 侧边栏集成

侧边栏需要展示助理会话列表：
- 新建按钮（+ ）→ 创建新会话（可选工具子集）
- 会话列表 → 点击切换，ChatWidget 加载对应会话
- 每个会话显示：最近一条消息摘要 + 时间

---

## 十、AgentConfig

```python
ASSISTANT_CONFIG = AgentConfig(
    agent_type=AgentType.ASSISTANT,  # 新增枚举值
    system_prompt=ASSISTANT_SYSTEM_PROMPT,  # 含 {profile_section} 和 {tools_section} 占位符
    max_iterations=200,  # 单次 run() 调用内的最大迭代数（每次用户发消息触发一次 run()，
                         # 实际消耗的迭代数 = 工具调用次数 + 1，通常远小于 200；
                         # 设高上限是为了支持复杂任务的长链式工具调用）
    text_as_user_input=True,  # 持续对话，不自然结束
)
```

`text_as_user_input=True`：助理直接返回文字时视为隐式 `talk_to_user`，Loop 返回 `NEEDS_USER_INPUT`，等待用户下一条消息。助理永远不会"自然结束"，只有用户关闭会话。

---

## 十一、文件结构

```
src/
  business/agents/
    agent_loop.py                    # 修改：tools 参数支持 callable，工具列表构建移到 while 循环内（见 4.4）
    config.py                        # 修改：新增 AgentType.ASSISTANT
    prompts/
      assistant_prompt.py            # 新增：ASSISTANT_SYSTEM_PROMPT + 模板格式化
    tools/
      assistant_tools.py             # 新增：report_tool_bug、codify_as_tool、update_profile、
                                     #        search_tools handler、内置通用工具注册
      dynamic_tool_manager.py        # 新增：DynamicToolManager（懒加载 FC 注入 + LRU 淘汰）

  business/orchestration/
    agent_orchestrator.py            # 修改：新增 assistant 类型处理、_build_assistant_tools、
                                     #        run_agent 签名变更（session_id 直传）、
                                     #        pending_assistant_tasks 队列消费 worker（bug_report + codify_tool）
    agent_ui_bridge.py               # 修改：reply_to_agent 签名变更、
                                     #        question_received 信号新增 session_id、
                                     #        per-session 消息排队机制

  business/memory/
    assistant_memory.py              # 新增：跨会话摘要生成（会话摘要、分组摘要、全局摘要）、
                                     #        摘要精炼 prompt、触发时机管理
    memory_search.py                 # 新增：memory_search handler（FTS5 + 可选向量检索）、
                                     #        embedding 降级策略、混合排序

  data/
    models_sqlite.py                 # 修改：Session.workflow_id 改为 nullable、
                                     #        Session 表新增 tool_ids 字段、
                                     #        新增 assistant_profile 表、assistant_summaries 表、
                                     #        tool_suggestion_history 表、pending_assistant_tasks 表
    repositories.py                  # 修改：新增 AssistantProfileRepository、
                                     #        AssistantSummaryRepository、
                                     #        ToolSuggestionRepository、PendingTaskRepository、
                                     #        ToolRepository 新增 get_published() / search_published()

  ui/
    dialogs/
      onboarding_dialog.py           # 新增：首次引导 PyQt Dialog（硬编码表单）
    widgets/
      chat_widget.py                 # 修改：接通 AgentUIBridge，去掉模拟回复
      sidebar_widget.py              # 修改：新增助理会话列表
    main_window.py                   # 修改：连接 ChatWidget 信号与 AgentUIBridge、
                                     #        session_id 路由
```

---

## 十二、实现优先级

| 优先级 | 模块 | 说明 |
|--------|------|------|
| 1 | AgentConfig + Prompt | 助理 Agent 配置、system prompt 模板 |
| 2 | 动态工具懒加载机制 | DynamicToolManager + search_tools / get_tool_detail |
| 3 | Orchestrator 适配 | assistant 类型的会话管理、工具构建、不调度下游 |
| 4 | ChatWidget 接通 | 去掉模拟回复，接通 AgentUIBridge |
| 5 | report_tool_bug | 工具 bug 报告 → PM 分诊流程 |
| 6 | 首次引导流程 | profile 收集、存储、注入 |
| 7 | 内置通用工具 | web_search、web_fetch、cron 等 16 个内置工具实现 |
| 8 | 侧边栏会话列表 | 多会话管理 UI |
| 9 | 新建会话工具选择 | 手动选择工具子集 |
| 10 | 工具沉淀路径 2 | codify_as_tool + PM 适配执行记录输入 |
| 11 | 工具沉淀路径 3 | 重复模式检测 + 自动建议 + 拒绝冷却 |
| 12 | 跨会话记忆 | 层级摘要 + memory_search + load_reference |

---

## 十三、与架构 v2 的关系

办公助理 Agent 是架构 v2 中**未定义**的新模块。它不改变现有的 PM/程序员/试用 Agent 流程，而是在"教技能"流程之上新增了"用技能"的日常入口。

### 复用的现有组件

- **AgentLoop**：需小幅改动——`tools` 参数支持 callable，工具列表构建移到 while 循环内部（见 4.4 节）。改动向后兼容，传入 list 时行为不变
- **tool_executor.run_tool_code**：原样复用
- **记忆机制**（引用替换、压缩）：原样复用
- **AgentUIBridge**：需适配——签名变更（session_id 参数）、pyqtSignal 新增 session_id、per-session 消息排队机制
- **PM 分诊流程**：report_tool_bug 触发的修复复用现有 `_start_triage` 路径
- **PM/程序员/试用 Agent**：完全不动，保持现有 FC 工具注册

### 新增的概念

| 概念 | 说明 |
|------|------|
| AgentType.ASSISTANT | 第四种 Agent 类型 |
| DynamicToolManager | 用户工具的懒加载 FC 注入管理器 |
| search_tools / get_tool_detail | 辅助工具，用于发现和激活用户动态工具 |
| 动态工具集 | 用户工具从 DB 查询，get_tool_detail 后动态注入 FC schema |
| assistant_profile | 用户偏好档案，影响 system prompt |
| assistant_summaries | 跨会话记忆存储 |
| report_tool_bug | 从日常使用触发修复流程的桥梁 |
| codify_as_tool | 从助理执行记录触发工具创建（路径 2/3） |
| tool_suggestion_history | 工具建议记录（拒绝冷却机制） |

---

## 待定事项

| 事项 | 说明 | 状态 |
|------|------|------|
| ~~首次引导是否走 AgentLoop~~ | 硬编码 UI 表单，参考 nanobot/openclaw 均采用确定性流程 | **已确定** |
| ~~内置通用工具列表~~ | 16 个内置工具 + search_tools / get_tool_detail 辅助工具 | **已确定** |
| ~~工具调用机制~~ | 保持 FC，用户动态工具通过 DynamicToolManager 懒加载 FC 注入。参考 nanobot/openclaw 均保留 FC 作为基础调用机制 | **已确定** |
| ~~工具沉淀三条路径~~ | 路径 1 录制、路径 2 用户主动、路径 3 自动检测重复模式 | **已确定** |
| ~~跨会话记忆细节~~ | 触发：新建会话时批量生成 + 12h 超时自动生成；分组每 10 个会话；全局随分组更新。摘要格式：任务 + 结果（成功/失败）+ REF 引用 | **已确定** |
| ~~memory_search 的 embedding 方案~~ | auto 降级策略：有 API Key 用混合检索（向量 + FTS5），没有降级 FTS-only。向量存储用 sqlite-vec。参考 openclaw 的 auto 模式 | **已确定** |

---

---

## 参考项目

| 项目 | 语言 | Agent 循环 | 记忆 | 首次引导 | 启示 |
|------|------|-----------|------|---------|------|
| [nanobot](https://github.com/nano-bot/nanobot) | Python | 简单 while 循环 + ToolRegistry + MessageBus | 两层文本文件（MEMORY.md + HISTORY.md），LLM 提取摘要 | 传统 CLI 问答 | Tools（FC）+ Skills（SKILL.md 知识层，按需 read_file 加载）双层架构 |
| [openclaw](https://github.com/openclaw/openclaw) | TypeScript | 复杂的 embedded runner + failover/auth rotation | 向量 + 关键词混合搜索（sqlite-vec + FTS5） | 传统 Wizard 表单 | 同样 Tools（FC）+ Skills 双层；Skills 有 token 预算控制（full → compact → truncate） |

---

*初版设计，记录时间：2026-03-25*
*更新：2026-03-25 — 根据 nanobot/openclaw 参考确认首次引导方案、工具调用机制（FC + 懒加载），补充参考项目表*
