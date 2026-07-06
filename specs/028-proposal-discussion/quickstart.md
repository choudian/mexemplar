# Quickstart: 提案审批"讨论"功能

## 用户视角 30 秒走查

1. 打开 Brain Management（`/brain`）→ 复盘视图 → 改进提案 tab。
2. 选中一条提案，详情区论证链（问题→证据→建议）下方有"讨论"按钮。
3. 点击 → 跳到 AI Assistant 屏，当前会话开场是一条包含该提案完整分析的助理消息。
4. 正常提问讨论；回到 `/brain` 提案页，批准/拒绝行为不变。
5. 重启应用，再点同一提案的"继续讨论" → 回到同一会话，历史完整。

## 开发验证命令

```powershell
# 后端：service 幂等/自愈/序列化 + endpoint contract + 守卫
uv run pytest tests/business/self_improvement tests/desktop_api/test_proposals_api.py tests/guardrails/test_proposal_guardrails.py -q

# 前端：讨论按钮 + store action
cd frontend; npx vitest run tests/unit/proposal-review.test.tsx

# migration 往返
uv run pytest tests/data -k migration -q
```

## 关键实现锚点

- 序列化单一来源：`src/business/self_improvement/proposal_context.py`
- 会话创建/绑定：`proposal_service.get_or_create_discussion_session`
- 绑定 CAS：`ImprovementProposalRepository.bind_discussion_session`（条件 UPDATE + rowcount）
- 前端入口：BrainScreen 详情区按钮 → `brainStore.openProposalDiscussion` → assistant 路由 + `selectSession`
