# Quickstart: 自我改进提案（B 阶段）端到端验证

> 目标：证明「复盘 → 提案 → 批准+补料 → 隔离 worktree 改源码 + 测试 → 回报」整条闭环真生效（不是"编译通过"），并守住安全边界。对应 spec SC-001..SC-006。

## 前置

- A 阶段执行复盘已启用（`self_improvement.execution_review.enabled`）。
- 新功能开关 `self_improvement.proposals.enabled` 打开。
- sidecar 已启动（调度器单例随之装配）。

## 路径 1：提案产生 + 人工把关（SC-001）

1. 触发一次会让审查员产出 `worth_changing=true` finding 的助理任务（或直接构造一条含此 finding 的复盘记录）。
2. 等 brain worker 跑完 `_run_execution_review`。
3. 打开 BrainScreen 执行复盘视图 → 断言：出现对应提案，状态 `pending_review`，展示 what/evidence/suggestion/severity。
4. 在提案上填补料文本、点批准 → 断言：状态变 `approved`，补料被持久化（刷新/重连不丢）。
5. 另起一条提案点拒绝 → 断言：状态 `rejected`，无任何实施动作发生。
6. 让 worker 再处理同一复盘 → 断言：不出现重复提案（幂等，UNIQUE 生效）。

## 路径 2：批准 → 自动实施 → 回报（SC-002 / SC-006）

1. 批准一条提案。
2. 断言（桥接）：创建了独立 git worktree（`.worktrees/improvement/<proposalId>`）+ 分支；提案转 `in_progress`，后端内部记录 `graphId/worktree_path/branch_name`，公开 DTO 只暴露 `worktreeAvailable`。
3. 断言（命门回归）：实施任务图被真实推进——规划专员拆解、执行体在 worktree 内改源码并跑测试（不是"建了没人跑"）。
4. 等图终态 + 轮询回报 → 断言：提案转 `done`（或 `failed`），并写回 `branchName + resultTestsPassed + resultSummary`，BrainScreen 可见。
5. 断言：全程除"批准"外无人工介入。

## 路径 3：隔离与可回滚（SC-003 / SC-004）

1. 实施进行期间断言：正在运行的应用所用源码文件未被改动（改动只在 worktree 内）。
2. 门卫断言：执行体尝试改 worktree 外路径 / DB 文件 / 外部副作用 → 全部 fail-closed 被拒。
3. 对一条 `failed` 提案点拒绝 → 断言：worktree 被清理，主工作区无残留；若清理失败，提案保持 `failed` 并可重试。
4. 对一条已合并/已弃的改造：删分支 / 弃 worktree 即干净回滚，未触碰数据库或外部资源。

## 路径 4：A 不被改（SC-005 回归）

- 断言：`execution_reviews` 表结构、审查员产出 findings 结构、`/api/execution-reviews` 行为、advisory 语义在本特性前后一致。

## 自动化测试落点

- 单元：`tests/business/self_improvement/test_proposal_service.py`（生成幂等 + 状态机 CAS）。
- 桥接：`tests/business/self_improvement/test_proposal_bridge.py`（批准→建图→踢图→回报，mock scheduler）。
- worktree/边界：`tests/business/self_improvement/test_proposal_workspace.py` + `tests/guardrails/test_proposal_guardrails.py`（source-only 硬边界、A 只读回归、无残留）。
- 数据：`tests/data/test_improvement_proposal_migration.py` / `test_improvement_proposal_repository.py`。
- API/事件：`tests/desktop_api/test_proposals_endpoint.py`。
- 端到端闭环（命门回归）：`tests/integration/test_proposal_closed_loop.py`。
- 前端：`frontend/tests/unit/proposal-review.test.tsx`。
