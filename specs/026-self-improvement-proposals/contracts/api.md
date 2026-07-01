# Contract: Typed API — 改进提案

> 沿用项目约定：DTO 字段 camelCase；只读 GET + 副作用 POST；router 只做 DTO/auth/错误映射，业务进 `ProposalService`；不泄漏 secret/原始错误。
> 路由可放在既有 `routers/execution_reviews.py` 旁或新建 `routers/proposals.py`（实现期定，契约不变）。

## GET `/api/improvement-proposals`

列出改进提案（供 BrainScreen 复盘视图）。

**Query**: `status?` (pending_review|approved|in_progress|done|failed|rejected)，`limit?`（默认 50，1..200）

**200 Response**:
```json
{
  "proposals": [
    {
      "id": "prop_xxx",
      "sourceReviewId": "rev_xxx",
      "findingIndex": 0,
      "status": "pending_review",
      "severity": "med",
      "findingType": "效率",
      "what": "助理重复抓取同一数据",
      "evidence": "step 3/7 与 step 9 重复调用同一查询",
      "suggestion": "提示先查缓存再抓取",
      "userSupplement": null,
      "graphId": null,
      "worktreeAvailable": false,
      "branchName": null,
      "resultTestsPassed": null,
      "resultSummary": null,
      "error": null,
      "createdAt": "2026-06-28T...",
      "decidedAt": null,
      "completedAt": null
    }
  ]
}
```
- 不返回本地绝对 `worktreePath` 或其他内部字段；不返回 `error` 的原始 provider 文本（只安全摘要）。公开 DTO 使用 `worktreeAvailable` 表示是否保留可检视 worktree。

## POST `/api/improvement-proposals/{id}/approve`

批准一条提案并附补料；触发桥接（异步）。

**Body**: `{ "supplement": "改造方向/注意事项，可空字符串" }`

**200 Response**: `{ "accepted": true, "id": "prop_xxx", "status": "approved" }`

**语义**：
- CAS `pending_review → approved`；非 `pending_review` → `{ "accepted": false, "reason": "not_pending" }`（幂等，不重复触发）。
- 批准后桥接异步进行（建 worktree + 建图 + 踢调度器）；API 立即返回 `approved`，后续状态经 UI 事件推送。
- 批准前不产生任何副作用（FR-008）。

## POST `/api/improvement-proposals/{id}/reject`

拒绝提案（或弃用已失败提案，触发 worktree 清理）。

**200 Response**: `{ "accepted": true, "id": "prop_xxx", "status": "rejected" }`
- CAS `pending_review|failed → rejected`；其它状态 → `{ "accepted": false, "reason": "invalid_transition" }`。
- 拒绝不触发任何实施动作；对 `failed` 提案的拒绝会先清理 worktree，清理失败返回 `{ "accepted": false, "reason": "cleanup_failed" }` 且提案保持 `failed` 以便重试。

## 错误与安全

- 所有端点带 `X-Mexemplar-Session` runtime token（既有 sidecar 约定）。
- 失败响应只含安全分类/消息，不含 provider 原始错误、endpoint、密钥、stack trace。
- 不新增 secret 字段；不在响应回显配置值。
