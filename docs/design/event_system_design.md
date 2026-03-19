# 事件系统与流程编排设计

本文档为架构 v2 优先级4的细化设计，定义 Agent 协作事件、事件数据格式、AgentOrchestrator 的职责、AgentUIBridge 的线程模型及调度逻辑。

依赖：[Agent Loop 设计](agent_loop_design.md)

---

## 一、整体定位

事件系统是 Orchestrator 与外部模块（UI、日志、持久化）之间的解耦通信机制。Orchestrator 发出业务事件，外部模块监听并做出响应。

**一个录制对应一个工作流，生成一个工具。**

```
UI 层（PyQt）
    ↕ PyQt 信号
AgentUIBridge（线程管理）
    ↓ 调用
AgentOrchestrator（编排器）
    ↓ 调用 loop.run()          ↓ 发出业务事件
AgentLoop（执行引擎）        UI / 日志 / transition 记录
    ↓                          （监听事件）
ContextManager / LLM
```

**两层通信机制：**

| 通信 | 机制 | 说明 |
|------|------|------|
| Loop → Orchestrator | return AgentResult | 内部通信，函数调用返回值 |
| Orchestrator → 外部 | blinker 事件 | 跨模块解耦通知，UI/日志/持久化各自监听 |

**关键设计决策：Loop 不发事件。** Loop 是纯执行引擎，只负责跑循环和返回结果。所有事件由 Orchestrator 在收到 result 后发出。这避免了 blinker 同步回调导致的嵌套执行问题（详见第十三节差异说明）。

---

## 二、业务事件定义

所有事件由 Orchestrator 发出，定义在 `src/utils/events.py` 中（统一 Namespace）。

### 2.1 交互事件

| 事件名称 | 触发时机 | 说明 |
|---------|---------|------|
| `agent_needs_user_input` | Agent 调用 talk_to_user | UI 展示问题，等待用户回复 |
| `agent_error` | Agent 执行失败 | UI 展示错误信息 |

### 2.2 协作事件

| 事件名称 | 触发时机 | 说明 |
|---------|---------|------|
| `requirement_confirmed` | PM 完成需求确认 | 触发程序员 Agent |
| `code_completed` | 程序员写完代码 | 触发 LLM Review |
| `review_passed` | LLM Review 通过 | 触发工具入库 |
| `review_failed` | LLM Review 不通过 | 触发程序员修改 |
| `tool_saved` | 工具入库（pending 状态） | 通知 UI |
| `trial_success` | 试用成功 | 累计计数，满 3 次发布 |
| `trial_failed` | 试用失败 | 触发 PM 分诊 |
| `triage_completed` | PM 分诊判定为代码问题 | 转给程序员排查（需求问题走 requirement_confirmed） |

**不再有 `agent_completed` 事件。** Loop 完成后 Orchestrator 直接发业务事件（如 `requirement_confirmed`），不需要先发一个通用的"完成"再转换。

---

## 三、事件数据格式

### 3.1 agent_needs_user_input

```python
{
    "workflow_id": str,             # 工作流 ID
    "session_id": str,              # 会话 ID
    "agent_type": str,              # Agent 类型（pm / programmer / trial）
    "question": str                 # Agent 向用户提出的问题
}
```

### 3.2 agent_error

```python
{
    "workflow_id": str,
    "session_id": str,
    "agent_type": str,
    "error": str,                   # 错误信息
    "error_type": str               # "error" / "max_iterations_reached"
}
```

### 3.3 requirement_confirmed

```python
{
    "workflow_id": str,
    "session_id": str,              # PM 会话 ID
    "requirements_json": {
        "goal": str,
        "recording_id": str,
        "parameters": [
            {
                "name": str,
                "description": str,
                "recorded_value": Optional[str],
                "type": str         # "variable" / "fixed"
            }
        ]
    }
}
```

### 3.4 code_completed

```python
{
    "workflow_id": str,
    "session_id": str,              # 程序员会话 ID
    "code": str
}
```

### 3.5 review_passed

```python
{
    "workflow_id": str,
    "session_id": str,
    "code": str
}
```

### 3.6 review_failed

```python
{
    "workflow_id": str,
    "session_id": str,
    "code": str,
    "feedback": str,
    "retry_count": int
}
```

### 3.7 tool_saved

```python
{
    "workflow_id": str,
    "session_id": str,
    "tool_id": str
}
```

### 3.8 trial_success

```python
{
    "workflow_id": str,
    "session_id": str,              # 试用会话 ID
    "tool_id": str,
    "success_count": int,           # 累计成功次数（1-3）
    "published": bool               # 是否已达 3 次并发布
}
```

### 3.9 trial_failed

```python
{
    "workflow_id": str,
    "session_id": str,
    "tool_id": str,
    "user_feedback": str
}
```

### 3.10 triage_completed

仅在 PM 分诊判定为代码问题时发出。需求问题时 PM 走 talk_to_user 重新确认，走正常 requirement_confirmed 流程，不发 triage_completed。

```python
{
    "workflow_id": str,
    "session_id": str,              # PM 会话 ID
    "triage_result": "code_issue",  # 目前只有 code_issue 会触发此事件
    "feedback": str                 # PM 转发给程序员的用户反馈
}
```

