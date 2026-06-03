# Phase 1 Data Model: 子代理可唤回机制

本特性**不新增数据库表、不新增迁移**，复用既有持久化结构；下列为概念实体到既有存储/内存 DTO 的映射。

## 复用的持久化实体（既有，无 schema 变更）

### 子代理工作会话 Subagent Work Session
- **承载**：既有 `sessions` 行（经 `SessionRepository` / `AgentSessionStore`）。
- **关键字段**（既有）：`session_id`（即对外 `subagent_id`）、`workflow_id`（格式 `dlg_{parent[:12]}_{16hex}`，用于归属校验）、`agent_type`（`ephemeral_subagent`）、`status`（`active` / `suspended` / `completed` / `failed`）。
- **对话历史**：既有 `messages` 行（经 `MessageRepository.get_context`），role ∈ system/user/assistant/tool/program；assistant 行的 `tool_calls`（JSON）用于概览统计。
- **状态转换**（本特性相关）：
  - `active → suspended`：撞迭代上限或 LLM 调用最终失败（仅 `resumable_on_failure=True`）。
  - `suspended/completed/failed → active`：唤回时 `_initialize_session` 恢复。
  - **不删除、不改写**历史行（CC-003）；唤回是追加式继续。

### 暂停 / 委派 transition
- **承载**：既有 `workflow_transitions` 行（经 `WorkflowTransitionRepository` / `record_transition`）。
- **本特性新增 event_type 值**：`assistant_delegation_paused`（payload：`{subagent_id, reason}`）。属自由文本 event_type，无需 allowlist/注册。

## 新增内存契约（非持久化）

### ResultType.PAUSED（`src/business/agents/config.py`）
- 枚举新值 `paused`。表示会话已置 `suspended`、工作历史保留、可唤回。

### AgentConfig.resumable_on_failure: bool = False
- 为真时 loop 把"迭代上限/LLM 调用最终失败"转 `PAUSED`；默认假保证非临时 Agent 零回归。

### Pause Reason（字符串，承载于 `AgentResult.error` → 工具返回 `reason`）
- 迭代超限：`"已达迭代上限（{N} 轮）"`。
- 调用失败：`"LLM 调用失败（账单或网络），可恢复后续跑"`（见 research R3 待收敛）。
- 主代理据 `reason` 走不同策略（FR-003）。

### Work Overview（`_inspect_subagent` 返回 dict，零模型调用）
| 字段 | 含义 |
|------|------|
| `success` | 是否成功（含归属校验结果） |
| `subagent_id` | 子代理标识符 |
| `status` | 会话状态 |
| `assistant_turns` | assistant 轮数 |
| `tool_call_counts` | `{工具名: 次数}` 聚合 |
| `last_output` | 最后一条 assistant 正文 |

### Delegation / Continue 返回句柄（dict）
- 成功：`{success, subagent_id, message, executor_session_id, workflow_id, result_type, result_text}`。
- 暂停：`{success:false, paused:true, subagent_id, message, executor_session_id, result_type, reason}`。
- 归属/状态拒绝：`{success:false, error, subagent_id?}`。
