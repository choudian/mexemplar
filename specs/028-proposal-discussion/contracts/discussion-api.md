# API Contract: 提案讨论入口

**Endpoint**: `POST /api/improvement-proposals/{proposal_id}/discussion`

## 语义

获取或创建该提案的讨论会话（幂等）。首次调用创建普通助理会话并以提案上下文开场；绑定存在且会话可用时直接返回既有会话；绑定死亡时自愈重建。

## Request

- Path: `proposal_id`（必填）
- Body: 无
- Auth: 既有 `X-Mexemplar-Session` runtime token（与所有 sidecar API 一致）

## Response 200

```json
{
  "sessionId": "ast_xxxxxxxxxxxx",
  "created": true
}
```

- `sessionId`: 绑定的助理会话 id，可直接用于 `assistantStore.selectSession`。
- `created`: 本次调用是否新建了会话（复用/自愈重建=true 仅在真的新建时）。

## Errors

- 404: 提案不存在 → `{ "detail": "提案不存在" }`
- 503: 提案功能未启用（沿用既有 proposals router 的启用检查语义）

## 行为约束（供 contract 测试断言）

1. 同一提案连续调用两次：第二次返回相同 `sessionId` 且 `created=false`；全库会话数只 +1。
2. 首次调用后，该会话消息里存在一条 assistant 角色开场消息，内容包含提案的 what/evidence/suggestion/severity 与已填 userSupplement；终态提案还包含实施结果/失败原因。
3. 调用不改变提案 `status`，不创建 worktree / task graph（零副作用，FR-425）。
4. 绑定会话被删除后调用：返回新 `sessionId`（≠ 旧值）且 `created=true`，提案绑定更新。
5. 开场消息落库不触发任何模型调用（无 AgentLoop 运行痕迹）。
