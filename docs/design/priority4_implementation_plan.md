# 优先级4 实现计划

## 概述

本文档为优先级4（事件系统 + 流程编排）的实现计划，基于六轮自审后的最终版本。

依赖设计文档：[event_system_design.md](event_system_design.md)

---

## 现有代码与设计的差距

| 文件 | 问题 |
|------|------|
| `src/utils/events.py` | `emit()` 用 `signal.send()` 而非 `send_robust()`，缺少 10 个 Agent 业务事件 |
| `src/data/models_sqlite.py` | `Tool` 缺 `workflow_id`、`trial_success_count`、`status` 字段；`WorkflowTransition.to_session_id` 声明为 `NOT NULL`（应可空） |
| `src/data/migrations.py` | `migrate_to_v3` 建 `workflow_transitions` 时 `to_session_id TEXT NOT NULL`；缺 v4 迁移（tools 表扩展） |
| `src/data/repositories.py` | `SessionRepository.get_by_workflow()` 缺 `agent_type`/`order_by` 参数；`ToolRepository` 缺 4 个新方法 |
| `src/business/agents/agent_loop.py` | 循环内发 8 处 `emit_event()`（设计要求 Loop 纯引擎不发事件）；session 恢复只检查 `"suspended"` 未包含 `"completed"` |
| `src/business/agents/events.py` | 维护独立 Namespace 和旧事件定义，应改为从 `src/utils/events.py` 导入 |
| `src/business/agents/__init__.py` | 导出了 `emit_event`，改完 `events.py` 后会引发 `AttributeError` |
| `tests/test_agents/test_agent_loop.py` | `test_events_emitted` patch 了 `emit_event` 并断言旧事件，需更新为验证 Loop 不发事件 |

---

## 变更清单

### Step 1 — 数据层修复

#### `src/data/models_sqlite.py`

**`Tool` 模型新增三个字段：**

```python
workflow_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
trial_success_count: Mapped[int] = mapped_column(Integer, default=0)
status: Mapped[str] = mapped_column(String(20), default="pending")
```

**`WorkflowTransition.to_session_id` 改为可空：**

```python
# 修改前
to_session_id: Mapped[str] = mapped_column(String(50), nullable=False)

# 修改后
to_session_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
```

#### `src/data/migrations.py`

**修复 `migrate_to_v3`**：`workflow_transitions` 建表改用 `DROP TABLE IF EXISTS` + `CREATE TABLE`（消除 `NOT NULL` 约束，空表安全）：

```python
# DROP + CREATE workflow_transitions（修复 to_session_id NOT NULL）
cursor.execute("DROP TABLE IF EXISTS workflow_transitions")
cursor.execute("""
    CREATE TABLE workflow_transitions (
        transition_id TEXT PRIMARY KEY,
        workflow_id   TEXT NOT NULL,
        from_session_id TEXT,
        to_session_id   TEXT,          -- 可空：外部触发时无来源
        event_type    TEXT NOT NULL,
        payload       TEXT,
        created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
""")
```

**新增 `migrate_to_v4`**：为 `tools` 表增加三个字段：

```python
def migrate_to_v4(db_manager):
    conn = db_manager.connect()
    cursor = conn.cursor()
    try:
        for col, definition in [
            ("workflow_id",          "TEXT"),
            ("trial_success_count",  "INTEGER DEFAULT 0"),
            ("status",               "TEXT DEFAULT 'pending'"),
        ]:
            try:
                cursor.execute(f"ALTER TABLE tools ADD COLUMN {col} {definition}")
            except sqlite3.OperationalError:
                pass  # 列已存在，忽略
        cursor.execute("UPDATE schema_version SET version = 4")
        conn.commit()
        logger.info("数据库迁移到版本 4 完成：tools 表新增 workflow_id、trial_success_count、status")
    except sqlite3.Error as e:
        conn.rollback()
        raise
```

**更新 `run_migrations`**：在末尾追加：

