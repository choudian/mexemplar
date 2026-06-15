# Phase 0 Research: 结构化多选澄清

本特性无 `NEEDS CLARIFICATION`（输入计划已足够详细）。研究聚焦"如何复用既有成熟模式落地"，避免发明新机制。所有结论来自对当前代码库的实地阅读。

## Decision 1：阻塞型工具 vs 中断型工具

- **Decision**：`ask_user_question` 实现为**非中断（`is_interrupting=False`）的阻塞工具**——handler 内 `event.wait(timeout=300s)`，拿到答案后返回 `str` 结果，AgentLoop 在**同一 loop 内继续**。
- **Rationale**：`reply_to_user` 是中断型（返回 `ToolSignal(NEEDS_USER_INPUT)`，结束回合）。但本特性要求"拿到答案后同一回合继续推进"（FR-007），不能结束回合。既有高危确认工具（`_ask_user_confirm`）正是"handler 内阻塞等 UI 决策再返回"的同步模式，AgentLoop 对其透明——这正是我们要的语义。
- **Alternatives rejected**：
  - 中断型 + 新回合恢复：破坏 FR-007"同一 AgentLoop 内继续"，且要引入恢复状态机，复杂度高。
  - 轮询：违背事件驱动原则，浪费 CPU。

## Decision 2：独占调用的批次处理

- **Decision**：给 `ToolDefinition` 增加 `requires_exclusive_call: bool = False`；在 `AgentLoop._execute_tool_batch`（`agent_loop.py:822` 之后）增加检查——`batch_size > 1 且批内任一 call 的 tool_def.requires_exclusive_call` → 对**全部** call 写 `invalid_model_output` 并 `return None`（不执行任何工具）。solo 时不拦截，落入既有 ordinary 串行路径正常阻塞执行。
- **Rationale**：完全复刻既有中断型混批拒绝逻辑（`agent_loop.py:832` `if batch_size > 1 and interrupting_count > 0`），口径一致、配对完整（`_save_error` 对每个 call 写配对结果）。`ask_user_question` 非中断，故需用独立的 `requires_exclusive_call` 标志而非复用 `is_interrupting`。
- **Alternatives rejected**：
  - 复用 `is_interrupting`：会让工具变成中断型结束回合（与 Decision 1 冲突）。
  - 在 handler 内判断并发：批次分类发生在 handler 之前，handler 看不到同批其他 call。

## Decision 3：pending 生命周期管理（first-decision-wins）

- **Decision**：新建 `src/business/agents/tools/clarification_manager.py`，复刻 `builtin_general_tools` 确认机制的结构：模块级 `_pending_clarifications: dict[request_id, PendingClarification]` + `_clarification_lock = threading.Lock()` + 可注入 `_clarification_signal`。`PendingClarification` 持 `request_id / session_id / questions / created_at / event / status / answers`。决策、超时、停止、关闭都经 `event.is_set()` 实现 first-decision-wins。
- **Rationale**：高危确认（`set_confirm_result` 的 `if pending.event.is_set(): return`）和试用预览（`TrialPreviewRequestManager.record_decision` 的 `if record.status != "pending"`）都已用 Event/status 守门实现并发幂等。直接对标，零创新风险。
- **Alternatives rejected**：
  - 复用 `_pending_confirms`：违反 FR-020"与高危确认完全分离"，会污染确认审计日志与 fail-closed 语义。
  - `asyncio`：AgentLoop worker 是线程模型（`threading.Thread`），用 `threading.Event` 与既有一致。

## Decision 4：稳定 ID 由后端生成

- **Decision**：handler 接收模型给的 questions 数组后，按位置生成 `questionId = f"q{i+1}"`、`optionId = f"q{i+1}o{j+1}"`，忽略模型可能提供的任何 ID。结果与事件、决策提交都基于这套后端 ID。
- **Rationale**：FR-004 明确不依赖模型 ID（模型可能重复或不稳定）。位置式 ID 稳定、可读、便于测试断言。
- **Alternatives rejected**：uuid（不可读、测试断言困难，且对单 pending 无必要）。

## Decision 5：超时实现

- **Decision**：模块常量 `CLARIFICATION_TIMEOUT_S = 300`（5 分钟）。handler 内 `completed = event.wait(timeout=CLARIFICATION_TIMEOUT_S)`，未完成则把 status 结算为 `timeout`。事件 payload 的 `expiresAt` 由 `created_at + 300s` 计算（对标 `confirmation_event_payload` 的 `expires_at`）。
- **Rationale**：与 `CONFIRM_TIMEOUT_MS` 同款常量风格，非用户可调（符合 III. 无新增配置）。`expiresAt` 让前端本地倒计时与 disable（对标试用预览 `expires_at`）。
- **Alternatives rejected**：可配置超时（引入配置项，违反 CC-001/III）。

