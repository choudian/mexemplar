# Quickstart: 子代理可唤回机制

## 验证命令

```powershell
# 行为契约测试（本特性）
uv run python -m pytest tests/business/agents/test_subagent_resumable.py -q

# 回归：非临时 Agent 中断处理零变化（FR-011 / SC-006）
uv run python -m pytest `
  tests/test_agent_loop_retry.py `
  tests/integration/test_agent_loop_multi_tool_calls.py `
  tests/integration/test_agent_orchestrator_architecture.py `
  tests/integration/test_assistant_dispatch.py `
  tests/business/agents/test_assistant_dispatch_tools.py -q

# 语法/格式
uv run python -m py_compile src/business/agents/agent_loop.py src/business/orchestration/agent/orchestrator.py
```

预期：契约测试 14 passed，回归 69 passed。

## 行为演练（对照验收场景）

1. **迭代超限唤回（US1）**：委派一个会顶到迭代上限的任务 → 委派返回 `paused:true` + `subagent_id` + `reason="已达迭代上限（N 轮）"`，会话 `suspended`，历史保留 → `continue_subagent(subagent_id)` 从断点续跑至完成。
2. **失败保活待恢复（US2）**：制造持续 LLM 调用失败（无效凭据/断网）→ 返回 `paused:true` + `reason` 标调用失败类 → 恢复条件后（含进程重启）`continue_subagent(subagent_id)` 成功续跑。
3. **诊断概览（US3）**：`inspect_subagent(subagent_id)` 返回轮数/工具调用次数/最后产出/状态，且**无任何模型调用**；据此选择 continue 或重新 delegate。
4. **返工（US4）**：对已完成子代理 `continue_subagent(subagent_id, instruction="补齐剩下的…")` 在原有上下文基础上继续。
5. **归属拒绝（SC-007）**：对非己出 `subagent_id` 的 inspect/continue 一律 `success:false`，不泄露内容。

## 收尾记录

- research R3 已处理：`_is_recoverable_llm_failure` 按异常类型/消息区分可恢复（配额/限流/网络）与不可恢复失败，仅前者转 PAUSED，后者仍走 ERROR；契约测试 `test_llm_failure_nonrecoverable_still_error_when_resumable` 覆盖。