```python
if current_version < 4:
    migrate_to_v4(db_manager)
    logger.info(f"数据库迁移完成：{db_manager.get_version() - 1} -> 4")
```

---

### Step 2 — Repository 扩展

#### `src/data/repositories.py`

**`SessionRepository.get_by_workflow` 加参数：**

```python
def get_by_workflow(
    self,
    workflow_id: str,
    agent_type: Optional[str] = None,
    order_by: Optional[str] = None,
) -> List[Session]:
    query = self.session.query(Session).filter(Session.workflow_id == workflow_id)
    if agent_type:
        query = query.filter(Session.agent_type == agent_type)
    if order_by == "created_at_desc":
        query = query.order_by(Session.created_at.desc())
    else:
        query = query.order_by(Session.created_at)
    return query.all()
```

**`ToolRepository` 新增 4 个方法：**

```python
def get_by_workflow_id(self, workflow_id: str) -> Optional[Tool]:
    return self.session.query(Tool).filter(Tool.workflow_id == workflow_id).first()

def update_code(self, tool_id: str, code: str):
    tool = self.get_by_id(tool_id)
    if tool:
        tool.execution_code = code
        tool.updated_at = datetime.now()
        self.session.commit()

def update_trial_success_count(self, tool_id: str, count: int):
    tool = self.get_by_id(tool_id)
    if tool:
        tool.trial_success_count = count
        self.session.commit()

def update_status(self, tool_id: str, status: str):
    tool = self.get_by_id(tool_id)
    if tool:
        tool.status = status
        self.session.commit()
```

---

### Step 3 — 事件系统统一

#### `src/utils/events.py`

**`emit()` 改为 `send_robust` + 自动注入 `event_name`：**

```python
def emit(event_name: str, sender: Any = None, **kwargs) -> None:
    signal = _signals.signal(event_name)
    results = signal.send_robust(sender, event_name=event_name, **kwargs)
    for receiver, result in results:
        if isinstance(result, Exception):
            logger.error(f"[Events] 监听器 {receiver.__name__} 处理 {event_name} 时异常: {result}")
```

**新增 10 个 Agent 业务事件**（在现有信号定义区域末尾追加）：

```python
# Agent 交互事件
agent_needs_user_input = _signals.signal("agent_needs_user_input")
agent_error            = _signals.signal("agent_error")

# Agent 协作事件
requirement_confirmed = _signals.signal("requirement_confirmed")
code_completed        = _signals.signal("code_completed")
review_passed         = _signals.signal("review_passed")
review_failed         = _signals.signal("review_failed")
tool_saved            = _signals.signal("tool_saved")
trial_success         = _signals.signal("trial_success")
trial_failed          = _signals.signal("trial_failed")
triage_completed      = _signals.signal("triage_completed")
```

同步更新 `list_signals()`、`clear_all()`、`__all__` 将新信号纳入。

#### `src/business/agents/events.py`

清空文件，改为：

```python
"""
Agent 事件 — 从统一事件系统导入

所有 Agent 相关事件统一在 src/utils/events.py 中定义。
"""
from src.utils.events import emit, connect

__all__ = ["emit", "connect"]
```

---

### Step 4 — Agent Loop 净化

#### `src/business/agents/agent_loop.py`

- 删除 `from .events import emit_event` import 行
- 删除循环内全部 8 处 `emit_event(...)` 调用：
  - `agent_iteration_started`（iteration 开始）
  - `agent_completed`（正常完成）
  - `agent_error`（LLM 调用失败）
  - `agent_needs_user_input`（talk_to_user 哨兵）
  - `agent_tool_executed`（工具执行成功）
  - `agent_tool_failed`（工具执行失败）
  - `agent_iteration_completed`（iteration 结束）
  - `agent_error`（超迭代次数）
- session 恢复逻辑改为同时接受 `completed` 状态（支持 session 复用）：

```python
# 修改前
if ctx.get_session_status() == "suspended":

# 修改后
if ctx.get_session_status() in ("suspended", "completed"):
```

