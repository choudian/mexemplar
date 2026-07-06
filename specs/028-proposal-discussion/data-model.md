# Data Model: 提案审批"讨论"功能

**Date**: 2026-07-06 | **Plan**: [plan.md](plan.md)

## ImprovementProposal（修改既有实体）

`src/data/models_sqlite.py` 的 `ImprovementProposal`（表 `improvement_proposals`）：

| 字段 | 类型 | 约束 | 说明 |
|------|------|------|------|
| `discussion_session_id` | TEXT | nullable，默认 NULL | 绑定的讨论会话 id（`sessions.session_id`）；一个提案至多一个；可因原会话删除而被替换 |

- 不加外键约束（项目既有惯例：跨表引用不建 FK，靠业务层自愈；`sessions` 行可被删除，FK 会阻塞既有删除路径）。
- 不加唯一索引（同一会话理论上不会被两个提案绑定——创建即绑定，无复用入口）。

### Migration v25

- upgrade：`ALTER TABLE improvement_proposals ADD COLUMN discussion_session_id TEXT`（可空，无回填）。
- downgrade：按项目既有 downgrade 惯例重建表去列或 `ALTER TABLE ... DROP COLUMN`（对齐 v21-v24 的写法）。
- 兼容性：旧行全 NULL = 从未讨论过，语义自洽；无数据回填需求。

## Repository 变更

`ImprovementProposalRepository` 新增：

- `bind_discussion_session(proposal_id, session_id) -> bool`：条件 UPDATE `WHERE id=:pid AND discussion_session_id IS NULL`，返回 rowcount==1。用于首次绑定（幂等竞态判定）。
- `rebind_discussion_session(proposal_id, session_id) -> None`：无条件 UPDATE，仅在旧绑定已确认死亡（D5）后由 service 调用。
- 既有 `get_by_id` / `_to_dict` 输出补 `discussion_session_id`。

## 状态与转换

提案状态机不变（pending_review → approved/rejected → in_progress → done/failed）。讨论绑定与状态机正交：任意状态都可绑定/使用讨论会话（FR-420）；绑定变更不触发状态转换（FR-425）。

## DTO 变更

- `ProposalDto`（desktop_api schemas）：增可空 `discussionSessionId`。
- 新增 `ProposalDiscussionResponse`：`{ sessionId: string, created: boolean }`（created 标识本次是否新建，前端可选用于提示）。