---

## 四、事件使用场景

### 4.1 正常工作流

```
用户录制 → UI 传 workflow_id 给 Orchestrator
→ Orchestrator 启动 PM Agent Loop
    → PM 多轮 talk_to_user（每轮 emit agent_needs_user_input）
    → 用户回复 → Orchestrator 恢复 PM Loop
    → PM 完成 → loop.run() 返回 COMPLETED
→ Orchestrator 发 requirement_confirmed → _dispatch_next 启动程序员
    → 程序员完成 → loop.run() 返回 COMPLETED
→ Orchestrator 发 code_completed → 启动 LLM Review
    → review_passed → 工具入库
→ Orchestrator 发 tool_saved → UI 通知
→ 用户试用
    → trial_success ×3 → 工具发布
```

### 4.2 Review 失败重试

```
程序员完成 → code_completed → LLM Review
→ review_failed (retry_count=1) → 恢复程序员修改
→ 程序员完成 → code_completed → LLM Review
→ review_failed (retry_count=2) → 恢复程序员修改
→ ...
→ review_failed (retry_count=3) → 强制入库（pending）
→ tool_saved
```

### 4.3 试用失败分诊

```
用户试用工具 → trial_failed → 恢复 PM session（自动复用）

→ PM 判断是代码问题
    → PM 调用 report_code_issue(feedback="...")
    → _on_pm_completed 检测 signal_tool.name == "report_code_issue"
    → triage_completed (code_issue) → 恢复程序员 session（自动复用）
    → 程序员排查修复 → code_completed → review_passed → 更新工具（清零试用计数）

→ PM 判断是需求问题
    → PM 调 talk_to_user 跟用户重新确认需求
    → PM 调用 submit_requirements(...)
    → _on_pm_completed 检测 signal_tool.name == "submit_requirements"
    → requirement_confirmed → 恢复程序员 session → 程序员按新需求重写
```

---

## 五、事件接收者

### 5.1 UI 展示

- 监听 `agent_needs_user_input`，展示问题给用户
- 监听 `agent_error`，展示错误给用户
- 监听协作事件，展示进度（如"需求已确认"、"代码已完成"）
- 监听 `tool_saved`，通知用户工具已入库
- 监听 `trial_success`，显示试用进度和发布状态

### 5.2 workflow_transitions 表

Orchestrator 在发出事件的同时，将关键事件记录到 `workflow_transitions` 表。

| 记录的事件类型 | from_session_id | to_session_id | 说明 |
|--------------|----------------|---------------|------|
| `requirement_confirmed` | PM 会话 ID | 程序员会话 ID | PM → 程序员 |
| `code_completed` | 程序员会话 ID | — | 程序员完成 |
| `review_passed` | — | — | Review 通过 |
| `review_failed` | — | 程序员会话 ID | Review → 程序员修改 |
| `tool_saved` | — | — | 工具入库 |
| `trial_success` | 试用会话 ID | — | 试用成功 |
| `trial_failed` | 试用会话 ID | PM 会话 ID | 试用 → PM 分诊（session 复用） |
| `triage_completed` | PM 会话 ID | 程序员会话 ID | 代码问题 → 程序员排查（session 复用） |
| `agent_error` | 失败会话 ID | — | Agent 执行失败 |

**注意**：`to_session_id` 在已知目标会话时填入（如 requirement_confirmed 时程序员会话已创建），未知时为 NULL。

---

## 六、会话状态转换

### 6.1 状态流转

```
active → suspended（遇到 talk_to_user，loop.run() 返回 NEEDS_USER_INPUT）
suspended → active（Orchestrator 再次调用 loop.run() 时自动恢复）
active → completed（正常完成，loop.run() 返回 COMPLETED）
active → failed（错误或超迭代，loop.run() 返回 ERROR / MAX_ITERATIONS_REACHED）
completed → active（复用 session：review 打回、分诊回来等场景）
```

**Session 复用原则**：一个 workflow + 一个 agent type = 一个 session。completed/suspended 的 session 直接复用，所有历史消息保留在同一个 session 中。failed 的 session 创建新的（避免残留的未配对 tool_call 等脏数据）。

### 6.2 与 Orchestrator 的关系

| loop.run() 返回值 | Orchestrator 动作 |
|-------------------|------------------|
| `COMPLETED` | 发业务事件 + `_dispatch_next` 调度下一步 |
| `NEEDS_USER_INPUT` | 发 `agent_needs_user_input` 事件，等待用户回复 |
| `ERROR` / `MAX_ITERATIONS_REACHED` | 发 `agent_error` 事件，记录 transition |

---

## 七、事件 Namespace 统一

所有事件统一注册在 `src/utils/events.py` 的 Namespace 中。不再在 `src/business/agents/events.py` 中创建独立的 Namespace。

