# 契约：start_external_coding_session 工具参数

**Date**: 2026-07-21
**契约类型**: Agent 工具参数 schema（本项目对模型暴露的调用接口）

本特性唯一的对外契约变更。其余 10 个外部 coding 工具的参数契约不变。

---

## 变更摘要

| 参数 | 变更前 | 变更后 |
|---|---|---|
| `targetWorktreePath` | 选填，说明为"可选目标 worktree 路径" | **必填**，说明改写为明确的填参约束 |
| 其余参数 | — | 不变 |

---

## 变更后的完整契约

**必填**：

| 参数 | 类型 | 说明要点 |
|---|---|---|
| `ownerType` | `"task"` \| `"workflow"` | 不变 |
| `ownerId` | string | 不变，不得为空 |
| `objective` | string | 不变，派给外部 coding agent 的目标 |
| `targetWorktreePath` | string | **新增必填**。要改动的目标仓库位置。说明中 MUST 写明：这是绝对路径；必须是一个可用的 git 仓库；不填将被拒绝；若目标就是 Exemplar 自身仓库，同样需要显式写出 |

**选填**（均不变）：

| 参数 | 类型 |
|---|---|
| `context` | string |
| `toolPreference` | `"auto"` \| `"claude_code"` \| `"codex_cli"` |
| `launchMode` | `"headless"` \| `"interactive"` |
| `targetBranch` | string |

---

## 填参约束的表达位置

按项目既有惯例，填参与调用约束 MUST 写在工具 schema 的 description 中，
MUST NOT 写入主助理系统提示词——主助理不持有该工具，提示词层面的约束对实际调用方
（执行专员）无效，且会稀释提示词的路由级原则。

---

## 契约破坏性说明

这是一次**破坏性变更**：变更后，未提供 `targetWorktreePath` 的调用一律失败。

判定为可直接生效、无需过渡期，依据：

- 项目当前单用户、未发布，无外部脚本、第三方集成或历史调用方依赖此契约
- `external_coding_sessions` 表 0 行——从未有过成功调用，不存在需要延续的调用习惯
- 过渡期方案（保留选填 + 告警）对 LLM 调用方无实际约束力，风险窗口继续敞开，与本特性目的相悖

---

## 相关但不变的契约

以下同样面向模型暴露，本特性不改动，列出以界定范围：

- `analyze_external_coding_merge` / `merge_external_coding_session` 的
  `targetWorktreePath` —— **本就已是必填**，无需变更
- `decide_external_coding_plan`、`resume_external_coding_session`、
  `inspect_external_coding_session`、`abandon_external_coding_session`、
  `escalate_to_user_external_coding_session`、`record_external_coding_review_outcome`、
  `plan_external_coding_rollback`、`confirm_external_coding_rollback`
- 能力组合"外部 Coding"的成员构成与只读、已发布属性
