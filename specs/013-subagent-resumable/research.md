# Phase 0 Research: 子代理可唤回机制

spec 无 `[NEEDS CLARIFICATION]` 残留（前置 brainstorming 已逐点敲定）。本文记录关键设计决策、备选与一个待收尾的保真度问题。

## R1 — 暂停语义放在通用 AgentLoop，用 config 开关门控

- **Decision**: 在 `AgentLoop` 的两条终止路径（撞 `max_iterations`、`_call_llm_with_retry` 返回 `None`）上判断 `self._config.resumable_on_failure`；为真则 `update_session_status("suspended")` 并返回新结果类型 `ResultType.PAUSED`，否则保持既有 `MAX_ITERATIONS_REACHED` / `ERROR`。
- **Rationale**: 终止语义是 loop 的固有职责；用默认 `False` 的开关门控，使临时子代理获得新行为而 PM / Programmer / Trial / Specialist 等零回归（FR-011 / SC-006）。
- **Alternatives**: ① 在 orchestrator 事后把 ERROR/MAX_ITERATIONS 翻译成暂停——无法区分"调用失败"与"业务报错"，且 loop 已写 `failed`；② 给子代理单独一个 loop 子类——重复终止逻辑、易漂移。

## R2 — 唤回基于持久化会话恢复，不依赖进程内存

- **Decision**: `_continue_subagent` 新建一个 `AgentConfig(resumable_on_failure=True)` 的 `AgentLoop`，对既有 `subagent_id` 调 `loop.run(subagent_id, user_input, tools=...)`。`_initialize_session` 对既有会话从 `suspended/completed/failed → active` 恢复，`ContextManager` 经 `MessageRepository.get_context` 从 SQLite 重建上下文。
- **Rationale**: 满足 FR-007 / CC-001——跨进程重启后凭 `subagent_id` 仍可唤回（账单超限可能等很久）。无需新增序列化/持久化机制（会话历史本就落 SQLite）。
- **Alternatives**: 进程内缓存子代理 loop 实例——重启即丢，违背 SC-003。

## R3 — 失败原因分类（✅ 已收敛）

> **状态**：已实现。`agent_loop.py` 新增 `_is_recoverable_llm_failure`（遍历异常链匹配 429/配额/billing/网络/超时/5xx 等标记），仅可恢复失败转 PAUSED 标"账单或网络"，其余不可恢复错误仍走 `ERROR` 并置会话 `failed`；契约测试 `test_llm_failure_nonrecoverable_still_error_when_resumable` 覆盖。下文保留原始问题分析。


- **现状**: `_call_llm_with_retry` 对**任何**异常重试耗尽后返回 `None`，loop 据此一律标注 reason 为"LLM 调用失败（账单或网络）"。
- **spec 意图**: Assumptions 把"调用失败可唤回"限定为**账户配额/账单超限与网络持续中断**这类需等外部恢复的失败；输出长度截断不算失败。
- **缺口**: 不可恢复错误（400 bad request、凭据配置错、序列化 bug 触发的异常）也会被转为可唤回暂停且 reason 误称"账单或网络"，prompt 据此引导主代理"等恢复后再续"，造成无效等待。
- **Decision（建议，列为实现任务）**: 在 loop 失败分支按异常类型/HTTP 状态码收敛——配额/限流/网络类 → 可唤回暂停且 reason 标"账单或网络"；其余 → 仍走 `ERROR`。最低限度也要弱化 reason 文案为不武断断言成因。FR-003 要求"可区分原因"，本项是其正确性的前提。

## R4 — 唤回时的工具范围

- **Decision**: 唤回用主代理**当前**可用工具池重建（`_resolve_user_tool_ids(tool_whitelist=None)`），不强制还原原始委派白名单。
- **Rationale**: 对应 spec Assumption；当前可用范围对续跑同样合理，且避免持久化原始白名单。

## R5 — 暂停作为内部 transition，不进公开 UI 事件

- **Decision**: 暂停记一条 `assistant_delegation_paused` workflow transition（复用 `record_transition`，event_type 自由文本、无 allowlist），用于编排可追溯性；本期不在 `ui_events.py` 注册公开事件、不在前端展示暂停子代理。
- **Rationale**: 对应 spec Event Impact；符合宪法 I（公开 UI 契约才需 Registry 注册）。

## R6 — 归属校验

- **Decision**: `_resolve_subagent_session` 校验 session 存在、`agent_type == EPHEMERAL_SUBAGENT`、且 `workflow_id` 以 `dlg_{parent_session_id[:12]}_` 开头；任一不满足返回 `None`，调用方回明确错误且不返回会话内容（FR-008 / SC-007）。
- **已知边界（低风险）**: 前缀取 parent id 前 12 字符，理论上前缀相同的两个 parent 可互访（UUID 下概率可忽略）；`status == "active"` 拒绝并发唤回是无锁字段判断（单用户桌面 TOCTOU 可忽略）。