```python
# src/utils/events.py 中新增

# Agent 交互事件
agent_needs_user_input = _signals.signal("agent_needs_user_input")
agent_error = _signals.signal("agent_error")

# Agent 协作事件
requirement_confirmed = _signals.signal("requirement_confirmed")
code_completed = _signals.signal("code_completed")
review_passed = _signals.signal("review_passed")
review_failed = _signals.signal("review_failed")
tool_saved = _signals.signal("tool_saved")
trial_success = _signals.signal("trial_success")
trial_failed = _signals.signal("trial_failed")
triage_completed = _signals.signal("triage_completed")
```

`src/business/agents/events.py` 改为从 `src/utils/events.py` 导入 `emit` 函数，不再维护独立的信号定义。

事件发送统一使用 `src/utils/events.py` 中的 `emit` 函数：

```python
from src.utils.events import emit

# sender 统一传 Orchestrator 实例，数据放 kwargs
# emit 内部自动注入 event_name 到 kwargs，供监听器识别事件来源
emit("requirement_confirmed", sender=self,
     workflow_id=workflow_id, session_id=session_id,
     requirements_json=requirements)
```

`emit` 和 `connect` 函数的实现：

```python
def emit(event_name: str, sender, **kwargs):
    """发送事件，自动注入 event_name 到 kwargs，使用 send_robust 隔离监听器异常"""
    signal = _signals.signal(event_name)
    results = signal.send_robust(sender, event_name=event_name, **kwargs)
    # 记录监听器异常（不中断调用方）
    for receiver, result in results:
        if isinstance(result, Exception):
            logger.error(f"[Events] 监听器 {receiver} 处理 {event_name} 异常: {result}")

def connect(event_name: str, handler):
    """注册事件监听器"""
    signal = _signals.signal(event_name)
    signal.connect(handler)
```

---

## 八、AgentOrchestrator 设计

### 8.1 整体定位

AgentOrchestrator 是 Agent 编排器，负责 session 生命周期管理、Agent 调度、业务事件发送。

**核心设计原则**：
- **workflow_id = recording_id** — 一个录制对应一个工作流，生成一个工具
- **后端管理 session_id** — UI 不需要保存 session_id，只需传入 workflow_id
- **显式调度** — 根据 loop.run() 的返回值决定下一步，通过 `_dispatch_next` 编排
- **事件只通知不调度** — 事件发给 UI / 日志 / transition，Orchestrator 不监听自己的事件

### 8.2 类结构

```python
# src/business/orchestration/agent_orchestrator.py

class AgentOrchestrator:
    """Agent 编排器"""

    def __init__(
        self,
        llm_client: LangChainLLMClient,
        config: UnifiedConfigManager,
        llm_reviewer: Optional[LLMReviewer] = None
    ):
        self._llm = llm_client
        self._config = config
        self._llm_reviewer = llm_reviewer or self._create_reviewer()
        self._session_repo = SessionRepository()
        self._transition_repo = WorkflowTransitionRepository()

        # Loop 实例缓存（按 agent_type）
        self._loops: Dict[str, AgentLoop] = {}

        # Review 重试计数（按 workflow_id）
        self._review_counts: Dict[str, int] = {}
```

### 8.3 核心 API

#### 8.3.1 run_agent — 运行 Agent（核心方法）

```python
def run_agent(
    self,
    agent_type: str,
    user_input: str,
    workflow_id: str
) -> None:
    """
    运行 Agent

    Args:
        agent_type: Agent 类型（pm / programmer / trial）
        user_input: 用户输入
        workflow_id: 工作流 ID（就是录制 ID）

    行为：
        1. 查询或创建会话
        2. 运行 Loop，获取 result
        3. 根据 result 发事件 + 调度下一步
    """
    session_id = self._get_or_create_session(workflow_id, agent_type)
    loop = self._get_loop(agent_type)

    result = loop.run(session_id, user_input)

    # 根据 result 处理
    if result.result_type == ResultType.COMPLETED:
        self._dispatch_next(agent_type, result, session_id, workflow_id)

    elif result.result_type == ResultType.NEEDS_USER_INPUT:
        emit("agent_needs_user_input", sender=self,
             workflow_id=workflow_id,
             session_id=session_id,
             agent_type=agent_type,
             question=result.question)

    elif result.result_type in (ResultType.ERROR, ResultType.MAX_ITERATIONS_REACHED):
        emit("agent_error", sender=self,
             workflow_id=workflow_id,
             session_id=session_id,
             agent_type=agent_type,
             error=result.error,
             error_type=result.result_type.value)
        self._transition_repo.create(
            workflow_id=workflow_id,
            event_type="agent_error",
            from_session_id=session_id,
            to_session_id=None,
            payload={"error": result.error, "agent_type": agent_type}
        )
```

#### 8.3.2 _dispatch_next — 显式调度

