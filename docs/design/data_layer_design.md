# 数据层设计

本文档为架构 v2 的数据层细化设计，定义会话管理和消息存储的表结构、Repository 接口及迁移方案。

---

## 一、表结构

### 1. sessions — 会话表

每次 Agent 运行对应一个 session。同一次录制触发的所有 session 共享 `workflow_id`。

```sql
CREATE TABLE sessions (
    session_id    TEXT PRIMARY KEY,
    workflow_id   TEXT NOT NULL,
    agent_type    TEXT NOT NULL,                    -- 'pm' | 'programmer' | 'trial'
    status        TEXT NOT NULL DEFAULT 'active',   -- 'active' | 'completed' | 'suspended' | 'failed'
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_sessions_workflow ON sessions(workflow_id);
CREATE INDEX idx_sessions_agent_type ON sessions(agent_type);
CREATE INDEX idx_sessions_status ON sessions(status);
```

**设计说明：**
- `workflow_id` — 第一个 PM session 创建时生成，后续所有 session 继承。查询某次录制的完整协作链路：`WHERE workflow_id = ? ORDER BY created_at`
- 不设 `parent_session_id` — 多 Agent 反复协作（A→B→A）时 parent 语义模糊，workflow_id + created_at 足以还原时间线
- 不存 recording_id、tool_id 等业务关联 — 这些信息通过消息内容传递（如 PM 输出的需求 JSON 作为程序员 session 的第一条消息）

### 2. messages — 消息表

存储每条消息，字段对齐 LLM API 的消息格式。

```sql
CREATE TABLE messages (
    message_id       TEXT PRIMARY KEY,
    session_id       TEXT NOT NULL,
    sequence         INTEGER NOT NULL,
    role             TEXT NOT NULL,                    -- 'system' | 'user' | 'assistant' | 'tool' | 'summary'
    content          TEXT,
    message_type     TEXT DEFAULT 'normal',            -- 'normal' | 'compressed'
    tool_call_id     TEXT,
    tool_name        TEXT,
    tool_calls       TEXT,                             -- JSON: assistant 消息的 tool_calls 数组
    compressed_range TEXT,                             -- 'X-Y' 表示压缩了第 X 到 Y 条消息
    is_archived      INTEGER DEFAULT 0,
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
);

CREATE INDEX idx_messages_session ON messages(session_id, sequence);
CREATE INDEX idx_messages_archived ON messages(session_id, is_archived);
```

**设计说明：**
- `sequence` — 会话内顺序号，从 1 开始，保证消息加载顺序
- `role` — 对应 LLM API 消息角色（system/user/assistant/tool），另有 `summary` 角色专用于压缩摘要消息。`summary` 在发给 LLM 时映射为 `system` 角色
- `tool_call_id` / `tool_name` — tool 角色消息必备字段
- `tool_calls` — assistant 消息中的工具调用请求（JSON 数组）
- `is_archived` — 被压缩后的原始消息标记为 1，加载上下文时跳过

### 3. workflow_transitions — 协作交接记录表

记录 Agent 之间的交接事件，供未来调度模型分析协作模式。

```sql
CREATE TABLE workflow_transitions (
    transition_id    TEXT PRIMARY KEY,
    workflow_id      TEXT NOT NULL,
    from_session_id  TEXT,                            -- NULL 表示流程起点（如录制完成触发）
    to_session_id    TEXT,                            -- NULL 表示无明确目标会话（如 code_completed、agent_error）
    event_type       TEXT NOT NULL,                   -- 触发事件类型
    payload          TEXT,                            -- JSON: 交接携带的关键数据摘要
    created_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_transitions_workflow ON workflow_transitions(workflow_id);
```

**设计说明：**
- `workflow_id` — 与 sessions 表一致，贯穿从录制到工具生成到执行成功的完整链路
- `event_type` — 如 `recording_completed`、`requirement_confirmed`、`code_completed`、`trial_failed`、`triage_completed` 等（事件名称见架构 v2 第五节）
- `payload` — 交接的关键摘要（如失败原因、确认的需求要点），不存完整数据（完整数据在消息里）
- `from_session_id` 为 NULL 表示外部触发（如录制完成是流程起点，不来自某个 Agent session）
- 查询完整协作链路：`WHERE workflow_id = ? ORDER BY created_at`

