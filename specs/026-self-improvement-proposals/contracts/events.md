# Contract: 公开 UI 事件 — 改进提案

> 必须先在 `src/desktop_api/ui_events.py` 的 UI Event Registry 注册 type + payload allowlist，前端按 type 消费；不得用内部 blinker 事件名做展示决策（009 反模式）。缺口/会话不匹配走 `backend.resync_required` 拉权威快照。

## 新增公开事件 type

### `improvement_proposal.changed`

提案生成或状态变更时发出，驱动 BrainScreen 复盘视图刷新提案列表。

**Scope**: 全局（提案非会话私有；BrainScreen 是管理界面）。

**Payload allowlist**（只含安全展示字段，无 secret、无 provider 原始错误）：
```json
{
  "proposalId": "prop_xxx",
  "sourceReviewId": "rev_xxx",
  "status": "pending_review | approved | in_progress | done | failed | rejected",
  "severity": "high | med | low | null",
  "changeType": "created | approved | rejected | in_progress | done | failed"
}
```

**触发点**：
- 提案生成（D1）→ `changeType=created`。
- 用户批准/拒绝 → `approved` / `rejected`。
- 桥接建图成功 → `in_progress`。
- 回报终态（D3）→ `done` / `failed`。

**前端消费**：收到事件后按 `status` 局部更新对应提案卡；列表缺口或拿不到上下文时发 `backend.resync_required` → 重新 `GET /api/improvement-proposals` 拉权威快照。

## 不引入的事件

- 不复用任务协作的 `task.*` 公开事件来驱动提案展示（提案的真相在提案表，不从任务图事件派生——避免跨契约耦合）。
- 实施任务图自身在任务协作视图的既有事件不变；提案视图只消费 `improvement_proposal.changed`。

## 后端内部通知

- 后端内部跨模块通知（如桥接通知轮询 job）优先 `src/utils/events.py` blinker；仅面向前端的状态变更经 UI Event Registry typed envelope 出口。