```python
def _dispatch_next(
    self,
    agent_type: str,
    result: AgentResult,
    session_id: str,
    workflow_id: str
) -> None:
    """
    根据完成的 Agent 类型，调度下一步

    这是流程编排的核心方法。所有 Agent 之间的衔接逻辑集中在这里。
    """
    try:
        if agent_type == "pm":
            self._on_pm_completed(result, session_id, workflow_id)
        elif agent_type == "programmer":
            self._on_programmer_completed(result, session_id, workflow_id)
        elif agent_type == "trial":
            self._on_trial_completed(result, session_id, workflow_id)
    except Exception as e:
        logger.error(f"[Orchestrator] 调度失败: {e}")
        emit("agent_error", sender=self,
             workflow_id=workflow_id,
             session_id=session_id,
             agent_type=agent_type,
             error=f"调度失败: {str(e)}",
             error_type="dispatch_error")

def _on_pm_completed(self, result, session_id, workflow_id):
    """
    PM 完成 → 根据 signal_tool.name 路由

    两种路径：
    - submit_requirements → 正常需求确认，emit requirement_confirmed，转给程序员
    - report_code_issue → 分诊代码问题，emit triage_completed，转给程序员
    """
    programmer_session_id = self._get_or_create_session(workflow_id, "programmer")

    if result.signal_tool and result.signal_tool.name == "submit_requirements":
        # 正常需求确认：结构化数据来自 FC schema，不需要解析容错
        requirements = result.signal_tool.args
        emit("requirement_confirmed", sender=self,
             workflow_id=workflow_id,
             session_id=session_id,
             requirements_json=requirements)
        self._transition_repo.create(
            workflow_id=workflow_id,
            event_type="requirement_confirmed",
            from_session_id=session_id,
            to_session_id=programmer_session_id,
            payload={"requirements": requirements}
        )
        self.run_agent("programmer", json.dumps(requirements), workflow_id)

    elif result.signal_tool and result.signal_tool.name == "report_code_issue":
        # 分诊代码问题：转给程序员排查
        feedback = result.signal_tool.args["feedback"]
        emit("triage_completed", sender=self,
             workflow_id=workflow_id,
             session_id=session_id,
             triage_result="code_issue",
             feedback=feedback)
        self._transition_repo.create(
            workflow_id=workflow_id,
            event_type="triage_completed",
            from_session_id=session_id,
            to_session_id=programmer_session_id,
            payload={"triage_result": "code_issue"}
        )
        self.run_agent("programmer", feedback, workflow_id)

    else:
        # 异常：PM 未通过信号工具结束（自然结束）
        emit("agent_error", sender=self,
             workflow_id=workflow_id,
             session_id=session_id,
             agent_type="pm",
             error="PM 未通过 submit_requirements 或 report_code_issue 结束",
             error_type="unexpected_completion")

def _on_programmer_completed(self, result, session_id, workflow_id):
    """程序员完成 → 从 signal_tool.args 获取结构化代码数据 → 启动 Review"""
    if result.signal_tool and result.signal_tool.name == "submit_code":
        code_data = result.signal_tool.args
        code = code_data["code"]
    else:
        # 异常：程序员未通过 submit_code 提交代码
        emit("agent_error", sender=self,
             workflow_id=workflow_id,
             session_id=session_id,
             agent_type="programmer",
             error="程序员未通过 submit_code 提交代码",
             error_type="unexpected_completion")
        return

    emit("code_completed", sender=self,
         workflow_id=workflow_id,
         session_id=session_id,
         code=code)
    self._transition_repo.create(
        workflow_id=workflow_id,
        event_type="code_completed",
        from_session_id=session_id,
        to_session_id=None,
        payload={"code_length": len(code)}
    )

    self._run_review(code_data, session_id, workflow_id)

def _on_trial_completed(self, result, session_id, workflow_id):
    """试用 Agent 完成 → 解析结果 → 更新计数或触发分诊"""
    # 试用 Agent 完成后的处理逻辑
    # 具体实现依赖优先级 7（试用 Agent）的设计
    pass
```

#### 8.3.3 _run_review — 运行 LLM Review

```python
def _run_review(
    self,
    code_data: dict,
    from_session_id: str,
    workflow_id: str
) -> None:
    """
    运行 LLM Review

    code_data 来自程序员 submit_code 的 signal_tool.args，
    包含 tool_name, description, code, execution_strategy, parameters。
    Review 重试次数通过 self._review_counts[workflow_id] 追踪。
    """
    code = code_data["code"]

    # 获取当前重试次数
    retry_count = self._review_counts.get(workflow_id, 0)

    review_result = self._llm_reviewer.review(code)

    if review_result.passed:
        # Review 通过 → 入库
        emit("review_passed", sender=self,
             workflow_id=workflow_id,
             session_id=from_session_id,
             code=code)
        self._transition_repo.create(
            workflow_id=workflow_id,
            event_type="review_passed",
            from_session_id=from_session_id,
            to_session_id=None
        )

        # 清理 retry 计数
        self._review_counts.pop(workflow_id, None)

        tool_id = self._save_tool(code_data, workflow_id, from_session_id)

    else:
        # Review 失败
        retry_count += 1
        self._review_counts[workflow_id] = retry_count

        if retry_count < 3:
            # 回传给程序员修改
            programmer_session_id = self._get_or_create_session(workflow_id, "programmer")

            emit("review_failed", sender=self,
                 workflow_id=workflow_id,
                 session_id=from_session_id,
                 code=code,
                 feedback=review_result.feedback,
                 retry_count=retry_count)
            self._transition_repo.create(
                workflow_id=workflow_id,
                event_type="review_failed",
                from_session_id=from_session_id,
                to_session_id=programmer_session_id,
                payload={"retry_count": retry_count, "feedback": review_result.feedback}
            )

            self.run_agent(
                "programmer",
                f"Review 失败（第{retry_count}次），修改意见：{review_result.feedback}",
                workflow_id
            )
        else:
            # 超过 3 次，强制入库（pending）
            emit("review_failed", sender=self,
                 workflow_id=workflow_id,
                 session_id=from_session_id,
                 code=code,
                 feedback=review_result.feedback,
                 retry_count=retry_count)
            self._transition_repo.create(
                workflow_id=workflow_id,
                event_type="review_failed",
                from_session_id=from_session_id,
                to_session_id=None,
                payload={"retry_count": retry_count, "forced_save": True}
            )

            self._review_counts.pop(workflow_id, None)
            tool_id = self._save_tool(code_data, workflow_id, from_session_id)
```