---

## 二、消息类型

`messages.message_type` 区分两种类型：

### normal — 普通消息
- Agent 回复、用户输入、系统提示、工具调用结果
- 加载上下文时正常包含

### compressed — 压缩消息
- 对第 X-Y 条消息的摘要
- `compressed_range` = "X-Y"
- 被压缩的原始消息（第 X-Y 条）标记 `is_archived = 1`
- 加载上下文时，archived 消息被跳过，compressed 消息替代它们

---

## 三、引用机制

**引用替换不在数据层实现。** 数据层始终存储原始完整内容。

引用机制是记忆层（优先级 2）的运行时行为：
- Agent Loop 加载上下文时，对 N 步之前、超过大小阈值的 tool 消息，运行时替换为指针文本发给 LLM
- Agent 调用 `load_reference` 时，通过 `MessageRepository.get_by_id()` 读取原始消息内容
- 不需要额外的引用表

---

## 四、上下文加载

加载会话上下文的规则：

```python
def load_context(session_id: str) -> List[dict]:
    """加载会话上下文，返回 LLM API 格式的消息列表"""
    messages = (
        db.query(Message)
        .filter(
            Message.session_id == session_id,
            Message.is_archived == 0,
        )
        .order_by(Message.sequence)
        .all()
    )
    return [msg.to_llm_format() for msg in messages]
```

---

## 五、Fork 操作

编辑消息或从某条消息分叉，本质是同一操作：

1. 创建新 session（同一 workflow_id）
2. 复制原 session 的第 1 到 N 条消息到新 session
3. 所有 ID 换新（message_id），session_id 指向新 session
4. 新 session 从 sequence = N+1 继续

**注意：** 引用指针中的 message_id 指向原始会话的消息。`load_reference` 通过 `get_by_id()` 全局查找，不限于当前 session，因此 fork 后引用仍然有效，不需要特殊处理。

---

## 六、Repository 接口

### SessionRepository

```python
class SessionRepository:
    def create(session) -> Session
    def get_by_id(session_id) -> Optional[Session]
    def get_by_workflow(workflow_id, agent_type=None, order_by=None) -> List[Session]
    def update_status(session_id, status)
```

### MessageRepository

```python
class MessageRepository:
    def create(message) -> Message
    def get_by_id(message_id) -> Optional[Message]
    def get_first(session_id) -> Optional[Message]   # 获取 sequence 最小的消息
    def get_context(session_id) -> List[Message]
    def get_all(session_id) -> List[Message]
    def get_next_sequence(session_id) -> int
    def mark_archived(session_id, from_seq, to_seq)
    def bulk_copy(from_session_id, to_session_id, up_to_sequence)
```

### WorkflowTransitionRepository

```python
class WorkflowTransitionRepository:
    def create(transition) -> WorkflowTransition
    def get_by_workflow(workflow_id) -> List[WorkflowTransition]
```

---

## 七、与现有表的关系

### 保留并扩展
- `tools` — 工具定义，新增以下列：
  - `workflow_id TEXT` — 关联工作流 ID，用于按 workflow 查找/更新已有工具
  - `trial_success_count INTEGER DEFAULT 0` — 试用成功计数，3 次成功后发布
  - 新增 ToolRepository 方法：`get_by_workflow_id(workflow_id)`、`update_code(tool_id, code)`、`update_trial_count(tool_id, count)`
- `task_executions` — 执行记录
- `app_settings` / `user_preferences` — 配置
- `intents` / `pending_tools` / `tool_trials` — v2 迁移创建的表

### 废弃
- `conversations` — 被 sessions + messages 替代，保留但不再写入

### 新增
- `sessions` — 会话管理
- `messages` — 消息存储
- `workflow_transitions` — Agent 协作交接记录

---

## 八、迁移方案

在 `src/data/migrations.py` 新增 `migrate_to_v3`：
- 创建 sessions、messages、workflow_transitions 三张表及索引
- 扩展 tools 表：`ALTER TABLE tools ADD COLUMN workflow_id TEXT`、`ALTER TABLE tools ADD COLUMN trial_success_count INTEGER DEFAULT 0`
- 更新 schema_version 到 3
- 不迁移旧 conversations 数据

---

*基于架构 v2 细化，记录时间：2026-03-12*
