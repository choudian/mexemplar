# Implementation Plan: 提案审批"讨论"功能（chat about this）

**Branch**: `028-proposal-discussion` | **Date**: 2026-07-06 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/028-proposal-discussion/spec.md`

## Summary

在 BrainScreen 提案详情区加"讨论"入口：首次点击创建一个真实普通助理会话，以该提案 finding 的 markdown 上下文作为会话内首条 assistant 消息开场（零模型调用），并把 `discussion_session_id` 持久绑定到 `improvement_proposals`（v25 migration，条件 UPDATE 保证幂等）；再次点击回到同一会话，绑定会话被删后自愈重建。前端经 brainStore 调新 endpoint 拿到 sessionId 后跳转 Assistant 屏并 `selectSession`。全程 0 新公开 UI 事件、0 新工具、0 prompt 变更，审批语义不动。

## Technical Context

**Language/Version**: Python 3.11+（运行时 3.12）后端；TypeScript + React 18 前端
**Primary Dependencies**: FastAPI sidecar、SQLAlchemy、Zustand、既有 ChatService / ImprovementProposalRepository / assistantStore
**Storage**: SQLite `improvement_proposals` 表新增可空 `discussion_session_id` 列（v25 migration + downgrade）
**Testing**: pytest（tests/business、tests/desktop_api、tests/guardrails）+ Vitest（frontend/tests/unit）
**Target Platform**: Windows 桌面（Tauri 2 shell + Python sidecar）
**Project Type**: desktop-app（前后端分离 + sidecar bridge）
**Performance Goals**: 点击"讨论"到会话可输入 < 1s（本地 DB 读写 + 一次消息插入，无模型调用）
**Constraints**: 审批前零副作用红线（026 CC 系列）；0 新公开事件；单用户单进程桌面语义
**Scale/Scope**: 1 列 migration、1 个 service 方法、1 个 endpoint、1 个共享序列化 helper、前端 1 按钮 + 1 store action + 跳转

## Constitution Check

| Principle | Gate question | Evidence |
|-----------|---------------|----------|
| I. Layered Boundaries & Event Coordination | 保持 UI→business→data？ | UI（BrainScreen/brainStore）→ typed API（proposals router）→ proposal_service → ChatService/Repository。0 新 blinker 事件、0 新公开 UI 事件（CC-162）。 |
| II. Data Boundary & Persistence Discipline | Repository 边界与迁移兼容？ | 仅 SQLite：v25 migration 加可空列（downgrade 删列）；绑定读写走 `ImprovementProposalRepository` 新方法（条件 UPDATE + rowcount，遵循项目 CAS 惯例）；不碰 DuckDB。 |
| III. Unified Config & Secret Handling | 配置/密钥？ | N/A：0 新配置键、0 secret。 |
| IV. Verifiable Delivery | 自动化覆盖？ | 单测：get_or_create 幂等/自愈/开场消息内容/终态上下文含实施结果；API contract 测试：discussion endpoint；守卫：讨论路径零实施副作用（不建 worktree/graph、不改状态）+ 序列化单一来源；前端单测：讨论按钮 + store action + 跳转。 |
| V. Living Docs & Spec-Driven Delivery | 活文档？ | 根 AGENTS/CLAUDE/GEMINI Recent Changes 增 028 条目；docs/ARCHITECTURE.md 自我改进小节补讨论会话一段；src/ 与 frontend/ 模块 AI 文档各补一条约束；spec/plan/tasks 在 specs/028-*。 |

**Gate 结论**: 全部通过，无需 Complexity Tracking 例外。

## Project Structure

### Documentation (this feature)

```text
specs/028-proposal-discussion/
├── plan.md              # 本文件
├── research.md          # Phase 0
├── data-model.md        # Phase 1
├── quickstart.md        # Phase 1
├── contracts/
│   └── discussion-api.md
└── tasks.md             # /speckit-tasks 产出
```

### Source Code (repository root)

```text
src/
├── business/
│   ├── self_improvement/
│   │   ├── proposal_context.py      # 新增：finding 上下文序列化单一来源
│   │   ├── proposal_service.py      # 修改：get_or_create_discussion_session
│   │   └── proposal_bridge.py       # 修改：节点 description 改用 proposal_context
│   └── services/chat_service.py     # 不改签名；讨论会话经其 create_session 创建
├── data/
│   ├── migrations.py                # 修改：migrate_to_v25（加列 + downgrade）
│   ├── models_sqlite.py             # 修改：ImprovementProposal.discussion_session_id
│   └── repos/improvement_proposal_repository.py  # 修改：bind_discussion_session（条件 UPDATE）
└── desktop_api/
    ├── routers/proposals.py         # 修改：POST /{id}/discussion
    └── schemas.py                   # 修改：ProposalDto 增 discussionSessionId；DiscussionResponse

frontend/src/
├── api/brain.ts（或提案 API 所在文件）  # 修改：openProposalDiscussion typed client
├── state/brainStore.ts              # 修改：openProposalDiscussion action
├── state/assistantStore.ts          # 不改：复用 selectSession
├── app/routes.tsx                   # 不改：复用 assistant 路由
└── screens/BrainScreen/BrainScreen.tsx  # 修改：详情区"讨论"按钮 + 跳转

tests/
├── business/self_improvement/       # service 幂等/自愈/序列化单测
├── desktop_api/                     # discussion endpoint contract 测试
└── guardrails/                      # 零副作用 + 序列化单一来源守卫

frontend/tests/unit/                 # proposal-review.test.tsx 增讨论按钮用例
```

**Structure Decision**: 全部落在既有模块内；唯一新文件是 `proposal_context.py`（序列化单一来源，被 bridge 与 discussion 两处消费）。

## Complexity Tracking

无例外。