#### 8.3.4 start_trial — 启动试用

```python
def start_trial(
    self,
    tool_id: str,
    user_input: str,
    workflow_id: str
) -> None:
    """启动试用 Agent"""
    self.run_agent("trial", user_input, workflow_id)
```

#### 8.3.5 handle_trial_result — 处理试用结果

```python
def handle_trial_result(
    self,
    tool_id: str,
    success: bool,
    workflow_id: str,
    session_id: str,
    user_feedback: str = ""
) -> None:
    """
    处理试用结果

    Args:
        tool_id: 工具 ID
        success: 是否成功
        workflow_id: 工作流 ID
        session_id: 试用会话 ID
        user_feedback: 失败时的用户反馈
    """
    from src.data.repositories import ToolRepository
    tool_repo = ToolRepository()

    if success:
        # 成功：累加计数
        tool = tool_repo.get_by_id(tool_id)
        new_count = tool.trial_success_count + 1
        tool_repo.update_trial_count(tool_id, new_count)

        published = new_count >= 3
        if published:
            tool_repo.update_status(tool_id, "published")

        emit("trial_success", sender=self,
             workflow_id=workflow_id,
             session_id=session_id,
             tool_id=tool_id,
             success_count=new_count,
             published=published)
        self._transition_repo.create(
            workflow_id=workflow_id,
            event_type="trial_success",
            from_session_id=session_id,
            to_session_id=None,
            payload={"success_count": new_count, "published": published}
        )
    else:
        # 失败：触发分诊
        pm_session_id = self._get_or_create_session(workflow_id, "pm")

        emit("trial_failed", sender=self,
             workflow_id=workflow_id,
             session_id=session_id,
             tool_id=tool_id,
             user_feedback=user_feedback)
        self._transition_repo.create(
            workflow_id=workflow_id,
            event_type="trial_failed",
            from_session_id=session_id,
            to_session_id=pm_session_id,
            payload={"tool_id": tool_id, "user_feedback": user_feedback}
        )

        self._start_triage(tool_id, user_feedback, workflow_id)
```

#### 8.3.6 _start_triage — 启动分诊

```python
def _start_triage(
    self,
    tool_id: str,
    user_feedback: str,
    workflow_id: str
) -> None:
    """
    启动 PM 分诊

    PM session 会被 _get_or_create_session 自动复用（completed → 复用），
    PM 能看到完整的需求确认上下文，做出更准确的分诊判断。

    PM 分诊后两种路径：
    - 需求问题 → PM 调 talk_to_user 跟用户重新确认 → 正常 requirement_confirmed 流程
    - 代码问题 → PM 直接完成，输出用户反馈 → _on_pm_completed 转给程序员
    """
    initial_input = (
        f"工具 {tool_id} 试用失败，用户反馈：{user_feedback}。"
        "请分析问题原因：如果是需求问题，请与用户重新确认需求；"
        "如果是代码问题，请直接输出用户反馈供程序员排查。"
    )
    self.run_agent("pm", initial_input, workflow_id)
```

### 8.4 Session 管理逻辑

```python
def _get_or_create_session(
    self,
    workflow_id: str,
    agent_type: str
) -> str:
    """
    查询或创建会话

    一个 workflow + 一个 agent type = 一个 session（复用原则）。

    规则：
    - suspended / completed → 复用（review 打回、分诊回来等场景）
    - active → 复用（记 warning，不应并发但不阻断）
    - failed → 创建新会话（避免残留脏数据）
    - 不存在 → 创建新会话

    Returns:
        session_id
    """
    sessions = self._session_repo.get_by_workflow(
        workflow_id, agent_type, order_by="created_at_desc"
    )

    if sessions:
        latest = sessions[0]

        if latest.status == "failed":
            # failed session 可能有未配对的 tool_call，创建新的
            return self._create_session(workflow_id, agent_type)

        if latest.status == "active":
            logger.warning(
                f"[Orchestrator] 会话 {latest.session_id} 仍在 active 状态，"
                "可能存在并发调用"
            )

        return latest.session_id

    return self._create_session(workflow_id, agent_type)

def _create_session(
    self,
    workflow_id: str,
    agent_type: str
) -> str:
    """创建新会话，返回 session_id"""
    session = self._session_repo.create(
        session_id=str(uuid.uuid4()),
        workflow_id=workflow_id,
        agent_type=agent_type,
        status="active"
    )
    return session.session_id
```