## Decision 6：公开事件契约

- **Decision**：在 `ui_events.py` UI Event Registry 注册两个事件：
  - `assistant.clarification_requested`（interactive）：`requestId / sessionId / questions / expiresAt / status`，`status` enum `{pending}`。
  - `assistant.clarification_resolved`（interactive）：`requestId / sessionId / status`，**不含答案**，`status` enum `{answered, cancelled, timeout, stopped, shutdown}`。
  scope 用 `sessionId`。`questions` 嵌套结构由 `ui_event_safety_service.unsafe_public_ui_event_value_reason` 递归扫描（禁用值/密钥模式命中即拒绝）。
- **Rationale**：009 把公开 UI 事件收敛到 Registry，前端只消费注册过的 type（CLAUDE.md 反模式约束）。安全服务已支持嵌套 dict/list 递归校验（`ui_event_safety_service.py:96-113`），无需标记 unredacted——保留扫描即 secret 防护。
- **Alternatives rejected**：裸事件名 / 未注册 payload（违反 009 契约与门卫）。

## Decision 7：停止 / 关闭 / 断线

- **Decision**：
  - 停止：`AssistantRuntime.cancel_session`（`assistant_runtime.py:206` `fail_closed_confirmations_for_session` 旁）并排调用 `settle_clarifications_for_session(sid, "stopped")`，唤醒阻塞 worker。
  - 关闭：`app.py` lifespan shutdown（`event_queue.shutdown()` 处，`app.py:98` 附近）调用 `settle_all_clarifications("shutdown")`。
  - 断线：普通 SSE 断线**不**结算——`event_queue` 断连不触碰 manager；前端重连经 replay 或 `GET pending` 恢复。
- **Rationale**：完全对标高危确认停止 fail-closed（CC-002 不破坏同步协议）与试用预览 `fail_pending("shutdown")`。断线不取消是 FR-014 硬要求。
- **Alternatives rejected**：断线即取消（破坏长任务、重连体验，违反 FR-014）。

## Decision 8：前端展示与会话隔离

- **Decision**：新建 `ClarificationCard.tsx`（独立于 `ConfirmationToast.tsx`），在 `AssistantScreen` 输入框上方渲染。`assistantStore` 增加按 `sessionId` 的 `pendingClarification` + `clarificationDrafts` + `clarificationSubmitting`；切换会话保留草稿（draft by session），resolved 事件统一清理。消费 `assistant.clarification_requested/resolved`；`backend.resync_required` 与会话打开时调 `GET pending` 刷新。
- **Rationale**：CLAUDE.md（frontend）要求确认浮层独立生命周期、一次一个 active、可访问、不复用 Toast；009 要求 resync 走权威快照。草稿按 session 保留符合"保留用户上下文跨切换"。
- **Alternatives rejected**：复用 confirmations 数组（违反 FR-020）；模态弹窗（违反非模态原则）。

## Decision 9：作用域限定（仅主助理）

- **Decision**：仅在 `orchestrator._build_assistant_tools`（`orchestrator.py:1991` 的 `static_tools`）注册 `ask_user_question`。PM/Programmer/Trial 走各自工具集；subagent/specialist 走 `_build_delegated_executor_tools`（不含此工具）。
- **Rationale**：FR-008。委派执行器工具集是独立函数，天然不暴露。门卫测试断言 subagent 工具集不含 `ask_user_question`。
- **Alternatives rejected**：全局注册后运行时过滤（易漏，门卫难写）。

## Decision 10：既有测试修复

- **Decision**：`tests/test_auth_toast_confirmation.py` 引用的 `general_tools._build_write_summary / _build_edit_summary / _build_exec_summary` 已在 015 重构中迁至 `builtin_permissions.py` 并改名 `build_write_summary / build_edit_summary / build_exec_summary`；更新测试引用（`_confirm_or_reject` 仍在 `builtin_general_tools:1112`，按实际运行结果核对）。修复后纳入完整门禁。
- **Rationale**：计划要求把该文件重新纳入门禁；这是顺带的 CC-004 技术债清理。
- **Alternatives rejected**：跳过（留破窗，违反 IV）。
