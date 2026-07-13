# Implementation Plan: 外部 Coding 内置技能组合与专员授权

**Branch**: `prepare-github` | **Date**: 2026-07-13 | **Spec**: [spec.md](./spec.md)

## Summary

在既有 Skill Composition 深模块内增加一个无数据库主记录的系统内置组合，由组合服务统一投影给 API、目录和运行时；专员配置增加版本化 `composition_ids`；委派编排从持久专员配置推导授权，并在工具注册边界同时校验执行型固定专员与持久 Task。前端只展示一个组合勾选项，并保留内置只读语义。

## Technical Context

- **Backend**: Python、SQLAlchemy、FastAPI/Pydantic、现有 AgentLoop/DynamicToolManager。
- **Frontend**: React 18、TypeScript、Zustand、Vitest/RTL。
- **Storage**: SQLite v29 为专员当前记录与版本记录增加 JSON 文本 `composition_ids`；内置组合定义不落普通组合表。
- **Events/Secrets**: 复用现有 `tools.changed`/组合刷新行为；0 新公开 UI event，0 新 secret。

## Constitution Check

| Principle | Result |
|---|---|
| 分层与事件 | PASS：UI → typed API → Specialist/Composition Service → Repository；工具构造留在 orchestration/agent 层。 |
| 数据边界 | PASS：专员配置只经 Repository；无业务 SQL；迁移仅负责 schema。 |
| 配置与密钥 | PASS：不新增配置或密钥，继续复用 030 的统一配置。 |
| 可验证交付 | PASS：覆盖组合域、迁移、Repository、Service、API、运行时授权矩阵和 React 交互。 |
| 活文档与规格 | PASS（带时序例外）：运行结构与硬约束更新活文档；spec/plan/tasks 在提交前补齐。 |

## Design Decisions

1. **内置组合是组合服务的只读投影**：固定定义不写入可编辑 `skill_compositions` 表，避免用户更新和成员漂移；调用方仍只依赖 `SkillCompositionService`。
2. **授权与激活分离**：专员持久配置决定“能否看到组合”，DynamicToolManager 决定“何时激活组合与成员”。目录快照不是授权事实。
3. **成员 ToolDefinition 延迟构造**：只有正式 Task 的固定 executor 专员通过门卫后才调用 030 的 factory，并绑定 parent session 与 task ID。
4. **普通组合维持父会话能力交集**：用户组合成员仍要通过父会话授权重校验；内置 external coding 使用专员组合配置和正式 Task 专用边界。
5. **陈旧配置可移除不可新增**：前端隐藏不可分配组合，但若已分配则继续展示；后端保存时按当前状态 fail-closed。

## Affected Areas

- `src/business/services/skill_composition/`: 内置定义、只读服务投影、API DTO。
- `src/business/brain/`、`src/data/`: 专员组合校验、版本化持久化、v29 migration。
- `src/business/orchestration/agent/`、`src/business/agents/tools/`: 授权推导、目录过滤、范围激活与工具门卫。
- `src/desktop_api/`: 专员/组合 typed contracts。
- `frontend/`: 组合只读呈现与专员单项配置。
- `tests/`: domain/data/API/integration/guardrail/frontend 回归。
- `docs/ARCHITECTURE.md`、`docs/PROJECT_CONSTRAINTS.md`: 活文档同步。

## Verification Plan

1. 后端定向测试覆盖组合、专员、迁移、API、编排和 external coding 全链路。
2. 前端完整 Vitest、lint 与 production build。
3. Python changed-file flake8/格式检查与 `git diff --check`。
4. 尝试完整后端测试；若受运行时长限制，交付时明确记录并以相关套件结果为证据。