### 8.5 辅助方法

```python
def _get_loop(self, agent_type: str) -> AgentLoop:
    """获取或创建 Loop 实例"""
    if agent_type not in self._loops:
        config = self._get_agent_config(agent_type)
        self._loops[agent_type] = AgentLoop(config, self._llm, self._config)
    return self._loops[agent_type]

def _get_agent_config(self, agent_type: str) -> AgentConfig:
    """获取 Agent 配置"""
    configs = {
        "pm": PM_CONFIG,
        "programmer": PROGRAMMER_CONFIG,
        "trial": TRIAL_CONFIG,
    }
    if agent_type not in configs:
        raise ValueError(f"未知 Agent 类型: {agent_type}")
    return configs[agent_type]

```

### 8.6 工具保存

```python
def _save_tool(
    self,
    code_data: dict,
    workflow_id: str,
    session_id: str,
    status: str = "pending"
) -> str:
    """
    保存工具到数据库

    按 workflow_id 查已有工具：存在则更新代码并清零试用计数，不存在则创建。
    这样分诊修复后不会创建重复工具。

    code_data 来自程序员 submit_code 工具的 signal_tool.args，包含：
    tool_name, description, code, execution_strategy, parameters
    """
    from src.data.repositories import ToolRepository

    tool_repo = ToolRepository()
    existing_tool = tool_repo.get_by_workflow_id(workflow_id)
    code = code_data["code"]

    if existing_tool:
        # 更新已有工具（分诊修复、review 打回后重新生成）
        tool_id = existing_tool.tool_id
        tool_repo.update_code(tool_id, code)
        tool_repo.update_trial_count(tool_id, 0)  # 代码变了，清零试用计数
        tool_repo.update_status(tool_id, status)
    else:
        # 首次创建：使用结构化 metadata，不再需要临时解析方法
        tool_id = tool_repo.create(
            tool_name=code_data["tool_name"],
            description=code_data["description"],
            code=code,
            parameters=json.dumps(code_data["parameters"]),
            workflow_id=workflow_id,
            status=status
        )

    emit("tool_saved", sender=self,
         workflow_id=workflow_id,
         session_id=session_id,
         tool_id=tool_id)
    self._transition_repo.create(
        workflow_id=workflow_id,
        event_type="tool_saved",
        from_session_id=session_id,
        to_session_id=None,
        payload={"tool_id": tool_id}
    )

    return tool_id
```

---

## 九、试用成功逻辑

### 9.1 计数机制

在 `tools` 表新增 `trial_success_count` 字段（INTEGER DEFAULT 0），记录连续试用成功次数。

### 9.2 规则

- 每次试用成功：`trial_success_count += 1`
- 达到 3 次：工具状态从 `pending` 更新为 `published`
- 试用失败：不清零（走分诊流程）
- **工具代码被修改时清零**：`_save_tool` 检测到已有工具时，更新代码并清零成功次数（见 8.6 节）

### 9.3 迁移

在 `src/data/migrations.py` 的 schema 升级中：

```sql
ALTER TABLE tools ADD COLUMN trial_success_count INTEGER DEFAULT 0;
```

---

## 十、AgentUIBridge 设计

### 10.1 整体定位

AgentUIBridge 是 UI 层与 Orchestrator 之间的桥梁，负责线程管理和 PyQt 信号转换。

**核心问题**：Orchestrator 的 `run_agent()` 是同步阻塞方法（内部跑 Agent Loop 的 while 循环），不能在 PyQt 主线程中调用，否则 UI 冻住。

### 10.2 线程模型

```
PyQt 主线程                          后台工作线程
    │                                     │
    │  用户操作（录制完成/回复问题）         │
    │ ──── start_agent() ──────────────→ │
    │                                     │ orchestrator.run_agent(...)
    │                                     │   → loop.run()
    │                                     │   → _dispatch_next()（可能链式调用）
    │                                     │   → emit 事件
    │                                     │
    │ ←── PyQt 信号（跨线程安全）─────── │
    │  UI 更新                            │
```

### 10.3 类结构