#### `src/business/agents/__init__.py`

- 删除 `from .events import emit_event`
- 删除 `__all__` 中的 `"emit_event"`

---

### Step 5 — 测试更新

#### `tests/test_agents/test_agent_loop.py`

将 `test_events_emitted` 更新为验证 Loop 不发事件：

```python
@patch("src.business.agents.agent_loop.ContextManager")
@patch("src.business.agents.agent_loop.MessageRepository")
def test_no_events_emitted_by_loop(self, mock_msg_repo_cls, mock_ctx_cls):
    """Loop 是纯执行引擎，不发任何业务事件（由 Orchestrator 发）"""
    mock_ctx = MagicMock()
    mock_ctx_cls.return_value = mock_ctx
    mock_ctx.get_session_status.return_value = None
    mock_ctx.assemble_context.return_value = [{"role": "system", "content": "test"}]
    mock_ctx.save_message.return_value = None
    mock_ctx.update_session_status.return_value = None

    mock_msg_repo = MagicMock()
    mock_msg_repo.get_first.return_value = None
    mock_msg_repo_cls.return_value = mock_msg_repo

    self.mock_llm.chat_with_tools.return_value = LLMResponse(content="完成", tool_calls=[])

    with patch("src.utils.events.emit") as mock_emit:
        loop = AgentLoop(self.test_config, self.mock_llm, self.mock_config)
        loop.run("test-session")
        mock_emit.assert_not_called()
```

---

### Step 6 — 新建 orchestration 目录

目录结构：

```
src/business/orchestration/
    __init__.py
    llm_reviewer.py        # LLM 代码质量 Review
    agent_orchestrator.py  # Agent 编排器（核心）
    agent_ui_bridge.py     # UI 线程桥接
```

#### `src/business/orchestration/__init__.py`

```python
from .agent_orchestrator import AgentOrchestrator
from .agent_ui_bridge import AgentUIBridge
from .llm_reviewer import LLMReviewer, ReviewResult

__all__ = ["AgentOrchestrator", "AgentUIBridge", "LLMReviewer", "ReviewResult"]
```

#### `src/business/orchestration/llm_reviewer.py`

- `ReviewResult(passed: bool, feedback: str)` 数据类
- `LLMReviewer(llm_client)` 类，`review(code: str) -> ReviewResult` 方法
- 调用 LLM 对代码做质量评审，提示词要求返回 JSON `{"passed": bool, "feedback": str}`

#### `src/business/orchestration/agent_orchestrator.py`

完整实现 `AgentOrchestrator`，包含：

| 方法 | 说明 |
|------|------|
| `__init__(llm_client, config, llm_reviewer=None)` | 初始化，缓存 `_loops`、`_review_counts`、Repositories |
| `run_agent(agent_type, user_input, workflow_id)` | 核心入口：获取 session → 运行 Loop → 根据结果发事件/调度 |
| `_dispatch_next(agent_type, result, session_id, workflow_id)` | 显式调度：pm→`_on_pm_completed`，programmer→`_on_programmer_completed` |
| `_on_pm_completed(result, session_id, workflow_id)` | 解析成功→`requirement_confirmed`；解析失败→`triage_completed`；均转程序员 |
| `_on_programmer_completed(result, session_id, workflow_id)` | 提取代码→`code_completed`→启动 Review |
| `_on_trial_completed(result, session_id, workflow_id)` | `pass`（依赖优先级7 Trial Agent 设计） |
| `_run_review(code, from_session_id, workflow_id)` | Review → 通过则入库；失败 <3 次回传程序员；≥3 次强制入库 |
| `_save_tool(code, workflow_id, session_id, status)` | 按 `workflow_id` 查重，存在则更新代码+清零试用计数，不存在则创建 |
| `handle_trial_result(tool_id, success, workflow_id, session_id, user_feedback)` | 成功累计计数；失败触发分诊 |
| `_start_triage(tool_id, user_feedback, workflow_id)` | 构造分诊 prompt，调 `run_agent("pm", ...)` |
| `_get_or_create_session(workflow_id, agent_type)` | 复用规则：suspended/completed/active→复用，failed→新建 |
| `_create_session(workflow_id, agent_type)` | 构造 `Session` model，调 `_session_repo.create(model)` |
| `_get_loop(agent_type)` | 缓存复用 `AgentLoop` 实例 |
| `_parse_requirements(output)` | 尝试 JSON 解析 → markdown 代码块提取 → 失败抛 `ValueError` |
| `_extract_code(output)` | 从 markdown 代码块提取 Python 代码，失败返回原文 |

