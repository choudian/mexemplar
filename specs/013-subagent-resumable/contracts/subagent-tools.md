# Phase 1 Contracts: 主代理子代理调度工具

本特性的"对外接口"是主代理（Assistant）可见的 3 个工具。无 HTTP / 前端契约（纯 Agent 工具层）。

## delegate_to_subagent（修改：返回契约扩展）

- **输入**（既有）：`task_description`（必填）、`execution_context`、`tool_whitelist`。
- **输出新增/变更**：
  - 始终返回 `subagent_id`（= executor session id），供后续 inspect/continue。
  - 子代理被迫中断时返回 `{success:false, paused:true, subagent_id, reason, result_type:"paused", message}`，而非失败。
- **契约不变量**：暂停不算失败；`reason` 至少区分"迭代超限"与"调用失败"两类。

## inspect_subagent（新增，只读，零模型调用）

- **输入**：`subagent_id`（必填）。
- **输出**：`{success, subagent_id, status, assistant_turns, tool_call_counts, last_output}`；非己出/不存在 → `{success:false, error}`。
- **契约不变量**：
  - MUST NOT 触发任何模型调用（纯 DB 读 + 内存聚合）——测试以 `chat_with_tools.assert_not_called()` 断言。
  - MUST 经归属校验拒绝非当前主代理派出的会话，不泄露其内容。

## continue_subagent（新增，唤回续跑）

- **输入**：`subagent_id`（必填）、`instruction`（可选追加指令）、`extra_iterations`（默认 20）。
- **输出**：
  - 完成：`{success:true, subagent_id, result_text, result_type:"completed", message}`。
  - 再次中断：`{success:false, paused:true, subagent_id, reason, result_type:"paused", message}`（可重复唤回，FR-009）。
  - 拒绝：非己出/不存在/仍在运行 → `{success:false, error, subagent_id?}`。
- **契约不变量**：
  - 基于持久化历史恢复，跨进程重启可用（FR-007）；无需重述原始任务。
  - 适用于被迫暂停的与已正常完成的子代理（FR-006）；`instruction` 进入既有上下文继续，不丢历史。
  - `status == "active"` 时拒绝并发唤回。
  - 用主代理当前可用工具池重建（不强制还原原始白名单）。

## Prompt 契约（assistant_prompt.py）

system prompt MUST 含"子代理暂停（可唤回）时的处理"引导：账单/网络类等外部恢复后再 continue；迭代超限先 inspect 诊断，复杂则 continue、走弯路则重新 delegate；已完成未达标可带 instruction 返工（FR-010）。