```python
# src/business/orchestration/agent_ui_bridge.py

from PyQt6.QtCore import QObject, pyqtSignal, QThread


class AgentWorker(QObject):
    """后台工作线程的执行体"""

    # 完成信号
    finished = pyqtSignal()

    def __init__(self, orchestrator, agent_type, user_input, workflow_id):
        super().__init__()
        self._orchestrator = orchestrator
        self._agent_type = agent_type
        self._user_input = user_input
        self._workflow_id = workflow_id

    def run(self):
        """在后台线程中执行"""
        try:
            self._orchestrator.run_agent(
                self._agent_type,
                self._user_input,
                self._workflow_id
            )
        except Exception as e:
            logger.error(f"[AgentWorker] 执行失败: {e}")
        finally:
            self.finished.emit()


class AgentUIBridge(QObject):
    """UI 与 Orchestrator 的桥梁"""

    # PyQt 信号（从事件监听器发出，跨线程安全传递给 UI）
    question_received = pyqtSignal(str, str, str)  # workflow_id, agent_type, question
    error_occurred = pyqtSignal(str, str, str)      # workflow_id, agent_type, error
    progress_updated = pyqtSignal(str, str)          # workflow_id, event_description
    tool_saved_signal = pyqtSignal(str, str)         # workflow_id, tool_id

    def __init__(self, orchestrator: AgentOrchestrator):
        super().__init__()
        self._orchestrator = orchestrator
        self._worker_thread: Optional[QThread] = None

        # 监听 Orchestrator 发出的事件，转换为 PyQt 信号
        from src.utils.events import connect
        connect("agent_needs_user_input", self._on_needs_user_input)
        connect("agent_error", self._on_error)
        connect("requirement_confirmed", self._on_progress)
        connect("code_completed", self._on_progress)
        connect("review_passed", self._on_progress)
        connect("review_failed", self._on_progress)
        connect("tool_saved", self._on_tool_saved)
        connect("trial_success", self._on_progress)

    def start_agent(self, agent_type: str, user_input: str, workflow_id: str):
        """
        在后台线程中启动 Agent

        UI 调用此方法，不会阻塞主线程。
        """
        if self._worker_thread and self._worker_thread.isRunning():
            logger.warning("[AgentUIBridge] 上一个任务仍在运行")
            return

        self._worker_thread = QThread()
        worker = AgentWorker(
            self._orchestrator, agent_type, user_input, workflow_id
        )
        worker.moveToThread(self._worker_thread)
        self._worker_thread.started.connect(worker.run)
        worker.finished.connect(self._worker_thread.quit)
        self._worker_thread.start()

    def reply_to_agent(self, agent_type: str, user_input: str, workflow_id: str):
        """
        用户回复 Agent 的提问

        与 start_agent 相同机制，在后台线程中调用 run_agent。
        """
        self.start_agent(agent_type, user_input, workflow_id)

    # --- 事件监听器 → PyQt 信号 ---

    def _on_needs_user_input(self, sender, **kwargs):
        self.question_received.emit(
            kwargs["workflow_id"],
            kwargs["agent_type"],
            kwargs["question"]
        )

    def _on_error(self, sender, **kwargs):
        self.error_occurred.emit(
            kwargs["workflow_id"],
            kwargs["agent_type"],
            kwargs["error"]
        )

    def _on_progress(self, sender, **kwargs):
        event_name = kwargs.get("event_name", "progress")
        self.progress_updated.emit(
            kwargs["workflow_id"],
            event_name
        )

    def _on_tool_saved(self, sender, **kwargs):
        self.tool_saved_signal.emit(
            kwargs["workflow_id"],
            kwargs["tool_id"]
        )
```

### 10.4 UI 使用示例

```python
# UI 层
bridge = AgentUIBridge(orchestrator)

# 连接信号到 UI 槽函数
bridge.question_received.connect(self._show_question)
bridge.error_occurred.connect(self._show_error)
bridge.progress_updated.connect(self._update_progress)
bridge.tool_saved_signal.connect(self._on_tool_saved)

# 录制完成后启动 PM
bridge.start_agent("pm", "请分析这段录制", recording_id)

# 用户回复
bridge.reply_to_agent("pm", user_reply, recording_id)
```

---

## 十一、文件结构

```
src/business/orchestration/
    __init__.py
    agent_orchestrator.py          # AgentOrchestrator 主类
    agent_ui_bridge.py             # AgentUIBridge + AgentWorker
    llm_reviewer.py                # LLM Reviewer

src/utils/events.py                # 统一事件定义（新增协作事件）
```

---

## 十二、使用示例

### 12.1 正常工作流

```python
# 初始化
config = get_unified_config()
llm_client = create_llm_client(config.get_ai_config())
orchestrator = AgentOrchestrator(llm_client, config)
bridge = AgentUIBridge(orchestrator)

# 录制完成后
recording_id = "rec_123"  # = workflow_id

# 1. 启动 PM
bridge.start_agent("pm", "请分析这段录制", recording_id)
# → PM 可能多轮 talk_to_user
# → bridge.question_received 信号触发，UI 展示问题

# 2. 用户回复
bridge.reply_to_agent("pm", "确认，搜索关键词是变量", recording_id)
# → PM 完成 → Orchestrator 自动启动程序员 → Review → 入库
# → bridge.progress_updated / tool_saved_signal 触发

# 3. 试用
bridge.start_agent("trial", "试一下", recording_id)

# 4. 试用结果
orchestrator.handle_trial_result(tool_id, success=True, workflow_id=recording_id, session_id=trial_session_id)
```

---

## 十三、边界情况

### 13.1 PM 未通过信号工具结束

`_on_pm_completed` 中，如果 `result.signal_tool` 为 None（PM 自然结束，未调用 `submit_requirements` 或 `report_code_issue`），视为异常情况，emit `agent_error`。这种情况下 PM 的 `final_output` 是自由文本，无法可靠路由。

### 13.2 重复事件

Orchestrator 的调度是显式的（`_dispatch_next`），不存在事件监听器被重复触发的问题。每次 `loop.run()` 返回后只执行一次调度逻辑。