**注意**：
- `WorkflowTransition` 的 `payload` 字段存储前须 `json.dumps(payload_dict)`
- `_loops: Dict[str, AgentLoop]` 按 `agent_type` 缓存，`AgentLoop` 内部的 `_ctx_cache` 按 `session_id` 缓存，session 复用时自动复用已有上下文

#### `src/business/orchestration/agent_ui_bridge.py`

- `AgentWorker(QObject)` — 后台线程执行体，持有 orchestrator 引用
  - `self.finished = pyqtSignal()` 完成信号
  - `run()` 调用 `orchestrator.run_agent(...)`，finally 发 `finished`
- `AgentUIBridge(QObject)` — UI 与 Orchestrator 的桥梁
  - PyQt 信号：`question_received`、`error_occurred`、`progress_updated`、`tool_saved_signal`
  - `__init__` 用 `connect()` 监听 10 个 blinker 事件，转换为 PyQt 信号
  - `start_agent(agent_type, user_input, workflow_id)` — 检查上一线程，创建 `QThread` + `AgentWorker`，**同时存储 `self._worker = worker`（防 GC 回收）**
  - `reply_to_agent(agent_type, user_input, workflow_id)` — 复用 `start_agent`
  - 事件监听器 `_on_needs_user_input`、`_on_error`、`_on_progress`、`_on_tool_saved` — 从 `kwargs` 取 `event_name`（由 `emit()` 自动注入）

---

## 完整变更清单

| 操作 | 文件 | 关键变更 |
|------|------|---------|
| 修改 | `src/data/models_sqlite.py` | `Tool` 加 3 字段；`WorkflowTransition.to_session_id` 改 `Optional` |
| 修改 | `src/data/migrations.py` | v3 精确修复 `workflow_transitions`；新增 v4 ALTER TABLE tools |
| 修改 | `src/data/repositories.py` | `SessionRepository.get_by_workflow` 加参数；`ToolRepository` 加 4 方法 |
| 修改 | `src/utils/events.py` | `emit()` 改 `send_robust` + 注入 `event_name`；加 10 个 Agent 事件 |
| 修改 | `src/business/agents/events.py` | 清空，只 re-export `emit`/`connect` |
| 修改 | `src/business/agents/agent_loop.py` | 删 import + 8 处 `emit_event`；session 恢复加 `"completed"` |
| 修改 | `src/business/agents/__init__.py` | 删 `emit_event` 导入和导出 |
| 修改 | `tests/test_agents/test_agent_loop.py` | `test_events_emitted` → `test_no_events_emitted_by_loop` |
| 新建 | `src/business/orchestration/__init__.py` | 导出 3 个类 |
| 新建 | `src/business/orchestration/llm_reviewer.py` | `LLMReviewer` + `ReviewResult` |
| 新建 | `src/business/orchestration/agent_orchestrator.py` | `AgentOrchestrator` 完整实现 |
| 新建 | `src/business/orchestration/agent_ui_bridge.py` | `AgentWorker` + `AgentUIBridge` |

---

## 实现顺序

按依赖顺序：Step 1 → Step 2 → Step 3 → Step 4 → Step 5 → Step 6

各 Step 内部无依赖，Step 3 和 Step 4 可并行。

---

*计划版本：经六轮自审，2026-03-17*