### 13.3 事件丢失

blinker 是内存事件，进程重启后丢失。关键事件通过 `workflow_transitions` 表持久化，重启后可从 transition 记录恢复工作流状态。

### 13.4 事件监听器异常

blinker 的 `signal.send()` **会传播**监听器异常 —— 如果某个监听器抛出异常，后续监听器不会被调用，异常会冒泡到 `emit` 的调用者（即 Orchestrator）。

为避免 UI 监听器的异常中断 Orchestrator 执行，`emit` 函数使用 `send_robust()` 替代 `send()`：

```python
def emit(event_name: str, sender, **kwargs):
    signal = _signals.signal(event_name)
    signal.send_robust(sender, event_name=event_name, **kwargs)
    # send_robust 捕获监听器异常并返回 (receiver, error) 列表，不中断调用方
```

### 13.5 并发调用

`_get_or_create_session` 对 `active` 状态的会话记录 warning。AgentUIBridge 通过检查 `_worker_thread.isRunning()` 防止同一 workflow 的并发调用。

### 13.6 进程重启后恢复

从 `workflow_transitions` 查询最后一条 transition，确定工作流进行到哪一步。根据最后的 session 状态恢复：
- 最后 session 是 `suspended` → 恢复对话
- 最后 session 是 `completed` + 无后续 → 从下一步开始
- 具体恢复逻辑待实现时细化

---

## 十四、设计决策

| 决策 | 说明 |
|------|------|
| **Loop 不发事件** | Loop 是纯执行引擎，只返回 AgentResult。事件全部由 Orchestrator 发出，避免 blinker 同步回调导致的嵌套执行 |
| **只有业务事件** | 去掉 `agent_completed` 等通用事件，只发有业务含义的事件（requirement_confirmed、code_completed 等） |
| **显式调度** | Orchestrator 根据 loop.run() 返回值在 `_dispatch_next` 中显式编排，不通过事件监听器调度 |
| **Namespace 统一** | 所有事件注册在 `src/utils/events.py`，不再有独立的 agents/events.py Namespace |
| **sender 统一** | emit 的 sender 统一传 Orchestrator 实例（`self`），数据放 kwargs |
| **Review 重试计数** | 用 Orchestrator 内存字典（`_review_counts`）按 workflow_id 追踪，Review 通过或强制入库后清理 |
| **Session 复用** | 一个 workflow + 一个 agent type = 一个 session。completed/suspended 直接复用，failed 新建（避免脏数据） |
| **试用成功计数** | 存 tools 表 `trial_success_count` 字段，3 次成功后发布，工具修改后清零 |
| **AgentUIBridge** | QThread + blinker → PyQt 信号，隔离 UI 线程和 Agent 执行线程 |
| **事件数据传字典** | 使用 kwargs 传递，避免定义过多数据类 |
| **分诊靠 signal_tool.name 路由** | PM 调用 submit_requirements → 需求确认流程；调用 report_code_issue → 代码问题，转给程序员。路由由工具名决定，不依赖输出格式解析 |
| **工具按 workflow_id 去重** | `_save_tool` 查已有工具：存在则更新代码并清零试用计数，不存在则创建。分诊修复后不会创建重复工具 |

---

## 十五、与架构 v2 及上游设计的差异说明

### 与架构 v2 第五节的关系

本设计保持一致的决策：
- **Agent 之间通过事件通信** — 事件是 Orchestrator 与外部模块的通信机制
- **流程编排集中管理** — `_dispatch_next` 集中了所有衔接逻辑
- **workflow_id 贯穿整个工作流** — 一个录制一个工作流一个工具

本设计细化/变更的决策：

| 决策 | 架构 v2 原文 | 本设计 |
|------|-------------|--------|
| 事件发送者 | "Agent 代码完成后发事件" | Loop 不发事件，Orchestrator 根据 return 值发业务事件 |
| 事件类型 | 通用事件 + 协作事件 | 只有业务事件，去掉 agent_completed 等通用事件 |
| 调度机制 | "流程编排文件监听事件" | Orchestrator 显式调度（`_dispatch_next`），不通过事件监听 |
| Orchestrator 职责 | "session 管理 + 事件发送" | session 管理 + 显式调度 + 事件发送 |
| workflow_id | 未明确 | workflow_id = recording_id |

### 与 Agent Loop 设计（优先级3）的差异

| 决策 | 优先级3 设计 | 本设计 |
|------|-------------|--------|
| 事件发送 | Loop 内部 emit 事件（agent_completed 等） | **Loop 不发任何事件**，由 Orchestrator 在 loop.run() 返回后发出 |
| 内部事件 | agent_iteration_started/completed、agent_tool_executed/failed | **全部去掉**，Loop 是纯执行引擎 |
| agents/events.py | 独立 Namespace，定义 Loop 事件 | 改为从 src/utils/events.py 导入，不维护独立信号 |

**注意**：以上差异需要在优先级4实现时同步修改 AgentLoop 代码（移除事件发送逻辑）。

---

*基于架构 v2 细化，记录时间：2026-03-16*
